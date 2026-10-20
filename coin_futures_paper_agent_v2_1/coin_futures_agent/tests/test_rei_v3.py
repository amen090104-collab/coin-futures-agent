import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.rei_v3_market import FuturesHistory, HistoryError, reconstruct, INTERVALS
from app.rei_v3_store import init, normalized, insert, samples, import_database, reconstruct_pending
from app.rei_v3_learning import fit, decision, evaluate, holdout, primary, DAY, EMBARGO
from app.rei_v3 import overview, run_analysis, frozen_models, source_connection, observe


@pytest.fixture
def db(tmp_path):
    with sqlite3.connect(tmp_path/'research.db') as con:
        con.row_factory = sqlite3.Row
        init(con)
        yield con


def original(i=1, stamp='2026-01-20T00:00:00Z'):
    return {'id': i, 'strategy_id': 'REVERSE_RR2', 'symbol': 'TESTUSDT', 'side': 'SHORT', 'score': 81,
            'opened_at': '2026-01-20T00:02:00Z', 'closed_at': '2026-01-20T04:00:00Z',
            'r_multiple': 1.8, 'fees': .2,
            'entry_context': json.dumps({'cohort_id': stamp+'::TESTUSDT', 'source_signal_side': 'LONG',
                                         'strategy_reverse': True, 'private_token': 'never-retain-this'})}


def test_normalization_never_substitutes_entry_clock_or_leaks_raw_context():
    row = normalized(original(), origin='HISTORICAL_PAPER', key=('battle_trades', 1), imported_ms=2_000_000_000_000)
    assert row['decision_ms'] < row['entry_ms'] < row['closed_ms'] < row['label_available_ms']
    assert 'never-retain-this' not in json.dumps(row)
    assert row['source_score'] == 81 and row['costs']['replay_equivalence'] is False
    missing = normalized(original(stamp=''), origin='HISTORICAL_PAPER', key=('x', 1), imported_ms=2_000_000_000_000)
    assert missing['decision_ms'] == 0 and missing['status'] == 'SIGNAL_TIME_UNRECOVERABLE'


def test_idempotent_import_source_readonly_preserves_all_tables(db, tmp_path):
    path = tmp_path/'private.db'
    with sqlite3.connect(path) as source:
        source.execute('CREATE TABLE battle_trades(id INTEGER, symbol TEXT, side TEXT, score REAL, opened_at TEXT, closed_at TEXT, r_multiple REAL, entry_context TEXT)')
        r = original()
        source.execute('INSERT INTO battle_trades VALUES(?,?,?,?,?,?,?,?)', tuple(r[k] for k in ('id','symbol','side','score','opened_at','closed_at','r_multiple','entry_context')))
        source.execute('CREATE TABLE balances(amount REAL)')
        source.execute('INSERT INTO balances VALUES(1234)')
    before = path.read_bytes()
    with source_connection(path) as source:
        assert import_database(source, db)['imported'] == 1
        assert import_database(source, db)['duplicate_or_ineligible'] == 1
        with pytest.raises(sqlite3.OperationalError):
            source.execute('DELETE FROM balances')
    assert path.read_bytes() == before
    assert len(samples(db)) == 1
    init(db)
    assert len(samples(db)) == 1


def test_incompatible_schema_refuses_migration(db):
    db.execute('UPDATE rei_v3_meta SET schema_version=99')
    with pytest.raises(ValueError, match='INCOMPATIBLE'):
        init(db)


def test_legacy_reverse_requires_explicit_source_evidence(db,tmp_path):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as source:
        source.execute('CREATE TABLE trades(id INTEGER, symbol TEXT, side TEXT, score REAL, opened_at TEXT, closed_at TEXT, r_multiple REAL, entry_context TEXT)')
        r=original()
        keys=('id','symbol','side','score','opened_at','closed_at','r_multiple','entry_context')
        source.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?)',tuple(r[k] for k in keys))
        r.update(id=2,entry_context='{}')
        source.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?)',tuple(r[k] for k in keys))
    source.close()
    with source_connection(path) as source:
        assert import_database(source,db)['imported']==1
    assert samples(db)[0]['source']['table_or_export']=='trades'


