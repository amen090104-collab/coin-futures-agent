from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("agent.db")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                signal_price REAL NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                quantity REAL NOT NULL,
                risk_usdt REAL NOT NULL,
                initial_risk_per_unit REAL NOT NULL,
                score REAL NOT NULL,
                reason_text TEXT NOT NULL,
                reason_codes TEXT NOT NULL,
                entry_context TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                max_favorable_price REAL NOT NULL,
                max_adverse_price REAL NOT NULL,
                last_price REAL NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                quantity REAL NOT NULL,
                score REAL NOT NULL,
                gross_pnl REAL NOT NULL,
                fees REAL NOT NULL,
                net_pnl REAL NOT NULL,
                r_multiple REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                holding_minutes REAL NOT NULL,
                mfe_r REAL NOT NULL,
                mae_r REAL NOT NULL,
                reason_text TEXT NOT NULL,
                reason_codes TEXT NOT NULL,
                entry_context TEXT NOT NULL,
                loss_analysis TEXT,
                fix_suggestions TEXT
            );

            CREATE TABLE IF NOT EXISTS account_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                report_date TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                markdown_path TEXT
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                evidence TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PROPOSED'
            );

            CREATE TABLE IF NOT EXISTS news_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                sentiment_score REAL NOT NULL,
                impact_score REAL NOT NULL,
                category TEXT NOT NULL,
                symbols TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_articles(published_at DESC);
            """
        )


def save_scan(created_at: str, payload: dict[str, Any]) -> None:
    with _connect() as con:
        con.execute("INSERT INTO scans(created_at, payload) VALUES (?, ?)", (created_at, json.dumps(payload)))


def latest_scan() -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute("SELECT payload FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None


def ensure_initial_balance(created_at: str, amount: float) -> None:
    with _connect() as con:
        row = con.execute("SELECT COUNT(*) c FROM account_events").fetchone()
        if int(row["c"]) == 0:
            con.execute(
                "INSERT INTO account_events(created_at,event_type,amount,note) VALUES (?,?,?,?)",
                (created_at, "INITIAL_BALANCE", amount, "paper account starting balance"),
            )


def account_balance() -> float:
    with _connect() as con:
        row = con.execute("SELECT COALESCE(SUM(amount),0) v FROM account_events").fetchone()
    return float(row["v"])


def add_account_event(created_at: str, event_type: str, amount: float, note: str) -> None:
    with _connect() as con:
        con.execute(
            "INSERT INTO account_events(created_at,event_type,amount,note) VALUES (?,?,?,?)",
            (created_at, event_type, amount, note),
        )


def open_positions() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM positions WHERE status='OPEN' ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def has_open_symbol(symbol: str) -> bool:
    with _connect() as con:
        row = con.execute("SELECT 1 FROM positions WHERE status='OPEN' AND symbol=? LIMIT 1", (symbol,)).fetchone()
    return row is not None


def insert_position(p: dict[str, Any]) -> int:
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO positions(
                symbol,side,opened_at,signal_price,entry_price,stop_loss,take_profit,quantity,
                risk_usdt,initial_risk_per_unit,score,reason_text,reason_codes,entry_context,status,
                max_favorable_price,max_adverse_price,last_price,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN',?,?,?,?)
            """,
            (
                p["symbol"], p["side"], p["opened_at"], p["signal_price"], p["entry_price"],
                p["stop_loss"], p["take_profit"], p["quantity"], p["risk_usdt"],
                p["initial_risk_per_unit"], p["score"], p["reason_text"],
                json.dumps(p["reason_codes"]), json.dumps(p["entry_context"]),
                p["entry_price"], p["entry_price"], p["entry_price"], p["opened_at"],
            ),
        )
        return int(cur.lastrowid)


def update_position_excursion(position_id: int, favorable: float, adverse: float, last_price: float, updated_at: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE positions SET max_favorable_price=?,max_adverse_price=?,last_price=?,updated_at=? WHERE id=?",
            (favorable, adverse, last_price, updated_at, position_id),
        )


