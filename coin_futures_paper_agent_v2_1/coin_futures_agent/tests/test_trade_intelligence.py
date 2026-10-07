from app.trade_intelligence import attribute_trade


def _trade(pnl=10.0, side="LONG"):
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "opened_at": "2026-10-07T00:00:00+00:00",
        "closed_at": "2026-10-07T01:00:00+00:00",
        "net_pnl": pnl,
        "exit_reason": "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
        "mfe_r": 1.0 if pnl > 0 else 0.2,
        "mae_r": -0.2 if pnl > 0 else -1.0,
        "entry_context": {"distance_ema20_atr": 0.5},
    }


def test_news_assisted_win_is_not_called_pure_thesis_win():
    news = [{
        "published_at": "2026-10-07T00:20:00+00:00",
        "impact_score": 90,
        "sentiment": "BULLISH",
        "source": "Official",
        "title": "Major positive event",
        "url": "https://example.com/event",
    }]
    result = attribute_trade(_trade(10.0, "LONG"), news)
    assert result["classification"] == "NEWS_ASSISTED_WIN"
    assert result["external_influence"] == "HIGH"


def test_plain_win_can_confirm_thesis():
    result = attribute_trade(_trade(10.0, "LONG"), [])
    assert result["classification"] == "THESIS_CONFIRMED"
