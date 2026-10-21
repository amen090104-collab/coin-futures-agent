"""Explain research gates without changing strategy.build_trade_plan or its settings."""
from collections import Counter

from .config import settings
from .reverse_intelligence import CORE, FEATURES, finite, valid_features

TRADE_FILTERS = {"SCORE_BELOW_THRESHOLD", "VOLUME_BELOW_MIN", "ATR_ABOVE_MAX",
                 "STOP_TOO_NARROW", "STOP_TOO_WIDE"}


def inspect_plan(row, frame, regime, builder):
    """Call the original builder once. Diagnose None/exception from the same frozen inputs."""
    plan, error = None, None
    try:
        if frame is not None:
            plan = builder(row, frame, regime)
    except Exception as exc:
        # Store type only, never exception text (which can contain paths/credentials).
        error = type(exc).__name__
    context = {"score_threshold": settings.score_threshold,
               "min_volume_ratio": settings.min_volume_ratio, "max_atr_pct": settings.max_atr_pct,
               "min_stop_pct": settings.min_stop_pct, "max_stop_pct": settings.max_stop_pct}
    if plan is not None:
        risk = finite(abs(plan.entry-plan.stop_loss))
        reason = "PLAN_OK" if risk is not None and risk > 0 and finite(plan.signal_price) is not None else "PLAN_RISK_INVALID"
    else:
        reason = "MISSING_15M_FRAME" if frame is None else rejected_reason(row, frame, context)
        if reason == "PLAN_GATE_UNRECORDED" and error:
            reason = "BUILD_EXCEPTION"
    return plan, {"plan_gate_reason": reason, "plan_gate_context": context,
                  "build_exception_type": error}


def rejected_reason(row, frame, context):
    side = row.get("bias")
    if side not in {"LONG", "SHORT"}:
        return "INVALID_SOURCE_SIDE"
    score = finite(row.get("long_score" if side == "LONG" else "short_score"))
    volume, atr_pct = finite(row.get("volume_ratio_1h", 0)), finite(row.get("atr_pct_1h", 99))
    context.update(source_score=score, volume_ratio_1h=volume, atr_pct_1h=atr_pct)
    if score is None:
        return "SOURCE_INDICATOR_INVALID"
    if score < settings.score_threshold:
        return "SCORE_BELOW_THRESHOLD"
    if volume is not None and volume < settings.min_volume_ratio:
        return "VOLUME_BELOW_MIN"
    if atr_pct is not None and atr_pct > settings.max_atr_pct:
        return "ATR_ABOVE_MAX"
    if volume is None or atr_pct is None:
        return "SOURCE_INDICATOR_INVALID"
    if frame is None or getattr(frame, "empty", False):
        return "MISSING_15M_FRAME"
    try:
        closed = frame.iloc[:-1] if len(frame) > 1 else frame
        last = closed.iloc[-1]
        price, atr = finite(last["close"]), finite(last["atr14"])
        swing = finite(closed.tail(settings.structure_lookback)["low" if side == "LONG" else "high"].min()
                       if side == "LONG" else closed.tail(settings.structure_lookback)["high"].max())
        context.update(signal_price=price, atr_15m=atr, swing_level=swing)
        if price is None or price <= 0 or atr is None or swing is None:
            return "FRAME_INDICATOR_INVALID"
        if atr <= 0:
            return "ATR_NON_POSITIVE"
        risk = price-min(swing-.15*atr, price-settings.stop_atr_mult*atr) if side == "LONG" else max(swing+.15*atr, price+settings.stop_atr_mult*atr)-price
        if risk <= 0:
            return "PLAN_RISK_INVALID"
        stop_pct = risk/price*100
        context["stop_pct"] = stop_pct
        if stop_pct < settings.min_stop_pct:
            return "STOP_TOO_NARROW"
        if stop_pct > settings.max_stop_pct:
            return "STOP_TOO_WIDE"
    except (ValueError, TypeError, IndexError, KeyError, AttributeError, OverflowError):
        return "FRAME_INDICATOR_INVALID"
    return "PLAN_GATE_UNRECORDED"


