from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

import httpx

from .config import settings
from .storage import set_system_state


API_ROOT = "https://api.github.com"

APP_ROOT = Path(__file__).resolve().parent.parent


def report_root() -> Path:
    """Resolve relative report directories against the application, not shell cwd."""
    p = Path(settings.reports_dir).expanduser()
    return p if p.is_absolute() else APP_ROOT / p


def local_report_status(day: str) -> dict[str, Any]:
    root = report_root()
    folder = root / day
    return {
        "day": day, "reports_dir": str(root), "exists": folder.is_dir(),
        "files": {name: (folder / name).exists() for name in (
            "daily-report.json", "daily-report.md", "daily-report.html",
            "daily-analysis.json", "daily-analysis.md", "daily-analysis.html"
        )},
    }


def _safe_repo(repo: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo))


def _diagnose_response(resp: httpx.Response, repo: str) -> str:
    code = resp.status_code
    if code in (401, 403):
        return f"GitHub HTTP {code}: token invalid, expired, or lacking Contents write permission for {repo}"
    if code == 404:
        return f"GitHub HTTP 404: repository {repo} not found or token has no access; create/private-connect it first"
    if code == 409:
        return "GitHub HTTP 409: target branch missing or concurrent update; create the branch or retry"
    if code == 422:
        return "GitHub HTTP 422: target branch or submitted file invalid; check branch and repository configuration"
    return f"GitHub HTTP {code}: {resp.text[:220]}"



def _enabled() -> bool:
    return bool(
        settings.report_github_sync_enabled
        and settings.report_github_repo.strip()
        and settings.report_github_token.strip()
    )


def sync_status() -> dict[str, Any]:
    return {
        "enabled": bool(settings.report_github_sync_enabled),
        "configured": bool(settings.report_github_repo.strip() and settings.report_github_token.strip()),
        "repo": settings.report_github_repo.strip(),
        "branch": settings.report_github_branch.strip() or "main",
        "base_path": settings.report_github_path.strip().strip("/") or "reports",
        "local_reports_dir": str(report_root()),
    }


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.report_github_token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "coin-futures-agent-report-sync/4.3.1",
    }


async def _existing_sha(
    client: httpx.AsyncClient,
    repo: str,
    remote_path: str,
    branch: str,
) -> str | None:
    r = await client.get(
        f"{API_ROOT}/repos/{repo}/contents/{remote_path}",
        params={"ref": branch},
    )
    if r.status_code == 404:
        return None
    if r.is_error:
        raise RuntimeError(_diagnose_response(r, repo))
    payload = r.json()
    return str(payload.get("sha") or "") or None


async def _put_text_file(
    client: httpx.AsyncClient,
    repo: str,
    branch: str,
    remote_path: str,
    text: str,
    message: str,
) -> dict[str, Any]:
    sha = await _existing_sha(client, repo, remote_path, branch)
    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    r = await client.put(
        f"{API_ROOT}/repos/{repo}/contents/{remote_path}",
        json=body,
    )
    if r.is_error:
        raise RuntimeError(_diagnose_response(r, repo))
    data = r.json()
    return {
        "path": remote_path,
        "updated": bool(sha),
        "commit_sha": (data.get("commit") or {}).get("sha"),
        "html_url": (data.get("content") or {}).get("html_url"),
    }


