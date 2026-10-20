"""Grouped, purged chronological research. Historical classifier != entry policy."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

from .reverse_intelligence import (FEATURES, CORE, finite, valid_features, digest, day, metrics,
                                   _matrix, _transform, fit_policy, predict, VERSION as V2_VERSION)

DAY = 86_400_000
EMBARGO = 3_600_000  # preregistered 1h; also purge overlapping outcome intervals.
MIN_TRAIN = 30
MIN_CAL = 12


def primary(rows, *, source_side=None, origin=None):
    """One label per correlated source cohort; never count REV variants as independent wins."""
    grouped = {}
    priority = {"HISTORICAL_PAPER": 0, "HISTORICAL_PAPER_EXPORT": 1, "FORWARD_SHADOW_V2": 2,
                "HISTORICAL_SHADOW": 3, "HISTORICAL_STRATEGY_LAB": 4}
    for row in sorted(rows, key=lambda r: (priority.get(r["origin"], 99),
                                          r.get("label_policy") != "REVERSE_RR2", r.get("control") != "REVERSE_NOW", r["sample_id"])):
        if source_side and row["source_side"] != source_side or origin and row["origin"] not in origin:
            continue
        if row["origin"] == "FORWARD_SHADOW_V2" and row.get("control") != "REVERSE_NOW":
            continue
        if (row.get("status") != "READY" or not valid_features(row.get("features", {}))
                or not 0 < row["feature_provenance"].get("max_source_ms", 0) <= row["decision_ms"] <= row["entry_ms"] <= row["closed_ms"]
                or finite(row.get("net_r")) is None):
            continue
        grouped.setdefault(row["group_id"], row)
    return sorted(grouped.values(), key=lambda r: (r["decision_ms"], r["sample_id"]))


def fit_binary(rows, family):
    raw = _matrix(rows)
    median = [float(np.median(c[np.isfinite(c)])) if np.isfinite(c).any() else 0. for c in raw.T]
    filled = np.where(np.isnan(raw), median, raw)
    scale = np.std(filled, axis=0)
    scaler = {"median": median, "scale": np.where(scale < 1e-8, 1., scale).tolist()}
    x = _transform(rows, scaler)
    y = np.array([r["net_r"] > 0 for r in rows], dtype=float)
    model = {"family": family, "scaler": scaler, "wins": int(y.sum()), "losses": int((y == 0).sum())}
    if family == "logistic_l2":
        w = np.zeros(x.shape[1])
        for _ in range(250):
            p = 1/(1+np.exp(-np.clip(x@w, -30, 30)))
            penalty = w.copy()
            penalty[0] = 0
            w -= .15*(x.T@(p-y)/len(y)+.05*penalty)
        model["weights"] = w.tolist()
    else:
        model.update(x=x.tolist(), y=y.tolist(), k=max(1, int(math.sqrt(len(y)))))
    return model


def estimate(model, features):
    x = _transform([{"features": features}], model["scaler"])[0]
    if model["family"] == "logistic_l2":
        return float(1/(1+np.exp(-np.clip(x@np.array(model["weights"]), -30, 30))))
    distances = np.mean((np.array(model["x"])[:, 1:]-x[1:])**2, axis=1)
    nearest = np.argsort(distances, kind="stable")[:model["k"]]
    return float(np.array(model["y"])[nearest].mean())


def fit(rows, *, asof_ms, side, excluded_groups=(), retrospective=False, lane="HISTORICAL_PAPER"):
    origins = {"HISTORICAL_PAPER", "HISTORICAL_PAPER_EXPORT"} if lane == "HISTORICAL_PAPER" else {"FORWARD_SHADOW_V2"}
    selected = primary(rows, source_side=side, origin=origins)
    if lane == "HISTORICAL_PAPER":
        selected = [r for r in selected if r.get("label_policy") == "REVERSE_RR2"]
    known = "historical_label_known_ms" if retrospective else "label_available_ms"
    history = [r for r in selected if r["group_id"] not in excluded_groups
               and r[known] < asof_ms-EMBARGO and r["closed_ms"] < asof_ms-EMBARGO][-2000:]
    evidence = {"source_side": side, "training_n": len(history), "lane": lane, "asof_ms": asof_ms,
                "retrospective": retrospective, "status": "INSUFFICIENT_DATA"}
    days = sorted({day(r["decision_ms"]) for r in history})
    if len(days) < 9:
        return evidence
    boundary = next(r["decision_ms"]//DAY*DAY for r in history if day(r["decision_ms"]) == days[-2])
    calibration = [r for r in history if r["decision_ms"] >= boundary]
    fit_rows = [r for r in history if r["decision_ms"] < boundary-EMBARGO
                and max(r["closed_ms"], r[known]) < boundary-EMBARGO]
    if len(fit_rows) < MIN_TRAIN or len(calibration) < MIN_CAL or len({day(r["decision_ms"]) for r in fit_rows}) < 7:
        return evidence
    if len({r["net_r"] > 0 for r in fit_rows}) < 2:
        return {**evidence, "status": "UNTRAINED_ONE_CLASS"}
    candidates = []
    targets = np.array([r["net_r"] > 0 for r in calibration], dtype=float)
    for family in ("logistic_l2", "empirical_neighbors"):
        model = fit_binary(fit_rows, family)
        predictions = np.array([estimate(model, r["features"]) for r in calibration])
        loss = float(np.mean((predictions-targets)**2))
        candidates.append((loss, family, model))
    brier, _, model = min(candidates, key=lambda x: (x[0], x[1]))
    result = {**evidence, "status": "RESEARCH_CLASSIFIER", "model": model,
              "fit_groups": [r["group_id"] for r in fit_rows], "calibration_groups": [r["group_id"] for r in calibration],
              "fit_window_ms": [fit_rows[0]["decision_ms"], fit_rows[-1]["decision_ms"]],
              "calibration_window_ms": [calibration[0]["decision_ms"], calibration[-1]["decision_ms"]],
              "max_fit_label_ms": max(r[known] for r in fit_rows), "calibration_start_ms": boundary,
              "max_label_ms": max(r[known] for r in history), "calibration_brier": brier,
              "training_digest": digest([{k: r[k] for k in ("sample_id", "features", "net_r", "decision_ms", "closed_ms", known)} for r in history])}
    result["model_id"] = digest(result)
    return result


def decision(features, model, *, side, paired_policy=None):
    reasons = []
    missing = [k for k in CORE if finite(features.get(k)) is None]
    result = {"score": None, "action": "NO_TRADE", "recommendation": "NO TRADE", "source_side": side,
              "status": "NO_MODEL", "reason_codes": [], "reasons": reasons, "factors": [],
              "model_id": model.get("model_id"), "score_is_win_probability": False, "money_mode": "SHADOW_ONLY"}
    if missing or not valid_features(features):
        result.update(status="MISSING_FEATURE", reason_codes=["MISSING_FEATURE"], missing_features=missing)
        reasons.append("Thiếu/sai đặc trưng tại thời điểm quyết định; không tạo điểm thay thế.")
        return result
    if model.get("status") != "RESEARCH_CLASSIFIER":
        result.update(status=model.get("status", "UNTRAINED"), reason_codes=[model.get("status", "UNTRAINED")])
        reasons.append(f"Chưa có mô hình đủ dữ liệu cho Base {side}; mẫu phù hợp: {model.get('training_n', 0)}.")
        return result
    score = 100*estimate(model["model"], features)
    result.update(score=round(score, 2), status="RISK_GATE", reason_codes=["NO_MATCHED_POLICY_EVIDENCE"])
    reasons.append("Điểm classifier nghiên cứu, chưa phải xác suất thắng đã hiệu chỉnh.")
    for key, median in zip(FEATURES, model["model"]["scaler"]["median"]):
        if finite(features.get(key)) is not None:
            delta = score-100*estimate(model["model"], {**features, key: median})
            result["factors"].append({"feature": key, "value": features[key], "delta_score": round(delta, 4)})
    result["factors"].sort(key=lambda f: abs(f["delta_score"]), reverse=True)
    if paired_policy and paired_policy.get("status") == "EXPLORATORY_MODEL":
        paired = predict(features, paired_policy, source_side=side)
        result.update(action=paired["action"], recommendation=paired["recommendation"], status="SHADOW_POLICY",
                      reason_codes=["PAIRED_FORWARD_POLICY"], paired_score=paired["score"], paired_model_id=paired["model_id"])
        result["reasons"].extend(paired["reasons"])
    else:
        reasons.append("Chưa đủ đối chứng NOW/WAIT/Base nên chưa khuyến nghị vào lệnh.")
    return result


def differentiators(rows):
    result = {}
    for side in ("LONG", "SHORT"):
        selected = primary(rows, source_side=side)
        features = []
        for key in FEATURES:
            win = [r["features"][key] for r in selected if r["net_r"] > 0 and finite(r["features"].get(key)) is not None]
            loss = [r["features"][key] for r in selected if r["net_r"] <= 0 and finite(r["features"].get(key)) is not None]
            if win and loss:
                features.append({"feature": key, "win_n": len(win), "loss_n": len(loss),
                                 "win_mean": float(np.mean(win)), "loss_mean": float(np.mean(loss)),
                                 "difference": float(np.mean(win)-np.mean(loss))})
        groups = defaultdict(list)
        for r in selected:
            f = r["features"]
            regime = "BULLISH" if f.get("btc_bullish") else "BEARISH" if f.get("btc_bearish") else "NEUTRAL" if f.get("btc_neutral") else "UNKNOWN"
            groups["regime:"+regime].append(r["net_r"])
            groups["score:"+str(int(f["source_score"]//10)*10)].append(r["net_r"])
            for code in r.get("reason_codes", []):
                groups["trigger:"+code].append(r["net_r"])
        result[side] = {"matched_cohorts": len(selected), "wins": sum(r["net_r"] > 0 for r in selected),
                        "losses_or_flat": sum(r["net_r"] <= 0 for r in selected), "features": features,
                        "conditions": {k: metrics(v) for k, v in groups.items()},
                        "interpretation": "Liên hệ mô tả; chưa chứng minh nguyên nhân hay lợi nhuận ngoài mẫu."}
    return result


def source_discovery(rows):
    """Available original signal reasons/score before reconstruction; descriptive only, no fake indicators."""
    selected = {}
    for row in sorted(rows, key=lambda r: (r["origin"] != "HISTORICAL_PAPER", r["sample_id"])):
        if row.get("label_policy") == "REVERSE_RR2" and row.get("status") != "IMPORT_CONFLICT":
            selected.setdefault(row["group_id"], row)
    result = {}
    for side in ("LONG", "SHORT"):
        group = sorted((r for r in selected.values() if r["source_side"] == side), key=lambda r: (r["closed_ms"], r["sample_id"]))
        known = [r for r in group if r.get("reason_codes_known")]
        codes = sorted({c for r in known for c in r["reason_codes"]})
        result[side] = {"n": len(group), "wins": sum(r["net_r"] > 0 for r in group),
            "losses_or_flat": sum(r["net_r"] <= 0 for r in group),
            "unknown_source_reasons": len(group)-len(known),
            "score_ranges": {str(low): metrics([r["net_r"] for r in group if finite(r.get("source_score")) is not None
                                                 and low <= r["source_score"] < low+10]) for low in range(0,101,10)},
            "reason_contrasts": {c: {"present": metrics([r["net_r"] for r in known if c in r["reason_codes"]]),
                                      "known_absent": metrics([r["net_r"] for r in known if c not in r["reason_codes"]])} for c in codes},
            "status": "DESCRIPTIVE_SOURCE_PAPER_NOT_MODEL_PERFORMANCE"}
    return result


def evaluate(rows, *, holdout_groups):
    """Never refit on held-out groups. Retrospective != forward OOS, even with PIT bars."""
    forecasts, models = [], {}
    for row in primary(rows, origin={"HISTORICAL_PAPER", "HISTORICAL_PAPER_EXPORT"}):
        if row.get("label_policy") != "REVERSE_RR2":
            continue
        cutoff = row["decision_ms"]//DAY*DAY
        key = (cutoff, row["source_side"])
        if key not in models:
            models[key] = fit(rows, asof_ms=cutoff, side=row["source_side"],
                              excluded_groups=holdout_groups, retrospective=True)
        model = models[key]
        out = decision(row["features"], model, side=row["source_side"])
        forecasts.append({"sample_id": row["sample_id"], "group_id": row["group_id"], "day": day(row["decision_ms"]),
                          "regime": "BULLISH" if row["features"].get("btc_bullish") else "BEARISH" if row["features"].get("btc_bearish") else "NEUTRAL" if row["features"].get("btc_neutral") else "UNKNOWN",
                          "source_side": row["source_side"], "score": out["score"], "net_r": row["net_r"],
                          "partition": "HELD_OUT_RETROSPECTIVE" if row["group_id"] in holdout_groups else "DEVELOPMENT_WALK_FORWARD",
                          "action": out["action"], "status": out["status"], "model_id": out["model_id"]})
    by_side = {}
    for side in ("LONG", "SHORT"):
        by_side[side] = {}
        for part in ("DEVELOPMENT_WALK_FORWARD", "HELD_OUT_RETROSPECTIVE"):
            subset = [r for r in forecasts if r["source_side"] == side and r["partition"] == part and r["score"] is not None]
            by_side[side][part] = {"n": len(subset), "classifier_brier": float(np.mean([
                (r["score"]/100-(r["net_r"] > 0))**2 for r in subset])) if subset else None,
                "score_bins": {str(low): metrics([r["net_r"] for r in subset if low <= r["score"] < low+20]) for low in range(0, 101, 20)}}
            by_side[side][part]["regimes"] = {regime: {"n": sum(r["regime"] == regime for r in subset),
                "stored_outcome": metrics([r["net_r"] for r in subset if r["regime"] == regime])}
                for regime in ("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN")}
    return {"status": "RETROSPECTIVE_ONLY" if any(r["score"] is not None for r in forecasts) else "INSUFFICIENT_DATA",
            "predictions": forecasts, "per_side": by_side, "forward_oos_validated": False,
            "policy_profitability": "UNVERIFIED_NO_MATCHED_COUNTERFACTUAL_FILLS",
            "purge": "closed label before split minus 1h; one correlated cohort per fit; held-out groups excluded from every fit"}


def holdout(rows):
    selected = primary(rows, origin={"HISTORICAL_PAPER", "HISTORICAL_PAPER_EXPORT"})
    days = sorted({day(r["decision_ms"]) for r in selected})
    if len(days) < 3:
        return []
    boundary = days[max(1, int(len(days)*.8))]
    return [r["group_id"] for r in selected if day(r["decision_ms"]) >= boundary]
