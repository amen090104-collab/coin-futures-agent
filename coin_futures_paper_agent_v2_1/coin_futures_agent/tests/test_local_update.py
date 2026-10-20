"""Offline updater failures and real local supervisor E2E; synthetic WAL data only."""
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import pytest

import local_update as update
from local_agent import FileLock, BusyError, atomic_json, locked
import safe_preupdate_backup as backup
import bootstrap_windows

APP = Path(__file__).resolve().parents[1]


@pytest.fixture
def install(tmp_path):
    root = tmp_path/'Nguoi dung Việt Nam'/'Trading Bot có dấu'
    root.mkdir(parents=True)
    (root/'.env').write_text('V44_SHADOW_ENABLED=false\nREPORTS_DIR=reports\n', encoding='utf-8')
    (root/'reports'/'old day').mkdir(parents=True)
    (root/'reports'/'old day'/'report.md').write_text('lịch sử', encoding='utf-8')
    with sqlite3.connect(root/'agent.db') as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE original_trades(id INTEGER PRIMARY KEY, net_r REAL)')
        db.execute('INSERT INTO original_trades VALUES(1,1.5)')
    db.close()
    (root/'approved_release.json').write_text(json.dumps({'manifest_version':1, 'approved_release':None}), encoding='utf-8')
    return root


def test_bundle_captures_committed_wal_env_reports_extra_db_and_restore(install):
    source=sqlite3.connect(install/'agent.db')
    source.execute('INSERT INTO original_trades VALUES(2,-1)')
    source.commit()
    with sqlite3.connect(install/'extra.db') as db:
        db.execute('CREATE TABLE additional(x)')
    path=backup.backup_bundle(install,extra_databases=['extra.db'])
    manifest=backup.verify_bundle(path)
    assert len(manifest['databases'])==2
    assert (path/'reports'/'old day'/'report.md').read_text(encoding='utf-8')=='lịch sử'
    source.close()
    with sqlite3.connect(install/'agent.db') as db:
        db.execute('DELETE FROM original_trades')
    backup.restore_bundle(install,path)
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT COUNT(*) FROM original_trades').fetchone()[0]==2
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_backup_failure_has_no_complete_manifest_or_update(install,monkeypatch):
    def broken(*a,**k): raise OSError('synthetic disk failure')
    monkeypatch.setattr(backup.shutil,'copy2',broken)
    with pytest.raises(OSError): backup.backup_bundle(install)
    assert not list((install/'backups').rglob('backup.json'))
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT COUNT(*) FROM original_trades').fetchone()[0]==1


def test_corrupted_backup_rejected_before_any_restore(install):
    path=backup.backup_bundle(install)
    (path/'.env').write_text('changed',encoding='utf-8')
    before=(install/'agent.db').read_bytes()
    with pytest.raises(ValueError,match='CHECKSUM'):
        backup.restore_bundle(install,path)
    assert (install/'agent.db').read_bytes()==before


def test_locked_database_backup_deadline_preserves_original(install):
    # Rollback journal writer lock exercises SQLite backup BUSY callback and bounded timeout.
    with sqlite3.connect(install/'locked.db',timeout=.1) as con:
        con.execute('CREATE TABLE data(x)')
        con.commit()
        con.execute('BEGIN EXCLUSIVE')
        con.execute('INSERT INTO data VALUES(1)')
        with pytest.raises(TimeoutError):
            backup.snapshot_database(install/'locked.db',install/'snapshot.db',deadline_sec=.1)
        assert not (install/'snapshot.db').exists()


def test_process_lock_prevents_double_scheduler(install):
    path=install/'.agent-updater'/'agent.lock'
    with FileLock(path):
        assert locked(path)
        with pytest.raises(BusyError):
            with FileLock(path): pass
    assert not locked(path)


def configure(updater,monkeypatch):
    old={'sha':update.V2_BASE,'code':str(updater.root),'python':sys.executable}
    monkeypatch.setattr(updater,'prerequisites',lambda:None)
    monkeypatch.setattr(updater,'current',lambda:old)
    monkeypatch.setattr(updater,'data_paths',lambda:([],['reports']))
    monkeypatch.setattr(updater,'approved',lambda:{'sha':'a'*40,'reviewed':True,'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/19'})
    monkeypatch.setattr(updater,'stop',lambda:False)
    return old


