from app import exit_simulator as sim


def trade():
    return {
        "id": 1, "symbol": "BTCUSDT", "side": "LONG",
        "opened_at": "2026-10-07T00:00:00+00:00",
        "entry_price": 100.0, "stop_loss": 98.0,
        "take_profit": 104.0, "quantity": 1.0,
        "exit_reason": "STOP_LOSS", "r_multiple": -1.05,
        "net_pnl": -2.1,
    }


def candle(minute, *, open=100, high=101, low=99.5, close=100.5):
    start=1791331200000 + 60000*minute
    return {"open_time": start, "close_time": start + 59999,
            "open": open, "high": high, "low": low, "close": close}


def by_key(doc, key):
    return next(x for x in doc["variants"] if x["variant"] == key)


def test_stop_wins_both_touched_even_when_take_profit_hit():
    doc = sim.simulate_exit_variants(
        trade(), [candle(1, high=106, low=97, close=104)],
        max_hold_hours=0.1,
    )
    one = by_key(doc, "FIXED_RR1")
    two = by_key(doc, "FIXED_RR2")
    assert one["status"] == "RESOLVED"
    assert two["exit_reason"] == "STOP_LOSS"
    assert one["net_pnl"] < 0
    assert two["net_pnl"] < 0


def test_be_activates_only_from_previous_closed_candle():
    candles = [
        candle(1, open=100, high=101.7, low=99.7, close=101.4),
        candle(2, open=101.4, high=101.8, low=99.9, close=100.2),
        candle(3, open=100.2, high=100.6, low=97.5, close=98.1),
    ]
    doc = sim.simulate_exit_variants(trade(), candles, max_hold_hours=0.1)
    be = by_key(doc, "BREAKEVEN_0_8R")
    fixed = by_key(doc, "FIXED_RR2")
    assert be["status"] == "RESOLVED"
    assert be["exit_reason"] == "BE_OR_TRAIL_STOP"
    assert be["fills"][0]["raw_price"] == 100.0
    assert fixed["exit_reason"] == "STOP_LOSS"
    # Profits are net of fees/slippage, so a breakeven stop is not free.
    assert be["net_pnl"] < 0


def test_partial_exit_and_runner_can_lock_profit():
    candles = [
        candle(1, high=102.2, low=99.6, close=101.7),
        candle(2, open=101.8, high=103, low=101.6, close=102.6),
        candle(3, open=102.6, high=104.5, low=101.8, close=103),
    ]
    doc = sim.simulate_exit_variants(trade(), candles, max_hold_hours=0.1)
    partial = by_key(doc, "PARTIAL_1R_TRAIL")
    assert partial["partial_fill"] is True
    assert partial["status"] == "RESOLVED"
    assert len(partial["fills"]) == 2


def test_gaps_and_unobserved_paths_are_censored():
    doc = sim.simulate_exit_variants(
        trade(), [candle(1), candle(3, high=105, low=98.5)],
        max_hold_hours=0.1,
    )
    assert doc["warnings"]
    assert all(v["status"] == "CENSORED" for v in doc["variants"])
    empty = sim.simulate_exit_variants(trade(), [])
    assert all(v["net_pnl"] is None for v in empty["variants"])