def eligibility(row):
    """Legacy rows cannot recover a lost frame/filter reason using present-day settings."""
    quality = row.get("quality", {})
    features_ok = valid_features(row.get("features", {}))
    missing = [k for k in CORE if finite(row.get("features", {}).get(k)) is None]
    timestamps_ok = bool(quality.get("timestamps_valid") and quality.get("source_signal_time_valid"))
    plan_ok = quality.get("plan_gate_reason") == "PLAN_OK" if "plan_gate_reason" in quality else bool(
        row.get("quality_ok") or finite(row.get("signal_price")) is not None and (finite(row.get("risk_distance")) or 0) > 0)
    reason = quality.get("plan_gate_reason") or ("PLAN_OK" if plan_ok else "LEGACY_PLAN_REASON_UNRECORDED")
    status = "ELIGIBLE" if features_ok and timestamps_ok and plan_ok else (
        "MISSING_FEATURE" if not features_ok else "TIMESTAMP_INVALID" if not timestamps_ok else
        "SKIPPED_BY_TRADE_FILTER" if reason in TRADE_FILTERS else "MISSING_TRADE_PLAN")
    return {"status": status, "plan_gate_reason": reason, "plan_missing": not plan_ok,
            "feature_missing": not features_ok, "timestamp_invalid": not timestamps_ok,
            "missing_core": missing, "invalid_feature_values": not features_ok and not missing,
            "timestamp_reasons": (["FEATURE_PROVENANCE_TIME_INVALID"] if not quality.get("timestamps_valid") else [])+
                                 (["SOURCE_SIGNAL_TIME_INVALID"] if not quality.get("source_signal_time_valid") else []),
            "observation_eligible": features_ok and timestamps_ok,
            "paired_policy_eligible": features_ok and timestamps_ok and plan_ok and bool(row.get("quality_ok"))}


def gate_counts(rows):
    def count(group):
        states = [eligibility(r) for r in group]
        return {"records": len(group), "quality_ok": sum(bool(r.get("quality_ok")) for r in group),
                "plan_gate_reasons": dict(Counter(s["plan_gate_reason"] for s in states)),
                "statuses": dict(Counter(s["status"] for s in states)),
                "missing_core_counts": {k: sum(finite(r.get("features", {}).get(k)) is None for r in group) for k in CORE},
                "missing_optional_counts": {k: sum(finite(r.get("features", {}).get(k)) is None for r in group) for k in FEATURES if k not in CORE},
                **{k: sum(s[k] for s in states) for k in ("plan_missing", "feature_missing", "timestamp_invalid",
                                                         "observation_eligible", "paired_policy_eligible")}}
    return {"all": count(rows), "by_source_side": {side: count([r for r in rows if r.get("source_side") == side])
                                                     for side in ("LONG", "SHORT")}}


def cohort_diagnostics(db, *, now_ms, limit=10000):
    import json
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='rei_v2_cohorts'").fetchone()
    rows = [json.loads(r[0]) for r in db.execute(
        "SELECT payload_json FROM rei_v2_cohorts ORDER BY observed_at_ms DESC,cohort_id DESC LIMIT ?", (limit,))] if exists else []
    latest = rows[0].get("source_signal_at") if rows else None
    total = db.execute("SELECT COUNT(*) FROM rei_v2_cohorts").fetchone()[0] if exists else 0
    return {"total_stored": total, "window_limit": limit, "window_records": len(rows),
            "truncated": total > len(rows), "window": gate_counts(rows),
            "rolling_24h": gate_counts([r for r in rows if now_ms-86400000 <= r["observed_at_ms"] <= now_ms]),
            "latest_scan_id": latest,
            "latest_scan": gate_counts([r for r in rows if r.get("source_signal_at") == latest]),
            "examples": [{"cohort_id": r["cohort_id"], "scan_id": r.get("source_signal_at"),
                          "observed_at_ms": r["observed_at_ms"], "source_side": r["source_side"],
                          **eligibility(r)} for r in rows[:10]],
            "legacy_note": "Legacy plan reasons are unknown; never infer historical filters from current settings."}
