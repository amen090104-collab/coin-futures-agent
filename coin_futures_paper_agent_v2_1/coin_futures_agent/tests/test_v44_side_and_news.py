"""Adaptive entry respects independent reversed trend and point-in-time news."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.indicators import enrich
from app.v44_trend import select_entry
from app import v44_shadow


def _frame_down():
    rows=[]
    for i in range(220):
        price=200-0.04*i
        if i==218:
            price-=0.25
        rows.append({"open":price+0.04,"close":price,"high":price+0.2,
                     "low":price-0.2,"volume":3000 if i==218 else 1000,
                     "open_time":i*900000,"close_time":(i+1)*900000-1})
    return enrich(pd.DataFrame(rows))


def test_opposite_source_trend_must_have_independent_confirmation():
    frame=_frame_down()
    row={"symbol":"SOLUSDT","bias":"LONG","long_score":87,"short_score":12}
    risk={"risk_state":"NORMAL"}
    tentative={"direction":"BEARISH","phase":"CONTINUATION","data_quality":"VALID",
               "strength":80,"continuation":65,"exhaustion":15}
    declined=select_entry(row,frame,tentative,risk)
    assert declined["action"]=="NO_TRADE"
    assert declined["reason"]=="OPPOSITE_TREND_NOT_INDEPENDENTLY_CONFIRMED"
    strong={**tentative,"strength":95,"continuation":90}
    chosen=select_entry(row,frame,strong,risk)
    if chosen["action"]!="NO_TRADE":
        assert chosen["side"]=="SHORT"
        assert chosen["direction_source_relation"]=="TREND_CONFIRMED_OPPOSITE"
    else:
        assert chosen["reason"]=="METHOD_SCORES_LOW"


def test_caution_never_bypasses_confirmation():
    frame=_frame_down()
    row={"symbol":"SOLUSDT","bias":"SHORT","long_score":12,"short_score":87}
    trend={"direction":"BEARISH","phase":"CONTINUATION","data_quality":"VALID",
           "strength":92,"continuation":92,"exhaustion":10}
    risk={"risk_state":"CAUTION"}
    result=select_entry(row,frame,trend,risk)
    # Caution may choose WAIT, or reject a method below quality threshold.
    assert result["action"] in ("WAIT","NO_TRADE","ENTER")
    if result["action"]=="ENTER":
        assert result["scores"][result["method"]]>=72
        assert frame.iloc[-2]["vol_ratio"]>=1.1


def test_news_category_must_be_published_and_ingested_by_asof(monkeypatch):
    ts=datetime.now(timezone.utc)
    def article(published,fetched):
        return {"category":"DEFI","symbols":["AAVE"],"source":"example",
                "published_at":published.isoformat(),"fetched_at":fetched.isoformat()}
    before=article(ts-timedelta(minutes=8),ts-timedelta(minutes=5))
    late=article(ts-timedelta(minutes=9),ts+timedelta(minutes=5))
    future=article(ts+timedelta(minutes=1),ts-timedelta(minutes=1))
    monkeypatch.setattr(v44_shadow,"recent_news",lambda **_: [before,late,future])
    seen=v44_shadow._known_news_at(ts.isoformat())
    assert seen==[before]
