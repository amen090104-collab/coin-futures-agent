"""Read-only offline Windows triage. Never imports the trading runtime or opens orders."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

WHITELIST = (
    "RUNTIME_PROFILE", "DATA_COLLECTION_MODE", "STRATEGY_BATTLE_ENABLED",
    "V44_SHADOW_ENABLED", "REVERSE_LAB_ENABLED",
    "REVERSE_ENTRY_INTELLIGENCE_ENABLED", "REVERSE_ENTRY_V3_ENABLED",
    "REVERSE_ENTRY_V3_SHADOW_EXECUTION_ENABLED", "SPOT_RESEARCH_ENABLED",
    "REPORT_GITHUB_SYNC_ENABLED",
)
JOBS = ("job_scan", "job_monitor", "job_report", "job_daily_analysis",
        "job_health", "job_backup", "job_reverse_lab", "scheduler")
JOB_FIELDS = ("status", "at", "report_date", "missed_jobs", "last_missed_job",
              "github_sync_ok", "github_sync_reason")


def read_flags(root: Path) -> dict:
    # Only emit explicitly whitelisted, non-secret settings.
    selected = {}
    path = root / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in WHITELIST:
                value = value.strip().strip('"').strip("'")
                if key == "RUNTIME_PROFILE":
                    selected[key] = value if value in {"full", "lean"} else "INVALID_VALUE"
                else:
                    selected[key] = value.lower() if value.lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"} else "INVALID_VALUE"
    return selected


def scan_database(path: Path) -> dict:
    if not path.is_file():
        return {"status": "MISSING_AGENT_DB"}
    try:
        # mode=ro includes existing WAL changes and never creates/upgrades tables.
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            quick = db.execute("PRAGMA quick_check(1)").fetchone()
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            out = {
                "status": "OK" if quick and quick[0] == "ok" else "INTEGRITY_WARNING",
                "quick_check": str(quick[0])[:80] if quick else "NO_RESULT",
                "tables_present": {name: name in tables for name in
                    ("scans", "positions", "trades", "battle_positions",
                     "battle_trades", "rei_v2_cohorts", "rei_v3_samples")},
                "jobs": {},
            }
            if "system_state" in tables:
                for key, raw in db.execute(
                    "SELECT key,value FROM system_state WHERE key IN (" +
                    ",".join("?" for _ in JOBS) + ")", JOBS
                ):
                    try:
                        value = json.loads(raw)
                    except (ValueError, TypeError):
                        value = None
                    if isinstance(value, dict):
                        out["jobs"][key] = {k: value[k] for k in JOB_FIELDS if k in value
                                            and isinstance(value[k], (str, int, bool, type(None)))}
            return out
    except (sqlite3.Error, OSError, ValueError):
        return {"status": "SQLITE_READ_ONLY_CHECK_FAILED"}


def inspect(root: Path) -> dict:
    root = root.resolve()
    installed = root / ".agent-updater" / "installed.json"
    version = "UNKNOWN"
    if installed.is_file():
        try:
            item = json.loads(installed.read_text(encoding="utf-8"))
            sha = item.get("sha", "")
            version = sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) else "UNKNOWN"
        except (ValueError, OSError):
            pass
    return {
        "diagnostic_version": "lean-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "installed_sha": version,
        "flags": read_flags(root),
        "database": scan_database(root / "agent.db"),
        "private_data_included": False,
        "notes": "No .env secrets, credentials, trade rows or file paths. SQLite was opened read-only.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("AGENT_KIEM_TRA.json"))
    args = parser.parse_args()
    result = inspect(args.root)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print("AGENT_DIAGNOSTIC_SAVED:", args.output.name)
    print("DATABASE_STATUS:", result["database"]["status"])
    return 0 if result["database"]["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
