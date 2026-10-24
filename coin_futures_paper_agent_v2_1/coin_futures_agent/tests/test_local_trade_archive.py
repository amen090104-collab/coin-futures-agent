"""Trade histories stay on the user's disk, never in GitHub Actions/reports repo."""
import asyncio
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path

import pytest
from app import local_trade_archive as archive, report_sync, storage
from app.config import settings


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    monkeypatch.setattr(settings, "report_storage_mode", "local_only")
    monkeypatch.setattr(settings, "timezone", "Asia/Ho_Chi_Minh")
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports"))
    monkeypatch.setattr(settings, "strategy_battle_enabled", True)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    with storage._connect() as db:
        # Keep this fixture lean: the real battle SQL reader needs only these
        # columns. All research/details are still present in actual databases.
        db.execute("""CREATE TABLE battle_trades (
            id INTEGER PRIMARY KEY, strategy_id TEXT, symbol TEXT, side TEXT,
            opened_at TEXT, closed_at TEXT, entry_price REAL, exit_price REAL,
            net_pnl REAL, r_multiple REAL, reason_text TEXT, entry_context TEXT)""")
        db.executemany(
            "INSERT INTO battle_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, "CASE_E", "BTCUSDT", "LONG", "2026-10-24T16:00:00+00:00",
                 "2026-10-24T16:59:50+00:00", 100., 101., 1., 1., "ok", "{}"),
                (2, "CASE_F", "=HYPERLINK(\\\"x\\\")", "SHORT", "2026-10-24T16:20:00+00:00",
                 "2026-10-24T17:00:02+00:00", 100., 102., -2., -1., "loss", "{}"),
                (3, "BASE_75_79", "ETHUSDT", "SHORT", "2026-10-24T16:10:00+00:00",
                 "2026-10-24T17:01:00+00:00", 200., 199., 1., 1., "legacy", "{}"),
            ],
        )
    return tmp_path / "reports"


def test_timezone_midnight_and_legacy_rows_are_archived(isolated):
    result = archive.export_local_trade_history("2026-10-25")
    assert result["status"] == "SAVED" and result["github_uploaded"] is False
    out = isolated / "2026-10-25"
    doc = json.loads((out / "trade-history.json").read_text(encoding="utf-8"))
    assert doc["trade_count"] == 2
    assert [x["strategy_id"] for x in doc["trades"]] == ["CASE_F", "BASE_75_79"]
    assert all(t["closed_at"] >= "2026-10-24T17:00:00+00:00" for t in doc["trades"])
    result_prior = archive.export_local_trade_history("2026-10-24")
    assert result_prior["trades"] == 1
    assert (isolated / "2026-10-24" / "trade-history.csv").is_file()


def test_csv_is_excel_friendly_and_blocks_formula_injection(isolated):
    archive.export_local_trade_history("2026-10-25")
    data = (isolated / "2026-10-25" / "trade-history.csv").read_text(encoding="utf-8-sig")
    parsed = list(csv.DictReader(StringIO(data)))
    assert len(parsed) == 2
    assert parsed[0]["symbol"].startswith("'=HYPERLINK")


def test_export_is_idempotent_and_does_not_delete_old_history(isolated):
    first = archive.export_local_trade_history("2026-10-25")
    old = Path(first["json"]).read_bytes()
    assert archive.export_local_trade_history("2026-10-25")["status"] == "UNCHANGED"
    assert Path(first["json"]).read_bytes() == old
    assert (isolated / "2026-10-24").exists() is False


def test_archive_refuses_to_shrink_after_stale_database_restore(isolated):
    first = archive.export_local_trade_history("2026-10-25")
    old_json = Path(first["json"]).read_bytes()
    old_csv = Path(first["csv"]).read_bytes()
    with storage._connect() as db:
        db.execute("DELETE FROM battle_trades WHERE id=3")
    with pytest.raises(ValueError, match="LOCAL_ARCHIVE_SHRINK_BLOCKED"):
        archive.export_local_trade_history("2026-10-25")
    assert Path(first["json"]).read_bytes() == old_json
    assert Path(first["csv"]).read_bytes() == old_csv


def test_local_only_never_calls_github_even_with_stale_env_token(isolated, monkeypatch):
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(settings, "report_github_repo", "owner/private-reports")
    monkeypatch.setattr(settings, "report_github_token", "OLD_TOKEN_IN_LOCAL_ENV")
    monkeypatch.setattr(settings, "report_storage_mode", "local_and_github")
    # LEAN remains protected even if someone re-enables remote mode in .env.
    monkeypatch.setattr(report_sync.httpx, "AsyncClient",
                        lambda **kwargs: pytest.fail("NO GITHUB API CALL ALLOWED"))
    assert report_sync.sync_status()["enabled"] is False
    result = asyncio.run(report_sync.sync_report_files("2026-10-25"))
    assert result["reason"] == "LOCAL_ONLY_NO_GITHUB"
    assert result["skipped"] and not result["uploaded"]


def test_default_local_storage_blocks_old_true_flag_even_in_full(isolated, monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "full")
    monkeypatch.setattr(settings, "report_storage_mode", "local_only")
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(settings, "report_github_repo", "owner/private-reports")
    monkeypatch.setattr(settings, "report_github_token", "OLD_TOKEN")
    monkeypatch.setattr(report_sync.httpx, "AsyncClient",
                        lambda **kwargs: pytest.fail("NO GITHUB API CALL ALLOWED"))
    assert report_sync.sync_status()["enabled"] is False
    result = asyncio.run(report_sync.sync_report_files("2026-10-25"))
    assert result["reason"] == "LOCAL_ONLY_NO_GITHUB"


def test_startup_catchup_limits_archive_window(isolated, monkeypatch):
    captured = []
    def fake_export(day):
        captured.append(day)
        return {"trades": 2, "status": "SAVED"}
    monkeypatch.setattr(archive, "export_local_trade_history", fake_export)
    result = archive.archive_recent_days(days=2)
    assert result["days"] == 3 and result["trades"] == 6
    assert len(captured) == len(set(captured)) == 3
    assert all(captured[i] < captured[i+1] for i in range(2))
    with pytest.raises(ValueError):
        archive.archive_recent_days(days=100)
