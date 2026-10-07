from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .battle_config import STRATEGIES as LEGACY_STRATEGIES
from .storage import _connect


DEFAULT_CASE_CONFIG = {
    "score_min": 75.0,
    "score_max": 100.0,
    "btc_regimes": ["BULLISH", "BEARISH", "NEUTRAL"],
    "side_filter": "BOTH",
    "min_volume_ratio": 0.85,
    "min_oi_change_pct": None,
    "funding_min": None,
    "funding_max": None,
    "atr_min_pct": None,
    "atr_max_pct": 7.0,
    "max_distance_ema20_atr": None,
    "risk_pct": None,
    "max_open_trades": None,
    "exit_mode": "FIXED_RR",
    "min_acceptable_rr": 0.70,
    "breakeven_trigger_r": None,
    "trail_trigger_r": None,
    "trail_lock_r": 0.25,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_id, spec in LEGACY_STRATEGIES.items():
        row = {
            "strategy_id": strategy_id,
            "name": spec["name"],
            "short_name": spec["short_name"],
            "enabled": True,
            "archived": False,
            "direction_mode": "REVERSE" if spec["reverse"] else "BASE",
            "rr": float(spec["rr"]),
            **DEFAULT_CASE_CONFIG,
        }
        rows.append(row)
    return rows


def init_case_registry() -> None:
    with _connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_cases (
                strategy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,
                direction_mode TEXT NOT NULL,
                rr REAL NOT NULL,
                score_min REAL NOT NULL,
                score_max REAL NOT NULL,
                btc_regimes TEXT NOT NULL,
                side_filter TEXT NOT NULL,
                min_volume_ratio REAL,
                min_oi_change_pct REAL,
                funding_min REAL,
                funding_max REAL,
                atr_min_pct REAL,
                atr_max_pct REAL,
                max_distance_ema20_atr REAL,
                risk_pct REAL,
                max_open_trades INTEGER,
                exit_mode TEXT NOT NULL DEFAULT 'FIXED_RR',
                min_acceptable_rr REAL NOT NULL DEFAULT 0.70,
                breakeven_trigger_r REAL,
                trail_trigger_r REAL,
                trail_lock_r REAL NOT NULL DEFAULT 0.25,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS strategy_case_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                changed_at TEXT NOT NULL,
                action TEXT NOT NULL,
                config_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_case_history
            ON strategy_case_history(strategy_id, version, id);
            """
        )
        for row in _default_rows():
            exists = con.execute(
                "SELECT 1 FROM strategy_cases WHERE strategy_id=?",
                (row["strategy_id"],),
            ).fetchone()
            if exists:
                continue
            now = _now()
            con.execute(
                """
                INSERT INTO strategy_cases(
                    strategy_id,name,short_name,enabled,archived,direction_mode,rr,
                    score_min,score_max,btc_regimes,side_filter,min_volume_ratio,
                    min_oi_change_pct,funding_min,funding_max,atr_min_pct,atr_max_pct,
                    max_distance_ema20_atr,risk_pct,max_open_trades,exit_mode,
                    min_acceptable_rr,breakeven_trigger_r,trail_trigger_r,trail_lock_r,
                    version,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["strategy_id"], row["name"], row["short_name"], 1, 0,
                    row["direction_mode"], row["rr"], row["score_min"], row["score_max"],
                    json.dumps(row["btc_regimes"]), row["side_filter"],
                    row["min_volume_ratio"], row["min_oi_change_pct"], row["funding_min"],
                    row["funding_max"], row["atr_min_pct"], row["atr_max_pct"],
                    row["max_distance_ema20_atr"], row["risk_pct"], row["max_open_trades"],
                    row["exit_mode"], row["min_acceptable_rr"], row["breakeven_trigger_r"],
                    row["trail_trigger_r"], row["trail_lock_r"], 1, now, now,
                ),
            )
            saved = dict(row)
            saved["version"] = 1
            con.execute(
                """
                INSERT INTO strategy_case_history(
                    strategy_id,version,changed_at,action,config_json
                ) VALUES (?,?,?,?,?)
                """,
                (row["strategy_id"], 1, now, "SEEDED", json.dumps(saved)),
            )


def _decode(row: Any) -> dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    d["archived"] = bool(d["archived"])
    try:
        d["btc_regimes"] = json.loads(d.get("btc_regimes") or "[]")
    except Exception:
        d["btc_regimes"] = ["BULLISH", "BEARISH", "NEUTRAL"]
    d["reverse"] = str(d.get("direction_mode")) == "REVERSE"
    d["description"] = (
        f"{d['direction_mode']} RR {float(d['rr']):g}; "
        f"score {float(d['score_min']):g}-{float(d['score_max']):g}"
    )
    return d


def list_strategy_cases(include_archived: bool = False) -> list[dict[str, Any]]:
    init_case_registry()
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


def active_strategy_cases() -> dict[str, dict[str, Any]]:
    return {
        x["strategy_id"]: x
        for x in list_strategy_cases(False)
        if x["enabled"] and not x["archived"]
    }


def get_strategy_case(strategy_id: str) -> dict[str, Any] | None:
    init_case_registry()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM strategy_cases WHERE strategy_id=?",
            (strategy_id,),
        ).fetchone()
    return _decode(row) if row else None


