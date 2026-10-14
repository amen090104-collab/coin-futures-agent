"""Reverse Research Lab: deterministic, closed-candle, forward-only Shadow fills.

Pure functions, no Binance orders or paper-account mutations. Decisions made
after a candle close only affect the NEXT candle. Entry slippage, exit slippage
and taker fees are all charged against original per-unit risk. Funding and
liquidation are NOT modeled; no paper-real-money suitability claims.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

VARIANTS = (
    "REV_A_FIXED_2R",
    "REV_B_CONFIRMED_2R",
    "REV_C_PARTIAL_RUNNER",
    "REV_D_ADAPTIVE",
)
TERMINAL = frozenset({"CLOSED", "EXPIRED", "CENSORED"})
MINUTE_MS = 60_000


class CandleGap(ValueError):
    """Historical candles must be processed without skipping a minute."""


def _finite(n: Any) -> float:
    f = float(n)
    if not math.isfinite(f):
        raise ValueError("Non-finite market value")
    return f


def sign(side: str) -> int:
    if side not in ("LONG", "SHORT"):
        raise ValueError("Invalid reverse side")
    return 1 if side == "LONG" else -1


def _complete(case: dict, state: dict, status: str, reason: str, at_ms: int) -> dict:
    case["status"] = status
    case["reason"] = reason
    case["closed_at_ms"] = at_ms
    if status == "CLOSED":
        case["net_r"] = round(float(case["realized_r"]) - float(case["fees_r"]), 8)
    else:
        case["net_r"] = None  # censored/expired can never appear as a realized loss or win
    state["final_reason"] = reason
    return case


def _save(case: dict, state: dict, bar: dict) -> dict:
    case["cursor_ms"] = int(bar["open_time"]) + MINUTE_MS
    case["state_json"] = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    return case


def advance_reverse(
    original: dict[str, Any],
    bar: dict[str, Any],
    *,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    max_hold_hours: float = 36.0,
) -> dict[str, Any]:
    """Consume EXACTLY the next fully closed 1m bar.

    A and C enter at the same first future minute's open; B waits for two
    positive one-minute closes and enters at the next open; D uses a frozen
    score-conditioned entry/exit rule. STOP wins OHLC ambiguity.
    """
    row = dict(original)
    state = (dict(row.get("state")) if isinstance(row.get("state"), dict)
             else json.loads(row.get("state_json") or "{}"))
    status = str(row["status"])
    if status in TERMINAL:
        return row
    bar_ms = int(bar["open_time"])
    if bar_ms != int(row["cursor_ms"]):
        raise CandleGap(f"Expected {row['cursor_ms']} but received {bar_ms}")
    end_ms = int(bar["close_time"])
    if end_ms != bar_ms + MINUTE_MS - 1:
        raise ValueError("Invalid minute candle timestamp")
    o, h, l, c = [_finite(bar[k]) for k in ("open", "high", "low", "close")]
    if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
        raise ValueError("Invalid OHLC")
    d = sign(str(row["side"]))
    risk = _finite(row["risk_distance"])
    if risk <= 0:
        raise ValueError("Invalid initial risk")
    fee = _finite(fee_bps)/10000
    slip = _finite(slippage_bps)/10000
    if fee < 0 or slip < 0 or slip >= .1:
        raise ValueError("Invalid execution costs")
    variant = str(row["variant"])
    if variant not in VARIANTS:
        raise ValueError("Unknown research variant")

    if status == "WAIT_CONFIRM":
        if bar_ms > int(row["expires_at_ms"]):
            return _save(_complete(row, state, "EXPIRED", "CONFIRMATION_TIMEOUT", end_ms), state, bar)
        # Prospective reversal confirmation: 2 consecutive completed 1m
        # bullish/bearish bodies with close beyond the frozen signal level.
        threshold = _finite(row["signal_price"])
        favorable = d*(c-o) >= max(risk*0.035, o*0.00005)
        beyond = d*(c-threshold) > 0
        state["confirmation_streak"] = int(state.get("confirmation_streak", 0))+1 if favorable and beyond else 0
        state["confirmed_at_ms"] = end_ms if state["confirmation_streak"] >= (
            1 if variant == "REV_D_ADAPTIVE" else 2
        ) else None
        if state["confirmed_at_ms"] is not None:
            row["status"] = "WAIT_ENTRY"  # FILL ONLY FROM THE NEXT 1m OPEN
            state["entry_confirmation"] = "CLOSED_1M_MOMENTUM"
        return _save(row, state, bar)

    if status == "WAIT_ENTRY":
        if bar_ms > int(row["expires_at_ms"]) and row.get("entered_at_ms") is None:
            return _save(_complete(row, state, "EXPIRED", "ENTRY_TTL_EXPIRED", end_ms), state, bar)
        entry = o*(1 + d*slip)  # adverse entry execution
        if entry - d*risk <= 0:
            return _save(_complete(row, state, "CENSORED", "INVALID_STOP_GEOMETRY", end_ms), state, bar)
        row.update(
            status="OPEN", entered_at_ms=bar_ms, entry=entry,
            stop=entry-d*risk, effective_stop=entry-d*risk,
            target=entry+d*2*risk, remaining=1.0, realized_r=0.0,
            fees_r=fee*entry/risk, high_water=0.0,
            adverse_water=0.0,
        )
        state["entry_raw_price"] = o
        state["entry_fee_r"] = round(row["fees_r"], 8)
        state["funding_modeled"] = False
        state["fills"] = []
        status = "OPEN"

    if status != "OPEN":
        raise ValueError("Unexpected reverse research state")

    entry = _finite(row["entry"])
    stop = _finite(row["effective_stop"])
    target = _finite(row["target"])
    remaining = _finite(row["remaining"])
    realized = _finite(row["realized_r"])
    fees_r = _finite(row["fees_r"])
    prev_high = _finite(row.get("high_water") or 0)
    high_r = (h-entry)/risk if d == 1 else (entry-l)/risk
    low_r = (l-entry)/risk if d == 1 else (entry-h)/risk
    highwater = max(prev_high, high_r)
    row["high_water"] = highwater
    row["adverse_water"] = min(_finite(row.get("adverse_water") or 0), low_r)

    def fill(raw_px: float, qty: float, reason: str) -> None:
        nonlocal realized, fees_r, remaining
        qty = min(remaining, max(0.0, qty))
        if qty <= 1e-10:
            return
        exit_px = raw_px*(1-d*slip)
        gross_r = d*(exit_px-entry)/risk*qty
        charged_fee_r = fee*exit_px/risk*qty
        realized += gross_r
        fees_r += charged_fee_r
        remaining = max(0.0, remaining-qty)
        state.setdefault("fills", []).append({
            "at_ms": end_ms, "quantity_fraction": round(qty, 8),
            "reason": reason, "price": round(exit_px, 12),
            "gross_r": round(gross_r, 8), "fee_r": round(charged_fee_r, 8),
        })
        row["reason"] = reason

    hit_stop = l <= stop if d == 1 else h >= stop
    # Stops triggered at the minute open suffer opening gaps.
    gap_beyond_stop = o <= stop if d == 1 else o >= stop
    queued_exit = state.pop("exit_next_open", None)
    hit_fixed = h >= target if d == 1 else l <= target

    if gap_beyond_stop:
        fill(o, remaining, "STOP_GAP")
    elif queued_exit:
        fill(o, remaining, str(queued_exit))
    elif hit_stop:
        raw = min(o, stop) if d == 1 else max(o, stop)
        fill(raw, remaining, "STOP_FIRST" if hit_fixed else "STOP")
    elif variant in ("REV_A_FIXED_2R", "REV_B_CONFIRMED_2R"):
        if hit_fixed:
            fill(target, remaining, "FIXED_TP_2R")
    else:
        partial_done = bool(state.get("partial_done"))
        # Frozen D policy chooses a smaller early partial for stronger source
        # signals. Never optimize these levels from outcomes on the fly.
        score = _finite(row["score"])
        level = 1.5 if variant == "REV_D_ADAPTIVE" and score >= 85 else 1.0
        portion = .40 if variant == "REV_D_ADAPTIVE" and score >= 85 else .50
        partial_px = entry + d*level*risk
        crossed = h >= partial_px if d == 1 else l <= partial_px
        if not partial_done and crossed:
            fill(partial_px, portion, f"PARTIAL_{level}R")
            state["partial_done"] = True

    row["realized_r"] = round(realized, 10)
    row["fees_r"] = round(fees_r, 10)
    row["remaining"] = round(remaining, 10)
    if remaining <= 1e-10:
        _complete(row, state, "CLOSED", row.get("reason") or "CLOSED", end_ms)
        return _save(row, state, bar)

    if variant in ("REV_C_PARTIAL_RUNNER", "REV_D_ADAPTIVE") and state.get("partial_done"):
        # Monotonic trailing only AFTER the completed candle; effective next bar.
        distance = (0.85 if variant == "REV_D_ADAPTIVE" and _finite(row["score"]) >= 85
                    else 1.05)
        lock = max(0.0, highwater-distance)
        proposed = entry+d*lock*risk
        row["effective_stop"] = max(stop, proposed) if d == 1 else min(stop, proposed)
        if variant == "REV_D_ADAPTIVE":
            # A sharp retreat is noticed at this close and executed NEXT open.
            close_r = d*(c-entry)/risk
            if highwater >= 1.5 and highwater-close_r >= 0.9:
                state["exit_next_open"] = "ADAPTIVE_TREND_FADE"

    if end_ms - int(row["entered_at_ms"]) >= max_hold_hours*3600000:
        state["exit_next_open"] = "MAX_HOLD"
    return _save(row, state, bar)


def describe_variant(key: str) -> str:
    return {
        "REV_A_FIXED_2R": "Reverse immediately, hard 2R control",
        "REV_B_CONFIRMED_2R": "Wait two future 1m confirming closes, then fixed 2R",
        "REV_C_PARTIAL_RUNNER": "Immediate Reverse, 50% at +1R, uncapped runner",
        "REV_D_ADAPTIVE": "High score immediate; otherwise confirm; adaptive partial/runner",
    }[key]
