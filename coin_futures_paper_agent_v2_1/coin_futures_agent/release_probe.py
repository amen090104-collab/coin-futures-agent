"""Candidate preflight in isolated temporary DB, without app lifespan, network or real trades."""
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing


def probe(backup):
    from safe_preupdate_backup import verify_bundle
    manifest = verify_bundle(backup)
    with tempfile.TemporaryDirectory(prefix='agent-probe-') as directory:
        path = Path(directory)/'agent.db'
        source = Path(backup)/'agent.db'
        if source.exists():
            shutil.copy2(source, path)
        with closing(sqlite3.connect(path)) as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name, required in {'battle_trades': {'id','symbol','side','entry_context','r_multiple'},
                                   'reverse_lab_cases': {'id','cohort_id','status','net_r'}}.items():
                if name in names and not required <= {r[1] for r in db.execute('PRAGMA table_info('+name+')')}:
                    raise ValueError('INCOMPATIBLE_SOURCE_SCHEMA')
            from app.rei_v3_store import init
            init(db)
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('INTEGRITY_CHECK_FAILED')
        from app import storage
        previous = storage.DB_PATH
        try:
            storage.DB_PATH = path
            from app.main import app
            if not any(r.path == '/local/health' for r in app.routes):
                raise ValueError('CANDIDATE_HEALTH_ROUTE_MISSING')
        finally:
            storage.DB_PATH = previous
    return True


if __name__ == '__main__':
    try:
        probe(Path(sys.argv[1]))
    except Exception:
        print('PREFLIGHT_FAILED_NO_PRODUCTION_MIGRATION')
        raise SystemExit(1)
