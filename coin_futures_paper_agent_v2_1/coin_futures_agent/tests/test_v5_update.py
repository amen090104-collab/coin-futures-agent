"""V5 direct package/approval/transaction regressions. All data/releases are fixtures."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import zipfile
import pytest
import v5_update as v5
from v5_package import materialize, verify_folder, INFO, SOURCES, sha256, APP_SUBDIR
from build_v5_package import build, verify
from local_update import UpdateError, V2_BASE
from local_agent import atomic_json
from safe_preupdate_backup import backup_bundle

APP=Path(__file__).resolve().parents[1]
PIN='a'*40


@pytest.fixture
def home(tmp_path):
    root=tmp_path/'Agent người dùng có dấu';root.mkdir()
    materialize(root,PIN,lambda name:(APP/name).read_bytes())
    (root/'.env').write_bytes(b'REVERSE_ENTRY_V3_ENABLED=false\nFIXTURE_PRIVATE=do-not-log\n')
    (root/'run.bat').write_bytes(b'@echo off\r\necho old V2\r\n')
    (root/'chay_agent_v2.bat').write_bytes(b'@echo off\r\necho personal V2 launcher\r\n')
    (root/'ghi chu.txt').write_text('Không sửa file này',encoding='utf-8')
    (root/'reports').mkdir();(root/'reports'/'old.md').write_bytes(b'Historical fixture')
    with closing(sqlite3.connect(root/'agent.db')) as db:
        db.execute('CREATE TABLE trades(id INTEGER PRIMARY KEY,net_r REAL)')
        db.execute('INSERT INTO trades VALUES(1,1.5)');db.commit()
    return root


def updater(home):
    u=v5.V5Updater(home,package_root=home)
    def git(*args,**kwargs):
        if args[:2]==('rev-parse','HEAD'):return V2_BASE
        raise AssertionError('Unexpected fixture Git call')
    u.git=git
    return u


def release():
    return {'tag_name':'v5.0.0','body':json.dumps({'approved_release':{'sha':PIN,'reviewed':True,
        'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/99'},
        'acceptance':{'code_sha':PIN,'windows_user_copy':True,'verified_market_windows':3,
            'ready_signal_records':1,'point_in_time_verified':True,
            'review_evidence_url':'https://github.com/amen090104-collab/coin-futures-agent/issues/20#issuecomment-1',
            'fixture_only':True}})}


def public_api(u,payload,*,merged=True,green=True):
    def api(path):
        if path=='releases/latest':return payload
        if path=='pulls/99':return {'merged_at':'FIXTURE_ONLY' if merged else None,'head':{'sha':PIN}}
        if path=='commits/'+PIN+'/check-runs':
            return {'check_runs':[{'name':name,'app':{'slug':'github-actions'},'status':'completed',
                'conclusion':'success' if green else 'failure'} for name in (
                'test (ubuntu-latest, Python 3.12)','test (windows-latest, Python 3.13.5)')]}
        raise AssertionError('Unexpected public API path')
    u.api=api


@pytest.mark.parametrize('field,value',[('windows_user_copy',False),('verified_market_windows',2),
    ('ready_signal_records',0),('point_in_time_verified',False),('code_sha','b'*40),('review_evidence_url','https://example.com/not-reviewed')])
def test_v5_approval_requires_measured_acceptance_not_renamed_v3(home,field,value):
    u=updater(home);payload=release();body=json.loads(payload['body']);body['acceptance'][field]=value
    payload['body']=json.dumps(body);public_api(u,payload)
    with pytest.raises(UpdateError,match='ACCEPTANCE_PENDING'):u.approved()


@pytest.mark.parametrize('merged,green',[(False,True),(True,False)])
def test_v5_requires_merged_review_and_both_ci_checks(home,merged,green):
    u=updater(home);public_api(u,release(),merged=merged,green=green)
    with pytest.raises(UpdateError):u.approved()


def test_unapproved_v5_preserves_v2_without_intermediate(home,monkeypatch,capsys):
    u=updater(home);public_api(u,None);monkeypatch.setattr(u,'prerequisites',lambda:None)
    before={p:p.read_bytes() for p in (home/'.env',home/'agent.db',home/'run.bat',home/'chay_agent_v2.bat')}
    assert u.update()=='NO_APPROVED_V5_RELEASE_KEEP_V2'
    assert all(p.read_bytes()==data for p,data in before.items())
    assert not u.installed.exists() and not u.journal.exists()
    assert 'do-not-log' not in capsys.readouterr().out
    public_api(u,{**release(),'tag_name':'local-v3.0.0'});assert u.approved() is None
    atomic_json(u.installed,{'sha':PIN,'code':'fixture-installed-v5','python':os.sys.executable})
    assert u.update()=='V5_NO_NEWER_APPROVED_RELEASE_CURRENT_VERSION_PRESERVED'
    assert json.loads(u.installed.read_text())['sha']==PIN
    assert all(p.read_bytes()==data for p,data in before.items())


def test_first_install_pin_matches_package(home):
    u=updater(home);public_api(u,release());assert u.approved()['sha']==PIN
    u.package['source_sha']='b'*40
    with pytest.raises(UpdateError,match='ACCEPTANCE_PENDING'):u.approved()


def prepare_transaction(u,home,tmp_path):
    backup=backup_bundle(home);code=tmp_path/'candidate-code';code.mkdir()
    for source in SOURCES.values():(code/source).write_bytes((APP/source).read_bytes())
    candidate={'sha':PIN,'code':str(code),'python':os.sys.executable}
    extra=u.transaction_extra(backup,candidate)
    return {'phase':'PREPARED','backup':backup.relative_to(home).as_posix(),
         'old':u.current(),'candidate':candidate,**extra}


def test_launcher_backup_restore_preserves_personal_script(home,tmp_path):
    u=updater(home);before={name:(home/name).read_bytes() for name in ('run.bat','chay_agent_v2.bat')}
    txn=prepare_transaction(u,home,tmp_path);u.apply_transaction(txn)
    assert all((home/name).read_bytes()==v5.launcher('run',PIN) for name in before)
    u.restore_transaction(txn)
    assert all((home/name).read_bytes()==data for name,data in before.items())
    assert not (home/'QUAY_LAI_BAN_CU.bat').exists()
    assert (home/'ghi chu.txt').read_text(encoding='utf-8')=='Không sửa file này'


def test_corruption_and_concurrent_launcher_edit_block_restore(home,tmp_path):
    u=updater(home);txn=prepare_transaction(u,home,tmp_path);u.apply_transaction(txn)
    (home/'chay_agent_v2.bat').write_bytes(b'new user edit');before=(home/'run.bat').read_bytes()
    with pytest.raises(UpdateError,match='CHANGED_RESTORE_BLOCKED'):u.restore_transaction(txn)
    assert (home/'run.bat').read_bytes()==before
    (home/'chay_agent_v2.bat').write_bytes(v5.launcher('run',PIN))
    (home/txn['backup']/'v5-launchers'/'run.bat').write_bytes(b'corrupt backup')
    with pytest.raises(UpdateError,match='BACKUP_CHECKSUM'):u.restore_transaction(txn)
    assert (home/'run.bat').read_bytes()==before


def test_interrupted_update_restores_data_launchers_and_pointer(home,tmp_path,monkeypatch):
    u=updater(home);original=(home/'run.bat').read_bytes();txn=prepare_transaction(u,home,tmp_path)
    atomic_json(u.journal,txn);u.apply_transaction(txn);atomic_json(u.installed,txn['candidate'])
    with closing(sqlite3.connect(home/'agent.db')) as db:db.execute('DELETE FROM trades');db.commit()
    monkeypatch.setattr(u,'stop',lambda:False)
    assert u.recover()
    assert json.loads(u.installed.read_text())==txn['old'] and (home/'run.bat').read_bytes()==original
    with closing(sqlite3.connect(home/'agent.db')) as db:assert db.execute('SELECT COUNT(*) FROM trades').fetchone()[0]==1


def test_modified_installed_source_rejected_before_start(home):
    u=updater(home);code=u.state/'releases'/PIN/'code';code.mkdir(parents=True)
    (code/'main.py').write_bytes(b'reviewed code')
    atomic_json(code.parent/'SOURCE_CHECKSUMS.json',{'sha':PIN,'files':{'main.py':sha256(b'reviewed code')}})
    atomic_json(code/'.build-info.json',{'sha':PIN,'version':'5.0.0'})
    install={'code':str(code),'sha':PIN};u.verify_install(install)
    (code/'main.py').write_bytes(b'changed since install')
    with pytest.raises(UpdateError,match='SOURCE_CHANGED'):u.verify_install(install)


def test_package_tamper_rejected(home):
    (home/'.v5-update/local_agent.py').write_bytes(b'changed helper')
    with pytest.raises(ValueError,match='CHECKSUM'):verify_folder(home)


def test_builder_git_pin_allowlist_and_reproducibility(tmp_path):
    repo=tmp_path/'repo';source=repo/APP_SUBDIR;source.mkdir(parents=True)
    for name in SOURCES.values():(source/name).write_bytes((APP/name).read_bytes())
    def git(*args):return subprocess.run(['git',*args],cwd=repo,capture_output=True,text=True,check=True).stdout.strip()
    git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
    git('add','.');git('commit','-m','fixture-only');sha=git('rev-parse','HEAD')
    a=tmp_path/'a.zip';b=tmp_path/'b.zip'
    manifest=build(a,expected_sha=sha,root=repo);build(b,expected_sha=sha,root=repo)
    assert a.read_bytes()==b.read_bytes() and len(manifest['files'])==7
    assert verify(a,expected_sha=sha,root=repo)==manifest
    with zipfile.ZipFile(a) as z:assert set(z.namelist())=={*SOURCES,INFO}
    with pytest.raises(ValueError,match='REVIEWED_HEAD'):build(tmp_path/'bad.zip',expected_sha='0'*40,root=repo)
