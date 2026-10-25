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



def test_old_reverse_lab_v2_v3_history_is_preserved_not_mislabeled_paper(tmp_path):
    make_history(tmp_path, 80)
    with sqlite3.connect(tmp_path / "agent.db") as db:
        db.execute("CREATE TABLE reverse_lab_cases (variant TEXT,side TEXT,status TEXT,net_r REAL)")
        db.executemany("INSERT INTO reverse_lab_cases VALUES (?,?,?,?)", [
            ("REV_A_FIXED_2R", "LONG", "CLOSED", 1.4),
            ("REV_A_FIXED_2R", "SHORT", "CLOSED", -1.0),
            ("REV_B_WAIT_CONFIRM", "LONG", "CENSORED", None),
        ])
        db.execute("CREATE TABLE rei_v2_cases (status TEXT)")
        db.execute("INSERT INTO rei_v2_cases VALUES ('CLOSED')")
        db.execute("CREATE TABLE rei_v3_samples (status TEXT)")
        db.execute("INSERT INTO rei_v3_samples VALUES ('READY')")
        db.execute("INSERT INTO rei_v3_samples VALUES ('PENDING_RECONSTRUCTION')")
    archive = backup_history.build_backup(tmp_path)
    trades, legacy = engine.load_backup(Path(archive["zip"]), include_legacy=True)
    assert len(trades) == 80
    assert legacy["reverse_lab"]["status_counts"]["CENSORED"] == 1
    assert legacy["reverse_lab"]["variants"]["REV_A_FIXED_2R"]["closed_with_realized_R"] == 2
    assert legacy["reverse_entry_v2_status"]["CLOSED"] == 1
    assert legacy["reverse_entry_v3_status"]["READY"] == 1
    assert legacy["reverse_entry_v3_status"]["PENDING_RECONSTRUCTION"] == 1
    assert bot.run_cycle(tmp_path)["status"] == "RESEARCHED"
    report = json.loads((tmp_path/"reverse_research_data"/"latest.json").read_text())
    assert report["total_unique_closed_trades"] == 80
    assert report["previous_reverse_research_history"]["reverse_lab"]["status_counts"]["CLOSED"] == 2


def test_every_closed_loss_gets_case_side_specific_audit_and_no_future_leakage():
    import loss_investigator
    from datetime import datetime, timedelta, timezone

    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(55):
        opened = start + timedelta(days=i)
        win = i % 3 != 0
        rows.append({
            "id": "battle:" + str(i + 1), "strategy_id": "REVERSE_RR2",
            "symbol": "BTCUSDT", "side": "LONG",
            "opened_at": opened.isoformat(),
            "closed_at": (opened + timedelta(minutes=45)).isoformat(),
            "net_pnl": 10.0 if win else -10.0,
            "r_multiple": 1.0 if win else -1.0,
            "feature_values": {"score": 90.0 if win else 60.0,
                               "rsi_1h": 50.0 if win else 70.0},
        })
    for i in range(12):
        opened = start + timedelta(days=i)
        rows.append({
            "id": "battle:short:" + str(i), "strategy_id": "BASE_RR1",
            "symbol": "ETHUSDT", "side": "SHORT",
            "opened_at": opened.isoformat(), "closed_at": (opened + timedelta(minutes=20)).isoformat(),
            "net_pnl": -5.0, "r_multiple": -1.0, "feature_values": {"score": 77.0},
        })
    report = loss_investigator.investigate_losses(rows)
    assert report["total_closed_trades_considered"] == 67
    assert report["total_losses_investigated"] == 19 + 12
    assert report["by_case_and_side"]["BASE_RR1/SHORT"]["losses"] == 12
    assert report["by_case_and_side"]["REVERSE_RR2/LONG"]["losses"] == 19
    assert report["losses_with_testable_hypotheses"] > 0
    assert report["causal_findings_verified"] == report["real_orders"] == report["paper_orders"] == 0
    assert report["forward_shadow_market_replay_implemented"] is False
    each = {x["id"]: x for x in report["loss_cases"]}
    for loss in each.values():
        assert not loss["cause_proven"]
        assert not loss["shadow_executed"]
        for hypothesis in loss["hypotheses"]:
            assert not hypothesis["is_verified_cause"]
            assert hypothesis["this_loss_would_be_filtered"]
            assert hypothesis["missed_winners_in_prior_data"] >= 0
            assert hypothesis["status"] == "EXPLORATORY_ONLY_REQUIRES_INDEPENDENT_TEST_AND_FORWARD_SHADOW"
    # A trade's explanation cannot change when later outcomes are appended.
    prior_report = loss_investigator.investigate_losses(rows[:32])
    all_ids = {x["id"]: x for x in report["loss_cases"]}
    for old in prior_report["loss_cases"]:
        assert old == all_ids[old["id"]]


