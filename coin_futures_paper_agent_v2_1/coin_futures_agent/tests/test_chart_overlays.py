from app.chart_overlays import locate_candle, build_trade_overlays


def candles():
    return [
        {"open_time": 1000, "close_time": 1999, "high": 103, "low": 99},
        {"open_time": 2000, "close_time": 2999, "high": 105, "low": 100},
        {"open_time": 3000, "close_time": 3999, "high": 106, "low": 102},
    ]


def test_timestamps_map_to_exact_candle_and_boundary():
    assert locate_candle(candles(), 1000) == 0
    assert locate_candle(candles(), 1999) == 0
    assert locate_candle(candles(), 2000) == 1
    assert locate_candle(candles(), 2999) == 1
    assert locate_candle(candles(), 999) is None
    assert locate_candle(candles(), 4000) is None


def test_entry_and_exit_overlay_indices_no_nearest_bar():
    trade = {
        "id": 12, "position_id": 4, "strategy_id": "BASE_RR1",
        "side": "LONG", "opened_at": 1500, "closed_at": 3400,
        "entry_price": 101, "stop_loss": 99, "take_profit": 103,
        "exit_price": 103, "net_pnl": 10.0, "r_multiple": 1.0,
        "exit_reason": "TAKE_PROFIT"
    }
    overlay = build_trade_overlays(candles(), trade)
    assert overlay["entry_index"] == 0
    assert overlay["exit_index"] == 2
    assert overlay["markers"][0]["candle_index"] == 0
    assert overlay["markers"][1]["candle_index"] == 2
    assert overlay["markers"][1]["exit_reason"] == "TAKE_PROFIT"
    trade["opened_at"] = 100
    overlay = build_trade_overlays(candles(), trade)
    assert overlay["entry_visible"] is False
    assert len(overlay["markers"]) == 1
