import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import storage
from app import report_sync as sync
from app.config import settings


def test_report_root_is_independent_of_process_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "reports_dir", "reports")
    monkeypatch.chdir(tmp_path)
    result = sync.report_root()
    assert result.is_absolute()
    assert result == Path(sync.__file__).resolve().parent.parent / "reports"
    assert result != tmp_path / "reports"


def test_report_root_supports_absolute_override(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "custom"))
    assert sync.report_root() == tmp_path / "custom"


def test_missing_report_returns_detailed_path_without_fake_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports"))
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(settings, "report_github_repo", "owner/report-repo")
    monkeypatch.setattr(settings, "report_github_token", "dummy-token")
    # Historical reports cannot be fabricated using current cumulative metrics.
    result = asyncio.run(sync.sync_report_files("2024-01-01"))
    assert not result["ok"]
    assert "Missing daily-report.json" in result["reason"]
    assert result["local"]["reports_dir"] == str(tmp_path / "reports")
    assert result["local"]["files"]["daily-report.json"] is False


def test_invalid_repository_name_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    monkeypatch.setattr(settings, "reports_dir", str(tmp_path / "reports"))
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(settings, "report_github_repo", "not_a_owner_repo")
    monkeypatch.setattr(settings, "report_github_token", "dummy-token")
    result = asyncio.run(sync.sync_report_files("2024-01-01"))
    assert not result["ok"]
    assert "owner/repository" in result["reason"]