def test_loss_investigation_written_separately_and_never_claims_shadow(tmp_path):
    make_history(tmp_path, 120)
    backup_history.build_backup(tmp_path)
    assert bot.run_cycle(tmp_path)["status"] == "RESEARCHED"
    workspace = tmp_path / "reverse_research_data"
    saved = json.loads((workspace / "loss-investigations.json").read_text())
    report = json.loads((workspace / "latest.json").read_text())
    assert saved["total_closed_trades_considered"] == 120
    assert saved["total_losses_investigated"] == 40
    assert len(saved["loss_cases"]) == 40
    assert report["loss_investigation"]["details_file"] == "loss-investigations.json"
    assert report["loss_investigation"]["forward_shadow_market_replay_implemented"] is False


def test_loss_clusters_use_same_condition_winners_and_holdout_before_shadow():
    import loss_clusters
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for d in range(95):
        for k in range(4):
            opened = start + timedelta(days=d, hours=k)
            risk = k < 2
            # Include some winning trades in losing clusters so filtering
            # cannot hide the missed-winner opportunity cost.
            win = ((d % 9) == 0) if risk else ((d % 11) != 0)
            rows.append({
                "id": f"battle:cluster-{d}-{k}", "strategy_id": "REVERSE_RR2",
                "symbol": "BTCUSDT", "side": "SHORT",
                "opened_at": opened.isoformat(),
                "closed_at": (opened + timedelta(minutes=20)).isoformat(),
                "net_pnl": 9.0 if win else -10.0,
                "r_multiple": 0.9 if win else -1.0,
                "feature_values": {
                    "btc_regime": "BULLISH" if risk else "BEARISH",
                    "rsi_1h": 70.0 if risk else 47.0,
                    "atr_pct_1h": 3.6 if risk else 1.1,
                    "score": 76.0 if risk else 85.0,
                    "volume_ratio_1h": 0.7 if risk else 1.7,
                },
            })
    report = loss_clusters.build_loss_clusters(rows)
    assert report["total_valid_closed_trades"] == 380
    assert report["losses_with_group_membership"] == report["total_losses"]
    assert report["losses_without_group_membership"] == 0
    assert report["shadow_executed"] is False
    assert report["time_split"]["status"] == "READY"
    group = next(x for x in report["groups"]
                 if x["case"] == "REVERSE_RR2" and x["side"] == "SHORT"
                 and x["family"] == "btc_regime+rsi_1h"
                 and x["buckets"] == {"btc_regime": "BULLISH", "rsi_1h": "HIGH_GT_60"})
    assert group["losses"] > 100 and group["wins"] > 0
    assert len(group["loss_ids"]) == group["losses"]
    assert len(group["win_ids"]) == group["wins"]
    candidate = next(c for c in report["candidates"] if c["group_id"] == group["id"])
    assert candidate["train"]["cluster"]["losses"] > 40
    assert candidate["validation"]["cluster"]["losses"] > 0
    assert candidate["holdout"]["cluster"]["losses"] > 0
    assert candidate["status"] == "AWAITING_PROSPECTIVE_SHADOW_SIGNAL_FEED"
    assert candidate["holdout_supported"] is True
    assert candidate["baseline_missed_winners_if_filtered_on_holdout"] > 0
    assert candidate["shadow_executed"] is False
    assert candidate["may_modify_trading_bot"] is False


