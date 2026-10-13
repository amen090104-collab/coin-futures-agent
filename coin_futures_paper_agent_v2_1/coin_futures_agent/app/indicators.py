import numpy as np
import pandas as pd


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]

    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    out["ema200"] = close.ewm(span=200, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi14"] = 100 - (100 / (1 + rs))

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    out["atr_pct"] = out["atr14"] / close * 100

    # Wilder-style directional movement strength. Research may use this as
    # supportive evidence; ADX is not a directional or predictive probability.
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    smooth_tr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smooth_tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smooth_tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out["adx14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    out["vol_ma20"] = out["volume"].rolling(20).mean()
    out["vol_ratio"] = out["volume"] / out["vol_ma20"]

    out["prev_20_high"] = high.shift(1).rolling(20).max()
    out["prev_20_low"] = low.shift(1).rolling(20).min()
    out["ret_1"] = close.pct_change() * 100
    return out
