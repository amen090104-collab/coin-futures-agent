"""Reverse Research Lab invariants: short-side risk, gaps and preexisting history."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app import storage
from app.battle_storage import init_battle_db
from app.config import settings
from app.reverse_execution import advance_reverse
from app.reverse_research import (
    init_reverse_lab, historic_case_c_diagnostics, reverse_lab_snapshot,
    register_reverse_signals, active_reverse_cases,
)
from app.reverse_runner import monitor_reverse_lab


def prep(tmp_path,monkeypatch,with_battle=True):
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"test.db")
    storage.init_db()
    if with_battle:
        init_battle_db()
    init_reverse_lab()


def short_case():
    return {"id":1,"cohort_id":"short","symbol":"BTCUSDT",
            "variant":"REV_A_FIXED_2R","status":"WAIT_ENTRY",
            "side":"SHORT","score":82.0,"signal_price":100.0,
            "risk_distance":2.0,"cursor_ms":0,"expires_at_ms":900000,
            "entered_at_ms":None,"entry":None,"stop":None,"effective_stop":None,
            "target":None,"remaining":1.0,"realized_r":0,"fees_r":0,
            "high_water":0,"adverse_water":0,"state_json":"{}"}


def bar(m,o,h,l,c):
    return {"open_time":m*60000,"close_time":(m+1)*60000-1,
            "open":o,"high":h,"low":l,"close":c}


def test_short_sl_tp_geometry_and_no_lookahead():
    first=advance_reverse(short_case(),bar(0,100,100.4,99.4,99.8))
    assert first["status"]=="OPEN"
    assert first["stop"]>first["entry"]>first["target"]
    second=advance_reverse(first,bar(1,99.8,100.1,95.5,96.0))
    assert second["status"]=="CLOSED"
    assert second["reason"]=="FIXED_TP_2R"
    assert 1.7<second["net_r"]<2.01


def test_short_same_minute_stop_target_is_stop_first():
    first=advance_reverse(short_case(),bar(0,100,103,95,99))
    assert first["status"]=="CLOSED"
    assert first["reason"]=="STOP_FIRST"
    assert first["net_r"] < -1


def test_daily_missing_trade_db_is_safe(tmp_path,monkeypatch):
    prep(tmp_path,monkeypatch,with_battle=False)
    snap=reverse_lab_snapshot()
    assert snap["cohorts"]==0
    assert historic_case_c_diagnostics()["closed_trades"]==0


def test_monitor_data_gap_censors_not_reports_profit(tmp_path,monkeypatch):
    prep(tmp_path,monkeypatch)
    monkeypatch.setattr(settings,"v44_shadow_enabled",True)
    monkeypatch.setattr(settings,"reverse_lab_enabled",True)
    monkeypatch.setattr(settings,"strategy_battle_enabled",True)
    case={"strategy_id":"REVERSE_RR2","symbol":"SOLUSDT","side":"LONG",
          "position_id":3,"score":81,"entry_price":100,"stop_loss":98,
          "signal_price":100,"entry_context":{
              "cohort_id":"2026-10-14::SOLUSDT","source_signal_side":"SHORT"}}
    scan={"btc_regime":"BEARISH","all":[{"symbol":"SOLUSDT"}]}
    register_reverse_signals([case],scan,observed_ms=100000)
    class GapClient:
        async def klines_1m_between(self,*_):
            return pd.DataFrame([bar(3,100,104,98,101)])
    result=asyncio.run(monitor_reverse_lab(client=GapClient(),now_ms=250000))
    assert result["censored"]==4
    assert active_reverse_cases()==[]
    with storage._connect() as db:
        pos=db.execute("SELECT status,net_r FROM reverse_lab_cases").fetchall()
    assert sum(x["status"]=="CENSORED" for x in pos)==4
    assert sum(x["status"]=="EXPIRED" for x in pos)==1
    assert all(x["net_r"] is None for x in pos)
    assert reverse_lab_snapshot()["paired_case_c"]["pairs"]==0


def test_existing_case_c_historical_diagnostics_no_shadow_backfill(tmp_path,monkeypatch):
    prep(tmp_path,monkeypatch)
    with storage._connect() as db:
        for i,r in enumerate([-1.03,1.93,1.94],start=1):
            db.execute("""INSERT INTO battle_trades(
                position_id,strategy_id,symbol,side,opened_at,closed_at,entry_price,
                exit_price,stop_loss,take_profit,quantity,score,gross_pnl,
                fees,net_pnl,r_multiple,exit_reason,holding_minutes,mfe_r,
                mae_r,reason_text,reason_codes,entry_context)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                i,"REVERSE_RR2","BTCUSDT","LONG",
                "2026-10-12T00:00:00Z",f"2026-10-12T0{i}:00:00Z",
                100,104,98,104,1,86,r*10,1,r*10,r,
                "STOP_LOSS" if i==1 else "TAKE_PROFIT",60,
                1.2 if i==1 else 2.0,.5,"history","[]",
                '{"btc_regime":"BEARISH"}'
            ))
    baseline=historic_case_c_diagnostics()
    assert baseline["closed_trades"]==3
    assert baseline["score"]["85-89"]["closed"]==3
    assert baseline["btc_regime"]["BEARISH"]["closed"]==3
    assert baseline["stops_after_mfe"]["had_reached_plus_1R"]==1
    snap=reverse_lab_snapshot()
    assert snap["cohorts"]==0 and snap["historical_case_c"]["closed_trades"]==3


def test_api_routes_present_without_starting_network(monkeypatch,tmp_path):
    prep(tmp_path,monkeypatch)
    from fastapi.testclient import TestClient
    from app.main import app
    # The legacy reverse API is a FULL-only compatibility route; LEAN
    # intentionally returns 410 and uses the independent research worker.
    monkeypatch.setattr(settings, "runtime_profile", "full")
    client=TestClient(app)
    res=client.get("/research/reverse")
    assert res.status_code==200
    assert res.json()["paper_trading_enabled_by_lab"] is False
    assert any(x.path=="/research/reverse/monitor" for x in app.routes)
    assert any(x.path=="/reports/daily/{day}/reverse" for x in app.routes)