def test_loss_clusters_include_all_cases_and_explicit_unknown_buckets():
    import loss_clusters
    rows = []
    for i, (case, side) in enumerate([("BASE_RR1", "LONG"),
                                      ("CASE_E", "SHORT"),
                                      ("CASE_F", "LONG"),
                                      ("REVERSE_RR2", "SHORT")]):
        rows.append({
            "id": f"battle:unknown-{i}", "strategy_id": case,
            "symbol": "ETHUSDT", "side": side,
            "opened_at": f"2026-01-0{i+1}T00:00:00+00:00",
            "closed_at": f"2026-01-0{i+1}T00:30:00+00:00",
            "net_pnl": -10.0, "r_multiple": -1.0, "feature_values": {},
        })
    report = loss_clusters.build_loss_clusters(rows)
    assert report["total_losses"] == 4
    assert report["losses_with_group_membership"] == 4
    assert len(report["groups"]) == 12
    assert all(x["data_quality"] == "MISSING_ENTRY_FEATURES" for x in report["groups"])
    assert report["time_split"]["status"] == "INSUFFICIENT_INDEPENDENT_DAYS"
    assert report["candidates"] == []
    assert report["real_orders"] == report["paper_orders"] == 0


def test_group_report_is_written_and_shadow_proposals_do_not_execute(tmp_path):
    make_history(tmp_path, 160)
    backup_history.build_backup(tmp_path)
    assert bot.run_cycle(tmp_path)["status"] == "RESEARCHED"
    workspace = tmp_path / "reverse_research_data"
    report = json.loads((workspace / "latest.json").read_text())
    groups = json.loads((workspace / "loss-clusters.json").read_text())
    proposals = json.loads((workspace / "shadow-candidate-proposals.json").read_text())
    assert report["loss_clusters"]["details_file"] == "loss-clusters.json"
    assert report["loss_clusters"]["group_count"] == len(groups["groups"])
    assert proposals["requires_point_in_time_signal_feed"] is True
    assert proposals["shadow_executed"] is False
    assert groups["total_valid_closed_trades"] == 160
    assert groups["real_orders"] == groups["paper_orders"] == 0


