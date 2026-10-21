"""Direct ZIP on an actual V2 clone. Git/venv/pip/WAL/probe/real V5 health app/CMD are real.
Public release approval is a fixture; normal scheduler/trading lifespan never runs.
"""
from contextlib import closing
import gc
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import zipfile
import pytest

from app import storage
from app.battle_storage import init_battle_db, ensure_battle_initial_balances
from app.strategy_cases import init_strategy_cases
from app.reverse_research import init_reverse_lab
from build_v5_package import build
from local_agent import FileLock, locked
from local_update import V2_BASE, APP_SUBDIR, UpdateError
from test_local_update_e2e import OfflineLabUpdater, sql_snapshot
from v5_update import V5Updater, launcher
import v5_update

APP=Path(__file__).resolve().parents[1]


class DirectLabUpdater(V5Updater):
    create_environment=OfflineLabUpdater.create_environment
    install_dependencies=OfflineLabUpdater.install_dependencies

    def __init__(self,root,pin,mode,writer):
        super().__init__(root,package_root=root)
        self.pin,self.mode,self.writer=pin,mode,writer

    def git(self,*args,**kwargs):
        if args[:3]==('remote','get-url','origin'):
            return 'https://github.com/amen090104-collab/coin-futures-agent.git'
        return super().git(*args,**kwargs)

    def api(self,path):
        if path=='releases/latest':
            return {'tag_name':'v5.0.0','body':json.dumps({'approved_release':{'sha':self.pin,'reviewed':True,
                'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/99'},
                'acceptance':{'code_sha':self.pin,'windows_user_copy':True,'verified_market_windows':3,
                    'ready_signal_records':1,'point_in_time_verified':True,'fixture_only':True,
                    'review_evidence_url':'https://github.com/amen090104-collab/coin-futures-agent/issues/20#issuecomment-1'}})}
        if path=='pulls/99':return {'merged_at':'FIXTURE_ONLY','head':{'sha':self.pin}}
        if path=='commits/'+self.pin+'/check-runs':
            return {'check_runs':[{'name':name,'app':{'slug':'github-actions'},'status':'completed','conclusion':'success'} for name in (
                'test (ubuntu-latest, Python 3.12)','test (windows-latest, Python 3.13.5)')]}
        raise AssertionError('Unexpected public fixture API')

    def probe(self,candidate,backup):
        assert Path(str(self.root/'agent.db')+'-wal').stat().st_size>0
        self.writer.close()
        return super().probe(candidate,backup)

    def healthy(self,child,sha,**kwargs):
        result=super().healthy(child,sha,wait_sec=20)
        assert result, 'Real V5 health-only app must start before injecting a failure'
        self.health_verified=True
        return result and self.mode!='health_failure'


