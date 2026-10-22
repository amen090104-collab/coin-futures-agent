import asyncio
import json
from pathlib import Path
import sqlite3
import pytest
from app import v5_acceptance as acceptance
from app.rei_v3_store import init, normalized, insert
from test_rei_v3 import original
from test_rei_v3_archives import archive_market


def test_measured_restoration_is_not_model_edge_or_shadow_enablement(tmp_path):
    db=sqlite3.connect(tmp_path/'fixture.db');db.row_factory=sqlite3.Row;init(db)
    row=normalized(original(stamp='2025-11-20T04:17:00Z'),origin='HISTORICAL_PAPER',key=('fixture',1),imported_ms=2_000_000_000_000)
    insert(db,row);db.commit()
    history,_=archive_market(db)
    result=asyncio.run(acceptance.measure(db,history=history))
    assert result['market']['verified_windows']==3 and result['ready_signal_records']==1
    assert result['point_in_time_verified']
    assert not result['model_edge_verified'] and not result['training_performed'] and not result['strategies_or_env_changed']
    assert result['restored_windows_proof'][0]['max_source_ms']<row['decision_ms']
    db.close()


def test_acceptance_requires_acknowledged_copy_before_reading_source(tmp_path,monkeypatch):
    source=tmp_path/'do-not-open.db';source.write_bytes(b'not a database; must not be read')
    out=tmp_path/'out'
    monkeypatch.setattr('sys.argv',['acceptance','--source-db',str(source),'--output-dir',str(out)])
    with pytest.raises(SystemExit) as exc:acceptance.main()
    assert exc.value.code==2 and not out.exists()


def test_acceptance_output_cannot_modify_source_report_tree(tmp_path,monkeypatch):
    reports=tmp_path/'reports';reports.mkdir();out=reports/'new-output'
    monkeypatch.setattr('sys.argv',['acceptance','--reports',str(reports),'--confirm-disposable-copy','--output-dir',str(out)])
    with pytest.raises(SystemExit) as exc:acceptance.main()
    assert exc.value.code==2 and not out.exists()


def test_ci_public_smoke_never_claims_user_copy_acceptance(tmp_path,monkeypatch):
    out=tmp_path/'out'
    async def fake_measure(*a,**k):
        return {'market':{'status':'VERIFIED','verified_windows':3,'release_market_evidence':True},
            'ready_signal_records':0,'point_in_time_verified':False,'model_edge_verified':False}
    monkeypatch.setenv('GITHUB_ACTIONS','true')
    monkeypatch.setattr(acceptance,'measure',fake_measure)
    monkeypatch.setattr('sys.argv',['acceptance','--output-dir',str(out),'--confirm-disposable-copy'])
    assert acceptance.main()==2
    evidence=json.loads((out/'acceptance.redacted.json').read_text(encoding='utf-8'))
    assert not evidence['windows_user_copy'] and not evidence['meets_measured_release_gates']
    assert evidence['not_release_authorization'] and evidence['input_kind']=='PUBLIC_MARKET_ONLY_NO_PRIVATE_HISTORY'
