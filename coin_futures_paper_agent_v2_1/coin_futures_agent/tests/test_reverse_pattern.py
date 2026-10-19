"""No network or trading: prospective pattern scoring and discovery invariants."""
from datetime import datetime, timezone, timedelta

from app.reverse_pattern import (
    compact_features, score_candidate, paper_signal_diagnostics, similarity,
)


def feature(side="SHORT", rsi=44, score=80, regime="BEARISH"):
    return compact_features({
        "rsi_1h": rsi, "distance_ema20_atr": 1.1,
        "volume_ratio_1h": 1.2, "oi_change_pct": 1.4,
        "atr_pct_1h": 2.0, "relative_strength_1h_pct": -.4,
        "trend_1h_long": False, "trend_1h_short": True,
        "trend_4h_long": False, "trend_4h_short": True,
    }, base_score=score, source_side=side, btc_regime=regime)


def example(i, *, side="SHORT", r=1.8, closed_late=False):
    base_ms = 1_700_000_000_000 + i * 86_400_000
    return {"cohort_id": f"signal-{i}-{side}", "source_side": side,
            "observed_at_ms": base_ms,
            "closed_at_ms": base_ms + (999 * 86_400_000 if closed_late else 3_600_000),
            "net_r": r, "features": feature(side=side)}


def test_no_history_never_promotes_shadow():
    out = score_candidate(feature(), [], source_side="SHORT", observed_at_ms=1_800_000_000_000)
    assert out["score"] is None and out["eligible"] is False
    assert out["status"] == "INSUFFICIENT_SIDE_HISTORY"


def test_leakage_closed_after_decision_must_not_train():
    prior = [example(i, closed_late=True) for i in range(45)]
    now = 1_700_000_000_000 + 46 * 86_400_000
    out = score_candidate(feature(), prior, source_side="SHORT", observed_at_ms=now)
    assert out["training_n"] == 0
    assert not out["eligible"]


def test_side_is_independent_even_if_opposite_has_many_winners():
    other = [example(i, side="LONG", r=1.9) for i in range(60)]
    out = score_candidate(feature(), other, source_side="SHORT", observed_at_ms=1_800_000_000_000)
    assert out["training_n"] == 0
    assert not out["eligible"]


def test_mature_positive_history_promotes_candidate_not_win_probability():
    rows = [example(i, r=1.7) for i in range(55)]
    out = score_candidate(feature(), rows, source_side="SHORT", observed_at_ms=1_800_000_000_000)
    assert out["status"] == "RESEARCH_CANDIDATE"
    assert out["eligible"] is True
    assert out["score"] > 55
    assert out["training_n"] == 55
    assert out["training_days"] == 55
    assert out["effective_n"] >= 20


def test_mature_losing_history_is_not_promoted():
    rows = [example(i, r=-1.1) for i in range(50)]
    out = score_candidate(feature(), rows, source_side="SHORT", observed_at_ms=1_800_000_000_000)
    assert out["status"] == "NO_ESTIMATED_EDGE"
    assert out["score"] < 55
    assert not out["eligible"]


def test_small_history_does_not_allow_candidate():
    rows = [example(i, r=1.8) for i in range(10)]
    out = score_candidate(feature(), rows, source_side="SHORT", observed_at_ms=1_800_000_000_000)
    assert out["status"] == "INSUFFICIENT_SIDE_HISTORY"
    assert not out["eligible"]


def test_missing_and_invalid_features_never_invent_evidence():
    candidate = compact_features({}, base_score=90, source_side="LONG", btc_regime="NEUTRAL")
    assert candidate["rsi_1h"] is None
    assert candidate["trend_1h_reverse"] is None
    out = score_candidate(candidate, [example(i, side="LONG") for i in range(40)],
                          source_side="LONG", observed_at_ms=1_800_000_000_000)
    assert out["status"] == "INSUFFICIENT_FEATURES"
    assert not out["eligible"]


def test_mismatch_has_lower_similarity_and_nan_not_accepted():
    a = feature()
    b = feature(rsi=80, score=96, regime="BULLISH")
    assert similarity(a, a)[0] > similarity(a, b)[0]
    assert compact_features({"rsi_1h": float("nan")}, base_score=90,
                            source_side="LONG", btc_regime="BEARISH")["rsi_1h"] is None


def test_historical_discovery_by_side_and_codes_is_descriptive_only():
    base = datetime(2026, 10, 10, tzinfo=timezone.utc)
    rows = []
    for i in range(40):
        codes = ["RSI_SHORT_ZONE"] if i < 20 else ["BREAKDOWN_1H"]
        rows.append({"side": "LONG",
                     "opened_at": (base + timedelta(days=i//5)).isoformat(),
                     "r_multiple": -1.0 if i < 20 else 1.8,
                     "entry_context": {"entry_thesis": {"reason_codes": codes}},
                     "exit_reason": "STOP_LOSS" if i < 20 else "TAKE_PROFIT"})
    out = paper_signal_diagnostics(rows)
    assert out["trades"] == 40
    diffs = {x["source_reason_code"]: x
             for x in out["reason_code_differences"]["LONG"]}
    assert diffs["RSI_SHORT_ZONE"]["ev_difference_r"] < 0
    assert out["by_reverse_side"]["LONG"]["all"]["n"] == 40
    assert out["status"] == "HISTORICAL_PAPER_DISCOVERY_ONLY"
