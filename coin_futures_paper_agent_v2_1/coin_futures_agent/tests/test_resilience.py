import pandas as pd

from app import storage
from app.paper import evaluate_position_candle


def _position():
    return {
        "id": 1,
        "symbol": "TESTUSDT",
        "side": "LONG",
        "opened_at": "2026-10-05T00:00:00+00:00",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "quantity": 1.0,
        "risk_usdt": 5.0,
        "initial_risk_per_unit": 5.0,
        "score": 80.0,
        "reason_text": "test",
        "reason_codes": "[]",
        "entry_context": "{}",
        "max_favorable_price": 100.0,
        "max_adverse_price": 100.0,
        "last_price": 100.0,
        "updated_at": "2026-10-05T00:00:00+00:00",
    }


def _trade(net_pnl=10.0):
    return {
        "symbol": "TESTUSDT",
        "side": "LONG",
        "opened_at": "2026-10-05T00:00:00+00:00",
        "closed_at": "2026-10-05T01:00:00+00:00",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "quantity": 1.0,
        "score": 80.0,
        "gross_pnl": 10.0,
        "fees": 0.0,
        "net_pnl": net_pnl,
        "r_multiple": 2.0,
        "exit_reason": "TAKE_PROFIT",
        "holding_minutes": 60.0,
        "mfe_r": 2.0,
        "mae_r": 0.2,
        "reason_text": "test",
        "reason_codes": [],
        "entry_context": {},
        "loss_analysis": [],
        "fix_suggestions": [],
    }


def test_evaluate_position_candle_hits_stop():
    candle = pd.Series({
        "open": 100.0,
        "high": 103.0,
        "low": 94.0,
        "close": 96.0,
        "close_time": 1791162059000,
    })
    out = evaluate_position_candle(_position(), candle)
    assert out["exit_reason"] == "STOP_LOSS"
    assert out["raw_exit"] == 95.0
    assert out["favorable"] == 103.0
    assert out["adverse"] == 94.0


def test_atomic_close_books_trade_and_balance(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    storage.ensure_initial_balance("2026-10-05T00:00:00+00:00", 10000.0)
    p = _position()
    pid = storage.insert_position({
        **p,
        "signal_price": 100.0,
        "opened_at": p["opened_at"],
    })
    tid = storage.close_position_atomic(pid, _trade()["closed_at"], _trade())
    assert tid > 0
    assert storage.account_balance() == 10010.0
    assert storage.open_positions() == []
    assert len(storage.recent_trades(10)) == 1

    # Idempotent if recovery attempts to persist the same close twice.
    tid2 = storage.close_position_atomic(pid, _trade()["closed_at"], _trade())
    assert tid2 == tid
    assert storage.account_balance() == 10010.0
    assert len(storage.recent_trades(10)) == 1


def test_reconcile_legacy_missing_pnl_event(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    storage.ensure_initial_balance("2026-10-05T00:00:00+00:00", 10000.0)
    p = _position()
    pid = storage.insert_position({
        **p,
        "signal_price": 100.0,
        "opened_at": p["opened_at"],
    })
    storage.close_position(pid, _trade()["closed_at"], _trade())
    assert storage.account_balance() == 10000.0
    assert storage.reconcile_trade_pnl_events() == 1
    assert storage.account_balance() == 10010.0
    assert storage.reconcile_trade_pnl_events() == 0


def test_database_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    storage.ensure_initial_balance("2026-10-05T00:00:00+00:00", 10000.0)
    path = storage.backup_database(str(tmp_path / "backups"), retention=3)
    assert (tmp_path / "backups").exists()
    assert storage.Path(path).exists()
