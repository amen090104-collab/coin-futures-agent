from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("agent.db")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=FULL;")
    con.execute("PRAGMA busy_timeout=5000;")
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

            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events(created_at DESC);

            CREATE TABLE IF NOT EXISTS spot_research (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_spot_research_created_at ON spot_research(created_at DESC);

            CREATE TABLE IF NOT EXISTS news_guardian_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                scope TEXT NOT NULL,
                symbols TEXT NOT NULL,
                category TEXT NOT NULL,
                impact_score REAL NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                cooldown_until TEXT,
                reference_symbol TEXT NOT NULL,
                reference_price REAL NOT NULL,
                headline TEXT NOT NULL,
                payload TEXT NOT NULL,
                reactions TEXT NOT NULL DEFAULT '{}',
                prediction_result TEXT NOT NULL DEFAULT 'PENDING'
            );
            CREATE INDEX IF NOT EXISTS idx_news_guardian_created
            ON news_guardian_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_guardian_status
            ON news_guardian_events(status, cooldown_until);
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


def close_position_atomic(position_id: int, closed_at: str, trade: dict[str, Any]) -> int:
    """Close a position, persist the trade and book paper PnL in one SQLite transaction."""
    with _connect() as con:
        existing = con.execute(
            "SELECT id FROM trades WHERE position_id=? ORDER BY id DESC LIMIT 1",
            (position_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        con.execute(
            "UPDATE positions SET status='CLOSED',updated_at=? WHERE id=? AND status='OPEN'",
            (closed_at, position_id),
        )
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
        trade_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO account_events(created_at,event_type,amount,note) VALUES (?,?,?,?)",
            (
                closed_at,
                "TRADE_PNL",
                float(trade["net_pnl"]),
                f"trade {trade_id} {trade['symbol']} {trade['side']} {trade['exit_reason']}",
            ),
        )
        return trade_id


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


def reconcile_trade_pnl_events() -> int:
    """Repair legacy half-commits where a trade exists but its paper PnL event is missing."""
    repaired = 0
    with _connect() as con:
        trades = con.execute(
            "SELECT id,closed_at,symbol,side,exit_reason,net_pnl FROM trades ORDER BY id"
        ).fetchall()
        for trade in trades:
            prefix = f"trade {trade['id']} "
            exists = con.execute(
                "SELECT 1 FROM account_events WHERE event_type='TRADE_PNL' AND note LIKE ? LIMIT 1",
                (prefix + "%",),
            ).fetchone()
            if exists:
                continue
            con.execute(
                "INSERT INTO account_events(created_at,event_type,amount,note) VALUES (?,?,?,?)",
                (
                    trade["closed_at"],
                    "TRADE_PNL",
                    float(trade["net_pnl"]),
                    f"trade {trade['id']} {trade['symbol']} {trade['side']} {trade['exit_reason']} [reconciled]",
                ),
            )
            repaired += 1
    return repaired


def set_system_state(key: str, value: Any, updated_at: str | None = None) -> None:
    updated_at = updated_at or datetime.now(timezone.utc).isoformat()
    raw = value if isinstance(value, str) else json.dumps(value)
    with _connect() as con:
        con.execute(
            """
            INSERT INTO system_state(key,value,updated_at) VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
            """,
            (key, raw, updated_at),
        )


def get_system_state(key: str, default: Any = None) -> Any:
    with _connect() as con:
        row = con.execute("SELECT value FROM system_state WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    raw = row["value"]
    try:
        return json.loads(raw)
    except Exception:
        return raw


def system_state_snapshot() -> dict[str, Any]:
    with _connect() as con:
        rows = con.execute("SELECT key,value,updated_at FROM system_state ORDER BY key").fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        raw = row["value"]
        try:
            value = json.loads(raw)
        except Exception:
            value = raw
        out[row["key"]] = {"value": value, "updated_at": row["updated_at"]}
    return out


def log_system_event(
    event_type: str,
    message: str,
    severity: str = "INFO",
    payload: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> int:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO system_events(created_at,event_type,severity,message,payload) VALUES (?,?,?,?,?)",
            (created_at, event_type, severity, message, json.dumps(payload or {})),
        )
        return int(cur.lastrowid)


def recent_system_events(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM system_events ORDER BY id DESC LIMIT ?",
            (min(max(int(limit), 1), 500),),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except Exception:
            item["payload"] = {}
        out.append(item)
    return out


def save_spot_research(created_at: str, market_regime: str, payload: dict[str, Any]) -> int:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO spot_research(created_at,market_regime,payload) VALUES (?,?,?)",
            (created_at, market_regime, json.dumps(payload)),
        )
        return int(cur.lastrowid)


def latest_spot_research(limit: int = 5) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id,created_at,market_regime,payload FROM spot_research ORDER BY id DESC LIMIT ?",
            (min(max(int(limit), 1), 100),),
        ).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload"])
        payload["id"] = row["id"]
        payload["created_at"] = row["created_at"]
        payload["market_regime"] = row["market_regime"]
        out.append(payload)
    return out


def backup_database(backup_dir: str = "backups", retention: int = 20) -> str:
    if not DB_PATH.exists():
        raise FileNotFoundError(str(DB_PATH))
    folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"agent-{stamp}.db"
    tmp = folder / f".agent-{stamp}.tmp"

    with _connect() as src:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    tmp.replace(target)

    backups = sorted(folder.glob("agent-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, int(retention)):]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(target)


def save_news_guardian_event(event: dict[str, Any]) -> int:
    with _connect() as con:
        con.execute(
            """
            INSERT INTO news_guardian_events(
                event_key,created_at,updated_at,status,scope,symbols,category,
                impact_score,direction,confidence,cooldown_until,reference_symbol,
                reference_price,headline,payload,reactions,prediction_result
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
                updated_at=excluded.updated_at,
                status=excluded.status,
                scope=excluded.scope,
                symbols=excluded.symbols,
                category=excluded.category,
                impact_score=excluded.impact_score,
                direction=excluded.direction,
                confidence=excluded.confidence,
                cooldown_until=CASE
                    WHEN news_guardian_events.cooldown_until IS NOT NULL
                    THEN news_guardian_events.cooldown_until
                    ELSE excluded.cooldown_until
                END,
                reference_symbol=excluded.reference_symbol,
                reference_price=CASE
                    WHEN news_guardian_events.reference_price > 0
                    THEN news_guardian_events.reference_price
                    ELSE excluded.reference_price
                END,
                headline=excluded.headline,
                payload=excluded.payload
            """,
            (
                event["event_key"],
                event["created_at"],
                event.get("updated_at") or event["created_at"],
                event["status"],
                event["scope"],
                json.dumps(event.get("symbols", [])),
                event.get("category", "MARKET"),
                float(event.get("impact_score") or 0),
                event.get("direction", "UNCLEAR"),
                float(event.get("confidence") or 0),
                event.get("cooldown_until"),
                event.get("reference_symbol", "BTCUSDT"),
                float(event.get("reference_price") or 0),
                event.get("headline", ""),
                json.dumps(event.get("payload", {})),
                json.dumps(event.get("reactions", {})),
                event.get("prediction_result", "PENDING"),
            ),
        )
        row = con.execute(
            "SELECT id FROM news_guardian_events WHERE event_key=?",
            (event["event_key"],),
        ).fetchone()
        return int(row["id"])


def update_news_guardian_event(
    event_id: int,
    *,
    reactions: dict[str, Any] | None = None,
    prediction_result: str | None = None,
    status: str | None = None,
    updated_at: str | None = None,
) -> None:
    updated_at = updated_at or datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        if reactions is not None:
            con.execute(
                "UPDATE news_guardian_events SET reactions=?,updated_at=? WHERE id=?",
                (json.dumps(reactions), updated_at, event_id),
            )
        if prediction_result is not None:
            con.execute(
                "UPDATE news_guardian_events SET prediction_result=?,updated_at=? WHERE id=?",
                (prediction_result, updated_at, event_id),
            )
        if status is not None:
            con.execute(
                "UPDATE news_guardian_events SET status=?,updated_at=? WHERE id=?",
                (status, updated_at, event_id),
            )


def recent_news_guardian_events(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM news_guardian_events ORDER BY id DESC LIMIT ?",
            (min(max(int(limit), 1), 500),),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, fallback in (("symbols", []), ("payload", {}), ("reactions", {})):
            try:
                item[key] = json.loads(item.get(key) or json.dumps(fallback))
            except Exception:
                item[key] = fallback
        out.append(item)
    return out


def get_news_guardian_event(event_id: int) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM news_guardian_events WHERE id=?",
            (event_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    for key, fallback in (("symbols", []), ("payload", {}), ("reactions", {})):
        try:
            item[key] = json.loads(item.get(key) or json.dumps(fallback))
        except Exception:
            item[key] = fallback
    return item
