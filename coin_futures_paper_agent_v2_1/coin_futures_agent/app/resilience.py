from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .binance import BinanceClient
from .battle import recover_battle_open_positions
from .config import settings
from .paper import recover_open_positions
from .storage import (
    backup_database,
    get_system_state,
    log_system_event,
    reconcile_trade_pnl_events,
    set_system_state,
    system_state_snapshot,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def recover_active_positions() -> dict[str, Any]:
    if settings.strategy_battle_enabled:
        return await recover_battle_open_positions()
    return await recover_active_positions()


async def probe_futures_connectivity() -> tuple[bool, str | None]:
    client = BinanceClient()
    try:
        await client.ping()
        return True, None
    except Exception as exc:
        return False, str(exc)[:500]
    finally:
        await client.close()


async def backup_now(reason: str = "manual") -> dict[str, Any]:
    created_at = _now()
    try:
        path = await asyncio.to_thread(
            backup_database,
            settings.backup_dir,
            settings.backup_retention,
        )
        payload = {"ok": True, "path": path, "reason": reason, "created_at": created_at}
        set_system_state("last_backup", payload, created_at)
        log_system_event("BACKUP_OK", f"Database backup created: {path}", payload=payload, created_at=created_at)
        return payload
    except Exception as exc:
        payload = {"ok": False, "reason": reason, "error": str(exc)[:500], "created_at": created_at}
        set_system_state("last_backup", payload, created_at)
        log_system_event(
            "BACKUP_FAILED",
            f"Database backup failed: {payload['error']}",
            severity="ERROR",
            payload=payload,
            created_at=created_at,
        )
        return payload


async def startup_recovery() -> dict[str, Any]:
    started_at = _now()
    repaired = reconcile_trade_pnl_events()
    if repaired:
        log_system_event(
            "ACCOUNT_RECONCILED",
            f"Repaired {repaired} missing paper PnL event(s) from legacy non-atomic closes.",
            severity="WARNING",
            payload={"repaired": repaired},
            created_at=started_at,
        )

    backup = await backup_now("startup")
    online, error = await probe_futures_connectivity()
    if not online:
        set_system_state(
            "network",
            {"status": "OFFLINE", "last_error": error, "since": started_at},
            started_at,
        )
        log_system_event(
            "NETWORK_OFFLINE",
            f"Startup without Binance connectivity: {error}",
            severity="WARNING",
            created_at=started_at,
        )
        recovery = {
            "status": "DEFERRED_OFFLINE",
            "created_at": started_at,
            "positions_checked": 0,
            "positions_closed": 0,
            "candles_replayed": 0,
            "errors": [{"error": error}],
        }
    else:
        set_system_state(
            "network",
            {"status": "ONLINE", "last_error": None, "since": started_at},
            started_at,
        )
        recovery = await recover_active_positions()
        recovery["status"] = "COMPLETED"
        recovery["created_at"] = _now()
        log_system_event(
            "STARTUP_RECOVERY",
            (
                f"Recovery replayed {recovery.get('candles_replayed', 0)} candle(s); "
                f"closed {recovery.get('positions_closed', 0)} position(s)."
            ),
            severity="WARNING" if recovery.get("errors") else "INFO",
            payload=recovery,
        )

    set_system_state("last_recovery", recovery)
    set_system_state("last_startup", {"created_at": started_at})
    return {
        "started_at": started_at,
        "reconciled_account_events": repaired,
        "backup": backup,
        "network_online": online,
        "recovery": recovery,
    }


async def health_check_and_recover() -> dict[str, Any]:
    checked_at = _now()
    previous = get_system_state("network", {}) or {}
    previous_status = previous.get("status", "UNKNOWN") if isinstance(previous, dict) else "UNKNOWN"
    online, error = await probe_futures_connectivity()

    if not online:
        since = previous.get("since") if previous_status == "OFFLINE" and isinstance(previous, dict) else checked_at
        state = {"status": "OFFLINE", "last_error": error, "since": since, "checked_at": checked_at}
        set_system_state("network", state, checked_at)
        if previous_status != "OFFLINE":
            log_system_event(
                "NETWORK_OFFLINE",
                f"Binance connectivity lost: {error}",
                severity="WARNING",
                payload=state,
                created_at=checked_at,
            )
        return {"online": False, "recovered": False, "error": error}

    if previous_status == "OFFLINE":
        recovering = {
            "status": "RECOVERING",
            "last_error": None,
            "since": checked_at,
            "checked_at": checked_at,
        }
        set_system_state("network", recovering, checked_at)
        log_system_event(
            "NETWORK_RESTORED",
            "Binance connectivity restored. Replaying missed candles before resuming entries.",
            payload={"restored_at": checked_at},
            created_at=checked_at,
        )
        recovery = await recover_active_positions()
        recovery["status"] = "COMPLETED_AFTER_RECONNECT"
        recovery["created_at"] = _now()
        set_system_state("last_recovery", recovery)
        online_state = {
            "status": "ONLINE",
            "last_error": None,
            "since": recovery["created_at"],
            "checked_at": recovery["created_at"],
        }
        set_system_state("network", online_state, recovery["created_at"])
        log_system_event(
            "RECONNECT_RECOVERY",
            (
                f"Reconnect recovery replayed {recovery.get('candles_replayed', 0)} candle(s); "
                f"closed {recovery.get('positions_closed', 0)} position(s)."
            ),
            severity="WARNING" if recovery.get("errors") else "INFO",
            payload=recovery,
        )
        return {"online": True, "recovered": True, "recovery": recovery}

    state = {"status": "ONLINE", "last_error": None, "since": checked_at, "checked_at": checked_at}
    set_system_state("network", state, checked_at)
    return {"online": True, "recovered": False}


def system_overview() -> dict[str, Any]:
    snapshot = system_state_snapshot()
    def value(key: str, default: Any = None) -> Any:
        item = snapshot.get(key)
        return item.get("value") if isinstance(item, dict) else default

    return {
        "network": value("network", {"status": "UNKNOWN"}),
        "last_backup": value("last_backup"),
        "last_recovery": value("last_recovery"),
        "last_startup": value("last_startup"),
        "jobs": {
            "scan": value("job_scan"),
            "monitor": value("job_monitor"),
            "news": value("job_news"),
            "spot": value("job_spot"),
            "health": value("job_health"),
            "backup": value("job_backup"),
            "report": value("job_report"),
            "news_review": value("job_news_review"),
        },
        "scheduler": value("scheduler", {"status": "UNKNOWN", "missed_jobs": 0}),
    }
