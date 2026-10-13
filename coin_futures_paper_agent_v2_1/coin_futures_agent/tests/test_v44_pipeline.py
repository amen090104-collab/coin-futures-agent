"""V4.4 end-to-end Research Integration checks on isolated temporary SQLite.

No network, production database or real orders required.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from app import storage
from app.v44_execution import advance_shadow
from app.v44_research import (init_research, open_shadow, open_shadows,
                              update_shadow, create_pending, update_pending,
                              log_decision, research_overview)
from app.v44_learning import (_bootstrap_interval, _evaluate_frozen_hypothesis,
                              _records, paper_case_comparison)
from app.v44_shadow import _first_future_bar


def _tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "shadow-test.db")
    storage.init_db()
    init_research()


def _candle(minute, o, hi, lo, c):
    return {"open_time": minute * 60000, "close_time": (minute + 1) * 60000-1,
            "open": o, "high": hi, "low": lo, "close": c}


def test_additive_schema_and_idempotent_pending(monkeypatch, tmp_path):
    _tmp_db(monkeypatch,tmp_path)
    now=datetime.now(timezone.utc).isoformat()
    signal_id=create_pending("cohort-1","BTCUSDT","LONG","PULLBACK",
                             {"price":100,"atr":2},(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat())
    assert signal_id==create_pending("cohort-1","BTCUSDT","LONG","PULLBACK",
                                    {"price":100,"atr":2},(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat())
    assert update_pending(signal_id,"CANCELLED","TREND_DEGRADED") is True
    assert update_pending(signal_id,"CANCELLED","TREND_DEGRADED") is False
    assert log_decision("cohort-1","BTCUSDT","ENTRY","WAIT",{},"PENDING","PULLBACK",event_key="unique")
    assert not log_decision("cohort-1","BTCUSDT","ENTRY","WAIT",{},"PENDING","PULLBACK",event_key="unique")
    init_research()
    result=research_overview()
    assert result["counts"]["v44_pending"]==1
    assert result["counts"]["v44_decisions"]==1
    with storage._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM account_events").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


def test_three_variant_shadow_geometry_and_storage(monkeypatch,tmp_path):
    _tmp_db(monkeypatch,tmp_path)
    start=int(datetime.now(timezone.utc).timestamp()//60*60*1000)
    for variant in ("ENTRY_ADAPTIVE","EXIT_A_TREND","EXIT_B_RUNNER"):
        assert open_shadow("same-cohort","ETHUSDT",variant,"LONG",start,100,98,104)
        assert not open_shadow("same-cohort","ETHUSDT",variant,"LONG",start,100,98,104)
    opened=open_shadows("ETHUSDT")
    assert len(opened)==3
    assert all(int(p["last_candle_ms"])==start-1 for p in opened)
    position=opened[0]
    r=advance_shadow(position, _candle(start//60000,100,101,99,100.5),{})
    update_shadow(r)
    restored=open_shadows("ETHUSDT")
    match=next(x for x in restored if x["id"]==position["id"])
    assert match["last_candle_ms"]==start+60000-1
    assert json.loads(match["state_json"])["entry_fee_applied"] is True


def test_partial_fee_and_runner_forward_stop_no_widen():
    now=datetime.now(timezone.utc)
    opened=now.replace(second=0,microsecond=0).isoformat()
    pos={"id":1,"variant":"EXIT_B_RUNNER","side":"LONG","entry":100.,
         "risk":2.,"stop":98.,"effective_stop":98.,"target":104.,
         "remaining":1.,"realized_r":0.,"high_water":0.,
         "last_candle_ms":0,"status":"OPEN","state":{},"entered_at":opened}
    trend={"data_quality":"VALID","direction":"BULLISH",
           "phase":"CONTINUATION","continuation":80,"asof_ms":60000}
    first=advance_shadow(pos,_candle(0,100,102.5,99.5,102),trend)
    assert first["status"]=="OPEN"
    assert first["remaining"]==0.5
    assert len(first["state"]["fills"])==1
    assert first["state"]["fees_r"]>0
    assert first["state"]["fills"][0]["reason"]=="PARTIAL_TP_1R_50PCT"
    # Runner activated at +2R after partial; tightening only affects later bar.
    second=advance_shadow(first,_candle(1,102,105,101.5,104),trend)
    assert second["remaining"]==0.5
    assert second["effective_stop"]>=first["effective_stop"]
    third=advance_shadow(second,_candle(2,104,104.5,101,102),trend)
    assert third["status"]=="CLOSED"
    assert third["net_r"] is not None
    assert third["state"]["fees_r"]>first["state"]["fees_r"]
    assert len(third["state"]["fills"])==2


def test_ahead_of_time_entry_not_accepted_as_future():
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    next_minute=(now_ms//60000+1)*60000
    class Fake:
        async def klines(self,symbol,interval,limit,start_time=None,end_time=None):
            assert start_time==next_minute
            return pd.DataFrame([_candle(next_minute//60000,100,101,99,100.5)])
    bar,reason=asyncio.run(_first_future_bar(Fake(),"BTCUSDT",now_ms,now_ms))
    assert bar is None
    assert reason=="WAIT_FOR_NEXT_CLOSED_MINUTE"


def test_holdout_excludes_training_time():
    spec={"type":"SKIP_IF","feature":"distance_ema_atr","threshold":1.5}
    cut="2026-10-10T12:00:00+00:00"
    rows=[]
    for i in range(100):
        day=10+i//10
        if day>19:
            day=19
        created=("2026-10-09T00:00:00+00:00" if i<50
                 else f"2026-10-{13+(i-50)//10:02d}T00:00:00+00:00")
        rows.append({"signal_at":created,"day":created[:10],"distance_ema_atr":2.0,
                     "control_r":-1.0})
    result=_evaluate_frozen_hypothesis(spec,cut,rows,1)
    assert result["cohorts_oos"]==50
    assert result["cohorts_triggered"]==50
    assert result["verdict"]=="INSUFFICIENT_OUT_OF_SAMPLE" # only five OOS calendar days


def test_cluster_interval_no_false_exact_certainty():
    assert _bootstrap_interval([0.2]) is None
    lo,hi=_bootstrap_interval([-1.0,1.0,0.3],groups=["d1","d1","d2"])
    assert lo <= hi


def test_paper_case_unavailable_is_safe(monkeypatch,tmp_path):
    _tmp_db(monkeypatch,tmp_path)
    result=paper_case_comparison([])
    assert result["status"]=="PAPER_CASE_TABLES_UNAVAILABLE"
