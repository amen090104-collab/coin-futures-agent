"""Issue #22: synthetic fixtures only. Counts reproduce the log, not the user's raw data."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from app import storage, rei_v3
from app.config import settings
from app.rei_plan_diagnostics import inspect_plan, eligibility, cohort_diagnostics
from app.rei_v3_learning import fit, fit_inputs, training_evidence, DAY
from app.rei_v3_store import init, insert, samples, reconstruct_pending
from app.reverse_intelligence_store import init_intelligence
from app.strategy import build_trade_plan
from app.v5_diagnostics import diagnose
from test_rei_v3 import training_rows, db
from test_reverse_intelligence_store import scan


@pytest.fixture
def trade_inputs(monkeypatch):
    for key, value in {'score_threshold':75., 'min_volume_ratio':1., 'max_atr_pct':5.,
                       'min_stop_pct':.1, 'max_stop_pct':5., 'stop_atr_mult':2.}.items():
        monkeypatch.setattr(settings,key,value)
    row=scan()['all'][0]
    frame=pd.DataFrame([{'close':100.,'atr14':1.,'low':99.,'high':101.}]*3)
    return row,frame


@pytest.mark.parametrize('side',['LONG','SHORT'])
@pytest.mark.parametrize('case,reason',[
    ('score','SCORE_BELOW_THRESHOLD'),('volume','VOLUME_BELOW_MIN'),('atr','ATR_ABOVE_MAX'),
    ('narrow','STOP_TOO_NARROW'),('wide','STOP_TOO_WIDE'),('missing','MISSING_15M_FRAME'),
    ('empty','MISSING_15M_FRAME'),('invalid','FRAME_INDICATOR_INVALID'),('zero_atr','ATR_NON_POSITIVE')])
def test_exact_original_plan_rejection_reasons(trade_inputs,monkeypatch,side,case,reason):
    row,frame=trade_inputs;row.update(bias=side,long_score=80.,short_score=80.)
    if case=='score':row['long_score']=row['short_score']=50.
    if case=='volume':row['volume_ratio_1h']=.5
    if case=='atr':row['atr_pct_1h']=10.
    if case=='narrow':monkeypatch.setattr(settings,'min_stop_pct',3.)
    if case=='wide':monkeypatch.setattr(settings,'max_stop_pct',1.)
    if case=='missing':frame=None
    if case=='empty':frame=pd.DataFrame()
    if case=='invalid':frame=frame.drop(columns='atr14')
    if case=='zero_atr':frame['atr14']=0.
    plan,proof=inspect_plan(row,frame,'NEUTRAL',build_trade_plan)
    assert plan is None and proof['plan_gate_reason']==reason


def test_builder_unchanged_called_once_and_exception_text_never_stored(trade_inputs):
    row,frame=trade_inputs
    original=build_trade_plan(row,frame,'NEUTRAL')
    calls=[]
    def builder(*args):calls.append(args);return build_trade_plan(*args)
    plan,proof=inspect_plan(row,frame,'NEUTRAL',builder)
    assert plan==original and len(calls)==1 and proof['plan_gate_reason']=='PLAN_OK'
    def broken(*args):raise RuntimeError('PRIVATE_PATH_AND_KEY_MUST_NOT_APPEAR')
    plan,proof=inspect_plan(row,frame,'NEUTRAL',broken)
    assert proof['plan_gate_reason']=='BUILD_EXCEPTION' and proof['build_exception_type']=='RuntimeError'
    assert 'PRIVATE_' not in json.dumps(proof)


def cohort(i=0,*,valid=True,reason=None,observed=70_000):
    return {'cohort_id':f'fixture::{i}', 'symbol':'TESTUSDT','source_side':'LONG',
            'observed_at_ms':observed,'features_available_at_ms':observed-1,
            'source_signal_at':'1970-01-01T00:01:00Z','features':training_rows(1,1)[0]['features'],
            'quality_ok':valid,'quality':{'missing_core':[],'missing_optional':[],
                'timestamps_valid':True,'source_signal_time_valid':True,
                **({'plan_gate_reason':reason} if reason else {})},
            'signal_price':100. if valid else None,'risk_distance':1. if valid else None}


def put_cohort(db,row):
    db.execute('INSERT INTO rei_v2_cohorts VALUES(?,?,?,?,?,?,?)',(
        row['cohort_id'],row['symbol'],row['source_side'],row['observed_at_ms'],row['source_signal_at'],None,json.dumps(row)))


def test_filters_are_observational_not_paired_trades_and_real_signal_captured(tmp_path,monkeypatch,trade_inputs):
    from app import reverse_intelligence_store as v2
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'fixture.db')
    monkeypatch.setattr(settings,'reverse_entry_intelligence_enabled',True)
    monkeypatch.setattr(settings,'v44_shadow_enabled',True)
    row,frame=trade_inputs
    s=scan();s['all']=[{**row,'long_score':50.},{**row,'symbol':'YESUSDT'}]
    result=v2.register(s,{'XUSDT':frame,'YESUSDT':frame},[],observed_ms=70_000)
    assert result['diagnostics']['all']['plan_gate_reasons']=={'SCORE_BELOW_THRESHOLD':1,'PLAN_OK':1}
    rows={r['symbol']:r for r in v2.dataset()}
    assert eligibility(rows['XUSDT'])['observation_eligible']
    assert not rows['XUSDT']['controls'] and not rows['XUSDT']['outcomes']
    assert len(rows['YESUSDT']['controls'])==5 and rows['YESUSDT']['quality_ok']
    with storage._connect() as con:
        init(con);rei_v3.observe(con,con,now_ms=75_000)
        predictions={r[0]:json.loads(r[1]) for r in con.execute('SELECT sample_id,payload FROM rei_v3_predictions')}
        skipped=predictions[rows['XUSDT']['cohort_id']]
        assert skipped['status']=='SKIPPED_BY_TRADE_FILTER' and skipped['score'] is None
        assert skipped['research_eligibility']['feature_missing'] is False
        assert predictions[rows['YESUSDT']['cohort_id']]['forward_eligible']


def test_true_missing_features_and_timestamp_invalid_stay_distinct(db,tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'source.db');init_intelligence()
    good=cohort(1)
    missing=cohort(2);missing['features']={**missing['features'],'rsi_1h':None}
    timestamp=cohort(3);timestamp['quality']['timestamps_valid']=False
    with storage._connect() as source:
        for row in (good,missing,timestamp):put_cohort(source,row)
        source.commit();rei_v3.observe(db,source,now_ms=75_000)
    out={r[0]:json.loads(r[1]) for r in db.execute('SELECT sample_id,payload FROM rei_v3_predictions')}
    assert out['fixture::2']['status']=='MISSING_FEATURE'
    assert out['fixture::3']['status']=='TIMESTAMP_INVALID'
    assert not out['fixture::2']['forward_eligible'] and not out['fixture::3']['forward_eligible']


def test_exact_windows_aggregate_fixture_preserves_frozen_oos_and_explains_ready(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'windows-fixture.db');init_intelligence()
    now=1800*DAY+3600_000
    with storage._connect() as con:
        init(con)
        for i in range(5755):
            put_cohort(con,cohort(i,valid=i<72,observed=now-100_000))
        for i in range(4046):
            p={'status':'MISSED_DECISION_WINDOW' if i<3955 else 'MISSING_FEATURE','score':None,
               'source_side':'LONG','symbol':'TESTUSDT','forward_eligible':False,'action':'NO_TRADE'}
            con.execute('INSERT INTO rei_v3_predictions VALUES(?,?,?)',(f'fixture::{i}',now,json.dumps(p)))
        for i in range(1668):
            r=copy.deepcopy(training_rows(1,1)[0]);r.update(sample_id=str(i),group_id=str(i),label_available_ms=now)
            r['origin']='HISTORICAL_PAPER' if i<1063 else 'HISTORICAL_SHADOW' if i<1600 else 'FORWARD_SHADOW_V2'
            r['status']='READY' if i<6 or i>=1600 else 'PENDING_RECONSTRUCTION'
            if r['origin']=='FORWARD_SHADOW_V2':r['control']='REVERSE_NOW'
            insert(con,r)
        for side in ('LONG','SHORT'):
            con.execute('INSERT INTO rei_v3_models VALUES(?,?,?,?)',(side,now//DAY*DAY,side,json.dumps({'status':'INSUFFICIENT_DATA','training_n':0})))
        con.commit()
        before=list(con.execute('SELECT sample_id,payload FROM rei_v3_predictions'))
        result=diagnose(con,now_ms=now)
        assert result['plan_gates']['window']['all']['records']==5755
        assert result['plan_gates']['window']['all']['quality_ok']==72
        assert result['plan_gates']['window']['all']['plan_gate_reasons']=={'PLAN_OK':72,'LEGACY_PLAN_REASON_UNRECORDED':5683}
        assert result['plan_gates']['window']['all']['feature_missing']==0
        assert result['observations']['historical_observed_late']==3955
        assert result['observations']['timely_prospective']==91
        assert result['historical']['statuses']=={'PENDING_RECONSTRUCTION':1594,'READY':74}
        assert result['historical']['origins']=={'HISTORICAL_PAPER':1063,'HISTORICAL_SHADOW':537,'FORWARD_SHADOW_V2':68}
        for lanes in result['current_training_evidence'].values():
            assert lanes['historical_for_frozen_model']['training_n']==0
            assert lanes['forward_shadow']['training_n']==0
        paper=result['current_training_evidence']['LONG']['historical_for_frozen_model']
        assert paper['excluded_counts']['LABEL_NOT_KNOWN_BEFORE_CUTOFF']==6
        assert result['current_training_evidence']['LONG']['forward_shadow']['excluded_counts']['LABEL_NOT_KNOWN_BEFORE_CUTOFF']==68
        ui=rei_v3.overview(con,now_ms=now)
        assert len(ui['recent'])==20 and all(p['status']=='MISSING_FEATURE' for p in ui['recent'])
        assert all(p['current_diagnostic']['status']=='MISSING_TRADE_PLAN' for p in ui['recent'])
        assert before==list(con.execute('SELECT sample_id,payload FROM rei_v3_predictions'))
        assert 'training_n' in json.dumps(result) and result['readonly']


def test_training_evidence_accounts_for_every_row_and_keeps_lanes_cutoff_holdout():
    rows=training_rows();now=rows[-1]['decision_ms']+DAY
    altered=copy.deepcopy(rows[:8])
    for i,r in enumerate(altered):r.update(sample_id='extra'+str(i),group_id='extra'+str(i))
    altered[0]['label_policy']='REVERSE_RR3'
    altered[1]['feature_provenance']['max_source_ms']=now
    altered[2]['features']['rsi_1h']=None
    altered[3]['feature_provenance']['lane']='ENTRY_PROXY'
    altered[4]['label_available_ms']=now
    altered[5]['net_r']=None
    altered[6]['origin']='HISTORICAL_SHADOW'
    altered[7]['status']='PENDING_RECONSTRUCTION'
    all_rows=rows+altered+[copy.deepcopy(rows[0])]
    e,h,_,_=fit_inputs(all_rows,asof_ms=now,side='LONG',excluded_groups=[rows[1]['group_id']])
    assert sum(e['excluded_counts'].values())+e['training_n']==len(all_rows)
    assert e['excluded_counts']['HOLDOUT_EXCLUDED']==1
    assert e['fit_n']>=30 and e['calibration_n']>=12
    assert e['fit_days']>=7 and e['training_days']>=9
    assert fit(rows,asof_ms=now,side='LONG')['model_id']==fit(rows+altered,asof_ms=now,side='LONG')['model_id']
    r=copy.deepcopy(rows[0]);r['label_available_ms']=now
    live=training_evidence([r],asof_ms=now)['LONG']
    assert live['historical_for_frozen_model']['training_n']==0
    assert live['historical_retrospective']['training_n']==1
    assert live['historical_retrospective']['retrospective'] is True


def test_readonly_ascii_cp1252_diagnostic_includes_wal_never_raw_context(db,tmp_path):
    row=training_rows(1,1)[0];row['note']='PRIVATE_RAW_CONTEXT_KHONG_XUAT'
    insert(db,row);db.commit()
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE personal_secret(value TEXT)');db.execute("INSERT INTO personal_secret VALUES('DO_NOT_PRINT')");db.commit()
    source=Path(db.execute('PRAGMA database_list').fetchone()[2]);before=source.read_bytes()
    out=tmp_path/'diagnostic.json'
    result=subprocess.run([sys.executable,'-m','app.v5_diagnostics','--source-db',str(source),'--output-json',str(out)],
        capture_output=True,env=dict(os.environ,PYTHONIOENCODING='cp1252:strict',PYTHONUTF8='0'),timeout=30)
    assert result.returncode==0,result.stderr.decode('ascii',errors='replace')
    result.stdout.decode('ascii');out.read_bytes().decode('ascii')
    assert json.loads(result.stdout)['historical']['total']==1
    assert all(token not in result.stdout for token in (b'PRIVATE_RAW_CONTEXT',b'DO_NOT_PRINT',str(tmp_path).encode()))
    assert source.read_bytes()==before
    blocked=subprocess.run([sys.executable,'-m','app.v5_diagnostics','--source-db',str(source),'--output-json',str(source)],capture_output=True)
    assert blocked.returncode!=0 and source.read_bytes()==before


def test_bounded_reconstruction_checkpoint_ready_delta_and_resume(db,monkeypatch):
    from app import rei_v3_market
    for r in training_rows(1,5):insert(db,{**r,'status':'PENDING_RECONSTRUCTION'})
    calls=[]
    async def recover(history,row,**kwargs):
        calls.append(row['sample_id']);return row['features'],row['feature_provenance']
    monkeypatch.setattr(rei_v3_market,'reconstruct',recover)
    assert asyncio.run(reconstruct_pending(db,object(),limit=3,now_ms=100))=={'READY':3}
    progress=rei_v3.reconstruction_progress(db,now_ms=100)
    assert progress['latest_batches']['signal']['ready_delta']==3 and progress['pending_or_retry']==2
    assert asyncio.run(reconstruct_pending(db,object(),limit=3,now_ms=200))=={'READY':2}
    assert len(calls)==len(set(calls))==5
    assert rei_v3.reconstruction_progress(db,now_ms=200)['daily_measured']['signal']['ready_delta']==5


def test_reconstruction_budget_timeout_and_global_backoff_keep_unattempted_rows(db,monkeypatch):
    from app import rei_v3_market
    for r in training_rows(1,3):insert(db,{**r,'status':'PENDING_RECONSTRUCTION'})
    async def slow(*a,**k):await asyncio.sleep(1)
    monkeypatch.setattr(rei_v3_market,'reconstruct',slow)
    assert asyncio.run(reconstruct_pending(db,object(),limit=10,now_ms=100,time_budget_sec=.01))=={'RETRY_HISTORY':1}
    assert sum(r['status']=='PENDING_RECONSTRUCTION' for r in samples(db))==2
    assert rei_v3.reconstruction_progress(db,now_ms=100)['latest_batches']['signal']['stop_reason']=='HISTORY_TIME_BUDGET'
    calls=[]
    async def limited(*a,**k):calls.append(1);raise rei_v3_market.HistoryError('RATE_LIMIT_RETRY_LATER')
    monkeypatch.setattr(rei_v3_market,'reconstruct',limited)
    assert asyncio.run(reconstruct_pending(db,object(),now_ms=200))=={'RETRY_HISTORY':1}
    assert asyncio.run(reconstruct_pending(db,object(),now_ms=300))=={}
    assert len(calls)==1
    assert sum(r['status']=='PENDING_RECONSTRUCTION' for r in samples(db))==1


def test_new_late_observations_not_recent_and_existing_daily_model_bytes_frozen(db,tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'source.db');init_intelligence()
    with storage._connect() as source:
        put_cohort(source,cohort());source.commit()
        rei_v3.observe(db,source,now_ms=200_000)
    frozen=list(db.execute('SELECT model_id,payload FROM rei_v3_models'))
    p=json.loads(db.execute('SELECT payload FROM rei_v3_predictions').fetchone()[0])
    assert p['status']=='HISTORICAL_OBSERVED_LATE' and p['score'] is None and not p['forward_eligible']
    assert rei_v3.overview(db,now_ms=200_000)['recent']==[]
    for r in training_rows():insert(db,r)
    rei_v3.frozen_models(db,samples(db),200_000)
    assert frozen==list(db.execute('SELECT model_id,payload FROM rei_v3_models'))