def _next_case_identity() -> tuple[str, str]:
    used = {x["short_name"] for x in list_strategy_cases(True)}
    for code in range(ord("E"), ord("Z") + 1):
        short = chr(code)
        if short not in used:
            return f"CASE_{short}", short
    i = 1
    while True:
        short = f"X{i}"
        if short not in used:
            return f"CUSTOM_{i}", short
        i += 1


def _normalise_payload(payload: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    src = dict(DEFAULT_CASE_CONFIG)
    if base:
        src.update({k: v for k, v in base.items() if k in src})
    src.update({k: v for k, v in payload.items() if k in src})

    direction = str(payload.get("direction_mode") or (base or {}).get("direction_mode") or "BASE").upper()
    if direction not in {"BASE", "REVERSE"}:
        raise ValueError("direction_mode must be BASE or REVERSE")
    side_filter = str(src.get("side_filter") or "BOTH").upper()
    if side_filter not in {"BOTH", "LONG", "SHORT"}:
        raise ValueError("side_filter must be BOTH, LONG or SHORT")
    exit_mode = str(src.get("exit_mode") or "FIXED_RR").upper()
    if exit_mode not in {"FIXED_RR", "STRUCTURE_TARGET", "ADAPTIVE"}:
        raise ValueError("exit_mode must be FIXED_RR, STRUCTURE_TARGET or ADAPTIVE")

    rr = float(payload.get("rr", (base or {}).get("rr", 1.0)))
    score_min = float(src["score_min"])
    score_max = float(src["score_max"])
    if rr <= 0:
        raise ValueError("rr must be > 0")
    if score_min < 0 or score_max > 100 or score_min > score_max:
        raise ValueError("score range must be within 0..100 and min <= max")

    regimes = src.get("btc_regimes") or ["BULLISH", "BEARISH", "NEUTRAL"]
    if isinstance(regimes, str):
        regimes = [x.strip().upper() for x in regimes.split(",") if x.strip()]
    regimes = [str(x).upper() for x in regimes]
    allowed = {"BULLISH", "BEARISH", "NEUTRAL"}
    if not regimes or any(x not in allowed for x in regimes):
        raise ValueError("btc_regimes must contain BULLISH/BEARISH/NEUTRAL")

    def opt_float(key: str) -> float | None:
        v = src.get(key)
        return None if v in (None, "") else float(v)

    def opt_int(key: str) -> int | None:
        v = src.get(key)
        return None if v in (None, "") else max(1, int(v))

    return {
        "direction_mode": direction,
        "rr": rr,
        "score_min": score_min,
        "score_max": score_max,
        "btc_regimes": regimes,
        "side_filter": side_filter,
        "min_volume_ratio": opt_float("min_volume_ratio"),
        "min_oi_change_pct": opt_float("min_oi_change_pct"),
        "funding_min": opt_float("funding_min"),
        "funding_max": opt_float("funding_max"),
        "atr_min_pct": opt_float("atr_min_pct"),
        "atr_max_pct": opt_float("atr_max_pct"),
        "max_distance_ema20_atr": opt_float("max_distance_ema20_atr"),
        "risk_pct": opt_float("risk_pct"),
        "max_open_trades": opt_int("max_open_trades"),
        "exit_mode": exit_mode,
        "min_acceptable_rr": max(0.0, float(src.get("min_acceptable_rr") or 0.0)),
        "breakeven_trigger_r": opt_float("breakeven_trigger_r"),
        "trail_trigger_r": opt_float("trail_trigger_r"),
        "trail_lock_r": max(0.0, float(src.get("trail_lock_r") or 0.0)),
    }


def _history(con: Any, row: dict[str, Any], action: str) -> None:
    con.execute(
        """
        INSERT INTO strategy_case_history(strategy_id,version,changed_at,action,config_json)
        VALUES (?,?,?,?,?)
        """,
        (
            row["strategy_id"],
            int(row["version"]),
            _now(),
            action,
            json.dumps(row),
        ),
    )


def create_strategy_case(payload: dict[str, Any]) -> dict[str, Any]:
    init_case_registry()
    strategy_id, short = _next_case_identity()
    cfg = _normalise_payload(payload)
    now = _now()
    name = str(payload.get("name") or f"CASE {short} - CUSTOM").strip()[:120]
    with _connect() as con:
        con.execute(
            """
            INSERT INTO strategy_cases(
                strategy_id,name,short_name,enabled,archived,direction_mode,rr,
                score_min,score_max,btc_regimes,side_filter,min_volume_ratio,
                min_oi_change_pct,funding_min,funding_max,atr_min_pct,atr_max_pct,
                max_distance_ema20_atr,risk_pct,max_open_trades,exit_mode,
                min_acceptable_rr,breakeven_trigger_r,trail_trigger_r,trail_lock_r,
                version,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                strategy_id, name, short, 1, 0, cfg["direction_mode"], cfg["rr"],
                cfg["score_min"], cfg["score_max"], json.dumps(cfg["btc_regimes"]),
                cfg["side_filter"], cfg["min_volume_ratio"], cfg["min_oi_change_pct"],
                cfg["funding_min"], cfg["funding_max"], cfg["atr_min_pct"],
                cfg["atr_max_pct"], cfg["max_distance_ema20_atr"], cfg["risk_pct"],
                cfg["max_open_trades"], cfg["exit_mode"], cfg["min_acceptable_rr"],
                cfg["breakeven_trigger_r"], cfg["trail_trigger_r"], cfg["trail_lock_r"],
                1, now, now,
            ),
        )
    row = get_strategy_case(strategy_id)
    assert row is not None
    with _connect() as con:
        _history(con, row, "CREATED")
    return row


def update_strategy_case(strategy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_strategy_case(strategy_id)
    if not current:
        raise KeyError(strategy_id)
    cfg = _normalise_payload(payload, current)
    version = int(current["version"]) + 1
    name = str(payload.get("name", current["name"])).strip()[:120]
    enabled = bool(payload.get("enabled", current["enabled"]))
    archived = bool(payload.get("archived", current["archived"]))
    now = _now()
    with _connect() as con:
        con.execute(
            """
            UPDATE strategy_cases SET
                name=?,enabled=?,archived=?,direction_mode=?,rr=?,score_min=?,score_max=?,
                btc_regimes=?,side_filter=?,min_volume_ratio=?,min_oi_change_pct=?,
                funding_min=?,funding_max=?,atr_min_pct=?,atr_max_pct=?,
                max_distance_ema20_atr=?,risk_pct=?,max_open_trades=?,exit_mode=?,
                min_acceptable_rr=?,breakeven_trigger_r=?,trail_trigger_r=?,trail_lock_r=?,
                version=?,updated_at=?
            WHERE strategy_id=?
            """,
            (
                name, int(enabled), int(archived), cfg["direction_mode"], cfg["rr"],
                cfg["score_min"], cfg["score_max"], json.dumps(cfg["btc_regimes"]),
                cfg["side_filter"], cfg["min_volume_ratio"], cfg["min_oi_change_pct"],
                cfg["funding_min"], cfg["funding_max"], cfg["atr_min_pct"],
                cfg["atr_max_pct"], cfg["max_distance_ema20_atr"], cfg["risk_pct"],
                cfg["max_open_trades"], cfg["exit_mode"], cfg["min_acceptable_rr"],
                cfg["breakeven_trigger_r"], cfg["trail_trigger_r"], cfg["trail_lock_r"],
                version, now, strategy_id,
            ),
        )
    row = get_strategy_case(strategy_id)
    assert row is not None
    with _connect() as con:
        _history(con, row, "UPDATED")
    return row


def clone_strategy_case(strategy_id: str, name: str | None = None) -> dict[str, Any]:
    current = get_strategy_case(strategy_id)
    if not current:
        raise KeyError(strategy_id)
    payload = {
        **current,
        "name": name or f"{current['name']} COPY",
    }
    return create_strategy_case(payload)


def strategy_case_history(strategy_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_case_registry()
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
        d = dict(row)
        try:
            d["config"] = json.loads(d.pop("config_json"))
        except Exception:
            d["config"] = {}
        out.append(d)
    return out


def case_passes_signal(spec: dict[str, Any], row: dict[str, Any], btc_regime: str) -> tuple[bool, str]:
    side = str(row.get("bias") or "WAIT")
    score = float(row.get("long_score") if side == "LONG" else row.get("short_score") or 0)
    if side not in {"LONG", "SHORT"}:
        return False, "NO_DIRECTION"
    if score < float(spec["score_min"]) or score > float(spec["score_max"]):
        return False, "SCORE_FILTER"
    if str(btc_regime).upper() not in set(spec.get("btc_regimes") or []):
        return False, "BTC_REGIME_FILTER"
    side_filter = str(spec.get("side_filter") or "BOTH")
    if side_filter != "BOTH" and side != side_filter:
        return False, "SIDE_FILTER"

    checks = [
        ("min_volume_ratio", "volume_ratio_1h", lambda actual, limit: actual >= limit, "VOLUME_FILTER"),
        ("min_oi_change_pct", "oi_change_pct", lambda actual, limit: actual >= limit, "OI_FILTER"),
        ("funding_min", "funding_rate", lambda actual, limit: actual >= limit, "FUNDING_MIN_FILTER"),
        ("funding_max", "funding_rate", lambda actual, limit: actual <= limit, "FUNDING_MAX_FILTER"),
        ("atr_min_pct", "atr_pct_1h", lambda actual, limit: actual >= limit, "ATR_MIN_FILTER"),
        ("atr_max_pct", "atr_pct_1h", lambda actual, limit: actual <= limit, "ATR_MAX_FILTER"),
        ("max_distance_ema20_atr", "distance_ema20_atr", lambda actual, limit: actual <= limit, "EXTENDED_ENTRY_FILTER"),
    ]
    for cfg_key, row_key, fn, reason in checks:
        limit = spec.get(cfg_key)
        if limit is None:
            continue
        actual = row.get(row_key)
        if actual is None or not fn(float(actual), float(limit)):
            return False, reason
    return True, "PASS"
