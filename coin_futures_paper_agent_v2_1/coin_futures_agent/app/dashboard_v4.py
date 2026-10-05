DASHBOARD_HTML_V4 = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coin Research & Paper Platform V4.0.1</title>
<style>
:root{
  --bg:#07101c;--panel:#101a2b;--panel2:#16243a;--line:#263a58;--text:#eef5ff;--muted:#94a8c5;
  --green:#37d887;--red:#ff6f7d;--amber:#ffc45c;--blue:#63a4ff;--cyan:#55dbea;--shadow:0 12px 32px rgba(0,0,0,.25)
}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:linear-gradient(180deg,#06101d,#091625 380px,#07101c);color:var(--text)}
a{color:#9ac7ff;text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:20;background:rgba(5,13,25,.95);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.topin{max-width:1580px;margin:auto;padding:13px 18px;display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.brand{font-size:20px;font-weight:900}.brand small{font-size:12px;color:var(--muted);font-weight:600;margin-left:8px}
.actions{display:flex;gap:7px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:9px 12px;border-radius:9px;font-weight:800;cursor:pointer}
.btn:hover{border-color:#557aa9}.btn.primary{background:#165fcf;border-color:#2c80f5}.btn.warn{background:#624615;border-color:#9d7223}.btn:disabled{opacity:.55;cursor:wait}
.wrap{max-width:1580px;margin:17px auto;padding:0 18px 50px}.status{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:12px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block}.dot.off{background:var(--red)}.dot.busy{background:var(--amber)}
.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px;font-weight:850}
.good{color:#75e8a6;background:rgba(55,216,135,.08);border-color:rgba(55,216,135,.35)}.bad{color:#ff929b;background:rgba(255,111,125,.08);border-color:rgba(255,111,125,.35)}
.warnb{color:#ffd384;background:rgba(255,196,92,.08);border-color:rgba(255,196,92,.35)}.blue{color:#95c2ff;background:rgba(99,164,255,.08);border-color:rgba(99,164,255,.35)}
.cards{display:grid;grid-template-columns:repeat(5,minmax(170px,1fr));gap:10px}.card{background:linear-gradient(180deg,var(--panel),#0d1726);border:1px solid var(--line);border-radius:13px;padding:13px;box-shadow:var(--shadow)}
.card .k{text-transform:uppercase;letter-spacing:.5px;font-size:10px;color:var(--muted)}.card .v{font-size:22px;font-weight:900;margin-top:6px}.card .sub{font-size:12px;color:var(--muted);margin-top:5px}
.tabs{display:flex;gap:7px;margin:16px 0 12px;overflow:auto}.tab{white-space:nowrap;border:1px solid var(--line);background:#0e192a;color:#adbed5;padding:9px 13px;border-radius:9px;font-weight:800;cursor:pointer}
.tab.active{background:#1c55a8;color:#fff;border-color:#4a8ef4}.section{display:none}.section.active{display:block}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:13px;box-shadow:var(--shadow);overflow:hidden}.panel h3{margin:0 0 10px;font-size:16px}
.panelhead{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.tablewrap{overflow:auto;max-height:650px}table{width:100%;border-collapse:collapse;min-width:760px}th,td{padding:8px;border-bottom:1px solid #203451;text-align:left;vertical-align:top;font-size:12px}
th{position:sticky;top:0;background:#14213a;color:#a9bbd3;z-index:2}tr:hover td{background:#11213a}
.pnlp{color:var(--green);font-weight:900}.pnln{color:var(--red);font-weight:900}.muted{color:var(--muted)}.small{font-size:11px}.reason{max-width:440px;line-height:1.45}.empty{text-align:center;color:var(--muted);padding:22px}
.kv{display:grid;grid-template-columns:1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid #203451}.kv:last-child{border-bottom:0}
.controls{display:flex;gap:7px;flex-wrap:wrap}.input,.select{background:#0d1727;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.newsitem{padding:11px 0;border-bottom:1px solid #203451}.newstitle{font-weight:800;line-height:1.4;margin:6px 0}.newsmeta{display:flex;gap:6px;flex-wrap:wrap;color:var(--muted);font-size:11px}.newsdesc{font-size:12px;color:#bdcadd;line-height:1.45}
.toast{position:fixed;right:18px;bottom:18px;display:none;background:#101d31;border:1px solid #3a567c;border-radius:10px;padding:11px 13px;box-shadow:var(--shadow);max-width:450px;z-index:30}.toast.show{display:block}
@media(max-width:1200px){.cards{grid-template-columns:repeat(3,1fr)}.grid2,.grid3{grid-template-columns:1fr}}
@media(max-width:650px){.cards{grid-template-columns:1fr 1fr}.wrap,.topin{padding-left:9px;padding-right:9px}.brand{font-size:17px}.card .v{font-size:19px}}
</style>
</head>
<body>
<div class="top"><div class="topin">
  <div class="brand">Coin Research & Paper Platform <small>V4.0.1 • Resilient Futures + Spot Research</small></div>
  <div class="actions">
    <button class="btn primary" onclick="act('/scan/run','Đang quét Futures...')">Quét Futures</button>
    <button class="btn" onclick="act('/paper/monitor','Đang kiểm tra lệnh...')">Monitor</button>
    <button class="btn primary" onclick="act('/spot/research/run','Đang research Spot...')">Research Spot</button>
    <button class="btn warn" onclick="act('/system/backup','Đang backup database...')">Backup DB</button>
    <button class="btn warn" onclick="act('/system/recover','Đang replay dữ liệu bị thiếu...')">Recovery</button>
    <button class="btn" onclick="loadAll()">Làm mới</button>
  </div>
</div></div>

<div class="wrap">
  <div class="status"><span id="dot" class="dot"></span><span id="status">Đang tải hệ thống...</span></div>
  <div class="cards" id="cards"></div>

  <div class="tabs">
    <button class="tab active" data-tab="overview">Tổng quan</button>
    <button class="tab" data-tab="positions">Futures đang mở</button>
    <button class="tab" data-tab="scanner">Scanner Futures</button>
    <button class="tab" data-tab="spot">Spot Research</button>
    <button class="tab" data-tab="system">System Guardian</button>
    <button class="tab" data-tab="performance">Hiệu suất</button>
    <button class="tab" data-tab="history">Lịch sử</button>
    <button class="tab" data-tab="news">News</button>
  </div>

  <section id="overview" class="section active">
    <div class="grid3">
      <div class="panel"><h3>System Guardian</h3><div id="sysQuick"></div></div>
      <div class="panel"><h3>Paper Futures</h3><div id="futQuick"></div></div>
      <div class="panel"><h3>Spot Research</h3><div id="spotQuick"></div></div>
    </div>
    <div class="grid2" style="margin-top:12px">
      <div class="panel"><h3>Top LONG Futures</h3><div id="topLong"></div></div>
      <div class="panel"><h3>Top SHORT Futures</h3><div id="topShort"></div></div>
    </div>
  </section>

  <section id="positions" class="section"><div class="panel"><h3>Vị thế paper đang mở</h3><div class="tablewrap" id="positionsTable"></div></div></section>

  <section id="scanner" class="section"><div class="panel">
    <div class="panelhead"><div><h3>Scanner Futures</h3><div class="muted small">50 coin thanh khoản cao, giữ nguyên strategy/data collection hiện tại.</div></div>
    <div class="controls"><input id="coinSearch" class="input" placeholder="BTC, ETH, SOL..." oninput="renderScanner()"><select id="biasFilter" class="select" onchange="renderScanner()"><option value="ALL">Tất cả</option><option>LONG</option><option>SHORT</option><option>WAIT</option></select></div></div>
    <div class="tablewrap" id="scannerTable"></div>
  </div></section>

  <section id="spot" class="section"><div class="panel">
    <div class="panelhead"><div><h3>Spot Research Agent</h3><div class="muted small">Research only: dữ liệu Spot + trend đa khung + momentum + volatility + news. Không tự đặt lệnh mua.</div></div><span id="spotTime" class="muted small"></span></div>
    <div class="tablewrap" id="spotTable"></div>
  </div></section>

  <section id="system" class="section">
    <div class="grid2">
      <div class="panel"><h3>Trạng thái hệ thống</h3><div id="systemState"></div></div>
      <div class="panel"><h3>Recovery gần nhất</h3><div id="recoveryState"></div></div>
    </div>
    <div class="panel" style="margin-top:12px"><h3>System events</h3><div class="tablewrap" id="eventsTable"></div></div>
  </section>

  <section id="performance" class="section">
    <div class="grid2"><div class="panel"><h3>Theo ngày</h3><div id="dailyPerf"></div></div><div class="panel"><h3>LONG vs SHORT</h3><div id="sidePerf"></div></div></div>
    <div class="panel" style="margin-top:12px"><h3>Setup performance</h3><div class="tablewrap" id="setupPerf"></div></div>
  </section>

  <section id="history" class="section"><div class="panel"><h3>Lịch sử Futures</h3><div class="tablewrap" id="historyTable"></div></div></section>

  <section id="news" class="section"><div class="panel"><h3>Market News</h3><div id="newsList"></div></div></section>
</div>
<div id="toast" class="toast"></div>

<script>
let D=null;
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(1)+'%';
const price=n=>{n=Number(n||0);if(n>=1000)return n.toFixed(2);if(n>=1)return n.toFixed(4);if(n>=.01)return n.toFixed(6);return n.toPrecision(5)};
const dt=x=>{try{return new Date(x).toLocaleString('vi-VN',{hour12:false})}catch(e){return x||'-'}};
const pnlClass=n=>Number(n)>=0?'pnlp':'pnln';
const badge=(t,k='blue')=>'<span class="badge '+k+'">'+esc(t)+'</span>';
const sideBadge=x=>badge(x,x==='LONG'?'good':x==='SHORT'?'bad':'warnb');
function toast(x){const e=document.getElementById('toast');e.textContent=x;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3500)}
async function act(url,msg){toast(msg);document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=true);try{const r=await fetch(url,{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);toast('Hoàn tất');await loadAll()}catch(e){toast('Lỗi: '+e.message)}finally{document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=false)}}
async function loadAll(){try{const r=await fetch('/api/dashboard');if(!r.ok)throw new Error(r.statusText);D=await r.json();renderAll();const net=D.system?.network||{};const online=net.status==='ONLINE';document.getElementById('dot').className='dot'+(online?'':' off');document.getElementById('status').textContent=(online?'ONLINE':'OFFLINE')+' • V'+D.version+(D.settings.data_collection_mode?' • DATA COLLECTION':'')+' • health '+D.settings.health_check_interval_sec+'s • '+new Date().toLocaleString('vi-VN')}catch(e){document.getElementById('dot').className='dot off';document.getElementById('status').textContent='Dashboard error: '+e.message}}
function renderAll(){renderCards();renderOverview();renderPositions();renderScanner();renderSpot();renderSystem();renderPerformance();renderHistory();renderNews()}
function renderCards(){const a=D.analytics||{},s=D.system||{},net=s.network||{},rec=s.last_recovery||{},sp=D.spot_research||{};const xs=[
 ['Network',net.status||'UNKNOWN',net.status==='OFFLINE'?(net.last_error||'Mất kết nối'):'Binance Futures'],
 ['Equity',money(a.equity)+' USDT','Balance + open PnL'],
 ['Open PnL',(a.unrealized_pnl>=0?'+':'')+money(a.unrealized_pnl)+' USDT',(D.open_positions||[]).length+' vị thế'],
 ['Win rate',pct(a.win_rate),(a.closed||0)+' lệnh đã đóng'],
 ['Spot research',sp.top?.[0]?.symbol||'-',sp.top?.[0]?('Score '+sp.top[0].score+' • '+sp.top[0].verdict):'Chưa có report']
];document.getElementById('cards').innerHTML=xs.map(x=>'<div class="card"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div><div class="sub">'+esc(x[2])+'</div></div>').join('')}
function kv(k,v){return '<div class="kv"><span>'+esc(k)+'</span><b>'+v+'</b></div>'}
function renderOverview(){const sys=D.system||{},net=sys.network||{},b=sys.last_backup||{},r=sys.last_recovery||{},a=D.analytics||{},sp=D.spot_research||{},ns=D.news_summary||{};
 document.getElementById('sysQuick').innerHTML=kv('Network',badge(net.status||'UNKNOWN',net.status==='ONLINE'?'good':'bad'))+kv('Backup',b.created_at?dt(b.created_at):'-')+kv('Recovery',r.status||'-')+kv('Replay candles',Number(r.candles_replayed||0));
 document.getElementById('futQuick').innerHTML=kv('Balance',money(a.balance)+' USDT')+kv('Realized',money(a.realized_pnl)+' USDT')+kv('Unrealized',money(a.unrealized_pnl)+' USDT')+kv('Max DD',pct(a.max_drawdown_pct));
 document.getElementById('spotQuick').innerHTML=kv('Market regime',badge(sp.market_regime||'-',sp.market_regime==='BULLISH'?'good':sp.market_regime==='BEARISH'?'bad':'warnb'))+kv('Researched',Number(sp.symbols_researched||0))+kv('Top candidate',sp.top?.[0]?esc(sp.top[0].symbol)+' / '+sp.top[0].score:'-')+kv('News market',badge(ns.market_bias||'-','blue'));
 document.getElementById('topLong').innerHTML=topTable(D.scan?.top_long,'LONG');document.getElementById('topShort').innerHTML=topTable(D.scan?.top_short,'SHORT')}
function topTable(xs,side){if(!xs?.length)return '<div class="empty">Chưa có tín hiệu.</div>';return '<table><tr><th>Coin</th><th>Score</th><th>Giá</th><th>RSI</th><th>Vol</th><th>OI</th><th>Lý do</th></tr>'+xs.slice(0,8).map(x=>'<tr><td><b>'+esc(x.symbol)+'</b></td><td>'+Number(side==='LONG'?x.long_score:x.short_score).toFixed(1)+'</td><td>'+price(x.price)+'</td><td>'+Number(x.rsi_1h||0).toFixed(1)+'</td><td>'+Number(x.volume_ratio_1h||0).toFixed(2)+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td><td class="reason">'+esc(((side==='LONG'?x.reasons_long:x.reasons_short)||[]).slice(0,3).join('; '))+'</td></tr>').join('')+'</table>'}
function renderPositions(){const xs=D.open_positions||[];document.getElementById('positionsTable').innerHTML=xs.length?'<table><tr><th>Coin</th><th>Side</th><th>Score</th><th>Entry</th><th>Last</th><th>PnL</th><th>R</th><th>SL</th><th>TP</th><th>Giữ</th><th>Lý do</th></tr>'+xs.map(x=>'<tr><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.side)+'</td><td>'+x.score+'</td><td>'+price(x.entry_price)+'</td><td>'+price(x.market_price)+'</td><td class="'+pnlClass(x.unrealized_pnl)+'">'+money(x.unrealized_pnl)+'</td><td class="'+pnlClass(x.unrealized_r)+'">'+Number(x.unrealized_r||0).toFixed(2)+'R</td><td>'+price(x.stop_loss)+'</td><td>'+price(x.take_profit)+'</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td class="reason">'+esc(x.reason_text)+'</td></tr>').join('')+'</table>':'<div class="empty">Không có vị thế đang mở.</div>'}
function renderScanner(){if(!D)return;const q=(document.getElementById('coinSearch')?.value||'').toUpperCase(),f=document.getElementById('biasFilter')?.value||'ALL';const xs=(D.scan?.all||[]).filter(x=>(!q||x.symbol.includes(q))&&(f==='ALL'||x.bias===f));document.getElementById('scannerTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Bias</th><th>LONG</th><th>SHORT</th><th>RSI</th><th>Vol</th><th>OI</th><th>Funding</th><th>ATR</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.bias)+'</td><td>'+x.long_score+'</td><td>'+x.short_score+'</td><td>'+x.rsi_1h+'</td><td>'+x.volume_ratio_1h+'x</td><td>'+x.oi_change_pct+'%</td><td>'+(Number(x.funding_rate||0)*100).toFixed(4)+'%</td><td>'+x.atr_pct_1h+'%</td></tr>').join('')+'</table>':'<div class="empty">Không có kết quả.</div>'}
function verdictBadge(v){return badge(v,v==='HIGH_PRIORITY_RESEARCH'?'good':v==='CAUTION'?'bad':v==='WATCH'?'blue':'warnb')}
function renderSpot(){const sp=D.spot_research||{},xs=sp.top||[];document.getElementById('spotTime').textContent=sp.created_at?'Cập nhật '+dt(sp.created_at):'Chưa chạy research';document.getElementById('spotTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Score</th><th>Verdict</th><th>Risk</th><th>Giá</th><th>24h</th><th>RSI4H</th><th>Vol4H</th><th>7D</th><th>30D</th><th>News</th><th>Luận điểm</th><th>Rủi ro</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td><b>'+x.score+'</b></td><td>'+verdictBadge(x.verdict)+'</td><td>'+badge(x.risk_level,x.risk_level.includes('HIGH')?'bad':'warnb')+'</td><td>'+price(x.price)+'</td><td class="'+pnlClass(x.price_change_24h_pct)+'">'+Number(x.price_change_24h_pct).toFixed(2)+'%</td><td>'+x.rsi_4h+'</td><td>'+x.volume_ratio_4h+'x</td><td class="'+pnlClass(x.momentum_7d_pct)+'">'+x.momentum_7d_pct+'%</td><td class="'+pnlClass(x.momentum_30d_pct)+'">'+x.momentum_30d_pct+'%</td><td>'+badge(x.news_bias,'blue')+'<div class="small muted">'+Number(x.news_score||0).toFixed(1)+'</div></td><td class="reason">'+esc((x.reasons||[]).join('; '))+'</td><td class="reason">'+esc((x.risks||[]).join('; '))+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có Spot Research. Bấm “Research Spot”.</div>'}
function renderSystem(){const s=D.system||{},n=s.network||{},b=s.last_backup||{},r=s.last_recovery||{};document.getElementById('systemState').innerHTML=kv('Network',badge(n.status||'UNKNOWN',n.status==='ONLINE'?'good':'bad'))+kv('Offline/Online since',n.since?dt(n.since):'-')+kv('Last error',esc(n.last_error||'-'))+kv('Last backup',b.created_at?dt(b.created_at):'-')+kv('Backup file',esc(b.path||'-'));
 document.getElementById('recoveryState').innerHTML=kv('Status',esc(r.status||'-'))+kv('Positions checked',Number(r.positions_checked||0))+kv('Positions closed',Number(r.positions_closed||0))+kv('Candles replayed',Number(r.candles_replayed||0))+kv('Errors',Number((r.errors||[]).length));
 const ev=D.system_events||[];document.getElementById('eventsTable').innerHTML=ev.length?'<table><tr><th>Thời gian</th><th>Severity</th><th>Event</th><th>Nội dung</th></tr>'+ev.map(x=>'<tr><td>'+dt(x.created_at)+'</td><td>'+badge(x.severity,x.severity==='ERROR'?'bad':x.severity==='WARNING'?'warnb':'blue')+'</td><td><b>'+esc(x.event_type)+'</b></td><td class="reason">'+esc(x.message)+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có system event.</div>'}
function renderPerformance(){const a=D.analytics||{},ds=a.daily||[],ss=a.setups||[],sides=a.sides||[];document.getElementById('dailyPerf').innerHTML=ds.length?'<table><tr><th>Ngày</th><th>Lệnh</th><th>WR</th><th>PnL</th><th>Avg R</th></tr>'+[...ds].reverse().map(x=>'<tr><td>'+x.date+'</td><td>'+x.trades+'</td><td>'+pct(x.win_rate)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+money(x.net_pnl)+'</td><td>'+x.avg_r+'R</td></tr>').join('')+'</table>':'<div class="empty">Chưa đủ dữ liệu.</div>';document.getElementById('sidePerf').innerHTML=sides.map(x=>kv(x.side,x.trades+' lệnh • '+pct(x.win_rate)+' • '+money(x.net_pnl)+' USDT')).join('');document.getElementById('setupPerf').innerHTML=ss.length?'<table><tr><th>Setup</th><th>Lệnh</th><th>WR</th><th>PnL</th><th>Avg R</th></tr>'+ss.map(x=>'<tr><td><b>'+esc(x.setup)+'</b></td><td>'+x.trades+'</td><td>'+pct(x.win_rate)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+money(x.net_pnl)+'</td><td>'+x.avg_r+'R</td></tr>').join('')+'</table>':'<div class="empty">Chưa đủ dữ liệu setup.</div>'}
function renderHistory(){const xs=[...(D.trades||[])].reverse();document.getElementById('historyTable').innerHTML=xs.length?'<table><tr><th>ID</th><th>Coin</th><th>Side</th><th>Exit</th><th>PnL</th><th>R</th><th>Giữ</th><th>Score</th><th>Lý do</th></tr>'+xs.map(x=>'<tr><td>#'+x.id+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.side)+'</td><td>'+esc(x.exit_reason)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+money(x.net_pnl)+'</td><td>'+Number(x.r_multiple||0).toFixed(2)+'R</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td>'+Number(x.score||0).toFixed(1)+'</td><td class="reason">'+esc(x.reason_text)+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có lịch sử.</div>'}
function renderNews(){const xs=D.news||[];document.getElementById('newsList').innerHTML=xs.length?xs.slice(0,40).map(n=>'<div class="newsitem"><div class="newsmeta">'+badge(n.sentiment,n.sentiment==='BULLISH'?'good':n.sentiment==='BEARISH'?'bad':'warnb')+' '+badge('Impact '+n.impact_score,'blue')+' <span>'+esc(n.source)+'</span> • <span>'+dt(n.published_at)+'</span></div><div class="newstitle"><a href="'+esc(n.url)+'" target="_blank" rel="noopener">'+esc(n.title)+'</a></div><div class="newsdesc">'+esc((n.summary||'').slice(0,320))+'</div></div>').join(''):'<div class="empty">Chưa có news.</div>'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});
loadAll();setInterval(loadAll,30000);
</script>
</body>
</html>
"""
