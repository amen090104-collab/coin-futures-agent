from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .binance import BinanceSpotClient
from .config import settings
from .indicators import enrich
from .json_safe import json_safe
from .news import symbol_news_context
from .storage import save_spot_research
from .spot_narratives import coin_narrative_context, run_narrative_research

STABLE_BASES = {"USDC", "FDUSD", "USDP", "TUSD", "DAI", "USDE", "BFUSD", "EUR", "TRY"}


def _trend(row: Any) -> int:
    close = float(row["close"])
    e20 = float(row["ema20"])
    e50 = float(row["ema50"])
    e200 = float(row["ema200"])
    if close > e20 > e50 > e200:
        return 2
    if close > e20 > e50:
        return 1
    if close < e20 < e50 < e200:
        return -2
    if close < e20 < e50:
        return -1
    return 0


def _momentum(df: Any, bars: int) -> float:
    closed = df.iloc[:-1] if len(df) > 1 else df
    if len(closed) <= bars:
        return 0.0
    a = float(closed.iloc[-1]["close"])
    b = float(closed.iloc[-1 - bars]["close"])
    return (a / b - 1) * 100 if b else 0.0


def score_spot_candidate(
    symbol: str,
    ticker: dict[str, Any],
    frame_1h: Any,
    frame_4h: Any,
    frame_1d: Any,
    market_regime: str,
    news: dict[str, Any],
    narrative_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    narrative_ctx = narrative_ctx or {"news_conviction": 0.0, "narratives": []}
    r1 = frame_1h.iloc[-2]
    r4 = frame_4h.iloc[-2]
    rd = frame_1d.iloc[-2]
    t1, t4, td = _trend(r1), _trend(r4), _trend(rd)

    score = 50.0
    reasons: list[str] = []
    risks: list[str] = []

    score += td * 9
    score += t4 * 7
    score += t1 * 3

    if td >= 1 and t4 >= 1:
        reasons.append("Xu hướng 1D và 4H đồng thuận tăng.")
    if td <= -1 and t4 <= -1:
        risks.append("Xu hướng 1D và 4H đang đồng thuận giảm.")

    rsi4 = float(r4["rsi14"])
    rsid = float(rd["rsi14"])
    if 45 <= rsi4 <= 65:
        score += 6
        reasons.append(f"RSI 4H {rsi4:.1f} còn trong vùng momentum lành mạnh.")
    elif rsi4 >= 75:
        score -= 9
        risks.append(f"RSI 4H {rsi4:.1f} cao, rủi ro mua đuổi.")
    elif rsi4 <= 30:
        score -= 3
        risks.append(f"RSI 4H {rsi4:.1f} yếu; chưa coi oversold là tín hiệu mua độc lập.")

    vr4 = float(r4["vol_ratio"])
    if vr4 >= 1.5:
        score += 7
        reasons.append(f"Volume 4H tăng mạnh {vr4:.2f}x.")
    elif vr4 >= 1.1:
        score += 3
    elif vr4 < 0.7:
        score -= 4
        risks.append(f"Volume 4H thấp ({vr4:.2f}x).")

    mom7 = _momentum(frame_1d, 7)
    mom30 = _momentum(frame_1d, 30)
    if 2 <= mom7 <= 25:
        score += 4
    elif mom7 < -12:
        score -= 6
        risks.append(f"Momentum 7 ngày yếu ({mom7:+.1f}%).")
    if mom30 >= 8:
        score += 4
    elif mom30 < -20:
        score -= 5

    atr = float(rd["atr_pct"])
    if atr > 10:
        score -= 10
        risks.append(f"Biến động ngày rất cao (ATR {atr:.1f}%).")
    elif atr > 6:
        score -= 5
        risks.append(f"Biến động ngày cao (ATR {atr:.1f}%).")
    elif 1 <= atr <= 5:
        score += 2

    news_score = float(news.get("score") or 0)
    if news.get("bias") == "BULLISH":
        score += min(8, max(2, news_score / 8))
        reasons.append(f"Tin 24h nghiêng tích cực ({news_score:+.1f}).")
    elif news.get("bias") == "BEARISH":
        score -= min(12, max(3, abs(news_score) / 6))
        risks.append(f"Tin 24h nghiêng tiêu cực ({news_score:+.1f}).")
    if int(news.get("high_impact") or 0) >= 2:
        risks.append("Có nhiều tin high-impact; nên chờ biến động ổn định.")

    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    if market_regime == "BEARISH":
        penalty = 3 if base == "BTC" else 9
        score -= penalty
        risks.append("BTC market regime đang BEARISH.")
    elif market_regime == "BULLISH":
        score += 5
        reasons.append("BTC market regime đang hỗ trợ tài sản rủi ro.")

    technical_score = round(max(0.0, min(100.0, score)), 1)
    narrative_conviction = float(narrative_ctx.get("news_conviction") or 0)
    symbol_news_norm = max(0.0, min(100.0, 50.0 + news_score / 2.0))
    if narrative_ctx.get("narratives"):
        research_score = round(
            0.55 * narrative_conviction
            + 0.20 * symbol_news_norm
            + 0.25 * technical_score,
            1,
        )
    else:
        research_score = round(0.55 * symbol_news_norm + 0.45 * technical_score, 1)

    if research_score >= 78:
        verdict = "TREND_RESEARCH_PRIORITY"
    elif research_score >= 65:
        verdict = "WATCH_NARRATIVE"
    elif research_score >= 50:
        verdict = "BACKGROUND_RESEARCH"
    else:
        verdict = "LOW_EVIDENCE"

    if atr >= 10 or (td <= -1 and t4 <= -1):
        risk_level = "HIGH"
    elif atr >= 6 or market_regime == "BEARISH":
        risk_level = "MEDIUM_HIGH"
    elif atr >= 4:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW_MEDIUM"

    price = float(ticker.get("lastPrice") or rd["close"])
    return {
        "symbol": symbol,
        "base": base,
        "price": price,
        "score": research_score,
        "research_score": research_score,
        "technical_score": technical_score,
        "news_conviction": round(narrative_conviction, 1),
        "narratives": narrative_ctx.get("narratives", []),
        "verdict": verdict,
        "risk_level": risk_level,
        "price_change_24h_pct": round(float(ticker.get("priceChangePercent") or 0), 2),
        "quote_volume_24h": round(float(ticker.get("quoteVolume") or 0), 2),
        "trend_1h": t1,
        "trend_4h": t4,
        "trend_1d": td,
        "rsi_4h": round(rsi4, 2),
        "rsi_1d": round(rsid, 2),
        "volume_ratio_4h": round(vr4, 2),
        "atr_pct_1d": round(atr, 2),
        "momentum_7d_pct": round(mom7, 2),
        "momentum_30d_pct": round(mom30, 2),
        "news_bias": news.get("bias", "NO_DATA"),
        "news_score": news_score,
        "news_articles": int(news.get("articles") or 0),
        "reasons": reasons[:6],
        "risks": risks[:6],
    }


def _btc_regime(frame_4h: Any, frame_1d: Any) -> str:
    t4 = _trend(frame_4h.iloc[-2])
    td = _trend(frame_1d.iloc[-2])
    if td >= 1 and t4 >= 1:
        return "BULLISH"
    if td <= -1 and t4 <= -1:
        return "BEARISH"
    return "NEUTRAL"


async def run_spot_research() -> dict[str, Any]:
    client = BinanceSpotClient()
    try:
        info, tickers = await asyncio.gather(client.exchange_info(), client.tickers_24h())
        allowed = {
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("status") == "TRADING"
            and s.get("quoteAsset") == "USDT"
            and s.get("isSpotTradingAllowed", True)
            and s.get("baseAsset") not in STABLE_BASES
        }

        ticker_map: dict[str, dict[str, Any]] = {}
        ranked: list[tuple[str, float]] = []
        for ticker in tickers:
            symbol = ticker.get("symbol")
            if symbol not in allowed:
                continue
            qv = float(ticker.get("quoteVolume") or 0)
            if qv < settings.spot_min_quote_volume_usdt:
                continue
            ticker_map[symbol] = ticker
            ranked.append((symbol, qv))
        ranked.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in ranked[: settings.spot_top_n_coins]]

        btc4, btcd = await asyncio.gather(
            client.klines("BTCUSDT", "4h", 220),
            client.klines("BTCUSDT", "1d", 220),
        )
        market_regime = _btc_regime(enrich(btc4), enrich(btcd))
        narrative_research = run_narrative_research()

        async def analyze(symbol: str) -> dict[str, Any]:
            try:
                a, b, c = await asyncio.gather(
                    client.klines(symbol, "1h", 220),
                    client.klines(symbol, "4h", 220),
                    client.klines(symbol, "1d", 220),
                )
                news = symbol_news_context(symbol, hours=24)
                narrative_ctx = coin_narrative_context(symbol, narrative_research)
                return score_spot_candidate(
                    symbol,
                    ticker_map[symbol],
                    enrich(a),
                    enrich(b),
                    enrich(c),
                    market_regime,
                    news,
                    narrative_ctx,
                )
            except Exception as exc:
                return {"symbol": symbol, "error": str(exc)[:500]}

        rows = await asyncio.gather(*(analyze(symbol) for symbol in symbols))
        good = [x for x in rows if "error" not in x]
        good.sort(key=lambda x: x["score"], reverse=True)
        created_at = datetime.now(timezone.utc).isoformat()
        result = {
            "created_at": created_at,
            "market_regime": market_regime,
            "symbols_researched": len(symbols),
            "top": good[: settings.spot_research_results],
            "all": good,
            "errors": [x for x in rows if "error" in x],
            "narrative_research": narrative_research,
            "method": "news-first narrative research; technical indicators are secondary context; research only, no automatic spot orders",
        }
        result = json_safe(result)
        save_spot_research(created_at, market_regime, result)
        return result
    finally:
        await client.close()
