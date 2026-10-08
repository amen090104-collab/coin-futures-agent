import json

from app.analysis_daily import (
    generate_and_save_analysis, build_daily_analysis,
)


def report(day):
    return {
        "report_date": day, "report_type": "DAILY_INTELLIGENCE_V432",
        "created_at": day+"T15:00:00+00:00",
        "strategies": [
            {"strategy_id": "BASE_RR1", "name": "BASE 1R",
             "direction_mode": "BASE", "rr": 1.0, "trades": 2, "wins": 1,
             "net_pnl": -2.5, "profit_factor": 0.8, "expectancy_r": -0.15,
             "win_rate_pct": 50.0},
            {"strategy_id": "REVERSE_RR2", "name": "REVERSE 2R",
             "direction_mode": "REVERSE", "rr": 2.0, "trades": 3, "wins": 2,
             "net_pnl": 8.2, "profit_factor": 1.8, "expectancy_r": 0.2,
             "win_rate_pct": 66.7},
        ],
        "market": {"btc_regime": "BULLISH"},
        "coin_analysis": {"daily": [
            {"symbol": "BTCUSDT", "net_pnl": 4.1},
            {"symbol": "SOLUSDT", "net_pnl": -2.8},
        ]},
        "trade_attribution": {"counts": {"NEWS_ASSISTED_WIN": 1},
                              "pnl_by_class": {"NEWS_ASSISTED_WIN": 2.0}},
        "cumulative": {"score_buckets": [], "regimes": [], "factors": {}},
        "strategy_evaluation": {"strategies": []},
        "news_guardian": {"summary": {"events": 1}},
        "sample_ready": False,
    }


def write_report(base, day):
    path = base/day/"daily-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report(day)), encoding="utf-8")


def test_daily_analysis_persists_three_formats_and_idempotent_history(tmp_path):
    write_report(tmp_path, "2026-10-06")
    write_report(tmp_path, "2026-10-07")
    a = generate_and_save_analysis("2026-10-07", tmp_path)
    assert a["analysis_type"] == "DAILY_RESEARCH_V433"
    assert a["history_comparison"]["prior_reports_available"] == 1
    assert all(x["status"] == "INSUFFICIENT_DATA" for x in a["hypotheses"])
    assert "NEWS_ASSISTED_WIN" in a["trade_attribution"]["counts"]
    for name in ("daily-analysis.json", "daily-analysis.md", "daily-analysis.html"):
        assert (tmp_path/"2026-10-07"/name).exists()
    generate_and_save_analysis("2026-10-07", tmp_path)
    h = json.loads((tmp_path/"research-history.json").read_text(encoding="utf-8"))
    assert len(h["H01"]["observations"]) == 1
    assert "2026-10-07" in (tmp_path/"2026-10-07"/"daily-analysis.md").read_text(encoding="utf-8")
