"""Real Git/venv/pip/backup/probe/supervisor on a V2 clone. Public feed and ASGI are fixtures."""
from contextlib import closing
import gc
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import sysconfig

import pytest

import local_update as update
from local_agent import locked
from app import storage
from app.battle_storage import init_battle_db
from app.reverse_research import init_reverse_lab
import bootstrap_windows

APP=Path(__file__).resolve().parents[1]


def sql_snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        return {table:db.execute('SELECT * FROM "'+table+'" ORDER BY rowid').fetchall() for table in tables}


class OfflineLabUpdater(update.Updater):
    """No fake stage: actual fetch/archive, per-release venv, pip and candidate release_probe."""
    def __init__(self, root, reviewed_sha, mode):
        super().__init__(root)
        self.reviewed_sha,self.mode=reviewed_sha,mode

    def git(self,*args,**kwargs):
        if args[:3]==('remote','get-url','origin'):
            return 'https://github.com/amen090104-collab/coin-futures-agent.git'
        return super().git(*args,**kwargs)

    def api(self,path):
        pin={'sha':self.reviewed_sha,'reviewed':True,'review_url':'https://github.com/amen090104-collab/coin-futures-agent/pull/19'}
        if path=='releases/latest':
            return {'tag_name':'local-v3.0.0','body':json.dumps({'approved_release':pin})}
        if path=='pulls/19':
            return {'merged_at':'TEST_FIXTURE_ONLY','head':{'sha':self.reviewed_sha}}
        if path=='commits/'+self.reviewed_sha+'/check-runs':
            return {'check_runs':[{'name':name,'app':{'slug':'github-actions'},'status':'completed','conclusion':'success'} for name in (
                'test (ubuntu-latest, Python 3.12)','test (windows-latest, Python 3.13.5)')]}
        raise AssertionError('Unexpected public API request')

    def create_environment(self,destination):
        # Reuse the test runner's installed packages offline. A nested venv only sees
        # base-Python packages via --system-site-packages, not the parent venv.
        result=subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(destination)],
            cwd=self.root,capture_output=True,timeout=120)
        # This subprocess only creates a disposable fixture venv: no Git, network,
        # production .env or credentials. Retain its error rather than masking the stage.
        assert result.returncode==0, 'FIXTURE_VENV_FAILED: '+result.stderr.decode('utf-8',errors='replace')[-1600:]
        packages=destination/('Lib/site-packages' if os.name=='nt' else
            f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
        (packages/'acceptance-fixture.pth').write_text(sysconfig.get_path('purelib')+'\n',encoding='utf-8')

    def install_dependencies(self,interpreter,code):
        update.command([str(interpreter),'-m','pip','install','--no-index','--disable-pip-version-check',
                        '-r',str(code/'requirements.txt')],cwd=code,timeout=180)

    def probe(self,candidate,backup):
        # Keep committed WAL live through the actual snapshot, then release the
        # fixture writer before any Windows restore can replace the database.
        assert Path(str(self.root/'agent.db')+'-wal').stat().st_size>0
        self.wal_writer.close()
        return super().probe(candidate,backup)

    def start(self,install):
        # Preserve pinned candidate files. Inject only the ASGI fixture in a separate test driver:
        # real app lifespan/paper schedulers must never run in an updater acceptance test.
        driver=self.state/'fixture_server.py'
        driver.write_text('import sys, types\nfrom fastapi import FastAPI\n'
            'sys.path.insert(0,sys.argv[1])\n'
            'fixture=types.ModuleType("app.main");fixture.app=FastAPI();sys.modules["app.main"]=fixture\n'
            'from local_agent import run\nrun(sys.argv[2],maintenance_start=True)\n',encoding='utf-8')
        flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        return subprocess.Popen([install['python'],str(driver),install['code'],str(self.root)],cwd=self.root,
                                creationflags=flags,env=dict(os.environ,PYTHONUTF8='1'))

    def healthy(self,child,sha,**kwargs):
        result=super().healthy(child,sha,wait_sec=20)
        self.health_verified=result
        state=self.state/'running.json'
        running=json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
        self.delegated_worker=running.get('pid')!=child.pid and running.get('parent_pid')==child.pid
        if not result:
            assert result, 'FIXTURE_HEALTH_FAILED '+json.dumps({'launcher_pid':child.pid,
                'exit_code':child.poll(),'supervisor':running})
        return result and self.mode!='health_failure'


@pytest.mark.parametrize('mode',['success','health_failure','bad_migration'])
def test_v2_clone_untracked_launcher_wal_actual_stage_and_recovery(tmp_path_factory,monkeypatch,mode,capsys):
    # Retain Unicode/spaces without adding the long pytest function name to every
    # nested executable path (CreateProcess can reject >MAX_PATH python.exe).
    tmp_path=tmp_path_factory.mktemp('v2')
    import _socket
    native=_socket.socket.connect
    def loopback(sock,address):
        assert address[0]=='127.0.0.1'
        return native(sock,address)
    monkeypatch.setattr(socket.socket,'connect',loopback)
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    monkeypatch.setenv('AGENT_LOCAL_PORT',str(port))
    repo=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=APP,capture_output=True,text=True,check=True).stdout.strip()
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=APP,capture_output=True,text=True,check=True).stdout.strip()
    clone=tmp_path/'Cài đặt V2 người dùng'
    subprocess.run(['git','clone','--quiet','--no-hardlinks','--no-checkout',repo,str(clone)],capture_output=True,check=True)
    subprocess.run(['git','switch','-c','local-reverse-v2',update.V2_BASE],cwd=clone,capture_output=True,check=True)
    target=clone/update.APP_SUBDIR
    monkeypatch.setattr(storage,'DB_PATH',target/'agent.db')
    storage.init_db();init_battle_db();init_reverse_lab()
    trade={'id':1,'position_id':1,'strategy_id':'REVERSE_RR2','symbol':'TESTUSDT','side':'SHORT',
        'opened_at':'2026-10-08T00:01:00Z','closed_at':'2026-10-08T00:11:00Z',
        'entry_price':100.,'exit_price':99.,'stop_loss':101.,'take_profit':98.,'quantity':1.,'score':80.,
        'gross_pnl':1.,'fees':.1,'net_pnl':.9,'r_multiple':.9,'exit_reason':'FIXTURE',
        'holding_minutes':10.,'mfe_r':1.,'mae_r':.1,'reason_text':'synthetic WAL fixture',
        'reason_codes':'[]','entry_context':json.dumps({'source_signal_side':'LONG','cohort_id':'2026-10-08T00:00:00Z::TESTUSDT'})}
    wal_writer=sqlite3.connect(target/'agent.db')
    with wal_writer as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        db.execute('INSERT INTO battle_trades('+','.join(trade)+') VALUES('+','.join('?' for _ in trade)+')',tuple(trade.values()))
        if mode=='bad_migration':
            db.execute('CREATE TABLE rei_v3_meta(schema_version INTEGER PRIMARY KEY,version TEXT)')
            db.execute("INSERT INTO rei_v3_meta VALUES(99,'incompatible-fixture')")
        db.commit()
    gc.collect()  # Legacy storage transaction contexts can retain handles until GC on Windows.
    env=target/'.env';env.write_text('V44_SHADOW_ENABLED=false\nREVERSE_ENTRY_INTELLIGENCE_ENABLED=false\nREVERSE_ENTRY_V3_ENABLED=false\nREPORTS_DIR=reports\n',encoding='utf-8')
    launcher=target/'chay_agent_v2.bat';launcher.write_bytes(b'@echo off\r\necho Legacy launcher must not execute\r\n')
    note=target/'ghi chu.txt';note.write_text('Tệp cá nhân được giữ nguyên',encoding='utf-8')
    (target/'reports').mkdir(exist_ok=True)
    report=target/'reports'/'history.md';report.write_text('Lịch sử giả lập',encoding='utf-8')
    bootstrap_windows.install(target,tmp_path/'Desktop có dấu',source=APP)
    before=sql_snapshot(target/'agent.db')
    bytes_before={p:p.read_bytes() for p in (env,launcher,note,report)}
    updater=OfflineLabUpdater(target,head,mode)
    updater.wal_writer=wal_writer
    updater.create_environment(target/'.venv')
    monkeypatch.setattr(update.webbrowser,'open',lambda *a:True)
    try:
        if mode=='success':
            assert updater.update()=='UPDATED'
            assert updater.health_verified
            assert locked(updater.state/'agent.lock')
            assert json.loads(updater.installed.read_text(encoding='utf-8'))['sha']==head
            assert updater.rollback().startswith('CODE_ROLLED_BACK')
            updater.child.wait(timeout=10)
        else:
            expected='NEW_AGENT_HEALTH_CHECK_FAILED' if mode=='health_failure' else 'COMMAND_FAILED_CHECK_GIT_NETWORK_OR_DEPENDENCIES'
            with pytest.raises(update.UpdateError,match='^'+expected+'$'):updater.update()
            if mode=='health_failure':
                assert updater.health_verified
                assert json.loads(updater.journal.read_text(encoding='utf-8'))['phase']=='ROLLED_BACK'
            else:
                assert not updater.journal.exists()
        assert sql_snapshot(target/'agent.db')==before
        assert all(p.read_bytes()==value for p,value in bytes_before.items())
        assert updater.git('rev-parse','HEAD')==update.V2_BASE
        assert updater.git('branch','--show-current')=='local-reverse-v2'
        assert not locked(updater.state/'agent.lock')
        assert list((target/'backups'/'updates').glob('*/backup.json'))
        assert 'chua duoc Git theo doi' in capsys.readouterr().out
        if os.environ.get('GITHUB_ACTIONS')=='true':
            with capsys.disabled():
                print('::notice title=V2 updater acceptance::'+json.dumps({'mode':mode,'live_wal_backup':True,
                    'health_verified':getattr(updater,'health_verified',None),
                    'delegated_worker':getattr(updater,'delegated_worker',None),
                    'original_rows_and_files_preserved':True}),flush=True)
    finally:
        if hasattr(updater,'child') and updater.child.poll() is None:updater.stop_child(updater.child)
        wal_writer.close()
