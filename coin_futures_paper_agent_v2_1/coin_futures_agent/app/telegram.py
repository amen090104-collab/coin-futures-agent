import httpx

from .config import settings


async def send_telegram(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text})
        r.raise_for_status()


def render_scan_alert(result: dict, opened: list[dict]) -> str:
    lines = [
        "FUTURES PAPER AGENT",
        f"BTC regime: {result['btc_regime']} | scanned: {result['symbols_scanned']}",
        "",
    ]
    if opened:
        lines.append("NEW PAPER TRADES")
        for x in opened:
            if x.get("status") == "PAUSED":
                lines.append("Trading paused: daily loss guard reached.")
                continue
            label = x.get("strategy_name") or x.get("strategy_id") or ""
            prefix = f"[{label}] " if label else ""
            lines.append(
                f"{prefix}{x['symbol']} {x['side']} | score {x['score']:.1f} | entry {x['entry_price']:.8g} | "
                f"SL {x['stop_loss']:.8g} | TP {x['take_profit']:.8g} | risk {x['risk_usdt']:.2f} USDT"
            )
    else:
        lines.append("No new paper trades this scan.")
    return "\n".join(lines)


def render_close_alert(events: list[dict]) -> str:
    lines = ["PAPER TRADE CLOSED"]
    for x in events:
        label = x.get("strategy_name") or x.get("strategy_id") or ""
        prefix = f"[{label}] " if label else ""
        lines.append(
            f"{prefix}{x['symbol']} {x['side']} | {x['exit_reason']} | PnL {x['net_pnl']:.2f} USDT | {x['r_multiple']:.2f}R"
        )
        if x.get("loss_analysis"):
            lines.append("Why it may have lost: " + " / ".join(x["loss_analysis"][:2]))
    return "\n".join(lines)


def render_daily_report(report: dict) -> str:
    if report.get("report_type") in {"STRATEGY_BATTLE", "DAILY_INTELLIGENCE_V42", "DAILY_INTELLIGENCE_V50"}:
        title = "DAILY STRATEGY INTELLIGENCE" if str(report.get("report_type","")).startswith("DAILY_INTELLIGENCE") else "DAILY STRATEGY BATTLE"
        lines = [f"{title} {report['report_date']}"]
        for s in report.get("strategies", []):
            expectancy = s.get("expectancy_r", s.get("avg_r", 0))
            lines.append(
                f"{s['name']}: {s['trades']} trades | WR {s['win_rate_pct']}% | "
                f"PnL {s['net_pnl']:.2f} | PF {s['profit_factor']} | Exp {expectancy:+.3f}R | "
                f"Balance {s['paper_balance']:.2f}"
            )
        news = (report.get("news_guardian") or {}).get("summary") or {}
        if news:
            lines.append(
                f"News: {news.get('events', 0)} events | locks {news.get('event_locks', 0)} | "
                f"correct/wrong {news.get('correct', 0)}/{news.get('wrong', 0)}"
            )
        lines.append(
            "Sample: " + ("READY" if report.get("sample_ready") else "NOT ENOUGH YET")
        )
        return "\n".join(lines)
    return (
        f"DAILY PAPER REPORT {report['report_date']}\n"
        f"Trades {report['trades']} | W/L {report['wins']}/{report['losses']} | WR {report['win_rate_pct']}%\n"
        f"Net PnL {report['net_pnl']:.2f} USDT | PF {report['profit_factor']} | Avg R {report['avg_r']}\n"
        f"Balance {report['paper_balance']:.2f} USDT"
    )


def render_news_guardian_alert(decision: dict, closed: list[dict] | None = None) -> str:
    closed = closed or []
    lines = [
        "NEWS GUARDIAN",
        f"Mode: {decision.get('mode', 'UNKNOWN')}",
        f"Impact: {decision.get('impact_score', 0)} | Direction: {decision.get('direction', 'UNCLEAR')} | Confidence: {decision.get('confidence', 0)}%",
        f"Scope: {decision.get('scope', 'MARKET')} | Cooldown until: {decision.get('cooldown_until', '-')}",
        str(decision.get("headline") or "High-impact market event"),
    ]
    if closed:
        lines.append(f"NEWS_RISK_EXIT: {len(closed)} paper position(s) closed.")
    elif decision.get("mode") in {"CAUTION", "DIRECTIONAL_WARNING"}:
        lines.append("New affected entries are paused during the cooldown window.")
    return "\n".join(lines)
