"""Autonomous, bounded OFFLINE Reverse hypothesis experiments.

Only compares selection rules against trades that really closed. No altered
entry/exit price is fabricated and no strategy is pushed into Trading Bot.
One pre-declared candidate family per archived-data revision. Holds out recent
days until candidate selection is frozen on historical validation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import math
import random
import statistics

MIN_TRAIN_TRADES = 40
MIN_VAL_TRADES = 20
MIN_TEST_TRADES = 20
MIN_VAL_SELECTED = 8
MIN_TEST_SELECTED = 8
MIN_DAYS = 12
BOOTSTRAP_ITERATIONS = 300


@dataclass(frozen=True)
class Hypothesis:
    id: str
    rationale: str
    field: str
    comparator: str
    boundary: float | str
    scope: str = "REVERSE"


# Fixed a priori universe: no unbounded random search and no peeking at test
# data to invent thresholds. New versions need a new experiment protocol ID.
PROTOCOL = "reverse-experiments-predeclared-v1"
HYPOTHESES = (
    Hypothesis("high_score_80", "Reverse scores 80+ may be more reliable", "score", ">=", 80.0),
    Hypothesis("high_score_85", "Reverse scores 85+ may avoid weak signals", "score", ">=", 85.0),
    Hypothesis("volume_ge_1_20", "Above-average volume confirms reversal", "volume_ratio_1h", ">=", 1.20),
    Hypothesis("volume_ge_1_50", "Very high volume confirms reversal", "volume_ratio_1h", ">=", 1.50),
    Hypothesis("atr_le_1_50", "Lower volatility may avoid immediate stopouts", "atr_pct_1h", "<=", 1.50),
    Hypothesis("atr_le_2_50", "Cap excessive volatility", "atr_pct_1h", "<=", 2.50),
    Hypothesis("rsi_neutral_35_65", "Avoid extreme RSI in reversal entries", "rsi_1h", "between", "35:65"),
    Hypothesis("rsi_neutral_40_60", "Require a narrower RSI band", "rsi_1h", "between", "40:60"),
    Hypothesis("btc_with_trade_side", "Trade only with BTC direction", "btc_regime", "agree", "SIDE"),
    Hypothesis("btc_against_trade_side", "Countertrend reversals may outperform", "btc_regime", "disagree", "SIDE"),
)
REVERSE_IDS = frozenset(("REVERSE_RR1", "REVERSE_RR2", "CASE_E", "CASE_F"))


def _value(row, field):
    return row.get("feature_values", {}).get(field)


def applies(rule: Hypothesis, row: dict) -> bool:
    if rule.scope == "REVERSE" and row.get("strategy_id") not in REVERSE_IDS:
        return False
    value = _value(row, rule.field)
    if rule.comparator in ("agree", "disagree"):
        if not isinstance(value, str):
            return False
        value = value.upper()
        bull = value in ("BULL", "BULLISH", "UP", "UPTREND")
        bear = value in ("BEAR", "BEARISH", "DOWN", "DOWNTREND")
        if not (bull or bear):
            return False
        same = (bull and row.get("side") == "LONG") or (bear and row.get("side") == "SHORT")
        return same if rule.comparator == "agree" else not same
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        return False
    if rule.comparator == ">=":
        return value >= float(rule.boundary)
    if rule.comparator == "<=":
        return value <= float(rule.boundary)
    if rule.comparator == "between":
        low, high = map(float, str(rule.boundary).split(":"))
        return low <= value <= high
    return False


def _stats(rows):
    values = [float(x["r_multiple"]) for x in rows if x.get("r_multiple") is not None]
    if len(values) != len(rows) or not rows:
        return {"sample": len(rows), "known_R": len(values), "mean_R": None,
                "total_R": None, "winrate": None}
    wins = sum(x["net_pnl"] > 0 for x in rows)
    return {"sample": len(rows), "known_R": len(values),
            "mean_R": round(statistics.mean(values), 5),
            "total_R": round(sum(values), 5),
            "winrate": round(wins/len(rows), 5)}


def _paired_day_delta(rows, rule):
    days = defaultdict(list)
    for x in rows:
        days[x["opened_at"][:10]].append(x)
    result = []
    for _, day in sorted(days.items()):
        baseline = _stats(day)
        selected = _stats([x for x in day if applies(rule, x)])
        if baseline["mean_R"] is not None and selected["mean_R"] is not None:
            result.append(selected["mean_R"] - baseline["mean_R"])
    return result


def _ci_by_day(values, *, seed):
    if len(values) < 5:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        draws.append(statistics.mean(rng.choice(values) for _ in values))
    draws.sort()
    return [round(draws[int(.025 * (len(draws)-1))], 4),
            round(draws[int(.975 * (len(draws)-1))], 4)]


def _folds(rows):
    usable = [x for x in rows if x.get("strategy_id") in REVERSE_IDS
              and x.get("r_multiple") is not None
              and x.get("opened_at") and x.get("closed_at")
              and math.isfinite(float(x["r_multiple"]))]
    usable.sort(key=lambda x: (x["opened_at"], x["id"]))
    days = sorted({x["opened_at"][:10] for x in usable})
    if len(days) < MIN_DAYS:
        return None, {"status": "INSUFFICIENT_INDEPENDENT_DAYS", "days": len(days)}
    train_cut = max(1, int(len(days) * .60))
    val_cut = max(train_cut+1, int(len(days) * .80))
    train_days, val_days, test_days = [set(days[:train_cut]),
                                       set(days[train_cut:val_cut]),set(days[val_cut:])]
    tr = [x for x in usable if x["opened_at"][:10] in train_days]
    va = [x for x in usable if x["opened_at"][:10] in val_days]
    te = [x for x in usable if x["opened_at"][:10] in test_days]
    if not va or not te:
        return None, {"status": "INSUFFICIENT_FOLDS", "days": len(days)}
    va_start = min(x["opened_at"] for x in va)
    te_start = min(x["opened_at"] for x in te)
    # Purge unresolved labels not known at the beginning of the next fold.
    tr_visible = [x for x in tr if x["closed_at"] <= va_start]
    va_visible = [x for x in va if x["closed_at"] <= te_start]
    if (len(tr_visible) < MIN_TRAIN_TRADES or len(va_visible) < MIN_VAL_TRADES
            or len(te) < MIN_TEST_TRADES):
        return None, {"status": "INSUFFICIENT_VISIBLE_LABELS",
                      "train": len(tr_visible), "validation": len(va_visible),
                      "test": len(te), "purged": len(tr)-len(tr_visible)+len(va)-len(va_visible)}
    return (tr_visible, va_visible, te), {"status": "READY", "days": len(days),
                                        "train_days": len(train_days),
                                        "validation_days": len(val_days),
                                        "test_days": len(test_days)}


def run_experiments(rows):
    splits, audit = _folds(rows)
    output = {"protocol": PROTOCOL, "experiment_count": len(HYPOTHESES),
              "status": audit["status"], "folds": audit,
              "auto_changed_trading_configuration": False,
              "real_orders": 0, "paper_orders": 0,
              "experimental_family_is_preregistered": True,
              "untouched_test_used_only_once_after_validation": True,
              "candidate_recommendation": None,
              "results": []}
    if splits is None:
        return output
    train, validation, test = splits
    base_val, base_test = _stats(validation), _stats(test)
    valid = []
    for rule in HYPOTHESES:
        found = [x for x in validation if applies(rule, x)]
        stats = _stats(found)
        enough = (len(found) >= MIN_VAL_SELECTED
                  and len({x["opened_at"][:10] for x in found}) >= 3
                  and stats["mean_R"] is not None)
        delta = (stats["mean_R"] - base_val["mean_R"]) if enough else None
        found_days = _paired_day_delta(validation, rule) if enough else []
        valid.append({"id": rule.id, "hypothesis": rule.rationale,
                      "validation": stats, "validation_vs_baseline_R": round(delta,5)
                      if delta is not None else None,
                      "validation_days_compared": len(found_days),
                      "status": "ELIGIBLE" if enough and len(found_days) >= 3
                      else "INSUFFICIENT_VALIDATION"})
    output["results"] = valid
    candidates = [a for a in valid if a["status"] == "ELIGIBLE"
                  and a["validation_vs_baseline_R"] > 0]
    output["validation_baseline"] = base_val
    output["test_baseline"] = base_test
    if not candidates:
        output["status"] = "NO_VALIDATED_CANDIDATE"
        return output
    # Multiple hypothesis comparisons: pick only one on validation,
    # test is not touched until choice has been frozen. Never re-rank by test.
    winner = max(candidates, key=lambda x: (x["validation_vs_baseline_R"], x["id"]))
    rule = next(r for r in HYPOTHESES if r.id == winner["id"])
    selected = [x for x in test if applies(rule, x)]
    stats = _stats(selected)
    paired = _paired_day_delta(test, rule)
    ci = _ci_by_day(paired, seed=int(hashlib.sha256(
        rule.id.encode("utf-8")).hexdigest()[:8],16))
    passed = bool(
        len(selected) >= MIN_TEST_SELECTED
        and len({x["opened_at"][:10] for x in selected}) >= 5
        and stats["mean_R"] is not None and base_test["mean_R"] is not None
        and stats["mean_R"] > base_test["mean_R"]
        and ci is not None and ci[0] > 0
    )
    output["selected_by_validation"] = winner["id"]
    output["held_out_test"] = {
        "selected": stats, "baseline": base_test,
        "paired_day_delta_R_ci95_descriptive": ci,
        "test_days_with_both": len(paired),
        "pass_exploratory_gate": passed,
    }
    output["status"] = ("PROVISIONAL_REQUIRES_FORWARD_OBSERVATION"
                        if passed else "HOLDOUT_NOT_CONVINCING")
    output["candidate_recommendation"] = ({"id": winner["id"],
                                           "status": output["status"],
                                           "deployment": "NOT_PERMITTED",
                                           "next": "Accumulate unseen forward days without retuning this selection."}
                                          if passed else None)
    output["limitations"] = ("Single fixed holdout, selected after multiple validation trials; "
                             "repeated daily reads are NOT independent holdout retests. "
                             "Historical skipped trades may change later exposure and risk. "
                             "Must run real chronological OHLC paper replay and forward shadow "
                             "before considering any change to six-case trading.")
    return output
