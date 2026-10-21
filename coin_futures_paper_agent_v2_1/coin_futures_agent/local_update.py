"""One-click, reviewed-pin local updater. Stdlib only; never git pull/reset or remote execution."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import webbrowser
import zipfile

from local_agent import FileLock, BusyError, atomic_json, locked, local_port, local_url
from safe_preupdate_backup import backup_bundle, verify_bundle, restore_bundle, checked_relative

ROOT = Path(__file__).resolve().parent
APP_SUBDIR = 'coin_futures_paper_agent_v2_1/coin_futures_agent'
V2_BASE = '534011468670993e656b898d1ed049ebcfab8997'


class UpdateError(RuntimeError):
    pass


def command(args, *, cwd, timeout=120, binary=False, env=None):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        raise UpdateError('COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
    if result.returncode:
        # Git/pip errors can contain authenticated URLs or .env details; never echo captured output.
        raise UpdateError('COMMAND_FAILED_CHECK_GIT_NETWORK_OR_DEPENDENCIES')
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace').strip()


def python_at(venv):
    return Path(venv)/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def port_open():
    try:
        with socket.create_connection(('127.0.0.1', local_port()), timeout=.3):
            return True
    except OSError:
        return False


class Updater:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.state = self.root/'.agent-updater'
        self.journal = self.state/'transaction.json'
        self.installed = self.state/'installed.json'

    def git(self, *args, binary=False):
        return command(['git', *args], cwd=self.root, binary=binary)

    def current(self):
        if self.installed.exists():
            return json.loads(self.installed.read_text(encoding='utf-8'))
        return {'sha': self.git('rev-parse', 'HEAD'), 'code': str(self.root),
                'python': str(python_at(self.root/'.venv'))}

    def approved(self):
        path = self.root/'approved_release.json'
        if not path.exists():
            path = Path(__file__).with_name('approved_release.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('manifest_version') != 1:
            raise UpdateError('UNSUPPORTED_APPROVAL_MANIFEST')
        release = data.get('approved_release')
        local_pin = release is not None
        if release is None:
            release = self.published_release()
            if release is None:
                return None
        if (not re.fullmatch('[0-9a-f]{40}', release.get('sha', '')) or release.get('reviewed') is not True
                or not re.fullmatch(r'https://github.com/amen090104-collab/coin-futures-agent/pull/[0-9]+', release.get('review_url', ''))):
            raise UpdateError('INVALID_APPROVED_RELEASE_PIN')
        if local_pin:
            self.verify_pin(release)
        return release

    def api(self, path):
        request = urllib.request.Request('https://api.github.com/repos/amen090104-collab/coin-futures-agent/'+path,
                                         headers={'Accept':'application/vnd.github+json','User-Agent':'coin-agent-local-updater'})
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise UpdateError('APPROVED_RELEASE_LOOKUP_FAILED_NO_UPDATE') from None
        except (OSError, ValueError):
            raise UpdateError('OFFLINE_CANNOT_VERIFY_APPROVED_RELEASE') from None

    def published_release(self):
        """Public, maintainer-published stable local release + merged review + successful CI."""
        release = self.api('releases/latest')
        if not release or release.get('draft') or release.get('prerelease') or not re.fullmatch(r'local-v[0-9]+\.[0-9]+\.[0-9]+',release.get('tag_name','')):
            return None
        try:
            pin = json.loads(release['body'])['approved_release']
            sha = pin['sha']
            if not re.fullmatch('[0-9a-f]{40}',sha) or pin.get('reviewed') is not True:
                raise ValueError
            match = re.fullmatch(r'https://github.com/amen090104-collab/coin-futures-agent/pull/([0-9]+)',pin['review_url'])
            if not match:
                raise ValueError
            self.verify_pin(pin)
            return pin
        except (ValueError, KeyError, TypeError):
            raise UpdateError('PUBLISHED_RELEASE_NOT_REVIEWED_OR_CI_NOT_GREEN') from None

    def verify_pin(self, pin):
        """A local JSON pin does not bypass the public PR/CI approval gate."""
        try:
            sha = pin['sha']
            match = re.fullmatch(r'https://github.com/amen090104-collab/coin-futures-agent/pull/([0-9]+)',pin['review_url'])
            if not match:
                raise ValueError
            pr = self.api('pulls/'+match[1])
            checks = self.api('commits/'+sha+'/check-runs')
            required = {'test (ubuntu-latest, Python 3.12)', 'test (windows-latest, Python 3.13.5)'}
            runs = {c['name']: c for c in (checks or {}).get('check_runs', []) if c.get('app',{}).get('slug') == 'github-actions'}
            if (not pr or not pr.get('merged_at') or sha not in {pr.get('merge_commit_sha'),pr.get('head',{}).get('sha')}
                    or not required <= runs.keys() or any(runs[name].get('status') != 'completed'
                        or runs[name].get('conclusion') != 'success' for name in required)):
                raise ValueError
            # A mutable tag never determines the executed revision: always fetch the reviewed SHA.
            return True
        except (ValueError, KeyError, TypeError):
            raise UpdateError('PUBLISHED_RELEASE_NOT_REVIEWED_OR_CI_NOT_GREEN') from None

    def prerequisites(self):
        if sys.version_info < (3, 12):
            raise UpdateError('PYTHON_3_12_OR_NEWER_REQUIRED')
        if shutil.which('git') is None:
            raise UpdateError('GIT_NOT_INSTALLED')
        if self.working_tree_dirty():
            raise UpdateError('DIRTY_WORKING_TREE_COMMIT_OR_SAVE_CHANGES_FIRST')
        if getattr(self, 'untracked_count', 0):
            print('Co', self.untracked_count, 'tep chua duoc Git theo doi (ke ca launcher cu). Giu nguyen; Update khong chay, xoa hay ghi de cac tep nay.')
        remote = self.git('remote', 'get-url', 'origin')
        if remote.rstrip('/') not in ('https://github.com/amen090104-collab/coin-futures-agent.git',
                                      'https://github.com/amen090104-collab/coin-futures-agent',
                                      'git@github.com:amen090104-collab/coin-futures-agent.git'):
            raise UpdateError('UNEXPECTED_ORIGIN')
        if shutil.disk_usage(self.root).free < 2*1024**3:
            raise UpdateError('NEED_AT_LEAST_2GB_FREE_PLUS_BACKUP_SIZE')
        probe = self.state/'write-check'
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b'')
        probe.unlink()

    def working_tree_dirty(self):
        raw = self.git('status', '--porcelain=v1', '-z', '--untracked-files=all', '--', ':(top,glob)**',
                             ':(top,exclude)'+APP_SUBDIR+'/.agent-updater',
                             ':(top,exclude)'+APP_SUBDIR+'/local_update_settings.json', binary=True)
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', errors='replace')
        entries = [v for v in raw.split('\0') if v]
        self.untracked_count = sum(v.startswith('?? ') for v in entries)
        # Source is staged from Git into a new release directory; ordinary untracked
        # files stay in the checkout and never become candidate code or commands.
        return any(not v.startswith('?? ') for v in entries)

    def data_paths(self):
        data = {}
        config = self.root/'local_update_settings.json'
        if config.exists():
            data = json.loads(config.read_text(encoding='utf-8'))
        reports = data.get('reports', ['reports'])
        # Only read the report path setting; never print .env values or read credentials.
        # REPORTS_DIR can be overridden by process env; refuse external paths rather than omit backup.
        report_setting = os.environ.get('REPORTS_DIR')
        env_path = self.root/'.env'
        if env_path.exists() and report_setting is None:
            for line in env_path.read_text(encoding='utf-8-sig').splitlines():
                match = re.fullmatch(r'\s*(?:export\s+)?REPORTS_DIR\s*=\s*(.*?)\s*', line, re.I)
                if match:
                    value = match[1]
                    if value.startswith(('\"', "'")):
                        if len(value) < 2 or value[-1] != value[0]:
                            raise UpdateError('UNSUPPORTED_REPORTS_DIR_CONFIG')
                        value = value[1:-1]
                    else:
                        value = value.split(' #', 1)[0].rstrip()
                    if '$' in value or '%' in value:
                        raise UpdateError('REPORTS_DIR_EXPANSION_NEEDS_EXPLICIT_LOCAL_PATH')
                    report_setting = value
        if report_setting:
            reports = list(dict.fromkeys([*reports, report_setting]))
        databases = list(dict.fromkeys([*data.get('databases', []),
                                       *[p.name for p in self.root.glob('*.db') if p.name != 'agent.db']]))
        for relative in [*reports, *databases]:
            checked_relative(self.root, relative)
            if Path(relative).parts[0].casefold() in {'.agent-updater', 'backups', '.git', '.venv'}:
                raise UpdateError('UNSAFE_BACKUP_CONFIGURATION')
        size = sum(p.stat().st_size for p in self.root.glob('*.db*') if p.is_file())
        for relative in reports:
            folder = checked_relative(self.root, relative)
            size += sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
        if shutil.disk_usage(self.root).free < 2*1024**3+size*3:
            raise UpdateError('INSUFFICIENT_BACKUP_DISK_SPACE')
        return databases, reports

    def stop(self, *, wait_sec=60):
        owner = locked(self.state/'agent.lock')
        if not owner:
            if port_open():
                raise UpdateError('UNMANAGED_AGENT_STOP_OLD_WINDOW_WITH_CTRL_C_THEN_RETRY')
            return False
        (self.state/'stop.request').touch()
        deadline = time.monotonic()+wait_sec
        while time.monotonic() < deadline:
            if not locked(self.state/'agent.lock') and not port_open():
                return True
            time.sleep(.2)
        raise UpdateError('AGENT_DID_NOT_STOP_NO_UPDATE_PERFORMED')

    def stage(self, release):
        sha = release['sha']
        self.git('fetch', '--no-tags', 'origin', sha)
        if self.git('rev-parse', 'FETCH_HEAD') != sha:
            raise UpdateError('FETCHED_COMMIT_MISMATCH')
        self.git('merge-base', '--is-ancestor', V2_BASE, sha)
        # Preserve clean but diverged local commits too; do not silently downgrade a newer install.
        self.git('merge-base', '--is-ancestor', self.current()['sha'], sha)
        destination = self.state/'releases'/sha
        # Never reuse an incomplete environment after a failed pip install.
        if destination.exists():
            shutil.rmtree(destination)
        code = destination/'code'
        code.mkdir(parents=True)
        # git archive applies the current subdirectory prefix even with SHA:path.
        # Run at the repository root, otherwise an app-directory invocation yields an empty ZIP.
        repository = self.git('rev-parse', '--show-toplevel')
        archive = self.git('-C', repository, 'archive', '--format=zip', sha+':'+APP_SUBDIR, binary=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for info in z.infolist():
                checked_relative(code, info.filename.rstrip('/'))
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise UpdateError('RELEASE_SYMLINK_REJECTED')
            z.extractall(code)
        for name in ('local_agent.py', 'release_probe.py', 'app/rei_v3.py', 'requirements.txt'):
            if not (code/name).is_file():
                raise UpdateError('INCOMPATIBLE_RELEASE')
        self.create_environment(destination/'venv')
        interpreter = python_at(destination/'venv')
        self.install_dependencies(interpreter, code)
        command([str(interpreter), '-m', 'pip', 'check'], cwd=code)
        return {'sha': sha, 'code': str(code), 'python': str(interpreter), 'review_url': release['review_url']}

    def create_environment(self, destination):
        command([sys.executable, '-m', 'venv', str(destination)], cwd=self.root)

    def install_dependencies(self, interpreter, code):
        command([str(interpreter), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(code/'requirements.txt')],
                cwd=code, timeout=600)

    def probe(self, candidate, backup):
        command([candidate['python'], str(Path(candidate['code'])/'release_probe.py'), str(backup)],
                cwd=self.root, timeout=60)

    def start(self, install):
        # Manager owns the process; stdout/stderr inherit user's local console, never uploaded.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        manager = Path(install['code'])/'local_agent.py'
        if not manager.exists():
            manager = Path(__file__).with_name('local_agent.py')
        environment = dict(os.environ, PYTHONUTF8='1')
        return subprocess.Popen([install['python'], str(manager),
                                 '--root', str(self.root), '--maintenance-start'],
                                cwd=self.root, creationflags=flags, shell=False, env=environment)

    def healthy(self, child, sha, *, wait_sec=60):
        deadline = time.monotonic()+wait_sec
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if child.poll() is not None:
                return False
            try:
                with opener.open(local_url()+'/local/health', timeout=1) as response:
                    data = json.load(response)
                if data == {'ok': True, 'release_sha': sha, 'pid': child.pid}:
                    return True
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        return False

    def stop_child(self, child):
        if child.poll() is not None:
            return
        (self.state/'stop.request').touch()
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            # Only our own child, never a process discovered by name/PID from another application.
            child.terminate()
            child.wait(timeout=10)
        if locked(self.state/'agent.lock') or port_open():
            raise UpdateError('CHILD_NOT_STOPPED_RESTORE_BLOCKED')

    def recover(self):
        if not self.journal.exists():
            return False
        txn = json.loads(self.journal.read_text(encoding='utf-8'))
        if txn['phase'] in {'COMMITTED', 'ROLLED_BACK'}:
            return False
        self.stop()
        with FileLock(self.state/'agent.lock'):
            restore_bundle(self.root, checked_relative(self.root, txn['backup']))
            atomic_json(self.installed, txn['old'])
        atomic_json(self.journal, {**txn, 'phase': 'ROLLED_BACK'})
        print('Da phuc hoi giao dich cap nhat bi gian doan; DB va .env da kiem tra. Bam run.bat de chay ban cu.')
        return True

    def update(self):
        with FileLock(self.state/'maintenance.lock'):
            if self.recover():
                return 'RECOVERED_INTERRUPTED_UPDATE'
            self.prerequisites()
            current, release = self.current(), self.approved()
            print('Current version:', current['sha'])
            print('Available version:', release['sha'] if release else 'Chua co ban moi duoc duyet')
            if not release or release['sha'] == current['sha']:
                return 'NO_NEWER_APPROVED_VERSION'
            # Stage dependencies before downtime. Existing checkout/venv remains intact.
            candidate = self.stage(release)
            databases, reports = self.data_paths()
            was_running = self.stop()
            txn, child = None, None
            try:
                with FileLock(self.state/'agent.lock'):
                    backup = backup_bundle(self.root, extra_databases=databases, reports=reports)
                    verify_bundle(backup)
                    self.probe(candidate, backup)
                    txn = {'phase': 'PREPARED', 'backup': backup.relative_to(self.root).as_posix(),
                           'old': current, 'candidate': candidate, 'was_running': was_running}
                    atomic_json(self.journal, txn)
                    atomic_json(self.installed, candidate)
                child = self.start(candidate)
                if not self.healthy(child, candidate['sha']):
                    raise UpdateError('NEW_AGENT_HEALTH_CHECK_FAILED')
                atomic_json(self.journal, {**txn, 'phase': 'COMMITTED'})
                print('Thanh cong. Installed git SHA:', candidate['sha'])
                self.child = child
                webbrowser.open(local_url())
                return 'UPDATED'
            except BaseException:
                if child is not None:
                    self.stop_child(child)
                if txn:
                    with FileLock(self.state/'agent.lock'):
                        restore_bundle(self.root, self.root/txn['backup'])
                        atomic_json(self.installed, current)
                    atomic_json(self.journal, {**txn, 'phase': 'ROLLED_BACK'})
                # Do not auto-run a legacy unmanaged version without the supervisor lock.
                print('Cap nhat dung. DB/.env duoc giu hoac phuc hoi; ban cu con nguyen. Bam run.bat de chay lai.')
                raise

    def rollback(self):
        with FileLock(self.state/'maintenance.lock'):
            if self.recover():
                return 'RECOVERED_INTERRUPTED_UPDATE'
            if not self.journal.exists():
                return 'NO_ROLLBACK_AVAILABLE'
            txn = json.loads(self.journal.read_text(encoding='utf-8'))
            if txn['phase'] != 'COMMITTED':
                return 'NO_ROLLBACK_AVAILABLE'
            self.stop()
            # Deliberate rollback of code only: keep trades accumulated AFTER a successful upgrade.
            with FileLock(self.state/'agent.lock'):
                backup_bundle(self.root, extra_databases=self.data_paths()[0], reports=self.data_paths()[1])
                atomic_json(self.installed, txn['old'])
            atomic_json(self.journal, {**txn, 'phase': 'ROLLED_BACK'})
            return 'CODE_ROLLED_BACK_DATA_PRESERVED_START_RUN_BAT'


def main():
    parser = argparse.ArgumentParser(description='Cap nhat local; khong deploy Render, khong update qua HTTP.')
    parser.add_argument('action', choices=('update', 'rollback', 'run', 'setup'), nargs='?', default='update')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    updater = Updater(args.root)
    try:
        if args.action == 'update':
            result = updater.update()
            print(result)
            if result == 'UPDATED':
                try:
                    updater.child.wait()
                except KeyboardInterrupt:
                    updater.stop_child(updater.child)
        elif args.action == 'rollback':
            print(updater.rollback())
        else:
            with FileLock(updater.state/'maintenance.lock'):
                if updater.journal.exists() and json.loads(updater.journal.read_text(encoding='utf-8'))['phase'] == 'PREPARED':
                    raise UpdateError('INTERRUPTED_UPDATE_CLICK_CAP_NHAT_TO_RECOVER_FIRST')
                if locked(updater.state/'agent.lock') or port_open():
                    raise UpdateError('AGENT_ALREADY_RUNNING_STOP_OR_OPEN_EXISTING_BROWSER')
                if not (updater.root/'.env').exists():
                    shutil.copy2(updater.root/'.env.example', updater.root/'.env')
                current = updater.current()
                if not Path(current['python']).is_file():
                    command([sys.executable, '-m', 'venv', str(updater.root/'.venv')], cwd=updater.root)
                    command([current['python'], '-m', 'pip', 'install', '-r', str(updater.root/'requirements.txt')], cwd=updater.root, timeout=600)
                command([current['python'], '-m', 'pip', 'check'], cwd=updater.root)
                atomic_json(updater.installed, current)
                child = updater.start(current)
                if not updater.healthy(child, current['sha']):
                    updater.stop_child(child)
                    raise UpdateError('START_HEALTH_CHECK_FAILED')
                webbrowser.open(local_url())
            # Keep local console open for app logs and Ctrl+C, no orphan task on launcher exit.
            try:
                child.wait()
            except KeyboardInterrupt:
                updater.stop_child(child)
    except (UpdateError, BusyError, OSError, ValueError, KeyError) as exc:
        code = str(exc) if isinstance(exc, (UpdateError, BusyError)) and re.fullmatch('[A-Z0-9_]+', str(exc)) else 'LOCAL_CHECK_OR_BACKUP_FAILED'
        print('KHONG HOAN TAT:', code)
        if code == 'DIRTY_WORKING_TREE_COMMIT_OR_SAVE_CHANGES_FIRST':
            print('Ma nguon Git da thay doi. Giu nguyen cac tep va nho nguoi bao tri xu ly; khong can nhap Git commands hay reset files.')
        print('Kiem tra Python >=3.12, Git, mang, working tree sach, dung agent cu va dung luong dia. Du lieu/secrets khong duoc in ra.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
