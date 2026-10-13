"""Deterministic forward-only shadow fills and exits for V4.4.

OHLC ambiguity uses adverse-stop-first. Trend measured at candle close can
only change stops or queue an exit for a *later* candle. All values are in
units of original R per unit of initial position. Never touches paper trades.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from typing import Any

from .config import settings

SHADOW_VARIANTS = (
    "SOURCE_FIXED_2R", "ENTRY_ADAPTIVE", "EXIT_A_TREND", "EXIT_B_RUNNER"
)


def side_sign(side: str) -> int:
    if side == "LONG":
        return 1
    if side == "SHORT":
        return -1
    raise ValueError("invalid side")


def valid_trade(side: str, entry: float, stop: float, target: float) -> bool:
    if not all(math.isfinite(float(x)) and float(x) > 0 for x in (entry, stop, target)):
        return False
    d = side_sign(side)
    return d * (entry - stop) > 0 and d * (target - entry) > 0


def adverse_fill(raw: float, side: str) -> float:
    return float(raw) * (1 - side_sign(side) * float(settings.slippage_bps) / 10000)


def _trend_condition(trend: dict, side: str) -> str:
    if trend.get("data_quality") != "VALID":
        return "UNCERTAIN"
    opposite = ("BEARISH" if side == "LONG" else "BULLISH")
    if (trend.get("direction") == opposite
            and float(trend.get("continuation") or 0) >= 60):
        return "OPPOSITE_TREND"
    if trend.get("phase") in ("EXHAUSTED", "REVERSAL_RISK", "WEAKENING"):
        return "WEAKENING"
    if float(trend.get("exhaustion") or 0) >= 60:
        return "WEAKENING"
    return "HEALTHY" if float(trend.get("continuation") or 0) >= 55 else "UNCERTAIN"


def advance_shadow(pos: dict[str, Any], bar: dict[str, Any], trend: dict | None = None) -> dict:
    """Apply ONE completely observed 1m candle. The current candle's trend
    may queue the next-bar exit, never execute on this candle's close.
    """
    result = dict(pos)
    state = json.loads(result.get("state_json") or "{}") if "state_json" in result else dict(result.get("state") or {})
    side = str(pos["side"])
    d = side_sign(side)
    entry = float(pos["entry"])
    stop0 = float(pos["stop"])
    stop = float(pos["effective_stop"])
    target = float(pos["target"])
    risk = float(pos["risk"])
    if not valid_trade(side, entry, stop0, target) or risk <= 0 or not math.isfinite(risk):
        raise ValueError("invalid shadow geometry")
    o, hi, lo, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    if min(o, hi, lo, c) <= 0 or lo > min(o, c) or hi < max(o, c):
        raise ValueError("invalid OHLC")
    if int(bar["close_time"]) <= int(pos["last_candle_ms"]):
        return result  # idempotency by candle time

    remaining = float(pos["remaining"])
    gross = float(pos["realized_r"])
    fee_r = float(state.get("fees_r", 0))
    if not state.get("entry_fee_applied"):
        fee_r += float(settings.taker_fee_bps) / 10000 * entry / risk
        state["entry_fee_applied"] = True
    state.setdefault("fills", [])
    state.setdefault("favorable_r", 0.0)
    state.setdefault("adverse_r", 0.0)
    state.setdefault("opposite_confirmations", 0)
    sign_favor = (hi - entry) / risk if d == 1 else (entry - lo) / risk
    sign_adverse = (lo - entry) / risk if d == 1 else (entry - hi) / risk
    high_water_before = float(pos.get("high_water") or 0.0)
    high_water = max(high_water_before, sign_favor)
    state["favorable_r"] = max(float(state["favorable_r"]), sign_favor)
    state["adverse_r"] = min(float(state["adverse_r"]), sign_adverse)
    state["last_price"] = c
    state["last_trend"] = dict(trend or {})

    def fill(raw: float, qty: float, reason: str) -> None:
        nonlocal remaining, gross, fee_r
        qty = max(0.0, min(remaining, qty))
        if qty <= 0:
            return
        px = adverse_fill(raw, side)
        leg_r = d * (px - entry) / risk * qty
        charged = float(settings.taker_fee_bps) / 10000 * px / risk * qty
        gross += leg_r
        fee_r += charged
        remaining -= qty
        state["fills"].append({
            "at_ms": int(bar["close_time"]), "reason": reason,
            "fill_price": round(px, 10), "quantity_fraction": round(qty, 8),
            "gross_r": round(leg_r, 6), "fees_r": round(charged, 6),
        })
        result["reason"] = reason

    hit_stop = lo <= stop if d == 1 else hi >= stop
    hit_target = hi >= target if d == 1 else lo <= target
    queued = state.pop("queued_exit", None)
    if hit_stop:  # Conservative even if candle also crossed target.
        raw = min(o, stop) if d == 1 else max(o, stop)
        fill(raw, remaining, "STOP_FIRST" if hit_target else "STOP")
    elif queued:
        fill(o, remaining, str(queued))  # queue was created AFTER previous close
    elif pos["variant"] == "EXIT_B_RUNNER":
        tp1 = entry + d * risk
        hit_tp1 = hi >= tp1 if d == 1 else lo <= tp1
        if remaining > 0.99 and hit_tp1:
            fill(tp1, 0.5, "PARTIAL_TP_1R_50PCT")
        elif remaining < 0.99 and hit_target:
            state["runner_active"] = True
    elif hit_target:
        fill(target, remaining, "FIXED_TP_2R")

    if remaining > 1e-10:
        condition = _trend_condition(trend or {}, side)
        state["last_exit_condition"] = condition
        if pos["variant"] in ("EXIT_A_TREND", "EXIT_B_RUNNER"):
            # Restrict reversal exits to two consecutive *different*
            # completed 15m snapshots to prevent 1m duplicate confirmation.
            asof = (trend or {}).get("asof_ms")
            if asof != state.get("last_trend_asof_ms"):
                state["last_trend_asof_ms"] = asof
                state["opposite_confirmations"] = (
                    int(state["opposite_confirmations"]) + 1
                    if condition == "OPPOSITE_TREND" else 0
                )
            if int(state["opposite_confirmations"]) >= 2:
                state["queued_exit"] = "CONFIRMED_OPPOSITE_TREND"
            if condition == "WEAKENING" and high_water >= 0.75:
                lock = max(0.0, high_water - 0.85)
                proposed = entry + d * lock * risk
                result["effective_stop"] = (
                    max(stop, proposed) if d == 1 else min(stop, proposed)
                )
            if pos["variant"] == "EXIT_B_RUNNER" and state.get("runner_active"):
                # New stop is effective NEXT candle; monotonic, never widened.
                lock = max(0.4, high_water - 1.1)
                proposed = entry + d * lock * risk
                effective = float(result.get("effective_stop", stop))
                result["effective_stop"] = (
                    max(effective, proposed) if d == 1 else min(effective, proposed)
                )
        opened_ms = int(datetime.fromisoformat(str(pos["entered_at"]).replace("Z", "+00:00")).timestamp() * 1000)
        if int(bar["close_time"]) - opened_ms >= float(settings.max_hold_hours) * 3600000:
            state["queued_exit"] = "MAX_HOLD_EXIT"

    result["remaining"] = max(0.0, remaining)
    result["realized_r"] = round(gross, 8)
    result["high_water"] = round(high_water, 8)
    result["last_candle_ms"] = int(bar["close_time"])
    state["fees_r"] = round(fee_r, 8)
    result["state"] = state
    if remaining <= 1e-10:
        result["status"] = "CLOSED"
        result["remaining"] = 0.0
        result["closed_at"] = datetime.fromtimestamp(int(bar["close_time"])/1000,timezone.utc).isoformat()
        result["net_r"] = round(gross - fee_r, 8)
    return result
