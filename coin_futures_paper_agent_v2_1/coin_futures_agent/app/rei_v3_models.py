"""V3.4: calibrated historical research and genuinely future frozen models.

Event-time chronology and actual label arrival are different clocks. A model
created NOW may learn old outcomes imported before NOW, without pretending
those labels existed at an old calibration date or backdating any prediction.
"""
import json
import math

import numpy as np

from .rei_v3_learning import (DAY, EMBARGO, MIN_TRAIN, MIN_CAL, primary, fit_binary,
                              estimate, holdout)
from .reverse_intelligence import digest, day, metrics, finite

MODEL_VERSION = "rei-v3.4-calibrated-1"


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x, -30, 30)))


def calibrate_fit(raw, labels):
    """Regularized Platt calibration, fit only on a later chronological partition."""
    z = np.log(np.clip(raw, 1e-6, 1-1e-6)/(1-np.clip(raw, 1e-6, 1-1e-6)))
    center, scale = float(np.mean(z)), max(float(np.std(z)), 1e-6)
    x = np.column_stack([np.ones(len(z)), (z-center)/scale])
    y = np.array(labels, dtype=float)
    w = np.array([math.log((y.sum()+1)/(len(y)-y.sum()+1)), 0.])
    for _ in range(300):
        penalty = np.array([0., .05*w[1]])
        w -= .1*(x.T@(sigmoid(x@w)-y)/len(y)+penalty)
    return {"method": "regularized_platt", "weights": w.tolist(), "center": center, "scale": scale,
            "n": len(y), "wins": int(y.sum()), "losses": int(len(y)-y.sum())}


def calibrated_score(model, features):
    if model.get("status") != "RESEARCH_CLASSIFIER" or not model.get("calibrated"):
        return None
    raw = min(1-1e-6, max(1e-6, estimate(model["model"], features)))
    c = model["calibrator"]
    z = (math.log(raw/(1-raw))-c["center"])/c["scale"]
    return float(100*sigmoid(c["weights"][0]+c["weights"][1]*z))


