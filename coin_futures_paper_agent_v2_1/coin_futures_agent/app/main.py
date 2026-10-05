from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from .analytics import build_dashboard_analytics
from .config import settings
from .dashboard_v3 import DASHBOARD_HTML_V3
from .news import fetch_and_store_news, market_news_summary
from .paper import monitor_positions, open_candidates
from .reports import generate_and_save, render_markdown
from .scanner import run_scan
from .storage import (
    account_balance,
    ensure_initial_balance,
    get_daily_report,
    init_db,
    latest_daily_reports,
    latest_scan,
    list_recommendations,
    open_positions,
    recent_news,
    recent_trades,
    save_scan,
)
from .telegram import render_close_alert, render_daily_report, render_scan_alert, send_telegram

scheduler = AsyncIOScheduler(timezone=settings.timezone)
scan_lock = asyncio.Lock()
monitor_lock = asyncio.Lock()
news_lock = asyncio.Lock()

scan_state = {
    "running": False,
    "started_at": None,
    "completed_at": None,
    "duration_sec": None,
    "symbols_scanned": 0,
    "last_error": None,
}


async def scan_job() -> dict:
    if scan_lock.locked():
        return {"status": "scan already running", "scan_state": dict(scan_state)}
    async with scan_lock:
        started = datetime.now(timezone.utc)
        t0 = perf_counter()
        scan_state.update(
            running=True,
            started_at=started.isoformat(),
            last_error=None,
        )
        try:
            result, frames = await run_scan()
            save_scan(result["created_at"], result)
            opened = await open_candidates(result, frames)
            await send_telegram(render_scan_alert(result, opened))
            scan_state.update(
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbols_scanned=int(result.get("symbols_scanned") or 0),
            )
            return {"scan": result, "opened": opened}
        except Exception as exc:
            scan_state.update(
                completed_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(exc)[:500],
            )
            raise
        finally:
            scan_state["running"] = False
            scan_state["duration_sec"] = round(perf_counter() - t0, 2)


async def monitor_job() -> list[dict]:
    if monitor_lock.locked():
        return []
    async with monitor_lock:
        events = await monitor_positions()
        if events:
            await send_telegram(render_close_alert(events))
        return events


async def news_job() -> dict:
    if news_lock.locked():
        return {"status": "news refresh already running"}
    async with news_lock:
        scan = latest_scan() or {}
        universe = {
            str(x.get("symbol", ""))[:-4]
            for x in scan.get("all", [])
            if str(x.get("symbol", "")).endswith("USDT")
        }
        return await fetch_and_store_news(universe or None)


async def daily_report_job() -> dict:
    tz = ZoneInfo(settings.timezone)
    day = datetime.now(tz).strftime("%Y-%m-%d")
    report = generate_and_save(day)
    await send_telegram(render_daily_report(report))
    return report


async def _bootstrap() -> None:
    # Load news first so the first paper entries can record news context.
    try:
        await news_job()
    except Exception:
        pass
    try:
        await scan_job()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_initial_balance(datetime.utcnow().isoformat() + "Z", settings.paper_start_balance)
    scheduler.add_job(scan_job, "interval", minutes=settings.scan_interval_min, id="market_scan", replace_existing=True)
    scheduler.add_job(monitor_job, "interval", seconds=settings.monitor_interval_sec, id="paper_monitor", replace_existing=True)
    scheduler.add_job(news_job, "interval", minutes=settings.news_refresh_min, id="news_research", replace_existing=True)
    scheduler.add_job(
        daily_report_job,
        "cron",
        hour=settings.daily_report_hour,
        minute=settings.daily_report_minute,
        id="daily_report",
        replace_existing=True,
    )
    scheduler.start()
    asyncio.create_task(_bootstrap())
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Coin Futures Paper Agent", version="3.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": "3.1.0",
        "paper_balance": account_balance(),
        "open_positions": len(open_positions()),
        "top_n_coins": settings.top_n_coins,
        "news_refresh_min": settings.news_refresh_min,
    }


@app.post("/scan/run")
async def manual_scan():
    return await scan_job()


@app.post("/paper/monitor")
async def manual_monitor():
    return await monitor_job()


@app.post("/news/run")
async def manual_news():
    return await news_job()


