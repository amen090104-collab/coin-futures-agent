"""Point-in-time Reverse Pattern Learning v1 (research only).

Training labels are net R from already CLOSED REV-A Shadow cohorts. Historical
Paper Case C is used only for descriptive diagnostics, never fitted into the
prospective policy. The output index is NOT a win probability or live approval.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any

VERSION = "reverse-pattern.1"
VARIANT = "REV_E_PATTERN_2R"
MIN_SIDE_CLOSED = 30
MIN_DAYS = 7
MIN_EFFECTIVE = 20.0
MIN_FEATURES = 4
MIN_EXPECTED_R = 0.15
MIN_INDEX = 55.0
PRIOR_MASS = 20.0
RECENT_TRAINING_LIMIT = 200

# Distance scales are frozen research hypotheses, NOT optimized coefficients.
SCALES = {
    "source_score": 15.0,
    "rsi_1h": 25.0,
    "distance_ema20_atr": 2.0,
    "volume_ratio_1h": 1.5,
    "oi_change_pct": 5.0,
    "atr_pct_1h": 4.0,
    "relative_strength_1h_pct": 3.0,
}
CATEGORIES = ("btc_regime", "trend_4h_reverse", "trend_1h_reverse")


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def compact_features(row: dict, *, base_score: float,
                     source_side: str, btc_regime: str) -> dict:
    """Freeze only small, signal-time market features already in the scan.

    Existing scan trend flags refer to fully closed 1h and 4h bars.
    Missing values remain None; never turn missing OI into neutral evidence.
    """
    reverse = "SHORT" if source_side == "LONG" else "LONG"
    result = {key: finite(base_score if key == "source_score" else row.get(key))
              for key in SCALES}
    result["btc_regime"] = btc_regime if btc_regime in (
        "BULLISH", "BEARISH", "NEUTRAL") else None
    for interval in ("4h", "1h"):
        value = row.get(f"trend_{interval}_{reverse.lower()}")
        result[f"trend_{interval}_reverse"] = value if isinstance(value, bool) else None
    return result


def similarity(a: dict, b: dict) -> tuple[float, int]:
    """Untrained similarity, with fixed distances; missing is not a match."""
    matches = []
    for key, scale in SCALES.items():
        x, y = finite(a.get(key)), finite(b.get(key))
        if x is not None and y is not None:
            matches.append(max(0.0, 1.0 - abs(x - y) / scale))
    for key in CATEGORIES:
        x, y = a.get(key), b.get(key)
        if x is not None and y is not None:
            matches.append(1.0 if x == y else 0.0)
    if not matches:
        return 0.0, 0
    return sum(matches) / len(matches), len(matches)


def score_candidate(features: dict, history: list[dict], *,
                    source_side: str, observed_at_ms: int) -> dict:
    """Score from outcomes available strictly BEFORE observed_at_ms.

    history rows carry signal-time feature snapshots and unmodified net_r,
    observed_at_ms, closed_at_ms, source_side and cohort_id. No future labels,
    OPEN, EXPIRED or CENSORED trades may contribute.
    """
    result = {
        "model_version": VERSION, "status": "INSUFFICIENT_SIDE_HISTORY",
        "eligible": False, "score": None, "expected_r": None,
        "training_n": 0, "training_days": 0, "matched_n": 0,
        "effective_n": 0.0, "minimum_closed": MIN_SIDE_CLOSED,
        "minimum_days": MIN_DAYS,
    }
    if source_side not in ("LONG", "SHORT"):
        result["status"] = "INVALID_SOURCE_SIDE"
        return result
    if sum(finite(features.get(k)) is not None for k in SCALES) < MIN_FEATURES - 1:
        result["status"] = "INSUFFICIENT_FEATURES"
        return result

    valid = []
    seen = set()
    # Freeze latest past outcomes, never the candidate cohort or future closures.
    for row in sorted(history, key=lambda x: int(x.get("observed_at_ms") or 0),
                      reverse=True):
        cid = str(row.get("cohort_id") or "")
        observed = int(row.get("observed_at_ms") or 0)
        closed = int(row.get("closed_at_ms") or 0)
        outcome = finite(row.get("net_r"))
        if (row.get("source_side") != source_side or not cid or cid in seen
                or outcome is None or not (0 < observed < closed < observed_at_ms)):
            continue
        seen.add(cid)
        valid.append(row)
        if len(valid) >= RECENT_TRAINING_LIMIT:
            break
    result["training_n"] = len(valid)
    if not valid:
        return result
    result["training_days"] = len({
        datetime.fromtimestamp(int(x["observed_at_ms"]) / 1000, timezone.utc).date()
        for x in valid
    })
    base_mean = mean(max(-3.0, min(3.0, float(x["net_r"]))) for x in valid)
    neighbors = []
    for row in valid:
        strength, fields = similarity(features, row.get("features") or {})
        if fields >= MIN_FEATURES and strength >= 0.45:
            neighbors.append((strength ** 3, float(row["net_r"]), row))
    result["matched_n"] = len(neighbors)
    total = sum(w for w, _, _ in neighbors)
    squared = sum(w * w for w, _, _ in neighbors)
    effective = total * total / squared if squared else 0.0
    result["effective_n"] = round(effective, 2)
    if total:
        # Cap extreme outcomes for estimation only, not for profit accounting.
        weighted = sum(w * max(-3.0, min(3.0, r)) for w, r, _ in neighbors)
        ev = (weighted + PRIOR_MASS * base_mean) / (total + PRIOR_MASS)
        result["expected_r"] = round(ev, 4)
        result["score"] = round(max(0, min(100, 50 + 35 * ev)), 1)
    if result["training_n"] < MIN_SIDE_CLOSED:
        result["status"] = "INSUFFICIENT_SIDE_HISTORY"
    elif result["training_days"] < MIN_DAYS:
        result["status"] = "INSUFFICIENT_INDEPENDENT_DAYS"
    elif effective < MIN_EFFECTIVE:
        result["status"] = "INSUFFICIENT_MATCHED_SAMPLES"
    elif (result["expected_r"] is not None
          and result["expected_r"] >= MIN_EXPECTED_R
          and result["score"] >= MIN_INDEX):
        result["status"] = "RESEARCH_CANDIDATE"
        result["eligible"] = True
    else:
        result["status"] = "NO_ESTIMATED_EDGE"
    return result


def _describe_trades(trades: list[dict]) -> dict:
    nums = [finite(x.get("r_multiple")) for x in trades]
    nums = [x for x in nums if x is not None]
    return {"n": len(nums), "wins": sum(x > 0 for x in nums),
            "win_rate_pct": round(100 * sum(x > 0 for x in nums) / len(nums), 2)
            if nums else None,
            "ev_r": round(mean(nums), 4) if nums else None}


def paper_signal_diagnostics(trades: list[dict]) -> dict:
    """Descriptive code presence/absence and time split, NOT a trained model."""
    valid = []
    for t in trades:
        if t.get("side") not in ("LONG", "SHORT") or finite(t.get("r_multiple")) is None:
            continue
        ctx = t.get("entry_context") or {}
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except (ValueError, TypeError):
                ctx = {}
        if not isinstance(ctx, dict):
            ctx = {}
        thesis = ctx.get("entry_thesis") or {}
        raw_codes = thesis.get("reason_codes") if isinstance(thesis, dict) else []
        row = dict(t)
        row["codes"] = set(raw_codes or [])
        row["opened_day"] = str(t.get("opened_at") or "")[:10]
        valid.append(row)
    result = {"status": "HISTORICAL_PAPER_DISCOVERY_ONLY",
              "trades": len(valid), "by_reverse_side": {},
              "reason_code_differences": {},
              "warning": "Descriptive, confounded by day/regime/news and overlap; not OOS or causal."}
    if not valid:
        return result
    latest = max(x["opened_day"] for x in valid)
    for side in ("LONG", "SHORT"):
        selected = [x for x in valid if x["side"] == side]
        dayset = sorted({x["opened_day"] for x in selected if x["opened_day"]})
        cutoff = dayset[-4] if len(dayset) >= 4 else dayset[0] if dayset else latest
        early = [x for x in selected if x["opened_day"] < cutoff]
        recent = [x for x in selected if x["opened_day"] >= cutoff]
        result["by_reverse_side"][side] = {
            "all": _describe_trades(selected),
            "earlier": _describe_trades(early),
            "latest_four_signal_days": _describe_trades(recent),
            "recent_cutoff_day": cutoff,
            "news_risk_exits": sum(x.get("exit_reason") == "NEWS_RISK_EXIT" for x in selected),
        }
        codes = sorted({c for x in selected for c in x["codes"]})
        comparisons = []
        for code in codes:
            a = [x for x in selected if code in x["codes"]]
            b = [x for x in selected if code not in x["codes"]]
            if len(a) < 8 or len(b) < 8:
                continue
            sa, sb = _describe_trades(a), _describe_trades(b)
            comparisons.append({"source_reason_code": code,
                                "present": sa, "absent": sb,
                                "ev_difference_r": round(sa["ev_r"] - sb["ev_r"], 4)})
        result["reason_code_differences"][side] = sorted(
            comparisons, key=lambda x: abs(x["ev_difference_r"]), reverse=True)[:8]
    return result
