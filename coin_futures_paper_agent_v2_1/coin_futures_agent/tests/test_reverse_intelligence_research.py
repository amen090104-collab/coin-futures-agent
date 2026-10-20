"""Offline parsing, report integration and dashboard behavior on synthetic fixtures."""
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from app.reverse_intelligence_research import analyze_reports, markdown
from app.reverse_intelligence import walk_forward
from app import storage
from app.config import settings
from app.reverse_research import init_reverse_lab, write_reverse_lab_report
from app.v44_learning import write_research_report
from app.battle_storage import init_battle_db


def write_daily(root, day, *, trade_id=1):
    folder = root / day
    folder.mkdir(parents=True)
    doc = {"report_date": day, "created_at": day + "T23:00:00+00:00", "strategies": [{
        "strategy_id": "REVERSE_RR2", "direction_mode": "REVERSE", "cumulative_closed": 5,
        "trade_details": [{"trade_id": trade_id, "side": "LONG", "symbol": "XUSDT", "score": 80.,
            "opened_at": "2026-10-10T10:00:00+00:00", "closed_at": "2026-10-10T11:00:00+00:00",
            "r_multiple": 1.8, "btc_regime": "BEARISH", "mfe_r": 2., "mae_r": -.1,
            "holding_minutes": 60., "entry_thesis": {"reason_codes": ["RSI_SHORT_ZONE"]},
            "exit_reason": "TAKE_PROFIT"}]}]}
    (folder / "daily-report.json").write_text(json.dumps(doc))


def test_reports_are_deduplicated_and_do_not_become_training_labels(tmp_path):
    write_daily(tmp_path, "2026-10-10")
    write_daily(tmp_path, "2026-10-11")
    result = analyze_reports(tmp_path)
    assert result["issues"]["duplicate_trade_export"] == 1
    assert result["exported_by_strategy"]["REVERSE_RR2"]["n"] == 1
    assert result["missing_details_vs_cumulative"]["REVERSE_RR2"] == 4
    assert result["missing_numeric_features_case_c"]["rsi_1h"] == 1
    assert result["training_eligible_from_reports"] == 0
    assert result["conditions_by_source_side"]["SHORT"]["reverse_side"] == "LONG"
    assert all(len(source["sha256"]) == 64 for source in result["sources"])


def test_missing_reports_fail_instead_of_generating_a_dataset(tmp_path):
    with pytest.raises(ValueError, match="Không tìm thấy"):
        analyze_reports(tmp_path)


def test_missing_reason_code_is_unknown_not_evidence_of_absence(tmp_path):
    write_daily(tmp_path, "2026-10-10")
    path = tmp_path / "2026-10-10/daily-report.json"
    doc = json.loads(path.read_text())
    prototype = doc["strategies"][0]["trade_details"][0]
    rows = []
    for i in range(17):
        rows.append({**prototype, "trade_id": i,
                     "entry_thesis": {"reason_codes": ["RSI_SHORT_ZONE"]} if i < 8 else {"reason_codes": []} if i < 16 else {},
                     "r_multiple": 1.8 if i < 8 else -1.1 if i < 16 else 99.})
    doc["strategies"][0]["trade_details"] = rows
    path.write_text(json.dumps(doc))
    group = analyze_reports(tmp_path)["conditions_by_source_side"]["SHORT"]
    assert group["unknown_reason_code_rows"] == 1
    contrast = group["reason_code_contrasts"][0]
    assert contrast["absent"]["n"] == 8 and contrast["absent"]["expectancy_r"] == -1.1


def test_report_date_mismatch_is_quarantined(tmp_path):
    write_daily(tmp_path, "2026-10-10")
    path = tmp_path / "2026-10-10/daily-report.json"
    doc = json.loads(path.read_text()); doc["report_date"] = "wrong"
    path.write_text(json.dumps(doc))
    result = analyze_reports(tmp_path)
    assert result["issues"]["report_date_mismatch"] == 1
    assert not result["exported_by_strategy"]


def test_markdown_comparison_is_a_contiguous_table(tmp_path):
    write_daily(tmp_path, "2026-10-10")
    text = markdown({"historical": analyze_reports(tmp_path), "walk_forward": walk_forward([])})
    assert "| Drawdown serial R |\n|---" in text
    assert "INSUFFICIENT_DATA" in text


@pytest.mark.parametrize("writer,name", [(write_research_report, "v44-research"),
                                        (write_reverse_lab_report, "reverse-lab")])
def test_both_labs_include_v2_summary_without_fabricated_scores(tmp_path, monkeypatch, writer, name):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", False)
    storage.init_db(); init_battle_db(); init_reverse_lab()
    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    document = writer(today, tmp_path / "reports")
    summary = document["reverse_entry_intelligence"]
    assert not summary["enabled"] and summary["status"] == "INSUFFICIENT_DATA"
    text = (tmp_path / "reports" / today / f"{name}.md").read_text()
    assert "Reverse Entry Intelligence V2" in text
    assert not summary["out_of_sample_validated"]


def test_dashboard_distinguishes_absent_score_from_zero_and_escapes_text():
    path = Path(__file__).resolve().parents[1] / "app/dashboard_v43.py"
    source = path.read_text()
    function = source[source.index("function renderReverseEntry(){"):source.index("function renderReverseLab(){")]
    harness = r'''
const assert=require('assert');
const nodes={}; const document={getElementById:id=>nodes[id]||(nodes[id]={})};
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
let D={reverse_entry_intelligence:{enabled:false,recent:[{symbol:'<script>',source_side:'LONG',observed_at_ms:1000,
prediction:{score:null,action:'NO_TRADE',recommendation:'NO TRADE',reasons:['<unsafe>']}}],timeline:[]}};
''' + function + r'''
renderReverseEntry();
assert(nodes.reverseEntrySignals.innerHTML.includes('—'));
assert(!nodes.reverseEntrySignals.innerHTML.includes('<script>'));
D.reverse_entry_intelligence.recent[0].prediction={score:0,action:'WAIT_CONFIRMATION',recommendation:'WAIT',reasons:[]};
renderReverseEntry();
assert(nodes.reverseEntrySignals.innerHTML.includes('0.0'));
assert(nodes.reverseEntrySignals.innerHTML.includes('WAIT'));
'''
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