async def sync_report_files(
    day: str,
    report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = sync_status()
    now = datetime.now(timezone.utc).isoformat()

    if not settings.report_github_sync_enabled:
        result = {**state, "ok": False, "skipped": True, "reason": "disabled", "at": now}
        set_system_state("report_github_sync", result)
        return result

    if not state["configured"]:
        result = {
            **state,
            "ok": False,
            "skipped": True,
            "reason": "missing REPORT_GITHUB_REPO or REPORT_GITHUB_TOKEN",
            "at": now,
        }
        set_system_state("report_github_sync", result)
        return result

    repo = state["repo"]
    branch = state["branch"]
    base_path = state["base_path"]
    if not _safe_repo(repo):
        result = {**state, "ok": False, "skipped": False, "report_date": day,
                  "reason": "REPORT_GITHUB_REPO must be owner/repository", "at": now}
        set_system_state("report_github_sync", result)
        return result
    local_dir = report_root() / day
    candidates = [
        local_dir / "daily-report.json",
        local_dir / "daily-report.md",
        local_dir / "daily-report.html",
        local_dir / "daily-analysis.json",
        local_dir / "daily-analysis.md",
        local_dir / "daily-analysis.html",
    ]
    existing = [p for p in candidates if p.exists()]
    if not (local_dir / "daily-report.json").exists():
        # The official report generator is source of truth. Regenerate only for
        # today/yesterday; older reports must not be backfilled using future stats.
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        from .battle_reports import generate_battle_and_save
        from .reports import generate_and_save
        local_today = datetime.now(ZoneInfo(settings.timezone)).date()
        allowed = {local_today.isoformat(), (local_today - timedelta(days=1)).isoformat()}
        if day in allowed:
            try:
                (generate_battle_and_save if settings.strategy_battle_enabled else generate_and_save)(day)
            except Exception as exc:
                result = {**state, "ok": False, "skipped": False, "report_date": day,
                          "reason": "Report generation failed: " + str(exc)[:350],
                          "local": local_report_status(day), "at": now}
                set_system_state("report_github_sync", result)
                return result
        existing = [p for p in candidates if p.exists()]
    if not (local_dir / "daily-report.json").is_file():
        result = {
            **state,
            "ok": False,
            "skipped": False,
            "reason": f"Missing daily-report.json for {day}. Local folder: {local_dir}",
            "local": local_report_status(day),
            "at": now,
        }
        set_system_state("report_github_sync", result)
        return result

    uploaded: list[dict[str, Any]] = []
    try:
        timeout = httpx.Timeout(settings.report_github_timeout_sec)
        async with httpx.AsyncClient(headers=_headers(), timeout=timeout) as client:
            repo_check = await client.get(f"{API_ROOT}/repos/{repo}")
            if repo_check.is_error:
                raise RuntimeError(_diagnose_response(repo_check, repo))
            repo_meta = repo_check.json()
            visibility = "private" if bool(repo_meta.get("private")) else "public"

            for local_path in existing:
                remote_path = f"{base_path}/{day}/{local_path.name}"
                uploaded.append(
                    await _put_text_file(
                        client,
                        repo,
                        branch,
                        remote_path,
                        local_path.read_text(encoding="utf-8"),
                        f"Daily trading report {day}: {local_path.name}",
                    )
                )

            latest_payload = (
                local_dir.joinpath("daily-report.json").read_text(encoding="utf-8")
                if local_dir.joinpath("daily-report.json").exists()
                else "{}"
            )
            latest_path = f"{base_path}/latest.json"
            uploaded.append(
                await _put_text_file(
                    client,
                    repo,
                    branch,
                    latest_path,
                    latest_payload,
                    f"Update latest trading report to {day}",
                )
            )

            analysis_path = local_dir / "daily-analysis.json"
            if analysis_path.exists():
                uploaded.append(
                    await _put_text_file(
                        client, repo, branch, f"{base_path}/latest-analysis.json",
                        analysis_path.read_text(encoding="utf-8"),
                        f"Update latest analysis to {day}",
                    )
                )
                research_history_path = report_root() / "research-history.json"
                if research_history_path.exists():
                    uploaded.append(
                        await _put_text_file(
                            client, repo, branch, f"{base_path}/research-history.json",
                            research_history_path.read_text(encoding="utf-8"),
                            f"Update research history through {day}",
                        )
                    )

        result = {
            **state,
            "ok": True,
            "skipped": False,
            "report_date": day,
            "visibility": visibility,
        "local": local_report_status(day),
            "uploaded": uploaded,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        set_system_state("report_github_sync", result)
        return result
    except Exception as exc:
        result = {
            **state,
            "ok": False,
            "skipped": False,
            "report_date": day,
            "reason": str(exc)[:1000],
            "local": local_report_status(day),
            "uploaded": uploaded,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        set_system_state("report_github_sync", result)
        return result
