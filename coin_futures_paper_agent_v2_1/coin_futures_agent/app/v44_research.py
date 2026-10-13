"""V4.4 append-only, isolated research state. Never changes paper account tables."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from .storage import _connect

VERSIONS = ("ENTRY_ADAPTIVE", "EXIT_A_TREND", "EXIT_B_RUNNER")

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_research() -> None:
    with _connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS v44_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL,
            cohort_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            method TEXT,
            action TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'v4.4-shadow.1'
        );
        CREATE INDEX IF NOT EXISTS idx_v44_decisions_cohort ON v44_decisions(cohort_id);
        CREATE TABLE IF NOT EXISTS v44_pending (
            signal_id TEXT PRIMARY KEY,
            cohort_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            method TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL,
            entry_zone_json TEXT NOT NULL,
            initial_snapshot_json TEXT NOT NULL,
            cancel_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_v44_pending_active ON v44_pending(status,symbol);
        CREATE TABLE IF NOT EXISTS v44_shadow_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unique_key TEXT UNIQUE NOT NULL,
            cohort_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            variant TEXT NOT NULL,
            side TEXT NOT NULL,
            entered_at TEXT NOT NULL,
            closed_at TEXT,
            entry REAL NOT NULL,
            stop REAL NOT NULL,
            effective_stop REAL NOT NULL,
            target REAL NOT NULL,
            risk REAL NOT NULL,
            high_water REAL NOT NULL,
            remaining REAL NOT NULL DEFAULT 1,
            realized_r REAL NOT NULL DEFAULT 0,
            net_r REAL,
            last_candle_ms INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            reason TEXT,
            state_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_v44_shadow_open ON v44_shadow_positions(status,symbol);
        CREATE TABLE IF NOT EXISTS v44_hypotheses (
            hypothesis_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'TESTING',
            title TEXT NOT NULL,
            rationale TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            evaluation_json TEXT NOT NULL DEFAULT '{}',
            approved_for_paper INTEGER NOT NULL DEFAULT 0
        );
        """)

