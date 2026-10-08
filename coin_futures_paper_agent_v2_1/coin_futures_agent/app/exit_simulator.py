"""Offline-only 1m OHLC counterfactual exit research.

No orders, no strategy mutation, no intrabar lookahead. When a 1m bar
contains both stop and target, stop wins. New stops only activate on the
next bar from already-observed MFE. Incomplete paths are CENSORED, not wins.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .binance import BinanceClient
from .chart_overlays import time_ms
from .config import settings
from .trade_intelligence import get_battle_trade

VARIANTS = {
    "FIXED_RR1": {"label": "Fixed TP 1R / original SL", "rr": 1.0, "mode": "FIXED"},
    "FIXED_RR2": {"label": "Fixed TP 2R / original SL", "rr": 2.0, "mode": "FIXED"},
    "BREAKEVEN_0_8R": {"label": "TP 2R + BE after 0.8R", "rr": 2.0, "mode": "BE"},
    "TRAIL_AFTER_1R": {"label": "TP 2R + trail after 1R", "rr": 2.0, "mode": "TRAIL"},
    "PARTIAL_1R_TRAIL": {"label": "50% at 1R; runner to 2R / trailing", "rr": 2.0, "mode": "PARTIAL"},
}


def _execution_price(raw: float, side: str) -> float:
    bps = float(settings.slippage_bps) / 10_000
    return raw * (1 - bps if side == "LONG" else 1 + bps)


def _close_leg(state: dict[str, Any], side: str, raw: float, fraction: float, reason: str) -> None:
    remaining = float(state["remaining_qty"])
    quantity = min(remaining, fraction * float(state["original_qty"]))
    if quantity <= 0:
        return
    exit_price = _execution_price(raw, side)
    entry = float(state["entry"])
    pnl = ((exit_price - entry) if side == "LONG" else (entry - exit_price)) * quantity
    fee = exit_price * quantity * float(settings.taker_fee_bps) / 10_000
    state["gross"] += pnl
    state["fees"] += fee
    state["remaining_qty"] -= quantity
    state["fills"].append(
        {"reason": reason, "raw_price": round(raw, 8), "fill_price": round(exit_price, 8),
         "quantity": quantity, "gross_pnl": round(pnl, 6), "exit_fee": round(fee, 6)}
    )


def _setup(trade: dict[str, Any], key: str) -> dict[str, Any]:
    spec = VARIANTS[key]
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss"])
    side = str(trade["side"])
    unit_risk = abs(entry - stop)
    direction = 1 if side == "LONG" else -1
    quantity = float(trade["quantity"])
    return {
        "variant": key, "label": spec["label"], "mode": spec["mode"],
        "entry": entry, "stop": stop, "target": entry + direction * unit_risk * spec["rr"],
        "initial_risk": unit_risk, "original_qty": quantity, "remaining_qty": quantity,
        "gross": 0.0, "fees": entry * quantity * float(settings.taker_fee_bps) / 10_000,
        "favorable": entry, "adverse": entry, "fills": [], "tp1_filled": False,
        "exit_reason": None, "exit_time": None,
    }


def _adverse_stop_fill(side: str, candle_open: float, effective_stop: float) -> float:
    """If price gaps through stop, do not pretend fill at the better stop."""
    return min(candle_open, effective_stop) if side == "LONG" else max(candle_open, effective_stop)


def simulate_exit_variants(
    trade: dict[str, Any],
    candles: list[dict[str, Any]],
    *,
    max_hold_hours: float | None = None,
    require_contiguous: bool = True,
) -> dict[str, Any]:
    side = str(trade["side"]).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    entry = float(trade["entry_price"])
    risk = abs(entry - float(trade["stop_loss"]))
    qty = float(trade["quantity"])
    if entry <= 0 or risk <= 0 or qty <= 0:
        raise ValueError("entry, risk and quantity must be positive")

    opened_ms = time_ms(trade["opened_at"])
    horizon_ms = opened_ms + int(
        float(max_hold_hours if max_hold_hours is not None else settings.max_hold_hours) * 3_600_000
    )
    bars = sorted(
        [x for x in candles if opened_ms <= int(x["open_time"]) <= horizon_ms],
        key=lambda x: int(x["open_time"]),
    )
    warnings: list[str] = []
    if not bars:
        warnings.append("No complete post-entry 1m candles. Cannot compare strategies.")
    if len(bars) > 1:
        gaps = sum(
            int(bars[i]["open_time"]) - int(bars[i-1]["open_time"]) > 60_000
            for i in range(1, len(bars))
        )
        if gaps:
            warnings.append(f"{gaps} missing 1m intervals: comparisons are CENSORED.")
    else:
        gaps = 0
    scenarios = {key: _setup(trade, key) for key in VARIANTS}
    for row in bars:
        t_open = int(row["open_time"])
        open_px, hi, lo, last = map(float, (row["open"], row["high"], row["low"], row["close"]))
        close_time = int(row["close_time"])
        for key, state in scenarios.items():
            if state["exit_reason"] is not None:
                continue
            original_stop = float(state["stop"])
            target = float(state["target"])
            previous = float(state["favorable"])
            prior_mfe = (previous - entry) / risk if side == "LONG" else (entry - previous) / risk
            mode = state["mode"]
            effective = original_stop
            if mode in {"BE", "PARTIAL"} and prior_mfe >= 0.8:
                effective = max(original_stop, entry) if side == "LONG" else min(original_stop, entry)
            if mode in {"TRAIL", "PARTIAL"} and prior_mfe >= 1.0:
                locked = max(0.25, prior_mfe - 0.75)
                trail = entry + (1 if side == "LONG" else -1) * locked * risk
                effective = max(effective, trail) if side == "LONG" else min(effective, trail)
            state["favorable"] = max(previous, hi) if side == "LONG" else min(previous, lo)
            state["adverse"] = min(float(state["adverse"]), lo) if side == "LONG" else max(float(state["adverse"]), hi)
            stop_hit = lo <= effective if side == "LONG" else hi >= effective
            tp_hit = hi >= target if side == "LONG" else lo <= target
            tp1 = entry + (1 if side == "LONG" else -1) * risk
            tp1_hit = hi >= tp1 if side == "LONG" else lo <= tp1

            if stop_hit:
                raw = _adverse_stop_fill(side, open_px, effective)
                reason = "STOP_LOSS" if effective == original_stop else "BE_OR_TRAIL_STOP"
                _close_leg(state, side, raw, 1.0, reason)
                state["exit_reason"] = reason
            elif mode == "PARTIAL" and not state["tp1_filled"] and tp1_hit:
                # Conservative: fill TP1 only. No hypothetical TP2 on same bar.
                _close_leg(state, side, tp1, 0.5, "TAKE_PROFIT_1R_50PCT")
                state["tp1_filled"] = True
            elif tp_hit:
                _close_leg(state, side, target, 1.0, "TAKE_PROFIT")
                state["exit_reason"] = "TAKE_PROFIT"
            elif close_time >= horizon_ms:
                _close_leg(state, side, last, 1.0, "TIME_EXIT")
                state["exit_reason"] = "TIME_EXIT"

            if state["exit_reason"] is not None:
                state["exit_time"] = datetime.fromtimestamp(
                    close_time / 1000, timezone.utc
                ).isoformat()

    results: list[dict[str, Any]] = []
    # A missing interval makes the counterfactual path untrustworthy even
    # when an apparent target was later touched.
    for state in scenarios.values():
        resolved = bool(state["exit_reason"]) and (not gaps or not require_contiguous)
        if resolved:
            net = float(state["gross"]) - float(state["fees"])
            net_r = net / (risk * qty)
        else:
            net = None
            net_r = None
        last_px = float(bars[-1]["close"]) if bars else None
        results.append({
            "variant": state["variant"],
            "label": state["label"],
            "status": "RESOLVED" if resolved else "CENSORED",
            "exit_reason": state["exit_reason"] if resolved else None,
            "exit_time": state["exit_time"] if resolved else None,
            "net_pnl": round(net, 4) if net is not None else None,
            "r_multiple": round(net_r, 4) if net_r is not None else None,
            "partial_fill": bool(state["tp1_filled"]),
            "remaining_qty": round(state["remaining_qty"], 8),
            "fills": state["fills"],
            "last_observed_price": last_px,
        })
    actual = {
        "exit_reason": trade.get("exit_reason"),
        "net_pnl": trade.get("net_pnl"),
        "r_multiple": trade.get("r_multiple"),
    }
    return {
        "trade_id": trade.get("id"), "symbol": trade["symbol"],
        "initial_risk_per_unit": round(risk, 8),
        "observed_candles": len(bars),
        "horizon_hours": float(max_hold_hours if max_hold_hours is not None else settings.max_hold_hours),
        "actual": actual, "variants": results, "warnings": warnings,
        "method": (
            "Counterfactual research from post-entry closed 1m OHLC; original entry/size; "
            "conservative stop-first conflicts, next-candle stop activation, gaps and fees/"
            "slippage. No order placement. No future candles inform an earlier decision."
        ),
    }


async def simulate_trade_exit(trade_id: int) -> dict[str, Any]:
    trade = get_battle_trade(trade_id)
    if not trade:
        raise KeyError(trade_id)
    opened = time_ms(trade["opened_at"])
    until = opened + int(float(settings.max_hold_hours) * 3_600_000) + 60_000
    until = min(until, int(datetime.now(timezone.utc).timestamp() * 1000))
    client = BinanceClient()
    try:
        frame = await client.klines_1m_between(
            trade["symbol"], opened, until,
        )
    finally:
        await client.close()
    candles = [
        {
            "open_time": int(row["open_time"]), "close_time": int(row["close_time"]),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
        }
        for _, row in frame.iterrows()
        if int(row["close_time"]) <= until
    ]
    return simulate_exit_variants(trade, candles)
