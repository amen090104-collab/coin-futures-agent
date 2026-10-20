"""Regression checks use temporary storage and never start the application lifespan."""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app import main, resilience, storage
from app import battle_reports, reports
from app.config import settings


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    class Midday(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz).replace(hour=12, minute=0, second=0)
    monkeypatch.setattr(main, "datetime", Midday)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports"))
    monkeypatch.setattr(settings, "strategy_battle_enabled", False)
    monkeypatch.setattr(settings, "v44_shadow_enabled", False)
    monkeypatch.setattr(settings, "reverse_lab_enabled", False)
    monkeypatch.setattr(settings, "report_github_sync_enabled", False)
    monkeypatch.setattr(main, "send_telegram", AsyncMock())
    storage.init_db()
    return tmp_path / "reports"


def local_day(offset=0):
    return (datetime.now(ZoneInfo(settings.timezone)) + timedelta(days=offset)).date().isoformat()


@pytest.mark.parametrize("battle", [False, True])
def test_recovery_dispatches_to_the_selected_engine(monkeypatch, battle):
    legacy = AsyncMock(return_value={"engine": "legacy"})
    strategy = AsyncMock(return_value={"engine": "battle"})
    monkeypatch.setattr(settings, "strategy_battle_enabled", battle)
    monkeypatch.setattr(resilience, "recover_open_positions", legacy)
    monkeypatch.setattr(resilience, "recover_battle_open_positions", strategy)
    assert asyncio.run(resilience.recover_active_positions()) == {
        "engine": "battle" if battle else "legacy"
    }
    assert legacy.await_count == int(not battle)
    assert strategy.await_count == int(battle)


def test_recovery_cannot_claim_success_without_artifacts(isolated, monkeypatch):
    monkeypatch.setattr(main, "daily_analysis_job", AsyncMock(return_value={"status": "SKIPPED"}))
    result = asyncio.run(main.missed_report_recovery_job())
    assert result["status"] != "RECOVERED"
    assert not (isolated / local_day(-1) / "daily-report.json").exists()


def test_recovery_notices_missing_research_artifacts(isolated, monkeypatch):
    monkeypatch.setattr(settings, "strategy_battle_enabled", True)
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    monkeypatch.setattr(settings, "reverse_lab_enabled", True)
    folder = isolated / local_day(-1)
    folder.mkdir(parents=True)
    for stem in ("daily-report", "daily-analysis"):
        (folder / f"{stem}.json").write_text(json.dumps({"report_date": local_day(-1)}))
    repair = AsyncMock(return_value={"status": "PARTIAL"})
    monkeypatch.setattr(main, "daily_analysis_job", repair)
    result = asyncio.run(main.missed_report_recovery_job())
    assert result["status"] != "ALREADY_PRESENT"
    assert result["status"] != "RECOVERED"
    repair.assert_awaited_once()


@pytest.mark.parametrize("generator", [reports.build_daily_report, battle_reports.build_battle_daily_report])
def test_historical_generation_rejected_before_current_state_reads(isolated, monkeypatch, generator):
    def forbidden(*args, **kwargs):
        pytest.fail("historical generation must not read current trading state")
    monkeypatch.setattr(reports, "trades_between", forbidden)
    monkeypatch.setattr(battle_reports, "list_strategy_cases", forbidden)
    with pytest.raises(ValueError, match="[Hh]istorical"):
        generator("2024-01-01")


@pytest.mark.parametrize("endpoint", [main.daily, main.daily_markdown, main.daily_html, main.make_daily])
def test_api_refuses_to_fabricate_a_missing_historical_report(isolated, monkeypatch, endpoint):
    generator = lambda *_: pytest.fail("must not synthesize a historical report")
    monkeypatch.setattr(main, "generate_and_save", generator)
    monkeypatch.setattr(main, "generate_battle_and_save", generator)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint("2024-01-01"))
    assert exc.value.status_code in {404, 409}


