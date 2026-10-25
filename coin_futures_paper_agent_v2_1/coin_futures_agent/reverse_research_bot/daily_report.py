"""Daily local research brief: observed evidence vs holdout vs NOT-YET Shadow.

Designed to run from the separate offline Research worker. Automatically
writes one HTML, Markdown and JSON snapshot per completed Vietnam-local date
even when NO new trades arrive. Reports are refreshed only when the input
research hash changes. Never pretends historical tests equal forward Shadow.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "daily-evidence-v1"
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
MAX_CANDIDATES = 8


def _number(v):
    try:
        if v is not None:
            x = float(v)
            import math
            return x if math.isfinite(x) else None
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _local_close(trade):
    try:
        raw = datetime.fromisoformat(str(trade.get("closed_at") or "").replace("Z", "+00:00"))
        # Unqualified timestamps are NOT assigned a guessed timezone.
        return raw.astimezone(LOCAL_TZ) if raw.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _fmt(value):
    n = _number(value)
    return f"{n:+.4f}" if n is not None else "N/A"


def build_report(rows: list[dict], research: dict, *, now: datetime | None = None):
    now = now or datetime.now(LOCAL_TZ)
    if now.tzinfo is None:
        raise ValueError("Report clock must have a timezone")
    now = now.astimezone(LOCAL_TZ)
    report_day = (now.date() - timedelta(days=1)).isoformat()
    day_trades = [t for t in rows if (dt := _local_close(t)) is not None
                  and dt.date().isoformat() == report_day]
    missing_close_zone = sum(_local_close(t) is None for t in rows)
    day_sides = {}
    for side in ("LONG", "SHORT"):
        selected = [x for x in day_trades if x.get("side") == side]
        r_values = [_number(x.get("r_multiple")) for x in selected]
        day_sides[side] = {
            "closed": len(selected),
            "wins": sum((_number(x.get("net_pnl")) or 0) > 0 for x in selected),
            "losses": sum((_number(x.get("net_pnl")) or 0) < 0 for x in selected),
            "mean_R": round(sum(r_values) / len(r_values), 5)
                      if r_values and all(x is not None for x in r_values) else None,
            "known_R_count": sum(x is not None for x in r_values),
        }
    daily_by_case = {}
    for case in sorted({str(x.get("strategy_id") or "UNKNOWN") for x in day_trades}):
        for side in ("LONG", "SHORT"):
            selected = [x for x in day_trades
                        if str(x.get("strategy_id") or "UNKNOWN") == case
                        and x.get("side") == side]
            if not selected:
                continue
            daily_by_case[case + "/" + side] = {
                "closed": len(selected),
                "wins": sum((_number(x.get("net_pnl")) or 0) > 0 for x in selected),
                "losses": sum((_number(x.get("net_pnl")) or 0) < 0 for x in selected)
            }
    historical_models = []
    for side in ("LONG", "SHORT"):
        model = (research.get("long_short_models") or {}).get(side) or {}
        tested = model.get("out_of_sample_test") or {}
        baseline = model.get("out_of_sample_baseline") or {}
        historical_models.append({
            "side": side, "status": model.get("status", "NOT_EVALUATED"),
            "test_count": model.get("test", 0),
            "selected_count": tested.get("selected", 0),
            "selected_mean_R": _number(tested.get("avg_realized_r")),
            "baseline_mean_R": _number(baseline.get("avg_realized_r")),
            "evidence_level": "HISTORICAL_HOLDOUT_ONLY_NOT_SHADOW",
        })
    clusters = research.get("loss_clusters") or {}
    candidates = []
    # Research may include group metadata in latest.json, not candidate details.
    # Detailed candidates can only be included if separately supplied by caller.
    for candidate in (research.get("_daily_candidate_details") or [])[:MAX_CANDIDATES]:
        holdout = candidate.get("holdout") or {}
        inside = holdout.get("cluster") or {}
        other = holdout.get("other_known_conditions") or {}
        candidates.append({
            "id": candidate.get("hypothesis_id"), "case": (candidate.get("rule") or {}).get("case"),
            "side": (candidate.get("rule") or {}).get("side"),
            "status": candidate.get("status"),
            "holdout_supported": candidate.get("holdout_supported") is True,
            "holdout_cluster_trades": inside.get("trades", 0),
            "holdout_cluster_mean_R": _number(inside.get("mean_R")),
            "holdout_other_mean_R": _number(other.get("mean_R")),
            "holdout_missed_winners_if_avoided": candidate.get(
                "baseline_missed_winners_if_filtered_on_holdout", 0),
            "evidence_level": "HISTORICAL_HOLDOUT_ONLY_NOT_SHADOW",
        })
    experiment = research.get("automated_experiments") or {}
    status = experiment.get("status", "NOT_AVAILABLE")
    return {
        "report_version": VERSION,
        "report_date": report_day,
        "generated_at_local": now.isoformat(),
        "data_snapshot_hash": research.get("data_hash"),
        "time_zone": "Asia/Ho_Chi_Minh",
        "source": "READ_ONLY_VERIFIED_LOCAL_HISTORY_AND_COMPLETE_DAILY_FILES",
        "source_total_closed": len(rows),
        "closed_yesterday": len(day_trades),
        "missing_close_timezone_or_timestamp": missing_close_zone,
        "daily_by_side": day_sides,
        "daily_by_case": daily_by_case,
        "historical_case_results": research.get("per_case_win_loss") or {},
        "historical_model_holdout": historical_models,
        "loss_investigation": research.get("loss_investigation") or {},
        "cluster_research_summary": {
            "groups": clusters.get("group_count", 0),
            "historical_holdout_supported": clusters.get("holdout_supported_shadow_candidates", 0),
            "candidate_count": clusters.get("candidate_count", 0),
        },
        "historical_holdout_candidates": candidates,
        "existing_experiment": {"status": status,
                                "validation_selected": experiment.get("selected_by_validation"),
                                "prospective_shadow_proven": False},
        "forward_shadow_verification": {
            "status": "NOT_IMPLEMENTED_NO_VERIFIED_FORWARD_SHADOW_RESULTS",
            "verified_strategies": 0,
            "verified_shadow_trades": 0,
            "note": "No immutable point-in-time signal feed or independently replayed future OHLC exists."
        },
        "recommendation": ("Continue independent prospective Shadow infrastructure; "
                           "never auto-change Trading Bot from historical patterns."),
        "limitations": [
            "Historical observed trades and out-of-sample tests are not live Shadow evidence.",
            "The daily count uses closed_at in Vietnam timezone; missing timezone is excluded.",
            "A historical filter that avoids losing trades can also skip winning trades.",
            "Absence of new completed trades is not a successful forward validation.",
            "No real orders, Paper orders, Trading Bot configuration changes or GitHub upload.",
        ],
        "real_orders": 0, "paper_orders": 0, "trading_bot_modified": False,
    }


def _plain(report):
    date = report["report_date"]
    longs, shorts = report["daily_by_side"]["LONG"], report["daily_by_side"]["SHORT"]
    models = report["historical_model_holdout"]
    out = [
        "# Reverse Research — Báo cáo hằng ngày " + date,
        "",
        "**Dữ liệu đã đóng theo giờ Việt Nam. Chỉ dùng dữ liệu lưu cục bộ.**",
        "",
        "Ngày báo cáo: " + date + " | Tạo lúc: " + report["generated_at_local"],
        "Hash bộ dữ liệu: " + str(report.get("data_snapshot_hash") or "khong co"),
        "",
        "## 1. Giao dịch đã đóng (Paper, không phải Shadow)",
        f"- Hom qua: {report['closed_yesterday']} lệnh.",
        f"- LONG: {longs['closed']} lệnh / {longs['wins']} thắng / {longs['losses']} thua / mean R: {_fmt(longs['mean_R'])}",
        f"- SHORT: {shorts['closed']} lệnh / {shorts['wins']} thắng / {shorts['losses']} thua / mean R: {_fmt(shorts['mean_R'])}",
        f"- Toàn bộ dữ liệu lịch sử: {report['source_total_closed']} lệnh đã đóng.",
        f"- Thiếu múi giờ closed_at: {report['missing_close_timezone_or_timestamp']}.",
        "",
        "## 2. Giao dịch đã đóng theo Case và chiều",
    ]
    for case, stats in report["daily_by_case"].items():
        out.append(f"- {case}: {stats['closed']} lệnh, {stats['wins']} thắng, {stats['losses']} thua.")
    if not report["daily_by_case"]:
        out.append("- Không có lệnh đã đóng đủ điều kiện trong ngày.")
    out += [
        "",
        "## 3. Kiểm định lịch sử LONG và SHORT (KHÔNG phải Shadow)",
    ]
    for m in models:
        out.append(
            f"- {m['side']}: {m['status']}; test {m['test_count']}, "
            f"loc {m['selected_count']}; mean R loc {_fmt(m['selected_mean_R'])}; "
            f"baseline {_fmt(m['baseline_mean_R'])}."
        )
    c = report["cluster_research_summary"]
    out += [
        "",
        "## 4. Nhóm lệnh thua và giả thuyết",
        f"- Nhóm đã ghi nhận: {c['groups']}; đề xuất lịch sử: {c['candidate_count']}; "
        f"có bằng chứng từ holdout lịch sử: {c['historical_holdout_supported']}.",
    ]
    for item in report["historical_holdout_candidates"]:
        out.append(
            f"- {item['case']} {item['side']} / {item['id']}: {item['status']}; "
            f"test {item['holdout_cluster_trades']} lệnh, "
            f"mean R nhom {_fmt(item['holdout_cluster_mean_R'])} "
            f"vs nhom doi chung {_fmt(item['holdout_other_mean_R'])}; "
            f"co the bo lo {item['holdout_missed_winners_if_avoided']} lenh thang."
        )
    out += [
        "",
        "## 5. Thí nghiệm đang theo dõi",
        "- " + report["existing_experiment"]["status"] + " (chỉ là lịch sử hoặc Paper đã đóng).",
        "",
        "## 6. Shadow đã KIỂM CHỨNG trên tín hiệu tương lai",
        "**CHƯA CÓ KẾT QUẢ SHADOW ĐƯỢC XÁC MINH.**",
        "Không được biến kết quả kiểm định lịch sử thành thành tích Shadow.",
        "",
        "## 7. Kết luận / việc tiếp theo",
        "Chưa được thay đổi 6 Case; cần tín hiệu theo thời điểm thực và phát lại nến OHLC.",
        "Báo cáo vẫn được tạo ngay cả khi không có giao dịch mới.",
        "",
        "Lưu ý: " + " ".join(report["limitations"]),
        "",
    ]
    return "\n".join(out)


def _html(report):
    from html import escape as esc
    sides = report["daily_by_side"]
    cards = "".join(
        f'<div class="card"><small>{esc(side)}</small><strong>{val["closed"]} lenh</strong>'
        f'<span>{val["wins"]} thắng / {val["losses"]} thua</span>'
        f'<span>Mean R: {esc(_fmt(val["mean_R"]))}</span></div>'
        for side, val in sides.items()
    )
    models = "".join(
        "<tr><td>" + esc(str(m["side"])) + "</td><td>" + esc(str(m["status"]))
        + "</td><td>" + esc(str(m["test_count"])) + "</td><td>"
        + esc(str(m["selected_count"])) + "</td><td>"
        + esc(_fmt(m["selected_mean_R"])) + "</td><td>"
        + esc(_fmt(m["baseline_mean_R"])) + "</td></tr>"
        for m in report["historical_model_holdout"]
    )
    daily_cases = "".join(
        "<tr><td>" + esc(str(case)) + "</td><td>" + esc(str(val["closed"]))
        + "</td><td>" + esc(str(val["wins"])) + "</td><td>"
        + esc(str(val["losses"])) + "</td></tr>"
        for case, val in report["daily_by_case"].items()
    ) or '<tr><td colspan="4">Không có lệnh mới trong ngày.</td></tr>'
    groups = "".join(
        "<tr><td>" + esc(str(q["case"])) + " / " + esc(str(q["side"]))
        + "</td><td>" + esc(str(q["id"])) + "</td><td>" + esc(str(q["status"]))
        + "</td><td>" + esc(str(q["holdout_cluster_trades"])) + "</td><td>"
        + esc(_fmt(q["holdout_cluster_mean_R"])) + "</td><td>"
        + esc(_fmt(q["holdout_other_mean_R"])) + "</td><td>"
        + esc(str(q["holdout_missed_winners_if_avoided"])) + "</td></tr>"
        for q in report["historical_holdout_candidates"]
    )
    if not groups:
        groups = '<tr><td colspan="7">Chua co de xuat nhom dat dieu kien kiem dinh lịch sử.</td></tr>'
    c = report["cluster_research_summary"]
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reverse Research - {esc(report['report_date'])}</title>
<style>
body{{font:15px/1.6 Arial,sans-serif;background:#f5f7fb;color:#162638;max-width:1100px;margin:auto;padding:32px 20px}}
main{{background:white;border-radius:16px;padding:28px;box-shadow:0 8px 32px #152a4010}}
h1{{margin:0;color:#10263a}}h2{{margin:30px 0 10px;border-bottom:1px solid #e5eaf1;padding-bottom:8px}}
.muted{{color:#637287}}.cards{{display:flex;flex-wrap:wrap;gap:14px}}.card{{display:flex;flex-direction:column;gap:4px;
border:1px solid #e1e8f1;border-radius:12px;padding:15px;min-width:180px;flex:1}}
.card strong{{font-size:25px}}.card small{{font-weight:bold;color:#536780}}.note{{border-left:3px solid #64748b;padding:12px 14px;
background:#f2f5f9}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #e2e8f0;text-align:left;padding:9px;white-space:nowrap}}th{{background:#edf2f7}}
footer{{margin-top:26px;color:#657489;font-size:12px}}
@media(max-width:600px){{body{{padding:10px}}main{{padding:15px}}}}
</style></head><body><main>
<h1>REVERSE RESEARCH | BÁO CÁO NGÀY</h1>
<p class="muted">Ngày dữ liệu đã hoàn tất: <b>{esc(report['report_date'])}</b> | Tạo: {esc(report['generated_at_local'])}</p>
<div class="note"><b>Phan biet bang chung:</b> Dữ liệu lệnh đã đóng là kết quả quan sát.
Kiểm định holdout là thử nghiệm lịch sử. <b>Chưa có kết quả Shadow được xác minh.</b></div>
<h2>1. Giao dịch đã đóng trong ngày</h2>
<p>{report['closed_yesterday']} lệnh Paper đã đóng; lịch sử hiện có {report['source_total_closed']} lệnh.</p>
<div class="cards">{cards}</div>
<h3>Theo từng Case và chiều</h3><div class="scroll"><table><thead>
<tr><th>Case / chiều</th><th>Đã đóng</th><th>Thắng</th><th>Thua</th></tr></thead>
<tbody>{daily_cases}</tbody></table></div>
<h2>2. Kiểm định LONG / SHORT trên lịch sử (không phải Shadow)</h2>
<div class="scroll"><table><thead><tr><th>Chiều</th><th>Trạng thái</th><th>Test</th><th>Loc</th>
<th>Mean R da loc</th><th>Baseline mean R</th></tr></thead><tbody>{models}</tbody></table></div>
<h2>3. Nhóm thua và giả thuyết</h2>
<p>{c['groups']} nhóm, {c['candidate_count']} đề xuất; {c['historical_holdout_supported']} đề xuất có tín hiệu
từ kiểm định holdout <b>lịch sử</b>.</p>
<div class="scroll"><table><thead><tr><th>Case / chiều</th><th>Giả thuyết</th><th>Trạng thái</th>
<th>Test n</th><th>Mean R nhóm</th><th>Mean R đối chứng</th><th>Lệnh thắng có thể bỏ lỡ</th>
</tr></thead><tbody>{groups}</tbody></table></div>
<h2>4. Thử nghiệm hiện có</h2><p>{esc(report['existing_experiment']['status'])}</p>
<h2>5. Shadow đã được kiểm chứng</h2>
<div class="note"><b>Chưa có bằng chứng Shadow hợp lệ.</b> Bộ theo dõi tín hiệu tương lai và phát lại
OHLC theo thời gian chưa được triển khai. Không ghi nhận 0 lệnh là chiến thắng.</div>
<h2>6. Kết luận</h2><p>Chưa tự thay đổi 6 Case Paper. Tiếp tục thu thập tín hiệu và nghiên cứu giả thuyết.</p>
<footer>Data hash: {esc(str(report.get('data_snapshot_hash') or 'N/A'))} |
No remote upload | No order placed | No auto Trading Bot edit.</footer>
</main></body></html>"""