def test_daily_brief_uses_only_completed_local_date_and_marks_holdout_not_shadow(tmp_path):
    import daily_report
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    examples = [
        {"id": "1", "strategy_id": "REVERSE_RR2", "side": "LONG",
         "opened_at": "2026-10-24T08:00:00+07:00",
         "closed_at": "2026-10-24T23:58:00+07:00",
         "net_pnl": -5, "r_multiple": -1},
        {"id": "2", "strategy_id": "REVERSE_RR1", "side": "SHORT",
         "opened_at": "2026-10-24T20:00:00+07:00",
         "closed_at": "2026-10-25T00:01:00+07:00",
         "net_pnl": 5, "r_multiple": 1},
        {"id": "3", "strategy_id": "BASE_RR1", "side": "LONG",
         "opened_at": "2026-10-24T02:00:00+00:00",
         "closed_at": "2026-10-24T16:59:00+00:00",
         "net_pnl": 3, "r_multiple": 1},
        {"id": "4", "strategy_id": "BASE_RR1", "side": "SHORT",
         "opened_at": "2026-10-24T19:00:00+00:00",
         "closed_at": "2026-10-24T23:59:00",
         "net_pnl": -2, "r_multiple": -1},
    ]
    research = {
        "data_hash": "immutable-hash-1", "per_case_win_loss": {},
        "long_short_models": {
            "LONG": {"status": "RESEARCH_ONLY_NOT_DEPLOYED", "test": 12,
                     "out_of_sample_test": {"selected": 0, "avg_realized_r": None},
                     "out_of_sample_baseline": {"avg_realized_r": -0.5}},
            "SHORT": {"status": "RESEARCH_ONLY_NOT_DEPLOYED", "test": 12,
                      "out_of_sample_test": {"selected": 4, "avg_realized_r": 0.1},
                      "out_of_sample_baseline": {"avg_realized_r": 0.5}},
        },
        "loss_clusters": {"group_count": 2, "candidate_count": 1,
                          "holdout_supported_shadow_candidates": 1},
        "automated_experiments": {"status": "HOLDOUT_NOT_CONVINCING",
                                  "selected_by_validation": "btc_against_trade_side"},
        "_daily_candidate_details": [{
            "hypothesis_id": "<script>alert(1)</script>", "holdout_supported": True,
            "status": "AWAITING_PROSPECTIVE_SHADOW_SIGNAL_FEED",
            "rule": {"case": "REVERSE_RR1", "side": "SHORT"},
            "holdout": {"cluster": {"trades": 16, "mean_R": -0.4},
                        "other_known_conditions": {"mean_R": 0.2}},
            "baseline_missed_winners_if_filtered_on_holdout": 3,
        }],
    }
    date1 = datetime(2026, 10, 25, 8, 0, tzinfo=tz)
    output = daily_report.write_daily_report(tmp_path, examples, research, now=date1)
    assert output["status"] == "DAILY_REPORT_WRITTEN"
    doc = json.loads(Path(output["json"]).read_text(encoding="utf-8"))
    assert doc["report_date"] == "2026-10-24"
    assert doc["closed_yesterday"] == 2
    assert doc["daily_by_side"]["LONG"]["closed"] == 2
    assert doc["daily_by_side"]["SHORT"]["closed"] == 0
    assert doc["missing_close_timezone_or_timestamp"] == 1
    assert doc["forward_shadow_verification"]["verified_strategies"] == 0
    assert doc["historical_holdout_candidates"][0]["holdout_missed_winners_if_avoided"] == 3
    assert doc["historical_holdout_candidates"][0]["evidence_level"] == "HISTORICAL_HOLDOUT_ONLY_NOT_SHADOW"
    html = Path(output["html"]).read_text(encoding="utf-8")
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Chua co bang chung Shadow hop le" in html
    assert daily_report.write_daily_report(tmp_path, examples, research, now=date1)["status"] == "DAILY_REPORT_ALREADY_CURRENT"
    # Next calendar date must still create its own report with unchanged data.
    date2 = datetime(2026, 10, 26, 8, 0, tzinfo=tz)
    next_doc = daily_report.write_daily_report(tmp_path, examples, research, now=date2)
    assert next_doc["status"] == "DAILY_REPORT_WRITTEN"
    assert json.loads(Path(next_doc["json"]).read_text())["report_date"] == "2026-10-25"
    assert json.loads(Path(next_doc["json"]).read_text())["closed_yesterday"] == 1


def test_research_cycle_writes_daily_report_even_if_data_unchanged(tmp_path):
    make_history(tmp_path, 160)
    backup_history.build_backup(tmp_path)
    first = bot.run_cycle(tmp_path)
    assert first["status"] == "RESEARCHED"
    daily = first["daily_report"]
    assert daily["status"] == "DAILY_REPORT_WRITTEN"
    assert Path(daily["html"]).is_file()
    assert Path(daily["json"]).is_file()
    assert Path(daily["html"]).with_suffix(".md").is_file()
    again = bot.run_cycle(tmp_path)
    assert again["status"] == "NO_NEW_CLOSED_TRADES"
    assert again["daily_report"]["status"] == "DAILY_REPORT_ALREADY_CURRENT"
    assert again["real_orders"] == 0


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