def test_conflicting_outcome_is_flagged_and_db_id_reuse_does_not_drop_new_trade(db):
    row=normalized(original(),origin='HISTORICAL_PAPER',key=('battle_trades',1),imported_ms=2_000_000_000_000)
    assert insert(db,row)
    assert not insert(db,{**row,'net_r':-10})
    assert samples(db)[0]['status']=='IMPORT_CONFLICT'
    rec=original()
    rec['opened_at']='2026-01-20T00:03:00Z'
    assert insert(db,normalized(rec,origin='HISTORICAL_PAPER',key=('battle_trades',1),imported_ms=2_000_000_000_000))
    assert len(samples(db))==2


def candles(start, end, step):
    import math
    return [[t, 100+math.sin(i/3), 103+math.sin(i/3), 97+math.sin(i/3),
             100+math.sin(i/3)+i*.001, 100+i%5, t+step-1, 0, 0, 0, 0, 0]
            for i, t in enumerate(range(start, end+1, step))]


def market(db, *, bad=None, statuses=None):
    calls, sleeps = [], []
    def handler(req):
        calls.append(req)
        if statuses:
            status = statuses.pop(0)
            if status != 200:
                return httpx.Response(status, headers={'Retry-After': '1'})
        p = req.url.params
        step = INTERVALS[p['interval']]
        raw = candles(int(p['startTime']), int(p['endTime']), step)
        if bad:
            raw = bad(raw)
        return httpx.Response(200, json=raw)
    async def sleep(seconds): sleeps.append(seconds)
    return FuturesHistory(db, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=sleep,
                          clock=lambda: 2_000_000_000), calls, sleeps


def test_historical_reconstruction_utc_completed_only_cache_and_unrecoverables(db):
    row = normalized(original(), origin='HISTORICAL_PAPER', key=('x', 1), imported_ms=2_000_000_000_000)
    h, calls, _ = market(db)
    features, proof = asyncio.run(reconstruct(h, row))
    assert features['rsi_1h'] is not None and features['source_score'] == 81
    assert features['oi_change_pct'] is None and features['funding_rate'] is None
    assert proof['max_source_ms'] < row['decision_ms']
    assert len(calls) == 6
    assert all(int(c.url.params['endTime']) < row['decision_ms'] for c in calls)
    again, _ = asyncio.run(reconstruct(h, row))
    assert again == features and len(calls) == 6
    row['source_score'] = None
    features, proof = asyncio.run(reconstruct(h, row))
    assert features['source_score'] is None and 'source_score' in proof['unrecoverable']


@pytest.mark.parametrize('bad', [lambda x:x[:-1], lambda x:x[1:]+[x[-1]],
    lambda x:x[:-1]+[[x[-1][0],100,103,97,101,10,x[-1][6]+1]],
    lambda x:x[:-1]+[[x[-1][0],100,99,97,101,10,x[-1][6]]]])
def test_missing_stale_duplicate_future_invalid_candles_fail_closed(db, bad):
    h, _, _ = market(db, bad=bad)
    with pytest.raises(HistoryError):
        asyncio.run(h.bars('TESTUSDT', '1h', 1_800_000_000_000))
    assert db.execute('SELECT COUNT(*) FROM rei_v3_market_cache').fetchone()[0] == 0


def test_rate_limit_retries_cache_and_resumable_progress(db):
    row = normalized(original(), origin='HISTORICAL_PAPER', key=('x', 1), imported_ms=2_000_000_000_000)
    insert(db, row)
    h, calls, sleeps = market(db, statuses=[429, 500, 200])
    result = asyncio.run(reconstruct_pending(db, h, now_ms=2_000_000_000_000))
    assert result == {'READY': 1} and sleeps[:2] == [1., 2]
    assert asyncio.run(reconstruct_pending(db, h)) == {}
    assert len(calls) == 8
    assert overview(db)['reconstructed'] == 1


def test_offline_jobs_retry_without_inventing_features(db):
    insert(db, normalized(original(), origin='HISTORICAL_PAPER', key=('x', 1), imported_ms=2_000_000_000_000))
    h, _, _ = market(db, statuses=[503, 503, 503])
    assert asyncio.run(reconstruct_pending(db, h, now_ms=100)) == {'RETRY_HISTORY': 1}
    assert asyncio.run(reconstruct_pending(db, h, now_ms=101)) == {}
    assert samples(db)[0]['features'] == {'source_score': 81.}