def test_legacy_generator_writes_the_sync_bundle(isolated):
    day = local_day()
    result = reports.generate_and_save(day)
    folder = isolated / day
    for suffix in ("json", "md", "html"):
        assert (folder / f"daily-report.{suffix}").stat().st_size > 0
    assert json.loads((folder / "daily-report.json").read_text())["report_date"] == day
    assert result["report_date"] == day


@pytest.mark.parametrize("battle,shadow,reverse,count", [
    (False, True, True, 3), (True, False, True, 6),
    (True, True, False, 9), (True, True, True, 12),
])
def test_required_artifacts_follow_enabled_features(isolated, monkeypatch, battle, shadow, reverse, count):
    from app.report_files import bundle_status
    monkeypatch.setattr(settings, "strategy_battle_enabled", battle)
    monkeypatch.setattr(settings, "v44_shadow_enabled", shadow)
    monkeypatch.setattr(settings, "reverse_lab_enabled", reverse)
    status = bundle_status(local_day())
    assert len(status["required"]) == count
    assert len(status["missing_or_invalid"]) == count
    assert not status["complete"]


def enable_research(monkeypatch):
    from app.battle_storage import init_battle_db, ensure_battle_initial_balances
    from app.strategy_cases import init_strategy_cases
    from app.decision_journal import init_decision_journal
    monkeypatch.setattr(settings, "strategy_battle_enabled", True)
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    monkeypatch.setattr(settings, "reverse_lab_enabled", True)
    init_battle_db()
    init_strategy_cases()
    init_decision_journal()
    ensure_battle_initial_balances(datetime.now().isoformat(), 10000)


@pytest.mark.parametrize("research", [False, True])
def test_recovery_creates_a_complete_bundle_and_is_repeatable(isolated, monkeypatch, research):
    from app.report_files import bundle_status
    if research:
        enable_research(monkeypatch)
    first = asyncio.run(main.missed_report_recovery_job())
    assert first["status"] == "RECOVERED"
    assert bundle_status(local_day(-1))["complete"]
    contents = {p.name: p.read_bytes() for p in (isolated / local_day(-1)).iterdir()}
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "ALREADY_PRESENT"
    assert contents == {p.name: p.read_bytes() for p in (isolated / local_day(-1)).iterdir()}


def test_partial_research_failure_is_visible_and_repaired_without_rebuilding_other_snapshots(isolated, monkeypatch):
    from app import reporting
    enable_research(monkeypatch)
    original = reporting.write_reverse_lab_report
    def broken(*args, **kwargs):
        raise OSError("simulated research write failure")
    monkeypatch.setattr(reporting, "write_reverse_lab_report", broken)
    first = asyncio.run(main.missed_report_recovery_job())
    assert first["status"] == "PARTIAL"
    assert "reverse-lab" in first["result"]["errors"]
    assert storage.get_system_state("job_daily_analysis")["status"] == "PARTIAL"
    folder = isolated / local_day(-1)
    saved = {name: (folder / name).read_bytes() for name in
             ("daily-report.json", "daily-analysis.json", "v44-research.json")}
    monkeypatch.setattr(reporting, "write_reverse_lab_report", original)
    second = asyncio.run(main.missed_report_recovery_job())
    assert second["status"] == "RECOVERED"
    assert saved == {name: (folder / name).read_bytes() for name in saved}


def test_missing_research_formats_use_the_saved_snapshot_not_live_research(isolated, monkeypatch):
    from app import reporting, v44_learning, reverse_research
    enable_research(monkeypatch)
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    folder = isolated / local_day(-1)
    saved = {}
    for stem in ("v44-research", "reverse-lab"):
        saved[stem] = (folder / f"{stem}.json").read_bytes()
        for suffix in ("md", "html"):
            (folder / f"{stem}.{suffix}").unlink()
    def forbidden(*args, **kwargs):
        pytest.fail("repair must not recompute a saved research snapshot")
    monkeypatch.setattr(reporting, "write_research_report", forbidden)
    monkeypatch.setattr(reporting, "write_reverse_lab_report", forbidden)
    monkeypatch.setattr(v44_learning, "research_snapshot", forbidden)
    monkeypatch.setattr(reverse_research, "reverse_lab_snapshot", forbidden)
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    assert saved == {stem: (folder / f"{stem}.json").read_bytes() for stem in saved}


