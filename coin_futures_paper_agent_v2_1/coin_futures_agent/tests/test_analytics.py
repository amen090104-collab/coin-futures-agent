from app.analytics import build_dashboard_analytics, enrich_open_position


def test_enrich_open_position_long_profit():
    p = {
        "side": "LONG",
        "entry_price": 100,
        "last_price": 105,
        "quantity": 2,
        "risk_usdt": 10,
        "stop_loss": 95,
        "take_profit": 110,
        "opened_at": "2026-10-04T10:00:00+00:00",
    }
    out = enrich_open_position(p, fee_bps=0)
    assert out["unrealized_pnl"] == 10
    assert out["unrealized_r"] == 1
    assert out["notional_usdt"] == 210


def test_dashboard_analytics_summary():
    trades = [
        {
            "side": "LONG",
            "closed_at": "2026-10-03T10:00:00+00:00",
            "net_pnl": 20,
            "r_multiple": 1.0,
            "reason_codes": '["TREND_1H_UP"]',
        },
        {
            "side": "SHORT",
            "closed_at": "2026-10-04T10:00:00+00:00",
            "net_pnl": -10,
            "r_multiple": -0.5,
            "reason_codes": '["TREND_1H_DOWN"]',
        },
    ]
    positions = [{
        "side": "LONG",
        "entry_price": 100,
        "last_price": 102,
        "quantity": 1,
        "risk_usdt": 5,
        "stop_loss": 95,
        "take_profit": 110,
        "opened_at": "2026-10-04T10:00:00+00:00",
    }]
    out = build_dashboard_analytics(trades, positions, 10010, "Asia/Ho_Chi_Minh", fee_bps=0)
    assert out["realized_pnl"] == 10
    assert out["unrealized_pnl"] == 2
    assert out["equity"] == 10012
    assert out["closed"] == 2
    assert out["wins"] == 1
    assert len(out["daily"]) == 2
