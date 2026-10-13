"""V4.4 shadow safety and trend research tests."""
from datetime import datetime, timezone
import pandas as pd
import math
from app.indicators import enrich
from app.v44_trend import assess_trend,closed_frame,select_entry,market_context,entry_risk_block
from app.v44_shadow import _next_step


def frames(sign=1, n=230):
    rows=[]
    anchor=100
    for k in range(n):
        center=anchor+sign*k*0.08+0.45*math.sin(k*0.8)
        rows.append({"open_time":k*900000,"close_time":(k+1)*900000-1,
                     "open":center-0.035,"high":center+0.12,
                     "low":center-0.12,"close":center,"volume":1000+k})
    df=enrich(pd.DataFrame(rows))
    return {"15m":df,"1h":df.copy(),"4h":df.copy()}


def test_trend_uses_last_closed_candle():
    f=frames()
    first=assess_trend(f)
    f["15m"].loc[len(f["15m"])-1,"close"]=0.01
    after=assess_trend(f)
    assert first==after
    assert first["data_quality"]=="VALID"


def test_trend_historical_asof_blocks_future():
    f=frames()
    asof=int(f["15m"].iloc[130]["close_time"])
    before=assess_trend(f,asof_ms=asof)
    for x in f.values():
        x.loc[x.index>130,"close"]=1e9
    after=assess_trend(f,asof_ms=asof)
    assert before==after


def test_invalid_data_is_no_trade():
    context=market_context({"btc_regime":"NEUTRAL","all":[{"long_score":78}],"created_at":"now"})
    entry=select_entry({"symbol":"BTCUSDT","bias":"LONG"},pd.DataFrame(),{"data_quality":"INSUFFICIENT"},context)
    assert entry["action"]=="NO_TRADE"


def test_market_lock_blocks_scope_only():
    context={"risk_state":"EVENT_LOCK","guardian_scope":"COIN","guardian_symbols":["BTC"]}
    assert entry_risk_block(context,"BTCUSDT")=="EVENT_LOCK"
    assert entry_risk_block(context,"ETHUSDT") is None


def test_missing_market_is_restricted():
    risk=market_context({"all":[],"btc_regime":"NEUTRAL"})
    assert risk["risk_state"]=="RESTRICTED"


def test_shadow_stop_first_and_no_stop_widening():
    p={"id":1,"variant":"EXIT_A_TREND","side":"LONG","entry":100.,
       "risk":2.,"stop":98.,"effective_stop":98.,"target":104.,
       "remaining":1.,"realized_r":0.,"high_water":0.,
       "last_candle_ms":0,"status":"OPEN","state":{}}
    bar={"open":100.,"high":105.,"low":97.,"close":102.,"close_time":60000}
    result=_next_step(p,bar,{"data_quality":"VALID","phase":"CONTINUATION","continuation":80})
    assert result["status"]=="CLOSED"
    assert result["reason"]=="STOP_FIRST"
    assert result["net_r"]<0
    q={**p,"effective_stop":99.5}
    bar2={"open":100.,"high":102.,"low":99.9,"close":101.,"close_time":60000}
    out=_next_step(q,bar2,{"data_quality":"VALID","phase":"WEAKENING","exhaustion":75})
    assert out["effective_stop"]>=q["effective_stop"]


def test_partial_takes_no_same_bar_runner():
    p={"id":1,"variant":"EXIT_B_RUNNER","side":"LONG","entry":100.,
       "risk":2.,"stop":98.,"effective_stop":98.,"target":104.,
       "remaining":1.,"realized_r":0.,"high_water":0.,
       "last_candle_ms":0,"status":"OPEN","state":{}}
    result=_next_step(p,{"open":100,"high":105,"low":100,"close":104,"close_time":60000},
                      {"data_quality":"VALID","phase":"CONTINUATION","continuation":80})
    assert result["remaining"]==0.5
    assert result["realized_r"]==0.5
    assert result["status"]=="OPEN"
