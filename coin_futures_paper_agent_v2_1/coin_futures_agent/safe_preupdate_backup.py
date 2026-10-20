"""Safely snapshot active SQLite/WAL before applying an application update."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import json
import hashlib
from contextlib import closing

ROOT=Path(__file__).resolve().parent


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot_database(source, destination, *, deadline_sec=30):
    source, destination = Path(source).resolve(), Path(destination)
    deadline = time.monotonic()+deadline_sec
    def progress(status, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError('DATABASE_BACKUP_TIMEOUT')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=1)) as src:
            with closing(sqlite3.connect(destination, timeout=1)) as target:
                src.backup(target, pages=100, progress=progress, sleep=.05)
                check = target.execute('PRAGMA integrity_check').fetchall()
                if check != [('ok',)]:
                    raise RuntimeError('DATABASE_BACKUP_INVALID')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def checked_relative(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or root not in path.resolve().parents:
        raise ValueError('UNSAFE_LOCAL_DATA_PATH')
    return path


def backup_bundle(root, *, extra_databases=(), reports=('reports',)):
    """After managed agent stops: complete manifest is the commit marker for rollback."""
    root = Path(root).resolve()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder = root/'backups'/'updates'/stamp
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {'version': 1, 'databases': [], 'files': [], 'directories': list(reports)}
    try:
        for relative in dict.fromkeys(('agent.db', *extra_databases)):
            source = checked_relative(root, relative)
            if not source.is_file():
                if relative != 'agent.db':
                    raise FileNotFoundError('ADDITIONAL_DATABASE_MISSING')
                manifest['agent_db_absent'] = True
                continue
            destination = checked_relative(folder, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            snapshot_database(source, destination)
            manifest['databases'].append({'path': relative, 'sha256': checksum(destination)})
        paths = [root/'.env']
        for relative in reports:
            directory = checked_relative(root, relative)
            if directory.exists():
                if not directory.is_dir():
                    raise ValueError('REPORT_PATH_NOT_DIRECTORY')
                paths.extend(p for p in directory.rglob('*') if p.is_file())
                if any(p.is_symlink() for p in directory.rglob('*')):
                    raise ValueError('SYMLINK_IN_REPORTS')
        for source in paths:
            if not source.exists():
                continue
            relative = source.relative_to(root).as_posix()
            checked_relative(root, relative)
            destination = checked_relative(folder, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if checksum(source) != checksum(destination):
                raise RuntimeError('FILE_BACKUP_INVALID')
            manifest['files'].append({'path': relative, 'sha256': checksum(destination)})
        (folder/'backup.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return folder
    except BaseException:
        # No complete manifest means never eligible for restore, even after power loss.
        (folder/'backup.json').unlink(missing_ok=True)
        raise


def verify_bundle(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'backup.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('BACKUP_VERSION_UNSUPPORTED')
    for rec in manifest['databases']+manifest['files']:
        path = checked_relative(folder, rec['path'])
        if checksum(path) != rec['sha256']:
            raise ValueError('BACKUP_CHECKSUM_MISMATCH')
    return manifest


def restore_bundle(root, folder):
    """Caller must hold maintenance AND agent locks. No secret contents printed."""
    root, folder = Path(root).resolve(), Path(folder).resolve()
    manifest = verify_bundle(folder)  # verify ALL inputs before touching destination.
    for rec in manifest['databases']:
        destination = checked_relative(root, rec['path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name+'.restore-tmp')
        snapshot_database(checked_relative(folder, rec['path']), temporary)
        for suffix in ('-wal', '-shm'):
            Path(str(destination)+suffix).unlink(missing_ok=True)
        temporary.replace(destination)
    if manifest.get('agent_db_absent'):
        for suffix in ('', '-wal', '-shm'):
            (root/('agent.db'+suffix)).unlink(missing_ok=True)
    for rec in manifest['files']:
        destination = checked_relative(root, rec['path'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checked_relative(folder, rec['path']), destination)
    # Reports created by a failed start are retained, not silently deleted.
    return manifest


def backup() -> str:
    base=ROOT/"backups"
    base.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    source=ROOT/"agent.db"
    if source.is_file():
        destination=base/f"agent-preupdate-{stamp}.db"
        try:
            uri=f"file:{source.as_posix()}?mode=ro"
            snapshot_database(source, destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    env=ROOT/".env"
    if env.is_file():
        shutil.copy2(env,base/f"env-preupdate-{stamp}.bak")
    return stamp


if __name__=="__main__":
    try:
        print("Pre-update WAL-safe backup:",backup())
    except Exception as exc:
        print("ERROR: Update stopped; backup failed:",exc,file=sys.stderr)
        sys.exit(1)