def training_rows(days=24, per_day=8):
    rows=[]
    start=1_750_032_000_000//DAY*DAY
    for d in range(days):
        for i in range(per_day):
            observed = start+d*DAY+(i+2)*3_600_000
            good = i%2 == 0
            rows.append({'sample_id':f'{d}-{i}', 'group_id':f'{d}-{i}', 'origin':'HISTORICAL_PAPER',
                'source_side':'LONG', 'reverse_side':'SHORT', 'symbol':'TESTUSDT', 'status':'READY', 'label_policy':'REVERSE_RR2',
                'decision_ms':observed, 'entry_ms':observed+60_000, 'closed_ms':observed+3600_000,
                'historical_label_known_ms':observed+3600_000, 'label_available_ms':observed+3600_000,
                'net_r':1.8 if good else -1.1,
                'features':{'source_score':81.,'rsi_1h':35. if good else 65., 'atr_pct_1h':2.,
                            'distance_ema20_atr':1.,'volume_ratio_1h':1.5, 'btc_neutral':1.},
                'feature_provenance':{'max_source_ms':observed-1}})
    return rows


def test_grouping_purged_windows_and_label_availability():
    rows=training_rows()
    rows += [{**r,'sample_id':r['sample_id']+'-variant','origin':'HISTORICAL_SHADOW'} for r in rows]
    assert len(primary(rows)) == 192
    cutoff=rows[191]['decision_ms']//DAY*DAY+DAY
    model=fit(rows, asof_ms=cutoff, side='LONG')
    assert model['status'] == 'RESEARCH_CLASSIFIER'
    assert model['max_fit_label_ms'] < model['calibration_start_ms']-EMBARGO
    assert set(model['fit_groups']).isdisjoint(model['calibration_groups'])
    invalid=[{**r,'label_available_ms':cutoff+1} for r in rows]
    assert fit(invalid,asof_ms=cutoff,side='LONG')['status']=='INSUFFICIENT_DATA'
    out=decision(rows[0]['features'],model,side='LONG')
    assert out['score'] is not None and out['status']=='RISK_GATE' and out['action']=='NO_TRADE'
    assert out['score_is_win_probability'] is False and out['factors']


def test_future_labels_cannot_change_frozen_historical_model_and_holdout():
    rows=training_rows()
    excluded=holdout(rows)
    cutoff=rows[-1]['decision_ms']+DAY
    a=fit(rows,asof_ms=cutoff,side='LONG',excluded_groups=excluded)
    mutated=[{**r,'net_r':-1000.} if r['group_id'] in excluded else r for r in rows]
    b=fit(mutated,asof_ms=cutoff,side='LONG',excluded_groups=excluded)
    assert a['model_id']==b['model_id']
    wf=evaluate(rows,holdout_groups=excluded)
    assert wf['status']=='RETROSPECTIVE_ONLY' and not wf['forward_oos_validated']
    assert wf['per_side']['LONG']['HELD_OUT_RETROSPECTIVE']['n']>0


def test_daily_models_and_holdout_persist_across_resume(db):
    for row in training_rows():
        insert(db,row)
    rows=samples(db)
    now=rows[-1]['decision_ms']+DAY
    run_analysis(db,now_ms=now)
    first=frozen_models(db,rows,now)
    for r in rows: r['net_r']=-100
    assert frozen_models(db,rows,now)==first
    info=overview(db,now_ms=now)
    assert info['models']['LONG']['training_n']>0
    assert info['analysis']['heldout_is_retrospective']
    assert info['forward']['scored']==0


def test_untrained_and_missing_have_explicit_non_numeric_reasons():
    f=training_rows()[0]['features']
    assert decision(f,{'status':'INSUFFICIENT_DATA'},side='SHORT')['reason_codes']==['INSUFFICIENT_DATA']
    assert decision({}, {},side='LONG')['status']=='MISSING_FEATURE'


def test_read_overview_does_not_initialize_v3(tmp_path):
    with sqlite3.connect(tmp_path/'empty.db') as con:
        assert overview(con)['status']=='UNTRAINED'
        assert not con.execute('SELECT name FROM sqlite_master').fetchall()


def test_missing_signal_and_unknown_side_never_reconstruct_or_train(db):
    row=normalized(original(stamp=''), origin='HISTORICAL_PAPER',key=('x',2),imported_ms=2_000_000_000_000)
    insert(db,row)
    h,calls,_=market(db)
    assert asyncio.run(reconstruct_pending(db,h))=={}
    assert not calls and not primary(samples(db))
    rec=original()
    rec['entry_context']='{}'
    assert normalized(rec,origin='HISTORICAL_PAPER',key=('x',3),imported_ms=2_000_000_000_000) is None