def close_position(position_id: int, closed_at: str, trade: dict[str, Any]) -> int:
    with _connect() as con:
        con.execute("UPDATE positions SET status='CLOSED',updated_at=? WHERE id=?", (closed_at, position_id))
        cur = con.execute(
            """
            INSERT INTO trades(
                position_id,symbol,side,opened_at,closed_at,entry_price,exit_price,stop_loss,take_profit,
                quantity,score,gross_pnl,fees,net_pnl,r_multiple,exit_reason,holding_minutes,mfe_r,mae_r,
                reason_text,reason_codes,entry_context,loss_analysis,fix_suggestions
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                position_id, trade["symbol"], trade["side"], trade["opened_at"], trade["closed_at"],
                trade["entry_price"], trade["exit_price"], trade["stop_loss"], trade["take_profit"],
                trade["quantity"], trade["score"], trade["gross_pnl"], trade["fees"], trade["net_pnl"],
                trade["r_multiple"], trade["exit_reason"], trade["holding_minutes"], trade["mfe_r"], trade["mae_r"],
                trade["reason_text"], json.dumps(trade["reason_codes"]), json.dumps(trade["entry_context"]),
                json.dumps(trade.get("loss_analysis", [])), json.dumps(trade.get("fix_suggestions", [])),
            ),
        )
        return int(cur.lastrowid)


def trades_between(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM trades WHERE closed_at>=? AND closed_at<? ORDER BY closed_at",
            (start_iso, end_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def recent_trades(limit: int = 40) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows][::-1]


def save_daily_report(report_date: str, created_at: str, payload: dict[str, Any], markdown_path: str | None) -> None:
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO daily_reports(report_date,created_at,payload,markdown_path) VALUES (?,?,?,?)",
            (report_date, created_at, json.dumps(payload), markdown_path),
        )


def get_daily_report(report_date: str) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute("SELECT payload FROM daily_reports WHERE report_date=?", (report_date,)).fetchone()
    return json.loads(row["payload"]) if row else None


def latest_daily_reports(limit: int = 14) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT report_date,payload,markdown_path FROM daily_reports ORDER BY report_date DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        p["report_date"] = r["report_date"]
        p["markdown_path"] = r["markdown_path"]
        out.append(p)
    return out


def add_recommendation(created_at: str, source: str, recommendation: str, evidence: str) -> None:
    with _connect() as con:
        existing = con.execute(
            "SELECT 1 FROM recommendations WHERE status='PROPOSED' AND recommendation=? LIMIT 1",
            (recommendation,),
        ).fetchone()
        if not existing:
            con.execute(
                "INSERT INTO recommendations(created_at,source,recommendation,evidence) VALUES (?,?,?,?)",
                (created_at, source, recommendation, evidence),
            )


def list_recommendations(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM recommendations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_news_articles(articles: list[dict[str, Any]]) -> int:
    if not articles:
        return 0
    count = 0
    with _connect() as con:
        for a in articles:
            if not a.get("url"):
                continue
            con.execute(
                """
                INSERT INTO news_articles(
                    source,title,summary,url,published_at,fetched_at,sentiment,sentiment_score,impact_score,category,symbols
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    source=excluded.source, title=excluded.title, summary=excluded.summary,
                    published_at=excluded.published_at, fetched_at=excluded.fetched_at,
                    sentiment=excluded.sentiment, sentiment_score=excluded.sentiment_score,
                    impact_score=excluded.impact_score, category=excluded.category, symbols=excluded.symbols
                """,
                (
                    a.get("source", ""), a.get("title", ""), a.get("summary", ""), a.get("url", ""),
                    a.get("published_at", ""), a.get("fetched_at", ""), a.get("sentiment", "NEUTRAL"),
                    float(a.get("sentiment_score") or 0), float(a.get("impact_score") or 0),
                    a.get("category", "PROJECT"), json.dumps(a.get("symbols") or []),
                ),
            )
            count += 1
    return count


def recent_news(limit: int = 60, hours: int | None = None, symbol: str | None = None) -> list[dict[str, Any]]:
    import datetime as _dt
    clauses = []
    params: list[Any] = []
    if hours is not None:
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)).isoformat()
        clauses.append("published_at>=?")
        params.append(cutoff)
    if symbol:
        clauses.append("symbols LIKE ?")
        params.append(f'%"{symbol}"%')
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(min(max(int(limit), 1), 500))
    with _connect() as con:
        rows = con.execute(
            f"SELECT * FROM news_articles{where} ORDER BY published_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    out = []
    for r in rows:
        x = dict(r)
        try:
            x["symbols"] = json.loads(x.get("symbols") or "[]")
        except Exception:
            x["symbols"] = []
        out.append(x)
    return out
