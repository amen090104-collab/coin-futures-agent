"""Local Windows supervisor: one DB owner, graceful local stop, no HTTP update API."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent


def local_port():
    port = int(os.environ.get('AGENT_LOCAL_PORT', '8000'))
    if not 1024 <= port <= 65535:
        raise ValueError('INVALID_LOCAL_PORT')
    return port


def local_url():
    return 'http://127.0.0.1:'+str(local_port())


class BusyError(RuntimeError):
    pass


class FileLock:
    def __init__(self, path):
        self.path, self.handle = Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+b')
        self.handle.seek(0)
        if self.path.stat().st_size == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise BusyError('AGENT_OR_UPDATE_ALREADY_RUNNING') from None
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def locked(path):
    try:
        with FileLock(path):
            return False
    except BusyError:
        return True


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    with temporary.open('r+b') as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def run(root=ROOT, *, maintenance_start=False, health_only=False):
    root = Path(root).resolve()
    state = root/'.agent-updater'
    # Serialize process creation with update; then retain exclusive DB ownership for full lifespan.
    maintenance = None
    if not maintenance_start:
        maintenance = FileLock(state/'maintenance.lock')
        maintenance.__enter__()
    try:
        owner = FileLock(state/'agent.lock')
        owner.__enter__()
    finally:
        if maintenance:
            maintenance.__exit__()
    try:
        stop = state/'stop.request'
        stop.unlink(missing_ok=True)
        install = json.loads((state/'installed.json').read_text(encoding='utf-8')) if (state/'installed.json').exists() else {}
        code = Path(install.get('code', root)).resolve()
        # Restrict installed pointer to the current checkout or its own immutable releases.
        if code != root and state/'releases' not in code.parents:
            raise ValueError('INVALID_INSTALLED_CODE_PATH')
        os.chdir(root)
        # Persist report/trade-history CSV+JSON under the same root as agent.db.
        # The updater backs up root/reports; versioned code under releases/code
        # is immutable and must never become the reporting data directory.
        os.environ['AGENT_DATA_ROOT'] = str(root)
        sys.path.insert(0, str(code))
        os.environ['AGENT_RELEASE_SHA'] = install.get('sha', 'checkout')
        if health_only:
            os.environ['AGENT_HEALTH_PROBE_ONLY'] = '1'
        else:
            os.environ.pop('AGENT_HEALTH_PROBE_ONLY', None)
        # No dotenv/secrets passed through command line or supervisor state.
        import uvicorn
        from app.main import app
        if not any(r.path == '/local/health' for r in app.routes):
            # Legacy V2 checkout remains byte-for-byte unchanged; add read-only supervisor identity in memory.
            async def identity():
                return {'ok': True, 'release_sha': os.environ['AGENT_RELEASE_SHA'], 'pid': os.getpid()}
            app.add_api_route('/local/health', identity, methods=['GET'])
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=local_port(), workers=1))
        done = threading.Event()
        def watch():
            while not done.wait(.2):
                if stop.exists():
                    server.should_exit = True
                    return
        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        atomic_json(state/'running.json', {'pid': os.getpid(), 'parent_pid': os.getppid(),
                                          'sha': install.get('sha', 'checkout')})
        try:
            server.run()
        finally:
            done.set()
            thread.join(timeout=1)
            (state/'running.json').unlink(missing_ok=True)
            stop.unlink(missing_ok=True)
    finally:
        owner.__exit__()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--maintenance-start', action='store_true')
    parser.add_argument('--health-only', action='store_true')
    args = parser.parse_args()
    try:
        run(args.root, maintenance_start=args.maintenance_start, health_only=args.health_only)
    except (BusyError, ValueError):
        print('Agent/update dang chay hoac duong dan khong hop le. Khong khoi dong ban thu hai.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