def test_source_cost_policies_not_pooled_as_independent_training_rows():
    rows=training_rows()
    other=[{**r,'sample_id':r['sample_id']+'-caseD','label_policy':'REVERSE_RR3','net_r':-100} for r in rows]
    cutoff=rows[-1]['decision_ms']+DAY
    a=fit(rows,asof_ms=cutoff,side='LONG')
    b=fit(rows+other,asof_ms=cutoff,side='LONG')
    assert a['model_id']==b['model_id']
    assert fit(other,asof_ms=cutoff,side='LONG')['status']=='INSUFFICIENT_DATA'


def test_live_observations_frozen_once_and_late_backfill_not_oos(tmp_path,monkeypatch):
    from app import storage
    from app.config import settings
    from app import reverse_intelligence_store as v2
    from types import SimpleNamespace
    from test_reverse_intelligence_store import scan
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'live.db')
    monkeypatch.setattr(settings,'reverse_entry_intelligence_enabled',True)
    monkeypatch.setattr(settings,'v44_shadow_enabled',True)
    monkeypatch.setattr(v2,'build_trade_plan',lambda *a:SimpleNamespace(score=80,signal_price=100,entry=100,stop_loss=99))
    v2.register(scan(),{'XUSDT':object()},[],observed_ms=70_000)
    with storage._connect() as con:
        init(con)
        observe(con,con,now_ms=75_000)
        before=con.execute('SELECT payload FROM rei_v3_predictions').fetchone()[0]
        assert json.loads(before)['forward_eligible']
        observe(con,con,now_ms=200_000)
        assert con.execute('SELECT payload FROM rei_v3_predictions').fetchone()[0]==before
    v2.register(scan('1970-01-01T00:03:00Z'),{'XUSDT':object()},[],observed_ms=190_000)
    with storage._connect() as con:
        observe(con,con,now_ms=300_000)
        latest=json.loads(con.execute('SELECT payload FROM rei_v3_predictions ORDER BY observed_ms DESC LIMIT 1').fetchone()[0])
        assert not latest['forward_eligible'] and latest['score'] is None
        assert latest['status']=='MISSED_DECISION_WINDOW'


def test_v3_snapshot_repair_never_queries_present_state(tmp_path,monkeypatch):
    from app import rei_v3, v44_learning, reverse_research, storage
    from app.v44_research import init_research
    from app.battle_storage import init_battle_db
    from app.strategy_cases import init_strategy_cases
    from app.decision_journal import init_decision_journal
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'fixture.db')
    storage.init_db()
    init_research()
    init_battle_db()
    init_strategy_cases()
    init_decision_journal()
    reverse_research.init_reverse_lab()
    p=v44_learning.research_snapshot()
    r=reverse_research.reverse_lab_snapshot()
    # Pure renderers operate only on supplied saved JSON, just like V2 snapshots.
    monkeypatch.setattr(rei_v3,'overview',lambda **k:pytest.fail('Must not read present state while repairing old report'))
    p['report_day']='2020-01-01'
    p['reverse_entry_v3']={'status':'UNTRAINED','source_counts':{},'statuses':{},'reconstructed':0,
                         'total_samples':0,'missingness':{},'models':{},'analysis':None,'forward':{}}
    v44_learning.save_research_snapshot(p,root=tmp_path)
    r['report_day']='2020-01-01'
    r['generated_at']='2020-01-02T00:00:00Z'
    r['reverse_entry_v3']=p['reverse_entry_v3']
    reverse_research.save_reverse_snapshot(r,root=tmp_path)


def test_dashboard_v3_escapes_content_and_distinguishes_zero_from_untrained():
    import subprocess
    import re
    from app.dashboard_v43 import DASHBOARD_HTML_V43
    renderer=re.search(r'function renderReverseEntryV3\(\)\{[\s\S]+?\n\}',DASHBOARD_HTML_V43).group(0)
    script='const els={}; const document={getElementById:k=>(els[k]??={})}; const esc=s=>String(s??"").replaceAll("<","&lt;");\n'
    script+='let D={reverse_entry_v3:{recent:[{symbol:"<img>",score:0,status:"RISK_GATE"},{symbol:"X",score:null,status:"NO_MODEL"}]}};\n'
    script+=renderer+'\nrenderReverseEntryV3();\n'
    script+='if(!els.reiV3Signals.innerHTML.includes("0.0") || !els.reiV3Signals.innerHTML.includes("—") || els.reiV3Signals.innerHTML.includes("<img>"))process.exit(1);'
    subprocess.run(['node','-e',script],check=True,capture_output=True)
