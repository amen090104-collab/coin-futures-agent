"""Run standalone Reverse Research beside (not inside) the six-case trader.

python bot.py --root <AGENT_ROOT> --once
python bot.py --root <AGENT_ROOT> --watch --interval 600

The process never imports trading app/main, opens agent.db, sends Telegram,
places orders or writes to the trader's database/reports/GitHub.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from engine import (load_backup, load_daily, deduplicate, save_json_atomic, study)



@contextmanager
def exclusive_research_process(root: Path):
    """One running research worker per installed Windows trading root."""
    workspace = root / "reverse_research_data"
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / ".worker.lock").open("a+b") as handle:
        handle.seek(0)
        handle.write(b"1")
        handle.flush()
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _latest_backup(root: Path) -> Path | None:
    candidates = sorted((root / "history_archives").glob("all-history-*.zip"))
    return candidates[-1] if candidates else None


def run_cycle(root: Path, *, seed: Path | None = None) -> dict:
    root = root.resolve()
    history = (seed or _latest_backup(root))
    past = []
    historic_research = {}
    if history is not None:
        past, historic_research = load_backup(history, include_legacy=True)
    timezone_name = "Asia/Ho_Chi_Minh"
    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    recent, rejected = load_daily(root / "reports", before_day=today)
    all_trades = deduplicate(past, recent)
    if history is None and not all_trades:
        return {"status": "NEEDS_FIRST_HISTORY_BACKUP", "required_action":
                "Create local full archive with BACKUP_HISTORY.bat; do not delete old Reverse DB."}
    data_hash = hashlib.sha256(json.dumps(
        {"paper_trades": all_trades, "legacy_research": historic_research},
        sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()
    workspace = root / "reverse_research_data"
    marker_path = workspace / "state.json"
    state = {}
    if marker_path.is_file():
        try:
            state = json.loads(marker_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    if state.get("data_hash") == data_hash and (workspace / "latest.json").is_file():
        return {"status": "NO_NEW_CLOSED_TRADES", "total": len(all_trades),
                "github_uploaded": False, "real_orders": 0}
    outcome = study(all_trades)
    outcome["previous_reverse_research_history"] = historic_research
    outcome.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "timezone": timezone_name,
        "source_seed_archive": history.name if history else None,
        "seed_trade_count": len(past),
        "new_daily_trade_files_count": len(recent),
        "rejected_day_files": rejected,
        "data_hash": data_hash,
        "mode": "REVERSE_RESEARCH_OFFLINE",
        "backtest_verified_profitable": False,
        "trading_integration": "NONE",
    })
    save_json_atomic(workspace / "latest.json", outcome)
    save_json_atomic(workspace / "reports" / today / "reverse-research.json", outcome)
    save_json_atomic(marker_path, {"data_hash": data_hash, "last_study_utc":
                                  outcome["generated_at_utc"], "closed_trades": len(all_trades)})
    return {"status": "RESEARCHED", "total": len(all_trades),
            "seed": len(past), "daily_records": len(recent),
            "rejected_daily_files": rejected, "model_status": {
                k: v["status"] for k, v in outcome["long_short_models"].items()},
            "report": str(workspace / "latest.json"), "github_uploaded": False,
            "real_orders": 0, "paper_orders": 0}


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--root", type=Path, default=Path.cwd())
    cli.add_argument("--seed", type=Path, help="Explicit complete locally verified history ZIP")
    flags = cli.add_mutually_exclusive_group(required=True)
    flags.add_argument("--once", action="store_true")
    flags.add_argument("--watch", action="store_true")
    cli.add_argument("--interval", type=int, default=600)
    args = cli.parse_args()
    if args.interval < 60:
        cli.error("Research interval must be 60 seconds or greater")
    if not args.root.is_dir():
        cli.error("Agent root is not a directory")
    if args.seed and not args.seed.is_file():
        cli.error("History backup ZIP does not exist")
    try:
        with exclusive_research_process(args.root.resolve()):
            while True:
                try:
                    print(json.dumps(run_cycle(args.root, seed=args.seed),
                                     ensure_ascii=False), flush=True)
                except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
                    # Never print arbitrary file contents or tokens.
                    print("RESEARCH_CYCLE_FAILED:", type(exc).__name__, flush=True)
                    if args.once:
                        return 1
                if args.once:
                    return 0
                try:
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    print("RESEARCH_STOPPED_WITHOUT_CHANGING_TRADING_BOT", flush=True)
                    return 0
    
    except OSError:
        print("RESEARCH_ALREADY_RUNNING_IN_ANOTHER_PROCESS", flush=True)
        return 2

if __name__ == "__main__":
    sys.exit(main())
