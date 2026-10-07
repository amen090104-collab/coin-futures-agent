from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .binance import BinanceClient
from .storage import _connect


def _as_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def init_trade_journal_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS trade_attributions (
                trade_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                outcome_class TEXT NOT NULL,
                thesis_quality TEXT NOT NULL,
                external_influence TEXT NOT NULL,
                primary_cause TEXT NOT NULL,
                signal_quality REAL NOT NULL,
                entry_quality REAL NOT NULL,
                stop_quality REAL NOT NULL,
                target_quality REAL NOT NULL,
                market_context_quality REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trade_attribution_cause
            ON trade_attributions(primary_cause, outcome_class);
            """
        )


def build_decision_thesis(
    row: dict[str, Any],
    plan: Any,
    spec: dict[str, Any],
    news_context: dict[str, Any],
    target_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    side = str(plan.side)
    score = float(plan.score)
    reasons = list(
        row.get("reasons_long", []) if side == "LONG" else row.get("reasons_short", [])
    )[:8]
    risks: list[str] = []
    distance = float(row.get("distance_ema20_atr") or 0)
    if distance >= 2:
        risks.append(f"Giá cách EMA20 khoảng {distance:.2f} ATR; rủi ro entry trễ.")
    funding = float(row.get("funding_rate") or 0)
    if side == "LONG" and funding > 0.0008:
        risks.append("Funding cao, phía LONG có dấu hiệu đông.")
    if side == "SHORT" and funding < -0.0008:
        risks.append("Funding âm sâu, phía SHORT có dấu hiệu đông.")
    if news_context.get("high_impact"):
        risks.append("Có tin high-impact gần thời điểm vào lệnh.")

    target_meta = target_meta or {}
    expected = (
        f"{side} theo {spec.get('direction_mode','BASE')} | "
        f"exit={spec.get('exit_mode','FIXED_RR')} | "
        f"RR mục tiêu {float(spec.get('rr') or 0):g}"
    )
    if target_meta.get("target_reason"):
        expected += f" | {target_meta['target_reason']}"

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "thesis": {
            "side": side,
            "score": score,
            "main_reason": reasons[0] if reasons else "quantitative score passed",
            "supporting_reasons": reasons,
            "risks": risks,
            "expected_scenario": expected,
        },
        "market_snapshot": {
            "btc_regime": plan.entry_context.get("btc_regime"),
            "long_score": row.get("long_score"),
            "short_score": row.get("short_score"),
            "rsi_1h": row.get("rsi_1h"),
            "volume_ratio_1h": row.get("volume_ratio_1h"),
            "atr_pct_1h": row.get("atr_pct_1h"),
            "oi_change_pct": row.get("oi_change_pct"),
            "funding_rate": row.get("funding_rate"),
            "distance_ema20_atr": row.get("distance_ema20_atr"),
        },
        "case_snapshot": {
            "strategy_id": spec.get("strategy_id"),
            "name": spec.get("name"),
            "version": spec.get("version"),
            "direction_mode": spec.get("direction_mode"),
            "rr": spec.get("rr"),
            "exit_mode": spec.get("exit_mode"),
        },
        "news_snapshot": news_context,
        "target_meta": target_meta,
    }


def _trade_row(trade_id: int) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM battle_trades WHERE id=?",
            (int(trade_id),),
        ).fetchone()
    return dict(row) if row else None


def _news_timeline(trade: dict[str, Any]) -> list[dict[str, Any]]:
    opened = _as_dt(trade["opened_at"]) - timedelta(minutes=30)
    closed = _as_dt(trade["closed_at"]) + timedelta(minutes=10)
    base = str(trade["symbol"]).replace("USDT", "").upper()
    with _connect() as con:
        rows = con.execute(
            """
            SELECT source,title,url,published_at,sentiment,sentiment_score,
                   impact_score,category,symbols
            FROM news_articles
            WHERE published_at>=? AND published_at<=?
            ORDER BY published_at
            """,
            (opened.isoformat(), closed.isoformat()),
        ).fetchall()
    out: list[dict[str, Any]] = []
    systemic = {"MACRO", "REGULATION", "SECURITY", "EXCHANGE"}
    for row in rows:
        d = dict(row)
        try:
            symbols = json.loads(d.get("symbols") or "[]")
        except Exception:
            symbols = []
        if base not in symbols and str(d.get("category")) not in systemic:
            continue
        d["symbols"] = symbols
        out.append(d)
    return out


def _score10(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 5.0
    return round(max(0.0, min(10.0, (value - lo) / (hi - lo) * 10.0)), 1)


def compute_trade_attribution(trade: dict[str, Any]) -> dict[str, Any]:
    try:
        context = json.loads(trade.get("entry_context") or "{}")
    except Exception:
        context = {}
    timeline = _news_timeline(trade)
    high_news = [x for x in timeline if float(x.get("impact_score") or 0) >= 75]
    net = float(trade.get("net_pnl") or 0)
    win = net > 0
    score = float(trade.get("score") or 0)
    mfe = float(trade.get("mfe_r") or 0)
    mae = float(trade.get("mae_r") or 0)
    distance = float(context.get("distance_ema20_atr") or 0)

    external = "HIGH" if high_news else "LOW"
    if high_news:
        outcome_class = "NEWS_ASSISTED_WIN" if win else "NEWS_SHOCK_LOSS"
        primary = "EXTERNAL_NEWS_CATALYST"
    elif win:
        outcome_class = "THESIS_CONFIRMED"
        primary = "SETUP_FOLLOW_THROUGH"
    elif distance >= 2.0:
        outcome_class = "THESIS_FAILED"
        primary = "LATE_OR_EXTENDED_ENTRY"
    elif mfe >= 0.65 and str(trade.get("exit_reason")) == "STOP_LOSS":
        outcome_class = "THESIS_PARTIAL"
        primary = "EXIT_MANAGEMENT_OR_REVERSAL"
    else:
        outcome_class = "THESIS_FAILED"
        primary = "DIRECTION_OR_CONTEXT_MISMATCH"

    signal_q = _score10(score, 65, 95)
    entry_q = round(max(0.0, min(10.0, 9.0 - max(0.0, distance - 0.8) * 2.3)), 1)
    stop_q = 7.5
    target_q = 7.5
    if not win and mfe >= 0.8:
        target_q = 4.5
    if win and str(trade.get("exit_reason")) == "TAKE_PROFIT":
        target_q = 8.5
    market_q = 5.0
    regime = str(context.get("btc_regime") or "NEUTRAL")
    source_side = str(context.get("source_signal_side") or trade.get("side") or "")
    if regime == "NEUTRAL":
        market_q = 6.0
    elif (regime == "BULLISH" and source_side == "LONG") or (
        regime == "BEARISH" and source_side == "SHORT"
    ):
        market_q = 7.5
    else:
        market_q = 4.5

    thesis_quality = "HIGH" if signal_q >= 7.5 and entry_q >= 6.5 else "MEDIUM" if signal_q >= 5 else "LOW"
    return {
        "trade_id": int(trade["id"]),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "outcome_class": outcome_class,
        "thesis_quality": thesis_quality,
        "external_influence": external,
        "primary_cause": primary,
        "signal_quality": signal_q,
        "entry_quality": entry_q,
        "stop_quality": stop_q,
        "target_quality": target_q,
        "market_context_quality": market_q,
        "news_timeline": timeline,
        "high_impact_news": len(high_news),
        "mfe_r": mfe,
        "mae_r": mae,
        "explanation": (
            "Kết quả có ảnh hưởng đáng kể từ tin high-impact trong thời gian giữ lệnh."
            if high_news
            else "Không phát hiện tin high-impact phù hợp trong cửa sổ giữ lệnh; kết quả chủ yếu quy cho setup/market context."
        ),
    }


def save_trade_attribution(trade_id: int) -> dict[str, Any] | None:
    init_trade_journal_db()
    trade = _trade_row(trade_id)
    if not trade:
        return None
    payload = compute_trade_attribution(trade)
    with _connect() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO trade_attributions(
                trade_id,created_at,outcome_class,thesis_quality,external_influence,
                primary_cause,signal_quality,entry_quality,stop_quality,target_quality,
                market_context_quality,payload
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(trade_id), payload["created_at"], payload["outcome_class"],
                payload["thesis_quality"], payload["external_influence"],
                payload["primary_cause"], payload["signal_quality"], payload["entry_quality"],
                payload["stop_quality"], payload["target_quality"],
                payload["market_context_quality"], json.dumps(payload),
            ),
        )
    return payload


def get_trade_attribution(trade_id: int) -> dict[str, Any] | None:
    init_trade_journal_db()
    with _connect() as con:
        row = con.execute(
            "SELECT payload FROM trade_attributions WHERE trade_id=?",
            (int(trade_id),),
        ).fetchone()
    if row:
        try:
            return json.loads(row["payload"])
        except Exception:
            pass
    return save_trade_attribution(trade_id)


def attribution_summary(strategy_id: str | None = None) -> dict[str, Any]:
    init_trade_journal_db()
    with _connect() as con:
        if strategy_id:
            rows = con.execute(
                """
                SELECT a.*,t.net_pnl,t.r_multiple
                FROM trade_attributions a
                JOIN battle_trades t ON t.id=a.trade_id
                WHERE t.strategy_id=?
                ORDER BY a.trade_id
                """,
                (strategy_id,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT a.*,t.net_pnl,t.r_multiple
                FROM trade_attributions a
                JOIN battle_trades t ON t.id=a.trade_id
                ORDER BY a.trade_id
                """
            ).fetchall()
    by_cause: dict[str, dict[str, Any]] = {}
    thesis_pnl = 0.0
    quality_adjusted_pnl = 0.0
    for row in rows:
        d = dict(row)
        cause = str(d["primary_cause"])
        bucket = by_cause.setdefault(cause, {"trades": 0, "net_pnl": 0.0})
        bucket["trades"] += 1
        bucket["net_pnl"] += float(d["net_pnl"])
        if d["outcome_class"] == "THESIS_CONFIRMED":
            thesis_pnl += float(d["net_pnl"])
        if d["outcome_class"] not in {"NEWS_ASSISTED_WIN"}:
            quality_adjusted_pnl += float(d["net_pnl"])
    return {
        "trades": len(rows),
        "by_primary_cause": by_cause,
        "thesis_confirmed_pnl": round(thesis_pnl, 2),
        "quality_adjusted_pnl_ex_news_assisted": round(quality_adjusted_pnl, 2),
    }


