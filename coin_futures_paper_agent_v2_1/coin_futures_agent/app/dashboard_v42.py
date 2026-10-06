DASHBOARD_HTML_V42 = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy Battle Pro V4.2</title>
<style>
:root{
  --bg:#08111f;--side:#0a1423;--panel:#101c2f;--panel2:#14233a;--line:#243956;
  --text:#edf4ff;--muted:#8fa4c0;--green:#42d392;--red:#ff7180;--amber:#ffc861;
  --blue:#69a8ff;--cyan:#58d7e8;--purple:#aa8cff;--shadow:0 14px 34px rgba(0,0,0,.23);
}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--text)}
a{color:#9bc8ff;text-decoration:none}button,input,select{font:inherit}.app{min-height:100vh;display:grid;grid-template-columns:235px 1fr}
.sidebar{position:sticky;top:0;height:100vh;background:linear-gradient(180deg,#091322,#0b1727);border-right:1px solid var(--line);padding:18px 12px;overflow:auto}
.logo{padding:5px 8px 18px;font-size:18px;font-weight:900;letter-spacing:.2px}.logo small{display:block;margin-top:5px;font-size:11px;color:var(--muted);font-weight:600}
.navtitle{font-size:10px;color:#607792;text-transform:uppercase;letter-spacing:1px;padding:15px 10px 6px}.nav{display:block;width:100%;text-align:left;border:0;background:transparent;color:#aebed2;padding:9px 10px;border-radius:8px;cursor:pointer;font-weight:700;margin:2px 0}.nav:hover{background:#12243b;color:white}.nav.active{background:#1d4f91;color:white}
.main{min-width:0}.topbar{position:sticky;top:0;z-index:20;background:rgba(8,17,31,.92);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:12px 18px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.headline{font-weight:900}.statusrow,.actions{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.chip{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid var(--line);border-radius:999px;font-size:11px;font-weight:800;background:#0e1a2b}.dot{width:7px;height:7px;border-radius:50%;background:var(--green)}.dot.red{background:var(--red)}.dot.amber{background:var(--amber)}
.btn{border:1px solid var(--line);background:#13233a;color:var(--text);padding:8px 10px;border-radius:8px;font-weight:800;cursor:pointer}.btn:hover{border-color:#4c75a6}.btn.primary{background:#1459bd;border-color:#2779e2}.btn.warn{background:#5d4317;border-color:#8a6726}.btn:disabled{opacity:.55}
.content{padding:18px;max-width:1700px;margin:auto}.view{display:none}.view.active{display:block}.titlebar{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:13px}.titlebar h1{font-size:24px;margin:0}.subtitle{font-size:12px;color:var(--muted);margin-top:5px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(190px,1fr));gap:10px}.casecard,.panel,.metric{background:linear-gradient(180deg,var(--panel),#0d1828);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}.casecard{padding:14px}.casehead{display:flex;justify-content:space-between;gap:8px;align-items:center}.caseid{font-size:11px;color:var(--muted);font-weight:900}.casename{font-size:13px;font-weight:850}.big{font-size:26px;font-weight:900;margin-top:10px}.casegrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:11px}.casegrid div{background:#0b1727;padding:8px;border-radius:8px}.k{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}.v{font-size:14px;font-weight:850;margin-top:3px}
.panel{padding:14px;overflow:hidden}.panel h3{margin:0 0 10px;font-size:15px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.metric{padding:12px}.metric .mv{font-size:20px;font-weight:900;margin-top:5px}
.tablewrap{overflow:auto;max-height:650px}table{width:100%;border-collapse:collapse;min-width:820px}th,td{padding:8px;border-bottom:1px solid #203652;text-align:left;vertical-align:top;font-size:12px}th{position:sticky;top:0;background:#14233a;color:#9fb2ca;z-index:2}tr:hover td{background:#102038}
.badge{display:inline-flex;align-items:center;padding:3px 7px;border:1px solid var(--line);border-radius:999px;font-size:10px;font-weight:900}.good{color:#75e7aa;border-color:rgba(66,211,146,.4);background:rgba(66,211,146,.08)}.bad{color:#ff939e;border-color:rgba(255,113,128,.4);background:rgba(255,113,128,.08)}.warn{color:#ffd785;border-color:rgba(255,200,97,.4);background:rgba(255,200,97,.08)}.info{color:#9fc9ff;border-color:rgba(105,168,255,.4);background:rgba(105,168,255,.08)}
.pos{color:var(--green);font-weight:900}.neg{color:var(--red);font-weight:900}.muted{color:var(--muted)}.small{font-size:11px}.reason{max-width:420px;line-height:1.4}.empty{padding:25px;text-align:center;color:var(--muted)}
.banner{border:1px solid var(--line);border-radius:12px;padding:13px 14px;margin-bottom:12px;background:#0c192a}.banner.lock{border-color:#a63847;background:rgba(166,56,71,.12)}.banner.caution{border-color:#9e7629;background:rgba(158,118,41,.11)}.banner.normal{border-color:#247653;background:rgba(36,118,83,.1)}.bannerhead{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.banner h2{font-size:16px;margin:0}.banner p{margin:7px 0 0;color:#b9c7d8;font-size:12px;line-height:1.45}
.chartbox{height:330px;position:relative}.chartbox canvas{width:100%;height:100%}.legend{display:flex;gap:12px;flex-wrap:wrap;margin:7px 0 0;font-size:11px}.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}
.controls{display:flex;gap:7px;flex-wrap:wrap}.input,.select{background:#0c1829;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 9px}
.event{padding:11px 0;border-bottom:1px solid #203652}.event:last-child{border-bottom:0}.eventtitle{font-weight:850;line-height:1.4;margin:5px 0}.eventmeta{display:flex;gap:5px;flex-wrap:wrap;color:var(--muted);font-size:10px}
.jobs{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.job{background:#0b1727;border:1px solid #203652;border-radius:9px;padding:10px}.jobname{font-size:10px;text-transform:uppercase;color:var(--muted)}.jobstatus{font-weight:850;margin-top:4px}
.toast{position:fixed;right:18px;bottom:18px;display:none;background:#102039;border:1px solid #365779;border-radius:9px;padding:11px 13px;box-shadow:var(--shadow);z-index:40}.toast.show{display:block}
.mobilemenu{display:none}
@media(max-width:1200px){.cards{grid-template-columns:1fr 1fr}.grid2,.grid3{grid-template-columns:1fr}.jobs{grid-template-columns:1fr 1fr}}
@media(max-width:800px){.app{grid-template-columns:1fr}.sidebar{display:none;position:fixed;z-index:50;width:235px}.sidebar.open{display:block}.mobilemenu{display:inline-block}.content{padding:10px}.topbar{padding:9px 10px}.cards{grid-template-columns:1fr}.jobs{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar" id="sidebar">
  <div class="logo">Strategy Battle Pro<small>V4.2 • Paper Research Terminal</small></div>
  <div class="navtitle">Trading</div>
  <button class="nav active" data-view="overview">Overview</button>
  <button class="nav" data-view="battle">Battle Matrix</button>
  <button class="nav" data-view="cohorts">Cohort Analysis</button>
  <button class="nav" data-view="positions">Open Positions</button>
  <div class="navtitle">Research</div>
  <button class="nav" data-view="scanner">Futures Scanner</button>
  <button class="nav" data-view="guardian">News Guardian</button>
  <button class="nav" data-view="spot">Spot Research</button>
  <div class="navtitle">Operations</div>
  <button class="nav" data-view="reports">Daily Reports</button>
  <button class="nav" data-view="history">Trade History</button>
  <button class="nav" data-view="system">System Health</button>
</aside>

<main class="main">
<header class="topbar">
  <div class="statusrow">
    <button class="btn mobilemenu" onclick="document.getElementById('sidebar').classList.toggle('open')">Menu</button>
    <span class="headline">Strategy Battle Pro</span>
    <span class="chip"><span class="dot" id="netDot"></span><span id="netText">...</span></span>
    <span class="chip" id="guardianChip">News Guardian ...</span>
    <span class="chip">V4.2</span>
  </div>
  <div class="actions">
    <button class="btn primary" onclick="act('/scan/run','Đang quét Futures...')">Scan</button>
    <button class="btn" onclick="act('/paper/monitor','Đang monitor...')">Monitor</button>
    <button class="btn" onclick="act('/news/run','Đang cập nhật News Guardian...')">News</button>
    <button class="btn" onclick="act('/spot/research/run','Đang research Spot...')">Spot</button>
    <button class="btn warn" onclick="act('/system/backup','Đang backup...')">Backup</button>
    <button class="btn" onclick="loadAll()">Refresh</button>
  </div>
</header>

<div class="content">
<section id="overview" class="view active">
  <div class="titlebar"><div><h1>Portfolio Overview</h1><div class="subtitle">4 chiến lược paper trên cùng cohort tín hiệu.</div></div><div class="small muted" id="updatedAt"></div></div>
  <div id="guardianBanner"></div>
  <div class="cards" id="caseCards"></div>
  <div class="grid2" style="margin-top:12px">
    <div class="panel"><h3>Equity Curve A/B/C/D</h3><div class="chartbox"><canvas id="equityChart"></canvas></div><div class="legend" id="equityLegend"></div></div>
    <div class="panel"><h3>Experiment Health</h3><div id="experimentHealth"></div></div>
  </div>
  <div class="grid3" style="margin-top:12px" id="factorCards"></div>
</section>

<section id="battle" class="view">
  <div class="titlebar"><div><h1>Battle Matrix</h1><div class="subtitle">So sánh profitability, expectancy và risk—not chỉ Win Rate.</div></div></div>
  <div class="panel"><div class="tablewrap" id="battleTable"></div></div>
  <div class="grid2" style="margin-top:12px">
    <div class="panel"><h3>Performance by Score</h3><div class="tablewrap" id="scoreTable"></div></div>
    <div class="panel"><h3>Performance by BTC Regime</h3><div class="tablewrap" id="regimeTable"></div></div>
  </div>
</section>

<section id="cohorts" class="view">
  <div class="titlebar"><div><h1>Cohort Analysis</h1><div class="subtitle">Một tín hiệu gốc → A/B/C/D cùng vào để so sánh công bằng.</div></div></div>
  <div class="grid2">
    <div class="panel"><h3>Best Complete Cohorts</h3><div class="tablewrap" id="bestCohorts"></div></div>
    <div class="panel"><h3>Worst Complete Cohorts</h3><div class="tablewrap" id="worstCohorts"></div></div>
  </div>
  <div class="panel" style="margin-top:12px"><h3>Recent Cohorts</h3><div class="tablewrap" id="recentCohorts"></div></div>
</section>

<section id="positions" class="view"><div class="titlebar"><div><h1>Open Positions</h1></div></div><div class="panel"><div class="tablewrap" id="positionsTable"></div></div></section>

<section id="scanner" class="view">
  <div class="titlebar"><div><h1>Futures Scanner</h1><div class="subtitle">Signal engine gốc dùng chung cho cả 4 case.</div></div><div class="controls"><input id="coinSearch" class="input" placeholder="BTC, ETH, SOL..." oninput="renderScanner()"><select id="biasFilter" class="select" onchange="renderScanner()"><option value="ALL">All bias</option><option>LONG</option><option>SHORT</option><option>WAIT</option></select></div></div>
  <div class="panel"><div class="tablewrap" id="scannerTable"></div></div>
</section>

<section id="guardian" class="view">
  <div class="titlebar"><div><h1>News Guardian</h1><div class="subtitle">Cluster analysis, Event Lock, cooldown và kiểm tra prediction 5m/15m/1h/4h.</div></div></div>
  <div id="guardianDetail"></div>
  <div class="panel"><h3>Event History</h3><div class="tablewrap" id="guardianEvents"></div></div>
</section>

<section id="spot" class="view"><div class="titlebar"><div><h1>Spot Research</h1><div class="subtitle">Research only—không tự mua.</div></div></div><div class="panel"><div class="tablewrap" id="spotTable"></div></div></section>

<section id="reports" class="view"><div class="titlebar"><div><h1>Daily Intelligence Reports</h1><div class="subtitle">Tạo tự động lúc 23:58.</div></div></div><div class="panel"><div class="tablewrap" id="reportsTable"></div></div></section>

<section id="history" class="view"><div class="titlebar"><div><h1>Trade History</h1></div></div><div class="panel"><div class="tablewrap" id="historyTable"></div></div></section>

<section id="system" class="view">
  <div class="titlebar"><div><h1>System Health</h1><div class="subtitle">Scheduler, recovery, backup và trạng thái từng worker.</div></div></div>
  <div class="jobs" id="jobs"></div>
  <div class="grid2" style="margin-top:12px">
    <div class="panel"><h3>System Status</h3><div id="systemState"></div></div>
    <div class="panel"><h3>Recent System Events</h3><div class="tablewrap" id="systemEvents"></div></div>
  </div>
</section>
</div>
</main>
</div>
<div class="toast" id="toast"></div>

<script>
let D=null;
const CASES=['BASE_RR2','BASE_RR1','REVERSE_RR2','REVERSE_RR1'];
const COLORS={BASE_RR2:'#69a8ff',BASE_RR1:'#42d392',REVERSE_RR2:'#ff7180',REVERSE_RR1:'#ffc861'};
const LABELS={BASE_RR2:'A · Base 1:2',BASE_RR1:'B · Base 1:1',REVERSE_RR2:'C · Reverse 1:2',REVERSE_RR1:'D · Reverse 1:1'};
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(1)+'%';
const price=n=>{n=Number(n||0);if(n>=1000)return n.toFixed(2);if(n>=1)return n.toFixed(4);if(n>=.01)return n.toFixed(6);return n.toPrecision(5)};
const dt=x=>{try{return new Date(x).toLocaleString('vi-VN',{hour12:false})}catch(e){return x||'-'}};
const cls=n=>Number(n)>=0?'pos':'neg';
const badge=(x,k='info')=>'<span class="badge '+k+'">'+esc(x)+'</span>';
const side=x=>badge(x,x==='LONG'?'good':x==='SHORT'?'bad':'warn');
const caseBadge=id=>'<span class="badge info">'+esc(LABELS[id]||id)+'</span>';
function toast(x){const e=document.getElementById('toast');e.textContent=x;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3500)}
async function act(url,msg){toast(msg);document.querySelectorAll('.actions .btn').forEach(x=>x.disabled=true);try{const r=await fetch(url,{method:'POST'}),j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);toast('Hoàn tất');await loadAll()}catch(e){toast('Lỗi: '+e.message)}finally{document.querySelectorAll('.actions .btn').forEach(x=>x.disabled=false)}}
async function loadAll(){try{const r=await fetch('/api/dashboard');if(!r.ok)throw new Error(r.statusText);D=await r.json();renderAll()}catch(e){document.getElementById('netText').textContent='Dashboard error';document.getElementById('netDot').className='dot red';toast(e.message)}}
function battle(){return D.strategy_battle||{}}
function rows(){return battle().strategies||[]}
function renderAll(){renderStatus();renderOverview();renderBattle();renderCohorts();renderPositions();renderScanner();renderGuardian();renderSpot();renderReports();renderHistory();renderSystem()}
function renderStatus(){const net=D.system?.network||{},g=D.news_guardian?.state||{};document.getElementById('netText').textContent=net.status||'UNKNOWN';document.getElementById('netDot').className='dot '+(net.status==='ONLINE'?'':net.status==='RECOVERING'?'amber':'red');const mode=g.mode||'NORMAL';document.getElementById('guardianChip').innerHTML='News '+badge(mode,mode==='EVENT_LOCK'?'bad':mode==='NORMAL'?'good':'warn');document.getElementById('updatedAt').textContent='Updated '+new Date().toLocaleString('vi-VN')}
function guardianBanner(){const g=D.news_guardian?.state||{},mode=g.mode||'NORMAL';const klass=mode==='EVENT_LOCK'?'lock':mode==='NORMAL'?'normal':'caution';return '<div class="banner '+klass+'"><div class="bannerhead"><h2>News Guardian · '+esc(mode)+'</h2>'+badge('Impact '+Number(g.impact_score||0).toFixed(0),mode==='EVENT_LOCK'?'bad':mode==='NORMAL'?'good':'warn')+'</div><p>'+esc(g.headline||g.reason||'No active high-impact event.')+(g.direction?' · Direction '+esc(g.direction)+' · Confidence '+Number(g.confidence||0).toFixed(0)+'%':'')+(g.cooldown_until?' · Cooldown '+dt(g.cooldown_until):'')+'</p></div>'}
function renderOverview(){document.getElementById('guardianBanner').innerHTML=guardianBanner();document.getElementById('caseCards').innerHTML=rows().map(s=>{const a=s.analytics||{};return '<div class="casecard"><div class="casehead"><div><div class="caseid">CASE '+esc(s.short_name)+'</div><div class="casename">'+esc(s.name)+'</div></div>'+badge(a.realized_pnl>=0?'PROFIT':'LOSS',a.realized_pnl>=0?'good':'bad')+'</div><div class="big">'+money(a.balance)+' <span class="small muted">USDT</span></div><div class="casegrid"><div><div class="k">Net PnL</div><div class="v '+cls(a.realized_pnl)+'">'+(a.realized_pnl>=0?'+':'')+money(a.realized_pnl)+'</div></div><div><div class="k">Win Rate</div><div class="v">'+pct(a.win_rate)+'</div></div><div><div class="k">Expectancy</div><div class="v '+cls(a.expectancy_r)+'">'+Number(a.expectancy_r||0).toFixed(3)+'R</div></div><div><div class="k">Max DD</div><div class="v">'+pct(a.max_drawdown_pct)+'</div></div></div></div>'}).join('');const b=battle(),f=b.factors||{};document.getElementById('experimentHealth').innerHTML='<div class="banner '+(b.sample_ready?'normal':'caution')+'"><div class="bannerhead"><h2>'+(b.sample_ready?'Sample Ready':'Collecting Sample')+'</h2>'+badge((b.min_closed_per_case||0)+' / '+(b.preferred_comparison_sample||50)+' trades','info')+'</div><p>Leader PnL: '+esc(LABELS[b.leader_net_pnl]||'-')+' · Expectancy: '+esc(LABELS[b.leader_expectancy]||'-')+' · PF: '+esc(LABELS[b.leader_profit_factor]||'-')+' · Lowest DD: '+esc(LABELS[b.leader_low_drawdown]||'-')+'</p></div><div class="metric"><div class="k">Complete Cohorts</div><div class="mv">'+Number(b.cohorts?.complete_count||0)+'</div></div>';document.getElementById('factorCards').innerHTML='<div class="metric"><div class="k">Direction Effect</div><div class="mv">'+esc(f.direction_effect?.leader||'TIE')+'</div><div class="small muted">Base '+money(f.direction_effect?.base_net_pnl)+' vs Reverse '+money(f.direction_effect?.reverse_net_pnl)+'</div></div><div class="metric"><div class="k">R:R Effect</div><div class="mv">'+esc(f.rr_effect?.leader||'TIE')+'</div><div class="small muted">1:2 '+money(f.rr_effect?.rr2_net_pnl)+' vs 1:1 '+money(f.rr_effect?.rr1_net_pnl)+'</div></div><div class="metric"><div class="k">News Mode</div><div class="mv">'+esc(D.news_guardian?.state?.mode||'NORMAL')+'</div><div class="small muted">'+esc(D.news_guardian?.state?.direction||'UNCLEAR')+' '+Number(D.news_guardian?.state?.confidence||0).toFixed(0)+'%</div></div>';requestAnimationFrame(drawEquity)}
function drawEquity(){const canvas=document.getElementById('equityChart');if(!canvas||!D)return;const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;canvas.width=Math.max(300,rect.width*dpr);canvas.height=Math.max(220,rect.height*dpr);const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);const W=rect.width,H=rect.height,pad={l:52,r:15,t:15,b:28};ctx.clearRect(0,0,W,H);const series={};let values=[];rows().forEach(s=>{const xs=s.analytics?.equity_curve||[];series[s.strategy_id]=xs;values.push(...xs.map(x=>Number(x.equity||0)))});if(!values.length)return;let min=Math.min(...values),max=Math.max(...values);if(max===min){max+=1;min-=1}const n=Math.max(...Object.values(series).map(x=>x.length),2);ctx.strokeStyle='#203652';ctx.fillStyle='#7890ad';ctx.font='10px Segoe UI';for(let i=0;i<5;i++){const y=pad.t+(H-pad.t-pad.b)*i/4;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();const val=max-(max-min)*i/4;ctx.fillText(val.toFixed(0),5,y+3)}for(const id of CASES){const xs=series[id]||[];if(xs.length<1)continue;ctx.strokeStyle=COLORS[id];ctx.lineWidth=2;ctx.beginPath();xs.forEach((p,i)=>{const x=pad.l+(W-pad.l-pad.r)*(i/Math.max(1,n-1));const y=pad.t+(H-pad.t-pad.b)*(1-(Number(p.equity)-min)/(max-min));if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)});ctx.stroke()}document.getElementById('equityLegend').innerHTML=CASES.map(id=>'<span><i style="background:'+COLORS[id]+'"></i>'+esc(LABELS[id])+'</span>').join('')}
function renderBattle(){const b=battle();document.getElementById('battleTable').innerHTML=rows().length?'<table><tr><th>Case</th><th>Balance</th><th>Closed</th><th>W/L</th><th>WR</th><th>Net PnL</th><th>PF</th><th>Expectancy</th><th>Avg Win</th><th>Avg Loss</th><th>TP</th><th>SL</th><th>News Exit</th><th>Max DD</th></tr>'+rows().map(s=>{const a=s.analytics||{};return '<tr><td><b>'+esc(s.name)+'</b></td><td>'+money(a.balance)+'</td><td>'+a.closed+'</td><td>'+a.wins+'/'+a.losses+'</td><td>'+pct(a.win_rate)+'</td><td class="'+cls(a.realized_pnl)+'">'+money(a.realized_pnl)+'</td><td>'+Number(a.profit_factor||0).toFixed(2)+'</td><td class="'+cls(a.expectancy_r)+'">'+Number(a.expectancy_r||0).toFixed(3)+'R</td><td>'+Number(a.avg_win_r||0).toFixed(2)+'R</td><td>'+Number(a.avg_loss_r||0).toFixed(2)+'R</td><td>'+pct(a.tp_rate)+'</td><td>'+pct(a.sl_rate)+'</td><td>'+pct(a.news_exit_rate)+'</td><td>'+pct(a.max_drawdown_pct)+'</td></tr>'}).join('')+'</table>':'<div class="empty">No battle data.</div>';document.getElementById('scoreTable').innerHTML=matrixTable(b.score_buckets||[],'bucket');document.getElementById('regimeTable').innerHTML=matrixTable(b.regimes||[],'regime')}
function matrixTable(xs,key){if(!xs.length)return '<div class="empty">Chưa đủ dữ liệu.</div>';return '<table><tr><th>'+esc(key)+'</th>'+CASES.map(id=>'<th>'+esc(id.slice(0,8))+'</th>').join('')+'</tr>'+xs.map(r=>'<tr><td><b>'+esc(r[key])+'</b></td>'+CASES.map(id=>{const s=r.strategies?.[id]||{};return '<td>'+Number(s.trades||0)+' trades<br><span class="'+cls(s.net_pnl)+'">'+money(s.net_pnl)+'</span> · WR '+pct(s.win_rate)+'</td>'}).join('')+'</tr>').join('')+'</table>'}
function cohortTable(xs){if(!xs?.length)return '<div class="empty">Chưa có complete cohort.</div>';return '<table><tr><th>Coin</th><th>Score</th><th>Source</th><th>BTC</th><th>A</th><th>B</th><th>C</th><th>D</th><th>Best</th></tr>'+[...xs].reverse().map(x=>'<tr><td><b>'+esc(x.symbol)+'</b></td><td>'+Number(x.score||0).toFixed(1)+'</td><td>'+esc(x.source_signal_side||'-')+'</td><td>'+esc(x.btc_regime||'-')+'</td>'+CASES.map(id=>{const y=x.results?.[id];return '<td>'+(y?('<span class="'+cls(y.net_pnl)+'">'+money(y.net_pnl)+'</span><br>'+Number(y.r_multiple||0).toFixed(2)+'R '+esc(y.exit_reason)):'-')+'</td>'}).join('')+'<td>'+caseBadge(x.best_strategy)+'</td></tr>').join('')+'</table>'}
function renderCohorts(){const c=battle().cohorts||{};document.getElementById('bestCohorts').innerHTML=cohortTable(c.best);document.getElementById('worstCohorts').innerHTML=cohortTable(c.worst);document.getElementById('recentCohorts').innerHTML=cohortTable(c.recent)}
function renderPositions(){const xs=D.open_positions||[];document.getElementById('positionsTable').innerHTML=xs.length?'<table><tr><th>Case</th><th>Coin</th><th>Side</th><th>Score</th><th>Entry</th><th>Last</th><th>PnL</th><th>R</th><th>SL</th><th>TP</th><th>Hold</th></tr>'+xs.map(x=>'<tr><td>'+caseBadge(x.strategy_id)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+side(x.side)+'</td><td>'+x.score+'</td><td>'+price(x.entry_price)+'</td><td>'+price(x.market_price)+'</td><td class="'+cls(x.unrealized_pnl)+'">'+money(x.unrealized_pnl)+'</td><td class="'+cls(x.unrealized_r)+'">'+Number(x.unrealized_r||0).toFixed(2)+'R</td><td>'+price(x.stop_loss)+'</td><td>'+price(x.take_profit)+'</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td></tr>').join('')+'</table>':'<div class="empty">No open positions.</div>'}
function renderScanner(){if(!D)return;const q=(document.getElementById('coinSearch')?.value||'').toUpperCase(),f=document.getElementById('biasFilter')?.value||'ALL';const xs=(D.scan?.all||[]).filter(x=>(!q||x.symbol.includes(q))&&(f==='ALL'||x.bias===f));document.getElementById('scannerTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Bias</th><th>LONG</th><th>SHORT</th><th>RSI</th><th>Volume</th><th>OI</th><th>Funding</th><th>ATR</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+side(x.bias)+'</td><td>'+x.long_score+'</td><td>'+x.short_score+'</td><td>'+x.rsi_1h+'</td><td>'+x.volume_ratio_1h+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td><td>'+(Number(x.funding_rate||0)*100).toFixed(4)+'%</td><td>'+x.atr_pct_1h+'%</td></tr>').join('')+'</table>':'<div class="empty">No scanner results.</div>'}
function renderGuardian(){const g=D.news_guardian?.state||{},events=D.news_guardian?.events||[];document.getElementById('guardianDetail').innerHTML=guardianBanner()+'<div class="grid3" style="margin-bottom:12px"><div class="metric"><div class="k">Direction</div><div class="mv">'+esc(g.direction||'UNCLEAR')+'</div></div><div class="metric"><div class="k">Confidence</div><div class="mv">'+Number(g.confidence||0).toFixed(0)+'%</div></div><div class="metric"><div class="k">Scope</div><div class="mv">'+esc(g.scope||'MARKET')+'</div></div></div>';document.getElementById('guardianEvents').innerHTML=events.length?'<table><tr><th>Time</th><th>Mode</th><th>Event</th><th>Impact</th><th>Direction</th><th>Conf.</th><th>5m</th><th>15m</th><th>1h</th><th>4h</th><th>Result</th></tr>'+events.map(ev=>{const r=ev.reactions||{},ch=k=>r[k]?Number(r[k].change_pct).toFixed(2)+'%':'-';return '<tr><td>'+dt(ev.created_at)+'</td><td>'+badge(ev.status,ev.status==='EVENT_LOCK'?'bad':ev.status==='CAUTION'?'warn':'info')+'</td><td class="reason"><b>'+esc(ev.headline)+'</b></td><td>'+ev.impact_score+'</td><td>'+esc(ev.direction)+'</td><td>'+Number(ev.confidence||0).toFixed(0)+'%</td><td>'+ch('5m')+'</td><td>'+ch('15m')+'</td><td>'+ch('1h')+'</td><td>'+ch('4h')+'</td><td>'+badge(ev.prediction_result,ev.prediction_result==='CORRECT'?'good':ev.prediction_result==='WRONG'?'bad':'info')+'</td></tr>'}).join('')+'</table>':'<div class="empty">No guardian events yet.</div>'}
function renderSpot(){const xs=D.spot_research?.top||[];document.getElementById('spotTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Score</th><th>Verdict</th><th>Risk</th><th>24h</th><th>RSI4H</th><th>7D</th><th>30D</th><th>News</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+x.score+'</td><td>'+badge(x.verdict,'info')+'</td><td>'+badge(x.risk_level,x.risk_level.includes('HIGH')?'bad':'warn')+'</td><td class="'+cls(x.price_change_24h_pct)+'">'+Number(x.price_change_24h_pct).toFixed(2)+'%</td><td>'+x.rsi_4h+'</td><td>'+x.momentum_7d_pct+'%</td><td>'+x.momentum_30d_pct+'%</td><td>'+esc(x.news_bias)+'</td></tr>').join('')+'</table>':'<div class="empty">No Spot Research yet.</div>'}
function renderReports(){const rs=D.reports||[];document.getElementById('reportsTable').innerHTML=rs.length?'<table><tr><th>Date</th><th>PnL Leader</th><th>WR Leader</th><th>Expectancy Leader</th><th>Sample</th><th>View</th></tr>'+rs.map(r=>'<tr><td><b>'+esc(r.report_date)+'</b></td><td>'+esc(LABELS[r.winner_by_net_pnl]||'-')+'</td><td>'+esc(LABELS[r.winner_by_win_rate]||'-')+'</td><td>'+esc(LABELS[r.winner_by_expectancy]||'-')+'</td><td>'+badge(r.sample_ready?'READY':'COLLECTING',r.sample_ready?'good':'warn')+'</td><td><a href="/reports/daily/'+esc(r.report_date)+'/html" target="_blank">HTML</a> · <a href="/reports/daily/'+esc(r.report_date)+'/markdown" target="_blank">Markdown</a></td></tr>').join('')+'</table>':'<div class="empty">No reports yet.</div>'}
function renderHistory(){const xs=[...(D.trades||[])].reverse();document.getElementById('historyTable').innerHTML=xs.length?'<table><tr><th>Case</th><th>ID</th><th>Coin</th><th>Side</th><th>Exit</th><th>PnL</th><th>R</th><th>Hold</th><th>Score</th></tr>'+xs.map(x=>'<tr><td>'+caseBadge(x.strategy_id)+'</td><td>#'+x.id+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+side(x.side)+'</td><td>'+esc(x.exit_reason)+'</td><td class="'+cls(x.net_pnl)+'">'+money(x.net_pnl)+'</td><td>'+Number(x.r_multiple||0).toFixed(2)+'R</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td>'+Number(x.score||0).toFixed(1)+'</td></tr>').join('')+'</table>':'<div class="empty">No trade history.</div>'}
function renderSystem(){const sys=D.system||{},jobs=sys.jobs||{},net=sys.network||{},rec=sys.last_recovery||{},bak=sys.last_backup||{},sch=sys.scheduler||{};const names=['scan','monitor','news','spot','health','backup','report','news_review'];document.getElementById('jobs').innerHTML=names.map(n=>{const j=jobs[n]||{};return '<div class="job"><div class="jobname">'+esc(n)+'</div><div class="jobstatus">'+esc(j.status||'WAITING')+'</div><div class="small muted">'+(j.at?dt(j.at):'-')+'</div></div>'}).join('');document.getElementById('systemState').innerHTML='<table><tr><th>Component</th><th>Status</th><th>Detail</th></tr><tr><td>Network</td><td>'+badge(net.status||'UNKNOWN',net.status==='ONLINE'?'good':'bad')+'</td><td>'+esc(net.last_error||'-')+'</td></tr><tr><td>Scheduler</td><td>'+badge(sch.status||'UNKNOWN',sch.status==='HEALTHY'?'good':'warn')+'</td><td>Missed jobs: '+Number(sch.missed_jobs||0)+'</td></tr><tr><td>Backup</td><td>'+badge(bak.ok===false?'FAILED':'OK',bak.ok===false?'bad':'good')+'</td><td>'+dt(bak.created_at)+'</td></tr><tr><td>Recovery</td><td>'+badge(rec.status||'-','info')+'</td><td>'+Number(rec.candles_replayed||0)+' candles replayed</td></tr></table>';const ev=D.system_events||[];document.getElementById('systemEvents').innerHTML=ev.length?'<table><tr><th>Time</th><th>Severity</th><th>Event</th><th>Message</th></tr>'+ev.map(x=>'<tr><td>'+dt(x.created_at)+'</td><td>'+badge(x.severity,x.severity==='ERROR'?'bad':x.severity==='WARNING'?'warn':'info')+'</td><td>'+esc(x.event_type)+'</td><td class="reason">'+esc(x.message)+'</td></tr>').join('')+'</table>':'<div class="empty">No system events.</div>'}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.view).classList.add('active');document.getElementById('sidebar').classList.remove('open');if(b.dataset.view==='overview')requestAnimationFrame(drawEquity)});
window.addEventListener('resize',()=>{if(document.getElementById('overview').classList.contains('active'))drawEquity()});
loadAll();setInterval(loadAll,30000);
</script>
</body></html>
"""
