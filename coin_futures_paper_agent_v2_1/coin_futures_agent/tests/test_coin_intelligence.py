from app import coin_intelligence as ci


def _trade(
    trade_id: int,
    symbol: str,
    strategy_id: str,
    side: str,
    pnl: float,
    r: float,
    score: float,
    regime: str,
):
    return {
        "id": trade_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "opened_at": "2026-10-07T00:00:00+00:00",
        "closed_at": "2026-10-07T01:00:00+00:00",
        "entry_price": 100,
        "exit_price": 101 if pnl > 0 else 99,
        "stop_loss": 98,
        "take_profit": 102,
        "score": score,
        "net_pnl": pnl,
        "r_multiple": r,
        "holding_minutes": 60,
        "mfe_r": 1.2 if pnl > 0 else 0.3,
        "mae_r": 0.3 if pnl > 0 else 1.0,
        "exit_reason": "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
        "entry_context": {"btc_regime": regime},
        "reason_codes": [],
        "loss_analysis": [],
        "fix_suggestions": [],
    }


def test_normalize_symbol():
    assert ci.normalize_symbol("btc") == "BTCUSDT"
    assert ci.normalize_symbol("ethusdt") == "ETHUSDT"


def test_coin_performance_groups_case_side_and_regime(monkeypatch):
    monkeypatch.setattr(
        ci,
        "list_strategy_cases",
        lambda include_archived=True: [
            {"strategy_id": "A", "name": "Case A", "short_name": "A"},
            {"strategy_id": "B", "name": "Case B", "short_name": "B"},
        ],
    )
    trades = [
        _trade(1, "BTCUSDT", "A", "LONG", 10, 1.0, 80, "NEUTRAL"),
        _trade(2, "BTCUSDT", "A", "LONG", -10, -1.0, 81, "NEUTRAL"),
        _trade(3, "BTCUSDT", "B", "SHORT", 20, 2.0, 90, "BULLISH"),
        _trade(4, "ETHUSDT", "A", "LONG", -5, -0.5, 78, "NEUTRAL"),
    ]
    rows = ci.coin_performance_summary(trades)
    btc = next(x for x in rows if x["symbol"] == "BTCUSDT")
    assert btc["trades"] == 3
    assert btc["wins"] == 2
    assert btc["net_pnl"] == 20.0
    assert btc["by_case"]["B"]["expectancy_r"] == 2.0
    assert btc["by_side"]["SHORT"]["win_rate"] == 100.0
    assert btc["by_regime"]["BULLISH"]["net_pnl"] == 20.0
    assert btc["best_case"] == "B"


def test_stats_track_drawdown_mfe_and_mae(monkeypatch):
    monkeypatch.setattr(
        ci,
        "list_strategy_cases",
        lambda include_archived=True: [{"strategy_id": "A", "name": "A", "short_name": "A"}],
    )
    trades = [
        _trade(1, "SOLUSDT", "A", "LONG", 10, 1.0, 80, "NEUTRAL"),
        _trade(2, "SOLUSDT", "A", "LONG", -15, -1.5, 80, "NEUTRAL"),
        _trade(3, "SOLUSDT", "A", "LONG", 5, 0.5, 80, "NEUTRAL"),
    ]
    row = ci.coin_performance_summary(trades)[0]
    assert row["max_drawdown_usdt"] == 15.0
    assert row["avg_mfe_r"] > 0
    assert row["avg_mae_r"] > 0
