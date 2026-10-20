"""Read-only research on report exports and optional V2 datasets; no external calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .reverse_intelligence import VERSION, CORE, day, finite, metrics, walk_forward
from .reverse_intelligence_store import CONTROL_VARIANTS, initial_case, costs_for_engine, dataset
from .reverse_execution import advance_reverse, TERMINAL


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000) if parsed.tzinfo is not None else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def reason_codes(trade):
    thesis = trade.get("entry_thesis")
    if not isinstance(thesis, dict) or not isinstance(thesis.get("reason_codes"), list):
        return None
    codes = thesis["reason_codes"]
    return codes if all(isinstance(code, str) for code in codes) else None


def replay(cohort, bars, *, override_costs=None):
    """Forward OHLC replay with frozen features/costs; never alters stored outcomes."""
    costs = {**cohort["costs"], **(override_costs or {})}
    states = {a: initial_case(a, source_side=cohort["source_side"], score=cohort["features"]["source_score"],
                              signal_price=cohort["signal_price"], risk=cohort["risk_distance"],
                              observed=cohort["observed_at_ms"]) for a in CONTROL_VARIANTS}
    for candle in sorted(bars, key=lambda b: b["open_time"]):
        for action, state in states.items():
            if state["status"] in TERMINAL or candle["open_time"] < state["cursor_ms"]:
                continue
            try:
                states[action] = advance_reverse(state, candle, **costs_for_engine(costs))
            except (ValueError, TypeError, KeyError):
                states[action] = {**state, "status": "CENSORED", "net_r": None, "reason": "REPLAY_INVALID_OR_GAP"}
    return states


def analyze_reports(root):
    root = Path(root)
    paths = sorted(root.glob("????-??-??/daily-report.json"))
    if not paths:
        raise ValueError("Không tìm thấy daily-report.json; không tạo số liệu thay thế.")
    trades, sources, issues = {}, [], Counter()
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        sources.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if document.get("report_date") != path.parent.name:
            issues["report_date_mismatch"] += 1
            continue
        for strategy in document.get("strategies", []):
            sid = strategy["strategy_id"]
            for record in strategy.get("trade_details", []):
                key = (sid, record.get("trade_id"))
                if key[1] is None:
                    issues["missing_trade_id"] += 1
                    continue
                if (finite(record.get("r_multiple")) is None or record.get("side") not in {"LONG", "SHORT"}
                        or not (0 < timestamp(record.get("opened_at")) <= timestamp(record.get("closed_at")))):
                    issues["invalid_trade"] += 1
                    continue
                if key in trades:
                    issues["duplicate_trade_export"] += 1
                    if trades[key]["r_multiple"] != finite(record["r_multiple"]):
                        issues["conflicting_outcome"] += 1
                    continue
                trades[key] = {**record, "strategy_id": sid, "r_multiple": float(record["r_multiple"]),
                               "btc_regime": record.get("btc_regime") or "UNKNOWN",
                               "source_side": ("SHORT" if record["side"] == "LONG" else "LONG")
                               if strategy.get("direction_mode") == "REVERSE" else record["side"],
                               "first_export_at": document.get("created_at")}
    groups = defaultdict(list)
    for trade in sorted(trades.values(), key=lambda t: (timestamp(t["closed_at"]), str(t["trade_id"]))):
        groups[trade["strategy_id"]].append(trade)
    reverse = groups.get("REVERSE_RR2", [])
    missing = {key: sum(finite(t.get(key if key != "source_score" else "score")) is None for t in reverse)
               for key in (*CORE, "oi_change_pct", "funding_rate", "relative_strength_1h_pct")}
    days = sorted({day(timestamp(t["closed_at"])) for t in reverse})
    partitions = {"early_descriptive": days[:len(days)//3],
                  "middle_descriptive": days[len(days)//3:2*len(days)//3],
                  "recent_descriptive": days[2*len(days)//3:]}
    condition_groups = {}
    for side in ("LONG", "SHORT"):
        selected = [t for t in reverse if t["source_side"] == side]
        known = [t for t in selected if reason_codes(t) is not None]
        codes = sorted({code for t in known for code in reason_codes(t)})
        contrasts = []
        for code in codes:
            present = [t["r_multiple"] for t in known if code in reason_codes(t)]
            absent = [t["r_multiple"] for t in known if code not in reason_codes(t)]
            if len(present) >= 8 and len(absent) >= 8:
                contrasts.append({"code": code, "present": metrics(present), "absent": metrics(absent),
                                  "descriptive_difference_r": round(sum(present)/len(present)-sum(absent)/len(absent), 6)})
        condition_groups[side] = {"reverse_side": "SHORT" if side == "LONG" else "LONG",
            "overall": metrics([t["r_multiple"] for t in selected]),
            "unknown_reason_code_rows": len(selected) - len(known),
            "regimes": {regime: metrics([t["r_multiple"] for t in selected if t.get("btc_regime") == regime])
                        for regime in sorted({t.get("btc_regime", "UNKNOWN") for t in selected})},
            "time_splits": {name: metrics([t["r_multiple"] for t in selected if day(timestamp(t["closed_at"])) in dates])
                            for name, dates in partitions.items()},
            "reason_code_contrasts": sorted(contrasts, key=lambda c: abs(c["descriptive_difference_r"]), reverse=True),
            "exit_reasons": dict(Counter(t.get("exit_reason") for t in selected)),
            "stopped_after_1r_mfe": sum(t.get("exit_reason") == "STOP_LOSS" and (finite(t.get("mfe_r")) or 0) >= 1 for t in selected),
            "mfe_mae_present": sum(finite(t.get("mfe_r")) is not None and finite(t.get("mae_r")) is not None for t in selected)}
        condition_groups[side]["win_loss_features"] = {}
        for outcome in ("win", "loss"):
            subset = [t for t in selected if (t["r_multiple"] > 0 if outcome == "win" else t["r_multiple"] < 0)]
            condition_groups[side]["win_loss_features"][outcome] = {"n": len(subset)}
            for key in ("score", "mfe_r", "mae_r", "holding_minutes"):
                values = [finite(t.get(key)) for t in subset if finite(t.get(key)) is not None]
                condition_groups[side]["win_loss_features"][outcome][key] = {
                    "available": len(values), "mean": round(sum(values)/len(values), 6) if values else None}
        condition_groups[side]["score_buckets_descriptive"] = {
            label: metrics([t["r_multiple"] for t in selected if finite(t.get("score")) is not None and lower <= float(t["score"]) < upper])
            for label, lower, upper in (("75-79", 75, 80), ("80-84", 80, 85), ("85-89", 85, 90), ("90+", 90, 101))}
        condition_groups[side]["entry_hour_utc_descriptive"] = {
            str(hour): metrics([t["r_multiple"] for t in selected
                if datetime.fromtimestamp(timestamp(t["opened_at"])/1000, timezone.utc).hour == hour])
            for hour in range(24)}
    lab_paths = sorted(root.glob("????-??-??/reverse-lab.json"))
    latest = json.loads(lab_paths[-1].read_text(encoding="utf-8")) if lab_paths else {}
    if lab_paths:
        sources.append({"path": lab_paths[-1].relative_to(root).as_posix(),
                        "sha256": hashlib.sha256(lab_paths[-1].read_bytes()).hexdigest()})
    paper_latest = json.loads(paths[-1].read_text(encoding="utf-8"))
    comparison = []
    for name, stats in latest.get("variants", {}).items():
        comparison.append({"strategy": name, "population": "latest aggregate Shadow; not matched V2",
                           "closed": stats.get("closed"), "expectancy_r": stats.get("expectancy_r"),
                           "win_rate_pct": stats.get("win_rate_pct"), "profit_factor_r": stats.get("profit_factor"),
                           "serial_drawdown_r": None, "unavailable_reason": "Không có toàn bộ đường equity/cohort trong export tổng hợp."})
    historic = latest.get("historical_case_c", {})
    comparison.append({"strategy": "CASE_C", "population": "latest aggregate Paper; different fill times",
                       **historic.get("overall", {}), "serial_drawdown_r": historic.get("serial_trade_drawdown_r")})
    latest_counts = {s["strategy_id"]: s.get("cumulative_closed") for s in paper_latest.get("strategies", [])}
    return {"version": VERSION, "status": "DESCRIPTIVE_ONLY_NO_CAUSAL_CLAIM", "sources": sources,
            "report_days": [p.parent.name for p in paths], "issues": dict(issues),
            "exported_by_strategy": {sid: metrics([t["r_multiple"] for t in records]) for sid, records in groups.items()},
            "latest_cumulative_counts": latest_counts,
            "missing_details_vs_cumulative": {sid: latest_counts[sid] - len(records) for sid, records in groups.items()
                if isinstance(latest_counts.get(sid), int)},
            "missing_numeric_features_case_c": missing, "time_partitions": partitions,
            "conditions_by_source_side": condition_groups, "comparison": comparison,
            "latest_reverse_report_day": latest.get("report_day"),
            "latest_reverse_cohorts": latest.get("cohorts"),
            "training_eligible_from_reports": 0,
            "training_blockers": ["Thiếu full signal-time feature snapshot cho từng cohort.",
                "Không có label_available_at/first_seen cho kết quả Shadow.",
                "Recent cohorts là cửa sổ rút gọn, không phải dataset đầy đủ; không biến Paper thành fill Shadow.",
                "Thiếu đường nến và chi phí funding/order book để backtest khớp thật."],
            "limitations": ["Reason codes là điều kiện mô tả, không phải số RSI/OI chính xác hoặc nguyên nhân nhân quả.",
                "So sánh nhiều phân nhóm sau quan sát có selection bias; không lấy ngưỡng từ test rồi tuyên bố tối ưu.",
                "MFE/MAE theo OHLC không cho biết thứ tự intrabar; drawdown serial-R không phải equity portfolio."]}


def markdown(result):
    data, validation = result["historical"], result["walk_forward"]
    lines = ["# Reverse Entry Intelligence V2 — báo cáo nghiên cứu", "",
             f"Khoảng báo cáo: {data['report_days'][0]} → {data['report_days'][-1]}.",
             "Phân tích mô tả; không xác nhận nguyên nhân nhân quả hoặc lợi nhuận tương lai.",
             "## Dữ liệu và chất lượng", f"Số giao dịch xuất theo case: { {k:v['n'] for k,v in data['exported_by_strategy'].items()} }.",
             f"Chi tiết thiếu so với tích lũy: {data['missing_details_vs_cumulative']}.",
             f"Thiếu numeric features Case C: {data['missing_numeric_features_case_c']}.",
             "## Khi nào Reverse thắng/thua — liên hệ lịch sử, chưa phải quy tắc đã kiểm định"]
    for source, group in data["conditions_by_source_side"].items():
        lines += [f"### Base {source} → Reverse {group['reverse_side']}",
                  f"Export: {group['overall']['n']} lệnh, expectancy {group['overall']['expectancy_r']}R.",
                  f"Theo regime: {group['regimes']}", f"Ba phần thời gian: {group['time_splits']}"]
        lines.append(f"Điểm/MFE/MAE/thời gian giữ theo thắng-thua: {group['win_loss_features']}")
        lines.append(f"Thiếu reason codes: {group['unknown_reason_code_rows']} bản ghi; không gộp vào nhóm 'không có code'.")
        lines.append(f"Bucket điểm (mô tả, không tối ưu ngưỡng): {group['score_buckets_descriptive']}")
        for contrast in group["reason_code_contrasts"][:5]:
            lines.append(f"- {contrast['code']}: có code {contrast['present']['n']} lệnh/{contrast['present']['expectancy_r']}R; "
                         f"không code {contrast['absent']['n']} lệnh/{contrast['absent']['expectancy_r']}R.")
        lines.append(f"Lý do thoát: {group['exit_reasons']}; STOP sau MFE ≥1R: {group['stopped_after_1r_mfe']} (thứ tự intrabar chưa biết).")
    lines += ["## So sánh mô tả — tập mẫu và thời điểm fill khác nhau",
              "| Case/variant | Đóng | Mean net R | Win rate | PF R | Drawdown serial R |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in data["comparison"]:
        cells = [row['strategy'], row.get('closed'), row.get('expectancy_r'), row.get('win_rate_pct'),
                 row.get('profit_factor_r',row.get('profit_factor')), row.get('serial_drawdown_r')]
        lines.append("| " + " | ".join("Chưa có" if x is None else str(x) for x in cells) + " |")
    v2 = validation["executed"]
    cells = ["V2 walk-forward: chỉ entry có fill", v2["n"] if validation["scored_oos_n"] else None,
             v2["expectancy_r"], v2["win_rate_pct"], v2["profit_factor_r"], v2["serial_drawdown_r"]]
    lines.append("| " + " | ".join("Chưa có" if x is None else str(x) for x in cells) + " |")
    lines += ["## Score V2 và walk-forward", f"Trạng thái: **{validation['status']}**; số dự đoán: {len(validation['predictions'])}.",
              f"Policy: {validation['policy']}; controls: {validation['controls']}.",
              "Không có mẫu đủ chuẩn từ report export để huấn luyện V2. Logistic L2 và empirical neighbors đã có trong công cụ; chưa gán hiệu suất cho mô hình chưa huấn luyện.",
              "Ngưỡng được chọn bằng calibration theo thời gian; bằng chứng tối thiểu là gate nghiên cứu, không phải ngưỡng tối ưu.",
              "## Phần còn thiếu và bước tiếp theo", *[f"- {x}" for x in data["training_blockers"]],
              "- Thu thập dataset V2 opt-in: các tín hiệu Base, feature/timestamp, đối chứng NOW/WAIT/BASE, nến bất biến và thời điểm outcome được biết.",
              "- Chạy walk-forward trên export dataset mới; tách theo hướng Base/regime; báo cả avoided losses và missed winners.",
              "- Tăng stress phí/slippage bằng replay từ nến lưu; thu funding/spread trước mọi đánh giá khả thi tiền thật.",
              *[f"- {x}" for x in data["limitations"]],
              "Không tự bật paper/live, không thay A/B/C/D/REV-E, không deploy Render."]
    # Keep table rows contiguous while separating prose paragraphs.
    start = next(i for i, line in enumerate(lines) if line.startswith("| Case/variant"))
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    lines[start:end] = ["\n".join(lines[start:end])]
    return "\n\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Nghiên cứu Reverse V2 chỉ đọc; output phải ngoài dữ liệu nguồn.")
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dataset", type=Path)
    group.add_argument("--sqlite", type=Path)
    args = parser.parse_args()
    source, target = args.reports.resolve(), args.output_dir.resolve()
    if target == source or source in target.parents or target in source.parents:
        parser.error("Output phải độc lập với thư mục báo cáo nguồn.")
    rows = []
    if args.dataset:
        rows = json.loads(args.dataset.read_text(encoding="utf-8"))
    elif args.sqlite:
        with sqlite3.connect(args.sqlite.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            rows = dataset(db)
    result = {"historical": analyze_reports(source), "walk_forward": walk_forward(rows)}
    # Refuse to overwrite research artifacts from an earlier run accidentally.
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("analysis.json", "BAO_CAO.md"):
        if (target / filename).exists():
            parser.error("Output đã có báo cáo; chọn thư mục mới để giữ nguyên lịch sử.")
    (target / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (target / "BAO_CAO.md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"status": result["walk_forward"]["status"], "output": str(target),
                      "training_eligible_from_reports": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
