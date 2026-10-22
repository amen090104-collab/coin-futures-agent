"""Approved updater unit regressions. All releases/credentials/source are synthetic."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import urllib.error
import zipfile

import pytest

import remote_release as protocol
import remote_update as remote
from local_agent import atomic_json
from local_update import UpdateError
from safe_preupdate_backup import backup_bundle
from v5_package import SOURCES
from test_v5_update import home, APP, PIN


def release(sha=PIN,tag='v5.1.0'):
    return {'tag_name':tag,'body':json.dumps({'manifest_version':2,'version':tag[1:],
        'execution_mode':'PAPER_SHADOW_ONLY','source_tree_sha256':'a'*64,
        'approved_release':{'sha':sha,'reviewed':True,'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/25'}})}


def api(payload=None,*,merged=True,green=True):
    def lookup(path):
        if path=='releases/latest':return payload
        if path=='pulls/25':return {'merged_at':'FIXTURE' if merged else None,'head':{'sha':PIN}}
        if path=='commits/'+PIN+'/check-runs':return {'check_runs':[{'id':5,'name':name,'status':'completed',
            'conclusion':'success' if green else 'failure','app':{'slug':'github-actions'}} for name in protocol.REQUIRED_CHECKS]}
        raise AssertionError('Unexpected fixture API')
    return lookup


@pytest.mark.parametrize('tag',['v5.1.0','v5.2.12','v5.10.0','v5.0.1'])
def test_release_protocol_accepts_semver_v5_and_does_not_require_fake_user_model_evidence(tag):
    r=release(tag=tag)
    out=protocol.approved(r,api(r))
    assert out['version']==tag[1:] and out['sha']==PIN
    assert out['acceptance']['model_profitability_verified'] is False
    assert protocol.version('v5.10.0')>protocol.version('v5.2.99')


@pytest.mark.parametrize('change',['draft','prerelease','unreviewed','unmerged','ci','checksum','wrongmode','badversion'])
def test_unapproved_release_never_reaches_stage(change):
    r=release();body=json.loads(r['body'])
    if change=='draft':r['draft']=True
    if change=='prerelease':r['prerelease']=True
    if change=='unreviewed':body['approved_release']['reviewed']=False
    if change=='checksum':body['source_tree_sha256']='not-a-hash'
    if change=='wrongmode':body['execution_mode']='REAL'
    if change=='badversion':body['version']='5.0.0'
    r['body']=json.dumps(body)
    if change in {'draft','prerelease'}:assert protocol.approved(r,api(r)) is None
    else:
        with pytest.raises(UpdateError):protocol.approved(r,api(r,merged=change!='unmerged',green=change!='ci'))


def test_latest_check_run_failure_cannot_be_masked_by_an_older_success():
    r=release();base=api(r)
    def lookup(path):
        result=base(path)
        if path.endswith('check-runs'):
            old=result['check_runs'][0]
            result['check_runs']=[{**old,'id':99,'conclusion':'failure'},*result['check_runs']]
        return result
    with pytest.raises(UpdateError,match='UNAPPROVED'):protocol.approved(r,lookup)


def test_private_repo_reuses_git_credentials_without_logging_or_env_files(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('GH_TOKEN',raising=False)
    github=protocol.GitHub(tmp_path);calls=[]
    def get(path,token=None):
        if token=='synthetic-private-token':return {'private':True}
        raise urllib.error.HTTPError('https://api.github.com',404,'fixture',None,None)
    def run(args,**kwargs):
        calls.append((args,kwargs))
        return subprocess.CompletedProcess(args,0,b'username=fixture\npassword=synthetic-private-token\n',b'')
    monkeypatch.setattr(github,'_get',get);monkeypatch.setattr(protocol.subprocess,'run',run)
    assert github.get('releases/latest')=={'private':True}
    assert calls[0][0]==['git','credential','fill'] and calls[0][1]['env']['GIT_TERMINAL_PROMPT']=='0'
    assert 'synthetic-private-token' not in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_public_repo_without_release_does_not_prompt_for_credentials(tmp_path,monkeypatch):
    github=protocol.GitHub(tmp_path)
    def get(path,token=None):
        if path=='':return {'private':False}
        raise urllib.error.HTTPError('https://api.github.com',404,'fixture',None,None)
    monkeypatch.setattr(github,'_get',get)
    monkeypatch.setattr(github,'_credentials',lambda:pytest.fail('No credential lookup for public/no release'))
    assert github.get('releases/latest') is None


def test_no_new_version_and_blocked_are_distinct_and_preserve_all_data(home,monkeypatch):
    u=remote.RemoteUpdater(home,package_root=home)
    monkeypatch.setattr(u,'prerequisites',lambda:None)
    u.current=lambda:{'sha':PIN,'code':str(home),'python':'fixture'}
    before={n:(home/n).read_bytes() for n in ('.env','agent.db','run.bat','update.bat')}
    u.api=api(None);assert u.update()=='UPDATE_BLOCKED_UNAPPROVED'
    u.api=api(release());assert u.update()=='NO_NEW_VERSION'
    assert all((home/n).read_bytes()==v for n,v in before.items())
    assert not u.journal.exists()


def test_source_digest_is_order_independent_and_tamper_changes_hash():
    def archive(records):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            for name,raw in records:z.writestr(name,raw)
        return out.getvalue()
    a=archive([('one.py',b'1'),('two.py',b'2')])
    b=archive([('two.py',b'2'),('one.py',b'1')])
    assert protocol.source_digest(a)==protocol.source_digest(b)
    assert protocol.source_digest(a)!=protocol.source_digest(archive([('one.py',b'changed'),('two.py',b'2')]))


def test_remote_launcher_backup_atomic_restore_and_stable_bytes(home,tmp_path,monkeypatch):
    u=remote.RemoteUpdater(home,package_root=home)
    u.current=lambda:{'sha':'b'*40,'code':str(home),'python':'fixture'}
    original={p:p.read_bytes() for p in (home/'update.bat',home/'run.bat',home/'chay_agent_v2.bat')}
    backup=backup_bundle(home);code=tmp_path/'code';code.mkdir()
    for source in (*SOURCES.values(),'update_driver.py'):(code/source).write_bytes((APP/source).read_bytes())
    candidate={'sha':PIN,'code':str(code),'python':'fixture'}
    extra=u.transaction_extra(backup,candidate)
    txn={'backup':backup.relative_to(home).as_posix(),'candidate':candidate,**extra}
    u.apply_transaction(txn)
    assert (home/'update.bat').read_bytes()==remote.stable_launcher('update')
    assert b'--from-package' not in (home/'update.bat').read_bytes()
    first=(home/'update.bat').read_bytes();u.apply_transaction(txn)
    assert (home/'update.bat').read_bytes()==first
    assert json.loads((home/'.agent-updater/updater.json').read_text())['sha']==PIN
    u.restore_transaction(txn)
    assert all(p.read_bytes()==v for p,v in original.items())
    assert not (home/'.agent-updater/update_driver.py').exists()


def test_downgrade_rebuild_and_failed_source_checksum_blocked_before_activation(home,tmp_path,monkeypatch):
    u=remote.RemoteUpdater(home,package_root=home)
    atomic_json(home/'.build-info.json',{'sha':'b'*40,'version':'5.1.0'})
    u.current=lambda:{'sha':'b'*40,'code':str(home)}
    with pytest.raises(UpdateError,match='DOWNGRADE'):u.stage({'sha':PIN,'version':'5.0.9'})
    with pytest.raises(UpdateError,match='DOWNGRADE'):u.stage({'sha':PIN,'version':'5.1.0'})
    from v5_update import V5Updater
    monkeypatch.setattr(V5Updater,'stage',lambda *a:{'sha':PIN,'code':str(tmp_path/'candidate')})
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:z.writestr('a.py','source')
    u.git=lambda *a,**k: raw.getvalue() if k.get('binary') else str(tmp_path)
    with pytest.raises(UpdateError,match='SOURCE_TREE_CHECKSUM'):
        u.stage({'sha':PIN,'version':'5.1.1','source_tree_sha256':'f'*64})
    assert not u.installed.exists() and not u.journal.exists()
