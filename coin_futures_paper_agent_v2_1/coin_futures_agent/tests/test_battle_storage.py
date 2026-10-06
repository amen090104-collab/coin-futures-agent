from app import storage
from app.battle_storage import (
    battle_account_balance,
    battle_open_positions,
    battle_recent_trades,
    close_battle_position_atomic,
    ensure_battle_initial_balances,
    init_battle_db,
    insert_battle_position,
    insert_battle_positions_atomic,
    reset_strategy_battle_data,
)


def _position(strategy_id="BASE_RR2"):
    return {
        "strategy_id": strategy_id,
        "symbol": "TESTUSDT",
        "side": "LONG",
        "opened_at": "2026-10-05T00:00:00+00:00",
        "signal_price": 100.0,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "quantity": 5.0,
        "risk_usdt": 10.0,
        "initial_risk_per_unit": 2.0,
        "score": 82.0,
        "reason_text": "battle test",
        "reason_codes": ["TEST", strategy_id],
        "entry_context": {"strategy_id": strategy_id},
    }


def _trade(strategy_id="BASE_RR2", pnl=20.0):
    return {
        "strategy_id": strategy_id,
        "symbol": "TESTUSDT",
        "side": "LONG",
        "opened_at": "2026-10-05T00:00:00+00:00",
        "closed_at": "2026-10-05T01:00:00+00:00",
        "entry_price": 100.0,
        "exit_price": 104.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "quantity": 5.0,
        "score": 82.0,
        "gross_pnl": 20.0,
        "fees": 0.0,
        "net_pnl": pnl,
        "r_multiple": 2.0,
        "exit_reason": "TAKE_PROFIT",
        "holding_minutes": 60.0,
        "mfe_r": 2.0,
        "mae_r": 0.2,
        "reason_text": "battle test",
        "reason_codes": ["TEST", strategy_id],
        "entry_context": {"strategy_id": strategy_id},
        "loss_analysis": [],
        "fix_suggestions": [],
    }


def test_battle_accounts_are_independent_and_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    init_battle_db()
    ensure_battle_initial_balances("2026-10-05T00:00:00+00:00", 10000.0)

    assert battle_account_balance("BASE_RR2") == 10000.0
    assert battle_account_balance("BASE_RR1") == 10000.0
    assert battle_account_balance("REVERSE_RR2") == 10000.0
    assert battle_account_balance("REVERSE_RR1") == 10000.0

    pid = insert_battle_position(_position("BASE_RR2"))
    tid = close_battle_position_atomic(pid, _trade()["closed_at"], _trade())

    assert tid == 1
    assert battle_account_balance("BASE_RR2") == 10020.0
    assert battle_account_balance("BASE_RR1") == 10000.0
    assert battle_account_balance("REVERSE_RR2") == 10000.0
    assert battle_account_balance("REVERSE_RR1") == 10000.0

    # Idempotent close.
    tid2 = close_battle_position_atomic(pid, _trade()["closed_at"], _trade())
    assert tid2 == tid
    assert battle_account_balance("BASE_RR2") == 10020.0
    assert len(battle_recent_trades(10, "BASE_RR2")) == 1


def test_reset_clears_old_history_and_restarts_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    init_battle_db()
    ensure_battle_initial_balances("2026-10-05T00:00:00+00:00", 10000.0)

    pid = insert_battle_position(_position("BASE_RR2"))
    close_battle_position_atomic(pid, _trade()["closed_at"], _trade())
    assert len(battle_recent_trades(10)) == 1

    result = reset_strategy_battle_data(10000.0)

    assert result["starting_balance_each"] == 10000.0
    assert battle_recent_trades(10) == []
    assert battle_open_positions() == []
    assert battle_account_balance("BASE_RR2") == 10000.0
    assert battle_account_balance("BASE_RR1") == 10000.0
    assert battle_account_balance("REVERSE_RR2") == 10000.0
    assert battle_account_balance("REVERSE_RR1") == 10000.0

    # AUTOINCREMENT is reset for a genuinely fresh experiment.
    assert insert_battle_position(_position("BASE_RR2")) == 1


def test_atomic_cohort_insert_creates_all_four(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    init_battle_db()
    ensure_battle_initial_balances("2026-10-05T00:00:00+00:00", 10000.0)

    cohort = [
        _position("BASE_RR2"),
        _position("BASE_RR1"),
        _position("REVERSE_RR2"),
        _position("REVERSE_RR1"),
    ]
    ids = insert_battle_positions_atomic(cohort)

    assert ids == [1, 2, 3, 4]
    xs = battle_open_positions()
    assert len(xs) == 4
    assert {x["strategy_id"] for x in xs} == {
        "BASE_RR2",
        "BASE_RR1",
        "REVERSE_RR2",
        "REVERSE_RR1",
    }