def log_decision(cohort_id: str, symbol: str, kind: str, action: str,
                 snapshot: dict[str, Any], reason: str, method: str | None = None,
                 *, event_key: str | None = None) -> bool:
    init_research()
    key = event_key or hashlib.sha256(
        f"{cohort_id}|{symbol}|{kind}|{action}|{method}".encode()
    ).hexdigest()
    with _connect() as db:
        cur = db.execute("""INSERT OR IGNORE INTO v44_decisions(
            event_key,cohort_id,symbol,created_at,kind,method,action,snapshot_json,reason)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (key,cohort_id,symbol,utcnow(),kind,method,action,
             json.dumps(snapshot,default=str,ensure_ascii=False),reason))
        return bool(cur.rowcount)

def create_pending(cohort_id: str, symbol: str, side: str, method: str,
                   snapshot: dict, expires_at: str) -> str:
    init_research()
    signal_id = hashlib.sha256(f"{cohort_id}|{symbol}|{method}".encode()).hexdigest()[:24]
    now = utcnow()
    with _connect() as db:
        db.execute("""INSERT OR IGNORE INTO v44_pending(
            signal_id,cohort_id,symbol,side,method,created_at,updated_at,
            expires_at,status,entry_zone_json,initial_snapshot_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (signal_id,cohort_id,symbol,side,method,now,now,expires_at,"PENDING",
             json.dumps({"trigger":snapshot.get("trigger_level"),"atr":snapshot.get("atr")}),
             json.dumps(snapshot,default=str)))
    return signal_id

def update_pending(signal_id: str, status: str, reason: str | None = None) -> bool:
    if status not in ("CONFIRMED","CANCELLED","EXPIRED"):
        raise ValueError("pending status invalid")
    with _connect() as db:
        cur=db.execute("""UPDATE v44_pending SET status=?,updated_at=?,cancel_reason=?
            WHERE signal_id=? AND status='PENDING'""",(status,utcnow(),reason,signal_id))
        return bool(cur.rowcount)

def active_pending(symbol: str | None = None) -> list[dict]:
    init_research()
    with _connect() as db:
        if symbol:
            rows=db.execute("SELECT * FROM v44_pending WHERE status='PENDING' AND symbol=?",(symbol,)).fetchall()
        else:
            rows=db.execute("SELECT * FROM v44_pending WHERE status='PENDING'").fetchall()
    return [dict(r) for r in rows]

def open_shadow(cohort_id: str, symbol: str, variant: str, side: str,
                opened_ms: int, entry: float, stop: float, target: float,
                *, state: dict | None = None) -> bool:
    init_research()
    if variant not in VERSIONS or side not in ("LONG","SHORT") or abs(entry-stop) <= 0:
        raise ValueError("shadow configuration invalid")
    key=f"{cohort_id}|{symbol}|{variant}"
    with _connect() as db:
        cur=db.execute("""INSERT OR IGNORE INTO v44_shadow_positions(
            unique_key,cohort_id,symbol,variant,side,entered_at,
            entry,stop,effective_stop,target,risk,high_water,last_candle_ms,state_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            key,cohort_id,symbol,variant,side,
            datetime.fromtimestamp(opened_ms/1000,timezone.utc).isoformat(),
            entry,stop,stop,target,abs(entry-stop),0.0,opened_ms,
            json.dumps(state or {},default=str)))
        return bool(cur.rowcount)

def open_shadows(symbol: str | None = None) -> list[dict]:
    init_research()
    with _connect() as db:
        if symbol:
            rows=db.execute("SELECT * FROM v44_shadow_positions WHERE status='OPEN' AND symbol=?",(symbol,)).fetchall()
        else:
            rows=db.execute("SELECT * FROM v44_shadow_positions WHERE status='OPEN'").fetchall()
    return [dict(r) for r in rows]

def update_shadow(pos: dict) -> None:
    with _connect() as db:
        db.execute("""UPDATE v44_shadow_positions SET
            closed_at=?, effective_stop=?, high_water=?, remaining=?,realized_r=?,
            net_r=?,last_candle_ms=?,status=?,reason=?,state_json=?
            WHERE id=? AND last_candle_ms<=? AND status='OPEN'""",
            (pos.get("closed_at"),pos["effective_stop"],pos["high_water"],pos["remaining"],
             pos["realized_r"],pos.get("net_r"),pos["last_candle_ms"],pos["status"],pos.get("reason"),
             json.dumps(pos.get("state") or {},default=str),pos["id"],pos["last_candle_ms"]))

def register_hypothesis(title: str, rationale: str, spec: dict) -> str:
    init_research()
    ident=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:20]
    with _connect() as db:
        db.execute("""INSERT OR IGNORE INTO v44_hypotheses(
            hypothesis_id,created_at,title,rationale,spec_json)
            VALUES(?,?,?,?,?)""",(ident,utcnow(),title,rationale,json.dumps(spec,sort_keys=True)))
    return ident

def research_overview(limit: int = 60) -> dict:
    init_research()
    with _connect() as db:
        stats = {}
        for table in ("v44_decisions","v44_pending","v44_shadow_positions","v44_hypotheses"):
            stats[table]=db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        recent=[dict(r) for r in db.execute(
            "SELECT id,cohort_id,symbol,kind,method,action,reason,created_at FROM v44_decisions ORDER BY id DESC LIMIT ?",
            (min(150,max(1,int(limit))),)).fetchall()]
        positions=[dict(r) for r in db.execute(
            "SELECT * FROM v44_shadow_positions ORDER BY id DESC LIMIT 200").fetchall()]
        pending=[dict(r) for r in db.execute(
            "SELECT * FROM v44_pending ORDER BY created_at DESC LIMIT 100").fetchall()]
        hypotheses=[dict(r) for r in db.execute(
            "SELECT * FROM v44_hypotheses ORDER BY created_at DESC LIMIT 100").fetchall()]
    for row in positions:
        row["state"]=json.loads(row.pop("state_json") or "{}")
    for row in pending:
        row["initial_snapshot"]=json.loads(row.pop("initial_snapshot_json") or "{}")
        row["entry_zone"]=json.loads(row.pop("entry_zone_json") or "{}")
    for row in hypotheses:
        row["spec"]=json.loads(row.pop("spec_json") or "{}")
        row["evaluation"]=json.loads(row.pop("evaluation_json") or "{}")
    resolved=[p for p in positions if p["status"]=="CLOSED" and p["net_r"] is not None]
    by_variant={}
    for key in VERSIONS:
        v=[x for x in resolved if x["variant"]==key]
        by_variant[key]={"closed":len(v),"total_net_r":round(sum(x["net_r"] for x in v),4),
                         "expectancy_r":round(sum(x["net_r"] for x in v)/len(v),4) if v else None}
    return {"mode":"SHADOW_ONLY","version":"4.4-shadow.1","counts":stats,
            "recent_decisions":recent,"positions":positions,"pending":pending,
            "hypotheses":hypotheses,"variants":by_variant,
            "disclaimer":"Heuristic shadow research; no calibrated accuracy or live execution"}
