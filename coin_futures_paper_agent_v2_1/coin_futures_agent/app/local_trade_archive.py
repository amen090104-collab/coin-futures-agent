"""Local-only closed-trade archives, partitioned by Asia/Ho_Chi_Minh day.

Agent's SQLite database remains the authoritative Paper ledger. These CSV/JSON
files are human-readable, loss-resistant local copies; they are never uploaded.
The archive includes any old experimental cases for historical integrity even
when the active lean runtime admits only six A-F case IDs for new trades.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from .battle_storage import battle_trades_between
from .config import settings
from .report_files import report_root, validate_day
from .storage import trades_between

# Compact public columns for Excel and full research context in the LOCAL JSON.
CSV_FIELDS = (
    "id", "strategy_id", "symbol", "side", "opened_at", "closed_at",
    "entry_price", "exit_price", "stop_loss", "take_profit",
    "quantity", "score", "gross_pnl", "fees", "net_pnl",
    "r_multiple", "exit_reason", "holding_minutes",
)
JSON_FIELDS = CSV_FIELDS + (
    "position_id", "mfe_r", "mae_r", "reason_text", "reason_codes",
    "entry_context", "loss_analysis", "fix_suggestions",
)


def _utc_bounds(day: str) -> tuple[str, str]:
    d = date.fromisoformat(validate_day(day))
    start_local = datetime.combine(d, time.min, tzinfo=ZoneInfo(settings.timezone))
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).isoformat(),
            end_local.astimezone(timezone.utc).isoformat())


def _safe_excel_cell(value):
    # Untrusted text in symbols/reasons must not become an Excel formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _atomic_write(path: Path, data: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent,
            prefix=".trade-history-", suffix=".tmp", delete=False
        ) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_local_trade_history(day: str, *, root: Path | None = None) -> dict:
    """Repeatable local snapshot of all trades CLOSED on a local calendar day.

    Never queries future candles, regenerates trading outcomes, touches balances,
    changes .env or calls GitHub. Existing larger archives cannot be replaced by
    a smaller history from a stale/rolled-back DB.
    """
    day = validate_day(day)
    start, end = _utc_bounds(day)
    source = "STRATEGY_BATTLE" if settings.strategy_battle_enabled else "PAPER_LEGACY"
    rows = (battle_trades_between if settings.strategy_battle_enabled else trades_between)(start, end)
    records = [{key: row.get(key) for key in JSON_FIELDS if key in row}
               for row in sorted(rows, key=lambda t: (str(t.get("closed_at") or ""), int(t.get("id") or 0)))]
    fingerprint = hashlib.sha256(json.dumps(
        records, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()
    folder = (root or report_root()) / day
    json_path, csv_path = folder / "trade-history.json", folder / "trade-history.csv"
    if json_path.exists():
        # Protect a full-day snapshot if this Agent starts against an older DB.
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        if previous.get("trade_count", 0) > len(records):
            raise ValueError("LOCAL_ARCHIVE_SHRINK_BLOCKED: existing file has more closed trades")
        if previous.get("sha256") == fingerprint and csv_path.exists():
            return {"status": "UNCHANGED", "day": day, "trades": len(records),
                    "csv": str(csv_path), "json": str(json_path), "github_uploaded": False}

    writer_out = StringIO(newline="")
    writer = csv.writer(writer_out, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in records:
        writer.writerow([_safe_excel_cell(row.get(k)) for k in CSV_FIELDS])
    payload = {
        "archive_version": "local-trades-v1",
        "report_date": day,
        "timezone": settings.timezone,
        "paper_source": source,
        "trade_count": len(records),
        "sha256": fingerprint,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "github_uploaded": False,
        "trades": records,
    }
    folder.mkdir(parents=True, exist_ok=True)
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n")
    _atomic_write(csv_path, "\ufeff" + writer_out.getvalue())
    return {"status": "SAVED", "day": day, "trades": len(records),
            "csv": str(csv_path), "json": str(json_path), "github_uploaded": False}


def archive_recent_days(*, days: int = 7) -> dict:
    """Catch up after offline days. Bounded so startup is predictable."""
    if not 0 <= days <= 31:
        raise ValueError("Days must be between 0 and 31")
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    saved = []
    for offset in range(days, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        saved.append(export_local_trade_history(day))
    return {"status": "LOCAL_ONLY", "days": len(saved),
            "trades": sum(x["trades"] for x in saved),
            "changed": sum(x["status"] == "SAVED" for x in saved),
            "github_uploaded": False}
