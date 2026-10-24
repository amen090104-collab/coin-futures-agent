"""Offline, non-destructive archive of ALL local Paper/Reverse history.

Creates a ZIP on the user's Windows disk. NEVER commits, syncs, emails,
uploads, or opens live trading. Database WAL is captured with SQLite backup().
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _redacted_private_file(path: Path) -> bool:
    name = path.name.lower()
    return (name == ".env" or name.startswith(".env.") or name.endswith((".key", ".pem"))
            or "token" in name or "secret" in name or "credential" in name)


def _sqlite_copy(source: Path, destination: Path) -> None:
    # SQLite online backup includes committed changes in the WAL without
    # freezing or writing to the live trading ledger.
    uri = source.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        with sqlite3.connect(destination, timeout=30) as out:
            db.backup(out, pages=256, sleep=0.10)
            status = out.execute("PRAGMA integrity_check").fetchone()
            if not status or status[0] != "ok":
                raise ValueError("ARCHIVE_SQLITE_INTEGRITY_FAILED")


def build_backup(root: Path, *, destination: Path | None = None) -> dict:
    root = root.resolve(strict=True)
    if not (root / "agent.db").is_file():
        raise FileNotFoundError("AGENT_DB_MISSING_NOTHING_WAS_CHANGED")
    output = (destination or (root / "history_archives")).resolve()
    if output == root or root not in output.parents:
        raise ValueError("HISTORY_ARCHIVE_MUST_BE_UNDER_AGENT_ROOT")
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = output / ("all-history-" + now + ".zip")
    if final.exists():
        raise FileExistsError("HISTORY_ARCHIVE_ALREADY_EXISTS")
    temp_zip: Path | None = None
    with tempfile.TemporaryDirectory(prefix="history-backup-") as temp:
        staging = Path(temp)
        staged_dbs: list[tuple[Path, str]] = []
        databases = sorted(p for p in root.glob("*.db") if p.is_file() and not p.is_symlink()
                           and p.name.lower() != "research.db")
        if root / "agent.db" not in databases:
            raise ValueError("PRIMARY_AGENT_DB_NOT_FOUND")
        for dbpath in databases:
            clean = staging / dbpath.name
            _sqlite_copy(dbpath, clean)
            staged_dbs.append((clean, dbpath.name))
        files: list[tuple[Path, str]] = [*staged_dbs]
        skipped: list[str] = []
        for foldername in ("reports", "backups"):
            folder = root / foldername
            if not folder.exists():
                continue
            if folder.is_symlink():
                raise ValueError("SYMLINK_HISTORY_DIRECTORY_REJECTED")
            for path in sorted(folder.rglob("*")):
                if path.is_symlink():
                    skipped.append(path.relative_to(root).as_posix())
                    continue
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                if _redacted_private_file(path):
                    skipped.append(relative)
                    continue
                files.append((path, relative))
        # No recursion into the history_archives destination; do not archive
        # .env/credentials or immutable release source trees.
        unique = {name: path for path, name in files}
        if len(unique) != len(files):
            raise ValueError("DUPLICATE_ARCHIVE_PATH")
        stat_bytes = sum(path.stat().st_size for path, _ in files)
        if shutil.disk_usage(output).free < max(256 * 1024**2, stat_bytes * 2):
            raise OSError("INSUFFICIENT_DISK_SPACE_FOR_SAFE_HISTORY_BACKUP")
        with tempfile.NamedTemporaryFile(dir=output, prefix=".history-", suffix=".tmp",
                                         delete=False) as tmp:
            temp_zip = Path(tmp.name)
        try:
            manifest = {"archive_version": "all-trading-history-v1",
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                        "database_is_sqlite_snapshot": True,
                        "private_credentials_included": False,
                        "github_uploaded": False, "files": [],
                        "excluded_private_or_symlink_files": skipped}
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as archive:
                for path, relative in files:
                    digest = hashlib.sha256()
                    with path.open("rb") as inp, archive.open(relative, "w", force_zip64=True) as out:
                        while True:
                            block = inp.read(1024 * 1024)
                            if not block:
                                break
                            digest.update(block)
                            out.write(block)
                    manifest["files"].append({"path": relative, "sha256": digest.hexdigest()})
                archive.writestr("manifest.json", json.dumps(manifest, indent=2,
                                                             ensure_ascii=False) + "\n")
            with zipfile.ZipFile(temp_zip) as check:
                if check.testzip() is not None:
                    raise ValueError("ZIP_CRC_FAILED")
                read = json.loads(check.read("manifest.json"))
                for entry in read["files"]:
                    # Check SHA of saved bytes, not the current live ledger.
                    h = hashlib.sha256()
                    with check.open(entry["path"]) as item:
                        for buf in iter(lambda: item.read(1024 * 1024), b""):
                            h.update(buf)
                    if h.hexdigest() != entry["sha256"]:
                        raise ValueError("ARCHIVE_SHA256_VERIFICATION_FAILED")
            os.replace(temp_zip, final)
            temp_zip = None
            return {"status": "VERIFIED_LOCAL_BACKUP", "zip": str(final),
                    "file_count": len(files), "sqlite_files": [n for _, n in staged_dbs],
                    "excluded_private_or_symlinks": len(skipped),
                    "bytes": final.stat().st_size, "github_uploaded": False}
        finally:
            if temp_zip is not None:
                temp_zip.unlink(missing_ok=True)


def main() -> int:
    cli = argparse.ArgumentParser(description="Backup agent.db / reports / backups to local verified ZIP.")
    cli.add_argument("--root", type=Path, default=Path.cwd())
    cli.add_argument("--destination", type=Path)
    args = cli.parse_args()
    result = build_backup(args.root, destination=args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
