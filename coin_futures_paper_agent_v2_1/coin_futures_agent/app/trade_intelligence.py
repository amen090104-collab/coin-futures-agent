from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .binance import BinanceClient
from .storage import _connect
from .chart_overlays import INTERVAL_MS, build_trade_overlays
from .decision_journal import journal_for_trade


def _dt(value: str) -> datetime:
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _decode_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def get_battle_trade(trade_id: int) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM battle_trades WHERE id=?",
            (int(trade_id),),
        ).fetchone()
    if not row:
        return None
    x = dict(row)
    x["entry_context"] = _decode_json(x.get("entry_context"), {})
    x["reason_codes"] = _decode_json(x.get("reason_codes"), [])
    x["loss_analysis"] = _decode_json(x.get("loss_analysis"), [])
    x["fix_suggestions"] = _decode_json(x.get("fix_suggestions"), [])
    return x


def _news_between(trade: dict[str, Any]) -> list[dict[str, Any]]:
    opened = _dt(trade["opened_at"]) - timedelta(minutes=45)
    closed = _dt(trade["closed_at"]) + timedelta(minutes=30)
    base = str(trade["symbol"]).replace("USDT", "")
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM news_articles
            WHERE published_at>=? AND published_at<=?
            ORDER BY published_at,id
            """,
            (opened.isoformat(), closed.isoformat()),
        ).fetchall()
    out = []
    for row in rows:
        x = dict(row)
        syms = _decode_json(x.get("symbols"), [])
        x["symbols"] = syms
        if base in syms or not syms or x.get("category") in {"MACRO", "REGULATION", "MARKET"}:
            out.append(x)
    return out


def attribute_trade(trade: dict[str, Any], news: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    news = news if news is not None else _news_between(trade)
    ctx = trade.get("entry_context") or {}
    opened = _dt(trade["opened_at"])
    closed = _dt(trade["closed_at"])
    side = str(trade.get("side") or "")
    won = float(trade.get("net_pnl") or 0) > 0
    relevant = []
    for item in news:
        try:
            published = _dt(item["published_at"])
        except Exception:
            continue
        if opened <= published <= closed and float(item.get("impact_score") or 0) >= 70:
            relevant.append(item)

    aligned = []
    opposed = []
    for item in relevant:
        sentiment = str(item.get("sentiment") or "NEUTRAL")
        if (side == "LONG" and sentiment == "BULLISH") or (side == "SHORT" and sentiment == "BEARISH"):
            aligned.append(item)
        elif (side == "LONG" and sentiment == "BEARISH") or (side == "SHORT" and sentiment == "BULLISH"):
            opposed.append(item)

    distance = abs(float(ctx.get("distance_ema20_atr") or 0))
    if str(trade.get("exit_reason")) == "NEWS_RISK_EXIT":
        classification = "RISK_EXIT"
        primary = "News Guardian closed exposure because event risk became unacceptable."
        external = "HIGH"
    elif won and aligned:
        classification = "NEWS_ASSISTED_WIN"
        primary = "A high-impact news event aligned with the trade after entry."
        external = "HIGH"
    elif (not won) and opposed:
        classification = "NEWS_SHOCK_LOSS"
        primary = "A high-impact news event opposed the trade after entry."
        external = "HIGH"
    elif won:
        classification = "THESIS_CONFIRMED"
        primary = "No dominant external catalyst was detected; price reached the planned favorable exit."
        external = "LOW" if not relevant else "MEDIUM"
    elif distance >= 2.0:
        classification = "LATE_ENTRY_OR_EXTENDED"
        primary = "The entry was materially extended from EMA20 relative to ATR and the trade failed."
        external = "LOW" if not relevant else "MEDIUM"
    else:
        classification = "THESIS_FAILED"
        primary = "The original directional thesis did not reach target before invalidation."
        external = "LOW" if not relevant else "MEDIUM"

    signal_quality = 7 if won else 4
    if classification in {"NEWS_ASSISTED_WIN", "NEWS_SHOCK_LOSS"}:
        signal_quality = 5
    entry_quality = max(2, min(9, int(round(8 - distance * 1.5))))
    stop_quality = 7
    if float(trade.get("mae_r") or 0) > 1.15:
        stop_quality = 5
    target_quality = 7 if won else 5
    if float(trade.get("mfe_r") or 0) > 0.7 and not won:
        target_quality = 4

    return {
        "classification": classification,
        "primary_cause": primary,
        "external_influence": external,
        "signal_quality": signal_quality,
        "entry_quality": entry_quality,
        "stop_quality": stop_quality,
        "target_quality": target_quality,
        "market_context_quality": 6,
        "high_impact_events_during_trade": len(relevant),
        "aligned_news": [
            {
                "source": x.get("source"),
                "title": x.get("title"),
                "url": x.get("url"),
                "published_at": x.get("published_at"),
                "impact_score": x.get("impact_score"),
                "sentiment": x.get("sentiment"),
            }
            for x in aligned[:8]
        ],
        "opposed_news": [
            {
                "source": x.get("source"),
                "title": x.get("title"),
                "url": x.get("url"),
                "published_at": x.get("published_at"),
                "impact_score": x.get("impact_score"),
                "sentiment": x.get("sentiment"),
            }
            for x in opposed[:8]
        ],
        "interpretation": (
            "Outcome and thesis quality are evaluated separately. A win can be news-assisted, "
            "and a loss can be caused by an external shock rather than a poor initial setup."
        ),
    }


def attribution_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    thesis_pnl = 0.0
    news_assisted_pnl = 0.0
    unclear_pnl = 0.0
    for raw in trades:
        trade = dict(raw)
        trade["entry_context"] = _decode_json(trade.get("entry_context"), {})
        # Keep dashboard aggregation fast. Full post-entry news attribution is performed
        # on demand in trade_detail(), where one bounded news query is acceptable.
        # NEWS_RISK_EXIT remains identifiable from the persisted exit reason.
        result = attribute_trade(trade, [])
        key = str(result["classification"])
        counts[key] = counts.get(key, 0) + 1
        pnl = float(trade.get("net_pnl") or 0)
        if key == "THESIS_CONFIRMED":
            thesis_pnl += pnl
        elif key in {"NEWS_ASSISTED_WIN", "NEWS_SHOCK_LOSS", "RISK_EXIT"}:
            news_assisted_pnl += pnl
        else:
            unclear_pnl += pnl
    return {
        "counts": counts,
        "thesis_confirmed_pnl": round(thesis_pnl, 2),
        "external_event_pnl": round(news_assisted_pnl, 2),
        "other_pnl": round(unclear_pnl, 2),
        "summary_mode": "FAST_NO_POST_ENTRY_NEWS",
        "note": (
            "Aggregate readiness avoids one news query per historical trade. Open Trade Detail "
            "for full news-assisted attribution using the actual trade-time news window."
        ),
    }


def _row_candle(row: Any) -> dict[str, Any]:
    return {
        "open_time": int(row["open_time"]),
        "close_time": int(row["close_time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


async def trade_detail(trade_id: int, interval: str = "15m") -> dict[str, Any]:
    """Replay around actual timestamps, keeping both entry and exit bars visible."""
    if interval not in INTERVAL_MS:
        interval = "15m"
    trade = get_battle_trade(trade_id)
    if not trade:
        raise KeyError(trade_id)

    opened = _dt(trade["opened_at"])
    closed = _dt(trade["closed_at"])
    step = INTERVAL_MS[interval]
    start_ms = int(opened.timestamp() * 1000) - 40 * step
    end_ms = int(closed.timestamp() * 1000) + 20 * step
    warning = None
    if interval == "1m" and end_ms - start_ms > 2_500 * step:
        # Do not silently show only the final bars and imply the entry marker
        # was absent. Encourage a timeframe where both endpoints fit.
        warning = "Lệnh giữ quá lâu cho chart 1m (giới hạn 2500 nến); chọn 5m/15m."
        candles: list[dict[str, Any]] = []
    else:
        client = BinanceClient()
        try:
            if interval == "1m":
                frame = await client.klines_1m_between(
                    trade["symbol"], max(0, start_ms), end_ms
                )
            else:
                frame = await client.klines(
                    trade["symbol"], interval, 1500,
                    start_time=max(0, start_ms), end_time=end_ms,
                )
        finally:
            await client.close()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        candles = [
            _row_candle(row) for _, row in frame.iterrows()
            if int(row["close_time"]) <= now_ms
        ]

    overlay = build_trade_overlays(candles, trade)
    news = _news_between(trade)
    attribution = attribute_trade(trade, news)
    context = trade["entry_context"]
    return {
        "trade": trade,
        "entry_thesis": context.get("entry_thesis") or {
            "primary_reason": trade.get("reason_text"),
            "reason_codes": trade.get("reason_codes") or [],
        },
        "signal_snapshot": {
            k: context.get(k)
            for k in (
                "strategy_version", "case_version", "btc_regime", "long_score",
                "short_score", "rsi_1h", "volume_ratio_1h", "atr_pct_1h",
                "oi_change_pct", "funding_rate", "distance_ema20_atr",
                "trend_4h_long", "trend_4h_short", "trend_1h_long", "trend_1h_short",
                "case_config",
            )
        },
        "decision_journal": journal_for_trade(trade),
        "attribution": attribution,
        "news_timeline": news,
        "chart": {
            "interval": interval, "candles": candles,
            "overlays": [overlay], "markers": overlay["markers"],
            "focus_trade_id": trade_id, "warning": warning,
            "entry_index": overlay["entry_index"], "exit_index": overlay["exit_index"],
        },
    }
