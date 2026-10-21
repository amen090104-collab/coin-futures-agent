import asyncio
import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone

import httpx
import pytest

from app.rei_v3_market import FuturesHistory, HistoryError, reconstruct, INTERVALS
from app.rei_v3_store import (init, insert, normalized, samples, coverage, reconstruct_entry_proxies,
                              reconstruct_pending)
from app.rei_v3_learning import primary, fit, DAY
from test_rei_v3 import original, candles


@pytest.fixture
def db(tmp_path):
    con=sqlite3.connect(tmp_path/'archive-test.db')
    con.row_factory=sqlite3.Row
    init(con)
    yield con
    con.close()


def zip_rows(filename, rows, *, bad_name=False):
    text=io.StringIO()
    writer=csv.writer(text)
    writer.writerow(['open_time','open','high','low','close','volume','close_time'])
    writer.writerows(rows)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        # The mock serves ZIP and CHECKSUM in separate requests. Wall-clock ZIP
        # timestamps would change their bytes across a two-second DOS-time boundary.
        member=zipfile.ZipInfo('../escape.csv' if bad_name else filename[:-4]+'.csv',date_time=(2020,1,1,0,0,0))
        member.compress_type=zipfile.ZIP_DEFLATED
        z.writestr(member,text.getvalue())
    return output.getvalue()


def archive_market(db, *, rest=451, monthly_missing=False, corrupt=False, bad_name=False,
                   alter_future=False, missing=False, duplicate=False):
    calls=[]
    def handler(req):
        calls.append(str(req.url))
        if req.url.host=='fapi.binance.com':
            return httpx.Response(rest)
        path=req.url.path
        if monthly_missing and '/monthly/' in path:
            return httpx.Response(404)
        filename=path.split('/')[-1].removesuffix('.CHECKSUM')
        parts=filename[:-4].split('-')
        interval=parts[1]
        step=INTERVALS[interval]
        day_format='%Y-%m-%d' if '/daily/' in path else '%Y-%m'
        date=datetime.strptime('-'.join(parts[2:]),day_format).replace(tzinfo=timezone.utc)
        if '/daily/' in path:
            until=int(date.timestamp()*1000)+DAY-1
        else:
            from app.rei_v3_archives import next_month
            until=int(next_month(date).timestamp()*1000)-1
        rows=candles(int(date.timestamp()*1000),until,step)
        # Archives contain post-event bars. A large change there must not change PIT features.
        cutoff=int(datetime(2025,11,20,4,17,tzinfo=timezone.utc).timestamp()*1000)
        if alter_future:
            for r in rows:
                if int(r[0])>=cutoff: r[1:6]=[10_000,20_000,9_000,15_000,1_000_000]
        if missing: rows=rows[::2]
        if duplicate: rows=rows+rows
        data=zip_rows(filename,rows,bad_name=bad_name)
        if path.endswith('.CHECKSUM'):
            checksum='0'*64 if corrupt else hashlib.sha256(data).hexdigest()
            return httpx.Response(200,text=checksum+'  '+filename+'\n')
        return httpx.Response(200,content=data)
    async def sleep(*a): pass
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return FuturesHistory(db,client=client,sleep=sleep,clock=lambda:1_800_000_000),calls


@pytest.mark.parametrize('status',[403,451,400,404,503])
def test_rest_unavailable_falls_back_official_futures_checksum_and_cache(db,status):
    history,calls=archive_market(db,rest=status)
    asof=int(datetime(2025,11,20,4,17,tzinfo=timezone.utc).timestamp()*1000)
    frame,proof=asyncio.run(history.bars('BTCUSDT','1h',asof))
    assert len(frame)==220 and int(frame.iloc[-1].close_time)<asof
    assert proof['provider']=='binance-official-usdm-archives'
    assert all('/futures/um/' in p['url'] for p in proof['archives'])
    assert proof['archives'][0]['sha256']
    count=len(calls)
    again,_=asyncio.run(history.bars('BTCUSDT','1h',asof))
    assert frame.equals(again) and len(calls)==count


