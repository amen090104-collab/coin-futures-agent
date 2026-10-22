"""V2 -> V5 in one update.bat. No trading, enablement or release-approval bypass."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from local_agent import FileLock, BusyError, atomic_json, locked, local_url
from local_update import Updater, UpdateError, command, APP_SUBDIR, V2_BASE, port_open, source_archive
from safe_preupdate_backup import checksum, checked_relative
from v5_package import materialize, verify_folder, verify_git, sha256

LAUNCHER_ACTIONS={'run.bat':'run','chay_agent_v2.bat':'run','QUAY_LAI_BAN_CU.bat':'rollback',
                  'CHAN_DOAN_V5.bat':'diagnose'}
LAUNCHERS=tuple(LAUNCHER_ACTIONS)


def atomic_bytes(path, data):
    path=Path(path)
    temporary=path.with_name(path.name+'.v5-tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def launcher(action, sha):
    if action not in {'run','rollback','diagnose'} or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('INVALID_V5_LAUNCHER')
    script='.agent-updater\\v5-runtime\\'+sha+'\\.v5-update\\v5_update.py'
    text=f'''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "v5_action={action}"
if "{action}"=="run" if "%~1"=="--check" set "v5_action=check"
if exist ".venv\\Scripts\\python.exe" goto venv
where py >nul 2>nul
if not errorlevel 1 goto py
python "{script}" %v5_action% --root "%~dp0."
goto finish
:venv
".venv\\Scripts\\python.exe" "{script}" %v5_action% --root "%~dp0."
goto finish
:py
py -3 "{script}" %v5_action% --root "%~dp0."
:finish
set "v5_exit=%errorlevel%"
if not "%AGENT_BATCH_NO_PAUSE%"=="1" pause
exit /b %v5_exit%
'''
    return text.replace('\n','\r\n').encode('utf-8')


class V5Updater(Updater):
    def __init__(self,root,*,package_root=None,from_package=False):
        super().__init__(root)
        for relative in ('.agent-updater','.agent-updater/releases','.agent-updater/v5-runtime'):
            checked_relative(self.root,relative)
        self.package_root=Path(package_root or Path(__file__).resolve().parent.parent)
        self.package=verify_folder(self.package_root)
        self.probing=False
        self.open_after_update=False
        self.from_package=from_package

    def approved(self):
        # Explicit manual installation of the package selected by the operator.
        # No moving branch, release publication or credential is needed for this path.
        if self.from_package:
            return {'sha':self.package['source_sha'],'reviewed':False,'version':self.package.get('agent_version','5.0.0'),
                    'review_url':'https://github.com/amen090104-collab/coin-futures-agent/issues/22',
                    'acceptance':None,'local_package':True}
        release=self.api('releases/latest')
        if not release or release.get('draft') or release.get('prerelease') or not re.fullmatch(r'v5\.[0-9]+\.[0-9]+',release.get('tag_name','')):
            return None
        try:
            body=json.loads(release['body']);pin=body['approved_release'];evidence=body['acceptance']
            if (not re.fullmatch('[0-9a-f]{40}',pin['sha']) or pin.get('reviewed') is not True
                    or evidence.get('code_sha')!=pin['sha'] or evidence.get('windows_user_copy') is not True
                    or evidence.get('verified_market_windows',0)<3 or evidence.get('ready_signal_records',0)<1
                    or evidence.get('point_in_time_verified') is not True
                    or not re.fullmatch(r'https://github.com/amen090104-collab/coin-futures-agent/(?:issues|pull)/[0-9]+(?:#issuecomment-[0-9]+)?',evidence.get('review_evidence_url',''))):
                raise ValueError
            self.verify_pin(pin)
            if not self.installed.exists() and self.package['source_sha']!=pin['sha']:
                raise ValueError
            return {**pin,'acceptance':evidence,'version':release['tag_name'][1:]}
        except (KeyError,ValueError,TypeError,AttributeError):
            raise UpdateError('V5_RELEASE_NOT_REVIEWED_OR_ACCEPTANCE_PENDING') from None

    def working_tree_dirty(self):
        allowed=[]
        if checksum(self.root/'update.bat')==self.package['files']['update.bat']:
            allowed.append('update.bat')
        if self.journal.exists():
            txn=json.loads(self.journal.read_text(encoding='utf-8'))
            sha=txn.get('v5_runtime_sha','')
            if re.fullmatch('[0-9a-f]{40}',sha):
                for name in LAUNCHERS:
                    path=self.root/name
                    expected=launcher(LAUNCHER_ACTIONS[name],sha)
                    if path.is_file() and not path.is_symlink() and path.read_bytes()==expected:
                        allowed.append(name)
        excludes=[':(top,exclude)'+APP_SUBDIR+'/'+name for name in allowed]
        raw=self.git('status','--porcelain=v1','-z','--untracked-files=all','--',':(top,glob)**',
                     ':(top,exclude)'+APP_SUBDIR+'/.agent-updater',
                     ':(top,exclude)'+APP_SUBDIR+'/local_update_settings.json',*excludes,binary=True)
        entries=[v for v in raw.decode('utf-8',errors='replace').split('\0') if v]
        self.untracked_count=sum(v.startswith('?? ') for v in entries)
        return any(not v.startswith('?? ') for v in entries)

    def untracked_notice(self):
        print('Co',self.untracked_count,'tep chua duoc Git theo doi. Giu tep ca nhan; '
              'launcher chay_agent_v2.bat duoc backup truoc khi thay launcher V5.')

    def prerequisites(self):
        verify_folder(self.package_root)
        if not self.installed.exists() and self.git('rev-parse','HEAD')!=V2_BASE:
            raise UpdateError('INITIAL_V5_UPGRADE_REQUIRES_EXACT_V2_BASE')
        if not (self.root/'.env').is_file() or not (self.root/'agent.db').is_file():
            raise UpdateError('SELECT_EXISTING_V2_FOLDER_WITH_ENV_AND_DB')
        for name in (*LAUNCHERS,'update.bat'):
            p=self.root/name
            if p.is_symlink() or (p.exists() and not p.is_file()):
                raise UpdateError('UNSAFE_V5_LAUNCHER_PATH')
        super().prerequisites()
        if locked(self.state/'agent.lock') or port_open():
            raise UpdateError('STOP_AGENT_WITH_CTRL_C_BEFORE_V5_UPDATE')

    def stage(self,release):
        # Verify the distributed helper against the approved Git pin as well as its hashes.
        self.git('fetch','--no-tags','origin',self.package['source_sha'])
        verify_git(self.package,self.git)
        candidate=super().stage(release)
        code=Path(candidate['code'])
        version=re.search(r'^VERSION\s*=\s*[\"\x27]([^\"\x27]+)',(code/'app/version.py').read_text(encoding='utf-8'),re.M)
        if not version or version[1]!=release['version']:
            raise UpdateError('V5_SOURCE_VERSION_DOES_NOT_MATCH_RELEASE')
        atomic_json(code/'.build-info.json',{'sha':release['sha'],'version':release['version'],
                    'approval':'LOCAL_PACKAGE_REQUESTED' if release.get('local_package') else 'REVIEWED_RELEASE',
                    'acceptance':release['acceptance']})
        # Attest extracted code bytes against immutable Git objects; generated build metadata is separate.
        records={}
        repository=self.git('rev-parse','--show-toplevel')
        raw_archive=source_archive(self.git,repository,release['sha']+':'+APP_SUBDIR)
        with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
            for name in archive.namelist():
                if name.endswith('/'):
                    continue
                raw=archive.read(name)
                if checked_relative(code,name).read_bytes()!=raw:
                    raise UpdateError('V5_STAGED_SOURCE_CHECKSUM_FAILED')
                records[name]=sha256(raw)
        atomic_json(Path(candidate['code']).parent/'SOURCE_CHECKSUMS.json',{'sha':release['sha'],'files':records})
        return candidate

    def transaction_extra(self,backup,candidate):
        runtime=self.state/'v5-runtime'/candidate['sha']
        if runtime.exists():
            shutil.rmtree(runtime)
        code=Path(candidate['code'])
        materialize(runtime,candidate['sha'],lambda name:(code/name).read_bytes())
        records=[]
        folder=Path(backup)/'v5-launchers';folder.mkdir()
        for name in LAUNCHERS:
            path=self.root/name
            data=path.read_bytes() if path.exists() else None
            if data is not None:
                (folder/name).write_bytes(data)
            action=LAUNCHER_ACTIONS[name]
            records.append({'name':name,'existed':data is not None,'old_sha256':sha256(data) if data is not None else None,
                            'new_sha256':sha256(launcher(action,candidate['sha']))})
        atomic_json(folder/'manifest.json',{'files':records})
        return {'v5_runtime_sha':candidate['sha'],'v5_launchers':records}

    def apply_transaction(self,txn):
        for record in txn['v5_launchers']:
            action=LAUNCHER_ACTIONS[record['name']]
            atomic_bytes(self.root/record['name'],launcher(action,txn['v5_runtime_sha']))

    def restore_transaction(self,txn):
        records=txn.get('v5_launchers',[])
        folder=checked_relative(self.root,txn['backup'])/'v5-launchers'
        # Validate every backup and current target before changing any launcher.
        for record in records:
            if record['name'] not in LAUNCHERS:
                raise UpdateError('INVALID_V5_LAUNCHER_RESTORE')
            path=self.root/record['name']
            if path.is_symlink() or (record['existed'] and checksum(folder/record['name'])!=record['old_sha256']):
                raise UpdateError('V5_LAUNCHER_BACKUP_CHECKSUM_FAILED')
            if path.exists() and checksum(path) not in {record['old_sha256'],record['new_sha256']}:
                raise UpdateError('V5_LAUNCHER_CHANGED_RESTORE_BLOCKED')
        for record in records:
            path=self.root/record['name']
            if record['existed']:
                atomic_bytes(path,(folder/record['name']).read_bytes())
            else:
                path.unlink(missing_ok=True)

    def verify_install(self,install):
        code=Path(install['code']).resolve()
        if code==self.root and install['sha']==V2_BASE:
            return  # Managed rollback to the original V2 checkout.
        if not re.fullmatch('[0-9a-f]{40}',install.get('sha','')) or code!=(self.state/'releases'/install['sha']/'code').resolve():
            raise UpdateError('V5_INSTALLED_POINTER_INVALID')
        attestation=json.loads((code.parent/'SOURCE_CHECKSUMS.json').read_text(encoding='utf-8'))
        if attestation.get('sha')!=install['sha'] or not attestation.get('files'):
            raise UpdateError('V5_INSTALLED_CHECKSUM_MANIFEST_INVALID')
        for name,expected in attestation['files'].items():
            if checksum(checked_relative(code,name))!=expected:
                raise UpdateError('V5_INSTALLED_SOURCE_CHANGED_DO_NOT_RUN')
        build=json.loads((code/'.build-info.json').read_text(encoding='utf-8'))
        if build.get('sha')!=install['sha'] or not re.fullmatch(r'5\.[0-9]+\.[0-9]+',build.get('version','')):
            raise UpdateError('V5_INSTALLED_BUILD_IDENTITY_MISMATCH')

    def start(self,install):
        self.verify_install(install)
        if not self.probing:
            return super().start(install)
        flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        return subprocess.Popen([install['python'],str(Path(install['code'])/'local_agent.py'),'--root',str(self.root),
            '--maintenance-start','--health-only'],cwd=self.root,creationflags=flags,env=dict(os.environ,PYTHONUTF8='1'))

    def healthy(self,child,sha,**kwargs):
        if not super().healthy(child,sha,**kwargs):
            return False
        if not self.probing:
            return True  # Includes managed V2 after deliberate code rollback.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(local_url()+'/version',timeout=3) as response:
                info=json.load(response)
            build=json.loads((Path(self.current()['code'])/'.build-info.json').read_text(encoding='utf-8'))
            return info.get('version')==build.get('version') and info.get('sha')==sha and info.get('real_orders_enabled') is False
        except (OSError,ValueError,AttributeError):
            return False

    def update(self):
        self.probing=True
        try:
            result=super().update()
            if result=='UPDATED':
                return 'V5_UPDATED_START_RUN_BAT'
            if result=='NO_NEWER_APPROVED_VERSION':
                return ('NO_APPROVED_V5_RELEASE_KEEP_V2' if self.current()['sha']==V2_BASE
                        else 'V5_NO_NEWER_APPROVED_RELEASE_CURRENT_VERSION_PRESERVED')
            return result
        finally:
            self.probing=False

    def after_health(self,child):
        self.stop_child(child)

    def run_local(self):
        if not (self.root/'.env').is_file():
            raise UpdateError('V5_EXISTING_ENV_MISSING_DO_NOT_RECREATE')
        return super().run_local()

    def diagnose(self):
        current=self.current()
        self.verify_install(current)
        if not (Path(current['code'])/'app/v5_diagnostics.py').is_file():
            raise UpdateError('DIAGNOSTICS_REQUIRE_ISSUE22_PATCH')
        # Read-only diagnostic is safe while Paper runs; SQLite takes a WAL snapshot.
        return subprocess.call([current['python'],'-c',
            "import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('app.v5_diagnostics',run_name='__main__')",
            current['code'],
            '--source-db',str(self.root/'agent.db'),'--output-json',str(self.root/'v5-diagnostics.json')],
            cwd=self.root, env=dict(os.environ,PYTHONUTF8='1',AGENT_RELEASE_SHA=current['sha']))

    def check_current(self):
        """Optional operator/CMD acceptance check; never starts normal jobs."""
        with FileLock(self.state/'maintenance.lock'):
            if self.journal.exists() and json.loads(self.journal.read_text(encoding='utf-8'))['phase']=='PREPARED':
                raise UpdateError('RECOVER_INTERRUPTED_V5_UPDATE_FIRST')
            if locked(self.state/'agent.lock') or port_open():
                raise UpdateError('AGENT_ALREADY_RUNNING_STOP_OR_OPEN_EXISTING_BROWSER')
            current=self.current()
            if not (Path(current['code'])/'.build-info.json').is_file():
                raise UpdateError('HEALTH_ONLY_CHECK_REQUIRES_INSTALLED_V5')
            self.probing=True
            child=None
            try:
                child=self.start(current)
                if not self.healthy(child,current['sha']):
                    raise UpdateError('V5_LAUNCHER_HEALTH_CHECK_FAILED')
                return 'V5_LAUNCHER_CHECK_OK_NO_JOBS'
            finally:
                if child is not None:self.stop_child(child)
                self.probing=False


def main():
    parser=argparse.ArgumentParser(description='V2 -> V5; mot update.bat, khong bat real/Shadow hay publish release.')
    parser.add_argument('action',choices=('update','run','rollback','check','diagnose'),nargs='?',default='update')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--from-package',action='store_true',help='Cai dung SHA cua goi user chu dong tai; khong can publish release.')
    args=parser.parse_args()
    try:
        updater=V5Updater(args.root,from_package=args.from_package)
        if args.action=='run':
            updater.run_local()
        elif args.action=='check':
            print(updater.check_current())
        elif args.action=='diagnose':
            return updater.diagnose()
        else:
            print(updater.update() if args.action=='update' else updater.rollback())
        return 0
    except (UpdateError,BusyError,OSError,ValueError,KeyError,TypeError) as exc:
        # No exception text, paths, Git/pip output or .env content in this novice-facing flow.
        code=str(exc) if isinstance(exc,(UpdateError,BusyError,ValueError)) and re.fullmatch('[A-Z0-9_]{1,150}',str(exc)) else 'LOCAL_CHECK_OR_BACKUP_FAILED'
        print('V5 CHUA HOAN TAT:',code)
        print('Giu nguyen DB/.env; khong pull main hoac reset. '
              'Can dung Agent, Python 3.13.5, Git, mang va goi V5 da duoc duyet. '
              'Neu chua co release nghiem thu, tiep tuc dung V2. Xem HUONG_DAN_CAP_NHAT_V5.txt.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