async def trade_detail(trade_id: int, interval: str = "15m") -> dict[str, Any]:
    trade = _trade_row(trade_id)
    if not trade:
        raise KeyError(trade_id)
    interval = interval if interval in {"1m", "5m", "15m", "1h"} else "15m"
    opened = _as_dt(trade["opened_at"])
    closed = _as_dt(trade["closed_at"])
    pad_before = timedelta(hours=4)
    pad_after = timedelta(hours=2)
    start_ms = int((opened - pad_before).timestamp() * 1000)
    end_ms = int((closed + pad_after).timestamp() * 1000)

    client = BinanceClient()
    try:
        if interval == "1m":
            df = await client.klines_1m_between(str(trade["symbol"]), start_ms, end_ms)
            if len(df) > 3000:
                df = df.tail(3000)
        else:
            df = await client.klines(
                str(trade["symbol"]),
                interval,
                1000,
                start_time=start_ms,
                end_time=end_ms,
            )
    finally:
        await client.close()

    candles = [
        {
            "open_time": int(r["open_time"]),
            "close_time": int(r["close_time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
        }
        for _, r in df.iterrows()
    ]
    try:
        context = json.loads(trade.get("entry_context") or "{}")
    except Exception:
        context = {}
    return {
        "trade": trade,
        "entry_context": context,
        "decision_thesis": context.get("decision_thesis"),
        "attribution": get_trade_attribution(trade_id),
        "interval": interval,
        "candles": candles,
        "markers": {
            "entry": {"time": trade["opened_at"], "price": trade["entry_price"]},
            "exit": {"time": trade["closed_at"], "price": trade["exit_price"]},
            "stop_loss": trade["stop_loss"],
            "take_profit": trade["take_profit"],
        },
    }