def write_daily_report(workspace: Path, rows: list[dict], research: dict,
                       *, now: datetime | None = None):
    from engine import save_json_atomic
    report = build_report(rows, research, now=now)
    day = report["report_date"]
    folder = Path(workspace) / "daily" / day
    destination = folder / "research-daily.json"
    digest = str(report.get("data_snapshot_hash") or "")
    if destination.is_file():
        try:
            old = json.loads(destination.read_text(encoding="utf-8"))
            if (old.get("data_snapshot_hash") == digest
                    and old.get("report_version") == VERSION
                    and (folder / "research-daily.html").is_file()
                    and (folder / "research-daily.md").is_file()):
                return {"status": "DAILY_REPORT_ALREADY_CURRENT",
                        "report_date": day, "html": str(folder / "research-daily.html")}
        except (OSError, ValueError):
            pass
    folder.mkdir(parents=True, exist_ok=True)
    # Write human-readable outputs before JSON manifest. A JSON manifest only
    # exists for a completed successfully written HTML+Markdown report.
    for name, text in (("research-daily.html", _html(report)),
                       ("research-daily.md", _plain(report))):
        target = folder / name
        temporary = target.with_name(name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
    save_json_atomic(destination, report)
    return {"status": "DAILY_REPORT_WRITTEN", "report_date": day,
            "html": str(folder / "research-daily.html"),
            "json": str(destination)}
