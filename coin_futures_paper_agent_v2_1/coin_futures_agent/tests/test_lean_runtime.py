"""Lean profile keeps the normal Paper safety gates and read-only triage."""
import json
import sqlite3

from app import main, battle, paper
from app.config import settings
from diagnose_agent import inspect


def test_full_runtime_preserves_legacy_jobs(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "full")
    assert main.legacy_research_jobs_enabled() is True


def test_lean_runtime_skips_legacy_jobs_but_not_v3_gates(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    assert main.legacy_research_jobs_enabled() is False
    # Lean deliberately does not mutate V3/V2 enablement or any .env values.
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", True)
    monkeypatch.setattr(settings, "reverse_entry_v3_enabled", True)
    assert main.rei_v3.enabled() is True


def test_lean_runtime_restores_paper_risk_limits(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    monkeypatch.setattr(settings, "data_collection_mode", True)
    policy = battle.battle_execution_policy()
    assert policy["enforce_daily_loss_guard"] is True
    assert policy["max_open_trades_per_strategy"] == settings.max_open_trades
    assert policy["max_new_trades_per_scan_per_strategy"] == settings.max_new_trades_per_scan
    assert policy["risk_per_trade_pct"] == settings.risk_per_trade_pct
    single_policy = paper.execution_policy()
    assert single_policy["enforce_daily_loss_guard"] is True
    assert single_policy["max_open_trades"] == settings.max_open_trades
    assert single_policy["max_new_trades_per_scan"] == settings.max_new_trades_per_scan
    assert single_policy["risk_per_trade_pct"] == settings.risk_per_trade_pct


def test_diagnostic_sqlite_read_only_and_secrets_not_exposed(tmp_path):
    (tmp_path / ".env").write_text(
        "RUNTIME_PROFILE=lean\nDATA_COLLECTION_MODE=true\n"
        "REPORT_GITHUB_TOKEN=SUPER_SECRET_VALUE\nTELEGRAM_BOT_TOKEN=OTHER_SECRET\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "agent.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE system_state(key TEXT, value TEXT, updated_at TEXT)")
        db.execute("INSERT INTO system_state VALUES(?,?,?)",
                   ("job_scan", json.dumps({"status": "ERROR", "at": "2026-10-25T00:00:00Z",
                                            "error": "SECRET_ERROR_TEXT"}),
                    "2026-10-25T00:00:00Z"))
    original = db_path.read_bytes()
    result = inspect(tmp_path)
    redacted = json.dumps(result)
    assert result["database"]["status"] == "OK"
    assert result["database"]["jobs"]["job_scan"]["status"] == "ERROR"
    assert result["flags"]["RUNTIME_PROFILE"] == "lean"
    assert "SUPER_SECRET_VALUE" not in redacted
    assert "OTHER_SECRET" not in redacted
    assert "SECRET_ERROR_TEXT" not in redacted
    assert str(tmp_path) not in redacted
    assert db_path.read_bytes() == original
