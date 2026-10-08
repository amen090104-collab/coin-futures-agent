from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .binance import BinanceClient
from .spot_narratives import coin_narratives
from .storage import _connect, latest_spot_research, recent_news
from .strategy_cases import list_strategy_cases
from .trade_intelligence import attribute_trade


_INTERVAL_LOOKBACK = {
    "1m": timedelta(hours=16),
    "5m": timedelta(days=3),
    "15m": timedelta(days=10),
    "1h": timedelta(days=40),
    "4h": timedelta(days=120),
}


def normalize_symbol(symbol: str) -> str:
    s = "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())
    if not s:
        raise ValueError("symbol is required")
    if not s.endswith("USDT"):
        s += "USDT"
    return s


def _f(value: Any) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else 0.0
    except Exception:
        return 0.0


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return fallback


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _decoded_trade(row: Any) -> dict[str, Any]:
    x = dict(row)
    x["entry_context"] = _json(x.get("entry_context"), {})
    x["reason_codes"] = _json(x.get("reason_codes"), [])
    x["loss_analysis"] = _json(x.get("loss_analysis"), [])
    x["fix_suggestions"] = _json(x.get("fix_suggestions"), [])
    return x


def symbol_trades(symbol: str, limit: int = 1000) -> list[dict[str, Any]]:
    symbol = normalize_symbol(symbol)
    limit = min(max(int(limit), 1), 5000)
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM battle_trades
            WHERE symbol=?
            ORDER BY closed_at,id
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()
    return [_decoded_trade(x) for x in rows]