@app.get("/scan/latest")
async def get_latest():
    data = latest_scan()
    if not data:
        raise HTTPException(404, "No scan result yet")
    return data


@app.get("/positions")
async def positions():
    return open_positions()


@app.get("/trades")
async def trades(limit: int = 100):
    return recent_trades(min(max(limit, 1), 500))


@app.get("/news")
async def news(
    limit: int = Query(60, ge=1, le=300),
    hours: int = Query(48, ge=1, le=720),
    symbol: str | None = None,
):
    symbol = symbol.upper().replace("USDT", "") if symbol else None
    return recent_news(limit=limit, hours=hours, symbol=symbol)


@app.get("/news/summary")
async def news_summary(hours: int = Query(24, ge=1, le=168)):
    return market_news_summary(hours)


@app.post("/reports/daily/{day}")
async def make_daily(day: str):
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Use YYYY-MM-DD")
    return generate_and_save(day)


@app.get("/reports/daily/{day}")
async def daily(day: str):
    data = get_daily_report(day)
    if not data:
        data = generate_and_save(day)
    return data


@app.get("/reports/daily/{day}/markdown", response_class=PlainTextResponse)
async def daily_markdown(day: str):
    data = get_daily_report(day) or generate_and_save(day)
    return render_markdown(data)


@app.get("/recommendations")
async def recommendations():
    return list_recommendations()


@app.get("/analytics")
async def analytics():
    trades_all = recent_trades(500)
    positions_all = open_positions()
    balance = account_balance()
    return build_dashboard_analytics(
        trades_all,
        positions_all,
        balance,
        settings.timezone,
        settings.taker_fee_bps,
    )


