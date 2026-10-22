"""Approved GitHub V5.x local updater, migrated once from fd829fc9 without ZIP."""
import argparse
import json
import os
from pathlib import Path
import re

from local_agent import atomic_json, BusyError
from local_update import Updater, UpdateError, APP_SUBDIR, V2_BASE, python_at, command, source_archive
from safe_preupdate_backup import checksum, checked_relative
from v5_package import verify_folder, sha256
from v5_update import V5Updater, atomic_bytes
from remote_release import GitHub, approved, source_digest, version

BAT_ACTIONS = {'update.bat':'update', 'run.bat':'run', 'chay_agent_v2.bat':'run',
               'QUAY_LAI_BAN_CU.bat':'rollback', 'CHAN_DOAN_V5.bat':'diagnose'}
TARGETS = (*BAT_ACTIONS, '.agent-updater/update_driver.py', '.agent-updater/updater.json','HUONG_DAN_CAP_NHAT_V5.txt')


def stable_launcher(action):
    if action not in {'update','run','rollback','diagnose'}: raise ValueError('INVALID_UPDATER_ACTION')
    body = f'''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".agent-updater\\update_driver.py" goto bootstrap
set "agent_action={action}"
if "{action}"=="run" if "%~1"=="--check" set "agent_action=check"
if exist ".venv\\Scripts\\python.exe" goto venv
where py >nul 2>nul
if not errorlevel 1 goto py
python ".agent-updater\\update_driver.py" %agent_action% --root "%~dp0."
goto finish
:venv
".venv\\Scripts\\python.exe" ".agent-updater\\update_driver.py" %agent_action% --root "%~dp0."
goto finish
:py
py -3 ".agent-updater\\update_driver.py" %agent_action% --root "%~dp0."
:finish
set "agent_exit=%errorlevel%"
goto end
:bootstrap
echo BOOTSTRAP_REQUIRED_ONCE_FROM_REVIEWED_RELEASE
echo Xem HUONG_DAN_CAP_NHAT_V5.txt. Khong xoa DB hoac .env.
set "agent_exit=1"
:end
if not "%AGENT_BATCH_NO_PAUSE%"=="1" pause
exit /b %agent_exit%
'''
    return body.replace('\n','\r\n').encode('ascii')


