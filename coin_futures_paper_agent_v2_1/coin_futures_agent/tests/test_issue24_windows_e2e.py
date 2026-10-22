"""Real Git/venv/pip/health/CMD; synthetic release API and isolated package reuse.
The unchanged fd829fc9 BAT, one-time Git bootstrap, then a second release by
the SAME BAT are exercised. No user DB/tokens or real trade endpoints.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import sysconfig

from app import storage
from app.battle_storage import init_battle_db, ensure_battle_initial_balances
from app.strategy_cases import init_strategy_cases
from app.reverse_research import init_reverse_lab
from app.rei_v3_store import init,insert
from build_approved_release import build,bootstrap_command
from v5_package import materialize,SOURCES,INFO
from local_update import V2_BASE,APP_SUBDIR
from test_local_update_e2e import OfflineLabUpdater,sql_snapshot
from test_issue24_learning import issue24_rows

APP=Path(__file__).resolve().parents[1]
INSTALLED='fd829fc9a28af91ee87b0b671550ce37d3d6762c'


def hook_text(feed,api_log,site_packages):
    return '''import io,json,pathlib,subprocess,sys,urllib.request
feed=pathlib.Path(FEED_PATH)
api_log=pathlib.Path(API_LOG)
real_open=urllib.request.urlopen
class Reply(io.BytesIO):
 def __init__(self,data,url):super().__init__(json.dumps(data).encode());self.url=url
 def geturl(self):return self.url
def urlopen(request,*a,**k):
 url=request.full_url if hasattr(request,'full_url') else str(request)
 prefix='https://api.github.com/repos/amen090104-collab/coin-futures-agent/'
 if url.startswith(prefix):
  key=url[len(prefix):];data=json.loads(feed.read_text())
  with api_log.open('a',encoding='ascii') as f:f.write(key+'\\n')
  return Reply(data[key],url)
 return real_open(request,*a,**k)
urllib.request.urlopen=urlopen
real_run=subprocess.run
def run(args,*a,**k):
 args=list(args)
 if args[:4]==['git','remote','get-url','origin']:
  return subprocess.CompletedProcess(args,0,b'https://github.com/amen090104-collab/coin-futures-agent.git\\n',b'')
 creating=len(args)>3 and args[1:3]==['-m','venv']
 if creating:args.insert(3,'--system-site-packages')
 if len(args)>3 and args[1:4]==['-m','pip','install']:args.insert(4,'--no-index')
 result=real_run(args,*a,**k)
 if creating and result.returncode==0:
  dest=pathlib.Path(args[-1])
  folder=dest/('Lib/site-packages' if sys.platform=='win32' else 'lib/python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'/site-packages')
  (folder/'isolated-fixture.pth').write_text(SITE_PACKAGES+'\\n',encoding='utf-8')
 return result
subprocess.run=run
'''.replace('FEED_PATH',repr(str(feed))).replace('API_LOG',repr(str(api_log))).replace('SITE_PACKAGES',repr(str(site_packages)))


def test_installed_fd829_bootstrap_no_zip_then_next_release_same_bat(tmp_path,monkeypatch):
    def git(*args,cwd=APP):
        return subprocess.run(['git',*args],cwd=cwd,capture_output=True,text=True,check=True).stdout.strip()
    repository=git('rev-parse','--show-toplevel');first=git('rev-parse','HEAD')
    origin=tmp_path/'origin';git('clone','--quiet','--no-hardlinks',repository,str(origin))
    origin_app=origin/APP_SUBDIR
    git('config','user.name','Isolated Fixture',cwd=origin);git('config','user.email','fixture@example.invalid',cwd=origin)
    source=origin_app/'app/version.py';source.write_text(source.read_text().replace('VERSION = "5.1.0"','VERSION = "5.1.1"'))
    git('add','.',cwd=origin);git('commit','-m','Fixture second release only',cwd=origin);second=git('rev-parse','HEAD',cwd=origin)
    manifest1=build(APP,sha=first,tag='v5.1.0',review_url='https://github.com/amen090104-collab/coin-futures-agent/pull/100')
    manifest2=build(origin_app,sha=second,tag='v5.1.1',review_url='https://github.com/amen090104-collab/coin-futures-agent/pull/101')
    clone=tmp_path/'V5 người dùng';git('clone','--quiet','--no-hardlinks','--no-checkout',str(origin),str(clone))
    git('switch','-c','local-reverse-v2',V2_BASE,cwd=clone);root=clone/APP_SUBDIR
    monkeypatch.setattr(storage,'DB_PATH',root/'agent.db')
    storage.init_db();init_strategy_cases();init_battle_db();init_reverse_lab()
    storage.ensure_initial_balance('2026-10-08T00:00:00Z',10000)
    ensure_battle_initial_balances('2026-10-08T00:00:00Z',10000)
    (root/'.env').write_text('V44_SHADOW_ENABLED=false\nREVERSE_ENTRY_INTELLIGENCE_ENABLED=false\nREVERSE_ENTRY_V3_ENABLED=false\nREPORTS_DIR=reports_custom\n')
    for folder in ('reports','reports_custom'):
        (root/folder).mkdir(exist_ok=True);(root/folder/'saved.md').write_bytes(b'fixture-original-report')
    with closing(storage._connect()) as db:
        init(db);rows,arrival=issue24_rows()
        for row in rows:insert(db,row)
        db.execute("UPDATE rei_v3_meta SET version='rei-v3.3'")
        db.execute("INSERT INTO rei_v3_runs VALUES('holdout-v1',?,'{\"groups\":[]}')",(arrival,))
        for side,n in (('LONG',19),('SHORT',2)):
            db.execute('INSERT INTO rei_v3_models VALUES(?,?,?,?)',('daily-old-'+side,arrival,side,json.dumps({'status':'INSUFFICIENT_DATA','training_n':n})))
        db.commit()
    with closing(sqlite3.connect(root/'other.db')) as db:
        db.execute('CREATE TABLE original_history(x)');db.execute('INSERT INTO original_history VALUES(42)');db.commit()
    package=tmp_path/'fd-package'
    materialize(package,INSTALLED,lambda name:subprocess.run(['git','cat-file','blob',INSTALLED+':'+APP_SUBDIR+'/'+name],cwd=APP,capture_output=True,check=True).stdout)
    for name in (*SOURCES,INFO):
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((package/name).read_bytes())
    spec=importlib.util.spec_from_file_location('installed_fd829_fixture',package/'.v5-update/v5_update.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    old=legacy.V5Updater(root,from_package=True)
    old.create_environment=OfflineLabUpdater.create_environment.__get__(old)
    old.install_dependencies=OfflineLabUpdater.install_dependencies.__get__(old)
    original_git=old.git
    old.git=lambda *a,**k:'https://github.com/amen090104-collab/coin-futures-agent.git' if a[:3]==('remote','get-url','origin') else original_git(*a,**k)
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    monkeypatch.setenv('AGENT_LOCAL_PORT',str(port))
    old.create_environment(root/'.venv');assert old.update()=='V5_UPDATED_START_RUN_BAT'
    old_bat=(root/'update.bat').read_bytes()
    assert old_bat==subprocess.run(['git','cat-file','blob',INSTALLED+':'+APP_SUBDIR+'/update.bat'],cwd=APP,capture_output=True,check=True).stdout
    assert b'--from-package' in old_bat
    before=sql_snapshot(root/'agent.db');extra=sql_snapshot(root/'other.db');env=(root/'.env').read_bytes()
    feed=tmp_path/'approved-api.json';api_log=tmp_path/'api-requests.txt'
    def feed_for(manifest,pr):
        sha=manifest['approved_release']['sha'];manifest['approved_release']['reviewed']=True
        feed.write_text(json.dumps({'releases/latest':{'tag_name':'v'+manifest['version'],'body':json.dumps(manifest)},
            'pulls/'+str(pr):{'merged_at':'FIXTURE_ONLY','head':{'sha':sha}},
            'commits/'+sha+'/check-runs':{'check_runs':[{'id':i+1,'name':name,'status':'completed','conclusion':'success','app':{'slug':'github-actions'}} for i,name in enumerate((
                'test (ubuntu-latest, Python 3.12)','test (windows-latest, Python 3.13.5)'))]}}))
    feed_for(manifest1,100)
    suffix=Path('Lib/site-packages') if os.name=='nt' else Path(f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    hook=root/'.venv'/suffix/'sitecustomize.py';hook.write_text(hook_text(feed,api_log,sysconfig.get_path('purelib')),encoding='utf-8')
    interpreter=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    environment=dict(os.environ,AGENT_BATCH_NO_PAUSE='1',PYTHONUTF8='1')
    transcript=[]
    def run(args,step,timeout=180):
        p=subprocess.run(args,cwd=root,env=environment,capture_output=True,timeout=timeout)
        text=p.stdout.decode('utf-8',errors='replace')
        assert p.returncode==0,step+': '+(p.stderr.decode('utf-8',errors='replace')+text)[-2000:]
        transcript.append({'step':step,'exit_code':p.returncode,'status_lines':[line for line in text.splitlines() if line.startswith(('V5_','NO_NEW_','CODE_ROLLED','V3_EXPERIMENT'))]})
        return text
    try:
        old_command=['cmd','/d','/c',str(root/'update.bat')] if os.name=='nt' else [str(interpreter),str(root/'.v5-update/v5_update.py'),'update','--from-package','--root',str(root)]
        result=run(old_command,'unchanged_fd829_update_bat')
        assert 'V5_NO_NEWER_APPROVED_RELEASE_CURRENT_VERSION_PRESERVED' in result
        assert not api_log.exists() and old_bat==(root/'update.bat').read_bytes()
        bootstrap_source=subprocess.run(['git','cat-file','blob',first+':'+APP_SUBDIR+'/bootstrap_remote_updater.py'],cwd=APP,capture_output=True,check=True).stdout
        one_time=bootstrap_command(first,hashlib.sha256(bootstrap_source).hexdigest())
        bootstrap_args=['cmd','/d','/c',one_time] if os.name=='nt' else [str(interpreter),'-c',one_time.split(' -c "',1)[1][:-1]]
        assert 'V5_UPDATED_START_RUN_BAT' in run(bootstrap_args,'one_time_pinned_git_bootstrap',timeout=300)
        new_bat=(root/'update.bat').read_bytes();assert b'--from-package' not in new_bat
        assert json.loads((root/'.agent-updater/installed.json').read_text())['sha']==first
        assert sql_snapshot(root/'agent.db')==before and (root/'.env').read_bytes()==env
        def bat(action,extra_args=()):
            if os.name=='nt':return ['cmd','/d','/c',str(root/('update.bat' if action=='update' else 'QUAY_LAI_BAN_CU.bat' if action=='rollback' else 'run.bat')),*extra_args]
            return [str(interpreter),str(root/'.agent-updater/update_driver.py'),action,'--root',str(root)]
        assert 'NO_NEW_VERSION' in run(bat('update'),'same_release_no_reinstall')
        feed_for(manifest2,101)
        assert 'V5_UPDATED_START_RUN_BAT' in run(bat('update'),'second_release_only_same_update_bat',timeout=300)
        assert new_bat==(root/'update.bat').read_bytes()
        assert json.loads((root/'.agent-updater/installed.json').read_text())['sha']==second
        assert sql_snapshot(root/'agent.db')==before
        run(bat('check',('--check',)),'native_run_bat_health_check')
        selected=json.loads((root/'.agent-updater/installed.json').read_text())
        experiment=tmp_path/'learning-output'
        p=subprocess.run([selected['python'],'-m','app.rei_v3_train','--source-db',str(root/'agent.db'),'--output-dir',str(experiment)],
            cwd=selected['code'],capture_output=True,timeout=120)
        assert p.returncode==0,p.stderr.decode('utf-8',errors='replace')[-1500:]
        learning=json.loads((experiment/'experiment.redacted.json').read_text())
        assert learning['forward_training_candidates']['SHORT']['status']=='RESEARCH_CLASSIFIER'
        assert learning['forward_training_candidates']['SHORT']['fit_n']==101
        assert learning['forward_training_candidates']['SHORT']['calibration_n']==58
        assert learning['orders_created']==0 and sql_snapshot(root/'agent.db')==before
        with closing(sqlite3.connect(root/'agent.db')) as db:
            db.execute('CREATE TABLE post_update_paper_trade(id INTEGER,net_r REAL)')
            db.execute('INSERT INTO post_update_paper_trade VALUES(1,1.5)');db.commit()
        assert 'CODE_ROLLED_BACK_DATA_PRESERVED_START_RUN_BAT' in run(bat('rollback'),'rollback_preserves_new_paper_data')
        assert json.loads((root/'.agent-updater/installed.json').read_text())['sha']==first
        assert new_bat==(root/'update.bat').read_bytes()
        assert 'V5_UPDATED_START_RUN_BAT' in run(bat('update'),'update_after_rollback_uses_preserved_updater',timeout=300)
        with closing(sqlite3.connect(root/'agent.db')) as db:assert db.execute('SELECT net_r FROM post_update_paper_trade').fetchone()[0]==1.5
        assert sql_snapshot(root/'other.db')==extra and (root/'.env').read_bytes()==env
        for folder in ('reports','reports_custom'):assert (root/folder/'saved.md').read_bytes()==b'fixture-original-report'
        assert git('rev-parse','HEAD',cwd=root)==V2_BASE and git('branch','--show-current',cwd=root)=='local-reverse-v2'
        evidence={'fixture_only':True,'windows_native_cmd':os.name=='nt','installed_source_sha':INSTALLED,
            'first_release_sha':first,'second_fixture_release_sha':second,'old_bat_sha256':hashlib.sha256(old_bat).hexdigest(),
            'new_stable_bat_sha256':hashlib.sha256(new_bat).hexdigest(),'same_bat_across_releases':True,
            'manual_zip_downloads_after_installed_fd829':0,'transcript':transcript,
            'learning':learning['forward_training_candidates'],'real_user_profitability_verified':False}
        if os.environ.get('GITHUB_ACTIONS')=='true' and os.name=='nt':
            out=APP/'v51-test-evidence';out.mkdir(exist_ok=True)
            (out/'windows-bootstrap-learning.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=True),encoding='ascii')
    finally:hook.unlink(missing_ok=True)
