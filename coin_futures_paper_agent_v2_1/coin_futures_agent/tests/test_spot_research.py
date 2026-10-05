import numpy as np
import pandas as pd

from app.spot_research import score_spot_candidate


def _frame(up=True):
    n = 50
    close = np.linspace(100, 140, n) if up else np.linspace(140, 100, n)
    df = pd.DataFrame({
        "close": close,
        "ema20": close - 2 if up else close + 2,
        "ema50": close - 5 if up else close + 5,
        "ema200": close - 10 if up else close + 10,
        "rsi14": np.full(n, 58 if up else 38),
        "vol_ratio": np.full(n, 1.4 if up else 0.7),
        "atr_pct": np.full(n, 3.0 if up else 7.0),
    })
    return df


def test_spot_research_scores_strong_context_higher():
    ticker = {"lastPrice": "140", "priceChangePercent": "4.5", "quoteVolume": "500000000"}
    bullish = score_spot_candidate(
        "TESTUSDT",
        ticker,
        _frame(True),
        _frame(True),
        _frame(True),
        "BULLISH",
        {"bias": "BULLISH", "score": 30, "articles": 4, "high_impact": 0},
    )
    bearish = score_spot_candidate(
        "TESTUSDT",
        ticker,
        _frame(False),
        _frame(False),
        _frame(False),
        "BEARISH",
        {"bias": "BEARISH", "score": -35, "articles": 4, "high_impact": 2},
    )
    assert bullish["score"] > bearish["score"]
    assert bullish["verdict"] in {"HIGH_PRIORITY_RESEARCH", "WATCH"}
    assert bearish["verdict"] in {"CAUTION", "NEUTRAL"}
