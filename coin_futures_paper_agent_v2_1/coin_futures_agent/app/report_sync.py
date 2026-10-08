from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .storage import set_system_state


API_ROOT = "https://api.github.com"


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
    r.raise_for_status()
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
    r.raise_for_status()
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
    local_dir = Path(settings.reports_dir) / day
    candidates = [
        local_dir / "daily-report.json",
        local_dir / "daily-report.md",
        local_dir / "daily-report.html",
    ]
    existing = [p for p in candidates if p.exists()]
    if not existing:
        result = {
            **state,
            "ok": False,
            "skipped": False,
            "reason": f"no report files found for {day}",
            "at": now,
        }
        set_system_state("report_github_sync", result)
        return result

    uploaded: list[dict[str, Any]] = []
    try:
        timeout = httpx.Timeout(settings.report_github_timeout_sec)
        async with httpx.AsyncClient(headers=_headers(), timeout=timeout) as client:
            repo_check = await client.get(f"{API_ROOT}/repos/{repo}")
            repo_check.raise_for_status()
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

        result = {
            **state,
            "ok": True,
            "skipped": False,
            "report_date": day,
            "visibility": visibility,
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
            "uploaded": uploaded,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        set_system_state("report_github_sync", result)
        return result
