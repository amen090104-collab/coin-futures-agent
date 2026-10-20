from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .binance import BinanceClient
from .config import settings
from .indicators import enrich
from .scoring import score_symbol
from .v44_trend import assess_trend

STABLE_BASES = {"USDC", "FDUSD", "USDP", "TUSD", "DAI", "USDE", "BFUSD"}


def _source_time(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


async def _frames(client: BinanceClient, symbol: str):
    data = await asyncio.gather(
        client.klines(symbol, "15m", 220),
        client.klines(symbol, "1h", 220),
        client.klines(symbol, "4h", 220),
        client.oi_history(symbol, "15m", 5),
    )
    frames = {"15m": enrich(data[0]), "1h": enrich(data[1]), "4h": enrich(data[2])}
    oi = data[3]
    oi_change = 0.0
    if len(oi) >= 2:
        first = float(oi[0].get("sumOpenInterestValue") or 0)
        last = float(oi[-1].get("sumOpenInterestValue") or 0)
        if first > 0:
            oi_change = (last / first - 1) * 100
    # Provenance only; keep the existing Base and REV-E score/fallback unchanged.
    if settings.reverse_entry_intelligence_enabled:
        frames["1h"].attrs["oi_observed"] = (len(oi) >= 2 and float(oi[0].get("sumOpenInterestValue") or 0) > 0
                                                   and all(_source_time(x.get("timestamp")) > 0 for x in oi))
        frames["1h"].attrs["oi_source_time_ms"] = max((_source_time(x.get("timestamp")) for x in oi), default=0)
    return frames, oi_change


def _btc_regime(frames: dict[str, Any]) -> tuple[str, int]:
    r4 = frames["4h"].iloc[-2]
    r1 = frames["1h"].iloc[-2]
    bull = r4["close"] > r4["ema20"] > r4["ema50"] and r1["close"] > r1["ema20"]
    bear = r4["close"] < r4["ema20"] < r4["ema50"] and r1["close"] < r1["ema20"]
    if bull:
        return "BULLISH", 1
    if bear:
        return "BEARISH", -1
    return "NEUTRAL", 0


async def run_scan() -> tuple[dict[str, Any], dict[str, Any]]:
    client = BinanceClient()
    frames_by_symbol: dict[str, Any] = {}
    try:
        info, tickers, premiums = await asyncio.gather(
            client.exchange_info(), client.tickers_24h(), client.premium_index()
        )
        allowed = {
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("status") == "TRADING"
            and s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("baseAsset") not in STABLE_BASES
        }
        ranked = []
        for t in tickers:
            sym = t.get("symbol")
            if sym not in allowed:
                continue
            qv = float(t.get("quoteVolume") or 0)
            if qv >= settings.min_quote_volume_usdt:
                ranked.append((sym, qv))
        ranked.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in ranked[: settings.top_n_coins]]

        funding_map = {p.get("symbol"): float(p.get("lastFundingRate") or 0) for p in premiums}
        btc_frames, _ = await _frames(client, "BTCUSDT")
        btc_regime, btc_bias = _btc_regime(btc_frames)
        btc_1h_change_pct = (float(btc_frames["1h"].iloc[-2]["close"]) /
                             float(btc_frames["1h"].iloc[-3]["close"]) - 1) * 100

        async def analyze(symbol: str):
            try:
                frames, oi_change = await _frames(client, symbol)
                frames_by_symbol[symbol] = frames["15m"]
                score = score_symbol(frames, funding_map.get(symbol, 0.0), oi_change, btc_bias)
                last = frames["15m"].iloc[-2]
                research = {}
                if settings.v44_shadow_enabled:
                    coin_1h_change_pct = (float(frames["1h"].iloc[-2]["close"]) /
                                          float(frames["1h"].iloc[-3]["close"]) - 1) * 100
                    research["relative_strength_1h_pct"] = round(
                        coin_1h_change_pct - btc_1h_change_pct, 3)
                    research["btc_1h_change_pct"] = round(btc_1h_change_pct, 3)
                    if settings.reverse_entry_intelligence_enabled:
                        premium = next((p for p in premiums if p.get("symbol") == symbol), {})
                        research["research_provenance"] = {
                            "available_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
                            "max_source_time_ms": max(
                                *(_source_time(frames[tf].iloc[-2].get("close_time")) for tf in ("15m", "1h", "4h")),
                                _source_time(frames["1h"].attrs.get("oi_source_time_ms")), _source_time(premium.get("time"))),
                            "oi_observed": bool(frames["1h"].attrs.get("oi_observed")),
                            "funding_observed": premium.get("lastFundingRate") is not None and _source_time(premium.get("time")) > 0,
                            "oi_measure": "sumOpenInterestValue change; includes price effect",
                        }
                if settings.v44_shadow_enabled:
                    # Reuse fetched 15m/1h/4h data; no duplicate Binance calls.
                    research["trend_v44"] = assess_trend(frames, market_features={
                        "oi_change_pct": oi_change,
                        "funding_rate":funding_map.get(symbol),
                    })
                return {
                    "symbol": symbol,
                    "price": round(float(last["close"]), 10),
                    **score,
                    **research,
                }
            except Exception as exc:
                return {"symbol": symbol, "error": str(exc)}

        rows = await asyncio.gather(*(analyze(s) for s in symbols))
        good = [r for r in rows if "error" not in r]
        top_long = sorted(
            [r for r in good if r["long_score"] >= settings.score_threshold],
            key=lambda x: x["long_score"], reverse=True,
        )[: settings.top_results]
        top_short = sorted(
            [r for r in good if r["short_score"] >= settings.score_threshold],
            key=lambda x: x["short_score"], reverse=True,
        )[: settings.top_results]

        created_at = datetime.now(timezone.utc).isoformat()
        result = {
            "created_at": created_at,
            "btc_regime": btc_regime,
            "symbols_scanned": len(symbols),
            "top_long": top_long,
            "top_short": top_short,
            "all": sorted(good, key=lambda x: max(x["long_score"], x["short_score"]), reverse=True),
            "errors": [r for r in rows if "error" in r],
        }
        return result, frames_by_symbol
    finally:
        await client.close()