class RemoteUpdater(V5Updater):
    def __init__(self, root, *, package_root=None):
        seed = Updater(root)
        if package_root is None:
            pointer = json.loads((seed.state/'updater.json').read_text(encoding='utf-8'))
            package_root = seed.state/'v5-runtime'/pointer['sha']
        super().__init__(root, package_root=package_root)
        self.github = GitHub(self.root)

    def api(self, path): return self.github.get(path)

    def approved(self):
        self.last_release=approved(self.api('releases/latest'), self.api)
        return self.last_release

    def working_tree_dirty(self):
        allow = []
        # Current stable launchers are deterministic, independent of release pin.
        for name, action in BAT_ACTIONS.items():
            p = self.root/name
            if p.is_file() and not p.is_symlink() and p.read_bytes()==stable_launcher(action): allow.append(name)
        # Bootstrap from unchanged fd829fc9: recognize the original package,
        # not arbitrary local edits to update.bat. Never overwrite it up front.
        try:
            legacy = verify_folder(self.root)
            if checksum(self.root/'update.bat') == legacy['files']['update.bat']: allow.append('update.bat')
        except (OSError, ValueError, KeyError): pass
        # Reuse exact legacy launcher recognition for tracked V2 run.bat.
        if self.journal.exists():
            from v5_update import launcher
            txn = json.loads(self.journal.read_text(encoding='utf-8'))
            pin = txn.get('v5_runtime_sha','')
            if re.fullmatch('[0-9a-f]{40}',pin):
                for name, action in BAT_ACTIONS.items():
                    if action=='update': continue
                    p=self.root/name
                    if p.is_file() and not p.is_symlink() and p.read_bytes()==launcher(action,pin): allow.append(name)
        raw = self.git('status','--porcelain=v1','-z','--untracked-files=all','--',':(top,glob)**',
            ':(top,exclude)'+APP_SUBDIR+'/.agent-updater', ':(top,exclude)'+APP_SUBDIR+'/local_update_settings.json',
            *[':(top,exclude)'+APP_SUBDIR+'/'+name for name in allow], binary=True)
        entries=[x for x in raw.decode('utf-8',errors='replace').split('\0') if x]
        self.untracked_count=sum(x.startswith('?? ') for x in entries)
        return any(not x.startswith('?? ') for x in entries)

    def prerequisites(self):
        super().prerequisites()
        self.verify_install(self.current())

    def stage(self, release):
        current=self.current()
        build=Path(current['code'])/'.build-info.json'
        current_version=json.loads(build.read_text(encoding='utf-8')).get('version','5.0.0') if build.exists() else '5.0.0'
        if version(release['version']) <= version(current_version) and current['sha']!=V2_BASE:
            raise UpdateError('UPDATE_BLOCKED_DOWNGRADE_OR_REBUILD_VERSION')
        # The newest updater survives an intentional Agent rollback. Do not
        # delete its own complete code directory while reactivating that release.
        pointer=self.state/'updater.json'
        if pointer.exists() and json.loads(pointer.read_text(encoding='utf-8')).get('sha')==release['sha']:
            self.git('fetch','--no-tags','origin',release['sha'])
            if self.git('rev-parse','FETCH_HEAD')!=release['sha']:raise UpdateError('FETCHED_COMMIT_MISMATCH')
            self.git('merge-base','--is-ancestor',V2_BASE,release['sha'])
            self.git('merge-base','--is-ancestor',current['sha'],release['sha'])
            code=self.state/'releases'/release['sha']/'code'
            cached={'sha':release['sha'],'code':str(code),'python':str(python_at(code.parent/'venv')),
                    'review_url':release['review_url'],'version':release['version']}
            self.verify_install(cached)
            command([cached['python'],'-m','pip','check'],cwd=code)
            repository=self.git('rev-parse','--show-toplevel')
            raw=source_archive(self.git,repository,release['sha']+':'+APP_SUBDIR)
            if source_digest(raw)!=release['source_tree_sha256']:raise UpdateError('UPDATE_BLOCKED_SOURCE_TREE_CHECKSUM')
            return cached
        candidate=super().stage(release)
        repository=self.git('rev-parse','--show-toplevel')
        archive=source_archive(self.git,repository,release['sha']+':'+APP_SUBDIR)
        if source_digest(archive)!=release['source_tree_sha256']:
            raise UpdateError('UPDATE_BLOCKED_SOURCE_TREE_CHECKSUM')
        candidate['version']=release['version']
        return candidate

    def transaction_extra(self, backup, candidate):
        # Base creates the immutable helper runtime. Replace its launcher list
        # with our complete transaction, including updater files and old BAT.
        extra=super().transaction_extra(backup,candidate)
        records=[]; folder=Path(backup)/'remote-launchers';folder.mkdir()
        for name in TARGETS:
            path=checked_relative(self.root,name)
            if path.is_symlink() or path.exists() and not path.is_file(): raise UpdateError('UPDATE_BLOCKED_LAUNCHER_PATH')
            data=path.read_bytes() if path.exists() else None
            target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
            if data is not None: target.write_bytes(data)
            new=self.target_bytes(name,candidate)
            records.append({'name':name,'existed':data is not None,'old_sha256':sha256(data) if data is not None else None,
                            'new_sha256':sha256(new)})
        return {**extra,'remote_launchers':records,'updater_protocol':1}

    def target_bytes(self, name, candidate):
        if name in BAT_ACTIONS: return stable_launcher(BAT_ACTIONS[name])
        if name=='.agent-updater/update_driver.py': return (Path(candidate['code'])/'update_driver.py').read_bytes()
        if name=='HUONG_DAN_CAP_NHAT_V5.txt': return (Path(candidate['code'])/name).read_bytes()
        if name=='.agent-updater/updater.json': return json.dumps({'sha':candidate['sha']},sort_keys=True).encode('ascii')
        raise UpdateError('UPDATE_BLOCKED_UNKNOWN_TRANSACTION_TARGET')

    def apply_transaction(self, txn):
        # Install dispatcher + pointer before replacing the old update.bat.
        for name in ('.agent-updater/update_driver.py','.agent-updater/updater.json',*BAT_ACTIONS,'HUONG_DAN_CAP_NHAT_V5.txt'):
            path=checked_relative(self.root,name);path.parent.mkdir(parents=True,exist_ok=True)
            atomic_bytes(path,self.target_bytes(name,txn['candidate']))

    def restore_transaction(self, txn):
        if 'remote_launchers' not in txn: return super().restore_transaction(txn)
        folder=checked_relative(self.root,txn['backup'])/'remote-launchers'
        for rec in txn['remote_launchers']:
            if rec['name'] not in TARGETS: raise UpdateError('UPDATE_BLOCKED_RESTORE_TARGET')
            path=checked_relative(self.root,rec['name'])
            if rec['existed'] and checksum(folder/rec['name'])!=rec['old_sha256']: raise UpdateError('UPDATE_BLOCKED_BACKUP_CHECKSUM')
            if path.exists() and checksum(path) not in {rec['old_sha256'],rec['new_sha256']}: raise UpdateError('UPDATE_BLOCKED_CONCURRENT_LAUNCHER_EDIT')
        for rec in txn['remote_launchers']:
            path=checked_relative(self.root,rec['name'])
            if rec['existed']: atomic_bytes(path,(folder/rec['name']).read_bytes())
            else: path.unlink(missing_ok=True)

    def update(self):
        result=super().update()
        if result in {'NO_APPROVED_V5_RELEASE_KEEP_V2','V5_NO_NEWER_APPROVED_RELEASE_CURRENT_VERSION_PRESERVED'}:
            # No release and current release are deliberately distinct statuses.
            release=getattr(self,'last_release',None)
            return 'NO_NEW_VERSION' if release and release['sha']==self.current()['sha'] else 'UPDATE_BLOCKED_UNAPPROVED'
        return result


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('update','run','rollback','check','diagnose'))
    p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    try:
        u=RemoteUpdater(a.root)
        if a.action=='update': print(u.update())
        elif a.action=='run': u.run_local()
        elif a.action=='rollback': print(u.rollback())
        elif a.action=='check': print(u.check_current())
        else: return u.diagnose()
        return 0
    except (UpdateError,BusyError,OSError,ValueError,KeyError,TypeError):
        # Never echo Git/HTTP/credential/path payloads.
        import sys
        exc=sys.exc_info()[1];code=str(exc) if isinstance(exc,(UpdateError,BusyError)) and re.fullmatch('[A-Z0-9_]{1,150}',str(exc)) else 'UPDATE_BLOCKED_LOCAL_CHECK'
        print(code);return 1


if __name__=='__main__': raise SystemExit(main())