@pytest.mark.parametrize("endpoint", [main.daily, main.daily_markdown, main.daily_html])
def test_saved_historical_report_is_read_without_current_account_access(isolated, monkeypatch, endpoint):
    doc = reports.generate_and_save(local_day())
    old = "2024-01-01"
    doc["report_date"] = old
    folder = isolated / old
    folder.mkdir()
    (folder / "daily-report.json").write_text(json.dumps(doc))
    monkeypatch.setattr(storage, "account_balance", lambda: pytest.fail("must not read live balance"))
    monkeypatch.setattr(reports, "build_daily_report", lambda *_: pytest.fail("must not generate"))
    result = asyncio.run(endpoint(old))
    assert result["report_date"] == old if isinstance(result, dict) else old in result


@pytest.mark.parametrize("day", ["2024-1-01", "invalid", "../2024-01-01"])
@pytest.mark.parametrize("endpoint", [main.daily, main.make_daily, main.run_analysis_manual])
def test_invalid_api_dates_fail_before_storage_access(isolated, monkeypatch, day, endpoint):
    monkeypatch.setattr(main, "get_daily_report", lambda *_: pytest.fail("must validate before DB access"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(endpoint(day))
    assert exc.value.status_code == 400


def test_atomic_file_failure_keeps_existing_snapshot_and_cleans_temporary_file(isolated, monkeypatch):
    from app import report_files
    doc = reports.generate_and_save(local_day())
    path = isolated / local_day() / "daily-report.json"
    original = path.read_bytes()
    def broken(*args, **kwargs):
        raise OSError("simulated interrupted replace")
    monkeypatch.setattr(report_files.os, "replace", broken)
    with pytest.raises(OSError):
        report_files.write_bundle(local_day(), "daily-report", {**doc, "net_pnl": 999}, "new", "new")
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".daily-report-*"))


def test_legacy_report_sync_regenerates_then_uploads_the_dated_bundle(isolated, monkeypatch):
    import base64
    import httpx
    from app import report_sync
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(report_sync, "sync_status", lambda: {
        "configured": True, "repo": "owner/reports", "branch": "main", "base_path": "reports"
    })
    monkeypatch.setattr(report_sync, "_headers", lambda: {})
    uploaded = {}
    def handler(request):
        if request.method == "GET":
            return httpx.Response(404 if "/contents/" in request.url.path else 200,
                                  json={"private": True})
        body = json.loads(request.content)
        uploaded[request.url.path] = base64.b64decode(body["content"])
        return httpx.Response(200, json={"commit": {"sha": "mock-commit"}, "content": {}})
    client = httpx.AsyncClient
    monkeypatch.setattr(report_sync.httpx, "AsyncClient", lambda **kwargs: client(
        transport=httpx.MockTransport(handler), **kwargs))
    day = local_day()
    result = asyncio.run(report_sync.sync_report_files(day))
    assert result["ok"]
    assert len(uploaded) == 4
    for suffix in ("json", "md", "html"):
        assert f"/repos/owner/reports/contents/reports/{day}/daily-report.{suffix}" in uploaded
    assert json.loads(uploaded["/repos/owner/reports/contents/reports/latest.json"])["report_date"] == day


def test_stale_analysis_is_rebuilt_only_from_its_saved_source(isolated, monkeypatch):
    from app.report_files import bundle_status
    enable_research(monkeypatch)
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    folder = isolated / local_day(-1)
    source = (folder / "daily-report.json").read_bytes()
    path = folder / "daily-analysis.json"
    stale = json.loads(path.read_text())
    stale["source_report_created_at"] = "old-source"
    path.write_text(json.dumps(stale))
    assert not bundle_status(local_day(-1))["complete"]
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    assert (folder / "daily-report.json").read_bytes() == source
    assert json.loads(path.read_text())["source_report_created_at"] == json.loads(source)["created_at"]