def test_no_release_never_fetches_main_or_runs_install(install,monkeypatch):
    u=update.Updater(install)
    configure(u,monkeypatch)
    monkeypatch.setattr(u,'approved',lambda:None)
    monkeypatch.setattr(u,'stage',lambda *a:pytest.fail('No approved code must execute'))
    assert u.update()=='NO_NEWER_APPROVED_VERSION'
    assert not list((install/'backups').rglob('backup.json'))


def test_manifest_rejects_unreviewed_or_moving_ref(install):
    p=install/'approved_release.json'
    p.write_text(json.dumps({'manifest_version':1,'approved_release':{'sha':'main','reviewed':True}}))
    with pytest.raises(update.UpdateError,match='INVALID_APPROVED'):
        update.Updater(install).approved()


def test_published_release_requires_merged_review_and_both_platform_checks(install,monkeypatch):
    u=update.Updater(install)
    pin={'sha':'a'*40,'reviewed':True,'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/19'}
    checks=[{'name':f'test ({platform}, Python {version})','app':{'slug':'github-actions'},'status':'completed','conclusion':'success'}
            for platform,version in [('ubuntu-latest','3.12'),('windows-latest','3.13.5')]]
    responses={'releases/latest':{'tag_name':'local-v3.0.0','body':json.dumps({'approved_release':pin})},
               'pulls/19':{'merged_at':'2026-01-01','head':{'sha':'a'*40}},'commits/'+('a'*40)+'/check-runs':{'check_runs':checks}}
    monkeypatch.setattr(u,'api',lambda path:responses[path])
    assert u.approved()==pin
    checks[-1]['conclusion']='failure'
    with pytest.raises(update.UpdateError,match='CI_NOT_GREEN'): u.approved()
    checks[-1]['conclusion']='success'
    responses['pulls/19']['merged_at']=None
    with pytest.raises(update.UpdateError,match='NOT_REVIEWED'): u.approved()


def test_bootstrap_from_actual_5340114_branch_keeps_git_db_and_env(install,tmp_path):
    origin=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=APP,capture_output=True,text=True,check=True).stdout.strip()
    clone=tmp_path/'Bản cũ local V2'
    subprocess.run(['git','clone','--quiet','--no-checkout','--no-hardlinks',origin,str(clone)],check=True,capture_output=True)
    subprocess.run(['git','switch','-c','local-reverse-v2',update.V2_BASE],cwd=clone,check=True,capture_output=True)
    target=clone/update.APP_SUBDIR
    shutil.copy2(install/'agent.db',target/'agent.db')
    shutil.copy2(install/'.env',target/'.env')
    before=(target/'agent.db').read_bytes(),(target/'.env').read_bytes()
    folder=bootstrap_windows.install(target,tmp_path/'Desktop có dấu',source=APP)
    assert (folder/'local_update.py').is_file()
    u=update.Updater(target)
    assert u.current()['sha']==update.V2_BASE
    assert not u.git('status','--porcelain','--','.',':(exclude).agent-updater')
    assert before==((target/'agent.db').read_bytes(),(target/'.env').read_bytes())


