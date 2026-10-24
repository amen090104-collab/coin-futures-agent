"""V5.1.1 lean acceptance: A-F Paper and Reverse research, no chart/entry UI."""
import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException

from app import main, battle, report_files, rei_v3, reverse_runner, reverse_intelligence_store, storage, strategy_cases
from app.config import settings
from app.dashboard_lean import DASHBOARD_HTML_LEAN


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    monkeypatch.setattr(settings, "strategy_battle_enabled", True)
    monkeypatch.setattr(settings, "reverse_lab_enabled", True)
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "agent.db")
    storage.init_db()
    strategy_cases.init_strategy_cases()
    with storage._connect() as db:
        template = db.execute("SELECT * FROM strategy_cases WHERE strategy_id='BASE_RR2'").fetchone()
        cols = list(template.keys())
        sql = "INSERT INTO strategy_cases("+",".join(cols)+") VALUES ("+",".join("?" for _ in cols)+")"
        for sid, short in (("CASE_E", "E"), ("CASE_F", "F"), ("BASE_75_79", "BASE_7")):
            obj = dict(template)
            obj.update(strategy_id=sid, short_name=short, name=sid)
            db.execute(sql, [obj[key] for key in cols])
        db.commit()
    return tmp_path


def test_lean_only_six_cases_without_erasing_other_case(isolated, monkeypatch):
    cases = strategy_cases.list_strategy_cases(False)
    assert [c["strategy_id"] for c in cases] == list(strategy_cases.LEAN_CASE_IDS)
    assert len(strategy_cases.active_strategy_cases()) == 6
    assert "BASE_75_79" in [x["strategy_id"] for x in strategy_cases.list_strategy_cases(True)]
    monkeypatch.setattr(settings, "runtime_profile", "full")
    assert "BASE_75_79" in [x["strategy_id"] for x in strategy_cases.list_strategy_cases(False)]


def test_reverse_lab_independent_from_old_v44_in_lean(isolated, monkeypatch):
    monkeypatch.setattr(settings, "v44_shadow_enabled", False)
    assert reverse_runner.reverse_lab_active() is True
    monkeypatch.setattr(settings, "runtime_profile", "full")
    assert reverse_runner.reverse_lab_active() is False
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    assert reverse_runner.reverse_lab_active() is True


def test_v2_v3_can_research_without_old_v44_and_skip_new_entries(isolated, monkeypatch):
    monkeypatch.setattr(settings, "v44_shadow_enabled", False)
    monkeypatch.setattr(settings, "reverse_entry_intelligence_enabled", True)
    monkeypatch.setattr(settings, "reverse_entry_v3_enabled", True)
    assert reverse_intelligence_store.enabled() is True
    assert rei_v3.enabled() is True
    monkeypatch.setattr(rei_v3.storage, "_connect", lambda: pytest.fail("V3 lean must not make new prediction on scan"))
    assert asyncio.run(rei_v3.collect()) is None


def test_legacy_extra_case_existing_position_is_still_monitored(isolated, monkeypatch):
    import pandas as pd
    old = {"id": 99, "strategy_id": "BASE_75_79", "symbol": "BTCUSDT", "side": "LONG"}
    monkeypatch.setattr(battle, "battle_open_positions", lambda *args: [old])
    class FakeClient:
        async def klines(self, *args):
            return pd.DataFrame([{"open": 100, "close": 100}, {"open": 100, "close": 101}])
        async def close(self):
            pass
    monkeypatch.setattr(battle, "BinanceClient", FakeClient)
    monkeypatch.setattr(battle, "evaluate_position_candle",
                        lambda position, candle: {
                            "favorable": 101, "adverse": 99, "last": 100,
                            "closed_at": "2026-10-25T00:00:00Z", "exit_reason": None
                        })
    update = Mock()
    monkeypatch.setattr(battle, "update_battle_position_excursion", update)
    monkeypatch.setattr(battle, "record_stop_change", Mock())
    monkeypatch.setattr(battle, "record_milestones", Mock())
    assert asyncio.run(battle.monitor_battle_positions()) == []
    assert update.call_args.args[0] == 99


