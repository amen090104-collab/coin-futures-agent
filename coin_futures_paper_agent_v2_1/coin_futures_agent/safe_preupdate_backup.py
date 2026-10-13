"""Safely snapshot active SQLite/WAL before applying an application update."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT=Path(__file__).resolve().parent


def backup() -> str:
    base=ROOT/"backups"
    base.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    source=ROOT/"agent.db"
    if source.is_file():
        destination=base/f"agent-preupdate-{stamp}.db"
        try:
            uri=f"file:{source.as_posix()}?mode=ro"
            with sqlite3.connect(uri,uri=True,timeout=20.0) as src:
                with sqlite3.connect(str(destination),timeout=20.0) as target:
                    src.backup(target,pages=100,sleep=0.1)
                    check=target.execute("PRAGMA quick_check").fetchone()
                    if not check or check[0]!="ok":
                        raise RuntimeError("SQLite backup integrity check failed")
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
