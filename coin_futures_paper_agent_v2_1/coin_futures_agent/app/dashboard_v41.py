DASHBOARD_HTML_V41 = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Strategy Battle V4.1</title>
<style>
:root{--bg:#07101c;--panel:#101a2b;--panel2:#16243a;--line:#263a58;--text:#eef5ff;--muted:#94a8c5;--green:#37d887;--red:#ff6f7d;--amber:#ffc45c;--blue:#63a4ff;--shadow:0 12px 32px rgba(0,0,0,.24)}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:linear-gradient(180deg,#06101d,#091625 380px,#07101c);color:var(--text)}
a{color:#9ac7ff;text-decoration:none}.top{position:sticky;top:0;z-index:20;background:rgba(5,13,25,.95);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}
.topin{max-width:1600px;margin:auto;padding:13px 18px;display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.brand{font-size:20px;font-weight:900}.brand small{font-size:12px;color:var(--muted);font-weight:600;margin-left:8px}
.actions{display:flex;gap:7px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:9px 12px;border-radius:9px;font-weight:800;cursor:pointer}.btn.primary{background:#165fcf;border-color:#2c80f5}.btn.warn{background:#624615;border-color:#9d7223}.btn:disabled{opacity:.5}
.wrap{max-width:1600px;margin:17px auto;padding:0 18px 50px}.status{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:12px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.dot.off{background:var(--red)}
.cards{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:10px}.card{background:linear-gradient(180deg,var(--panel),#0d1726);border:1px solid var(--line);border-radius:13px;padding:13px;box-shadow:var(--shadow)}.card .k{text-transform:uppercase;letter-spacing:.5px;font-size:10px;color:var(--muted)}.card .v{font-size:22px;font-weight:900;margin-top:6px}.card .sub{font-size:12px;color:var(--muted);margin-top:5px}
.tabs{display:flex;gap:7px;margin:16px 0 12px;overflow:auto}.tab{white-space:nowrap;border:1px solid var(--line);background:#0e192a;color:#adbed5;padding:9px 13px;border-radius:9px;font-weight:800;cursor:pointer}.tab.active{background:#1c55a8;color:#fff;border-color:#4a8ef4}
.section{display:none}.section.active{display:block}.panel{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:13px;box-shadow:var(--shadow);overflow:hidden}.panel h3{margin:0 0 10px;font-size:16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.tablewrap{overflow:auto;max-height:680px}
table{width:100%;border-collapse:collapse;min-width:850px}th,td{padding:9px 8px;border-bottom:1px solid #203451;text-align:left;vertical-align:top;font-size:12px}th{position:sticky;top:0;background:#14213a;color:#a9bbd3;z-index:2}tr:hover td{background:#11213a}
.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px;font-weight:850}.good{color:#75e8a6;background:rgba(55,216,135,.08);border-color:rgba(55,216,135,.35)}.bad{color:#ff929b;background:rgba(255,111,125,.08);border-color:rgba(255,111,125,.35)}.warnb{color:#ffd384;background:rgba(255,196,92,.08);border-color:rgba(255,196,92,.35)}.blue{color:#95c2ff;background:rgba(99,164,255,.08);border-color:rgba(99,164,255,.35)}
.pnlp{color:var(--green);font-weight:900}.pnln{color:var(--red);font-weight:900}.muted{color:var(--muted)}.small{font-size:11px}.reason{max-width:440px;line-height:1.45}.empty{text-align:center;color:var(--muted);padding:22px}
.note{padding:11px 12px;border-radius:10px;border:1px solid var(--line);background:#0c1728;margin-bottom:12px;line-height:1.45}.note.goodnote{border-color:rgba(55,216,135,.45)}.note.warnnote{border-color:rgba(255,196,92,.45)}
.kv{display:grid;grid-template-columns:1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid #203451}.kv:last-child{border-bottom:0}
.controls{display:flex;gap:7px;flex-wrap:wrap}.input,.select{background:#0d1727;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.newsitem{padding:11px 0;border-bottom:1px solid #203451}.newstitle{font-weight:800;line-height:1.4;margin:6px 0}.newsmeta{display:flex;gap:6px;flex-wrap:wrap;color:var(--muted);font-size:11px}.newsdesc{font-size:12px;color:#bdcadd;line-height:1.45}
.toast{position:fixed;right:18px;bottom:18px;display:none;background:#101d31;border:1px solid #3a567c;border-radius:10px;padding:11px 13px;box-shadow:var(--shadow);max-width:450px;z-index:30}.toast.show{display:block}
@media(max-width:1200px){.cards{grid-template-columns:repeat(3,1fr)}.grid2,.grid3{grid-template-columns:1fr}}@media(max-width:650px){.cards{grid-template-columns:1fr 1fr}.wrap,.topin{padding-left:9px;padding-right:9px}.brand{font-size:17px}.card .v{font-size:19px}}
</style>
</head>
<body>
<div class="top"><div class="topin">
<div class="brand">Strategy Battle <small>V4.1 • 3 paper agents chạy song song</small></div>
<div class="actions">
<button class="btn primary" onclick="act('/scan/run','Đang quét và tạo 3 case...')">Quét Futures</button>
<button class="btn" onclick="act('/paper/monitor','Đang kiểm tra A/B/C...')">Monitor</button>
<button class="btn primary" onclick="act('/spot/research/run','Đang research Spot...')">Research Spot</button>
<button class="btn warn" onclick="act('/system/backup','Đang backup DB...')">Backup DB</button>
<button class="btn warn" onclick="act('/system/recover','Đang recovery...')">Recovery</button>
<button class="btn" onclick="loadAll()">Làm mới</button>
</div></div></div>

<div class="wrap">
<div class="status"><span id="dot" class="dot"></span><span id="status">Đang tải...</span></div>
<div class="cards" id="cards"></div>

<div class="tabs">
<button class="tab active" data-tab="battle">Strategy Battle</button>
<button class="tab" data-tab="positions">Lệnh đang mở</button>
<button class="tab" data-tab="scanner">Scanner</button>
<button class="tab" data-tab="spot">Spot Research</button>
<button class="tab" data-tab="reports">Báo cáo ngày</button>
<button class="tab" data-tab="system">System Guardian</button>
<button class="tab" data-tab="history">Lịch sử</button>
<button class="tab" data-tab="news">News</button>
</div>

<section id="battle" class="section active">
<div id="sampleNote"></div>
<div class="panel"><h3>So sánh 3 case</h3><div class="tablewrap" id="battleTable"></div></div>
<div class="grid2" style="margin-top:12px">
<div class="panel"><h3>Top LONG từ AI gốc</h3><div id="topLong"></div></div>
<div class="panel"><h3>Top SHORT từ AI gốc</h3><div id="topShort"></div></div>
</div>
</section>

<section id="positions" class="section"><div class="panel"><h3>Vị thế paper A/B/C đang mở</h3><div class="tablewrap" id="positionsTable"></div></div></section>
<section id="scanner" class="section"><div class="panel"><div class="controls" style="margin-bottom:10px"><input id="coinSearch" class="input" placeholder="BTC, ETH, SOL..." oninput="renderScanner()"><select id="biasFilter" class="select" onchange="renderScanner()"><option value="ALL">Tất cả</option><option>LONG</option><option>SHORT</option><option>WAIT</option></select></div><div class="tablewrap" id="scannerTable"></div></div></section>
<section id="spot" class="section"><div class="panel"><h3>Spot Research Agent</h3><div class="muted small" id="spotTime"></div><div class="tablewrap" id="spotTable"></div></div></section>
<section id="reports" class="section"><div class="panel"><h3>Daily Strategy Battle Reports</h3><div id="reportsTable"></div></div></section>
<section id="system" class="section"><div class="grid2"><div class="panel"><h3>System status</h3><div id="systemState"></div></div><div class="panel"><h3>Recovery gần nhất</h3><div id="recoveryState"></div></div></div><div class="panel" style="margin-top:12px"><h3>System events</h3><div class="tablewrap" id="eventsTable"></div></div></section>
<section id="history" class="section"><div class="panel"><h3>Lịch sử A/B/C</h3><div class="tablewrap" id="historyTable"></div></div></section>
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
const caseBadge=x=>badge(x==='BASE_RR2'?'CASE A':x==='BASE_RR1'?'CASE B':x==='REVERSE_RR2'?'CASE C':x,'blue');
function toast(x){const e=document.getElementById('toast');e.textContent=x;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3500)}
async function act(url,msg){toast(msg);document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=true);try{const r=await fetch(url,{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);toast('Hoàn tất');await loadAll()}catch(e){toast('Lỗi: '+e.message)}finally{document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=false)}}
async function loadAll(){try{const r=await fetch('/api/dashboard');if(!r.ok)throw new Error(r.statusText);D=await r.json();renderAll();const net=D.system?.network||{};const online=net.status==='ONLINE';document.getElementById('dot').className='dot'+(online?'':' off');document.getElementById('status').textContent=(net.status||'UNKNOWN')+' • V'+D.version+' • DATA COLLECTION '+(D.settings.data_collection_mode?'ON':'OFF')+' • '+new Date().toLocaleString('vi-VN')}catch(e){document.getElementById('dot').className='dot off';document.getElementById('status').textContent='Dashboard error: '+e.message}}
function renderAll(){renderCards();renderBattle();renderPositions();renderScanner();renderSpot();renderReports();renderSystem();renderHistory();renderNews()}
function battleRows(){return D.strategy_battle?.strategies||[]}
function renderCards(){const net=D.system?.network||{},sp=D.spot_research||{},bs=battleRows();const cards=[['Network',net.status||'UNKNOWN','System Guardian']];for(const s of bs){const a=s.analytics||{};cards.push([s.short_name+' • '+s.name.split(' - ')[1],money(a.balance)+' USDT','WR '+pct(a.win_rate)+' • PnL '+(a.realized_pnl>=0?'+':'')+money(a.realized_pnl)])}cards.push(['Spot research',sp.top?.[0]?.symbol||'-',sp.top?.[0]?('Score '+sp.top[0].score):'Chưa có report']);document.getElementById('cards').innerHTML=cards.map(x=>'<div class="card"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div><div class="sub">'+esc(x[2])+'</div></div>').join('')}
function renderBattle(){const b=D.strategy_battle||{},rows=b.strategies||[];const ready=!!b.sample_ready;document.getElementById('sampleNote').innerHTML='<div class="note '+(ready?'goodnote':'warnnote')+'">'+(ready?'ĐÃ ĐỦ MẪU TỐI THIỂU để bắt đầu so sánh nghiêm túc.':'CHƯA ĐỦ MẪU: case ít nhất mới có '+Number(b.min_closed_per_case||0)+' lệnh đóng. Mục tiêu tối thiểu '+Number(b.recommended_comparison_sample||30)+' lệnh/case, tốt hơn là 50–100.')+(b.leader_net_pnl?' • Dẫn PnL: '+b.leader_net_pnl:'')+(b.leader_win_rate?' • Dẫn WR: '+b.leader_win_rate:'')+'</div>';document.getElementById('battleTable').innerHTML=rows.length?'<table><tr><th>Case</th><th>Cách trade</th><th>Balance</th><th>Equity</th><th>Đã đóng</th><th>W/L</th><th>Win rate</th><th>Net PnL</th><th>PF</th><th>Avg R</th><th>Max DD</th><th>Đang mở</th></tr>'+rows.map(s=>{const a=s.analytics||{},lead=b.leader_net_pnl===s.strategy_id?' '+badge('PnL leader','good'):'',wr=b.leader_win_rate===s.strategy_id?' '+badge('WR leader','blue'):'';return '<tr><td><b>'+esc(s.name)+'</b>'+lead+wr+'</td><td class="reason">'+esc(s.description)+'</td><td>'+money(a.balance)+'</td><td>'+money(a.equity)+'</td><td>'+a.closed+'</td><td>'+a.wins+'/'+a.losses+'</td><td><b>'+pct(a.win_rate)+'</b></td><td class="'+pnlClass(a.realized_pnl)+'">'+(a.realized_pnl>=0?'+':'')+money(a.realized_pnl)+'</td><td>'+Number(a.profit_factor||0).toFixed(2)+'</td><td>'+Number(a.avg_r||0).toFixed(2)+'R</td><td>'+pct(a.max_drawdown_pct)+'</td><td>'+((a.open_positions||[]).length)+'</td></tr>'}).join('')+'</table>':'<div class="empty">Chưa có dữ liệu battle.</div>';document.getElementById('topLong').innerHTML=topTable(D.scan?.top_long,'LONG');document.getElementById('topShort').innerHTML=topTable(D.scan?.top_short,'SHORT')}
function topTable(xs,side){if(!xs?.length)return '<div class="empty">Chưa có tín hiệu.</div>';return '<table><tr><th>Coin</th><th>Score</th><th>Giá</th><th>RSI</th><th>Vol</th><th>OI</th></tr>'+xs.slice(0,8).map(x=>'<tr><td><b>'+esc(x.symbol)+'</b></td><td>'+Number(side==='LONG'?x.long_score:x.short_score).toFixed(1)+'</td><td>'+price(x.price)+'</td><td>'+Number(x.rsi_1h||0).toFixed(1)+'</td><td>'+Number(x.volume_ratio_1h||0).toFixed(2)+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td></tr>').join('')+'</table>'}
function renderPositions(){const xs=D.open_positions||[];document.getElementById('positionsTable').innerHTML=xs.length?'<table><tr><th>Case</th><th>Coin</th><th>Side</th><th>Score</th><th>Entry</th><th>Last</th><th>PnL</th><th>R</th><th>SL</th><th>TP</th><th>Giữ</th></tr>'+xs.map(x=>'<tr><td>'+caseBadge(x.strategy_id)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.side)+'</td><td>'+x.score+'</td><td>'+price(x.entry_price)+'</td><td>'+price(x.market_price)+'</td><td class="'+pnlClass(x.unrealized_pnl)+'">'+money(x.unrealized_pnl)+'</td><td class="'+pnlClass(x.unrealized_r)+'">'+Number(x.unrealized_r||0).toFixed(2)+'R</td><td>'+price(x.stop_loss)+'</td><td>'+price(x.take_profit)+'</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td></tr>').join('')+'</table>':'<div class="empty">Chưa có vị thế mở.</div>'}
function renderScanner(){if(!D)return;const q=(document.getElementById('coinSearch')?.value||'').toUpperCase(),f=document.getElementById('biasFilter')?.value||'ALL';const xs=(D.scan?.all||[]).filter(x=>(!q||x.symbol.includes(q))&&(f==='ALL'||x.bias===f));document.getElementById('scannerTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Bias gốc</th><th>LONG</th><th>SHORT</th><th>RSI</th><th>Vol</th><th>OI</th><th>ATR</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.bias)+'</td><td>'+x.long_score+'</td><td>'+x.short_score+'</td><td>'+x.rsi_1h+'</td><td>'+x.volume_ratio_1h+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td><td>'+x.atr_pct_1h+'%</td></tr>').join('')+'</table>':'<div class="empty">Không có kết quả.</div>'}
function verdictBadge(v){return badge(v,v==='HIGH_PRIORITY_RESEARCH'?'good':v==='CAUTION'?'bad':v==='WATCH'?'blue':'warnb')}
function renderSpot(){const sp=D.spot_research||{},xs=sp.top||[];document.getElementById('spotTime').textContent=sp.created_at?'Cập nhật '+dt(sp.created_at):'Chưa chạy research';document.getElementById('spotTable').innerHTML=xs.length?'<table><tr><th>#</th><th>Coin</th><th>Score</th><th>Verdict</th><th>Risk</th><th>24h</th><th>RSI4H</th><th>7D</th><th>30D</th><th>News</th></tr>'+xs.map((x,i)=>'<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b></td><td><b>'+x.score+'</b></td><td>'+verdictBadge(x.verdict)+'</td><td>'+badge(x.risk_level,x.risk_level.includes('HIGH')?'bad':'warnb')+'</td><td class="'+pnlClass(x.price_change_24h_pct)+'">'+Number(x.price_change_24h_pct).toFixed(2)+'%</td><td>'+x.rsi_4h+'</td><td>'+x.momentum_7d_pct+'%</td><td>'+x.momentum_30d_pct+'%</td><td>'+badge(x.news_bias,'blue')+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có Spot Research.</div>'}
function renderReports(){const rs=D.reports||[];document.getElementById('reportsTable').innerHTML=rs.length?'<table><tr><th>Ngày</th><th>Case A</th><th>Case B</th><th>Case C</th><th>Trạng thái mẫu</th></tr>'+rs.map(r=>{const m={};(r.strategies||[]).forEach(s=>m[s.strategy_id]=s);const cell=id=>{const s=m[id];return s?('WR '+s.win_rate_pct+'% • PnL '+(s.net_pnl>=0?'+':'')+money(s.net_pnl)):'-'};return '<tr><td><a target="_blank" href="/reports/daily/'+esc(r.report_date)+'/markdown">'+esc(r.report_date)+'</a></td><td>'+cell('BASE_RR2')+'</td><td>'+cell('BASE_RR1')+'</td><td>'+cell('REVERSE_RR2')+'</td><td>'+badge(r.sample_ready?'READY':'CHƯA ĐỦ',r.sample_ready?'good':'warnb')+'</td></tr>'}).join('')+'</table>':'<div class="empty">Chưa có báo cáo ngày mới.</div>'}
function kv(k,v){return '<div class="kv"><span>'+esc(k)+'</span><b>'+v+'</b></div>'}
function renderSystem(){const s=D.system||{},n=s.network||{},b=s.last_backup||{},r=s.last_recovery||{};document.getElementById('systemState').innerHTML=kv('Network',badge(n.status||'UNKNOWN',n.status==='ONLINE'?'good':'bad'))+kv('Last backup',b.created_at?dt(b.created_at):'-')+kv('Backup file',esc(b.path||'-'));document.getElementById('recoveryState').innerHTML=kv('Status',esc(r.status||'-'))+kv('Positions checked',Number(r.positions_checked||0))+kv('Positions closed',Number(r.positions_closed||0))+kv('Candles replayed',Number(r.candles_replayed||0))+kv('Errors',Number((r.errors||[]).length));const ev=D.system_events||[];document.getElementById('eventsTable').innerHTML=ev.length?'<table><tr><th>Thời gian</th><th>Severity</th><th>Event</th><th>Nội dung</th></tr>'+ev.map(x=>'<tr><td>'+dt(x.created_at)+'</td><td>'+badge(x.severity,x.severity==='ERROR'?'bad':x.severity==='WARNING'?'warnb':'blue')+'</td><td><b>'+esc(x.event_type)+'</b></td><td class="reason">'+esc(x.message)+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có event.</div>'}
function renderHistory(){const xs=[...(D.trades||[])].reverse();document.getElementById('historyTable').innerHTML=xs.length?'<table><tr><th>Case</th><th>ID</th><th>Coin</th><th>Side</th><th>Exit</th><th>PnL</th><th>R</th><th>Giữ</th><th>Score</th></tr>'+xs.map(x=>'<tr><td>'+caseBadge(x.strategy_id)+'</td><td>#'+x.id+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+sideBadge(x.side)+'</td><td>'+esc(x.exit_reason)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+money(x.net_pnl)+'</td><td>'+Number(x.r_multiple||0).toFixed(2)+'R</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td>'+Number(x.score||0).toFixed(1)+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có lệnh đóng.</div>'}
function renderNews(){const xs=D.news||[];document.getElementById('newsList').innerHTML=xs.length?xs.slice(0,40).map(n=>'<div class="newsitem"><div class="newsmeta">'+badge(n.sentiment,n.sentiment==='BULLISH'?'good':n.sentiment==='BEARISH'?'bad':'warnb')+' '+badge('Impact '+n.impact_score,'blue')+' <span>'+esc(n.source)+'</span> • <span>'+dt(n.published_at)+'</span></div><div class="newstitle"><a href="'+esc(n.url)+'" target="_blank" rel="noopener">'+esc(n.title)+'</a></div><div class="newsdesc">'+esc((n.summary||'').slice(0,320))+'</div></div>').join(''):'<div class="empty">Chưa có news.</div>'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});
loadAll();setInterval(loadAll,30000);
</script>
</body></html>
"""
