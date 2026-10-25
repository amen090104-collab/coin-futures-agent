"""Prepare report artifacts without reconstructing historical trading/research state."""
from __future__ import annotations

from .config import settings
from .report_files import bundle_status, read_snapshot, require_recent_day, validate_day, write_bundle
from .reports import generate_and_save, render_markdown, render_html
from .battle_reports import generate_battle_and_save, render_battle_markdown, render_battle_html
from .analysis_daily import generate_and_save_analysis, render_analysis_markdown, render_analysis_html
from .v44_learning import write_research_report, save_research_snapshot
from .reverse_research import write_reverse_lab_report, save_reverse_snapshot


def prepare_daily_bundle(day: str, *, refresh: bool = False) -> dict:
    validate_day(day)
    report = None
    if not refresh:
        try:
            report = read_snapshot(day, "daily-report")
        except (OSError, ValueError):
            pass
    if report is None:
        # Guard even when a generator has been replaced by a caller or test.
        require_recent_day(day)
        report = (generate_battle_and_save if settings.strategy_battle_enabled else generate_and_save)(day)

    is_battle = "strategies" in report
    write_bundle(day, "daily-report", report,
                 (render_battle_markdown if is_battle else render_markdown)(report),
                 (render_battle_html if is_battle else render_html)(report), repair=True)

    analysis = None
    errors = {}
    if settings.strategy_battle_enabled:
        if not is_battle:
            errors["daily-analysis"] = "Saved daily report is legacy; Strategy Battle analysis requires a battle snapshot"
        else:
            try:
                if not refresh:
                    try:
                        analysis = read_snapshot(day, "daily-analysis")
                        if analysis.get("source_report_created_at") != report.get("created_at"):
                            analysis = None
                    except (OSError, ValueError):
                        pass
                if analysis is None:
                    # Analysis reads the saved daily JSON, not current accounts.
                    analysis = generate_and_save_analysis(day)
                else:
                    write_bundle(day, "daily-analysis", analysis, render_analysis_markdown(analysis),
                                 render_analysis_html(analysis), repair=True)
            except Exception as exc:
                errors["daily-analysis"] = str(exc)[:500]

        research = []
        if settings.runtime_profile == "full" and settings.v44_shadow_enabled:
            research.append(("v44-research", write_research_report, save_research_snapshot))
        if settings.runtime_profile == "full" and settings.reverse_lab_enabled and settings.v44_shadow_enabled:
            research.append(("reverse-lab", write_reverse_lab_report, save_reverse_snapshot))
        for stem, generate, restore in research:
            try:
                try:
                    saved = read_snapshot(day, stem)
                except (OSError, ValueError):
                    require_recent_day(day)
                    generate(day)
                else:
                    # Keep JSON/timestamp unchanged; restore missing formats from it.
                    restore(saved, repair=True)
            except Exception as exc:
                errors[stem] = str(exc)[:500]

    artifacts = bundle_status(day)
    return {"status": "OK" if artifacts["complete"] and not errors else "PARTIAL",
            "report": report, "analysis": analysis, "artifacts": artifacts, "errors": errors}
