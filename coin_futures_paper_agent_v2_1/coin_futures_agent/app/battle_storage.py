from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .battle_config import STRATEGIES, STRATEGY_IDS
from .storage import _connect


def init_battle_db() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS battle_account_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_battle_account_strategy
            ON battle_account_events(strategy_id, id);

            CREATE TABLE IF NOT EXISTS battle_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_battle_positions_status
            ON battle_positions(status, strategy_id, symbol);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_battle_one_open_symbol
            ON battle_positions(strategy_id, symbol)
            WHERE status='OPEN';

            CREATE TABLE IF NOT EXISTS battle_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL,
                strategy_id TEXT NOT NULL,
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
            CREATE UNIQUE INDEX IF NOT EXISTS idx_battle_trade_position
            ON battle_trades(position_id);
            CREATE INDEX IF NOT EXISTS idx_battle_trades_strategy_closed
            ON battle_trades(strategy_id, closed_at);
            """
        )


def ensure_battle_initial_balances(created_at: str, amount: float) -> None:
    init_battle_db()
    with _connect() as con:
        for strategy_id in STRATEGY_IDS:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM battle_account_events WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            if int(row["c"]) == 0:
                con.execute(
                    """
                    INSERT INTO battle_account_events(
                        strategy_id,created_at,event_type,amount,note
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        strategy_id,
                        created_at,
                        "INITIAL_BALANCE",
                        float(amount),
                        f"{STRATEGIES[strategy_id]['name']} starting balance",
                    ),
                )


def battle_account_balance(strategy_id: str) -> float:
    with _connect() as con:
        row = con.execute(
            "SELECT COALESCE(SUM(amount),0) AS v FROM battle_account_events WHERE strategy_id=?",
            (strategy_id,),
        ).fetchone()
    return float(row["v"])


def battle_balances() -> dict[str, float]:
    return {sid: battle_account_balance(sid) for sid in STRATEGY_IDS}


