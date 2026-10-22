"""Clock/learning/execution fixtures. Synthetic outcomes are NOT measured user profitability."""
import asyncio
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from app.config import settings
from app.rei_v3_store import init, samples, insert
from app.rei_v3_learning import fit as legacy_fit, DAY, EMBARGO, holdout
from app.rei_v3_models import train, frozen, research_baseline, calibrated_score
from app.rei_v3_decisions import (make_decision, create_order, init_orders, advance_orders,
                                  order_summary, policy_evidence)
from app.reverse_intelligence import digest
from test_rei_v3 import training_rows, db
from test_issue22_diagnostics import cohort


def issue24_rows():
    start=1760486400000//DAY*DAY
    imported=start+15*DAY+12*3600000
    rows=[]
    for side,counts in [('SHORT',[12]*8+[5,29,29]),('LONG',[7]*8+[9,1,1])]:
        for d,n in enumerate(counts):
            for i in range(n):
                r=copy.deepcopy(training_rows(1,1)[0]);signal=start+d*DAY+2*3600000+i*60000
                good=i%2==0
                r.update(sample_id=f'{side}-{d}-{i}',group_id=f'{side}-{d}-{i}',source_side=side,
                    reverse_side='LONG' if side=='SHORT' else 'SHORT',decision_ms=signal,entry_ms=signal+60000,
                    closed_ms=signal+3600000,historical_label_known_ms=signal+3600000,label_available_ms=imported,
                    net_r=1.8 if good else -1.1)
                r['features'].update(rsi_1h=35. if good else 65.)
                r['feature_provenance']={'max_source_ms':signal-1,'status':'RECONSTRUCTED','usable_at_original_signal':True}
                rows.append(r)
    return rows,imported


def test_real_diagnostic_clock_shape_old_zero_fit_new_future_training_and_retro_are_separate():
    rows,arrival=issue24_rows();now=arrival+2*3600000
    old=legacy_fit(rows,asof_ms=now,side='SHORT')
    assert old['fit_n']==0 and old['split_purged_n']==101
    retro=train(rows,frozen_at_ms=now,side='SHORT',kind='HISTORICAL_RESEARCH_MODEL')
    online=train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    assert retro['fit_n']==online['fit_n']==101
    assert retro['calibration_n']==online['calibration_n']==58
    assert online['fit_days']==9 and online['status']=='RESEARCH_CLASSIFIER' and online['calibrated']
    assert online['max_fit_closed_ms']<online['calibration_start_ms']-EMBARGO
    assert online['max_label_ms']<online['frozen_at_ms']-EMBARGO
    assert online['max_label_ms']>online['calibration_start_ms']  # Honest imported-label training NOW.
    assert online['first_forward_decision_ms']==now and not online['forward_oos_validated']
    long=train(rows,frozen_at_ms=now,side='LONG',kind='FORWARD_FROZEN_MODEL')
    assert long['fit_n']==65 and long['calibration_n']==2
    assert 'INSUFFICIENT_CALIBRATION_SAMPLES' in long['reason_codes'] and calibrated_score(long,rows[0]['features']) is None