@pytest.mark.parametrize('failure',['offline','migration','backup'])
def test_prestart_failure_preserves_local_data(install,monkeypatch,failure):
    u=update.Updater(install)
    configure(u,monkeypatch)
    before=(install/'.env').read_bytes()
    def fail(*a,**k): raise update.UpdateError('SIMULATED_FAILURE')
    monkeypatch.setattr(u,'stage',fail if failure=='offline' else lambda *a:{'sha':'a'*40,'code':str(install),'python':sys.executable})
    monkeypatch.setattr(u,'probe',fail if failure=='migration' else lambda *a:True)
    if failure=='backup': monkeypatch.setattr(update,'backup_bundle',fail)
    monkeypatch.setattr(u,'start',lambda *a:pytest.fail('Must not start'))
    with pytest.raises(update.UpdateError): u.update()
    assert before==(install/'.env').read_bytes()
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT * FROM original_trades').fetchall()==[(1,1.5)]
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_failed_health_rolls_back_writes_and_installed_pointer(install,monkeypatch):
    u=update.Updater(install)
    old=configure(u,monkeypatch)
    monkeypatch.setattr(u,'stage',lambda *a:{'sha':'a'*40,'code':str(install),'python':sys.executable})
    monkeypatch.setattr(u,'probe',lambda *a:True)
    def start(*a):
        with sqlite3.connect(install/'agent.db') as db:
            db.execute('INSERT INTO original_trades VALUES(99,-50)')
        return object()
    monkeypatch.setattr(u,'start',start)
    monkeypatch.setattr(u,'healthy',lambda *a:False)
    monkeypatch.setattr(u,'stop_child',lambda *a:None)
    with pytest.raises(update.UpdateError,match='HEALTH'):
        u.update()
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT id FROM original_trades').fetchall()==[(1,)]
    assert json.loads(u.installed.read_text())==old
    assert json.loads(u.journal.read_text())['phase']=='ROLLED_BACK'


def test_interrupted_transaction_restores_before_any_new_update(install,monkeypatch):
    u=update.Updater(install)
    old=configure(u,monkeypatch)
    path=backup.backup_bundle(install)
    atomic_json(u.journal,{'phase':'PREPARED','backup':path.relative_to(install).as_posix(),'old':old})
    with sqlite3.connect(install/'agent.db') as db:
        db.execute('DELETE FROM original_trades')
    assert u.update()=='RECOVERED_INTERRUPTED_UPDATE'
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT COUNT(*) FROM original_trades').fetchone()[0]==1


def test_successful_rollback_preserves_trades_created_after_upgrade(install,monkeypatch):
    u=update.Updater(install)
    old=configure(u,monkeypatch)
    atomic_json(u.journal,{'phase':'COMMITTED','old':old})
    with sqlite3.connect(install/'agent.db') as db:
        db.execute('INSERT INTO original_trades VALUES(2,3)')
    assert u.rollback().startswith('CODE_ROLLED_BACK')
    with sqlite3.connect(install/'agent.db') as db:
        assert db.execute('SELECT COUNT(*) FROM original_trades').fetchone()[0]==2


def test_dirty_repo_git_absent_and_low_disk_stop_early(install,monkeypatch):
    u=update.Updater(install)
    monkeypatch.setattr(update.shutil,'which',lambda *a:None)
    with pytest.raises(update.UpdateError,match='GIT_NOT'):
        u.prerequisites()
    monkeypatch.setattr(update.shutil,'which',lambda *a:'git')
    monkeypatch.setattr(u,'git',lambda *a:' M app/main.py')
    with pytest.raises(update.UpdateError,match='DIRTY'):
        u.prerequisites()
    monkeypatch.setattr(u,'git',lambda *a:'' if a[0]=='status' else 'https://github.com/amen090104-collab/coin-futures-agent.git')
    monkeypatch.setattr(update.shutil,'disk_usage',lambda *a:type('Disk',(),{'free':1})())
    with pytest.raises(update.UpdateError,match='2GB'):
        u.prerequisites()


def test_external_report_path_and_traversal_not_silently_omitted(install):
    (install/'.env').write_text('REPORTS_DIR=../private-reports\n',encoding='utf-8')
    with pytest.raises(ValueError,match='UNSAFE'):
        update.Updater(install).data_paths()


def test_unmanaged_listener_is_not_killed(install,monkeypatch):
    monkeypatch.setattr(update,'port_open',lambda:True)
    with pytest.raises(update.UpdateError,match='UNMANAGED'):
        update.Updater(install).stop()


