import numpy as np
import pandas as pd

from app.strategy import build_trade_plan


def test_trade_plan_long():
    n = 30
    close = np.linspace(100, 110, n)
    df = pd.DataFrame({
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "atr14": np.full(n, 1.0),
    })
    row = {
        "symbol": "TESTUSDT",
        "bias": "LONG",
        "long_score": 85,
        "short_score": 20,
        "volume_ratio_1h": 1.4,
        "atr_pct_1h": 1.2,
        "reasons_long": ["trend up"],
        "reason_codes_long": ["TREND_1H_UP"],
        "rsi_1h": 60,
        "oi_change_pct": 2.0,
        "funding_rate": 0.0001,
        "distance_ema20_atr": 0.4,
        "trend_4h_long": True,
        "trend_4h_short": False,
        "trend_1h_long": True,
        "trend_1h_short": False,
    }
    p = build_trade_plan(row, df, "BULLISH")
    assert p is not None
    assert p.stop_loss < p.entry < p.take_profit