def test_same_day_arrival_midnight_embargo_and_late_labels_never_backdated(db):
    rows,arrival=issue24_rows()
    for now in (arrival-1,arrival,arrival+EMBARGO):
        assert train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')['training_n']==0
    after=train(rows,frozen_at_ms=arrival+EMBARGO+1,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    assert after['status']=='RESEARCH_CLASSIFIER'
    midnight=(arrival//DAY+1)*DAY
    assert train(rows,frozen_at_ms=midnight,side='SHORT',kind='FORWARD_FROZEN_MODEL')['max_label_ms']<midnight-EMBARGO
    future=copy.deepcopy(rows)
    for r in future:r['label_available_ms']=midnight+DAY
    assert train(future,frozen_at_ms=midnight,side='SHORT',kind='FORWARD_FROZEN_MODEL')['training_n']==0
    assert train(future,frozen_at_ms=midnight,side='SHORT',kind='HISTORICAL_RESEARCH_MODEL')['training_n']>0


def test_only_valid_models_frozen_attempts_can_resume_legacy_and_forward_bytes_immutable(db):
    rows,arrival=issue24_rows()
    db.execute("INSERT INTO rei_v3_models VALUES('daily-old',?,'SHORT',?)",(arrival,'{"training_n":2,"status":"INSUFFICIENT_DATA"}'));db.commit()
    frozen(db,rows,now_ms=arrival)
    assert db.execute('SELECT COUNT(*) FROM rei_v3_models').fetchone()[0]==1
    models=frozen(db,rows,now_ms=arrival+2*3600000)
    assert models['SHORT']['calibrated']
    before=[tuple(r) for r in db.execute('SELECT * FROM rei_v3_models ORDER BY model_id')]
    mutated=copy.deepcopy(rows)
    for r in mutated:r['net_r']=-1000
    assert frozen(db,mutated,now_ms=arrival+3*3600000)['SHORT']['model_id']==models['SHORT']['model_id']
    assert before==[tuple(r) for r in db.execute('SELECT * FROM rei_v3_models ORDER BY model_id')]


def test_group_holdout_future_features_and_one_class_do_not_create_scores():
    rows,arrival=issue24_rows();now=arrival+2*3600000
    a=train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    variants=[{**r,'sample_id':r['sample_id']+'-RR3','label_policy':'REVERSE_RR3'} for r in rows]
    b=train(rows+variants,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    assert a['model_id']==b['model_id']
    short=[r for r in rows if r['source_side']=='SHORT']
    held={short[0]['group_id']}
    m=train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL',excluded_groups=held)
    assert held.isdisjoint(m['fit_groups']+m['calibration_groups'])
    bad=copy.deepcopy(rows)
    for r in bad:r['feature_provenance']['max_source_ms']=r['decision_ms']+1
    assert train(bad,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')['training_n']==0
    for r in rows:r['net_r']=1.
    one=train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    assert one['status']=='INSUFFICIENT_DATA' and 'FIT_ONE_CLASS' in one['reason_codes']


def test_pinned_research_baseline_chronological_holdout_is_not_forward_profit():
    rows=training_rows(24,8);now=rows[-1]['label_available_ms']+DAY
    held=holdout(rows);b=research_baseline(rows,now_ms=now,held=held)
    assert b['manifest']['dataset_digest'] and b['manifest']['manifest_id']
    assert not b['manifest']['forward_oos_validated']
    assert b['per_side']['LONG']['HELD_OUT_RETROSPECTIVE']['scored']>0
    mutated=copy.deepcopy(rows)
    for r in mutated:
        if r['group_id'] in held:r['net_r']=-1000
    c=research_baseline(mutated,now_ms=now,held=held)
    assert b['models']['LONG']['model_id']==c['models']['LONG']['model_id']
    assert [(p['sample_id'],p['score']) for p in b['predictions']]==[(p['sample_id'],p['score']) for p in c['predictions']]


@pytest.fixture
def qualified(monkeypatch):
    from app import rei_v3_decisions as decisions
    rows,arrival=issue24_rows();now=arrival+2*3600000
    m=train(rows,frozen_at_ms=now,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    r=cohort(observed=now);r.update(source_side='SHORT',btc_regime='NEUTRAL',
        risk_snapshot={'observed_at_ms':now,'news_allowed':True},
        costs={'fee_bps':5.,'slippage_bps':2.,'max_hold_hours':36.})
    r['quality']['plan_gate_reason']='PLAN_OK'
    # This fixture tests execution admission, not proof of a real model edge.
    monkeypatch.setattr(decisions,'predict',lambda *a,**k:{'action':'REVERSE_NOW'})
    monkeypatch.setattr(settings,'reverse_entry_v3_shadow_execution_enabled',True)
    monkeypatch.setattr(settings,'reverse_entry_v3_max_open',3)
    return r,m,{'policy':{},'evidence':{'qualified':True,'fixture_only':True}},now


@pytest.mark.parametrize('base',['LONG','SHORT'])
def test_clear_reverse_plan_qualified_shadow_and_no_effect_on_paper(db,qualified,base):
    r,m,p,now=qualified;r['source_side']=base
    # Model direction must match its Base side, never silently swap weights.
    if base=='LONG':
        rows=training_rows(16,8);m=train(rows,frozen_at_ms=now,side='LONG',kind='FORWARD_FROZEN_MODEL')
    d=make_decision(r,m,p,now_ms=now+1)
    assert d['qualified'] and d['action']==('REVERSE_SHORT' if base=='LONG' else 'REVERSE_LONG')
    plan=d['candidate_plan'];assert plan['reward_risk']==2. and plan['entry_is_reference_not_fill']
    if base=='LONG':assert plan['stop_loss']>plan['entry']>plan['take_profit']
    else:assert plan['stop_loss']<plan['entry']<plan['take_profit']
    init_orders(db);db.execute('CREATE TABLE paper_balance(x)');db.execute('INSERT INTO paper_balance VALUES(10000)')
    assert create_order(db,r,d) and not create_order(db,r,d)
    db.execute('CREATE TABLE rei_v2_bars(symbol,open_time_ms,first_seen_at_ms,sha256,payload_json)')
    first=(now//60000+1)*60000
    bar={'open_time':first,'close_time':first+59999,'open':100.,'high':103.,'low':97.,'close':100.}
    db.execute('INSERT INTO rei_v2_bars VALUES(?,?,?,?,?)',('TESTUSDT',first,first+60000,digest(bar),json.dumps(bar)))
    advance_orders(db,now_ms=first+60001)
    summary=order_summary(db)
    assert summary['closed']==1 and summary['performance']['expectancy_r']<-1  # stop first + fees/slippage
    assert db.execute('SELECT x FROM paper_balance').fetchone()[0]==10000


@pytest.mark.parametrize('failure',['optin','news','regime','capacity','late','entry_window','plan','costs','policy','wrong_model'])
def test_exact_admission_gates_never_force_orders(db,qualified,monkeypatch,failure):
    r,m,p,now=qualified;active=0;at=now+1
    if failure=='optin':monkeypatch.setattr(settings,'reverse_entry_v3_shadow_execution_enabled',False)
    if failure=='news':r['risk_snapshot']['news_allowed']=False
    if failure=='regime':r['btc_regime']='UNKNOWN'
    if failure=='capacity':active=3
    if failure=='late':at=now+60001
    if failure=='entry_window':at=(now//60000+1)*60000
    if failure=='plan':r['quality_ok']=False;r['quality']['plan_gate_reason']='SCORE_BELOW_THRESHOLD'
    if failure=='costs':r['costs']['fee_bps']=None
    if failure=='policy':p['evidence']['qualified']=False
    if failure=='wrong_model':m['model_kind']='HISTORICAL_RESEARCH_MODEL'
    d=make_decision(r,m,p,now_ms=at,active_count=active)
    assert not d['qualified'] and d['action']=='NO_TRADE' and d['reason_codes']
    init_orders(db);assert not create_order(db,r,d)
    assert db.execute('SELECT COUNT(*) FROM rei_v3_orders').fetchone()[0]==0
    if failure=='late':assert d['score'] is None


def test_wait_confirmation_and_no_matching_oos_evidence_remain_explicit(qualified,monkeypatch):
    from app import rei_v3_decisions as decisions
    r,m,p,now=qualified
    monkeypatch.setattr(decisions,'predict',lambda *a,**k:{'action':'WAIT_CONFIRMATION'})
    assert make_decision(r,m,p,now_ms=now+1)['action']=='WAIT_CONFIRMATION'
    evidence=policy_evidence([],side='SHORT',now_ms=now)
    assert not evidence['qualified'] and evidence['scored_cohorts']==0
    assert not evidence['gates']['OOS_MIN_COHORTS'] and not evidence['gates']['OOS_BASE_DELTA_CI_POSITIVE']


def test_windows_learning_fixture_evidence_is_labelled_synthetic():
    import os
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.name!='nt':return
    rows,arrival=issue24_rows();m=train(rows,frozen_at_ms=arrival+2*3600000,side='SHORT',kind='FORWARD_FROZEN_MODEL')
    out=Path('v51-test-evidence');out.mkdir(exist_ok=True)
    (out/'learning-fixture.json').write_text(json.dumps({'fixture_only':True,'source':'synthetic clock shape from Issue #24, not user DB',
        'SHORT':{k:m[k] for k in ('status','fit_n','calibration_n','fit_days','frozen_at_ms','max_label_ms','calibrated')},
        'real_user_model_profitability_verified':False},indent=2),encoding='ascii')
