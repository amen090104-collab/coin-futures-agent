from app import storage
from app.decision_journal import (
    init_decision_journal, record_open, record_exit,
    record_milestones, journal_for_trade,
)


def position():
    return {
        "id": 15, "strategy_id": "BASE_RR1", "symbol": "BTCUSDT",
        "side": "LONG", "opened_at": "2026-10-07T00:00:00+00:00",
        "entry_price": 100.0, "stop_loss": 98.0, "take_profit": 102.0,
        "max_favorable_price": 100, "reason_text": "Volume and breakout",
        "entry_context": {"entry_thesis": {"primary_reason": "Breakout"}},
    }


def test_journal_persists_entry_milestone_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    storage.init_db()
    init_decision_journal()
    p = position()
    record_open(15, p)
    record_open(15, p)  # idempotent
    record_milestones(p, {
        "favorable": 102.1, "closed_at": "2026-10-07T00:01:00+00:00"
    })
    t = {
        "id": 42, "position_id": 15, "strategy_id": "BASE_RR1",
        "symbol": "BTCUSDT", "opened_at": p["opened_at"],
        "closed_at": "2026-10-07T00:05:00+00:00",
        "exit_reason": "TAKE_PROFIT", "exit_price": 102,
        "net_pnl": 1.8, "r_multiple": 0.9,
        "entry_context": p["entry_context"],
    }
    record_exit(p, 42, t)
    events = journal_for_trade(t)
    assert events[0]["event_type"] == "ENTRY"
    assert len([x for x in events if x["event_type"] == "ENTRY"]) == 1
    assert len([x for x in events if x["event_type"] == "MILESTONE"]) == 2
    assert events[-1]["event_type"] == "EXIT"
    assert all(x["source"] == "PERSISTED" for x in events)


def test_older_trade_is_labelled_reconstructed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    storage.init_db()
    init_decision_journal()
    old = {
        "id": 1, "position_id": 123456, "strategy_id": "BASE_RR2",
        "symbol": "BTCUSDT", "opened_at": "2026-10-07T00:00:00+00:00",
        "closed_at": "2026-10-07T00:05:00+00:00", "exit_reason": "STOP_LOSS",
        "entry_context": {},
    }
    events = journal_for_trade(old)
    assert len(events) == 2
    assert all(x["source"] == "RECONSTRUCTED" for x in events)
