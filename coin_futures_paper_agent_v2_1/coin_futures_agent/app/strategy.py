from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from .config import settings


@dataclass
class TradePlan:
    symbol: str
    side: str
    signal_price: float
    entry: float
    stop_loss: float
    take_profit: float
    risk_per_unit: float
    stop_pct: float
    reward_risk: float
    atr_15m: float
    swing_level: float
    score: float
    reason_text: str
    reason_codes: list[str]
    entry_context: dict

    def as_dict(self) -> dict:
        return asdict(self)


def _round_price(x: float) -> float:
    if x >= 1000:
        return round(x, 2)
    if x >= 100:
        return round(x, 3)
    if x >= 1:
        return round(x, 5)
    if x >= 0.01:
        return round(x, 7)
    return round(x, 10)


def build_trade_plan(row: dict, frame15: pd.DataFrame, btc_regime: str) -> TradePlan | None:
    side = row.get("bias")
    if side not in {"LONG", "SHORT"}:
        return None

    score = float(row["long_score"] if side == "LONG" else row["short_score"])
    if score < settings.score_threshold:
        return None
    if float(row.get("volume_ratio_1h", 0)) < settings.min_volume_ratio:
        return None
    if float(row.get("atr_pct_1h", 99)) > settings.max_atr_pct:
        return None

    closed = frame15.iloc[:-1] if len(frame15) > 1 else frame15
    last = closed.iloc[-1]
    signal_price = float(last["close"])
    atr = float(last["atr14"])
    if atr <= 0:
        return None

    lookback = closed.tail(settings.structure_lookback)
    if side == "LONG":
        swing = float(lookback["low"].min())
        structure_stop = swing - 0.15 * atr
        atr_stop = signal_price - settings.stop_atr_mult * atr
        stop = min(structure_stop, atr_stop)
        risk = signal_price - stop
        tp = signal_price + settings.reward_risk * risk
        reasons = row.get("reasons_long", [])
        codes = row.get("reason_codes_long", [])
    else:
        swing = float(lookback["high"].max())
        structure_stop = swing + 0.15 * atr
        atr_stop = signal_price + settings.stop_atr_mult * atr
        stop = max(structure_stop, atr_stop)
        risk = stop - signal_price
        tp = signal_price - settings.reward_risk * risk
        reasons = row.get("reasons_short", [])
        codes = row.get("reason_codes_short", [])

    if risk <= 0:
        return None
    stop_pct = risk / signal_price * 100
    if not (settings.min_stop_pct <= stop_pct <= settings.max_stop_pct):
        return None

    context = {
        "btc_regime": btc_regime,
        "long_score": row.get("long_score"),
        "short_score": row.get("short_score"),
        "rsi_1h": row.get("rsi_1h"),
        "volume_ratio_1h": row.get("volume_ratio_1h"),
        "atr_pct_1h": row.get("atr_pct_1h"),
        "oi_change_pct": row.get("oi_change_pct"),
        "funding_rate": row.get("funding_rate"),
        "distance_ema20_atr": row.get("distance_ema20_atr"),
        "trend_4h_long": row.get("trend_4h_long"),
        "trend_4h_short": row.get("trend_4h_short"),
        "trend_1h_long": row.get("trend_1h_long"),
        "trend_1h_short": row.get("trend_1h_short"),
    }

    reason_text = "; ".join(reasons[:6]) or "quantitative score passed"
    return TradePlan(
        symbol=row["symbol"],
        side=side,
        signal_price=_round_price(signal_price),
        entry=_round_price(signal_price),
        stop_loss=_round_price(stop),
        take_profit=_round_price(tp),
        risk_per_unit=abs(signal_price - stop),
        stop_pct=round(stop_pct, 3),
        reward_risk=settings.reward_risk,
        atr_15m=atr,
        swing_level=_round_price(swing),
        score=score,
        reason_text=reason_text,
        reason_codes=list(codes),
        entry_context=context,
    )
