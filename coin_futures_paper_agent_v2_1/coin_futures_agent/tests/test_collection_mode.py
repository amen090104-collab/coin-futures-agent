from app.config import settings
from app.paper import execution_policy


def test_collection_mode_policy(monkeypatch):
    monkeypatch.setattr(settings, "data_collection_mode", True)
    monkeypatch.setattr(settings, "collection_max_open_trades", 50)
    monkeypatch.setattr(settings, "top_n_coins", 50)
    monkeypatch.setattr(settings, "collection_risk_per_trade_pct", 0.10)

    p = execution_policy()
    assert p["max_open_trades"] == 50
    assert p["max_new_trades_per_scan"] is None
    assert p["risk_per_trade_pct"] == 0.10
    assert p["enforce_daily_loss_guard"] is False


def test_normal_mode_policy(monkeypatch):
    monkeypatch.setattr(settings, "data_collection_mode", False)
    monkeypatch.setattr(settings, "max_open_trades", 5)
    monkeypatch.setattr(settings, "max_new_trades_per_scan", 3)
    monkeypatch.setattr(settings, "risk_per_trade_pct", 0.50)

    p = execution_policy()
    assert p["max_open_trades"] == 5
    assert p["max_new_trades_per_scan"] == 3
    assert p["risk_per_trade_pct"] == 0.50
    assert p["enforce_daily_loss_guard"] is True
