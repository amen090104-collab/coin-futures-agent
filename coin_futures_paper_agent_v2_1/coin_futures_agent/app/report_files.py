"""Report paths, snapshot validation and artifact completeness (no trading reads)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import settings

APP_ROOT = Path(__file__).resolve().parent.parent


class HistoricalReportError(ValueError):
    pass


def report_root() -> Path:
    path = Path(settings.reports_dir).expanduser()
    if path.is_absolute():
        return path
    # The reviewed updater imports app code from immutable .agent-updater
    # releases. Local trading reports MUST remain in the persistent agent root
    # (backed up by the updater), never inside a release that gets replaced.
    data_root = os.environ.get("AGENT_DATA_ROOT")
    if data_root:
        base = Path(data_root).expanduser().resolve()
        resolved = (base / path).resolve()
        if base != resolved and base not in resolved.parents:
            raise ValueError("REPORTS_DIR_OUTSIDE_PERSISTENT_AGENT_ROOT")
        return resolved
    return APP_ROOT / path


def validate_day(day: str) -> str:
    parsed = datetime.strptime(day, "%Y-%m-%d").date()
    if parsed.isoformat() != day:
        raise ValueError("Expected YYYY-MM-DD")
    return day


def require_recent_day(day: str) -> None:
    validate_day(day)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    if day not in {today.isoformat(), (today - timedelta(days=1)).isoformat()}:
        raise HistoricalReportError(
            "Historical or future reports cannot be generated from current state; "
            "use a saved snapshot. Only today/yesterday can be finalized."
        )


def read_snapshot(day: str, stem: str, root: Path | None = None) -> dict:
    validate_day(day)
    doc = json.loads(((root or report_root()) / day / f"{stem}.json").read_text(encoding="utf-8"))
    key = "report_day" if stem in {"v44-research", "reverse-lab"} else "report_date"
    if not isinstance(doc, dict) or doc.get(key) != day:
        raise ValueError(f"{stem} snapshot date does not match {day}")
    return doc


def artifact_valid(day: str, name: str, root: Path | None = None) -> bool:
    path = (root or report_root()) / day / name
    try:
        if path.suffix == ".json":
            read_snapshot(day, path.stem, root)
            return True
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, UnicodeError):
        return False


def bundle_status(day: str) -> dict:
    validate_day(day)
    stems = ["daily-report"]
    if settings.strategy_battle_enabled:
        stems.append("daily-analysis")
        if settings.runtime_profile == "full" and settings.v44_shadow_enabled:
            stems.append("v44-research")
        # Lean preserves Reverse Lab daily evidence but no longer creates
        # placeholder V4.4 reports for background tasks that were retired.
        if settings.runtime_profile == "full" and settings.reverse_lab_enabled and settings.v44_shadow_enabled:
            stems.append("reverse-lab")
    required = [f"{stem}.{suffix}" for stem in stems for suffix in ("json", "md", "html")]
    missing = [name for name in required if not artifact_valid(day, name)]
    if "daily-analysis" in stems and not any(
        name in missing for name in ("daily-report.json", "daily-analysis.json")
    ):
        source = read_snapshot(day, "daily-report")
        analysis = read_snapshot(day, "daily-analysis")
        if analysis.get("source_report_created_at") != source.get("created_at"):
            missing.append("daily-analysis.json")
    return {"report_date": day, "complete": not missing,
            "required": required, "missing_or_invalid": missing}


def write_bundle(day: str, stem: str, snapshot: dict, markdown: str,
                 html: str, *, root: Path | None = None, repair: bool = False) -> None:
    """Replace each file atomically; repair preserves valid saved artifacts."""
    validate_day(day)
    key = "report_day" if stem in {"v44-research", "reverse-lab"} else "report_date"
    if snapshot.get(key) != day:
        raise ValueError(f"{stem} snapshot date does not match {day}")
    folder = (root or report_root()) / day
    folder.mkdir(parents=True, exist_ok=True)
    contents = {"json": json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
                "md": markdown, "html": html}
    for suffix, content in contents.items():
        name = f"{stem}.{suffix}"
        if repair and artifact_valid(day, name, root):
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder,
                                             prefix=f".{stem}-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            os.replace(temporary, folder / name)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
