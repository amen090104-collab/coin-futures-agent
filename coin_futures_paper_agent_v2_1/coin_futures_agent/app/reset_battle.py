from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .battle_storage import init_battle_db, reset_strategy_battle_data
from .config import settings
from .storage import backup_database, init_db


def main() -> None:
    init_db()
    init_battle_db()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    db_backup = backup_database(settings.backup_dir, max(settings.backup_retention, 20))

    env_path = Path(".env")
    env_backup = None
    if env_path.exists():
        env_backup_path = backup_dir / f"env-pre-battle-{stamp}.txt"
        shutil.copy2(env_path, env_backup_path)
        env_backup = str(env_backup_path)

    reports_dir = Path(settings.reports_dir)
    archived_reports = None
    if reports_dir.exists() and any(reports_dir.iterdir()):
        archive = backup_dir / f"reports-pre-battle-{stamp}"
        if archive.exists():
            shutil.rmtree(archive)
        shutil.move(str(reports_dir), str(archive))
        archived_reports = str(archive)

    result = reset_strategy_battle_data(settings.battle_start_balance)

    print("Strategy Battle reset completed.")
    print(f"Database backup: {db_backup}")
    if env_backup:
        print(f"Env backup: {env_backup}")
    if archived_reports:
        print(f"Old reports archived: {archived_reports}")
    print(f"Starting balance each case: {result['starting_balance_each']:.2f} USDT")
    for strategy in result["strategies"]:
        print(
            f"- {strategy['strategy_id']}: {strategy['name']} | "
            f"RR {strategy['rr']} | reverse={strategy['reverse']}"
        )


if __name__ == "__main__":
    main()