@pytest.mark.parametrize('mode',['success','health_failure','bad_migration','antivirus'])
def test_direct_v2_zip_update_real_health_launchers_and_safe_rollback(tmp_path_factory,monkeypatch,mode):
    tmp=tmp_path_factory.mktemp('v5')
    import _socket
    native=_socket.socket.connect
    def loopback(sock,address):
        assert address[0]=='127.0.0.1';return native(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback)
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    monkeypatch.setenv('AGENT_LOCAL_PORT',str(port))
    def git(*args,cwd=APP):return subprocess.run(['git',*args],cwd=cwd,capture_output=True,text=True,check=True).stdout.strip()
    repo=git('rev-parse','--show-toplevel');pin=git('rev-parse','HEAD')
    clone=tmp/'V2 người dùng';git('clone','--quiet','--no-hardlinks','--no-checkout',repo,str(clone))
    git('switch','-c','local-reverse-v2',V2_BASE,cwd=clone)
    root=clone/APP_SUBDIR
    monkeypatch.setattr(storage,'DB_PATH',root/'agent.db')
    storage.init_db();init_strategy_cases();init_battle_db();init_reverse_lab()
    storage.ensure_initial_balance('2026-10-08T00:00:00Z',10_000)
    ensure_battle_initial_balances('2026-10-08T00:00:00Z',10_000)
    writer=sqlite3.connect(root/'agent.db')
    trade={'id':1,'position_id':1,'strategy_id':'REVERSE_RR2','symbol':'TESTUSDT','side':'SHORT',
        'opened_at':'2026-10-08T00:01:00Z','closed_at':'2026-10-08T00:11:00Z','entry_price':100.,'exit_price':99.,
        'stop_loss':101.,'take_profit':98.,'quantity':1.,'score':80.,'gross_pnl':1.,'fees':.1,'net_pnl':.9,
        'r_multiple':.9,'exit_reason':'FIXTURE_ONLY','holding_minutes':10.,'mfe_r':1.,'mae_r':.1,
        'reason_text':'synthetic closed Reverse','reason_codes':'[]',
        'entry_context':json.dumps({'source_signal_side':'LONG','cohort_id':'2026-10-08T00:00:00Z::TESTUSDT'})}
    writer.execute('INSERT INTO battle_trades('+','.join(trade)+') VALUES('+','.join('?' for _ in trade)+')',tuple(trade.values()))
    if mode=='bad_migration':
        writer.execute('CREATE TABLE rei_v3_meta(schema_version INTEGER PRIMARY KEY,version TEXT)')
        writer.execute("INSERT INTO rei_v3_meta VALUES(99,'fixture-only')")
    writer.commit();gc.collect()
    (root/'.env').write_text('V44_SHADOW_ENABLED=false\nREVERSE_ENTRY_INTELLIGENCE_ENABLED=false\nREVERSE_ENTRY_V3_ENABLED=false\nREPORTS_DIR=reports_custom\n',encoding='utf-8')
    (root/'chay_agent_v2.bat').write_bytes(b'@echo off\r\necho old personal launcher\r\n')
    (root/'ghi chu.txt').write_text('Ghi chú cá nhân',encoding='utf-8')
    for folder in ('reports','reports_custom'):
        (root/folder).mkdir(exist_ok=True);(root/folder/'old.md').write_bytes(b'fixture history')
    with closing(sqlite3.connect(root/'other.db')) as db:
        db.execute('CREATE TABLE historical(x)');db.execute('INSERT INTO historical VALUES(42)');db.commit()
    original={name:(root/name).read_bytes() for name in ('run.bat','chay_agent_v2.bat','.env','ghi chu.txt','reports/old.md','reports_custom/old.md')}
    before=sql_snapshot(root/'agent.db');other=sql_snapshot(root/'other.db')
    archive=tmp/'v5.zip';build(archive,expected_sha=pin)
    with zipfile.ZipFile(archive) as z:z.extractall(root)  # User's only extraction; no bootstrap install.
    u=DirectLabUpdater(root,pin,mode,writer)
    u.create_environment(root/'.venv')
    if mode=='antivirus':
        real_write=v5_update.atomic_bytes;denied=False
        def deny_once(path,data):
            nonlocal denied
            if Path(path).name=='chay_agent_v2.bat' and not denied:
                denied=True;raise PermissionError('fixture antivirus replacement denial')
            return real_write(path,data)
        monkeypatch.setattr(v5_update,'atomic_bytes',deny_once)
    try:
        if mode=='success':
            assert u.update()=='V5_UPDATED_START_RUN_BAT' and u.health_verified
            assert u.child.poll() is not None and not locked(u.state/'agent.lock')
            assert not u.working_tree_dirty()
            assert u.check_current()=='V5_LAUNCHER_CHECK_OK_NO_JOBS'
            with FileLock(u.state/'agent.lock'):
                with pytest.raises(UpdateError,match='ALREADY_RUNNING'):u.check_current()
            if os.name=='nt':
                result=subprocess.run(['cmd','/d','/c',str(root/'run.bat'),'--check'],cwd=root,
                    capture_output=True,timeout=60,env=dict(os.environ,AGENT_BATCH_NO_PAUSE='1'))
                assert result.returncode==0 and b'V5_LAUNCHER_CHECK_OK_NO_JOBS' in result.stdout
            assert sql_snapshot(root/'agent.db')==before
            with closing(sqlite3.connect(root/'agent.db')) as db:
                db.execute('CREATE TABLE post_update_data(id INTEGER PRIMARY KEY,value TEXT)')
                db.execute("INSERT INTO post_update_data VALUES(2,'must-survive-voluntary-rollback')");db.commit()
            assert u.rollback().startswith('CODE_ROLLED_BACK')
            with closing(sqlite3.connect(root/'agent.db')) as db:assert db.execute('SELECT COUNT(*) FROM post_update_data').fetchone()[0]==1
            assert (root/'run.bat').read_bytes()==launcher('run',pin)  # Managed V2, no two processes.
            assert json.loads(u.installed.read_text())['sha']==V2_BASE
        else:
            expected=PermissionError if mode=='antivirus' else UpdateError
            with pytest.raises(expected) as failure:u.update()
            if mode=='health_failure':
                assert str(failure.value)=='NEW_AGENT_HEALTH_CHECK_FAILED' and u.health_verified
            assert sql_snapshot(root/'agent.db')==before
            assert all((root/name).read_bytes()==data for name,data in original.items())
            assert not (root/'QUAY_LAI_BAN_CU.bat').exists()
        assert all((root/name).read_bytes()==original[name] for name in ('.env','ghi chu.txt','reports/old.md','reports_custom/old.md'))
        assert sql_snapshot(root/'other.db')==other
        assert git('rev-parse','HEAD',cwd=root)==V2_BASE and git('branch','--show-current',cwd=root)=='local-reverse-v2'
        assert not locked(u.state/'agent.lock')
        bundles=list((root/'backups/updates').glob('*/backup.json'));assert bundles
        first=json.loads(bundles[0].read_text());assert {x['path'] for x in first['databases']}=={'agent.db','other.db'}
    finally:
        writer.close()
        if hasattr(u,'child') and u.child.poll() is None:u.stop_child(u.child)
