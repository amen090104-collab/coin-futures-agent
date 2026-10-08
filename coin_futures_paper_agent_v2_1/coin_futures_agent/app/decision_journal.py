"""Durable, append-only decision log for paper Strategy Battle.

Journal writes are best-effort and must never block a protective trade exit.
Historical trades without events are labeled RECONSTRUCTED at read time.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .storage import _connect

log = logging.getLogger(__name__)


def init_decision_journal() -> None:
    with _connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS trade_decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            trade_id INTEGER,
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            event_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(position_id,event_key)
        );
        CREATE INDEX IF NOT EXISTS idx_decision_journal_position
          ON trade_decision_journal(position_id,occurred_at);
        CREATE INDEX IF NOT EXISTS idx_decision_journal_trade
          ON trade_decision_journal(trade_id);
        """)


def append_decision(
    position: dict[str, Any],
    *,
    occurred_at: str,
    event_key: str,
    event_type: str,
    reason_code: str,
    details: dict[str, Any] | None = None,
    trade_id: int | None = None,
) -> bool:
    try:
        init_decision_journal()
        with _connect() as con:
            cur = con.execute(
                """INSERT OR IGNORE INTO trade_decision_journal
                   (position_id,trade_id,strategy_id,symbol,occurred_at,event_key,
                    event_type,reason_code,details_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (int(position["id"]), trade_id, str(position["strategy_id"]),
                 str(position["symbol"]), occurred_at, event_key, event_type,
                 reason_code, json.dumps(details or {}, ensure_ascii=False, default=str)),
            )
            return bool(cur.rowcount)
    except Exception:
        log.exception("Decision journal write failed; paper position remains authoritative")
        return False


def record_open(position_id: int, record: dict[str, Any]) -> None:
    if "id" not in record:
        position = {"id": position_id, **record}
    else:
        position = dict(record)
    ctx = position.get("entry_context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (ValueError, TypeError):
            ctx = {}
    thesis = ctx.get("entry_thesis") or {}
    append_decision(
        position,
        occurred_at=str(position["opened_at"]),
        event_key="ENTRY",
        event_type="ENTRY",
        reason_code="SOURCE_SIGNAL" if not ctx.get("strategy_reverse") else "REVERSE_EXPERIMENT",
        details={
            "side": position.get("side"), "entry_price": position.get("entry_price"),
            "stop_loss": position.get("stop_loss"), "take_profit": position.get("take_profit"),
            "score": position.get("score"), "thesis": thesis,
            "case_config": ctx.get("case_config") or {},
            "strategy_version": ctx.get("strategy_version"),
            "reason_text": position.get("reason_text"),
            "observations": {k: ctx.get(k) for k in (
                "btc_regime","rsi_1h","volume_ratio_1h","atr_pct_1h",
                "oi_change_pct","funding_rate","distance_ema20_atr"
            )},
        },
    )


def record_stop_change(position: dict[str, Any], evaluated: dict[str, Any]) -> None:
    """Log an effective dynamic stop only after prior-bar evidence changed it."""
    mode = str(evaluated.get("management_mode") or "FIXED")
    if mode == "FIXED" or evaluated.get("exit_reason"):
        return
    original = float(position["stop_loss"])
    effective = float(evaluated.get("effective_stop") or original)
    risk = abs(float(position["entry_price"]) - original)
    if risk <= 0 or abs(effective - original) < 0.15 * risk:
        return
    try:
        init_decision_journal()
        with _connect() as con:
            previous = con.execute(
                """SELECT details_json FROM trade_decision_journal
                   WHERE position_id=? AND event_type='STOP_UPDATE'
                   ORDER BY id DESC LIMIT 1""",
                (int(position["id"]),),
            ).fetchone()
        if previous:
            old_stop = json.loads(previous["details_json"]).get("effective_stop", original)
            if abs(effective - float(old_stop)) < risk * 0.20:
                return
        append_decision(
            position,
            occurred_at=str(evaluated["closed_at"]),
            event_key="STOP_UPDATE:" + str(evaluated["closed_at"]),
            event_type="STOP_UPDATE",
            reason_code=mode,
            details={"original_stop": original, "effective_stop": effective,
                     "prior_closed_candle_confirmation": True,
                     "note": "Calculated effective stop; source entry/SL/TP unchanged"},
        )
    except Exception:
        log.exception("Could not journal dynamic stop adjustment")


def record_milestones(position: dict[str, Any], evaluated: dict[str, Any]) -> None:
    """Journal meaningful price milestones, not noisy per-minute HOLD messages."""
    risk = abs(float(position["entry_price"]) - float(position["stop_loss"]))
    if risk <= 0:
        return
    entry = float(position["entry_price"])
    side = str(position["side"])
    before = float(position["max_favorable_price"])
    after = float(evaluated["favorable"])
    prior_r = (before - entry) / risk if side == "LONG" else (entry - before) / risk
    reached_r = (after - entry) / risk if side == "LONG" else (entry - after) / risk
    for threshold in (0.5, 1.0, 2.0):
        if prior_r < threshold <= reached_r:
            append_decision(
                position,
                occurred_at=str(evaluated["closed_at"]),
                event_key=f"MFE_{threshold:.1f}R",
                event_type="MILESTONE",
                reason_code=f"MFE_{threshold:.1f}R_REACHED",
                details={
                    "previous_mfe_r": round(prior_r, 3),
                    "current_mfe_r": round(reached_r, 3),
                    "source": "last_closed_1m_candle",
                    "note": "Observation, not proof of original thesis",
                },
            )


def record_exit(
    position: dict[str, Any],
    trade_id: int,
    trade: dict[str, Any],
) -> None:
    reason = str(trade.get("exit_reason") or "UNKNOWN")
    ctx = trade.get("entry_context") or {}
    append_decision(
        position, trade_id=int(trade_id),
        occurred_at=str(trade["closed_at"]),
        event_key="EXIT", event_type="EXIT", reason_code=reason,
        details={
            "exit_price": trade.get("exit_price"), "net_pnl": trade.get("net_pnl"),
            "r_multiple": trade.get("r_multiple"), "mfe_r": trade.get("mfe_r"),
            "mae_r": trade.get("mae_r"), "news_risk_exit": ctx.get("news_risk_exit"),
            "recovered_after_offline": ctx.get("recovered_after_offline", False),
        },
    )


def journal_for_trade(trade: dict[str, Any]) -> list[dict[str, Any]]:
    init_decision_journal()
    trade_id = int(trade["id"])
    ctx = trade.get("entry_context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (ValueError, TypeError):
            ctx = {}
    # New trades are keyed by position id in battle_trades. Older records may
    # predate the journal, therefore reconstruct only a minimal inferred history.
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM trade_decision_journal
               WHERE position_id=? ORDER BY occurred_at,id""",
            (int(trade["position_id"]),),
        ).fetchall()
    if rows:
        result = []
        for row in rows:
            x = dict(row)
            x["details"] = json.loads(x.pop("details_json") or "{}")
            x["source"] = "PERSISTED"
            result.append(x)
        return result
    return [
        {
            "event_type": "ENTRY", "occurred_at": trade.get("opened_at"),
            "reason_code": "HISTORICAL_ENTRY", "source": "RECONSTRUCTED",
            "details": {"entry_price": trade.get("entry_price"),
                        "thesis": ctx.get("entry_thesis"),
                        "reason_text": trade.get("reason_text")},
        },
        {
            "event_type": "EXIT", "occurred_at": trade.get("closed_at"),
            "reason_code": str(trade.get("exit_reason") or "UNKNOWN"),
            "source": "RECONSTRUCTED",
            "details": {"exit_price": trade.get("exit_price"),
                        "net_pnl": trade.get("net_pnl")},
        },
    ]