def test_real_supervisor_health_graceful_stop_and_unicode_paths(install,monkeypatch):
    """Runs on Windows 3.13.5 CI too. Fixture ASGI app, no trading/scheduler/network jobs."""
    # Permit only loopback for this test, including under the suite's external-network blocker.
    import _socket
    native_connect=_socket.socket.connect
    def loopback(sock,address):
        assert address[0]=='127.0.0.1'
        return native_connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        selected_port=reservation.getsockname()[1]
    monkeypatch.setenv('AGENT_LOCAL_PORT',str(selected_port))
    code=install/'.agent-updater'/'releases'/('a'*40)/'code'
    (code/'app').mkdir(parents=True)
    shutil.copy2(APP/'local_agent.py',code/'local_agent.py')
    (code/'app'/'__init__.py').write_text('')
    (code/'app'/'main.py').write_text(
        'import os\nfrom fastapi import FastAPI\napp=FastAPI()\n'
        '@app.get("/local/health")\ndef health():\n'
        ' return {"ok":True,"release_sha":os.environ["AGENT_RELEASE_SHA"],"pid":os.getpid()}\n',encoding='utf-8')
    u=update.Updater(install)
    candidate={'sha':'a'*40,'code':str(code),'python':sys.executable}
    atomic_json(u.installed,candidate)
    child=u.start(candidate)
    try:
        assert u.healthy(child,'a'*40,wait_sec=15)
        assert locked(u.state/'agent.lock')
        assert u.stop(wait_sec=15)
        child.wait(timeout=10)
        assert child.returncode==0
        assert not locked(u.state/'agent.lock') and not update.port_open()
    finally:
        if child.poll() is None:
            u.stop_child(child)


def test_update_transaction_e2e_with_real_supervisor_and_wal_fixture(install,monkeypatch):
    """Full backup/probe/switch/start/health/rollback path; staging substitutes an offline reviewed fixture."""
    import _socket
    native_connect=_socket.socket.connect
    def loopback(sock,address):
        assert address[0]=='127.0.0.1'
        return native_connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    monkeypatch.setenv('AGENT_LOCAL_PORT',str(port))
    u=update.Updater(install)
    old=configure(u,monkeypatch)
    code=u.state/'releases'/('a'*40)/'code'
    (code/'app').mkdir(parents=True)
    shutil.copy2(APP/'local_agent.py',code/'local_agent.py')
    (code/'app'/'__init__.py').write_text('')
    # Legacy fixture deliberately lacks /local/health: supervisor provides identity in memory.
    (code/'app'/'main.py').write_text('from fastapi import FastAPI\napp=FastAPI()\n',encoding='utf-8')
    candidate={'sha':'a'*40,'code':str(code),'python':sys.executable}
    monkeypatch.setattr(u,'stage',lambda *a:candidate)
    def probe(*a):
        assert backup.verify_bundle(a[1])['databases']
        from release_probe import probe as actual_probe
        assert actual_probe(a[1])
    monkeypatch.setattr(u,'probe',probe)
    monkeypatch.setattr(update.webbrowser,'open',lambda *a:True)
    try:
        assert u.update()=='UPDATED'
        assert json.loads(u.installed.read_text())['sha']=='a'*40
        assert json.loads(u.journal.read_text())['phase']=='COMMITTED'
        with sqlite3.connect(install/'agent.db') as db:
            assert db.execute('SELECT * FROM original_trades').fetchall()==[(1,1.5)]
        u.stop_child(u.child)
        assert u.rollback().startswith('CODE_ROLLED_BACK')
        assert json.loads(u.installed.read_text())==old
    finally:
        if hasattr(u,'child') and u.child.poll() is None:
            u.stop_child(u.child)


@pytest.mark.skipif(os.name!='nt',reason='CMD launcher is exercised by Windows 3.13.5 CI')
def test_windows_cmd_launcher_quotes_unicode_directory(install):
    for name in ('WINDOWS_AGENT.bat','CAP_NHAT_AGENT.bat'):
        shutil.copy2(APP/name,install/name)
    (install/'local_update.py').write_text('from pathlib import Path\nPath("launcher-ok").write_text("ok")\n',encoding='utf-8')
    result=subprocess.run(['cmd','/d','/c',str(install/'CAP_NHAT_AGENT.bat')],cwd=install,input=b'\n',capture_output=True,timeout=20)
    assert result.returncode==0 and (install/'launcher-ok').is_file()
