"""Interpretable loss clusters with same-condition winner controls.

All closed LONG and SHORT Paper trades are profiled; every losing trade
receives memberships or an explicit missing-feature explanation. Candidates
are discovered ONLY on earlier, label-visible dates, then checked on later
validation and holdout days. Nothing here simulates a new entry or executes
a Shadow trade.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math

VERSION = "loss-clusters-time-split-v1"
# Fixed feature bins decided before observing this dataset. No data-derived
# distance thresholds and no per-trade hindsight optimization.
FAMILIES = (
    ("btc_regime", "rsi_1h"),
    ("rsi_1h", "atr_pct_1h"),
    ("score", "volume_ratio_1h"),
)
MIN_TRAIN_IN = 10
MIN_TRAIN_OUT = 12
MIN_VAL_IN = 5
MIN_VAL_OUT = 8
MIN_TEST_IN = 5
MIN_TEST_OUT = 8
MAX_CANDIDATES = 10


def _date(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _numeric(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bucket(field, row):
    ctx = row.get("feature_values")
    if not isinstance(ctx, dict):
        return "UNKNOWN"
    x = ctx.get(field)
    if field == "btc_regime":
        if x is None:
            return "UNKNOWN"
        normalized = str(x).upper()
        if normalized in ("UP", "UPTREND", "BULL", "BULLISH"):
            return "BULLISH"
        if normalized in ("DOWN", "DOWNTREND", "BEAR", "BEARISH"):
            return "BEARISH"
        if normalized == "NEUTRAL":
            return "NEUTRAL"
        return "UNKNOWN"
    x = _numeric(x)
    if x is None:
        return "UNKNOWN"
    if field == "rsi_1h":
        if x < 0 or x > 100:
            return "UNKNOWN"
        return "LOW_LT_40" if x < 40 else "MID_40_60" if x <= 60 else "HIGH_GT_60"
    if field == "atr_pct_1h":
        return "UNKNOWN" if x < 0 else "LOW_LT_1_5" if x < 1.5 else "MID_1_5_3" if x < 3 else "HIGH_GE_3"
    if field == "score":
        return "UNKNOWN" if x < 0 or x > 100 else "LT_80" if x < 80 else "80_89" if x < 90 else "GE_90"
    if field == "volume_ratio_1h":
        return "UNKNOWN" if x < 0 else "LOW_LT_1" if x < 1 else "MID_1_1_5" if x < 1.5 else "HIGH_GE_1_5"
    raise ValueError("UNRECOGNIZED_FEATURE")


def _memberships(row):
    case, side = str(row.get("strategy_id") or ""), str(row.get("side") or "")
    if not case or side not in ("LONG", "SHORT"):
        return []
    return [
        {"family": "+".join(fields),
         "features": list(fields),
         "case": case, "side": side,
         "buckets": {field: _bucket(field, row) for field in fields}}
        for fields in FAMILIES
    ]


def _identifier(spec):
    return spec["case"] + "|" + spec["side"] + "|" + spec["family"] + "|" + "|".join(
        spec["buckets"][f] for f in spec["features"])


def _metrics(group):
    n = len(group)
    if not n:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": None,
                "mean_R": None, "total_R": None, "known_R": 0}
    vals = [_numeric(x.get("r_multiple")) for x in group]
    complete = all(x is not None for x in vals)
    return {"trades": n, "wins": sum(x["net_pnl"] > 0 for x in group),
            "losses": sum(x["net_pnl"] < 0 for x in group),
            "win_rate": round(sum(x["net_pnl"] > 0 for x in group) / n, 5),
            "mean_R": round(sum(vals) / n, 5) if complete else None,
            "total_R": round(sum(vals), 5) if complete else None,
            "known_R": sum(x is not None for x in vals)}


def _valid_rows(rows):
    accepted, rejected = [], 0
    for r in rows:
        opened, closed = _date(r.get("opened_at")), _date(r.get("closed_at"))
        pnl = _numeric(r.get("net_pnl"))
        if not opened or not closed or closed < opened or pnl is None or r.get("side") not in ("LONG", "SHORT"):
            rejected += 1
            continue
        accepted.append({**r, "_opened": opened, "_closed": closed})
    return sorted(accepted, key=lambda x: (x["_opened"], str(x.get("id")))), rejected


def _folds(rows):
    dates = sorted({x["_opened"].date() for x in rows})
    if len(dates) < 15:
        return None, {"status": "INSUFFICIENT_INDEPENDENT_DAYS", "days": len(dates)}
    cut1 = max(1, int(.6 * len(dates)))
    cut2 = max(cut1 + 1, int(.8 * len(dates)))
    d1, d2, d3 = set(dates[:cut1]), set(dates[cut1:cut2]), set(dates[cut2:])
    train0 = [x for x in rows if x["_opened"].date() in d1]
    val0 = [x for x in rows if x["_opened"].date() in d2]
    test = [x for x in rows if x["_opened"].date() in d3]
    if not train0 or not val0 or not test:
        return None, {"status": "EMPTY_FOLD"}
    val_start, test_start = min(x["_opened"] for x in val0), min(x["_opened"] for x in test)
    train = [x for x in train0 if x["_closed"] <= val_start]
    val = [x for x in val0 if x["_closed"] <= test_start]
    return (train, val, test), {
        "status": "READY",
        "days": len(dates),
        "train": len(train), "validation": len(val), "test": len(test),
        "labels_purged_before_next_fold": len(train0) - len(train) + len(val0) - len(val),
        "validation_starts_at_utc": val_start.isoformat(),
        "holdout_starts_at_utc": test_start.isoformat(),
    }


def _same_case_side(rows, spec):
    return [x for x in rows if x.get("strategy_id") == spec["case"]
            and x.get("side") == spec["side"]]


def _matching(rows, spec):
    return [x for x in _same_case_side(rows, spec)
            if all(_bucket(k, x) == v for k, v in spec["buckets"].items())]


def _contrast(rows, spec):
    baseline = _same_case_side(rows, spec)
    inside = _matching(rows, spec)
    # A comparator should have the SAME available features; missing data is
    # not evidence of a safer alternative.
    available = [x for x in baseline if all(_bucket(field, x) != "UNKNOWN"
                                           for field in spec["features"])]
    outside = [x for x in available if x not in inside]
    return {"cluster": _metrics(inside), "other_known_conditions": _metrics(outside),
            "unknown_features": len(baseline) - len(available),
            "case_side_total": len(baseline)}


def _is_bad_group(stats, *, n_in, n_out):
    a, b = stats["cluster"], stats["other_known_conditions"]
    return bool(a["trades"] >= n_in and b["trades"] >= n_out
                and a["losses"] >= max(4, n_in // 2)
                and a["mean_R"] is not None and b["mean_R"] is not None
                and a["mean_R"] < b["mean_R"] - 0.12)


def build_loss_clusters(rows):
    source, rejected = _valid_rows(rows)
    buckets = defaultdict(lambda: {"spec": None, "loss_ids": [], "win_ids": [], "trades": []})
    for row in source:
        for spec in _memberships(row):
            key = _identifier(spec)
            entry = buckets[key]
            entry["spec"] = spec
            entry["trades"].append(row)
            if row["net_pnl"] < 0:
                entry["loss_ids"].append(str(row.get("id")))
            elif row["net_pnl"] > 0:
                entry["win_ids"].append(str(row.get("id")))
    all_losses = {str(x.get("id")) for x in source if x["net_pnl"] < 0}
    groups = []
    memberships = defaultdict(list)
    for key, group in sorted(buckets.items()):
        for trade_id in group["loss_ids"]:
            memberships[trade_id].append(key)
        spec = group["spec"]
        counts = _metrics(group["trades"])
        groups.append({"id": key, **spec, **counts,
                       "loss_ids": group["loss_ids"], "win_ids": group["win_ids"],
                       "descriptive_only": True,
                       "data_quality": "MISSING_ENTRY_FEATURES" if "UNKNOWN" in spec["buckets"].values()
                                       else "ENTRY_SNAPSHOT_TIMESTAMP_NOT_INDEPENDENTLY_ATTESTED"})
    splits, audit = _folds(source)
    candidates = []
    if splits is not None:
        train, validation, holdout = splits
        # Discover groups exclusively using past labelled training rows.
        # Bounded preregistered categories; test does not choose thresholds.
        possible = []
        for group in groups:
            spec = {k: group[k] for k in ("case", "side", "family", "features", "buckets")}
            if "UNKNOWN" in spec["buckets"].values():
                continue
            tr = _contrast(train, spec)
            if _is_bad_group(tr, n_in=MIN_TRAIN_IN, n_out=MIN_TRAIN_OUT):
                possible.append((group["id"], spec, tr))
        possible.sort(key=lambda x: (x[0]))
        qualified = []
        for key, spec, tr in possible:
            val = _contrast(validation, spec)
            if _is_bad_group(val, n_in=MIN_VAL_IN, n_out=MIN_VAL_OUT):
                qualified.append((key, spec, tr, val))
        # Multiple comparisons controlled by a fixed candidate budget; the
        # test set does not change the selection order or feature boundaries.
        for key, spec, tr, val in qualified[:MAX_CANDIDATES]:
            test = _contrast(holdout, spec)
            passed = _is_bad_group(test, n_in=MIN_TEST_IN, n_out=MIN_TEST_OUT)
            candidates.append({
                "hypothesis_id": "AVOID_" + key, "group_id": key,
                "hypothesis": "Avoid entries matching this recurring loss-condition cluster",
                "rule": spec, "train": tr, "validation": val, "holdout": test,
                "holdout_supported": passed,
                "status": "AWAITING_PROSPECTIVE_SHADOW_SIGNAL_FEED" if passed
                          else "REJECTED_ON_INDEPENDENT_HOLDOUT",
                "shadow_executed": False, "no_new_trade_wins_claimed": True,
                "baseline_missed_winners_if_filtered_on_holdout": test["cluster"]["wins"],
                "frozen_after_opened_at": max(x["_opened"] for x in source).isoformat(),
                "requires": "Prospective timestamped signals and chronological immutable 1m OHLC replay",
                "may_modify_trading_bot": False,
            })
    return {
        "version": VERSION,
        "method": "PREDECLARED_INTERPRETABLE_BUCKETS_PER_CASE_AND_SIDE",
        "families": ["+".join(x) for x in FAMILIES],
        "total_valid_closed_trades": len(source),
        "invalid_trades": rejected, "total_losses": len(all_losses),
        "losses_with_group_membership": len(memberships),
        "losses_without_group_membership": len(all_losses - memberships.keys()),
        "groups": groups,
        "time_split": audit, "candidates": candidates,
        "holdout_supported_shadow_candidates": sum(x["holdout_supported"] for x in candidates),
        "status": "EXPLORATORY_NO_SHADOW_EXECUTION",
        "shadow_executed": False, "true_signal_feed_available": False,
        "shadow_orders": 0, "paper_orders": 0, "real_orders": 0,
        "causality_proven": False,
        "limitations": "Clusters are overlapping descriptive categories; per-group membership is "
                       "not independent, missing values are not imputed, and entry-time provenance "
                       "must be verified before prospective Shadow. Historical avoidance changes "
                       "which other trades could be taken; OHLC event replay is required.",
    }
