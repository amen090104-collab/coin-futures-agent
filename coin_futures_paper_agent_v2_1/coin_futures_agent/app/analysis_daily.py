"""Evidence-labelled deterministic daily analysis (not an external LLM).

The source of truth is the saved daily-report.json. All hypotheses have
explicit minimum sample gates; the system never claims causal proof of
news or real-money readiness.
"""
from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings
from .report_sync import report_root

HYPOTHESES = {
    "H01": "BASE with high score >=85 may be late or overextended",
    "H02": "BTC BULLISH may favor REVERSE over BASE",
    "H03": "BTC NEUTRAL may favor BASE over REVERSE",
    "H04": "REVERSE RR2 may outperform REVERSE RR1",
}


def _f(value: Any) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _source(day: str, base: Path) -> dict[str, Any]:
    path = base / day / "daily-report.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; generate the official daily report first")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("report_date") != day:
        raise ValueError("Daily report date does not match requested analysis day")
    return result


def _prior_reports(base: Path, day: str, limit: int = 30) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(base.glob("????-??-??/daily-report.json"), reverse=True):
        if path.parent.name >= day:
            continue
        if len(items) >= limit:
            break
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("report_date") == path.parent.name:
                items.append(doc)
        except (ValueError, OSError):
            continue
    return items


def _segments(report: dict[str, Any], key: str, predicate: Any) -> dict[str, float]:
    rows = ((report.get("cumulative") or {}).get(key) or [])
    spec = {str(x.get("strategy_id")): x for x in report.get("strategies") or []}
    total_n = 0
    total_pnl = 0.0
    for row in rows:
        if not predicate(str(row.get("bucket") if key == "score_buckets" else row.get("regime"))):
            continue
        for sid, stats in (row.get("strategies") or {}).items():
            if not spec.get(sid):
                continue
            total_n += int(stats.get("trades") or 0)
            total_pnl += _f(stats.get("net_pnl"))
    return {"n": total_n, "pnl": round(total_pnl, 2),
            "pnl_per_trade": round(total_pnl / total_n, 3) if total_n else 0.0}


def _direction_group(
    report: dict[str, Any], group: str, condition: Any
) -> dict[str, float]:
    spec = {str(x.get("strategy_id")): x for x in report.get("strategies") or []}
    n, pnl = 0, 0.0
    for item in (report.get("cumulative") or {}).get("regimes") or []:
        if not condition(str(item.get("regime"))):
            continue
        for sid, cell in (item.get("strategies") or {}).items():
            if str(spec.get(sid, {}).get("direction_mode")) != group:
                continue
            n += int(cell.get("trades") or 0)
            pnl += _f(cell.get("net_pnl"))
    return {"n": n, "pnl": round(pnl, 2),
            "pnl_per_trade": round(pnl / n, 3) if n else 0.0}