def test_monthly_404_falls_back_daily_with_utc_boundaries(db):
    history,calls=archive_market(db,monthly_missing=True)
    asof=int(datetime(2025,11,20,4,17,tzinfo=timezone.utc).timestamp()*1000)
    frame,proof=asyncio.run(history.bars('BTCUSDT','1h',asof))
    assert len(frame)==220
    assert all('/daily/klines/BTCUSDT/1h/' in a['url'] for a in proof['archives'])
    assert int(frame.iloc[0].open_time)%INTERVALS['1h']==0


@pytest.mark.parametrize('options',[{'corrupt':True},{'bad_name':True},{'missing':True},{'duplicate':True}])
def test_checksum_container_gaps_and_duplicates_fail_closed(db,options):
    history,_=archive_market(db,**options)
    with pytest.raises(HistoryError):
        asyncio.run(history.bars('BTCUSDT','1h',1_763_619_420_000))
    assert not db.execute('SELECT 1 FROM rei_v3_market_cache').fetchone()


def test_future_archive_prices_cannot_change_signal_features(db):
    row=normalized(original(stamp='2025-11-20T04:17:00Z'),origin='HISTORICAL_PAPER',key=('t',1),imported_ms=2_000_000_000_000)
    # original fixture entry/closed later than this signal; use explicit signal time, never entry.
    a,_=archive_market(db)
    features,proof=asyncio.run(reconstruct(a,row))
    db.execute('DELETE FROM rei_v3_market_cache');db.execute('DELETE FROM rei_v3_archives');db.commit()
    b,_=archive_market(db,alter_future=True)
    after,_=asyncio.run(reconstruct(b,row))
    assert features==after and proof['max_source_ms']<row['decision_ms']


def test_missing_signal_gets_entry_proxy_not_training_or_forward_oos(db):
    row=normalized(original(stamp=''),origin='HISTORICAL_PAPER',key=('t',2),imported_ms=2_000_000_000_000)
    insert(db,row);db.commit()
    history,_=archive_market(db)
    assert asyncio.run(reconstruct_pending(db,history))=={}
    assert asyncio.run(reconstruct_entry_proxies(db,history))=={'PROXY_READY':1}
    saved=samples(db)[0]
    assert saved['decision_ms']==0 and saved['features']=={'source_score':81.}
    record=db.execute('SELECT payload FROM rei_v3_entry_context').fetchone()
    proxy=json.loads(record[0])
    assert proxy['feature_asof_ms']==row['entry_ms'] and not proxy['usable_at_original_signal'] and not proxy['forward_oos']
    assert proxy['provenance']['max_source_ms']<row['entry_ms']
    assert not primary([saved])
    accidental={**saved,'status':'READY','decision_ms':row['entry_ms'],'features':proxy['features'],
                'feature_provenance':proxy['provenance']}
    assert not primary([accidental])
    result=coverage(db)['by_source']['HISTORICAL_PAPER']['by_base_side']['LONG']
    assert result['proxy_ready']==1 and result['ready_cohorts']==0 and result['with_signal_time']==0


def test_proxy_missing_score_is_explicit_not_fabricated(db):
    record=original(stamp='');record['score']=None
    row=normalized(record,origin='HISTORICAL_PAPER',key=('t',3),imported_ms=2_000_000_000_000)
    insert(db,row);db.commit()
    history,_=archive_market(db)
    assert asyncio.run(reconstruct_entry_proxies(db,history))=={'PROXY_READY':1}
    payload=json.loads(db.execute('SELECT payload FROM rei_v3_entry_context').fetchone()[0])
    assert payload['features']['source_score'] is None and 'source_score' in payload['provenance']['unrecoverable']


def test_schema_v1_migration_preserves_v3_rows(db):
    row=normalized(original(),origin='HISTORICAL_PAPER',key=('t',4),imported_ms=2_000_000_000_000)
    insert(db,row)
    db.execute("UPDATE rei_v3_meta SET schema_version=1,version='rei-v3.1'");db.commit()
    init(db);init(db)
    assert samples(db)==[row]
    assert [tuple(r) for r in db.execute('SELECT * FROM rei_v3_meta')]==[(2,'rei-v3.2')]
    db.execute('DELETE FROM rei_v3_meta');db.commit()
    init(db)  # recovery after an interrupted first schema initialization
    assert samples(db)==[row] and db.execute('SELECT schema_version FROM rei_v3_meta').fetchone()[0]==2


