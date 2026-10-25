from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import os
from time import perf_counter
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from .v44_research import init_research, research_overview
from .v44_learning import research_snapshot
from .v44_shadow import scan_shadow, monitor_shadow
from .reverse_research import init_reverse_lab, reverse_lab_overview
from .reverse_runner import reverse_scan_job, monitor_reverse_lab, reverse_lab_active
from .reverse_intelligence_store import (enabled as rei_enabled, init_intelligence,
    collect as collect_reverse_entry, monitor as monitor_reverse_entry, overview as reverse_entry_overview)
from . import rei_v3
from .version import VERSION, version_info
from .analytics import build_dashboard_analytics
from .battle import close_battle_for_news, monitor_battle_positions, open_battle_candidates
from .battle_analytics import build_strategy_battle_dashboard
from .battle_reports import generate_battle_and_save, render_battle_html, render_battle_markdown
from .battle_storage import (
    battle_account_balance,
    battle_open_positions,
    battle_recent_trades,
    ensure_battle_initial_balances,
    init_battle_db,
)
from .json_safe import json_safe
from .config import settings
from .dashboard_v4 import DASHBOARD_HTML_V4
from .dashboard_v43 import DASHBOARD_HTML_V43
from .dashboard_lean import DASHBOARD_HTML_LEAN
from .news import fetch_and_store_news, market_news_summary
from .news_guardian import (
    evaluate_news_guardian,
    news_guardian_overview,
    review_news_guardian_events,
)
from .paper import monitor_positions, open_candidates, recover_open_positions
from .resilience import backup_now, health_check_and_recover, recover_active_positions, startup_recovery, system_overview
from .spot_research import run_spot_research
from .strategy_cases import (
    init_strategy_cases,
    LEAN_CASE_IDS,
    list_strategy_cases,
    create_strategy_case,
    update_strategy_case,
    clone_strategy_case,
    strategy_case_history,
)
from .trade_intelligence import trade_detail
from .exit_simulator import simulate_trade_exit
from .analysis_daily import render_telegram_analysis
from .decision_journal import init_decision_journal
from .strategy_evaluation import strategy_evaluation_overview
from .coin_intelligence import coin_detail
from .reports import generate_and_save, render_markdown
from .reports import render_html as render_legacy_html
from .report_files import (HistoricalReportError, bundle_status, read_snapshot,
                           require_recent_day, validate_day)
from .reporting import prepare_daily_bundle
from .local_trade_archive import archive_recent_days, export_local_trade_history
from .report_sync import sync_report_files, sync_status, report_root, local_report_status
from .scanner import run_scan
from .storage import (
    account_balance,
    ensure_initial_balance,
    get_daily_report,
    get_system_state,
    init_db,
    latest_daily_reports,
    latest_scan,
    latest_spot_research,
    list_recommendations,
    open_positions,
    recent_system_events,
    recent_news,
    recent_trades,
    save_scan,
    set_system_state,
)
from .telegram import (
    render_close_alert,
    render_daily_report,
    render_news_guardian_alert,
    render_scan_alert,
    send_telegram,
)

scheduler = AsyncIOScheduler(timezone=settings.timezone)
scan_lock = asyncio.Lock()
v44_scan_lock = asyncio.Lock()
v44_monitor_lock = asyncio.Lock()
reverse_monitor_lock = asyncio.Lock()
reverse_entry_lock = asyncio.Lock()
reverse_entry_v3_lock = asyncio.Lock()


async def collect_entry_research(result, frames, opened):
    if settings.runtime_profile == "lean":
        return {"status": "MOVED_TO_STANDALONE_RESEARCH"}
    await collect_reverse_entry(result, frames, opened)
    async with reverse_entry_v3_lock:
        await rei_v3.collect()


async def reverse_entry_v3_job():
    if settings.runtime_profile == "lean":
        return {"status": "MOVED_TO_STANDALONE_RESEARCH"}
    if reverse_entry_v3_lock.locked():
        return {"status": "ALREADY_RUNNING"}
    async with reverse_entry_v3_lock:
        return await rei_v3.cycle()


monitor_lock = asyncio.Lock()
news_lock = asyncio.Lock()
spot_lock = asyncio.Lock()
health_lock = asyncio.Lock()
backup_lock = asyncio.Lock()
analysis_lock = asyncio.Lock()
log = logging.getLogger(__name__)


def legacy_research_jobs_enabled() -> bool:
    """Lean keeps Paper, Reverse Lab and V2/V3, skips V4.4/Spot workers."""
    return settings.runtime_profile == 'full'


