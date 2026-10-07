from app import storage
from app.battle_storage import init_battle_db, battle_account_balance
from app.strategy_cases import (
    init_strategy_cases,
    list_strategy_cases,
    create_strategy_case,
    update_strategy_case,
    clone_strategy_case,
    case_accepts_signal,
)


def test_dynamic_case_crud_and_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    init_battle_db()
    init_strategy_cases()

    assert len(list_strategy_cases()) >= 4

    case = create_strategy_case({
        "strategy_id": "BASE_LOW_SCORE",
        "name": "Low score base",
        "short_name": "E",
        "direction_mode": "BASE",
        "rr": 1.0,
        "score_min": 75,
        "score_max": 84.9,
        "allowed_regimes": ["NEUTRAL"],
        "side_filter": "BOTH",
        "risk_pct": 0.1,
        "max_open": 10,
    })
    assert case["version"] == 1
    assert battle_account_balance("BASE_LOW_SCORE") == 10000.0

    row = {
        "long_score": 80,
        "short_score": 20,
        "volume_ratio_1h": 1.2,
        "oi_change_pct": 0.5,
        "atr_pct_1h": 2.0,
    }
    assert case_accepts_signal(case, row, "LONG", "NEUTRAL")[0] is True
    assert case_accepts_signal(case, {**row, "long_score": 90}, "LONG", "NEUTRAL")[0] is False
    assert case_accepts_signal(case, row, "LONG", "BULLISH")[0] is False

    updated = update_strategy_case("BASE_LOW_SCORE", {"score_max": 82})
    assert updated["version"] == 2
    clone = clone_strategy_case("BASE_LOW_SCORE", {
        "strategy_id": "BASE_LOW_SCORE_CLONE",
        "short_name": "F",
    })
    assert clone["enabled"] is False
    assert clone["version"] == 1
