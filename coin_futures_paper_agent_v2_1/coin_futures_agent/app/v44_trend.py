"""V4.4 point-in-time trend, market regime and adaptive entry research.

All methods are deterministic heuristics, NOT calibrated probabilities. Only
completed candles available at asof_ms are consumed; no live/paper orders.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import pandas as pd


def clamp(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def closed_frame(frame: pd.DataFrame | None, asof_ms: int | None = None) -> pd.DataFrame:
    """Exclude the potentially forming last candle, and any later than asof.

    Scanner includes the current forming candle. A replay may supply a frame
    containing only completed candles and pass asof_ms to avoid dropping one.
    """
    if frame is None or frame.empty:
        return pd.DataFrame()
    if asof_ms is not None and "close_time" in frame:
        result = frame.loc[pd.to_numeric(frame["close_time"], errors="coerce") <= asof_ms]
        return result.copy()
    return frame.iloc[:-1].copy()


def assess_trend(frames: dict[str, pd.DataFrame], *, asof_ms: int | None = None,
                 market_features: dict[str, Any] | None = None) -> dict[str, Any]:
    views = {tf: closed_frame(frames.get(tf), asof_ms) for tf in ("15m", "1h", "4h")}
    if any(len(x) < 55 for x in views.values()):
        return {
            "direction": "NEUTRAL", "phase": "UNCERTAIN", "strength": 0.0,
            "continuation": 0.0, "exhaustion": 0.0, "reversal": 0.0,
            "data_quality": "INSUFFICIENT", "reason_codes": ["NOT_ENOUGH_CLOSED_BARS"],
            "asof_ms": asof_ms,
        }
    a, h, d = (views[k] for k in ("15m", "1h", "4h"))
    last15, last1, last4 = (x.iloc[-1] for x in (a, h, d))
    necessary = ("close", "ema20", "ema50", "rsi14", "atr14", "vol_ratio")
    if any(not math.isfinite(_finite(row.get(k), float("nan"))) for row in (last15, last1, last4) for k in necessary):
        return {
            "direction": "NEUTRAL", "phase": "UNCERTAIN", "strength": 0.0,
            "continuation": 0.0, "exhaustion": 0.0, "reversal": 0.0,
            "data_quality": "INVALID_INDICATORS", "reason_codes": ["NAN_INDICATORS"],
            "asof_ms": asof_ms,
        }
    adx = _finite(last1.get("adx14"))
    sign1 = 1 if last1["close"] > last1["ema20"] > last1["ema50"] else -1 if last1["close"] < last1["ema20"] < last1["ema50"] else 0
    sign4 = 1 if last4["close"] > last4["ema20"] > last4["ema50"] else -1 if last4["close"] < last4["ema20"] < last4["ema50"] else 0
    direction = "BULLISH" if sign1 == sign4 == 1 else "BEARISH" if sign1 == sign4 == -1 else "NEUTRAL"
    sign = 1 if direction == "BULLISH" else -1 if direction == "BEARISH" else 0
    atr = max(_finite(last15["atr14"]), 1e-12)
    close = _finite(last15["close"])
    ema = _finite(last15["ema20"])
    distance = sign * (close - ema) / atr
    m15 = _finite(last15["rsi14"])
    m1 = _finite(last1["rsi14"])
    slope = sign * (_finite(h.iloc[-1]["ema20"]) - _finite(h.iloc[-5]["ema20"])) / max(_finite(last1["atr14"]), 1e-12)
    recent, previous = a.iloc[-10:], a.iloc[-20:-10]
    hh = _finite(recent["high"].max()) > _finite(previous["high"].max())
    hl = _finite(recent["low"].min()) > _finite(previous["low"].min())
    ll = _finite(recent["low"].min()) < _finite(previous["low"].min())
    lh = _finite(recent["high"].max()) < _finite(previous["high"].max())
    structure_ok = (hh and hl) if sign == 1 else (ll and lh) if sign == -1 else False
    volume = _finite(last15["vol_ratio"], 1.0)
    directional_rsi = m15 if sign == 1 else (100 - m15) if sign == -1 else 50
    strength = clamp(
        25 + (23 if sign else 0) + (15 if structure_ok else 0)
        + min(17, max(0, slope) * 14) + max(-15, min(18, (directional_rsi - 50) * 0.6))
        + min(12, max(0, adx - 17) * 0.7)
    )
    exhaustion = clamp(
        max(0, distance - 1) * 25
        + max(0, directional_rsi - 70) * 2.2
        + (20 if slope < 0 else 0)
        + (13 if volume < 0.7 else 0)
        + (18 if sign and not structure_ok else 0)
    )
    features = market_features or {}
    oi_raw=features.get("oi_change_pct")
    funding_raw=features.get("funding_rate")
    oi_known=oi_raw is not None and math.isfinite(_finite(oi_raw,float("nan")))
    funding_known=funding_raw is not None and math.isfinite(_finite(funding_raw,float("nan")))
    oi_confirmed=bool(sign and oi_known and _finite(oi_raw)>=1.0)
    funding_crowded=bool(sign and funding_known and sign*_finite(funding_raw)>0.0008)
    if funding_crowded:
        exhaustion=clamp(exhaustion+10)
    if oi_confirmed:
        strength=clamp(strength+5)
    continuation = clamp(
        25 + (25 if sign else 0) + (18 if structure_ok else 0)
        + (12 if slope > 0.05 else -8)
        + (10 if volume >= 1.0 else -5)
        + (10 if adx >= 23 else -5)
        + (6 if oi_confirmed else 0)
        - exhaustion * 0.45
    )
    reversal = clamp((35 if sign and not structure_ok else 0)
                     + (35 if sign and distance < -0.9 else 0)
                     + (20 if slope < -0.2 else 0))
    broke = bool(
        (sign == 1 and close > _finite(last15.get("prev_20_high"), float("inf")))
        or (sign == -1 and close < _finite(last15.get("prev_20_low"), float("-inf")))
    )
    if not sign:
        phase = "RANGING" if abs(_finite(last1["ema20"]) - _finite(last1["ema50"])) < _finite(last1["atr14"]) * 0.6 else "UNCERTAIN"
    elif reversal >= 65:
        phase = "REVERSAL_RISK"
    elif exhaustion >= 65:
        phase = "EXHAUSTED"
    elif broke and volume >= 1.05:
        phase = "BREAKOUT"
    elif distance < 0.1:
        phase = "PULLBACK"
    elif structure_ok:
        phase = "CONTINUATION"
    else:
        phase = "WEAKENING"
    reasons = [
        "1H_4H_ALIGNED" if sign else "HIGHER_TIMEFRAMES_CONFLICT",
        "STRUCTURE_CONFIRMED" if structure_ok else "STRUCTURE_NOT_CONFIRMED",
        "EMA20_SLOPE_POSITIVE" if slope > 0 else "EMA20_SLOPE_WEAK",
    ]
    if exhaustion >= 65:
        reasons.append("EXHAUSTION_WARNING")
    if oi_confirmed:
        reasons.append("OPEN_INTEREST_CONFIRMS_DIRECTION")
    if funding_crowded:
        reasons.append("CROWDED_DIRECTIONAL_FUNDING")
    return {
        "direction": direction, "phase": phase, "strength": strength,
        "continuation": continuation, "exhaustion": exhaustion, "reversal": reversal,
        "data_quality": "VALID", "reason_codes": reasons,
        "ema_distance_atr_signed": round(distance, 3),
        "rsi_15m": round(m15, 2), "adx_1h": round(adx,2), "volume_ratio_15m": round(volume, 3),
        "asof_ms": asof_ms if asof_ms is not None else int(last15.get("close_time", 0)),
        "confidence_status": "UNCALIBRATED_HEURISTIC",
        "oi_data_status": "AVAILABLE" if oi_known else "NOT_AVAILABLE",
        "oi_change_pct":round(_finite(oi_raw),3) if oi_known else None,
        "funding_data_status": "AVAILABLE" if funding_known else "NOT_AVAILABLE",
        "funding_rate":round(_finite(funding_raw),8) if funding_known else None,
    }


def market_context(scan: dict[str, Any], guardian: dict[str, Any] | None = None,
                   articles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Market breadth of SCANNED universe, not the full crypto market."""
    rows = list(scan.get("all") or [])
    from .config import settings
    threshold=float(settings.score_threshold)
    longs = sum(1 for x in rows if _finite(x.get("long_score")) >= threshold)
    shorts = sum(1 for x in rows if _finite(x.get("short_score")) >= threshold)
    count = len(rows)
    breadth_up=sum(1 for x in rows if x.get("trend_1h_long") is True)
    breadth_down=sum(1 for x in rows if x.get("trend_1h_short") is True)
    funded=[abs(_finite(r.get("funding_rate"))) for r in rows if r.get("funding_rate") is not None]
    relative=sorted([{"symbol":r.get("symbol"),"relative_strength_1h_pct":
                    round(_finite(r.get("relative_strength_1h_pct")),3)}
                     for r in rows if r.get("relative_strength_1h_pct") is not None],
                    key=lambda x:x["relative_strength_1h_pct"],reverse=True)
    broad_bias = round((longs - shorts) / count, 3) if count else 0.0
    # News category tags are a contextual grouping only. They are NOT evidence
    # of sector fund flows; assets without a verified category remain UNCLASSIFIED.
    sector_assets: dict[str,set[str]] = {}
    scanned_bases={str(x.get("symbol") or "").removesuffix("USDT") for x in rows}
    for article in articles or []:
        category=str(article.get("category") or "").upper()
        if category not in {"AI","DEFI","RWA","L1","L2","MEME","GAMING","NFT","INFRA","SECURITY"}:
            continue
        for sym in article.get("symbols") or []:
            base=str(sym).upper().removesuffix("USDT")
            if base in scanned_bases:
                sector_assets.setdefault(category,set()).add(base)
    sector_digest=[]
    for category,assets in sorted(sector_assets.items()):
        members=[r for r in rows if str(r.get("symbol") or "").removesuffix("USDT") in assets]
        strengths=[_finite(r.get("relative_strength_1h_pct")) for r in members
                   if r.get("relative_strength_1h_pct") is not None]
        sector_digest.append({"category":category,"coin_count":len(assets),
                              "coins":sorted(assets)[:15],
                              "mean_relative_strength_1h_pct":
                                  round(sum(strengths)/len(strengths),3) if strengths else None})
    g = (guardian or {}).get("state") or {}
    mode = str(g.get("mode") or "NORMAL").upper()
    if not count:
        risk = "RESTRICTED"
        reasons = ["MARKET_DATA_MISSING"]
    elif mode == "EVENT_LOCK":
        risk = "EVENT_LOCK"
        reasons = ["NEWS_EVENT_LOCK"]
    elif mode not in ("NORMAL", "DISABLED"):
        risk = "CAUTION"
        reasons = ["NEWS_GUARDIAN_CAUTION"]
    elif abs(broad_bias) > 0.55 and scan.get("btc_regime") == "NEUTRAL":
        risk = "CAUTION"
        reasons = ["BTC_BREADTH_DIVERGENCE"]
    else:
        risk = "NORMAL"
        reasons = []
    return {
        "risk_state": risk, "btc_regime": scan.get("btc_regime", "NEUTRAL"),
        "scanned": count, "long_signals": longs, "short_signals": shorts,
        "breadth_bias": broad_bias, "breadth_1h_up": breadth_up,
        "breadth_1h_down": breadth_down,
        "relative_strength_top": relative[:5],
        "relative_strength_bottom": relative[-5:] if relative else [],
        "news_tagged_sector_research": sector_digest,
        "sector_method": "VERIFIED_NEWS_CATEGORY_ONLY_NOT_FUND_FLOWS",
        "mean_abs_funding_rate": round(sum(funded)/len(funded),7) if funded else None,
        "universe_scope": "SCANNED_TOP_N",
        "guardian_scope": g.get("scope", "MARKET"),
        "guardian_symbols": g.get("symbols") or [],
        "guardian_mode": mode,
        "guardian_event_key": g.get("event_key"),
        "guardian_event_id": g.get("event_id"),
        "guardian_published_or_detected_at": g.get("created_at"),
        "guardian_seen_at": g.get("updated_at"),
        "guardian_cooldown_until": g.get("cooldown_until"),
        "reason_codes": reasons,
        "asof": scan.get("created_at"),
    }