def test_daily_bundle_requires_reverse_but_not_obsolete_v44(isolated, monkeypatch):
    monkeypatch.setattr(settings, "v44_shadow_enabled", True)
    monkeypatch.setattr(report_files, "artifact_valid", lambda *a, **kw: True)
    monkeypatch.setattr(report_files, "read_snapshot", lambda day, stem: {
        "created_at": "same", "source_report_created_at": "same"
    })
    status = report_files.bundle_status("2026-10-25")
    assert "reverse-lab.json" in status["required"]
    assert "v44-research.json" not in status["required"]
    assert status["complete"] is True


def test_dashboard_has_no_candle_replay_or_exit_simulator(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    markup = asyncio.run(main.dashboard())
    assert markup == DASHBOARD_HTML_LEAN
    assert "coinChart" not in markup
    assert "tradeChart" not in markup
    assert "TradeCharts" not in markup
    assert "Exit Simulator" not in markup
    assert "Case Paper" in markup
    for endpoint in (main.get_trade_detail(1, "15m"),
                     main.get_coin_detail("BTCUSDT", "15m", 10),
                     main.simulate_trade_exit_api(1)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(endpoint)
        assert error.value.status_code == 410


def test_lean_scanner_still_dispatches_reverse_without_v44_worker(isolated, monkeypatch):
    monkeypatch.setattr(settings, "v44_shadow_enabled", False)
    monkeypatch.setattr(main, "system_overview", lambda: {"network": {"status": "ONLINE"}})
    monkeypatch.setattr(main, "run_scan", AsyncMock(return_value=(
        {"created_at": "2026-10-25T00:00:00Z", "symbols_scanned": 1, "all": []}, {}
    )))
    monkeypatch.setattr(main, "open_battle_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "reverse_scan_job", AsyncMock(return_value={"status": "SHADOW_ONLY"}))
    monkeypatch.setattr(main, "v44_scan_job", AsyncMock())
    monkeypatch.setattr(main, "send_telegram", AsyncMock())
    monkeypatch.setattr(main, "save_scan", lambda *a: None)
    monkeypatch.setattr(main, "_mark_job", lambda *a, **k: None)
    monkeypatch.setattr(main, "rei_enabled", lambda: False)
    async def run():
        await main.scan_job()
        await asyncio.sleep(0.01)
    asyncio.run(run())
    main.reverse_scan_job.assert_awaited_once()
    main.v44_scan_job.assert_not_awaited()


def test_lean_api_only_exposes_paper_without_large_research(monkeypatch):
    monkeypatch.setattr(settings, "runtime_profile", "lean")
    monkeypatch.setattr(settings, "strategy_battle_enabled", True)
    monkeypatch.setattr(main, "build_strategy_battle_dashboard", lambda: {
        "strategies": [{"strategy_id": "CASE_E", "name": "Case E", "short_name": "E", "analytics": {}}],
        "trades": [], "open_positions": []
    })
    monkeypatch.setattr(main, "battle_open_positions", lambda: [
        {"strategy_id": "BASE_75_79"}, {"strategy_id": "CASE_E"}
    ])
    monkeypatch.setattr(main, "latest_scan", lambda: {})
    monkeypatch.setattr(main, "latest_daily_reports", lambda _: [])
    monkeypatch.setattr(main, "system_overview", lambda: {})
    monkeypatch.setattr(main, "version_info", lambda: {"version": "5.1.1"})
    result = asyncio.run(main.lean_dashboard_data())
    assert result["legacy_open_positions"] == 1
    assert result["cases"][0]["strategy_id"] == "CASE_E"
    assert "CASE_F" in result["missing_case_ids"]
    assert "v44_research" not in result and "spot_research" not in result