def battle_open_positions(strategy_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as con:
        if strategy_id:
            rows = con.execute(
                """
                SELECT * FROM battle_positions
                WHERE status='OPEN' AND strategy_id=?
                ORDER BY id
                """,
                (strategy_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM battle_positions WHERE status='OPEN' ORDER BY id"
            ).fetchall()
    return [dict(r) for r in rows]


def battle_has_open_symbol(strategy_id: str, symbol: str) -> bool:
    with _connect() as con:
        row = con.execute(
            """
            SELECT 1 FROM battle_positions
            WHERE status='OPEN' AND strategy_id=? AND symbol=?
            LIMIT 1
            """,
            (strategy_id, symbol),
        ).fetchone()
    return row is not None


def insert_battle_position(position: dict[str, Any]) -> int:
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO battle_positions(
                strategy_id,symbol,side,opened_at,signal_price,entry_price,stop_loss,take_profit,
                quantity,risk_usdt,initial_risk_per_unit,score,reason_text,reason_codes,entry_context,
                status,max_favorable_price,max_adverse_price,last_price,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?,?,?)
            """,
            (
                position["strategy_id"],
                position["symbol"],
                position["side"],
                position["opened_at"],
                position["signal_price"],
                position["entry_price"],
                position["stop_loss"],
                position["take_profit"],
                position["quantity"],
                position["risk_usdt"],
                position["initial_risk_per_unit"],
                position["score"],
                position["reason_text"],
                json.dumps(position["reason_codes"]),
                json.dumps(position["entry_context"]),
                position["entry_price"],
                position["entry_price"],
                position["entry_price"],
                position["opened_at"],
            ),
        )
        return int(cur.lastrowid)


def update_battle_position_excursion(
    position_id: int,
    favorable: float,
    adverse: float,
    last_price: float,
    updated_at: str,
) -> None:
    with _connect() as con:
        con.execute(
            """
            UPDATE battle_positions
            SET max_favorable_price=?,max_adverse_price=?,last_price=?,updated_at=?
            WHERE id=?
            """,
            (favorable, adverse, last_price, updated_at, position_id),
        )


def close_battle_position_atomic(
    position_id: int,
    closed_at: str,
    trade: dict[str, Any],
) -> int:
    strategy_id = str(trade["strategy_id"])
    with _connect() as con:
        existing = con.execute(
            "SELECT id FROM battle_trades WHERE position_id=? LIMIT 1",
            (position_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        con.execute(
            """
            UPDATE battle_positions
            SET status='CLOSED',updated_at=?
            WHERE id=? AND status='OPEN'
            """,
            (closed_at, position_id),
        )
        cur = con.execute(
            """
            INSERT INTO battle_trades(
                position_id,strategy_id,symbol,side,opened_at,closed_at,entry_price,exit_price,
                stop_loss,take_profit,quantity,score,gross_pnl,fees,net_pnl,r_multiple,
                exit_reason,holding_minutes,mfe_r,mae_r,reason_text,reason_codes,entry_context,
                loss_analysis,fix_suggestions
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                position_id,
                strategy_id,
                trade["symbol"],
                trade["side"],
                trade["opened_at"],
                trade["closed_at"],
                trade["entry_price"],
                trade["exit_price"],
                trade["stop_loss"],
                trade["take_profit"],
                trade["quantity"],
                trade["score"],
                trade["gross_pnl"],
                trade["fees"],
                trade["net_pnl"],
                trade["r_multiple"],
                trade["exit_reason"],
                trade["holding_minutes"],
                trade["mfe_r"],
                trade["mae_r"],
                trade["reason_text"],
                json.dumps(trade["reason_codes"]),
                json.dumps(trade["entry_context"]),
                json.dumps(trade.get("loss_analysis", [])),
                json.dumps(trade.get("fix_suggestions", [])),
            ),
        )
        trade_id = int(cur.lastrowid)
        con.execute(
            """
            INSERT INTO battle_account_events(
                strategy_id,created_at,event_type,amount,note
            ) VALUES (?,?,?,?,?)
            """,
            (
                strategy_id,
                closed_at,
                "TRADE_PNL",
                float(trade["net_pnl"]),
                (
                    f"battle trade {trade_id} {trade['symbol']} {trade['side']} "
                    f"{trade['exit_reason']}"
                ),
            ),
        )
        return trade_id


def battle_recent_trades(
    limit: int = 100,
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), 5000)
    with _connect() as con:
        if strategy_id:
            rows = con.execute(
                """
                SELECT * FROM battle_trades
                WHERE strategy_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (strategy_id, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM battle_trades ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows][::-1]


def battle_trades_between(
    start_iso: str,
    end_iso: str,
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    with _connect() as con:
        if strategy_id:
            rows = con.execute(
                """
                SELECT * FROM battle_trades
                WHERE strategy_id=? AND closed_at>=? AND closed_at<?
                ORDER BY closed_at,id
                """,
                (strategy_id, start_iso, end_iso),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT * FROM battle_trades
                WHERE closed_at>=? AND closed_at<?
                ORDER BY closed_at,id
                """,
                (start_iso, end_iso),
            ).fetchall()
    return [dict(r) for r in rows]


def reset_strategy_battle_data(starting_balance: float) -> dict[str, Any]:
    """Clear previous Futures paper history and initialize a fresh 3-case experiment."""
    init_battle_db()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        reset_tables = (
            "battle_trades",
            "battle_positions",
            "battle_account_events",
            "trades",
            "positions",
            "account_events",
            "daily_reports",
            "recommendations",
            "scans",
        )
        for table in reset_tables:
            con.execute(f"DELETE FROM {table}")
        placeholders = ",".join("?" for _ in reset_tables)
        con.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
            reset_tables,
        )
        for strategy_id in STRATEGY_IDS:
            con.execute(
                """
                INSERT INTO battle_account_events(
                    strategy_id,created_at,event_type,amount,note
                ) VALUES (?,?,?,?,?)
                """,
                (
                    strategy_id,
                    now,
                    "INITIAL_BALANCE",
                    float(starting_balance),
                    f"{STRATEGIES[strategy_id]['name']} fresh experiment balance",
                ),
            )
        con.commit()

    return {
        "reset_at": now,
        "starting_balance_each": float(starting_balance),
        "strategies": [
            {
                "strategy_id": sid,
                **STRATEGIES[sid],
            }
            for sid in STRATEGY_IDS
        ],
    }