def test_public_smoke_records_verification_without_profitability_claim(db):
    from app.rei_v3_smoke import smoke
    history,_=archive_market(db)
    result=asyncio.run(smoke(db,cases=[('BTCUSDT','2025-11-20T04:17:00Z','1h')],history=history))
    assert result['verified_windows']==1 and result['release_market_evidence']
    assert not result['model_or_profitability_validated']


def test_archive_budget_and_rate_limit_resumable_without_fallback_evasion(db):
    history,calls=archive_market(db,rest=429)
    with pytest.raises(HistoryError,match='RATE_LIMIT'):
        asyncio.run(history.bars('BTCUSDT','1h',1_763_619_420_000))
    assert all('fapi.binance.com' in c for c in calls)
    history,_=archive_market(db);history.http.max_requests=1
    with pytest.raises(HistoryError,match='BUDGET'):
        asyncio.run(history.bars('BTCUSDT','1h',1_763_619_420_000))


def test_archive_cache_rechecks_bytes_and_enforces_response_budget(db):
    history,_=archive_market(db)
    asof=1_763_619_420_000
    asyncio.run(history.bars('BTCUSDT','1h',asof))
    db.execute('DELETE FROM rei_v3_market_cache')
    db.execute("UPDATE rei_v3_archives SET compressed=X'00'");db.commit()
    with pytest.raises(HistoryError,match='ARCHIVE_CACHE_CHECKSUM_MISMATCH'):
        asyncio.run(history.bars('BTCUSDT','1h',asof))
    from app.rei_v3_archives import PublicHistoryHTTP
    client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'12345')))
    bounded=PublicHistoryHTTP(client)
    with pytest.raises(HistoryError,match='HISTORY_RESPONSE_TOO_LARGE'):
        asyncio.run(bounded.get('https://data.binance.vision/test',max_bytes=4))


def test_old_provider_unrecoverable_reconsidered_once_without_retrying_corruption(db):
    from app.rei_v3_archives import POLICY
    row=normalized(original(stamp='2025-11-20T04:17:00Z'),origin='HISTORICAL_PAPER',key=('t',5),imported_ms=2_000_000_000_000)
    row.update(status='HISTORY_UNRECOVERABLE',feature_provenance={'status':'SYMBOL_HISTORY_UNAVAILABLE'})
    insert(db,row);db.commit()
    history,calls=archive_market(db)
    assert asyncio.run(reconstruct_pending(db,history))=={'READY':1}
    assert samples(db)[0]['feature_provenance']['market_policy']==POLICY
    assert asyncio.run(reconstruct_pending(db,history))=={}
    row=normalized(original(stamp='2025-11-20T04:17:00Z'),origin='HISTORICAL_PAPER',key=('t',6),imported_ms=2_000_000_000_000)
    row.update(status='HISTORY_UNRECOVERABLE',feature_provenance={'status':'CACHE_CHECKSUM_MISMATCH'})
    insert(db,row);db.commit()
    count=len(calls)
    assert asyncio.run(reconstruct_pending(db,history))=={} and len(calls)==count


def test_proxy_retry_waits_one_hour_then_resumes_without_signal_mutation(db):
    row=normalized(original(stamp=''),origin='HISTORICAL_PAPER',key=('t',7),imported_ms=2_000_000_000_000)
    insert(db,row);db.commit()
    history,_=archive_market(db);history.http.max_requests=0
    now=2_000_000_000_000
    assert asyncio.run(reconstruct_entry_proxies(db,history,now_ms=now))=={'PROXY_RETRY':1}
    history,_=archive_market(db)
    assert asyncio.run(reconstruct_entry_proxies(db,history,now_ms=now+1))=={}
    assert asyncio.run(reconstruct_entry_proxies(db,history,now_ms=now+3_600_000))=={'PROXY_READY':1}
    assert samples(db)==[row] and not primary(samples(db))