@app.get("/api/dashboard")
async def dashboard_data():
    trades_all = recent_trades(500)
    positions_all = open_positions()
    balance = account_balance()
    analytics_data = build_dashboard_analytics(
        trades_all,
        positions_all,
        balance,
        settings.timezone,
        settings.taker_fee_bps,
    )
    return {
        "version": "3.1.0",
        "balance": analytics_data["balance"],
        "equity": analytics_data["equity"],
        "unrealized_pnl": analytics_data["unrealized_pnl"],
        "open_positions": analytics_data["open_positions"],
        "trades": trades_all[-100:],
        "trade_stats": {
            "closed": analytics_data["closed"],
            "wins": analytics_data["wins"],
            "losses": analytics_data["losses"],
            "win_rate": analytics_data["win_rate"],
            "net_pnl": analytics_data["realized_pnl"],
            "profit_factor": analytics_data["profit_factor"],
            "avg_r": analytics_data["avg_r"],
            "max_drawdown_pct": analytics_data["max_drawdown_pct"],
        },
        "analytics": analytics_data,
        "scan_state": dict(scan_state),
        "scan": latest_scan(),
        "news_summary": market_news_summary(24),
        "news": recent_news(limit=50, hours=settings.news_lookback_hours),
        "reports": latest_daily_reports(14),
        "recommendations": list_recommendations(12),
        "settings": {
            "top_n_coins": settings.top_n_coins,
            "scan_interval_min": settings.scan_interval_min,
            "monitor_interval_sec": settings.monitor_interval_sec,
            "news_refresh_min": settings.news_refresh_min,
            "score_threshold": settings.score_threshold,
            "data_collection_mode": settings.data_collection_mode,
            "collection_max_open_trades": settings.collection_max_open_trades,
            "collection_risk_per_trade_pct": settings.collection_risk_per_trade_pct,
            "max_open_trades": settings.max_open_trades,
            "risk_per_trade_pct": settings.risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "reward_risk": settings.reward_risk,
            "paper_leverage": settings.paper_leverage,
            "taker_fee_bps": settings.taker_fee_bps,
            "slippage_bps": settings.slippage_bps,
        },
    }


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coin Futures Agent v2.1</title>
<style>
:root{--bg:#0b1020;--panel:#121a2d;--panel2:#182238;--line:#26334d;--text:#edf2ff;--muted:#94a3bd;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6;--cyan:#22d3ee;--shadow:0 12px 32px rgba(0,0,0,.25)}
*{box-sizing:border-box} body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:linear-gradient(180deg,#08101f,#0d1425 420px,#0b1020);color:var(--text)}
a{color:#8ec5ff;text-decoration:none} a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:10;background:rgba(8,14,28,.94);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.topin{max-width:1500px;margin:auto;padding:14px 20px;display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.brand{font-size:20px;font-weight:800}.brand small{font-size:12px;color:var(--muted);font-weight:500;margin-left:8px}
.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:9px 13px;border-radius:9px;cursor:pointer;font-weight:650}.btn:hover{border-color:#4b638c}.btn.primary{background:#1755c8;border-color:#2368e8}.btn:disabled{opacity:.55;cursor:wait}
.wrap{max-width:1500px;margin:20px auto;padding:0 20px 60px}.statusline{color:var(--muted);font-size:13px;margin:0 0 14px}
.cards{display:grid;grid-template-columns:repeat(6,minmax(150px,1fr));gap:12px}.card{background:linear-gradient(180deg,var(--panel),#101827);border:1px solid var(--line);border-radius:14px;padding:15px;box-shadow:var(--shadow)}.card .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}.card .v{font-size:24px;font-weight:800;margin-top:6px}.card .sub{font-size:12px;color:var(--muted);margin-top:5px}
.tabs{display:flex;gap:8px;margin:18px 0 14px;overflow:auto;padding-bottom:3px}.tab{white-space:nowrap;border:1px solid var(--line);background:#11192a;color:#aebbd0;padding:10px 14px;border-radius:10px;cursor:pointer;font-weight:700}.tab.active{background:#1b4ea2;color:white;border-color:#3b82f6}
.section{display:none}.section.active{display:block}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px;box-shadow:var(--shadow);overflow:hidden}.panel h3{margin:0 0 12px;font-size:16px}.panelhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.tablewrap{overflow:auto;max-height:600px}table{width:100%;border-collapse:collapse;min-width:780px}th,td{padding:10px 8px;border-bottom:1px solid #22304a;text-align:left;font-size:13px;vertical-align:top}th{position:sticky;top:0;background:#151f33;color:#aab8cc;z-index:1}tr:hover td{background:#142039}
.badge{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px;font-weight:800}.bull{color:#68e38e;background:rgba(34,197,94,.09);border-color:rgba(34,197,94,.35)}.bear{color:#ff7b7b;background:rgba(239,68,68,.09);border-color:rgba(239,68,68,.35)}.mix{color:#ffd274;background:rgba(245,158,11,.09);border-color:rgba(245,158,11,.35)}.blue{color:#83b7ff;background:rgba(59,130,246,.10);border-color:rgba(59,130,246,.35)}
.score{font-weight:900}.score.good{color:#55df86}.score.bad{color:#ff7979}.pnlp{color:#55df86;font-weight:800}.pnln{color:#ff7979;font-weight:800}.muted{color:var(--muted)}.small{font-size:12px}.reason{max-width:460px;line-height:1.45}.empty{padding:24px;text-align:center;color:var(--muted)}
.newsitem{padding:13px 0;border-bottom:1px solid #22304a}.newsitem:last-child{border-bottom:0}.newstitle{font-weight:750;line-height:1.4;margin:7px 0}.newsmeta{display:flex;gap:7px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--muted)}.newsdesc{font-size:12px;color:#b6c2d5;line-height:1.45;margin-top:6px}.impact{height:5px;background:#25324b;border-radius:4px;overflow:hidden;margin-top:8px}.impact i{display:block;height:100%;background:linear-gradient(90deg,#22c55e,#f59e0b,#ef4444)}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.input,.select{background:#0f1728;border:1px solid var(--line);color:var(--text);padding:8px 10px;border-radius:8px;outline:none}.input{min-width:210px}.toast{position:fixed;right:20px;bottom:20px;background:#111c31;border:1px solid #3c4e6f;border-radius:12px;padding:12px 15px;box-shadow:var(--shadow);display:none;max-width:420px;z-index:20}.toast.show{display:block}
details summary{cursor:pointer;color:#b9c7db}.linkbtn{font-size:12px;border:1px solid var(--line);padding:5px 8px;border-radius:7px;background:#11192a;color:#c8d5e8;cursor:pointer}.footer{color:var(--muted);font-size:12px;margin-top:20px}
@media(max-width:1100px){.cards{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}}
@media(max-width:650px){.wrap,.topin{padding-left:10px;padding-right:10px}.cards{grid-template-columns:repeat(2,1fr)}.card .v{font-size:20px}.brand{font-size:17px}}
</style>
</head>
<body>
<div class="top"><div class="topin"><div class="brand">Coin Futures Paper Agent <small>v2.1 • 50 coin + News Research</small></div><div class="actions"><button class="btn primary" onclick="action('/scan/run','Đang quét 50 coin...')">Quét ngay</button><button class="btn" onclick="action('/news/run','Đang cập nhật tin tức...')">Cập nhật tin</button><button class="btn" onclick="action('/paper/monitor','Đang kiểm tra SL/TP...')">Kiểm tra lệnh</button><button class="btn" onclick="loadAll()">Làm mới</button></div></div></div>
<div class="wrap">
<p class="statusline" id="status">Đang tải dữ liệu...</p>
<div class="cards" id="cards"></div>
<div class="tabs">
<button class="tab active" data-tab="overview">Tổng quan</button>
<button class="tab" data-tab="scanner">Scanner 50 coin</button>
<button class="tab" data-tab="positions">Lệnh đang chạy</button>
<button class="tab" data-tab="history">Lịch sử giao dịch</button>
<button class="tab" data-tab="news">Tin tức thị trường</button>
<button class="tab" data-tab="reports">Báo cáo & Khắc phục</button>
</div>
<section id="overview" class="section active"><div class="grid2"><div class="panel"><div class="panelhead"><h3>Top LONG</h3><span class="muted small" id="scanTime"></span></div><div id="topLong"></div></div><div class="panel"><h3>Top SHORT</h3><div id="topShort"></div></div></div><div class="grid2" style="margin-top:14px"><div class="panel"><h3>Tin high-impact gần nhất</h3><div id="hotNews"></div></div><div class="panel"><h3>Lệnh đang mở</h3><div id="openMini"></div></div></div></section>
<section id="scanner" class="section"><div class="panel"><div class="panelhead"><div><h3>Scanner 50 coin</h3><div class="muted small">Xếp theo điểm mạnh nhất. Score ≥ ngưỡng mới có thể tạo paper trade.</div></div><div class="controls"><input class="input" id="coinSearch" placeholder="Tìm BTC, SOL, XRP..." oninput="renderScanner()"><select class="select" id="biasFilter" onchange="renderScanner()"><option value="ALL">Tất cả</option><option value="LONG">LONG</option><option value="SHORT">SHORT</option><option value="WAIT">WAIT</option></select></div></div><div class="tablewrap" id="scannerTable"></div></div></section>
<section id="positions" class="section"><div class="panel"><h3>Lệnh paper đang chạy</h3><div class="tablewrap" id="positionsTable"></div></div></section>
<section id="history" class="section"><div class="panel"><h3>Lịch sử giao dịch</h3><div class="tablewrap" id="historyTable"></div></div></section>
<section id="news" class="section"><div class="grid2"><div class="panel"><h3>Đánh giá tin tức 24 giờ</h3><div id="newsSummary"></div><p class="muted small">Tin tức hiện được dùng làm bối cảnh nghiên cứu và ghi vào lý do entry; v2.1 chưa tự thay đổi score vì tin để tránh overfit.</p></div><div class="panel"><h3>Bộ lọc tin</h3><div class="controls"><select class="select" id="sentFilter" onchange="renderNews()"><option value="ALL">Mọi xu hướng</option><option value="BULLISH">Bullish</option><option value="BEARISH">Bearish</option><option value="NEUTRAL">Neutral</option></select><select class="select" id="impactFilter" onchange="renderNews()"><option value="ALL">Mọi mức ảnh hưởng</option><option value="75">High impact ≥75</option><option value="60">Impact ≥60</option></select><input class="input" id="newsSearch" placeholder="Tìm BTC, ETF, SEC..." oninput="renderNews()"></div></div></div><div class="panel" style="margin-top:14px"><h3>Dòng tin thị trường</h3><div id="newsList"></div></div></section>
<section id="reports" class="section"><div class="grid2"><div class="panel"><h3>Báo cáo theo ngày</h3><div id="reportsList"></div></div><div class="panel"><h3>Đề xuất khắc phục chiến lược</h3><div id="recommendations"></div></div></div></section>
<div class="footer">Paper trading only. Tin tức được phân loại tự động từ headline/summary và có thể sai sắc thái; luôn mở bài gốc khi tin có ảnh hưởng lớn.</div>
</div>
<div class="toast" id="toast"></div>
<script>
let D=null;
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(1)+'%';
const price=n=>{n=Number(n||0);if(n>=1000)return n.toFixed(2);if(n>=1)return n.toFixed(4);if(n>=.01)return n.toFixed(6);return n.toPrecision(5)};
const dt=x=>{try{return new Date(x).toLocaleString('vi-VN',{hour12:false})}catch(e){return x||'-'}};
const badge=(t,kind)=>`<span class="badge ${kind}">${esc(t)}</span>`;
function scoreClass(n){return Number(n)>=80?'good':Number(n)>=70?'':'bad'}
function regimeKind(x){return x==='BULLISH'?'bull':x==='BEARISH'?'bear':'mix'}
function toast(msg){let e=document.getElementById('toast');e.textContent=msg;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3500)}
async function action(url,msg){toast(msg);document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=true);try{let r=await fetch(url,{method:'POST'});let j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);toast('Hoàn tất');await loadAll()}catch(e){toast('Lỗi: '+e.message)}finally{document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=false)}}
async function loadAll(){try{let r=await fetch('/api/dashboard');D=await r.json();renderAll();document.getElementById('status').textContent=`Agent online • Quét ${D.settings.scan_interval_min} phút/lần • Tin ${D.settings.news_refresh_min} phút/lần • Monitor ${D.settings.monitor_interval_sec} giây/lần • ${new Date().toLocaleString('vi-VN')}`;}catch(e){document.getElementById('status').textContent='Không tải được dữ liệu: '+e.message}}
function renderAll(){renderCards();renderOverview();renderScanner();renderPositions();renderHistory();renderNews();renderReports()}
function renderCards(){let s=D.trade_stats||{},scan=D.scan||{},ns=D.news_summary||{};let cards=[['Paper balance',money(D.balance)+' USDT','Tài khoản giả lập'],['Lệnh đang mở',D.open_positions.length,`Tối đa ${D.settings.max_open_trades} lệnh`],['Win rate',pct(s.win_rate),`${s.wins||0} thắng / ${s.losses||0} thua`],['Net PnL',(s.net_pnl>=0?'+':'')+money(s.net_pnl)+' USDT',`${s.closed||0} lệnh đã đóng`],['BTC regime',scan.btc_regime||'CHƯA CÓ',`Scan ${scan.symbols_scanned||0}/${D.settings.top_n_coins} coin`],['News 24h',ns.market_bias||'NO DATA',`${ns.risk_level||'-'} risk • ${ns.high_impact||0} high-impact`]];document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="k">${esc(c[0])}</div><div class="v">${esc(c[1])}</div><div class="sub">${esc(c[2])}</div></div>`).join('')}
function topTable(xs,side){if(!xs?.length)return '<div class="empty">Chưa có coin đạt ngưỡng.</div>';return `<table><tr><th>Coin</th><th>Score</th><th>Giá</th><th>OI</th><th>Vol</th><th>Lý do</th></tr>${xs.slice(0,8).map(x=>{let sc=side==='LONG'?x.long_score:x.short_score;let rs=side==='LONG'?x.reasons_long:x.reasons_short;return `<tr><td><b>${esc(x.symbol)}</b></td><td class="score ${scoreClass(sc)}">${sc}</td><td>${price(x.price)}</td><td>${Number(x.oi_change_pct||0).toFixed(2)}%</td><td>${Number(x.volume_ratio_1h||0).toFixed(2)}x</td><td class="reason">${esc((rs||[]).slice(0,3).join('; '))}</td></tr>`}).join('')}</table>`}
function renderOverview(){let scan=D.scan||{};document.getElementById('topLong').innerHTML=topTable(scan.top_long,'LONG');document.getElementById('topShort').innerHTML=topTable(scan.top_short,'SHORT');document.getElementById('scanTime').textContent=scan.created_at?'Scan: '+dt(scan.created_at):'Chưa scan';let hot=(D.news||[]).filter(n=>Number(n.impact_score)>=75).slice(0,6);document.getElementById('hotNews').innerHTML=hot.length?hot.map(newsItem).join(''):'<div class="empty">Chưa có tin high-impact.</div>';let p=D.open_positions||[];document.getElementById('openMini').innerHTML=p.length?`<table><tr><th>Coin</th><th>Side</th><th>Entry</th><th>SL</th><th>TP</th></tr>${p.slice(0,7).map(x=>`<tr><td>${esc(x.symbol)}</td><td>${badge(x.side,x.side==='LONG'?'bull':'bear')}</td><td>${price(x.entry_price)}</td><td>${price(x.stop_loss)}</td><td>${price(x.take_profit)}</td></tr>`).join('')}</table>`:'<div class="empty">Chưa có lệnh mở.</div>'}
function renderScanner(){if(!D)return;let q=(document.getElementById('coinSearch')?.value||'').toUpperCase(),f=document.getElementById('biasFilter')?.value||'ALL';let xs=(D.scan?.all||[]).filter(x=>(!q||x.symbol.includes(q))&&(f==='ALL'||x.bias===f));let html=`<table><tr><th>#</th><th>Coin</th><th>Bias</th><th>LONG</th><th>SHORT</th><th>RSI 1h</th><th>Volume</th><th>OI</th><th>Funding</th><th>ATR 1h</th><th>Lý do mạnh nhất</th></tr>`+xs.map((x,i)=>{let side=x.bias,rs=side==='LONG'?x.reasons_long:side==='SHORT'?x.reasons_short:[];return `<tr><td>${i+1}</td><td><b>${esc(x.symbol)}</b><div class="muted small">${price(x.price)}</div></td><td>${badge(side,side==='LONG'?'bull':side==='SHORT'?'bear':'mix')}</td><td class="score ${scoreClass(x.long_score)}">${x.long_score}</td><td class="score ${scoreClass(x.short_score)}">${x.short_score}</td><td>${x.rsi_1h}</td><td>${x.volume_ratio_1h}x</td><td>${Number(x.oi_change_pct||0).toFixed(2)}%</td><td>${(Number(x.funding_rate||0)*100).toFixed(4)}%</td><td>${x.atr_pct_1h}%</td><td class="reason">${esc((rs||[]).slice(0,4).join('; '))}</td></tr>`}).join('')+'</table>';document.getElementById('scannerTable').innerHTML=xs.length?html:'<div class="empty">Không có kết quả phù hợp bộ lọc.</div>'}
function renderPositions(){let xs=D.open_positions||[];if(!xs.length){document.getElementById('positionsTable').innerHTML='<div class="empty">Chưa có lệnh paper đang chạy.</div>';return}document.getElementById('positionsTable').innerHTML=`<table><tr><th>Coin</th><th>Side</th><th>Score</th><th>Entry</th><th>SL</th><th>TP</th><th>Risk</th><th>Mở lúc</th><th>Lý do vào</th></tr>${xs.map(x=>`<tr><td><b>${esc(x.symbol)}</b></td><td>${badge(x.side,x.side==='LONG'?'bull':'bear')}</td><td>${x.score}</td><td>${price(x.entry_price)}</td><td>${price(x.stop_loss)}</td><td>${price(x.take_profit)}</td><td>${money(x.risk_usdt)} USDT</td><td>${dt(x.opened_at)}</td><td class="reason">${esc(x.reason_text)}</td></tr>`).join('')}</table>`}
function renderHistory(){let xs=[...(D.trades||[])].reverse();if(!xs.length){document.getElementById('historyTable').innerHTML='<div class="empty">Chưa có lệnh đóng.</div>';return}document.getElementById('historyTable').innerHTML=`<table><tr><th>ID</th><th>Coin</th><th>Side</th><th>Kết quả</th><th>PnL</th><th>R</th><th>Giữ lệnh</th><th>Lý do vào</th><th>Postmortem</th></tr>${xs.map(x=>{let good=Number(x.net_pnl)>0;let loss='';try{let a=JSON.parse(x.loss_analysis||'[]');loss=a.slice(0,3).join('; ')}catch(e){}return `<tr><td>#${x.id}</td><td><b>${esc(x.symbol)}</b></td><td>${badge(x.side,x.side==='LONG'?'bull':'bear')}</td><td>${esc(x.exit_reason)}</td><td class="${good?'pnlp':'pnln'}">${good?'+':''}${money(x.net_pnl)}</td><td>${Number(x.r_multiple).toFixed(2)}R</td><td>${Number(x.holding_minutes).toFixed(0)}m</td><td class="reason">${esc(x.reason_text)}</td><td class="reason">${esc(loss)}</td></tr>`}).join('')}</table>`}
function newsItem(n){let kind=n.sentiment==='BULLISH'?'bull':n.sentiment==='BEARISH'?'bear':'mix',sy=(n.symbols||[]).map(s=>badge(s,'blue')).join(' ');return `<div class="newsitem"><div class="newsmeta">${badge(n.sentiment,kind)} ${badge('Impact '+Number(n.impact_score).toFixed(0),Number(n.impact_score)>=75?'bear':'blue')} ${badge(n.category,'blue')} <span>${esc(n.source)}</span><span>•</span><span>${dt(n.published_at)}</span>${sy}</div><div class="newstitle"><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></div>${n.summary?`<div class="newsdesc">${esc(n.summary.slice(0,280))}${n.summary.length>280?'…':''}</div>`:''}<div class="impact"><i style="width:${Math.min(100,Number(n.impact_score||0))}%"></i></div></div>`}
function renderNews(){if(!D)return;let ns=D.news_summary||{};document.getElementById('newsSummary').innerHTML=`<div class="cards" style="grid-template-columns:repeat(3,1fr)"><div class="card"><div class="k">Market bias</div><div class="v">${badge(ns.market_bias||'NO DATA',regimeKind(ns.market_bias))}</div><div class="sub">Score ${Number(ns.market_score||0).toFixed(1)}</div></div><div class="card"><div class="k">News risk</div><div class="v">${esc(ns.risk_level||'-')}</div><div class="sub">${ns.high_impact||0} tin high-impact</div></div><div class="card"><div class="k">24h</div><div class="v">${ns.articles||0}</div><div class="sub">${ns.bullish||0} bull • ${ns.bearish||0} bear</div></div></div>`;let sf=document.getElementById('sentFilter')?.value||'ALL',imp=Number(document.getElementById('impactFilter')?.value||0),q=(document.getElementById('newsSearch')?.value||'').toLowerCase();let xs=(D.news||[]).filter(n=>(sf==='ALL'||n.sentiment===sf)&&(!imp||Number(n.impact_score)>=imp)&&(!q||(`${n.title} ${n.summary} ${(n.symbols||[]).join(' ')}`).toLowerCase().includes(q)));document.getElementById('newsList').innerHTML=xs.length?xs.map(newsItem).join(''):'<div class="empty">Không có tin phù hợp.</div>'}
function renderReports(){let rs=D.reports||[];document.getElementById('reportsList').innerHTML=rs.length?`<table><tr><th>Ngày</th><th>Lệnh</th><th>WR</th><th>PnL</th><th>PF</th><th>Avg R</th></tr>${rs.map(r=>`<tr><td><a target="_blank" href="/reports/daily/${r.report_date}/markdown">${esc(r.report_date)}</a></td><td>${r.trades}</td><td>${r.win_rate_pct}%</td><td class="${Number(r.net_pnl)>=0?'pnlp':'pnln'}">${Number(r.net_pnl)>=0?'+':''}${money(r.net_pnl)}</td><td>${r.profit_factor}</td><td>${r.avg_r}</td></tr>`).join('')}</table>`:'<div class="empty">Chưa có báo cáo ngày.</div>';let rec=D.recommendations||[];document.getElementById('recommendations').innerHTML=rec.length?rec.map(x=>`<div class="newsitem"><div class="newstitle">${esc(x.recommendation)}</div><div class="newsdesc">${esc(x.evidence)}</div><div class="newsmeta">${esc(x.source)} • ${dt(x.created_at)}</div></div>`).join(''):'<div class="empty">Chưa đủ dữ liệu để đề xuất thay đổi.</div>'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});
loadAll();setInterval(loadAll,30000);
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML_V3
