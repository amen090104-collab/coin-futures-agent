import json

from app.paper import evaluate_position_candle


def _position(mode: str):
    return {
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "side": "LONG",
        "opened_at": "2026-10-07T00:00:00+00:00",
        "max_favorable_price": 102.0,
        "max_adverse_price": 99.0,
        "entry_context": json.dumps({"case_config": {"management_mode": mode}}),
    }


def _candle(low=99.8, high=102.2, close=101.0):
    return {
        "open": 101.5,
        "high": high,
        "low": low,
        "close": close,
        "close_time": 1791331260000,
    }


def test_breakeven_uses_prior_closed_candle_excursion():
    result = evaluate_position_candle(_position("BREAKEVEN_0_8R"), _candle(low=99.9))
    assert result["exit_reason"] == "BREAKEVEN_EXIT"
    assert result["raw_exit"] == 100.0


def test_trailing_stop_locks_profit_from_prior_excursion():
    p = _position("TRAIL_AFTER_1R")
    p["max_favorable_price"] = 103.0  # prior MFE = 1.5R
    result = evaluate_position_candle(p, _candle(low=101.4, high=103.1))
    assert result["exit_reason"] == "TRAILING_STOP"
    assert result["raw_exit"] == 101.5


def test_fixed_mode_preserves_legacy_behavior():
    result = evaluate_position_candle(_position("FIXED"), _candle(low=99.9))
    assert result["exit_reason"] is None
    assert result["effective_stop"] == 98.0


def test_no_same_candle_lookahead_activation():
    p = _position("BREAKEVEN_0_8R")
    p["max_favorable_price"] = 100.5  # only 0.25R before this candle
    # This candle reaches +1R then falls under entry. The new stop must not
    # activate until the next candle because OHLC cannot reveal intrabar order.
    result = evaluate_position_candle(p, _candle(low=99.9, high=102.2))
    assert result["exit_reason"] is None