def test_historical_research_repair_uses_frozen_json_and_refuses_missing_snapshots(isolated, monkeypatch):
    import shutil
    from app import reporting
    enable_research(monkeypatch)
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    old = "2024-01-01"
    folder = isolated / old
    shutil.copytree(isolated / local_day(-1), folder)
    for path in folder.glob("*.json"):
        doc = json.loads(path.read_text())
        doc["report_day" if path.stem in {"v44-research", "reverse-lab"} else "report_date"] = old
        path.write_text(json.dumps(doc))
    saved = {p.name: p.read_bytes() for p in folder.glob("*.json")}
    for path in folder.glob("*.md"):
        path.unlink()
    for path in folder.glob("*.html"):
        path.unlink()
    def forbidden(*args, **kwargs):
        pytest.fail("historical repair must not query live trading or research state")
    monkeypatch.setattr(reporting, "generate_battle_and_save", forbidden)
    monkeypatch.setattr(reporting, "write_research_report", forbidden)
    monkeypatch.setattr(reporting, "write_reverse_lab_report", forbidden)
    assert reporting.prepare_daily_bundle(old)["status"] == "OK"
    assert saved == {name: (folder / name).read_bytes() for name in saved}
    (folder / "reverse-lab.json").unlink()
    incomplete = reporting.prepare_daily_bundle(old)
    assert incomplete["status"] == "PARTIAL"
    assert "Historical" in incomplete["errors"]["reverse-lab"]


def test_corrupt_historical_sync_fails_before_network(isolated, monkeypatch):
    from app import report_sync
    old = "2024-01-01"
    folder = isolated / old
    folder.mkdir(parents=True)
    path = folder / "daily-report.json"
    path.write_text('{"report_date":"wrong-day"}')
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(report_sync, "sync_status", lambda: {
        "configured": True, "repo": "owner/reports", "branch": "main", "base_path": "reports"
    })
    monkeypatch.setattr(report_sync, "_headers", lambda: pytest.fail("must not contact GitHub"))
    result = asyncio.run(report_sync.sync_report_files(old))
    assert not result["ok"] and "Invalid daily-report.json" in result["reason"]
    assert path.read_text() == '{"report_date":"wrong-day"}'


def test_startup_catchup_checks_the_entire_bundle(isolated, monkeypatch):
    repair = AsyncMock(return_value={"status": "PARTIAL"})
    monkeypatch.setattr(main, "missed_report_recovery_job", repair)
    monkeypatch.setattr(main, "news_job", AsyncMock())
    monkeypatch.setattr(main, "scan_job", AsyncMock())
    monkeypatch.setattr(main, "spot_research_job", AsyncMock())
    asyncio.run(main._bootstrap())
    repair.assert_awaited_once()


def test_sync_retry_repairs_missing_research_before_accepting_old_upload_marker(isolated, monkeypatch):
    enable_research(monkeypatch)
    assert asyncio.run(main.missed_report_recovery_job())["status"] == "RECOVERED"
    storage.set_system_state("report_github_sync", {
        "ok": True, "report_date": local_day(-1),
        "uploaded": [{"path": "reports/latest-analysis.json"}],
    })
    (isolated / local_day(-1) / "reverse-lab.html").unlink()
    sync = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(main, "sync_report_files", sync)
    asyncio.run(main.analysis_sync_retry_job())
    sync.assert_awaited_once_with(local_day(-1))
    assert (isolated / local_day(-1) / "reverse-lab.html").exists()


def test_recovery_does_not_overlap_in_a_single_process(isolated, monkeypatch):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        async def slow_sync(*args, **kwargs):
            started.set()
            await release.wait()
            return {"ok": False, "reason": "disabled"}
        monkeypatch.setattr(main, "sync_report_files", slow_sync)
        task = asyncio.create_task(main.daily_analysis_job(local_day(-1)))
        await started.wait()
        try:
            # Even if files are already written, direct concurrent analysis is locked.
            assert (await main.daily_analysis_job(local_day(-1)))["status"] == "ALREADY_RUNNING"
        finally:
            release.set()
            await task
    asyncio.run(scenario())
