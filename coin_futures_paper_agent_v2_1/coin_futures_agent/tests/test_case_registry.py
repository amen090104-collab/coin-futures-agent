from app import storage
from app.case_registry import (
    case_passes_signal,
    create_strategy_case,
    init_case_registry,
    list_strategy_cases,
    strategy_case_history,
    update_strategy_case,
)


def test_dynamic_case_create_filter_and_version(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    init_case_registry()

    seeded = list_strategy_cases()
    assert {x["short_name"] for x in seeded} >= {"A", "B", "C", "D"}

    case = create_strategy_case(
        {
            "name": "CASE E - LOW SCORE NEUTRAL",
            "direction_mode": "BASE",
            "rr": 1.0,
            "score_min": 75,
            "score_max": 84,
            "btc_regimes": ["NEUTRAL"],
            "side_filter": "BOTH",
            "min_volume_ratio": 0.9,
            "max_distance_ema20_atr": 1.8,
        }
    )
    assert case["short_name"] == "E"
    assert case["version"] == 1

    row = {
        "bias": "LONG",
        "long_score": 81,
        "short_score": 25,
        "volume_ratio_1h": 1.2,
        "oi_change_pct": 0.4,
        "funding_rate": 0.0001,
        "atr_pct_1h": 2.0,
        "distance_ema20_atr": 1.2,
    }
    assert case_passes_signal(case, row, "NEUTRAL") == (True, "PASS")
    assert case_passes_signal(case, {**row, "long_score": 89}, "NEUTRAL")[0] is False
    assert case_passes_signal(case, row, "BULLISH")[0] is False
    assert case_passes_signal(case, {**row, "distance_ema20_atr": 2.4}, "NEUTRAL")[0] is False

    changed = update_strategy_case(
        case["strategy_id"],
        {"score_min": 78, "score_max": 82, "enabled": False},
    )
    assert changed["version"] == 2
    assert changed["enabled"] is False
    history = strategy_case_history(case["strategy_id"])
    assert len(history) >= 2
    assert history[0]["version"] == 2