def _assess(
    hypothesis_id: str,
    a: dict[str, float],
    b: dict[str, float],
    *,
    min_n: int = 30,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Exploratory comparison of paper dollars/trade; shared cohorts correlated."""
    diff = _f(a.get("pnl_per_trade")) - _f(b.get("pnl_per_trade"))
    enough = a["n"] >= min_n and b["n"] >= min_n
    status = (
        "INSUFFICIENT_DATA" if not enough
        else "SUPPORTED" if diff > threshold
        else "WEAKENED" if diff < -threshold
        else "MIXED"
    )
    return {
        "id": hypothesis_id, "hypothesis": HYPOTHESES[hypothesis_id],
        "status": status, "group_a": a, "group_b": b,
        "difference_usdt_per_trade": round(diff, 3),
        "min_n_each": min_n, "threshold_usdt_per_trade": threshold,
        "note": (
            "Exploratory, not out-of-sample validation. Case trades often share "
            "a cohort and are correlated; no independence or causality assumed."
        ),
    }


def _hypotheses(report: dict[str, Any]) -> list[dict[str, Any]]:
    spec = {str(x.get("strategy_id")): x for x in report.get("strategies") or []}

    def score_group(high: bool) -> dict[str, float]:
        total, pnl = 0, 0.0
        for row in (report.get("cumulative") or {}).get("score_buckets") or []:
            bucket = str(row.get("bucket"))
            is_high = bucket in {"85-89", "90+"}
            if is_high != high:
                continue
            for sid, cell in (row.get("strategies") or {}).items():
                if str(spec.get(sid, {}).get("direction_mode")) != "BASE":
                    continue
                total += int(cell.get("trades") or 0)
                pnl += _f(cell.get("net_pnl"))
        return {"n": total, "pnl": round(pnl, 2),
                "pnl_per_trade": round(pnl / total, 3) if total else 0.0}

    def reverse_rr(rr: float) -> dict[str, float]:
        rows = ((report.get("strategy_evaluation") or {}).get("strategies") or [])
        total, weighted_r, pnl_proxy = 0, 0.0, 0.0
        for row in rows:
            case = spec.get(str(row.get("strategy_id"))) or {}
            if str(case.get("direction_mode")) != "REVERSE" or abs(_f(case.get("rr")) - rr) > 0.01:
                continue
            n = int(row.get("closed_trades") or 0)
            total += n
            weighted_r += n * _f(row.get("expectancy_r"))
        return {"n": total, "pnl": None,
                "pnl_per_trade": round(weighted_r / total, 3) if total else 0.0,
                "unit": "R/trade"}

    out = [
        # H01 compares low vs high Base: expected low > high.
        _assess("H01", score_group(False), score_group(True)),
        _assess("H02", _direction_group(report, "REVERSE", lambda x: x == "BULLISH"),
                _direction_group(report, "BASE", lambda x: x == "BULLISH")),
        _assess("H03", _direction_group(report, "BASE", lambda x: x == "NEUTRAL"),
                _direction_group(report, "REVERSE", lambda x: x == "NEUTRAL")),
        _assess("H04", reverse_rr(2.0), reverse_rr(1.0), threshold=0.05),
    ]
    out[-1]["difference_r_per_trade"] = out[-1].pop("difference_usdt_per_trade")
    out[-1]["threshold_r_per_trade"] = out[-1].pop("threshold_usdt_per_trade")
    return out


def _daily_brief(report: dict[str, Any]) -> dict[str, Any]:
    cases = report.get("strategies") or []
    coin_rows = ((report.get("coin_analysis") or {}).get("daily") or [])
    total_trades = sum(int(x.get("trades") or 0) for x in cases)
    top = max(cases, key=lambda x: _f(x.get("net_pnl")), default=None)
    bottom = min(cases, key=lambda x: _f(x.get("net_pnl")), default=None)
    best_coin = max(coin_rows, key=lambda x: _f(x.get("net_pnl")), default=None)
    worst_coin = min(coin_rows, key=lambda x: _f(x.get("net_pnl")), default=None)
    return {
        "paper_case_trade_count": total_trades,
        "aggregate_case_pnl_diagnostic_only": round(
            sum(_f(x.get("net_pnl")) for x in cases), 2
        ),
        "best_case": {
            "id": top.get("strategy_id"), "name": top.get("name"),
            "pnl": top.get("net_pnl"), "expectancy_r": top.get("expectancy_r"),
            "closed": top.get("trades"),
        } if top else None,
        "worst_case": {
            "id": bottom.get("strategy_id"), "name": bottom.get("name"),
            "pnl": bottom.get("net_pnl"), "expectancy_r": bottom.get("expectancy_r"),
            "closed": bottom.get("trades"),
        } if bottom else None,
        "best_coin": {"symbol": best_coin.get("symbol"), "pnl": best_coin.get("net_pnl")}
        if best_coin else None,
        "worst_coin": {"symbol": worst_coin.get("symbol"), "pnl": worst_coin.get("net_pnl")}
        if worst_coin else None,
        "news_events": ((report.get("news_guardian") or {}).get("summary") or {}),
        "attribution": ((report.get("trade_attribution") or {}).get("counts") or {}),
        "btc_regime_at_report": ((report.get("market") or {}).get("btc_regime") or "UNKNOWN"),
    }


def _history_compare(report: dict[str, Any], prior: list[dict[str, Any]]) -> dict[str, Any]:
    current = {str(x.get("strategy_id")): x for x in report.get("strategies") or []}
    out: list[dict[str, Any]] = []
    for sid, now in current.items():
        old = []
        for doc in prior[:30]:
            x = next((z for z in doc.get("strategies") or [] if z.get("strategy_id") == sid), None)
            if x:
                old.append(x)
        def period(n: int) -> dict[str, Any]:
            xs = old[:n]
            return {
                "days_available": len(xs),
                "closed_trades": sum(int(x.get("trades") or 0) for x in xs),
                "net_pnl": round(sum(_f(x.get("net_pnl")) for x in xs), 2),
            }
        out.append({
            "strategy_id": sid, "name": now.get("name"),
            "today_pnl": round(_f(now.get("net_pnl")), 2),
            "prior_day_pnl": round(_f(old[0].get("net_pnl")), 2) if old else None,
            "previous_7_reports": period(7),
            "previous_30_reports": period(30),
        })
    return {"prior_reports_available": len(prior), "cases": out}


def build_daily_analysis(day: str, base_dir: Path | None = None) -> dict[str, Any]:
    base = base_dir or report_root()
    report = _source(day, base)
    previous = _prior_reports(base, day, 30)
    brief = _daily_brief(report)
    hypotheses = _hypotheses(report)
    ready = ((report.get("strategy_evaluation") or {}).get("strategies") or [])
    directions = ((report.get("cumulative") or {}).get("factors") or {})
    notes = list(report.get("research_findings") or [])
    if not brief["paper_case_trade_count"]:
        notes.append("Không có giao dịch đóng trong ngày; không suy luận chiến lược thắng.")
    if not report.get("sample_ready"):
        notes.append(
            "Số lệnh chưa đạt ngưỡng so sánh tối thiểu; kết luận chỉ mang tính giả thuyết."
        )
    if not previous:
        notes.append("Chưa có báo cáo ngày trước để so sánh xu hướng lịch sử.")
    if brief["attribution"].get("NEWS_ASSISTED_WIN") or brief["attribution"].get("NEWS_SHOCK_LOSS"):
        notes.append(
            "Có tin quan trọng trùng thời điểm giao dịch. Phân loại là tương quan theo timestamp, "
            "không khẳng định tin gây ra biến động hoặc thesis ban đầu đúng/sai."
        )
    return {
        "analysis_type": "DAILY_RESEARCH_V433",
        "report_date": day,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_report_type": report.get("report_type"),
        "source_report_created_at": report.get("created_at"),
        "overview": brief,
        "case_performance": [
            {k: row.get(k) for k in (
                "strategy_id","name","direction_mode","rr","trades","wins","losses",
                "win_rate_pct","net_pnl","profit_factor","expectancy_r",
                "avg_win_r","avg_loss_r","max_drawdown_usdt"
            )}
            for row in report.get("strategies") or []
        ],
        "factors": directions,
        "coin_performance": (report.get("coin_analysis") or {}).get("daily") or [],
        "trade_attribution": report.get("trade_attribution") or {},
        "news_guardian": report.get("news_guardian") or {},
        "history_comparison": _history_compare(report, previous),
        "hypotheses": hypotheses,
        "strategy_readiness": [
            {k: row.get(k) for k in (
                "strategy_id","name","version","status","closed_trades",
                "expectancy_r","profit_factor","win_rate","break_even_win_rate",
                "max_drawdown_pct","gates","exit_research"
            )}
            for row in ready
        ],
        "research_findings": notes,
        "recommendation": (
            "Continue paper research. Do not auto-change a case or use real funds based "
            "on one-day results. Promote only after locked out-of-sample tests."
        ),
        "limitations": [
            "Deterministic rules, not an external LLM or causal analysis.",
            "Daily PnL across independent A/B/C/D accounts is diagnostic, NOT one real portfolio.",
            "Shared cohorts make case outcomes correlated; sample sizes are not independent.",
            "News-assisted classification is heuristic; a news timestamp is not causal proof.",
            "BTC regime is the latest scan snapshot, not necessarily the day's dominant regime.",
            "No automatic real-money trading or LIVE READY approval.",
        ],
    }


def render_analysis_markdown(doc: dict[str, Any]) -> str:
    o = doc["overview"]
    lines = [
        f"# Daily Futures Research Review — {doc['report_date']}", "",
        "## Tổng quan", "",
        f"- Tổng lệnh đóng trên các case: **{o['paper_case_trade_count']}**",
        f"- Tổng PnL của các paper case (chỉ để đối chiếu, không phải một tài khoản): **{o['aggregate_case_pnl_diagnostic_only']:+.2f} USDT**",
        f"- BTC regime tại lúc tổng hợp: **{o['btc_regime_at_report']}**",
        f"- Case tốt nhất theo PnL ngày: **{(o['best_case'] or {}).get('name','N/A')}**",
        f"- Case yếu nhất theo PnL ngày: **{(o['worst_case'] or {}).get('name','N/A')}**",
        f"- Coin tốt/xấu: **{(o['best_coin'] or {}).get('symbol','N/A')} / {(o['worst_coin'] or {}).get('symbol','N/A')}**",
        "", "## Chiến lược và lợi thế", "",
        "| Case | Trades | WR | PnL | PF | Expectancy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for x in doc["case_performance"]:
        lines.append(
            f"| {x.get('name')} | {x.get('trades',0)} | {_f(x.get('win_rate_pct')):.1f}% "
            f"| {_f(x.get('net_pnl')):+.2f} | {_f(x.get('profit_factor')):.2f} "
            f"| {_f(x.get('expectancy_r')):+.3f}R |"
        )
    lines += ["", "## So sánh với các báo cáo trước", ""]
    h = doc["history_comparison"]
    lines.append(f"- Có **{h['prior_reports_available']}** báo cáo trước để đối chiếu.")
    for x in h["cases"]:
        lines.append(
            f"- {x['name']}: hôm nay {x['today_pnl']:+.2f}; "
            f"ngày trước {x['prior_day_pnl'] if x['prior_day_pnl'] is not None else 'N/A'}; "
            f"7 báo cáo trước {x['previous_7_reports']['net_pnl']:+.2f} USDT "
            f"({x['previous_7_reports']['days_available']} ngày có dữ liệu)."
        )
    lines += ["", "## Giả thuyết đang theo dõi (exploratory)", ""]
    for x in doc["hypotheses"]:
        difference = x.get("difference_r_per_trade", x.get("difference_usdt_per_trade"))
        unit = "R/trade" if "difference_r_per_trade" in x else "USDT/trade"
        lines.append(
            f"- **{x['id']} · {x['status']}**: {x['hypothesis']} | "
            f"N(A)={x['group_a']['n']}, N(B)={x['group_b']['n']}, "
            f"chênh lệch {difference:+.3f} {unit}."
        )
    lines += ["", "## Nguyên nhân thắng/thua và tin tức", ""]
    attrs = doc["trade_attribution"]
    for key, count in (attrs.get("counts") or {}).items():
        lines.append(
            f"- {key}: {count} trades; PnL {_f((attrs.get('pnl_by_class') or {}).get(key)):+.2f} USDT"
        )
    lines += ["", "## SL/TP và độ sẵn sàng nghiên cứu", ""]
    for x in doc["strategy_readiness"]:
        ex = x.get("exit_research") or {}
        lines.append(
            f"- {x.get('name')} v{x.get('version')}: {x.get('status')}, "
            f"N={x.get('closed_trades')}, EV={_f(x.get('expectancy_r')):+.3f}R, "
            f"PF={_f(x.get('profit_factor')):.2f}, DD={_f(x.get('max_drawdown_pct')):.2f}%; "
            f"winning MAE P90={_f(ex.get('winning_trade_mae_p90_r')):.2f}R; "
            f"losing MFE median={_f(ex.get('losing_trade_mfe_median_r')):.2f}R."
        )
    lines += ["", "## Nhận định và công việc nghiên cứu tiếp theo", ""]
    lines += [f"- {x}" for x in doc["research_findings"]]
    lines += ["", "## Giới hạn phân tích", ""]
    lines += [f"- {x}" for x in doc["limitations"]]
    return "\n".join(lines) + "\n"


def render_analysis_html(doc: dict[str, Any]) -> str:
    lines = render_analysis_markdown(doc).splitlines()
    output = []
    in_table = False
    for raw in lines:
        if raw.startswith("|"):
            if raw.replace("|","").strip().startswith("---"):
                continue
            if not in_table:
                output.append("<table>")
                in_table = True
            cells = [html.escape(s.strip().replace("**","")) for s in raw.strip("|").split("|")]
            tag = "th" if len(output) >= 1 and output[-1] == "<table>" else "td"
            output.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            output.append("</table>")
            in_table = False
        if not raw.strip():
            continue
        if raw.startswith("# "):
            output.append(f"<h1>{html.escape(raw[2:])}</h1>")
        elif raw.startswith("## "):
            output.append(f"<h2>{html.escape(raw[3:])}</h2>")
        elif raw.startswith("- "):
            output.append(f"<p class='item'>{html.escape(raw[2:]).replace('**','')}</p>")
        else:
            output.append(f"<p>{html.escape(raw).replace('**','')}</p>")
    if in_table:
        output.append("</table>")
    return (
        "<!doctype html><html lang='vi'><meta charset='utf-8'>"
        "<title>Daily Trading Review</title><style>"
        "body{font-family:Segoe UI,Arial,sans-serif;background:#eff3f8;color:#16233a;"
        "max-width:1200px;margin:30px auto;padding:20px}h1,h2{color:#12315b}"
        "table{border-collapse:collapse;width:100%;background:white}"
        "th,td{padding:9px;border:1px solid #d8e0ec;text-align:left}"
        "th{background:#dfe9f6}.item{background:white;padding:10px;border-left:3px solid #537aa7}"
        "</style><body>" + "\n".join(output) + "</body></html>"
    )


def _update_research_history(base: Path, day: str, hypotheses: list[dict[str, Any]]) -> Path:
    path = base / "research-history.json"
    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        history = {}
    for hypothesis in hypotheses:
        key = hypothesis["id"]
        row = history.setdefault(key, {"hypothesis": HYPOTHESES[key], "observations": []})
        row["observations"] = [
            x for x in row.get("observations", [])
            if x.get("report_date") != day
        ] + [{
            "report_date": day, "status": hypothesis["status"],
            "group_a_n": hypothesis["group_a"]["n"],
            "group_b_n": hypothesis["group_b"]["n"],
            "difference": hypothesis.get("difference_r_per_trade",
                                         hypothesis.get("difference_usdt_per_trade")),
        }]
        row["observations"].sort(key=lambda x: x["report_date"])
        row["observations"] = row["observations"][-180:]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def generate_and_save_analysis(day: str, base_dir: Path | None = None) -> dict[str, Any]:
    base = base_dir or report_root()
    doc = build_daily_analysis(day, base)
    dest = base / day
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "daily-analysis.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dest / "daily-analysis.md").write_text(
        render_analysis_markdown(doc), encoding="utf-8"
    )
    (dest / "daily-analysis.html").write_text(
        render_analysis_html(doc), encoding="utf-8"
    )
    _update_research_history(base, day, doc["hypotheses"])
    return doc


def render_telegram_analysis(doc: dict[str, Any]) -> str:
    o = doc["overview"]
    best = o.get("best_case") or {}
    worst = o.get("worst_case") or {}
    lines = [
        f"DAILY TRADING REVIEW {doc['report_date']}",
        f"Case trades: {o['paper_case_trade_count']}",
        f"Best case: {best.get('name','N/A')} {best.get('pnl',0):+.2f} USDT",
        f"Worst case: {worst.get('name','N/A')} {worst.get('pnl',0):+.2f} USDT",
        f"Best/Worst coin: {(o.get('best_coin') or {}).get('symbol','N/A')} / "
        f"{(o.get('worst_coin') or {}).get('symbol','N/A')}",
    ]
    lines += [f"{x['id']}: {x['status']}" for x in doc["hypotheses"]]
    lines.append("Research only, not live-trading advice. Full report in GitHub.")
    return "\n".join(lines)
