"""Additional V4.4 research acceptance tests: prospective learning + risk/exits."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from app import storage
from app.indicators import enrich
from app.v44_execution import advance_shadow
from app.v44_learning import (_records, evaluate_live_hypotheses,
                              _evaluate_frozen_hypothesis, write_research_report)
from app.v44_research import (init_research, log_decision, open_shadow,
                              register_hypothesis)
from app.v44_trend import market_context, select_entry


def _setup(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"db.sqlite")
    storage.init_db()
    init_research()


def _bar(k,o,h,l,c):
    return {"open_time":k*60000, "close_time":(k+1)*60000-1,
            "open":o,"high":h,"low":l,"close":c}


def _pos(variant="EXIT_A_TREND",side="LONG"):
    return {"variant":variant, "side":side,"id":1,"entry":100.,
            "stop":98. if side=="LONG" else 102.,
            "effective_stop":98. if side=="LONG" else 102.,
            "target":104. if side=="LONG" else 96.,
            "risk":2.,"remaining":1.,"realized_r":0.,
            "high_water":0.,"last_candle_ms":-1,"status":"OPEN",
            "entered_at":"1970-01-01T00:00:00+00:00","state":{}}


def test_trend_based_exit_queued_for_future_bar():
    pos=_pos()
    opposite1={"data_quality":"VALID","direction":"BEARISH",
               "continuation":75,"phase":"CONTINUATION","asof_ms":100}
    opposite2={**opposite1,"asof_ms":200}
    first=advance_shadow(pos,_bar(0,100,100.8,99.5,100.2),opposite1)
    assert first["status"]=="OPEN"
    assert first["state"]["opposite_confirmations"]==1
    second=advance_shadow(first,_bar(1,100.2,100.7,99.8,100.1),opposite2)
    assert second["status"]=="OPEN"
    assert second["state"]["queued_exit"]=="CONFIRMED_OPPOSITE_TREND"
    third=advance_shadow(second,_bar(2,100,100.7,99.1,99.8),opposite2)
    assert third["status"]=="CLOSED"
    assert third["reason"]=="CONFIRMED_OPPOSITE_TREND"
    assert third["state"]["fills"][-1]["at_ms"]==179999


def test_source_no_trade_research_counts_missed_winner(monkeypatch,tmp_path):
    _setup(tmp_path,monkeypatch)
    stamp=datetime.now(timezone.utc).isoformat()
    source={"entry":{"action":"NO_TRADE","method":None},
            "trend":{"phase":"EXHAUSTED","direction":"BULLISH"},
            "market":{"btc_regime":"NEUTRAL","risk_state":"CAUTION"},
            "source_row":{"bias":"LONG","distance_ema20_atr":2.5,
                          "long_score":87,"volume_ratio_1h":0.8}}
    assert log_decision("sample-1","DOGEUSDT","ENTRY","NO_TRADE",
                        source,"NO_TRADE",event_key="sample-1|ADAPTIVE_ENTRY_DECISION")
    start=int(datetime.now(timezone.utc).timestamp()//60*60*1000)
    assert open_shadow("sample-1","DOGEUSDT","SOURCE_FIXED_2R","LONG",start,100,98,104)
    with storage._connect() as db:
        db.execute("""UPDATE v44_shadow_positions SET status='CLOSED',
            net_r=1.95,realized_r=2.0 WHERE cohort_id=?""",("sample-1",))
    cohorts=_records()
    assert len(cohorts)==1
    assert cohorts[0]["control_r"]==1.95
    assert cohorts[0]["adaptive_r"]==0.0
    assert cohorts[0]["delta_r"]==-1.95


def test_hypothesis_logs_prospective_skip_only(monkeypatch,tmp_path):
    _setup(tmp_path,monkeypatch)
    spec={"type":"SKIP_IF","feature":"distance_ema_atr",
          "threshold":1.5,"policy_action":"SKIP"}
    hid=register_hypothesis("Avoid late long","train-only association",spec)
    stamped=(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat()
    count=evaluate_live_hypotheses("future-cohort","BTCUSDT",stamped,
                                   {"distance_ema20_atr":2.1},
                                   {"exhaustion":45,"phase":"CONTINUATION"},
                                   {"btc_regime":"NEUTRAL","risk_state":"NORMAL"})
    assert count==1
    assert evaluate_live_hypotheses("future-cohort","BTCUSDT",stamped,
                                    {"distance_ema20_atr":2.1},
                                    {"exhaustion":45,"phase":"CONTINUATION"},
                                    {"btc_regime":"NEUTRAL","risk_state":"NORMAL"})==0
    with storage._connect() as db:
        row=db.execute("SELECT snapshot_json,action FROM v44_decisions WHERE kind='HYPOTHESIS'").fetchone()
    assert row["action"]=="SKIP"
    assert json.loads(row["snapshot_json"])["hypothesis_id"]==hid
    observed={"future-cohort":"SKIP"}
    rows=[{"cohort_id":"old","signal_at":"2026-10-09T00:00:00+00:00",
           "day":"2026-10-09","control_r":-1.0,"distance_ema_atr":2.0},
          {"cohort_id":"future-cohort","signal_at":stamped,"day":stamped[:10],
           "control_r":-1.0,"distance_ema_atr":2.0}]
    result=_evaluate_frozen_hypothesis(spec,"2026-10-12T00:00:00+00:00",
                                        rows,1,observed=observed)
    assert result["cohorts_oos"]==1
    assert result["cohorts_triggered"]==1


def test_market_event_provenance_and_caution():
    risk=market_context({"all":[{"long_score":85,"short_score":4,
                                  "trend_1h_long":True,"relative_strength_1h_pct":1.0},
                                 {"long_score":30,"short_score":83,
                                  "trend_1h_short":True,"relative_strength_1h_pct":-2.0}],
                         "btc_regime":"NEUTRAL","created_at":"2026-10-13T00:00:00Z"},
                        {"state":{"mode":"CAUTION","event_key":"hash-source-abc",
                                  "event_id":3,"scope":"SYMBOL","symbols":["BTC"]}})
    assert risk["risk_state"]=="CAUTION"
    assert risk["guardian_event_key"]=="hash-source-abc"
    assert risk["guardian_event_id"]==3
    assert risk["relative_strength_top"][0]["symbol"] is None or isinstance(risk["relative_strength_top"],list)


def test_daily_research_html_and_json_on_empty_db(monkeypatch,tmp_path):
    _setup(tmp_path,monkeypatch)
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    out=write_research_report(day,tmp_path)
    folder=tmp_path/day
    assert (folder/"v44-research.json").exists()
    assert (folder/"v44-research.md").exists()
    assert (folder/"v44-research.html").exists()
    assert out["promotion_requires_user_approval"] is True
    assert out["entry_vs_fixed_2r"]["cohorts_resolved"]==0
