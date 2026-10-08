import asyncio
from app import storage
from app.config import settings
from app.report_sync import sync_report_files, sync_status


def test_report_sync_status_disabled(monkeypatch):
    monkeypatch.setattr(settings, "report_github_sync_enabled", False)
    monkeypatch.setattr(settings, "report_github_repo", "")
    monkeypatch.setattr(settings, "report_github_token", "")
    status = sync_status()
    assert status["enabled"] is False
    assert status["configured"] is False


def test_report_sync_skips_safely_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    monkeypatch.setattr(settings, "report_github_sync_enabled", True)
    monkeypatch.setattr(settings, "report_github_repo", "")
    monkeypatch.setattr(settings, "report_github_token", "")
    result = asyncio.run(sync_report_files("2026-10-07"))
    assert result["ok"] is False
    assert result["skipped"] is True
    assert "missing" in result["reason"].lower()
