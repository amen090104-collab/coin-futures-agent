"""Reverse Lab integration and forward-1m acceptance tests.

Uses isolated temporary SQLite and fake market-data clients. No network,
Binance order placement, paper account reset or access to user's agent.db.
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app import storage
from app.battle_storage import init_battle_db
from app.config import settings
from app.reverse_execution import advance_reverse, CandleGap, VARIANTS
from app.reverse_research import (
    init_reverse_lab, register_reverse_signals, active_reverse_cases,
    persist_reverse_case, reverse_lab_snapshot, write_reverse_lab_report,
)
from app.reverse_runner import monitor_reverse_lab


def setup_db(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"isolated.db")
    storage.init_db()
    init_battle_db()
    init_reverse_lab()


def signal(symbol="BTCUSDT",cohort="scan::BTCUSDT",score=87,case_id=42,side="LONG"):
    source="SHORT" if side=="LONG" else "LONG"
    return {"strategy_id":"REVERSE_RR2","symbol":symbol,"side":side,
            "score":score,"position_id":case_id,
            "signal_price":100.0,"entry_price":100.0,
            "stop_loss":98.0 if side=="LONG" else 102.0,
            "entry_context":{"cohort_id":cohort,"source_signal_side":source}}


def scan(symbol="BTCUSDT"):
    return {"created_at":"2026-10-14T00:00:00Z","btc_regime":"NEUTRAL",
            "all":[{"symbol":symbol,"rsi_1h":65,"distance_ema20_atr":2.5,
                    "volume_ratio_1h":1.2,"atr_pct_1h":2.0,
                    "funding_rate":.0001,"oi_change_pct":2.0}]}


def candle(idx,o,h,l,c):
    return {"open_time":idx*60000,"close_time":(idx+1)*60000-1,
            "open":o,"high":h,"low":l,"close":c}


def state(variant="REV_A_FIXED_2R",status="WAIT_ENTRY",idx=0,score=87):
    return {"id":1,"cohort_id":"c1","symbol":"BTCUSDT","variant":variant,
            "side":"LONG","score":score,"signal_price":100.0,
            "risk_distance":2.0,"status":status,"cursor_ms":idx*60000,
            "expires_at_ms":3600000,"entered_at_ms":None,
            "entry":None,"stop":None,"effective_stop":None,"target":None,
            "remaining":1.0,"realized_r":0.0,"fees_r":0.0,"net_r":None,
            "high_water":0.0,"adverse_water":0.0,"state_json":"{}"}


def test_register_only_actual_case_c_and_same_cohort(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    opened=[signal(),{**signal(cohort="other",case_id=43),"strategy_id":"BASE_RR2"}]
    first=register_reverse_signals(opened,scan(),observed_ms=100_000)
    again=register_reverse_signals(opened,scan(),observed_ms=100_000)
    assert first["registered"]==1 and again["registered"]==0
    positions=active_reverse_cases()
    assert len(positions)==4
    assert {x["variant"] for x in positions}==set(VARIANTS)-{"REV_E_PATTERN_2R"}
    with storage._connect() as db:
        skipped=db.execute("SELECT status,reason,net_r FROM reverse_lab_cases WHERE variant='REV_E_PATTERN_2R'").fetchone()
        assert skipped["status"]=="EXPIRED" and skipped["net_r"] is None
        assert skipped["reason"].startswith("PATTERN_INSUFFICIENT")
    assert all(x["cursor_ms"]==120_000 for x in positions)
    assert next(x for x in positions if x["variant"]=="REV_B_CONFIRMED_2R")["status"]=="WAIT_CONFIRM"
    assert next(x for x in positions if x["variant"]=="REV_D_ADAPTIVE")["status"]=="WAIT_ENTRY"
    with storage._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM battle_trades").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM battle_positions").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM battle_account_events").fetchone()[0]==0


def test_immediate_variants_share_same_fill_and_different_exit():
    a=advance_reverse(state("REV_A_FIXED_2R"),candle(0,100,102.2,99.6,101))
    c=advance_reverse(state("REV_C_PARTIAL_RUNNER"),candle(0,100,102.2,99.6,101))
    assert a["status"]=="OPEN" and a["remaining"]==1
    assert c["status"]=="OPEN" and c["remaining"]==0.5
    assert a["entered_at_ms"]==c["entered_at_ms"]==0
    assert a["entry"]==c["entry"] and a["fees_r"]>0
    assert c["effective_stop"]>=c["stop"]
    a2=advance_reverse(a,candle(1,101,104.7,100.8,104))
    c2=advance_reverse(c,candle(1,101,104.7,100.8,104))
    assert a2["status"]=="CLOSED"
    assert a2["reason"]=="FIXED_TP_2R"
    assert c2["status"]=="OPEN" and c2["effective_stop"]>=c["effective_stop"]
    c3=advance_reverse(c2,candle(2,104,104.2,101.4,102))
    assert c3["status"]=="CLOSED"
    assert c3["reason"]=="STOP_FIRST"  # candle also touched 2R; conservative loss-first
    assert c3["net_r"] is not None and c3["fees_r"]>c["fees_r"]


def test_confirmation_requires_two_closed_candles_and_next_open():
    b=state("REV_B_CONFIRMED_2R",status="WAIT_CONFIRM")
    b1=advance_reverse(b,candle(0,100,100.35,99.9,100.2))
    assert b1["status"]=="WAIT_CONFIRM" and b1["entered_at_ms"] is None
    b2=advance_reverse(b1,candle(1,100.2,100.6,100.1,100.45))
    assert b2["status"]=="WAIT_ENTRY" and b2["entered_at_ms"] is None
    assert b2["cursor_ms"]==120000
    b3=advance_reverse(b2,candle(2,100.45,100.6,100.2,100.5))
    assert b3["status"]=="OPEN"
    assert b3["entered_at_ms"]==120000


def test_adaptive_score_rule_is_frozen_at_signal():
    high=advance_reverse(state("REV_D_ADAPTIVE",score=88),
                         candle(0,100,100.8,99.7,100.6))
    assert high["status"]=="OPEN" and high["entered_at_ms"]==0
    low=advance_reverse(state("REV_D_ADAPTIVE",score=78,status="WAIT_CONFIRM"),
                        candle(0,100,100.4,99.8,100.3))
    assert low["status"]=="WAIT_ENTRY" and low["entered_at_ms"] is None


def test_stop_first_and_gap_slippage_never_inflate_result():
    a=advance_reverse(state(),candle(0,100,105,97,100))
    assert a["status"]=="CLOSED" and a["reason"]=="STOP_FIRST"
    assert a["net_r"] < -1.0
    p=advance_reverse(state(),candle(0,100,100.8,99.7,100.2))
    gap=advance_reverse(p,candle(1,96,97,95,96.5))
    assert gap["reason"]=="STOP_GAP"
    assert gap["net_r"] < -1.5


def test_no_lookahead_no_skipped_1m_data_and_expiry():
    with pytest.raises(CandleGap):
        advance_reverse(state(),candle(1,100,101,99,100.5))
    b=state("REV_B_CONFIRMED_2R",status="WAIT_CONFIRM",idx=70)
    expired=advance_reverse(b,candle(70,100,101,99,100.2))
    assert expired["status"]=="EXPIRED"
    assert expired["net_r"] is None


def test_monitor_uses_market_data_once_and_is_idempotent(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    monkeypatch.setattr(settings,"v44_shadow_enabled",True)
    monkeypatch.setattr(settings,"reverse_lab_enabled",True)
    monkeypatch.setattr(settings,"strategy_battle_enabled",True)
    register_reverse_signals([signal()],scan(),observed_ms=100000)
    class Fake:
        def __init__(self):
            self.calls=0
        async def klines_1m_between(self,sym,start_ms,end_ms):
            self.calls+=1
            assert sym=="BTCUSDT"
            return pd.DataFrame([candle(2,100,101,99.5,100.5),
                                 candle(3,100.5,101.5,100.4,101.2)])
    fake=Fake()
    result=asyncio.run(monitor_reverse_lab(client=fake,now_ms=245000))
    assert result["status"]=="SHADOW_ONLY" and result["entries"]>=2
    first=active_reverse_cases()
    assert all(r["cursor_ms"]==240000 for r in first)
    again=asyncio.run(monitor_reverse_lab(client=fake,now_ms=245000))
    second=active_reverse_cases()
    assert second==first and again.get("updated",0)==0


def test_expired_wait_counts_missed_winner_and_avoided_loss(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    register_reverse_signals([signal()],scan(),observed_ms=100000)
    with storage._connect() as db:
        db.execute("""UPDATE reverse_lab_cases SET status='CLOSED',net_r=1.93,
                    reason='FIXED_TP_2R' WHERE variant='REV_A_FIXED_2R'""")
        db.execute("""UPDATE reverse_lab_cases SET status='EXPIRED',reason='TIMEOUT'
                    WHERE variant='REV_B_CONFIRMED_2R'""")
    s=reverse_lab_snapshot()
    assert s["missed_opportunities"]["REV_B_CONFIRMED_2R"]["missed_winners"]==1
    assert s["paired_vs_control"]["REV_B_CONFIRMED_2R"]["delta_r_mean"]==-1.93
    assert s["paired_vs_control"]["REV_B_CONFIRMED_2R"]["status"]=="INSUFFICIENT_DATA"
    with storage._connect() as db:
        db.execute("""UPDATE reverse_lab_cases SET net_r=-1.06
                    WHERE variant='REV_A_FIXED_2R'""")
    s=reverse_lab_snapshot()
    assert s["missed_opportunities"]["REV_B_CONFIRMED_2R"]["avoided_losses"]==1


def test_case_c_reference_join_exact_position_and_side(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    register_reverse_signals([signal()],scan(),observed_ms=100000)
    with storage._connect() as db:
        db.execute("""INSERT INTO battle_trades(
            position_id,strategy_id,symbol,side,opened_at,closed_at,entry_price,
            exit_price,stop_loss,take_profit,quantity,score,gross_pnl,fees,
            net_pnl,r_multiple,exit_reason,holding_minutes,mfe_r,mae_r,
            reason_text,reason_codes,entry_context)
            VALUES (42,'REVERSE_RR2','BTCUSDT','LONG',
              '2026-10-14T00:00:00Z','2026-10-14T01:00:00Z',
              100,104,98,104,1,87,4,.1,3.9,1.95,'TAKE_PROFIT',
              60,2.1,.2,'test','[]','{}')""")
        db.execute("""UPDATE reverse_lab_cases SET status='CLOSED',net_r=1.80
                    WHERE variant='REV_A_FIXED_2R'""")
    snap=reverse_lab_snapshot()
    assert snap["paired_case_c"]["pairs"]==1
    assert snap["paired_case_c"]["delta_mean_r"]==pytest.approx(-.15)
    # Deliberate wrong side must not enter the matched Case C comparison.
    with storage._connect() as db:
        db.execute("UPDATE battle_trades SET side='SHORT' WHERE position_id=42")
    assert reverse_lab_snapshot()["paired_case_c"]["pairs"]==0


def test_daily_reporting_and_no_historical_backfill(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    day=datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    out=write_reverse_lab_report(day,root=tmp_path)
    assert out["cohorts"]==0 and out["paper_trading_enabled_by_lab"] is False
    for ext in ("json","md","html"):
        assert (tmp_path/day/f"reverse-lab.{ext}").exists()
    with pytest.raises(ValueError):
        write_reverse_lab_report("2020-01-01",root=tmp_path)


def test_persist_optimistic_cas_preserves_single_forward_cursor(monkeypatch,tmp_path):
    setup_db(tmp_path,monkeypatch)
    register_reverse_signals([signal()],scan(),observed_ms=100000)
    before=next(x for x in active_reverse_cases() if x["variant"]=="REV_A_FIXED_2R")
    newer=advance_reverse(before,candle(2,100,101,99.5,100.3))
    assert persist_reverse_case(before,newer)
    assert not persist_reverse_case(before,newer)
    with storage._connect() as db:
        row=db.execute("SELECT * FROM reverse_lab_cases WHERE id=?",(before["id"],)).fetchone()
    assert row["cursor_ms"]==newer["cursor_ms"]
