from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class SideScore:
    long: float = 0.0
    short: float = 0.0

    def clamp(self) -> None:
        self.long = max(0.0, min(100.0, self.long))
        self.short = max(0.0, min(100.0, self.short))


def _trend_points(row: pd.Series, weight: float) -> SideScore:
    s = SideScore()
    p, e20, e50, e200 = row["close"], row["ema20"], row["ema50"], row["ema200"]
    if p > e20 > e50 > e200:
        s.long += weight
    elif p < e20 < e50 < e200:
        s.short += weight
    else:
        if p > e50:
            s.long += weight * 0.35
        if p < e50:
            s.short += weight * 0.35
        if e20 > e50:
            s.long += weight * 0.20
        if e20 < e50:
            s.short += weight * 0.20
    return s


def _aligned(row: pd.Series, side: str) -> bool:
    if side == "LONG":
        return bool(row["close"] > row["ema20"] > row["ema50"])
    return bool(row["close"] < row["ema20"] < row["ema50"])


def score_symbol(frames: dict[str, pd.DataFrame], funding: float, oi_change_pct: float, btc_bias: int = 0) -> dict:
    s = SideScore()
    reasons_long: list[str] = []
    reasons_short: list[str] = []
    codes_long: list[str] = []
    codes_short: list[str] = []

    for interval, weight in [("4h", 22), ("1h", 18), ("15m", 8)]:
        row = frames[interval].iloc[-2]
        pts = _trend_points(row, weight)
        s.long += pts.long
        s.short += pts.short
        if pts.long >= weight * 0.8:
            reasons_long.append(f"{interval} trend up")
            codes_long.append(f"TREND_{interval.upper()}_UP")
        if pts.short >= weight * 0.8:
            reasons_short.append(f"{interval} trend down")
            codes_short.append(f"TREND_{interval.upper()}_DOWN")

    row1h = frames["1h"].iloc[-2]
    row15 = frames["15m"].iloc[-2]
    rsi = float(row1h["rsi14"])
    if 52 <= rsi <= 70:
        s.long += 10
        reasons_long.append(f"RSI 1h {rsi:.1f} supports momentum")
        codes_long.append("RSI_LONG_ZONE")
    elif 30 <= rsi <= 48:
        s.short += 10
        reasons_short.append(f"RSI 1h {rsi:.1f} supports momentum")
        codes_short.append("RSI_SHORT_ZONE")
    elif rsi > 75:
        s.long -= 3
    elif rsi < 25:
        s.short -= 3

    vr = float(row1h["vol_ratio"])
    if vr >= 1.5:
        if row1h["close"] >= row1h["open"]:
            s.long += 10
            reasons_long.append(f"1h volume spike {vr:.2f}x")
            codes_long.append("VOLUME_SPIKE_UP")
        else:
            s.short += 10
            reasons_short.append(f"1h volume spike {vr:.2f}x")
            codes_short.append("VOLUME_SPIKE_DOWN")
    elif vr >= 1.1:
        if row1h["close"] >= row1h["open"]:
            s.long += 5
        else:
            s.short += 5

    close = float(row1h["close"])
    h20 = float(row1h["prev_20_high"])
    l20 = float(row1h["prev_20_low"])
    if close > h20:
        s.long += 10
        reasons_long.append("1h breakout above 20-bar high")
        codes_long.append("BREAKOUT_1H")
    if close < l20:
        s.short += 10
        reasons_short.append("1h breakdown below 20-bar low")
        codes_short.append("BREAKDOWN_1H")

    atr_pct = float(row1h["atr_pct"])
    if 0.5 <= atr_pct <= 4.0:
        s.long += 5
        s.short += 5
    elif atr_pct > 7:
        s.long -= 4
        s.short -= 4

    price_change_1h = (
        float(frames["1h"].iloc[-2]["close"]) / float(frames["1h"].iloc[-3]["close"]) - 1
    ) * 100
    if oi_change_pct > 1.0 and price_change_1h > 0:
        s.long += 10
        reasons_long.append(f"OI +{oi_change_pct:.1f}% with price rising")
        codes_long.append("OI_CONFIRMS_LONG")
    elif oi_change_pct > 1.0 and price_change_1h < 0:
        s.short += 10
        reasons_short.append(f"OI +{oi_change_pct:.1f}% with price falling")
        codes_short.append("OI_CONFIRMS_SHORT")
    elif oi_change_pct < -1.0:
        s.long -= 2
        s.short -= 2

    if funding > 0.0008:
        s.long -= 6
        reasons_short.append("funding is crowded on long side")
        codes_short.append("CROWDED_LONG_FUNDING")
    elif funding < -0.0008:
        s.short -= 6
        reasons_long.append("funding is crowded on short side")
        codes_long.append("CROWDED_SHORT_FUNDING")
    else:
        s.long += 2
        s.short += 2

    if btc_bias > 0:
        s.long += 5
        s.short -= 3
        codes_long.append("BTC_REGIME_SUPPORT")
    elif btc_bias < 0:
        s.short += 5
        s.long -= 3
        codes_short.append("BTC_REGIME_SUPPORT")

    s.clamp()
    bias = "LONG" if s.long >= s.short + 10 else "SHORT" if s.short >= s.long + 10 else "WAIT"
    ema20_15 = float(row15["ema20"])
    atr15 = float(row15["atr14"])
    distance_ema20_atr = abs(float(row15["close"]) - ema20_15) / atr15 if atr15 > 0 else 0.0

    return {
        "long_score": round(s.long, 1),
        "short_score": round(s.short, 1),
        "bias": bias,
        "rsi_1h": round(rsi, 2),
        "volume_ratio_1h": round(vr, 2),
        "atr_pct_1h": round(atr_pct, 2),
        "atr_15m": round(atr15, 12),
        "ema20_15m": round(ema20_15, 12),
        "distance_ema20_atr": round(distance_ema20_atr, 2),
        "oi_change_pct": round(oi_change_pct, 2),
        "funding_rate": funding,
        "trend_4h_long": _aligned(frames["4h"].iloc[-2], "LONG"),
        "trend_4h_short": _aligned(frames["4h"].iloc[-2], "SHORT"),
        "trend_1h_long": _aligned(frames["1h"].iloc[-2], "LONG"),
        "trend_1h_short": _aligned(frames["1h"].iloc[-2], "SHORT"),
        "reasons_long": reasons_long[:8],
        "reasons_short": reasons_short[:8],
        "reason_codes_long": codes_long,
        "reason_codes_short": codes_short,
    }