def _mark_job(name: str, status: str = "OK", **extra) -> None:
    payload = {
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    set_system_state(f"job_{name}", payload)


def _scheduler_listener(event) -> None:
    state = get_system_state("scheduler", {}) or {}
    missed = int(state.get("missed_jobs") or 0) if isinstance(state, dict) else 0
    if event.code == EVENT_JOB_MISSED:
        missed += 1
    set_system_state(
        "scheduler",
        {
            "status": "HEALTHY" if event.code != EVENT_JOB_MISSED else "WARNING",
            "missed_jobs": missed,
            "last_event_at": datetime.now(timezone.utc).isoformat(),
            "last_missed_job": getattr(event, "job_id", None) if event.code == EVENT_JOB_MISSED else state.get("last_missed_job") if isinstance(state, dict) else None,
        },
    )


scheduler.add_listener(_scheduler_listener, EVENT_JOB_MISSED)


scan_state = {
    "running": False,
    "started_at": None,
    "completed_at": None,
    "duration_sec": None,
    "symbols_scanned": 0,
    "last_error": None,
}


async def scan_job() -> dict:
    if scan_lock.locked():
        return {"status": "scan already running", "scan_state": dict(scan_state)}
    network = system_overview().get("network") or {}
    if network.get("status") in {"OFFLINE", "RECOVERING"}:
        return {"status": "skipped while offline", "scan_state": dict(scan_state)}
    async with scan_lock:
        started = datetime.now(timezone.utc)
        t0 = perf_counter()
        scan_state.update(
            running=True,
            started_at=started.isoformat(),
            last_error=None,
        )
        try:
            result, frames = await run_scan()
            save_scan(result["created_at"], result)
            if settings.strategy_battle_enabled:
                opened = await open_battle_candidates(result, frames)
            elif settings.runtime_profile == 'lean':
                # Lean is six-case-only; never fall back to legacy single Paper.
                opened = []
            else:
                opened = await open_candidates(result, frames)
            if settings.runtime_profile == "full" and rei_enabled():
                asyncio.create_task(collect_entry_research(result, frames, opened))
            try:
                await send_telegram(render_scan_alert(result, opened))
            except Exception:
                # Notification failure is not a failed scan/Paper trade.
                log.exception("Scan Telegram delivery failed; Paper and Reverse continue")
            if settings.v44_shadow_enabled and legacy_research_jobs_enabled():
                # Old generic V4.4 is optional and never blocks Paper.
                asyncio.create_task(v44_scan_job(result, frames, opened))
            if settings.runtime_profile == "full" and reverse_lab_active():
                # Legacy compatibility only. Lean Paper has no Reverse worker.
                asyncio.create_task(reverse_scan_job(result, opened))
            scan_state.update(
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbols_scanned=int(result.get("symbols_scanned") or 0),
            )
            _mark_job("scan", symbols_scanned=int(result.get("symbols_scanned") or 0), opened=len(opened))
            return {"scan": result, "opened": opened}
        except Exception as exc:
            scan_state.update(
                completed_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(exc)[:500],
            )
            _mark_job("scan", "ERROR", error=str(exc)[:500])
            raise
        finally:
            scan_state["running"] = False
            scan_state["duration_sec"] = round(perf_counter() - t0, 2)


async def monitor_job() -> list[dict]:
    if monitor_lock.locked():
        return []
    network = system_overview().get("network") or {}
    if network.get("status") in {"OFFLINE", "RECOVERING"}:
        return []
    async with monitor_lock:
        events = (
            await monitor_battle_positions()
            if settings.strategy_battle_enabled
            else await monitor_positions()
        )
        if events:
            try:
                await send_telegram(render_close_alert(events))
            except Exception:
                log.exception("Monitor Telegram delivery failed; closed Paper positions preserved")
        _mark_job("monitor", closed=len(events))
        return events


async def v44_scan_job(scan: dict, frames: dict, opened: list | None = None) -> dict:
    if v44_scan_lock.locked():
        return {"status": "SKIPPED", "reason": "research scan already running"}
    async with v44_scan_lock:
        try:
            return await scan_shadow(scan, frames, opened)
        except Exception:
            log.exception("V4.4 shadow scan failed; paper path unaffected")
            return {"status": "ERROR", "reason": "shadow scan failed"}


async def v44_monitor_job() -> dict:
    if v44_monitor_lock.locked():
        return {"status": "SKIPPED", "reason": "research monitor already running"}
    async with v44_monitor_lock:
        try:
            return await monitor_shadow()
        except Exception:
            log.exception("V4.4 monitor failed; paper path is unaffected")
            return {"status": "ERROR", "reason": "shadow monitor failed"}


async def reverse_lab_monitor_job() -> dict:
    if reverse_monitor_lock.locked():
        return {"status":"SKIPPED","reason":"Reverse Lab monitor already running"}
    async with reverse_monitor_lock:
        try:
            result=await monitor_reverse_lab()
            _mark_job("reverse_lab", status="OK" if result.get("status")=="SHADOW_ONLY" else "SKIPPED",
                      closed=result.get("closed",0), open_cases=result.get("open_cases",0))
            return result
        except Exception:
            log.exception("Reverse Lab monitoring failed; paper trade handling unaffected")
            _mark_job("reverse_lab","ERROR")
            return {"status":"ERROR","reason":"Reverse Lab monitoring failed"}


async def reverse_entry_monitor_job() -> dict:
    if reverse_entry_lock.locked():
        return {"status": "ALREADY_RUNNING"}
    async with reverse_entry_lock:
        return await monitor_reverse_entry()


async def news_job() -> dict:
    if news_lock.locked():
        return {"status": "news refresh already running"}
    async with news_lock:
        scan = latest_scan() or {}
        universe = {
            str(x.get("symbol", ""))[:-4]
            for x in scan.get("all", [])
            if str(x.get("symbol", "")).endswith("USDT")
        }
        result = await fetch_and_store_news(universe or None)
        guardian = await evaluate_news_guardian()
        closed: list[dict] = []

        if (
            settings.strategy_battle_enabled
            and guardian.get("mode") == "EVENT_LOCK"
            and guardian.get("is_new_event")
        ):
            async with monitor_lock:
                closed = await close_battle_for_news(guardian)
            if closed:
                await send_telegram(render_close_alert(closed))

        if guardian.get("is_new_event") and guardian.get("mode") != "NORMAL":
            await send_telegram(render_news_guardian_alert(guardian, closed))

        _mark_job(
            "news",
            received=int(result.get("received") or 0),
            guardian_mode=guardian.get("mode"),
            news_risk_exits=len(closed),
        )
        return {**result, "guardian": guardian, "news_risk_exits": closed}


async def news_review_job() -> dict:
    try:
        result = await review_news_guardian_events()
        _mark_job("news_review", updated=int(result.get("updated_events") or 0))
        return result
    except Exception as exc:
        _mark_job("news_review", "ERROR", error=str(exc)[:500])
        raise


async def spot_research_job() -> dict:
    if not settings.spot_research_enabled or not legacy_research_jobs_enabled():
        return {"status": "spot research disabled by settings or lean profile"}
    if spot_lock.locked():
        return {"status": "spot research already running"}
    network = system_overview().get("network") or {}
    if network.get("status") in {"OFFLINE", "RECOVERING"}:
        return {"status": "skipped while offline"}
    async with spot_lock:
        result = await run_spot_research()
        _mark_job("spot", researched=int(result.get("symbols_researched") or 0))
        return result


async def health_job() -> dict:
    if health_lock.locked():
        return {"status": "health check already running"}
    async with health_lock:
        async with monitor_lock:
            result = await health_check_and_recover()
        if result.get("recovered"):
            closed = (result.get("recovery") or {}).get("closed") or []
            if closed:
                await send_telegram(render_close_alert(closed))
        _mark_job("health", online=bool(result.get("online")))
        return result


async def backup_job() -> dict:
    if backup_lock.locked():
        return {"status": "backup already running"}
    async with backup_lock:
        result = await backup_now("scheduled")
        _mark_job("backup", ok=bool(result.get("ok")))
        return result


async def save_daily_trade_history(day: str) -> dict:
    """Local CSV/JSON trade snapshots; no network and no GitHub uploads."""
    try:
        result = await asyncio.to_thread(export_local_trade_history, day)
        _mark_job("local_history", "OK", report_date=day, trade_count=result["trades"],
                  archive_status=result["status"], github_uploaded=False)
        return result
    except Exception as exc:
        _mark_job("local_history", "ERROR", report_date=day, error=str(exc)[:220])
        raise


async def local_trade_history_finalize_job() -> dict:
    """00:15 local: finalize yesterday after the daily analysis job."""
    day = (datetime.now(ZoneInfo(settings.timezone)) - timedelta(days=1)).strftime("%Y-%m-%d")
    return await save_daily_trade_history(day)


async def daily_report_job() -> dict:
    tz = ZoneInfo(settings.timezone)
    day = datetime.now(tz).strftime("%Y-%m-%d")
    report = (
        generate_battle_and_save(day)
        if settings.strategy_battle_enabled
        else generate_and_save(day)
    )
    # A daily report is saved locally; lean also keeps a compact trade ledger.
    local_history = await save_daily_trade_history(day) if settings.runtime_profile == "lean" else None
    # The uploader returns LOCAL_ONLY_NO_GITHUB before any network access in lean.
    sync = await sync_report_files(day, report)
    try:
        await send_telegram(render_daily_report(report))
    except Exception:
        log.exception("Daily report Telegram delivery failed")
    _mark_job("report", report_date=day, github_sync_ok=bool(sync.get("ok")),
              github_sync_reason=sync.get("reason"), local_history=local_history)
    return {**report, "github_sync": sync, "local_history": local_history}


async def daily_analysis_job(day: str | None = None, *, refresh: bool = True) -> dict:
    """At 00:10 local time analyze yesterday's *complete* 00:00-24:00 session."""
    if analysis_lock.locked():
        return {"status": "ALREADY_RUNNING"}
    async with analysis_lock:
        tz = ZoneInfo(settings.timezone)
        yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
        day = day or yesterday
        try:
            # Only the scheduled finalization refreshes yesterday's daily data.
            # Repair/restart preserves existing snapshots and their timestamps.
            prepared = prepare_daily_bundle(day, refresh=refresh and day == yesterday)
            analysis = prepared["analysis"]
            # Rerun after midnight to include late closes from 23:58–24:00.
            local_history = await save_daily_trade_history(day) if settings.runtime_profile == "lean" else None
            sync = await sync_report_files(day)
            _mark_job("daily_analysis", prepared["status"], report_date=day,
                      artifacts=prepared["artifacts"], errors=prepared["errors"],
                      github_sync_ok=bool(sync.get("ok")),
                      github_sync_reason=sync.get("reason"))
            if day == yesterday and analysis is not None:
                try:
                    await send_telegram(render_telegram_analysis(analysis))
                except Exception:
                    log.exception("Daily analysis Telegram delivery failed")
            return {**prepared, "github_sync": sync, "local_history": local_history}
        except Exception as exc:
            _mark_job("daily_analysis", "ERROR", report_date=day,
                      error=str(exc)[:500])
            log.exception("Daily analysis generation failed")
            raise


async def report_sync_retry_job() -> dict:
    tz = ZoneInfo(settings.timezone)
    # The 23:58 report belongs to the previous local day when this retry runs at 00:05.
    day = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    result = await sync_report_files(day)
    _mark_job(
        "report_sync",
        "OK" if result.get("ok") else "WARNING",
        report_date=day,
        reason=result.get("reason"),
    )
    return result


async def missed_report_recovery_job() -> dict:
    """Recover yesterday only; never synthesize older point-in-time snapshots."""
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    if now.hour == 0 and now.minute < 10:
        return {"status": "WAITING_FOR_0010"}
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    before = bundle_status(yesterday)
    if before["complete"]:
        return {"status": "ALREADY_PRESENT", "report_date": yesterday, "artifacts": before}
    if analysis_lock.locked():
        return {"status": "ALREADY_RUNNING"}
    try:
        result = await daily_analysis_job(yesterday, refresh=False)
        after = bundle_status(yesterday)
        complete = result.get("status") == "OK" and after["complete"]
        status = "RECOVERED" if complete else result.get("status", "PARTIAL")
        if status == "OK":
            status = "PARTIAL"
        _mark_job("missed_report_recovery", "OK" if complete else "WARNING",
                  report_date=yesterday, artifacts=after)
        return {"status": status, "report_date": yesterday, "artifacts": after, "result": result}
    except Exception as exc:
        _mark_job("missed_report_recovery", "ERROR", report_date=yesterday, error=str(exc)[:500])
        return {"status": "ERROR", "report_date": yesterday, "reason": str(exc)[:500]}


async def analysis_sync_retry_job() -> dict:
    yesterday = (datetime.now(ZoneInfo(settings.timezone)) - timedelta(days=1)).strftime("%Y-%m-%d")
    if not bundle_status(yesterday)["complete"]:
        repaired = await missed_report_recovery_job()
        if repaired["status"] != "RECOVERED":
            return repaired
    last = get_system_state("report_github_sync", {}) or {}
    uploaded = [x.get("path", "") for x in last.get("uploaded", [])]
    latest_name = "latest-analysis.json" if settings.strategy_battle_enabled else "latest.json"
    if (last.get("ok") and last.get("report_date") == yesterday
            and any(x.endswith("/" + latest_name) for x in uploaded)):
        return {"status": "ALREADY_SYNCED", "report_date": yesterday}
    result = await sync_report_files(yesterday)
    _mark_job("analysis_sync_retry", "OK" if result.get("ok") else "WARNING",
              report_date=yesterday, github_sync_ok=bool(result.get("ok")),
              reason=result.get("reason"))
    return result


async def _bootstrap() -> None:
    # Startup recovery is completed before this background bootstrap is scheduled.
    if settings.runtime_profile == "lean":
        try:
            catchup = await asyncio.to_thread(archive_recent_days, days=7)
            _mark_job("local_history", "OK", catchup_days=catchup["days"],
                      exported_trades=catchup["trades"], github_uploaded=False)
        except Exception as exc:
            _mark_job("local_history", "ERROR", error=str(exc)[:220])
            log.exception("Local trade-history catch-up failed")
    # A laptop/desktop may be off at 00:10. Catch up once after local 00:10
    # whenever yesterday's required report bundle is incomplete.
    try:
        await missed_report_recovery_job()
    except Exception:
        log.exception("Startup daily analysis catch-up failed")
    try:
        await news_job()
    except Exception:
        pass
    try:
        await scan_job()
    except Exception:
        pass
    if settings.spot_research_enabled and legacy_research_jobs_enabled():
        try:
            await spot_research_job()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get('AGENT_HEALTH_PROBE_ONLY') == '1':
        yield
        return
    init_db()
    if settings.runtime_profile == "full":
        init_research()  # Legacy compatibility: local historical DB is preserved.
        init_reverse_lab()
    if settings.runtime_profile == "full" and rei_enabled():
        init_intelligence()
    if settings.runtime_profile == "full" and rei_v3.enabled():
        from .storage import _connect
        with _connect() as db:
            rei_v3.init(db)
    if settings.strategy_battle_enabled:
        init_battle_db()
        init_strategy_cases()
        init_decision_journal()
        ensure_battle_initial_balances(
            datetime.utcnow().isoformat() + "Z",
            settings.battle_start_balance,
        )
    else:
        ensure_initial_balance(
            datetime.utcnow().isoformat() + "Z",
            settings.paper_start_balance,
        )
    await startup_recovery()

    common = {
        "replace_existing": True,
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 30,
    }
    scheduler.add_job(scan_job, "interval", minutes=settings.scan_interval_min, id="market_scan", **common)
    if settings.runtime_profile == "full" and rei_v3.enabled():
        scheduler.add_job(reverse_entry_v3_job, "interval", minutes=5, id="reverse_entry_v3_research", **common)
    if settings.runtime_profile == "full" and rei_enabled():
        scheduler.add_job(reverse_entry_monitor_job, "interval",
                          minutes=max(1, settings.v44_shadow_monitor_interval_min),
                          id="reverse_entry_v2_monitor", **common)
    scheduler.add_job(monitor_job, "interval", seconds=settings.monitor_interval_sec, id="paper_monitor", **common)
    if settings.v44_shadow_enabled and legacy_research_jobs_enabled():
        scheduler.add_job(v44_monitor_job, "interval", minutes=max(1,settings.v44_shadow_monitor_interval_min), id="v44_shadow_monitor", **common)
    if settings.runtime_profile == "full" and reverse_lab_active():
        scheduler.add_job(reverse_lab_monitor_job, "interval",
                          minutes=max(1,settings.v44_shadow_monitor_interval_min),
                          id="reverse_lab_monitor", **common)
    scheduler.add_job(news_job, "interval", minutes=settings.news_refresh_min, id="news_research", **common)
    scheduler.add_job(
        news_review_job,
        "interval",
        minutes=settings.news_guardian_review_interval_min,
        id="news_guardian_review",
        **common,
    )
    scheduler.add_job(health_job, "interval", seconds=settings.health_check_interval_sec, id="system_health", **common)
    scheduler.add_job(backup_job, "interval", hours=settings.backup_interval_hours, id="database_backup", **common)
    if settings.spot_research_enabled and legacy_research_jobs_enabled():
        scheduler.add_job(
            spot_research_job,
            "interval",
            minutes=settings.spot_research_interval_min,
            id="spot_research",
            **common,
        )
    scheduler.add_job(
        daily_report_job,
        "cron",
        hour=settings.daily_report_hour,
        minute=settings.daily_report_minute,
        id="daily_report",
        **common,
    )
    # No GitHub retry workers when archives are local-only.
    # Keep the upload schedule exclusively for explicitly opted-in FULL mode.
    if sync_status()["enabled"]:
        scheduler.add_job(
            report_sync_retry_job, "cron", hour=0, minute=5,
            id="daily_report_github_sync_retry", **common,
        )
    scheduler.add_job(
        daily_analysis_job,
        "cron",
        hour=0,
        minute=10,
        id="daily_analysis_0010",
        **common,
    )
    if sync_status()["enabled"]:
        scheduler.add_job(
            analysis_sync_retry_job, "cron", hour=0, minute=20,
            id="daily_analysis_sync_retry", **common,
        )
        scheduler.add_job(
            analysis_sync_retry_job, "cron", minute=30,
            id="daily_analysis_hourly_sync_retry", **common,
        )
    if settings.runtime_profile == "lean":
        scheduler.add_job(
            local_trade_history_finalize_job, "cron", hour=0, minute=15,
            id="daily_trade_history_local_finalize", **common,
        )
    scheduler.add_job(missed_report_recovery_job, "cron", minute=35,
                      id="missed_report_recovery_hourly", **common)
    scheduler.start()
    set_system_state(
        "scheduler",
        {
            "status": "HEALTHY",
            "missed_jobs": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    asyncio.create_task(_bootstrap())
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await backup_now("shutdown")


class SafeJSONResponse(JSONResponse):
    def render(self, content):
        return super().render(json_safe(content))


app = FastAPI(
    title="Trading Bot V5.1",
    version=VERSION,
    lifespan=lifespan,
    default_response_class=SafeJSONResponse,
)


@app.middleware('http')
async def maintenance_probe_routes(request, call_next):
    if os.environ.get('AGENT_HEALTH_PROBE_ONLY') == '1' and request.url.path not in {'/local/health','/version'}:
        return JSONResponse({'detail':'MAINTENANCE_HEALTH_ONLY_NO_JOBS'},status_code=503)
    return await call_next(request)


@app.get('/version')
async def executing_version():
    return version_info()


@app.get("/assets/trade_charts.js", include_in_schema=False)
async def trade_chart_script():
    if settings.runtime_profile == 'lean':
        raise HTTPException(410, 'CANDLE_CHARTS_RETIRED_IN_LEAN_MODE')
    return Response(
        content=Path(__file__).with_name("trade_charts.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": VERSION,
        "build": version_info(),
        "paper_balance": (
            battle_account_balance("BASE_RR2")
            if settings.strategy_battle_enabled
            else account_balance()
        ),
        "open_positions": (
            len(battle_open_positions())
            if settings.strategy_battle_enabled
            else len(open_positions())
        ),
        "strategy_battle_enabled": settings.strategy_battle_enabled,
        "runtime_profile": settings.runtime_profile,
        "data_collection_mode_effective": bool(settings.data_collection_mode and legacy_research_jobs_enabled()),
        "top_n_coins": settings.top_n_coins,
        "news_refresh_min": settings.news_refresh_min,
        "system": system_overview(),
        "spot_research_enabled": settings.spot_research_enabled,
    }


@app.get("/local/health")
async def local_release_health():
    # Read-only identity for the local supervisor. No updater/command execution route.
    return {"ok": True, "release_sha": os.environ.get("AGENT_RELEASE_SHA", "checkout"), "pid": os.getpid()}


@app.get("/research/reverse-entry-v3")
async def reverse_entry_v3_api():
    if settings.runtime_profile == "lean":
        raise HTTPException(410, "USE_STANDALONE_REVERSE_RESEARCH_BOT")
    return rei_v3.overview()


@app.post("/scan/run")
async def manual_scan():
    return await scan_job()


@app.post("/paper/monitor")
async def manual_monitor():
    return await monitor_job()


@app.post("/news/run")
async def manual_news():
    return await news_job()


@app.post("/spot/research/run")
async def manual_spot_research():
    return await spot_research_job()


@app.get("/spot/research")
async def spot_research_history(limit: int = Query(5, ge=1, le=50)):
    return latest_spot_research(limit)


@app.get("/strategy-evaluation")
async def strategy_evaluation():
    return strategy_evaluation_overview()


@app.get("/strategy-cases")
async def strategy_cases(include_archived: bool = False):
    return list_strategy_cases(include_archived=include_archived)


@app.post("/strategy-cases")
async def strategy_case_create(payload: dict = Body(...)):
    try:
        return create_strategy_case(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.patch("/strategy-cases/{strategy_id}")
async def strategy_case_update(strategy_id: str, payload: dict = Body(...)):
    try:
        return update_strategy_case(strategy_id, payload)
    except KeyError:
        raise HTTPException(404, "Strategy case not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/strategy-cases/{strategy_id}/clone")
async def strategy_case_clone(strategy_id: str, payload: dict = Body(default={})):
    try:
        return clone_strategy_case(strategy_id, payload)
    except KeyError:
        raise HTTPException(404, "Strategy case not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/strategy-cases/{strategy_id}/history")
async def strategy_case_versions(strategy_id: str, limit: int = Query(100, ge=1, le=500)):
    if not any(x["strategy_id"] == strategy_id for x in list_strategy_cases(True)):
        raise HTTPException(404, "Strategy case not found")
    return strategy_case_history(strategy_id, limit)


@app.get("/coins/{symbol}/detail")
async def get_coin_detail(
    symbol: str,
    interval: str = Query("15m", pattern="^(1m|5m|15m|1h|4h)$"),
    trade_limit: int = Query(1000, ge=1, le=5000),
):
    if settings.runtime_profile == 'lean':
        raise HTTPException(410, 'CANDLE_COIN_DETAILS_RETIRED')
    try:
        return await coin_detail(symbol, interval=interval, trade_limit=trade_limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/trades/{trade_id}/detail")
async def get_trade_detail(
    trade_id: int,
    interval: str = Query("15m", pattern="^(1m|5m|15m|1h|4h)$"),
):
    if settings.runtime_profile == 'lean':
        raise HTTPException(410, 'CANDLE_TRADE_DETAILS_RETIRED')
    try:
        return await trade_detail(trade_id, interval)
    except KeyError:
        raise HTTPException(404, "Trade not found")


@app.post("/trades/{trade_id}/exit-simulate")
async def simulate_trade_exit_api(trade_id: int):
    if settings.runtime_profile == 'lean':
        raise HTTPException(410, 'EXIT_SIMULATOR_RETIRED')
    try:
        return await simulate_trade_exit(trade_id)
    except KeyError:
        raise HTTPException(404, "Trade not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/reports/daily/{day}/analysis")
async def read_daily_analysis(day: str):
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Expected YYYY-MM-DD")
    path = report_root() / day / "daily-analysis.json"
    if not path.exists():
        raise HTTPException(404, "Analysis not generated yet")
    import json
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/reports/daily/{day}/analysis/markdown", response_class=PlainTextResponse)
async def read_analysis_markdown(day: str):
    path = report_root() / day / "daily-analysis.md"
    if not path.exists():
        raise HTTPException(404, "Analysis not generated yet")
    return path.read_text(encoding="utf-8")


@app.get("/reports/daily/{day}/analysis/html", response_class=HTMLResponse)
async def read_analysis_html(day: str):
    path = report_root() / day / "daily-analysis.html"
    if not path.exists():
        raise HTTPException(404, "Analysis not generated yet")
    return path.read_text(encoding="utf-8")


@app.post("/reports/daily/{day}/analysis/run")
async def run_analysis_manual(day: str):
    try:
        validate_day(day)
    except ValueError:
        raise HTTPException(400, "Expected YYYY-MM-DD")
    try:
        return await daily_analysis_job(day, refresh=False)
    except HistoricalReportError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/reports/recover/yesterday")
async def recover_yesterdays_report():
    """Explicit manual catch-up; only yesterday is safe to regenerate."""
    return await missed_report_recovery_job()


@app.get("/reports/github-sync/status")
async def github_report_sync_status():
    return {
        **sync_status(),
        "last": get_system_state("report_github_sync", {}) or {},
        "today": local_report_status(datetime.now(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d")),
        "yesterday": local_report_status((datetime.now(ZoneInfo(settings.timezone)) - timedelta(days=1)).strftime("%Y-%m-%d")),
    }


@app.post("/reports/github-sync/{day}")
async def manual_github_report_sync(day: str):
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "day must be YYYY-MM-DD")
    return await sync_report_files(day)


@app.post("/system/backup")
async def manual_backup():
    return await backup_now("manual")


@app.post("/system/recover")
async def manual_recovery():
    async with monitor_lock:
        result = await recover_active_positions()
    if result.get("closed"):
        await send_telegram(render_close_alert(result["closed"]))
    return result


@app.get("/system/status")
async def system_status():
    return system_overview()


@app.get("/system/events")
async def system_events(limit: int = Query(50, ge=1, le=500)):
    return recent_system_events(limit)


@app.get("/research/reverse")
async def reverse_research_api(limit: int = Query(35, ge=1, le=120)):
    if settings.runtime_profile == "lean":
        raise HTTPException(410, "USE_STANDALONE_REVERSE_RESEARCH_BOT")
    return {
        **reverse_lab_overview(limit=limit),
        "enabled": reverse_lab_active(),
    }


@app.get("/research/reverse-entry")
async def reverse_entry_api(limit: int = Query(30, ge=1, le=120)):
    if settings.runtime_profile == "lean":
        raise HTTPException(410, "USE_STANDALONE_REVERSE_RESEARCH_BOT")
    return reverse_entry_overview(limit=limit)


@app.post("/research/reverse/monitor")
async def reverse_research_monitor():
    if settings.runtime_profile == "lean":
        raise HTTPException(410, "USE_STANDALONE_REVERSE_RESEARCH_BOT")
    if not reverse_lab_active():
        return {"status":"DISABLED","reason":"Enable Reverse Lab + Strategy Battle"}
    return await reverse_lab_monitor_job()


@app.get("/reports/daily/{day}/reverse", response_class=HTMLResponse)
async def reverse_research_report(day: str):
    try:
        datetime.strptime(day,"%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(400,"Expected YYYY-MM-DD") from exc
    target=report_root()/day/"reverse-lab.html"
    if not target.is_file():
        raise HTTPException(404,"Reverse Lab report is not generated yet")
    return target.read_text(encoding="utf-8")


@app.get("/research/v44")
async def v44_research_overview(limit: int = Query(60, ge=1, le=150)):
    return research_overview(limit)


@app.post("/research/v44/monitor")
async def v44_research_monitor():
    if not settings.v44_shadow_enabled:
        return {"status":"DISABLED", "reason":"Set V44_SHADOW_ENABLED=true to run shadow research"}
    return await v44_monitor_job()


@app.get("/research/v44/analysis")
async def v44_cached_analysis():
    return get_system_state("v44_research_summary", {}) or {"status":"NO_RESEARCH_REPORT_YET"}


@app.post("/research/v44/analysis/run")
async def v44_refresh_analysis():
    if not settings.v44_shadow_enabled:
        return {"status":"DISABLED", "reason":"V44_SHADOW_ENABLED=false"}
    if analysis_lock.locked():
        return {"status":"ALREADY_RUNNING"}
    async with analysis_lock:
        return await asyncio.to_thread(research_snapshot)


@app.get("/reports/daily/{day}/v44", response_class=HTMLResponse)
async def v44_daily_report_html(day: str):
    try:
        datetime.strptime(day,"%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400,detail="Invalid day format") from exc
    filepath=report_root()/day/"v44-research.html"
    if not filepath.is_file():
        raise HTTPException(status_code=404,detail="V4.4 research report not found")
    return filepath.read_text(encoding="utf-8")


@app.get("/scan/latest")
async def get_latest():
    data = latest_scan()
    if not data:
        raise HTTPException(404, "No scan result yet")
    return data


@app.get("/positions")
async def positions():
    return (
        battle_open_positions()
        if settings.strategy_battle_enabled
        else open_positions()
    )


@app.get("/trades")
async def trades(limit: int = 100):
    safe_limit = min(max(limit, 1), 500)
    return (
        battle_recent_trades(safe_limit)
        if settings.strategy_battle_enabled
        else recent_trades(safe_limit)
    )


@app.get("/news")
async def news(
    limit: int = Query(60, ge=1, le=300),
    hours: int = Query(48, ge=1, le=720),
    symbol: str | None = None,
):
    symbol = symbol.upper().replace("USDT", "") if symbol else None
    return recent_news(limit=limit, hours=hours, symbol=symbol)


@app.get("/news/summary")
async def news_summary(hours: int = Query(24, ge=1, le=168)):
    return market_news_summary(hours)


@app.get("/news/guardian")
async def news_guardian():
    return news_guardian_overview()


@app.post("/news/guardian/run")
async def manual_news_guardian():
    decision = await evaluate_news_guardian()
    closed = []
    if (
        settings.strategy_battle_enabled
        and decision.get("mode") == "EVENT_LOCK"
        and decision.get("is_new_event")
    ):
        async with monitor_lock:
            closed = await close_battle_for_news(decision)
    return {"decision": decision, "closed": closed}


@app.post("/reports/daily/{day}")
async def make_daily(day: str):
    try:
        validate_day(day)
    except ValueError:
        raise HTTPException(400, "Use YYYY-MM-DD")
    try:
        require_recent_day(day)
    except HistoricalReportError as exc:
        raise HTTPException(409, str(exc)) from exc
    return (
        generate_battle_and_save(day)
        if settings.strategy_battle_enabled
        else generate_and_save(day)
    )


def _saved_or_recent_report(day: str) -> dict:
    try:
        validate_day(day)
    except ValueError as exc:
        raise HTTPException(400, "Use YYYY-MM-DD") from exc
    data = get_daily_report(day)
    if data and data.get("report_date") == day:
        return data
    try:
        return read_snapshot(day, "daily-report")
    except (OSError, ValueError):
        pass
    try:
        require_recent_day(day)
    except HistoricalReportError as exc:
        raise HTTPException(404, "Saved historical report is missing or invalid; current state cannot reconstruct it") from exc
    return (generate_battle_and_save if settings.strategy_battle_enabled else generate_and_save)(day)


@app.get("/reports/daily/{day}")
async def daily(day: str):
    return _saved_or_recent_report(day)


@app.get("/reports/daily/{day}/markdown", response_class=PlainTextResponse)
async def daily_markdown(day: str):
    data = _saved_or_recent_report(day)
    return (
        render_battle_markdown(data)
        if data.get("report_type") in {"STRATEGY_BATTLE", "DAILY_INTELLIGENCE_V42", "DAILY_INTELLIGENCE_V43", "DAILY_INTELLIGENCE_V432"}
        else render_markdown(data)
    )


@app.get("/reports/daily/{day}/html", response_class=HTMLResponse)
async def daily_html(day: str):
    data = _saved_or_recent_report(day)
    if data.get("report_type") in {"STRATEGY_BATTLE", "DAILY_INTELLIGENCE_V42", "DAILY_INTELLIGENCE_V43", "DAILY_INTELLIGENCE_V432"}:
        return render_battle_html(data)
    return render_legacy_html(data)


@app.get("/recommendations")
async def recommendations():
    return list_recommendations()


@app.get("/analytics")
async def analytics():
    if settings.strategy_battle_enabled:
        return build_strategy_battle_dashboard()
    trades_all = recent_trades(500)
    positions_all = open_positions()
    balance = account_balance()
    return build_dashboard_analytics(
        trades_all,
        positions_all,
        balance,
        settings.timezone,
        settings.taker_fee_bps,
    )



@app.get("/api/lean")
async def lean_dashboard_data():
    """Fast, redacted summary for A-F Paper UI. Research is lazy-loaded."""
    battle = build_strategy_battle_dashboard() if settings.strategy_battle_enabled else None
    cases = battle["strategies"] if battle else []
    allowed = set(LEAN_CASE_IDS)
    positions_all = battle_open_positions() if settings.strategy_battle_enabled else []
    case_fields = ("realized_pnl", "closed", "win_rate", "profit_factor",
                   "expectancy_r", "max_drawdown_pct")
    position_fields = ("strategy_id", "symbol", "side", "entry_price", "stop_loss",
                       "take_profit", "unrealized_pnl")
    trade_fields = ("strategy_id", "symbol", "side", "closed_at", "net_pnl",
                    "r_multiple", "exit_reason")
    scan_fields = ("symbol", "bias", "long_score", "short_score", "rsi_1h", "atr_pct_1h")
    scan = latest_scan() or {}
    system = system_overview()
    return {
        "build": version_info(),
        "runtime_profile": settings.runtime_profile,
        "local_trade_history": {"enabled": settings.runtime_profile == "lean",
                                "storage": "LOCAL_ONLY",
                                "relative_path": "reports/YYYY-MM-DD/trade-history.csv",
                                "github_upload": False},
        "strategy_battle_enabled": settings.strategy_battle_enabled,
        "cases": [
            {"strategy_id": c["strategy_id"], "name": c["name"],
             "short_name": c["short_name"], "enabled": c["enabled"],
             "analytics": {k: c["analytics"].get(k) for k in case_fields}}
            for c in cases
        ],
        "missing_case_ids": [sid for sid in LEAN_CASE_IDS if sid not in {c["strategy_id"] for c in cases}],
        "open_positions": [{k: p.get(k) for k in position_fields}
                           for p in (battle["open_positions"] if battle else [])],
        "legacy_open_positions": sum(1 for p in positions_all if p.get("strategy_id") not in allowed),
        "trades": [{k: t.get(k) for k in trade_fields}
                   for t in (battle["trades"][-100:] if battle else [])],
        "scan": {
            "created_at": scan.get("created_at"), "btc_regime": scan.get("btc_regime"),
            "symbols_scanned": scan.get("symbols_scanned"),
            "all": [{k: r.get(k) for k in scan_fields} for r in (scan.get("all") or [])[:60]],
        },
        "reports": [{k: row.get(k) for k in ("report_date", "created_at")}
                    for row in latest_daily_reports(14)],
        "system": {key: system.get(key) for key in
                   ("network", "last_backup", "jobs", "scheduler")},
    }

@app.get("/api/lean/reverse")
async def lean_reverse_data():
    """Old in-process Reverse research is retired; separate process owns reports."""
    raise HTTPException(410, "USE_STANDALONE_REVERSE_RESEARCH_BOT")


@app.get("/api/dashboard")
async def dashboard_data():
    strategy_battle = (
        build_strategy_battle_dashboard()
        if settings.strategy_battle_enabled
        else None
    )

    if strategy_battle:
        baseline = next(
            s for s in strategy_battle["strategies"]
            if s["strategy_id"] == "BASE_RR2"
        )
        analytics_data = baseline["analytics"]
        positions_all = strategy_battle["open_positions"]
        trades_all = strategy_battle["trades"]
    else:
        trades_all = recent_trades(500)
        positions_all_raw = open_positions()
        balance = account_balance()
        analytics_data = build_dashboard_analytics(
            trades_all,
            positions_all_raw,
            balance,
            settings.timezone,
            settings.taker_fee_bps,
        )
        positions_all = analytics_data["open_positions"]

    return {
        "version": VERSION,
        "build": version_info(),
        "reverse_entry_intelligence": reverse_entry_overview(limit=25),
        "reverse_entry_v3": rei_v3.overview(),
        "v44_research": research_overview(25),
        "reverse_research": {
            **reverse_lab_overview(limit=30),
            "enabled": bool(settings.reverse_lab_enabled and settings.v44_shadow_enabled
                            and settings.strategy_battle_enabled),
        },
        "balance": analytics_data["balance"],
        "equity": analytics_data["equity"],
        "unrealized_pnl": analytics_data["unrealized_pnl"],
        "open_positions": positions_all,
        "trades": trades_all[-300:],
        "trade_stats": {
            "closed": analytics_data["closed"],
            "wins": analytics_data["wins"],
            "losses": analytics_data["losses"],
            "win_rate": analytics_data["win_rate"],
            "net_pnl": analytics_data["realized_pnl"],
            "profit_factor": analytics_data["profit_factor"],
            "avg_r": analytics_data["avg_r"],
            "max_drawdown_pct": analytics_data["max_drawdown_pct"],
        },
        "analytics": analytics_data,
        "strategy_battle": strategy_battle,
        "scan_state": dict(scan_state),
        "scan": latest_scan(),
        "news_summary": market_news_summary(24),
        "news_guardian": news_guardian_overview(),
        "news": recent_news(limit=50, hours=settings.news_lookback_hours),
        "reports": [
            {
                **r,
                "analysis_available": bool(
                    r.get("report_date")
                    and (report_root() / str(r["report_date"]) / "daily-analysis.json").exists()
                ),
            }
            for r in latest_daily_reports(14)
        ],
        "recommendations": list_recommendations(12),
        "spot_research": (latest_spot_research(1) or [None])[0],
        "system": system_overview(),
        "system_events": recent_system_events(25),
        "strategy_cases": list_strategy_cases(include_archived=False) if settings.strategy_battle_enabled else [],
        "strategy_evaluation": strategy_evaluation_overview() if settings.strategy_battle_enabled else None,
        "daily_analysis_status": get_system_state("job_daily_analysis", {}) or {},
        "report_sync": {
            **sync_status(),
            "last": get_system_state("report_github_sync", {}) or {},
        },
        "settings": {
            "v44_shadow_enabled": settings.v44_shadow_enabled,
            "reverse_lab_enabled": settings.reverse_lab_enabled,
            "top_n_coins": settings.top_n_coins,
            "scan_interval_min": settings.scan_interval_min,
            "monitor_interval_sec": settings.monitor_interval_sec,
            "news_refresh_min": settings.news_refresh_min,
            "news_guardian_enabled": settings.news_guardian_enabled,
            "news_caution_impact": settings.news_caution_impact,
            "news_high_impact": settings.news_high_impact,
            "news_direction_confidence": settings.news_direction_confidence,
            "health_check_interval_sec": settings.health_check_interval_sec,
            "backup_interval_hours": settings.backup_interval_hours,
            "spot_research_enabled": settings.spot_research_enabled,
            "spot_research_interval_min": settings.spot_research_interval_min,
            "score_threshold": settings.score_threshold,
            "data_collection_mode": settings.data_collection_mode,
            "collection_max_open_trades": settings.collection_max_open_trades,
            "collection_risk_per_trade_pct": settings.collection_risk_per_trade_pct,
            "strategy_battle_enabled": settings.strategy_battle_enabled,
            "battle_start_balance": settings.battle_start_balance,
            "max_open_trades": settings.max_open_trades,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "reward_risk": settings.reward_risk,
            "paper_leverage": settings.paper_leverage,
            "taker_fee_bps": settings.taker_fee_bps,
            "slippage_bps": settings.slippage_bps,
        },
    }


# Deprecated inline V3 HTML removed. Full-mode fallback remains in dashboard_v43.py.


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    if settings.runtime_profile == 'lean':
        return DASHBOARD_HTML_LEAN
    return DASHBOARD_HTML_V43 if settings.strategy_battle_enabled else DASHBOARD_HTML_V4