def test_autonomous_hypothesis_lab_is_bounded_and_never_alters_paper(tmp_path):
    import experiment_lab
    make_history(tmp_path, 480)
    records = list(engine._db_records(tmp_path / "agent.db"))
    report = experiment_lab.run_experiments(records)
    assert report["protocol"] == experiment_lab.PROTOCOL
    assert report["experiment_count"] == len(experiment_lab.HYPOTHESES) == 10
    assert report["real_orders"] == report["paper_orders"] == 0
    assert report["auto_changed_trading_configuration"] is False
    assert report["status"] in {
        "NO_VALIDATED_CANDIDATE", "HOLDOUT_NOT_CONVINCING",
        "PROVISIONAL_REQUIRES_FORWARD_OBSERVATION"}
    lock = experiment_lab.frozen_record(report, records)
    if lock:
        assert lock["must_get_manual_approval"] is True
        assert lock["can_trade"] is False
        assert all(x["opened_at"] <= lock["frozen_after_opened_at"] for x in records)
        old = experiment_lab.monitor_frozen_candidate(records, lock)
        assert old["status"] == "FORWARD_ACCUMULATING"
        assert old["new_complete_trades"] == 0
        assert old["auto_changed_trading_configuration"] is False


def test_day_splits_never_mix_same_signal_day_or_future_labels(tmp_path):
    import experiment_lab
    make_history(tmp_path, 480)
    observations = list(engine._db_records(tmp_path / "agent.db"))
    folds, meta = experiment_lab._folds(observations)
    assert meta["status"] == "READY"
    train, validation, test = folds
    ds = [{x["opened_at"][:10] for x in part} for part in (train,validation,test)]
    assert ds[0].isdisjoint(ds[1])
    assert ds[0].isdisjoint(ds[2])
    assert ds[1].isdisjoint(ds[2])
    assert max(x["closed_at"] for x in train) <= min(x["opened_at"] for x in validation)
    assert max(x["closed_at"] for x in validation) <= min(x["opened_at"] for x in test)


def test_experiment_lock_survives_new_data_without_retuning(tmp_path):
    import experiment_lab
    make_history(tmp_path, 240)
    root = tmp_path
    history = backup_history.build_backup(root)
    result = bot.run_cycle(root)
    assert result["status"] == "RESEARCHED"
    first = json.loads((root/"reverse_research_data"/"latest.json").read_text())
    auto = first["automated_experiments"]
    assert auto["real_orders"] == 0
    assert auto["auto_changed_trading_configuration"] is False
    frozen = root/"reverse_research_data"/"experiment_protocol.json"
    if auto.get("status") == "PROVISIONAL_REQUIRES_FORWARD_OBSERVATION":
        assert frozen.is_file()
        old = json.loads(frozen.read_text())
        assert old["can_trade"] is False
        assert bot.run_cycle(root)["status"] == "NO_NEW_CLOSED_TRADES"
        assert json.loads(frozen.read_text()) == old


def test_failed_holdout_does_not_freeze_and_old_failed_lock_is_retired(tmp_path):
    import experiment_lab
    make_history(tmp_path, 240)
    records = list(engine._db_records(tmp_path / "agent.db"))
    failing = {"status": "HOLDOUT_NOT_CONVINCING",
               "selected_by_validation": "btc_against_trade_side"}
    assert experiment_lab.frozen_record(failing, records) is None
    archive = backup_history.build_backup(tmp_path)
    workspace = tmp_path / "reverse_research_data"
    workspace.mkdir(exist_ok=True)
    obsolete = {"protocol": experiment_lab.PROTOCOL,
                "id": "btc_against_trade_side",
                "first_holdout_status": "HOLDOUT_NOT_CONVINCING",
                "frozen_after_opened_at": "2026-01-31T00:00:00+00:00",
                "can_trade": False}
    (workspace / "experiment_protocol.json").write_text(json.dumps(obsolete))
    result = bot.run_cycle(tmp_path)
    assert result["status"] == "RESEARCHED"
    doc = json.loads((workspace / "latest.json").read_text())
    assert doc["automated_experiments"]["status"] == "HISTORICAL_CANDIDATE_REJECTED"
    assert doc["automated_experiments"]["can_trade"] is False
    assert "forward" not in doc["automated_experiments"]
    assert json.loads((workspace / "experiment_protocol.json").read_text()) == obsolete

def test_failed_or_missing_initial_backup_does_not_claim_full_learning(tmp_path):
    result = bot.run_cycle(tmp_path)
    assert result["status"] == "NEEDS_FIRST_HISTORY_BACKUP"
    assert not (tmp_path / "reverse_research_data").exists()