def entry_risk_block(context: dict[str, Any], symbol: str) -> str | None:
    risk = context.get("risk_state", "RESTRICTED")
    if risk == "RESTRICTED":
        return "MARKET_RESTRICTED"
    if risk != "EVENT_LOCK":
        return None
    scope = context.get("guardian_scope", "MARKET")
    symbols = {str(s).upper() for s in context.get("guardian_symbols", [])}
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return "EVENT_LOCK" if scope == "MARKET" or base in symbols else None


def select_entry(row: dict[str, Any], frame: pd.DataFrame,
                 trend: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Evaluate current completed 15m bar; never promise later entry fills."""
    symbol = str(row.get("symbol") or "")
    block = entry_risk_block(context, symbol)
    if block or trend.get("data_quality") != "VALID":
        return {"action": "NO_TRADE", "method": None, "reason": block or "INVALID_TREND_DATA", "scores": {}}
    direction = trend.get("direction")
    if direction not in ("BULLISH", "BEARISH") or trend.get("phase") in ("EXHAUSTED", "REVERSAL_RISK", "WEAKENING"):
        return {"action": "NO_TRADE", "method": None, "reason": "NO_CONFIRMED_HEALTHY_TREND", "scores": {}}
    side = "LONG" if direction == "BULLISH" else "SHORT"
    opposite_source = side != row.get("bias")
    if opposite_source and not (
        float(trend.get("strength") or 0) >= 75
        and float(trend.get("continuation") or 0) >= 70
        and float(trend.get("exhaustion") or 100) <= 45
        and trend.get("phase") in ("BREAKOUT","CONTINUATION","PULLBACK")
    ):
        return {"action": "NO_TRADE", "method": None,
                "reason": "OPPOSITE_TREND_NOT_INDEPENDENTLY_CONFIRMED", "scores": {}}
    bar = closed_frame(frame)
    if len(bar) < 25:
        return {"action": "NO_TRADE", "method": None, "reason": "INSUFFICIENT_15M", "scores": {}}
    last = bar.iloc[-1]
    close = _finite(last["close"])
    atr = _finite(last["atr14"])
    if close <= 0 or atr <= 0:
        return {"action": "NO_TRADE", "method": None, "reason": "INVALID_PRICE_ATR", "scores": {}}
    ema = _finite(last["ema20"])
    sign = 1 if side == "LONG" else -1
    dist = sign * (close - ema) / atr
    level = _finite(last["prev_20_high"] if sign == 1 else last["prev_20_low"])
    breakout = bool(sign * (close - level) > 0)
    retest = bool(
        sign * (close - level) >= 0
        and (last["low"] <= level + 0.15 * atr if sign == 1 else last["high"] >= level - 0.15 * atr)
    )
    rebound = (last["close"] > last["open"]) if sign == 1 else (last["close"] < last["open"])
    quality = _finite(trend.get("continuation"))
    strength = _finite(trend.get("strength"))
    volume = _finite(last.get("vol_ratio"), 1.0)
    scores = {
        "BREAKOUT": clamp(quality * 0.4 + strength * 0.25 + (25 if breakout else 0)
                          + (10 if volume >= 1.1 else 0) - max(0, dist - 1.3) * 24),
        "PULLBACK": clamp(quality * 0.35 + strength * 0.25 + (25 if 0 <= dist <= 0.8 else 0)
                          + (12 if rebound else 0) - max(0, dist - 1.2) * 20),
        "RETEST": clamp(quality * 0.35 + strength * 0.25 + (30 if retest else 0)
                        + (10 if rebound else 0) - max(0, dist - 1.5) * 20),
    }
    if opposite_source:
        scores={k:clamp(v-8) for k,v in scores.items()}
    eligible = {k: v for k, v in scores.items() if v >= (65 if opposite_source else 55)}
    if not eligible:
        return {"action": "NO_TRADE", "method": None, "reason": "METHOD_SCORES_LOW", "scores": scores}
    method = max(eligible, key=eligible.get)
    ready = ((method == "BREAKOUT" and breakout and volume >= 1.1 and 0 <= dist <= 1.5)
             or (method == "PULLBACK" and 0 <= dist <= 0.8 and rebound)
             or (method == "RETEST" and retest and rebound))
    if opposite_source:
        # A reverse entry requires its own closed-candle structure and volume;
        # it is not an automatic reversal of the source scanner signal.
        ready=bool(ready and scores[method]>=70 and volume>=1.1)
    if context.get("risk_state") == "CAUTION":
        # No fresh entry without stronger momentum and score confirmation.
        ready = bool(ready and scores[method] >= 72 and volume >= 1.1)
    if not ready and method == "BREAKOUT" and dist > 1.5:
        method = "RETEST"  # wait rather than chase an extended breakout
    low10, high10 = _finite(bar.tail(10)["low"].min()), _finite(bar.tail(10)["high"].max())
    stop = min(low10 - 0.15 * atr, close - 1.35 * atr) if sign == 1 else max(high10 + 0.15 * atr, close + 1.35 * atr)
    risk = abs(close - stop)
    stop_pct = 100 * risk / close
    if stop_pct < 0.35 or stop_pct > 3.50:
        return {"action": "NO_TRADE", "method": method, "reason": "STOP_DISTANCE_INVALID",
                "scores": scores, "stop_pct": round(stop_pct, 3)}
    return {
        "action": "ENTER" if ready else "WAIT",
        "method": method, "reason": ("CONFIRMED_" if ready else "CAUTION_WAIT_" if context.get("risk_state")=="CAUTION" else "PENDING_") + method,
        "scores": scores, "side": side, "price": close, "stop": stop,
        "target": close + sign * 2 * risk, "risk": risk,
        "trigger_level": level, "atr": atr, "stop_pct": round(stop_pct, 3),
        "source_side":row.get("bias"),
        "direction_source_relation":("TREND_CONFIRMED_OPPOSITE" if opposite_source else "ALIGNED"),
        "decision_candle_ms": int(last["close_time"]),
    }


def trend_exit_state(trend: dict[str, Any], side: str | None = None) -> str:
    """Conservative exit-policy input; not an instruction to trade."""
    if trend.get("data_quality") != "VALID":
        return "UNCERTAIN"
    opposite = "BEARISH" if side == "LONG" else "BULLISH" if side == "SHORT" else None
    if opposite and trend.get("direction") == opposite and trend.get("continuation",0)>=60:
        return "OPPOSITE_TREND"
    if trend.get("phase") == "REVERSAL_RISK":
        return "WEAKENING"
    if trend.get("phase") in ("WEAKENING", "EXHAUSTED") or trend.get("exhaustion", 0) >= 60:
        return "WEAKENING"
    return "HEALTHY" if trend.get("continuation", 0) >= 55 else "UNCERTAIN"
