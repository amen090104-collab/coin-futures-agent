"""Synthetic data below is exclusively for unit tests, never a performance claim."""
import copy
from datetime import datetime, timezone

import pytest

from app.reverse_intelligence import (VERSION, ACTIONS, eligible_rows, fit_policy,
                                      predict, metrics, walk_forward)

START = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000


def features(good=True):
    return {"source_score": 78 if good else 94, "rsi_1h": 38 if good else 68,
            "distance_ema20_atr": .5 if good else 3., "atr_pct_1h": 1.5,
            "volume_ratio_1h": 1.2 if good else 2.5, "oi_change_pct": 1.,
            "funding_rate": .0001, "relative_strength_1h_pct": -.5,
            "trend_1h_reverse": 1., "trend_4h_reverse": 1., "btc_bullish": 0., "btc_bearish": 1.}


def history(days=14, side="LONG", wait_better=False):
    rows = []
    for index in range(days):
        for j in range(8):
            observed = START + index * DAY + (j * 2 + 1) * 3600_000
            good = j < 4
            rows.append({"dataset": VERSION, "cohort_id": f"{side}-{index}-{j}", "source_side": side,
                "btc_regime": "BEARISH", "observed_at_ms": observed, "features_available_at_ms": observed - 1,
                "label_closed_at_ms": observed + 3600_000, "label_available_at_ms": observed + 7200_000,
                "quality_ok": True, "features": features(good), "outcomes": {
                    "REVERSE_NOW": 1.2 if good else -1.1,
                    "WAIT_CONFIRMATION": (1.8 if wait_better else .8) if good else -.2,
                    "BASE_CONTROL": -1. if good else 1.8}})
    return rows


@pytest.fixture(scope="module")
def trained():
    return fit_policy(history(), asof_ms=START + 15 * DAY, source_side="LONG")


def test_cold_start_has_no_fabricated_score_or_entry():
    result = predict(features(), fit_policy([], asof_ms=START, source_side="LONG"), source_side="LONG")
    assert result["score"] is None and result["action"] == "NO_TRADE"
    assert result["score_is_win_probability"] is False


def test_nested_calibration_learns_research_policy_and_preserves_cutoffs(trained):
    assert trained["status"] == "EXPLORATORY_MODEL"
    assert trained["fit_label_cutoff_ms"] < trained["calibration_start_ms"]
    assert not set(trained["fit_ids"]) & set(trained["calibration_ids"])
    decision = predict(features(), trained, source_side="LONG")
    assert decision["action"] == "REVERSE_NOW" and 0 <= decision["score"] <= 100
    assert decision["model_id"] == trained["model_id"]
    assert decision["factors"] and all("delta_score" in x for x in decision["factors"])


def test_base_can_be_better_than_reverse(trained):
    result = predict(features(False), trained, source_side="LONG")
    assert result["action"] == "NO_TRADE"
    assert result["expected_net_r"]["BASE_CONTROL"] > result["expected_net_r"]["REVERSE_NOW"]


def test_wait_confirmation_can_be_learned():
    policy = fit_policy(history(wait_better=True), asof_ms=START + 15 * DAY, source_side="LONG")
    assert predict(features(), policy, source_side="LONG")["action"] == "WAIT_CONFIRMATION"


def test_future_or_late_ingested_outcomes_cannot_change_a_frozen_model(trained):
    extra = history(side="SHORT")
    late = copy.deepcopy(history())
    for row in late:
        row["cohort_id"] += "-late"
        row["label_available_at_ms"] = START + 99 * DAY
        row["outcomes"] = {a: 9999. for a in ACTIONS}
    future = copy.deepcopy(history())
    for row in future:
        row["cohort_id"] += "-future"
        row["observed_at_ms"] += 99 * DAY
    candidate = fit_policy(history() + extra + late + future, asof_ms=START + 15 * DAY, source_side="LONG")
    assert candidate["model_id"] == trained["model_id"]


@pytest.mark.parametrize("field,value", [("quality_ok", False), ("dataset", "PAPER"),
    ("label_available_at_ms", START + 100 * DAY), ("label_closed_at_ms", 0),
    ("features_available_at_ms", START + 100 * DAY)])
def test_invalid_training_evidence_is_excluded(field, value):
    row = history(1)[0]
    row[field] = value
    assert eligible_rows([row], START + 20 * DAY, "LONG") == []


@pytest.mark.parametrize("value", [None, float("nan"), -1, 101, True])
def test_missing_or_out_of_range_features_fail_closed(trained, value):
    row = features()
    row["rsi_1h"] = value
    result = predict(row, trained, source_side="LONG")
    assert result["score"] is None and result["action"] == "NO_TRADE"


def test_opposite_source_cannot_use_a_long_source_model(trained):
    assert predict(features(), trained, source_side="SHORT")["status"] == "INVALID_SIDE"


def test_walk_forward_excludes_test_labels_and_counts_skipped_winners():
    rows = history(12)
    evaluated = walk_forward(rows)
    assert evaluated["scored_oos_n"] > 0
    for fold in evaluated["folds"]:
        if fold["label_cutoff_ms"]:
            cutoff = int(datetime.fromisoformat(fold["test_day"]).replace(tzinfo=timezone.utc).timestamp() * 1000)
            assert fold["label_cutoff_ms"] < cutoff
    # Changing only the final test day's labels must not change its decisions/models.
    altered = copy.deepcopy(rows)
    final_day = max(x["test_day"] for x in evaluated["predictions"])
    for row in altered:
        if datetime.fromtimestamp(row["observed_at_ms"]/1000, timezone.utc).date().isoformat() == final_day:
            row["outcomes"] = {a: -100. for a in ACTIONS}
    reevaluated = walk_forward(altered)
    left = [(p["cohort_id"], p["model_id"], p["action"], p["score"]) for p in evaluated["predictions"] if p["test_day"] == final_day]
    right = [(p["cohort_id"], p["model_id"], p["action"], p["score"]) for p in reevaluated["predictions"] if p["test_day"] == final_day]
    assert left == right
    assert evaluated["missed_winners"] > 0
    assert evaluated["avoided_losses"] > 0
    assert not evaluated["out_of_sample_validated"]


def test_metrics_distinguish_no_observations_and_serial_drawdown():
    assert metrics([])["expectancy_r"] is None
    values = metrics([1, -2, -1, 4])
    assert values["serial_drawdown_r"] == 3
    assert values["profit_factor_r"] == pytest.approx(5/3, abs=1e-6)
    assert metrics([0, 0])["win_rate_pct"] == 0