def train(rows, *, frozen_at_ms, side, kind, excluded_groups=(), label_cutoff_ms=None):
    retrospective = kind == "HISTORICAL_RESEARCH_MODEL"
    known = "historical_label_known_ms" if retrospective else "label_available_ms"
    cutoff = frozen_at_ms if label_cutoff_ms is None else label_cutoff_ms
    chosen = primary(rows, source_side=side, origin={"HISTORICAL_PAPER", "HISTORICAL_PAPER_EXPORT"})
    excluded = set(excluded_groups)
    selected = [r for r in chosen if r.get("label_policy") == "REVERSE_RR2" and r["group_id"] not in excluded
                and 0 < r.get(known, 0) < cutoff-EMBARGO and r["closed_ms"] < cutoff-EMBARGO][-2000:]
    if not retrospective:
        selected = [r for r in selected if all(w.get('fetched_at_ms',0) <= frozen_at_ms
                    for w in r.get('feature_provenance',{}).get('windows',[]))]
    out = {"version": MODEL_VERSION, "model_kind": kind, "source_side": side,
           "status": "INSUFFICIENT_DATA", "calibrated": False, "training_n": len(selected),
           "frozen_at_ms": frozen_at_ms, "asof_ms": cutoff, "label_clock": known,
           "historical_calibration_is_retrospective": True, "forward_oos_validated": False,
           "first_forward_decision_ms": frozen_at_ms if not retrospective else None,
           "reason_codes": [], "fit_n": 0, "calibration_n": 0,
           "fit_days": 0, "calibration_days": 0, "embargo_ms": EMBARGO,
           "holdout_excluded_groups": len(excluded)}
    days = sorted({day(r["decision_ms"]) for r in selected})
    out["training_days"] = len(days)
    if len(days) < 9:
        out["reason_codes"] = ["INSUFFICIENT_TRAINING_DAYS"]
        return out
    boundary = next(r["decision_ms"]//DAY*DAY for r in selected if day(r["decision_ms"]) == days[-2])
    calibration = [r for r in selected if r["decision_ms"] >= boundary]
    # Purge overlapping event/outcome intervals. Arrival is checked at the real
    # freeze, NOT falsely against an event-time split that predates the import.
    fitting = [r for r in selected if r["decision_ms"] < boundary-EMBARGO and r["closed_ms"] < boundary-EMBARGO]
    out.update(fit_n=len(fitting), calibration_n=len(calibration),
               fit_days=len({day(r["decision_ms"]) for r in fitting}),
               calibration_days=len({day(r["decision_ms"]) for r in calibration}),
               calibration_start_ms=boundary, split_purged_n=len(selected)-len(fitting)-len(calibration))
    for condition, reason in ((len(fitting) < MIN_TRAIN, "INSUFFICIENT_FIT_SAMPLES"),
                              (len(calibration) < MIN_CAL, "INSUFFICIENT_CALIBRATION_SAMPLES"),
                              (out["fit_days"] < 7, "INSUFFICIENT_FIT_DAYS"),
                              (len({r["net_r"] > 0 for r in fitting}) < 2, "FIT_ONE_CLASS"),
                              (len({r["net_r"] > 0 for r in calibration}) < 2, "CALIBRATION_ONE_CLASS")):
        if condition: out["reason_codes"].append(reason)
    if out["reason_codes"]: return out
    candidates = []
    y = np.array([r["net_r"] > 0 for r in calibration], dtype=float)
    for family in ("logistic_l2", "empirical_neighbors"):
        m = fit_binary(fitting, family)
        raw = np.array([estimate(m, r["features"]) for r in calibration])
        candidates.append((float(np.mean((raw-y)**2)), family, m, raw))
    brier, family, model, raw = min(candidates, key=lambda c: (c[0], c[1]))
    calibrator = calibrate_fit(raw, y)
    selected_manifest = [{k: r.get(k) for k in ("sample_id", "group_id", "features", "net_r", "decision_ms", "closed_ms", known)} for r in selected]
    out.update(status="RESEARCH_CLASSIFIER", calibrated=True, model=model, calibrator=calibrator,
               family=family, raw_calibration_brier=brier,
               fit_groups=[r["group_id"] for r in fitting], calibration_groups=[r["group_id"] for r in calibration],
               fit_window_ms=[fitting[0]["decision_ms"], fitting[-1]["decision_ms"]],
               calibration_window_ms=[calibration[0]["decision_ms"], calibration[-1]["decision_ms"]],
               max_fit_closed_ms=max(r["closed_ms"] for r in fitting),
               max_label_ms=max(r[known] for r in selected), training_digest=digest(selected_manifest),
               calibration_basis="historical_chronological_selection_and_calibrator_fit_not_forward_OOS")
    calibrated = [calibrated_score(out, r["features"])/100 for r in calibration]
    out["calibration_fit_brier"] = float(np.mean((np.array(calibrated)-y)**2))
    out["model_id"] = digest(out)
    return out


def frozen(db, rows, *, now_ms, held=()):
    """Never rewrite legacy models. A failed attempt isn't a frozen learned model."""
    result = {}
    for side in ("LONG", "SHORT"):
        key = f"v34::FORWARD_FROZEN_MODEL::{now_ms//DAY}::{side}"
        old = db.execute("SELECT payload FROM rei_v3_models WHERE model_id=?", (key,)).fetchone()
        model = json.loads(old[0]) if old else train(rows, frozen_at_ms=now_ms, side=side,
                kind="FORWARD_FROZEN_MODEL", excluded_groups=held)
        if not old and model["status"] == "RESEARCH_CLASSIFIER":
            db.execute("INSERT OR IGNORE INTO rei_v3_models VALUES(?,?,?,?)", (key, now_ms, side, json.dumps(model, allow_nan=False)))
            model = json.loads(db.execute("SELECT payload FROM rei_v3_models WHERE model_id=?", (key,)).fetchone()[0])
        elif not old:
            db.execute("INSERT OR REPLACE INTO rei_v3_runs VALUES(?,?,?)", (
                "v34-attempt::"+side, now_ms, json.dumps(model, allow_nan=False)))
        result[side] = model
    db.commit()
    return result


def research_baseline(rows, *, now_ms, held):
    models, predictions = {}, []
    folds = {}
    for side in ("LONG", "SHORT"):
        models[side] = train(rows, frozen_at_ms=now_ms, side=side, kind="HISTORICAL_RESEARCH_MODEL", excluded_groups=held)
    for r in primary(rows, origin={"HISTORICAL_PAPER", "HISTORICAL_PAPER_EXPORT"}):
        if r.get("label_policy") != "REVERSE_RR2": continue
        cutoff = r["decision_ms"]//DAY*DAY
        key = (cutoff, r["source_side"])
        if key not in folds:
            folds[key] = train(rows, frozen_at_ms=cutoff, side=r["source_side"], kind="HISTORICAL_RESEARCH_MODEL", excluded_groups=held)
        m = folds[key]
        score = calibrated_score(m, r["features"])
        predictions.append({"sample_id": r["sample_id"], "group_id": r["group_id"], "source_side": r["source_side"],
            "decision_ms": r["decision_ms"], "score": score, "net_r": r["net_r"], "model_id": m.get("model_id"),
            "partition": "HELD_OUT_RETROSPECTIVE" if r["group_id"] in held else "DEVELOPMENT_WALK_FORWARD"})
    def measure(group):
        scored = [r for r in group if r["score"] is not None]
        return {"records": len(group), "scored": len(scored),
                "brier": float(np.mean([(r["score"]/100-(r["net_r"] > 0))**2 for r in scored])) if scored else None,
                "stored_outcomes": metrics([r["net_r"] for r in scored]),
                "basis": "stored_source_net_R_not_V3_policy_profit"}
    manifest = {"version": MODEL_VERSION, "created_at_ms": now_ms, "dataset_digest": digest([
        {k: r.get(k) for k in ("sample_id", "group_id", "features", "net_r", "decision_ms", "closed_ms", "label_available_ms")}
        for r in rows]), "holdout_digest": digest(sorted(held)), "holdout_groups": len(held),
        "folds": [{"asof_ms": k[0], "source_side": k[1], "status": m["status"], "model_id": m.get("model_id"),
                   "fit_n": m["fit_n"], "calibration_n": m["calibration_n"], "max_label_ms": m.get("max_label_ms")}
                  for k, m in folds.items()], "forward_oos_validated": False}
    manifest["manifest_id"] = digest(manifest)
    return {"manifest": manifest, "models": models, "predictions": predictions,
            "per_side": {side: {part: measure([r for r in predictions if r["source_side"] == side and r["partition"] == part])
                                for part in ("HELD_OUT_RETROSPECTIVE", "DEVELOPMENT_WALK_FORWARD")}
                         for side in ("LONG", "SHORT")}}
