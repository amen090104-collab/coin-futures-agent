from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .battle_config import STRATEGIES
from .config import settings
from .storage import _connect


DEFAULT_CASES = {
    "BASE_RR2": {
        "name": "CASE A - BASE 1:2",
        "short_name": "A",
        "direction_mode": "BASE",
        "rr": 2.0,
    },
    "BASE_RR1": {
        "name": "CASE B - BASE 1:1",
        "short_name": "B",
        "direction_mode": "BASE",
        "rr": 1.0,
    },
    "REVERSE_RR2": {
        "name": "CASE C - REVERSE 1:2",
        "short_name": "C",
        "direction_mode": "REVERSE",
        "rr": 2.0,
    },
    "REVERSE_RR1": {
        "name": "CASE D - REVERSE 1:1",
        "short_name": "D",
        "direction_mode": "REVERSE",
        "rr": 1.0,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_strategy_cases() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_cases (
                strategy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,
                direction_mode TEXT NOT NULL DEFAULT 'BASE',
                rr REAL NOT NULL DEFAULT 1.0,
                score_min REAL NOT NULL DEFAULT 75.0,
                score_max REAL,
                allowed_regimes TEXT NOT NULL DEFAULT '["BULLISH","BEARISH","NEUTRAL"]',
                side_filter TEXT NOT NULL DEFAULT 'BOTH',
                min_volume_ratio REAL,
                min_oi_change_pct REAL,
                min_atr_pct REAL,
                max_atr_pct REAL,
                risk_pct REAL,
                max_open INTEGER,
                news_policy TEXT NOT NULL DEFAULT 'RESPECT_GUARDIAN',
                entry_mode TEXT NOT NULL DEFAULT 'MARKET_SIGNAL',
                exit_mode TEXT NOT NULL DEFAULT 'FIXED_RR',
                management_mode TEXT NOT NULL DEFAULT 'FIXED',
                version INTEGER NOT NULL DEFAULT 1,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS strategy_case_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                changed_at TEXT NOT NULL,
                action TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_case_history_strategy
            ON strategy_case_history(strategy_id, version);
            """
        )
        now = _now()
        for sid, spec in DEFAULT_CASES.items():
            con.execute(
                """
                INSERT OR IGNORE INTO strategy_cases(
                    strategy_id,name,short_name,enabled,archived,direction_mode,rr,
                    score_min,score_max,allowed_regimes,side_filter,min_volume_ratio,
                    max_atr_pct,risk_pct,max_open,news_policy,entry_mode,exit_mode,
                    management_mode,version,description,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sid,
                    spec["name"],
                    spec["short_name"],
                    1,
                    0,
                    spec["direction_mode"],
                    spec["rr"],
                    settings.score_threshold,
                    None,
                    json.dumps(["BULLISH", "BEARISH", "NEUTRAL"]),
                    "BOTH",
                    settings.min_volume_ratio,
                    settings.max_atr_pct,
                    settings.collection_risk_per_trade_pct
                    if settings.data_collection_mode
                    else settings.risk_per_trade_pct,
                    settings.collection_max_open_trades
                    if settings.data_collection_mode
                    else settings.max_open_trades,
                    "RESPECT_GUARDIAN",
                    "MARKET_SIGNAL",
                    "FIXED_RR",
                    "FIXED",
                    1,
                    STRATEGIES.get(sid, {}).get("description", ""),
                    now,
                    now,
                ),
            )


def _decode(row: Any) -> dict[str, Any]:
    x = dict(row)
    x["enabled"] = bool(x.get("enabled"))
    x["archived"] = bool(x.get("archived"))
    try:
        x["allowed_regimes"] = json.loads(x.get("allowed_regimes") or "[]")
    except Exception:
        x["allowed_regimes"] = ["BULLISH", "BEARISH", "NEUTRAL"]
    return x


def list_strategy_cases(include_archived: bool = False) -> list[dict[str, Any]]:
    init_strategy_cases()
    with _connect() as con:
        if include_archived:
            rows = con.execute(
                "SELECT * FROM strategy_cases ORDER BY created_at,strategy_id"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM strategy_cases WHERE archived=0 ORDER BY created_at,strategy_id"
            ).fetchall()
    return [_decode(r) for r in rows]


def active_strategy_cases() -> list[dict[str, Any]]:
    return [x for x in list_strategy_cases(False) if x["enabled"]]


def get_strategy_case(strategy_id: str) -> dict[str, Any] | None:
    init_strategy_cases()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM strategy_cases WHERE strategy_id=?",
            (strategy_id,),
        ).fetchone()
    return _decode(row) if row else None


def _safe_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", (value or "").strip().upper()).strip("_")
    if not value:
        raise ValueError("strategy_id is required")
    return value[:48]


def _normalize(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    base.update(payload)
    direction = str(base.get("direction_mode") or "BASE").upper()
    if direction not in {"BASE", "REVERSE"}:
        raise ValueError("direction_mode must be BASE or REVERSE")
    side_filter = str(base.get("side_filter") or "BOTH").upper()
    if side_filter not in {"BOTH", "LONG", "SHORT"}:
        raise ValueError("side_filter must be BOTH, LONG or SHORT")
    regimes = base.get("allowed_regimes") or ["BULLISH", "BEARISH", "NEUTRAL"]
    if isinstance(regimes, str):
        regimes = [x.strip().upper() for x in regimes.split(",") if x.strip()]
    regimes = [x for x in regimes if x in {"BULLISH", "BEARISH", "NEUTRAL"}]
    if not regimes:
        raise ValueError("allowed_regimes cannot be empty")
    rr = float(base.get("rr") or 0)
    if rr <= 0 or rr > 10:
        raise ValueError("rr must be >0 and <=10")
    score_min = float(base.get("score_min", settings.score_threshold))
    score_max = base.get("score_max")
    score_max = None if score_max in {"", None} else float(score_max)
    if score_max is not None and score_max < score_min:
        raise ValueError("score_max must be >= score_min")
    return {
        **base,
        "direction_mode": direction,
        "side_filter": side_filter,
        "allowed_regimes": regimes,
        "rr": rr,
        "score_min": score_min,
        "score_max": score_max,
        "enabled": bool(base.get("enabled", True)),
        "archived": bool(base.get("archived", False)),
    }


def _history(con: Any, case: dict[str, Any], action: str) -> None:
    con.execute(
        """
        INSERT INTO strategy_case_history(strategy_id,version,changed_at,action,payload)
        VALUES (?,?,?,?,?)
        """,
        (
            case["strategy_id"],
            int(case["version"]),
            _now(),
            action,
            json.dumps(case, ensure_ascii=False),
        ),
    )


def create_strategy_case(payload: dict[str, Any]) -> dict[str, Any]:
    init_strategy_cases()
    sid = _safe_id(str(payload.get("strategy_id") or payload.get("name") or ""))
    if get_strategy_case(sid):
        raise ValueError(f"strategy case {sid} already exists")
    short = str(payload.get("short_name") or sid[:6]).strip()[:12]
    case = _normalize(
        {
            "strategy_id": sid,
            "name": str(payload.get("name") or sid)[:120],
            "short_name": short,
            "enabled": payload.get("enabled", True),
            "archived": False,
            "direction_mode": payload.get("direction_mode", "BASE"),
            "rr": payload.get("rr", 1.0),
            "score_min": payload.get("score_min", settings.score_threshold),
            "score_max": payload.get("score_max"),
            "allowed_regimes": payload.get("allowed_regimes"),
            "side_filter": payload.get("side_filter", "BOTH"),
            "min_volume_ratio": payload.get("min_volume_ratio", settings.min_volume_ratio),
            "min_oi_change_pct": payload.get("min_oi_change_pct"),
            "min_atr_pct": payload.get("min_atr_pct"),
            "max_atr_pct": payload.get("max_atr_pct", settings.max_atr_pct),
            "risk_pct": payload.get(
                "risk_pct",
                settings.collection_risk_per_trade_pct
                if settings.data_collection_mode
                else settings.risk_per_trade_pct,
            ),
            "max_open": payload.get(
                "max_open",
                settings.collection_max_open_trades
                if settings.data_collection_mode
                else settings.max_open_trades,
            ),
            "news_policy": payload.get("news_policy", "RESPECT_GUARDIAN"),
            "entry_mode": payload.get("entry_mode", "MARKET_SIGNAL"),
            "exit_mode": payload.get("exit_mode", "FIXED_RR"),
            "management_mode": payload.get("management_mode", "FIXED"),
            "version": 1,
            "description": str(payload.get("description") or "")[:500],
        }
    )
    now = _now()
    with _connect() as con:
        con.execute(
            """
            INSERT INTO strategy_cases(
                strategy_id,name,short_name,enabled,archived,direction_mode,rr,
                score_min,score_max,allowed_regimes,side_filter,min_volume_ratio,
                min_oi_change_pct,min_atr_pct,max_atr_pct,risk_pct,max_open,news_policy,
                entry_mode,exit_mode,management_mode,version,description,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sid, case["name"], case["short_name"], int(case["enabled"]), 0,
                case["direction_mode"], case["rr"], case["score_min"], case["score_max"],
                json.dumps(case["allowed_regimes"]), case["side_filter"],
                case.get("min_volume_ratio"), case.get("min_oi_change_pct"),
                case.get("min_atr_pct"), case.get("max_atr_pct"), case.get("risk_pct"),
                case.get("max_open"), case.get("news_policy"), case.get("entry_mode"),
                case.get("exit_mode"), case.get("management_mode"), 1,
                case.get("description", ""), now, now,
            ),
        )
        case["created_at"] = now
        case["updated_at"] = now
        _history(con, case, "CREATE")
        con.execute(
            """
            INSERT INTO battle_account_events(strategy_id,created_at,event_type,amount,note)
            VALUES (?,?,?,?,?)
            """,
            (sid, now, "INITIAL_BALANCE", settings.battle_start_balance, f"{case['name']} starting balance"),
        )
    return get_strategy_case(sid) or case


def update_strategy_case(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_strategy_case(strategy_id)
    if not current:
        raise KeyError(strategy_id)
    updated = _normalize(payload, current)
    version = int(current.get("version") or 1) + 1
    now = _now()
    with _connect() as con:
        con.execute(
            """
            UPDATE strategy_cases SET
                name=?,short_name=?,enabled=?,archived=?,direction_mode=?,rr=?,
                score_min=?,score_max=?,allowed_regimes=?,side_filter=?,min_volume_ratio=?,
                min_oi_change_pct=?,min_atr_pct=?,max_atr_pct=?,risk_pct=?,max_open=?,
                news_policy=?,entry_mode=?,exit_mode=?,management_mode=?,version=?,
                description=?,updated_at=?
            WHERE strategy_id=?
            """,
            (
                str(updated.get("name") or current["name"])[:120],
                str(updated.get("short_name") or current["short_name"])[:12],
                int(updated["enabled"]), int(updated["archived"]),
                updated["direction_mode"], updated["rr"], updated["score_min"],
                updated["score_max"], json.dumps(updated["allowed_regimes"]),
                updated["side_filter"], updated.get("min_volume_ratio"),
                updated.get("min_oi_change_pct"), updated.get("min_atr_pct"),
                updated.get("max_atr_pct"), updated.get("risk_pct"), updated.get("max_open"),
                updated.get("news_policy", "RESPECT_GUARDIAN"),
                updated.get("entry_mode", "MARKET_SIGNAL"),
                updated.get("exit_mode", "FIXED_RR"),
                updated.get("management_mode", "FIXED"),
                version, str(updated.get("description") or "")[:500], now, strategy_id,
            ),
        )
        snap = {**updated, "strategy_id": strategy_id, "version": version, "updated_at": now}
        _history(con, snap, "UPDATE")
    return get_strategy_case(strategy_id) or snap


def clone_strategy_case(strategy_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    src = get_strategy_case(strategy_id)
    if not src:
        raise KeyError(strategy_id)
    payload = dict(payload or {})
    new_id = payload.pop("strategy_id", f"{strategy_id}_CLONE")
    data = {
        **src,
        **payload,
        "strategy_id": new_id,
        "name": payload.get("name", f"{src['name']} Clone"),
        "short_name": payload.get("short_name", f"{src['short_name']}2"),
        "enabled": payload.get("enabled", False),
    }
    for k in ("created_at", "updated_at", "version", "archived"):
        data.pop(k, None)
    return create_strategy_case(data)


def strategy_case_history(strategy_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_strategy_cases()
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM strategy_case_history
            WHERE strategy_id=? ORDER BY id DESC LIMIT ?
            """,
            (strategy_id, min(max(int(limit), 1), 500)),
        ).fetchall()
    out = []
    for row in rows:
        x = dict(row)
        try:
            x["payload"] = json.loads(x.get("payload") or "{}")
        except Exception:
            x["payload"] = {}
        out.append(x)
    return out


def case_accepts_signal(case: dict[str, Any], row: dict[str, Any], source_side: str, btc_regime: str) -> tuple[bool, str]:
    score = float(row.get("long_score") if source_side == "LONG" else row.get("short_score") or 0)
    if score < float(case.get("score_min") or 0):
        return False, "score_below_min"
    score_max = case.get("score_max")
    if score_max is not None and score > float(score_max):
        return False, "score_above_max"
    if btc_regime not in (case.get("allowed_regimes") or []):
        return False, "btc_regime_filtered"
    if case.get("side_filter") not in {"BOTH", source_side}:
        return False, "side_filtered"
    vol = case.get("min_volume_ratio")
    if vol is not None and float(row.get("volume_ratio_1h") or 0) < float(vol):
        return False, "volume_filtered"
    oi = case.get("min_oi_change_pct")
    if oi is not None and float(row.get("oi_change_pct") or 0) < float(oi):
        return False, "oi_filtered"
    atr = float(row.get("atr_pct_1h") or 0)
    if case.get("min_atr_pct") is not None and atr < float(case["min_atr_pct"]):
        return False, "atr_below_min"
    if case.get("max_atr_pct") is not None and atr > float(case["max_atr_pct"]):
        return False, "atr_above_max"
    return True, "accepted"
