"""Live history is never changed or sent to GitHub by the separate research bot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

import pytest

BOT = Path(__file__).resolve().parent.parent / "reverse_research_bot"
sys.path.insert(0, str(BOT))
import backup_history
import bot
import engine


def make_history(root: Path, n: int = 160):
    dbpath = root / "agent.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("""CREATE TABLE battle_trades (
            id INTEGER PRIMARY KEY, strategy_id TEXT, symbol TEXT, side TEXT,
            opened_at TEXT, closed_at TEXT, entry_context TEXT,
            net_pnl REAL, r_multiple REAL, mfe_r REAL, mae_r REAL,
            score REAL, exit_reason TEXT)""")
        for i in range(n):
            opening = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i*4)
            finish = opening + timedelta(minutes=45)
            pnl = 10 if i % 3 else -10
            ctx = {"btc_regime": "UP" if i%2 else "DOWN",
                   "rsi_1h": 42.0 + i%20, "atr_pct_1h": 0.4+i%9/10,
                   "volume_ratio_1h": 1.05+i%4/10,
                   "cohort_id": "cohort-"+str(i//2)}
            db.execute("INSERT INTO battle_trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (i+1, ("BASE_RR2","REVERSE_RR2","CASE_E","CASE_F")[i%4],
                        "BTCUSDT", "LONG" if i%2 else "SHORT",
                        opening.isoformat(),finish.isoformat(),json.dumps(ctx),
                        pnl, 1 if pnl>0 else -1, 1.5, 0.9, 76, "TP" if pnl>0 else "SL"))
    return dbpath


def test_full_backup_is_local_consistent_excludes_secrets_and_keeps_legacy(tmp_path):
    db = make_history(tmp_path, 160)
    (tmp_path / ".env").write_text("REPORT_GITHUB_TOKEN=SECRET_TO_NEVER_UPLOAD")
    (tmp_path / "reports" / "old").mkdir(parents=True)
    (tmp_path / "reports" / "old" / "daily-report.json").write_text('{"past":true}')
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / ".env").write_text("PAST_TOKEN=SECRET")
    (tmp_path / "backups" / "historical.db").write_bytes(b"old historical bytes")
    before = db.stat().st_size
    result = backup_history.build_backup(tmp_path)
    assert result["status"] == "VERIFIED_LOCAL_BACKUP"
    assert result["github_uploaded"] is False
    assert db.stat().st_size == before
    with zipfile.ZipFile(result["zip"]) as archived:
        assert "agent.db" in archived.namelist()
        assert "reports/old/daily-report.json" in archived.namelist()
        assert "backups/historical.db" in archived.namelist()
        assert ".env" not in archived.namelist()
        assert "backups/.env" not in archived.namelist()
        assert "SECRET" not in json.dumps(archived.namelist())
    allrows = engine.load_backup(Path(result["zip"]))
    assert len(allrows) == 160


def test_backfill_trains_only_on_past_and_creates_separate_offline_research(tmp_path):
    make_history(tmp_path, 180)
    archive = backup_history.build_backup(tmp_path)
    result = bot.run_cycle(tmp_path)
    assert result["status"] == "RESEARCHED"
    assert result["total"] == 180
    assert result["github_uploaded"] is False and result["real_orders"] == 0
    report = json.loads((tmp_path / "reverse_research_data" / "latest.json").read_text())
    assert report["source_seed_archive"] == Path(archive["zip"]).name
    assert report["total_unique_closed_trades"] == 180
    assert report["real_trade_orders"] == 0
    assert all(x["status"] in {"RESEARCH_ONLY_NOT_DEPLOYED","INSUFFICIENT_INDEPENDENT_DAYS_OR_HISTORY",
                                "TRAIN_OR_VALIDATION_LABELS_NOT_YET_KNOWN", "INSUFFICIENT_VALIDATION"}
               for x in report["long_short_models"].values())
    assert all(x["proven_new_wins"] == 0 for x in report["loss_recovery_hypotheses"])
    assert bot.run_cycle(tmp_path)["status"] == "NO_NEW_CLOSED_TRADES"


def test_too_few_or_late_labels_never_fakes_a_profitable_model():
    examples = [{
        "id": "battle:"+str(i), "strategy_id": "CASE_E", "symbol": "BTCUSDT",
        "side": "LONG", "opened_at": f"2026-01-{1+i//5:02d}T00:00:00+00:00",
        "closed_at": f"2026-09-20T00:00:00+00:00",
        "net_pnl": 100 if i%3 else -100, "r_multiple": 1 if i%3 else -1,
        "feature_values": {k: (80 if k=="score" else "UP" if k=="btc_regime"
                             else 10.0) for k in engine.FEATURES},
    } for i in range(60)]
    output = engine.evaluate_side(examples, "LONG")
    assert output["status"] == "TRAIN_OR_VALIDATION_LABELS_NOT_YET_KNOWN"
    assert output["placed_paper_orders"] == 0
    assert engine.evaluate_side(examples[:10], "LONG")["status"] == "INSUFFICIENT_INDEPENDENT_DAYS_OR_HISTORY"


def test_extra_daily_duplicates_not_counted_as_new_trades(tmp_path):
    db = make_history(tmp_path, 4)
    snapshot = list(engine._db_records(db))
    rows = []
    for x in snapshot:
        rows.append({"id": int(x["id"].split(":")[-1]), "strategy_id": x["strategy_id"],
                     "side":x["side"],"symbol":x["symbol"],"opened_at":x["opened_at"],
                     "closed_at":x["closed_at"],"score":76,"net_pnl":x["net_pnl"],
                     "entry_context":{"rsi_1h": x["feature_values"]["rsi_1h"]}})
    day = "2026-01-01"
    folder = tmp_path / "reports" / day
    folder.mkdir(parents=True)
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"), default=str).encode()).hexdigest()
    (folder / "trade-history.json").write_text(json.dumps({
        "archive_version":"local-trades-v1","report_date":day,"trade_count":len(rows),
        "trades":rows,"sha256":fingerprint}), encoding="utf-8")
    daily, rejected = engine.load_daily(tmp_path / "reports",before_day="2026-10-25")
    assert rejected == []
    assert len(engine.deduplicate(snapshot,daily)) == len(snapshot)


def test_failed_or_missing_initial_backup_does_not_claim_full_learning(tmp_path):
    result = bot.run_cycle(tmp_path)
    assert result["status"] == "NEEDS_FIRST_HISTORY_BACKUP"
    assert not (tmp_path / "reverse_research_data").exists()
