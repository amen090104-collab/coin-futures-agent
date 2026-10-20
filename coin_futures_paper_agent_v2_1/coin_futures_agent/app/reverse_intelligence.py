"""Reverse Entry V2: pure, chronological research. No orders or automatic promotion."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np

VERSION = "reverse-entry-v2.1"
FEATURES = ("source_score", "rsi_1h", "distance_ema20_atr", "atr_pct_1h",
            "volume_ratio_1h", "oi_change_pct", "funding_rate", "relative_strength_1h_pct",
            "signed_ema_distance_atr", "trend_1h_reverse", "trend_4h_reverse",
            "btc_bullish", "btc_bearish", "btc_neutral", "btc_unknown", "hour_sin", "hour_cos")
CORE = FEATURES[:5]
ACTIONS = ("REVERSE_NOW", "WAIT_CONFIRMATION", "BASE_CONTROL")
# Evidence gates and search grid are preregistered research choices, not optimal cutoffs.
MIN_FIT = 30
MIN_FIT_DAYS = 7
MIN_CALIBRATION = 12
CALIBRATION_DAYS = 2
MIN_SELECTED = 5
EMBARGO_MS = 60_000
FAMILIES = ("logistic_l2", "empirical_neighbors")


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def day(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).date().isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def metrics(values):
    values = [float(v) for v in values if finite(v) is not None]
    if not values:
        return {"n": 0, "expectancy_r": None, "profit_factor_r": None,
                "win_rate_pct": None, "total_net_r": 0., "serial_drawdown_r": None}
    profit = sum(max(0., v) for v in values)
    loss = -sum(min(0., v) for v in values)
    equity = peak = drawdown = 0.
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"n": len(values), "expectancy_r": round(sum(values) / len(values), 6),
            "profit_factor_r": round(profit / loss, 6) if loss else None,
            "win_rate_pct": round(100 * sum(v > 0 for v in values) / len(values), 3),
            "total_net_r": round(sum(values), 6), "serial_drawdown_r": round(drawdown, 6)}


def valid_features(features):
    if any(finite(features.get(k)) is None for k in CORE):
        return False
    return (0 <= float(features["source_score"]) <= 100 and 0 <= float(features["rsi_1h"]) <= 100
            and float(features["distance_ema20_atr"]) >= 0 and float(features["atr_pct_1h"]) > 0
            and float(features["volume_ratio_1h"]) >= 0)


def cluster_interval(pairs):
    groups = {}
    for signal_day, delta in pairs:
        groups.setdefault(signal_day, []).append(delta)
    if len(groups) < 3:
        return None
    values = list(groups.values())
    random = np.random.default_rng(4420)
    means = []
    for _ in range(500):
        sample = [value for index in random.integers(0, len(values), size=len(values)) for value in values[index]]
        means.append(sum(sample) / len(sample))
    return [round(float(v), 6) for v in np.quantile(means, [.025, .975])]


def eligible_rows(rows, asof_ms, source_side):
    """Labels must be CLOSED/EXPIRED, known before cutoff, and from this dataset."""
    valid, seen = [], set()
    for row in sorted(rows, key=lambda r: (r.get("observed_at_ms", 0), r.get("cohort_id", ""))):
        cid = row.get("cohort_id")
        observed = row.get("observed_at_ms", 0)
        available = row.get("label_available_at_ms", 0)
        closed = row.get("label_closed_at_ms", 0)
        features_at = row.get("features_available_at_ms", 0)
        outcomes = row.get("outcomes", {})
        if (not cid or cid in seen or row.get("source_side") != source_side
                or row.get("dataset") != VERSION or not row.get("quality_ok")
                or not (0 < features_at <= observed < closed <= available < asof_ms)
                or any(finite(outcomes.get(a)) is None for a in ACTIONS)
                or not valid_features(row.get("features", {}))):
            continue
        seen.add(cid)
        valid.append(row)
    return valid[-2000:]


def _matrix(rows):
    return np.array([[np.nan if finite(r.get("features", {}).get(k)) is None
                      else float(r["features"][k]) for k in FEATURES] for r in rows], dtype=float)


def _transform(rows, scaler):
    raw = _matrix(rows)
    missing = np.isnan(raw)
    filled = np.where(missing, scaler["median"], raw)
    standardized = np.clip((filled - scaler["median"]) / scaler["scale"], -8, 8)
    return np.column_stack([np.ones(len(rows)), standardized, missing.astype(float)])


def _fit(rows, family):
    raw = _matrix(rows)
    median = [float(np.median(col[np.isfinite(col)])) if np.isfinite(col).any() else 0.
              for col in raw.T]
    filled = np.where(np.isnan(raw), median, raw)
    scale = np.std(filled, axis=0)
    scaler = {"median": median, "scale": np.where(scale < 1e-8, 1., scale).tolist()}
    x = _transform(rows, scaler)
    outcomes = np.array([[r["outcomes"][a] for a in ACTIONS] for r in rows], dtype=float)
    model = {"family": family, "scaler": scaler}
    if family == "logistic_l2":
        targets = (outcomes > 0).astype(float)
        weights = np.zeros((x.shape[1], len(ACTIONS)))
        # Fixed L2/optimizer settings; no tuning on test labels.
        for _ in range(250):
            probability = 1 / (1 + np.exp(-np.clip(x @ weights, -30, 30)))
            penalty = weights.copy()
            penalty[0] = 0
            weights -= .15 * (x.T @ (probability - targets) / len(x) + .05 * penalty)
        model["weights"] = weights.tolist()
        model["positive_mean"] = [float(y[y > 0].mean()) if (y > 0).any() else 0. for y in outcomes.T]
        model["nonpositive_mean"] = [float(y[y <= 0].mean()) if (y <= 0).any() else 0. for y in outcomes.T]
    else:
        model.update(x=x.tolist(), outcomes=outcomes.tolist(), k=max(1, int(math.sqrt(len(x)))))
    return model


def _estimates(model, row):
    x = _transform([row], model["scaler"])[0]
    if model["family"] == "logistic_l2":
        weights = np.array(model["weights"])
        probabilities = 1 / (1 + np.exp(-np.clip(x @ weights, -30, 30)))
        ev = probabilities * model["positive_mean"] + (1 - probabilities) * model["nonpositive_mean"]
    else:
        distance = np.mean((np.array(model["x"])[:, 1:] - x[1:]) ** 2, axis=1)
        nearest = np.argsort(distance, kind="stable")[:model["k"]]
        outcomes = np.array(model["outcomes"])[nearest]
        ev = outcomes.mean(axis=0)
        probabilities = (outcomes > 0).mean(axis=0)
    return probabilities, ev


def _choice(model, row, threshold):
    probabilities, ev = _estimates(model, row)
    index = int(np.argmax(ev[:2]))
    score = float(100 * probabilities[index])
    action = ACTIONS[index] if ev[index] > max(0., ev[2]) and score >= threshold else "NO_TRADE"
    return action, score, ev, index


def fit_policy(rows, *, asof_ms, source_side):
    """Train -> temporal calibration -> future test; no random split or CV leakage."""
    window = sorted((r for r in rows if r.get("observed_at_ms", 0) < asof_ms - EMBARGO_MS),
                    key=lambda r: (r["observed_at_ms"], r.get("cohort_id", "")))[-4000:]
    history = eligible_rows(window, asof_ms - EMBARGO_MS, source_side)
    evidence = {"training_n": len(history), "training_days": len({day(r["observed_at_ms"]) for r in history})}
    days = sorted({day(r["observed_at_ms"]) for r in history})
    if len(days) < MIN_FIT_DAYS + CALIBRATION_DAYS:
        return {"status": "INSUFFICIENT_HISTORY", **evidence}
    calibration_days = days[-CALIBRATION_DAYS:]
    cutoff = int(datetime.fromisoformat(calibration_days[0]).replace(tzinfo=timezone.utc).timestamp() * 1000)
    fit = [r for r in history if r["observed_at_ms"] < cutoff and r["label_available_at_ms"] < cutoff - EMBARGO_MS]
    calibration = [r for r in history if day(r["observed_at_ms"]) in calibration_days]
    if len(fit) < MIN_FIT or len({day(r["observed_at_ms"]) for r in fit}) < MIN_FIT_DAYS or len(calibration) < MIN_CALIBRATION:
        return {"status": "INSUFFICIENT_CALIBRATION", **evidence}
    baseline_dd = metrics([r["outcomes"]["REVERSE_NOW"] for r in calibration])["serial_drawdown_r"]
    candidates, diagnostics = [], []
    for family in FAMILIES:
        model = _fit(fit, family)
        fit_scores = [_choice(model, r, 0)[1] for r in fit]
        # Threshold grid comes from fit features; selection uses only later calibration.
        thresholds = sorted({0., *[round(float(np.quantile(fit_scores, q)), 6) for q in (.25, .5, .75, .9)]})
        for threshold in thresholds:
            choices = [_choice(model, r, threshold)[0] for r in calibration]
            values = [r["outcomes"].get(a, 0.) for r, a in zip(calibration, choices)]
            stats = metrics(values)
            selected = sum(a != "NO_TRADE" for a in choices)
            summary = {"family": family, "threshold": round(threshold, 6),
                       "selected": selected, "calibration": stats}
            diagnostics.append(summary)
            if selected >= MIN_SELECTED and stats["expectancy_r"] > 0 and stats["serial_drawdown_r"] <= baseline_dd:
                candidates.append((stats["expectancy_r"], -stats["serial_drawdown_r"], -threshold, model, summary))
    if not candidates:
        return {"status": "NO_CALIBRATION_EDGE", **evidence, "search": diagnostics}
    _, _, _, model, selected = max(candidates, key=lambda x: x[:3])
    manifest = {"version": VERSION, "status": "EXPLORATORY_MODEL", "source_side": source_side,
                "features": list(FEATURES), "model": model, "threshold": selected["threshold"],
                "fit_ids": [r["cohort_id"] for r in fit], "calibration_ids": [r["cohort_id"] for r in calibration],
                "fit_label_cutoff_ms": max(r["label_available_at_ms"] for r in fit),
                "calibration_start_ms": cutoff,
                "label_cutoff_ms": max(r["label_available_at_ms"] for r in history),
                "training_digest": digest([{k: r[k] for k in ("cohort_id", "source_side", "observed_at_ms",
                    "features_available_at_ms", "label_available_at_ms", "label_closed_at_ms", "features", "outcomes")}
                    for r in history]), "calibration_selected": selected,
                "search": diagnostics, **evidence}
    manifest["model_id"] = digest(manifest)
    return manifest


def predict(features, policy, *, source_side):
    output = {"version": VERSION, "score": None, "score_is_win_probability": False,
              "action": "NO_TRADE", "recommendation": "NO TRADE", "source_side": source_side,
              "reverse_side": "SHORT" if source_side == "LONG" else "LONG",
              "status": policy.get("status"), "model_id": policy.get("model_id"),
              "factors": [], "reasons": [], "out_of_sample_validated": False}
    missing = [key for key in CORE if finite(features.get(key)) is None]
    if missing:
        output.update(status="MISSING_FEATURES", reasons=["Thiếu đặc trưng tại thời điểm tín hiệu: " + ", ".join(missing)])
        return output
    if not valid_features(features):
        output.update(status="INVALID_FEATURES", reasons=["Đặc trưng ngoài miền hợp lệ; không tạo điểm."])
        return output
    if source_side not in {"LONG", "SHORT"} or policy.get("source_side", source_side) != source_side:
        output.update(status="INVALID_SIDE", reasons=["Hướng nguồn không khớp mô hình đã đóng băng."])
        return output
    if policy.get("status") != "EXPLORATORY_MODEL":
        output["reasons"] = ["Chưa đủ dữ liệu/kiểm định theo thời gian hoặc chưa có lợi thế trên calibration."]
        return output
    row = {"features": features}
    action, score, ev, index = _choice(policy["model"], row, policy["threshold"])
    output.update(score=round(score, 2), action=action,
                  recommendation=output["reverse_side"] if action == "REVERSE_NOW" else "WAIT" if action == "WAIT_CONFIRMATION" else "NO TRADE",
                  expected_net_r={a: round(float(v), 6) for a, v in zip(ACTIONS, ev)},
                  researched_threshold=policy["threshold"], family=policy["model"]["family"])
    if ev[2] >= max(ev[:2]):
        output["reasons"].append("Đối chứng theo Base có kỳ vọng ước lượng cao hơn Reverse; không ép đảo chiều.")
    output["reasons"].append("Điểm là chỉ số mô hình chưa hiệu chỉnh; ngưỡng được chọn trên calibration quá khứ, chưa tối ưu ngoài mẫu.")
    # Feature ablation is a model association, not a causal attribution.
    for key, median in zip(FEATURES, policy["model"]["scaler"]["median"]):
        if finite(features.get(key)) is None:
            continue
        neutral = {**features, key: median}
        neutral_p, neutral_ev = _estimates(policy["model"], {"features": neutral})
        output["factors"].append({"feature": key, "value": features[key],
                                  "delta_score": round(score - float(100 * neutral_p[index]), 4),
                                  "delta_estimated_r": round(float(ev[index] - neutral_ev[index]), 6)})
    output["factors"].sort(key=lambda f: abs(f["delta_estimated_r"]), reverse=True)
    return output


def walk_forward(rows):
    """Freeze models at each UTC day start; pending/late labels are never trained."""
    days = sorted({day(r["observed_at_ms"]) for r in rows if r.get("observed_at_ms")})
    predictions, folds = [], []
    for test_day in days:
        cutoff = int(datetime.fromisoformat(test_day).replace(tzinfo=timezone.utc).timestamp() * 1000)
        for source_side in ("LONG", "SHORT"):
            policy = fit_policy(rows, asof_ms=cutoff, source_side=source_side)
            selected = [r for r in rows if day(r["observed_at_ms"]) == test_day and r.get("source_side") == source_side]
            if not selected:
                continue
            folds.append({"test_day": test_day, "source_side": source_side,
                          "status": policy["status"], "model_id": policy.get("model_id"),
                          "fit_label_cutoff_ms": policy.get("fit_label_cutoff_ms"),
                          "label_cutoff_ms": policy.get("label_cutoff_ms"), "test_n": len(selected)})
            for row in selected:
                valid_features = row.get("quality_ok") and 0 < row.get("features_available_at_ms", 0) <= row["observed_at_ms"]
                decision = predict(row.get("features", {}), policy if valid_features else {"status": "INVALID_PROVENANCE"}, source_side=source_side)
                # Outcome evaluation is separate and only includes complete, valid research rows.
                resolved = bool(eligible_rows([row], 2**62, source_side))
                control = row.get("controls", {}).get(decision["action"])
                filled = False if decision["action"] == "NO_TRADE" else (
                    control.get("entered_at_ms") is not None if control is not None else None)
                predictions.append({"cohort_id": row["cohort_id"], "test_day": test_day,
                                    "observed_at_ms": row["observed_at_ms"], "source_side": source_side,
                                    "label_closed_at_ms": row.get("label_closed_at_ms", 0),
                                    "extra_outcomes": {k: v["net_r"] for k, v in row.get("controls", {}).items()
                                        if k in {"REV_C_CONTROL", "REV_D_CONTROL"} and v["status"] == "CLOSED" and finite(v.get("net_r")) is not None},
                                    "btc_regime": row.get("btc_regime"), **decision,
                                    "filled": filled, "resolved": resolved, "outcomes": row.get("outcomes", {}) if resolved else {}})
    complete = sorted((p for p in predictions if p["resolved"]), key=lambda p: (p["label_closed_at_ms"], p["cohort_id"]))
    values = [p["outcomes"].get(p["action"], 0.) for p in complete]
    skipped = [p for p in complete if p["filled"] is False]
    scored = [p for p in complete if p["score"] is not None]
    comparisons = {}
    for action in ACTIONS:
        pairs = [(p["test_day"], p["outcomes"].get(p["action"], 0.) - p["outcomes"][action]) for p in scored]
        independent_days = len({d for d, _ in pairs})
        comparisons[action] = {"matched": len(pairs), "independent_days": independent_days,
            "mean_delta_r": round(sum(v for _, v in pairs)/len(pairs), 6) if pairs else None,
            "day_cluster_95pct_interval": cluster_interval(pairs),
            "status": "INSUFFICIENT_SAMPLE" if len(pairs) < 100 or independent_days < 14 else "EXPLORATORY_HOLDOUT_REVIEW"}
    return {"version": VERSION, "status": "EXPLORATORY_WALK_FORWARD" if any(p["score"] is not None for p in complete) else "INSUFFICIENT_DATA",
            "out_of_sample_validated": False, "folds": folds, "predictions": predictions,
            "policy": metrics(values), "executed": metrics([v for p, v in zip(complete, values) if p["filled"] is True]),
            "attempted_entries": sum(p["action"] != "NO_TRADE" for p in complete),
            "filled_entries": sum(p["filled"] is True for p in complete),
            "unknown_fill_status": sum(p["filled"] is None for p in complete),
            "scored_oos_n": sum(p["score"] is not None for p in complete),
            "cold_start_n": sum(p["score"] is None for p in complete),
            "trained_policy": metrics([v for p, v in zip(complete, values) if p["score"] is not None]),
            "matched_scored_comparisons": comparisons,
            "controls": {a: metrics([p["outcomes"][a] for p in complete]) for a in ACTIONS},
            "additional_control_results": {a: metrics([p["extra_outcomes"][a] for p in complete if a in p["extra_outcomes"]])
                                           for a in ("REV_C_CONTROL", "REV_D_CONTROL")},
            "avoided_losses": sum(p["outcomes"]["REVERSE_NOW"] < 0 for p in skipped),
            "missed_winners": sum(p["outcomes"]["REVERSE_NOW"] > 0 for p in skipped),
            "unresolved": len(predictions) - len(complete),
            "by_source_regime": {f"{side}/{regime}": metrics([p["outcomes"].get(p["action"], 0.) for p in complete
                if p["source_side"] == side and p.get("btc_regime") == regime])
                for side, regime in sorted({(p["source_side"], str(p.get("btc_regime"))) for p in complete})},
            "decisions": dict(Counter(p["action"] for p in predictions)),
            "limitations": ["Drawdown là serial net-R, không phải drawdown equity portfolio khi lệnh chồng lấn.",
                            "Funding, liquidation, spread và thanh khoản khớp thật chưa được mô hình đầy đủ.",
                            "So sánh chỉ dùng cohort đủ ba outcome; cần kiểm tra thiên lệch do censoring."]}