def symbol_open_positions(symbol: str) -> list[dict[str, Any]]:
    symbol = normalize_symbol(symbol)
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM battle_positions
            WHERE symbol=? AND status='OPEN'
            ORDER BY id
            """,
            (symbol,),
        ).fetchall()
    out = []
    for row in rows:
        x = dict(row)
        x["entry_context"] = _json(x.get("entry_context"), {})
        x["reason_codes"] = _json(x.get("reason_codes"), [])
        out.append(x)
    return out


def _drawdown(trades: list[dict[str, Any]]) -> tuple[float, float]:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_r = 0.0
    equity_r = 0.0
    peak_r = 0.0
    for trade in sorted(trades, key=lambda x: (str(x.get("closed_at") or ""), int(x.get("id") or 0))):
        equity += _f(trade.get("net_pnl"))
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        equity_r += _f(trade.get("r_multiple"))
        peak_r = max(peak_r, equity_r)
        max_dd_r = max(max_dd_r, peak_r - equity_r)
    return max_dd, max_dd_r


def _stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    wins = [x for x in trades if _f(x.get("net_pnl")) > 0]
    losses = [x for x in trades if _f(x.get("net_pnl")) < 0]
    gross_profit = sum(max(0.0, _f(x.get("net_pnl"))) for x in trades)
    gross_loss = -sum(min(0.0, _f(x.get("net_pnl"))) for x in trades)
    rs = [_f(x.get("r_multiple")) for x in trades]
    win_rs = [_f(x.get("r_multiple")) for x in wins]
    loss_rs = [_f(x.get("r_multiple")) for x in losses]
    max_dd, max_dd_r = _drawdown(trades)
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "net_pnl": round(sum(_f(x.get("net_pnl")) for x in trades), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "expectancy_r": round(sum(rs) / n, 3) if n else 0.0,
        "avg_r": round(sum(rs) / n, 3) if n else 0.0,
        "avg_win_r": round(sum(win_rs) / len(win_rs), 3) if win_rs else 0.0,
        "avg_loss_r": round(sum(loss_rs) / len(loss_rs), 3) if loss_rs else 0.0,
        "avg_hold_minutes": round(sum(_f(x.get("holding_minutes")) for x in trades) / n, 1) if n else 0.0,
        "avg_mfe_r": round(sum(_f(x.get("mfe_r")) for x in trades) / n, 3) if n else 0.0,
        "avg_mae_r": round(sum(_f(x.get("mae_r")) for x in trades) / n, 3) if n else 0.0,
        "max_drawdown_usdt": round(max_dd, 2),
        "max_drawdown_r": round(max_dd_r, 3),
    }


def _score_bucket(score: float) -> str:
    if score >= 90:
        return "90+"
    if score >= 85:
        return "85-89"
    if score >= 80:
        return "80-84"
    return "75-79"


def coin_performance_summary(
    trades: list[dict[str, Any]],
    *,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    cases = {str(x["strategy_id"]): x for x in list_strategy_cases(include_archived=True)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in decoded:
        grouped[str(trade.get("symbol") or "UNKNOWN")].append(trade)

    rows: list[dict[str, Any]] = []
    for symbol, xs in grouped.items():
        by_case: dict[str, dict[str, Any]] = {}
        for sid in sorted({str(x.get("strategy_id") or "") for x in xs}):
            ss = [x for x in xs if str(x.get("strategy_id") or "") == sid]
            by_case[sid] = {
                **_stats(ss),
                "strategy_id": sid,
                "name": cases.get(sid, {}).get("name", sid),
                "short_name": cases.get(sid, {}).get("short_name", sid),
            }
        by_side = {
            side: _stats([x for x in xs if str(x.get("side")) == side])
            for side in ("LONG", "SHORT")
            if any(str(x.get("side")) == side for x in xs)
        }
        regimes: dict[str, dict[str, Any]] = {}
        for regime in ("BULLISH", "BEARISH", "NEUTRAL"):
            subset = [
                x for x in xs
                if str((x.get("entry_context") or {}).get("btc_regime") or "NEUTRAL") == regime
            ]
            if subset:
                regimes[regime] = _stats(subset)

        case_rank = sorted(
            by_case.values(),
            key=lambda x: (x["expectancy_r"], x["net_pnl"], x["trades"]),
            reverse=True,
        )
        rows.append({
            "symbol": symbol,
            **_stats(xs),
            "by_case": by_case,
            "by_side": by_side,
            "by_regime": regimes,
            "best_case": case_rank[0]["strategy_id"] if case_rank else None,
            "worst_case": case_rank[-1]["strategy_id"] if case_rank else None,
            "exit_reasons": dict(Counter(str(x.get("exit_reason") or "UNKNOWN") for x in xs)),
        })

    rows.sort(key=lambda x: (x["net_pnl"], x["expectancy_r"]), reverse=True)
    return rows[:top_n] if top_n else rows


def _trade_news_candidates(trade: dict[str, Any], news: list[dict[str, Any]]) -> list[dict[str, Any]]:
    opened = _dt(trade.get("opened_at"))
    closed = _dt(trade.get("closed_at"))
    if not opened or not closed:
        return []
    base = str(trade.get("symbol") or "").replace("USDT", "")
    out = []
    for item in news:
        published = _dt(item.get("published_at"))
        if not published or not (opened <= published <= closed):
            continue
        symbols = item.get("symbols") or []
        category = str(item.get("category") or "")
        if base in symbols or not symbols or category in {"MACRO", "REGULATION", "MARKET"}:
            out.append(item)
    return out


def daily_trade_attribution(trades: list[dict[str, Any]], news_hours: int = 72) -> dict[str, Any]:
    # Query the actual trade-time window rather than "last N hours" so regenerated
    # historical reports keep the same news evidence.
    decoded = [_decoded_trade(x) for x in trades]
    opened = [_dt(x.get("opened_at")) for x in decoded]
    closed = [_dt(x.get("closed_at")) for x in decoded]
    opened = [x for x in opened if x is not None]
    closed = [x for x in closed if x is not None]
    news: list[dict[str, Any]] = []
    if opened and closed:
        start = min(opened) - timedelta(minutes=45)
        end = max(closed) + timedelta(minutes=30)
        with _connect() as con:
            rows = con.execute(
                """
                SELECT * FROM news_articles
                WHERE published_at>=? AND published_at<=?
                ORDER BY published_at,id
                LIMIT 1500
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        for row in rows:
            item = dict(row)
            item["symbols"] = _json(item.get("symbols"), [])
            news.append(item)

    counts: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    pnl_by_class: dict[str, float] = defaultdict(float)
    for raw in trades:
        trade = _decoded_trade(raw)
        result = attribute_trade(trade, _trade_news_candidates(trade, news))
        key = str(result.get("classification") or "UNKNOWN")
        counts[key] += 1
        pnl_by_class[key] += _f(trade.get("net_pnl"))
        details.append({
            "trade_id": trade.get("id"),
            "strategy_id": trade.get("strategy_id"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "net_pnl": _f(trade.get("net_pnl")),
            "r_multiple": _f(trade.get("r_multiple")),
            "exit_reason": trade.get("exit_reason"),
            "classification": key,
            "primary_cause": result.get("primary_cause"),
            "external_influence": result.get("external_influence"),
            "high_impact_events_during_trade": result.get("high_impact_events_during_trade"),
        })
    return {
        "counts": dict(counts),
        "pnl_by_class": {k: round(v, 2) for k, v in pnl_by_class.items()},
        "details": details,
    }


def _research_context(symbol: str) -> dict[str, Any]:
    base = symbol.replace("USDT", "")
    latest = (latest_spot_research(1) or [None])[0] or {}
    coin_row = next(
        (x for x in latest.get("top", []) if str(x.get("symbol")) == symbol),
        None,
    )
    narrative_rows = []
    sectors = coin_narratives(symbol)
    for item in (latest.get("narrative_research") or {}).get("narratives", []):
        if item.get("narrative") in sectors:
            narrative_rows.append({
                "narrative": item.get("narrative"),
                "trend_score": item.get("trend_score"),
                "state": item.get("state"),
                "bias": item.get("bias"),
                "articles_24h": item.get("articles_24h"),
                "independent_sources_24h": item.get("independent_sources_24h"),
            })
    return {
        "base": base,
        "sectors": sectors,
        "spot_research": coin_row,
        "narratives": sorted(narrative_rows, key=lambda x: _f(x.get("trend_score")), reverse=True),
    }


def _candle(row: Any) -> dict[str, Any]:
    return {
        "open_time": int(row["open_time"]),
        "close_time": int(row["close_time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


async def coin_detail(
    symbol: str,
    interval: str = "15m",
    trade_limit: int = 1000,
) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    if interval not in _INTERVAL_LOOKBACK:
        interval = "15m"

    trades = symbol_trades(symbol, trade_limit)
    positions = symbol_open_positions(symbol)
    stats = _stats(trades)
    performance = coin_performance_summary(trades)
    summary = performance[0] if performance else {"by_case": {}, "by_side": {}, "by_regime": {}}

    now = datetime.now(timezone.utc)
    start = now - _INTERVAL_LOOKBACK[interval]
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    client = BinanceClient()
    try:
        if interval == "1m":
            df = await client.klines_1m_between(symbol, start_ms, end_ms)
            if len(df) > 1000:
                df = df.tail(1000)
        else:
            df = await client.klines(symbol, interval, 1000, start_time=start_ms, end_time=end_ms)
    finally:
        await client.close()

    if not df.empty:
        visible_start = int(df.iloc[0]["open_time"])
        visible_end = int(df.iloc[-1]["close_time"])
    else:
        visible_start, visible_end = start_ms, end_ms

    def in_window(value: Any) -> bool:
        d = _dt(value)
        if not d:
            return False
        ms = int(d.timestamp() * 1000)
        return visible_start <= ms <= visible_end

    def overlaps_window(opened_at: Any, closed_at: Any) -> bool:
        o = _dt(opened_at)
        z = _dt(closed_at)
        if not o or not z:
            return False
        return int(o.timestamp() * 1000) <= visible_end and int(z.timestamp() * 1000) >= visible_start

    chart_trades = [
        {
            "id": t.get("id"),
            "strategy_id": t.get("strategy_id"),
            "side": t.get("side"),
            "opened_at": t.get("opened_at"),
            "closed_at": t.get("closed_at"),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "stop_loss": t.get("stop_loss"),
            "take_profit": t.get("take_profit"),
            "net_pnl": t.get("net_pnl"),
            "r_multiple": t.get("r_multiple"),
            "exit_reason": t.get("exit_reason"),
        }
        for t in trades
        if overlaps_window(t.get("opened_at"), t.get("closed_at"))
    ][-80:]

    news = recent_news(limit=60, hours=168, symbol=symbol.replace("USDT", ""))
    cases = {str(x["strategy_id"]): x for x in list_strategy_cases(include_archived=True)}
    history = []
    for t in reversed(trades):
        history.append({
            **t,
            "strategy_name": cases.get(str(t.get("strategy_id")), {}).get("name", t.get("strategy_id")),
            "strategy_short_name": cases.get(str(t.get("strategy_id")), {}).get("short_name", t.get("strategy_id")),
        })

    return {
        "symbol": symbol,
        "stats": stats,
        "best_case": summary.get("best_case"),
        "worst_case": summary.get("worst_case"),
        "by_case": summary.get("by_case") or {},
        "by_side": summary.get("by_side") or {},
        "by_regime": summary.get("by_regime") or {},
        "exit_reasons": summary.get("exit_reasons") or {},
        "open_positions": positions,
        "trade_history": history,
        "news": news,
        "research": _research_context(symbol),
        "chart": {
            "interval": interval,
            "visible_start_ms": visible_start,
            "visible_end_ms": visible_end,
            "candles": [_candle(row) for _, row in df.iterrows()],
            "trades": chart_trades,
            "open_positions": [
                {
                    "id": x.get("id"),
                    "strategy_id": x.get("strategy_id"),
                    "side": x.get("side"),
                    "opened_at": x.get("opened_at"),
                    "entry_price": x.get("entry_price"),
                    "stop_loss": x.get("stop_loss"),
                    "take_profit": x.get("take_profit"),
                    "last_price": x.get("last_price"),
                }
                for x in positions
                if (_dt(x.get("opened_at")) and int(_dt(x.get("opened_at")).timestamp() * 1000) <= visible_end)
            ],
        },
        "note": (
            "Coin-level statistics aggregate paper trades across strategy cases. "
            "Use per-case and per-trade detail before drawing conclusions."
        ),
    }
