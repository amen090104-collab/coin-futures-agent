DASHBOARD_HTML_V3 = r"""
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coin Futures Agent V3</title>
<style>
:root{
  --bg:#08101d;--panel:#111b2d;--panel2:#17243a;--line:#263955;--text:#edf4ff;--muted:#93a6c3;
  --green:#35d07f;--red:#ff6675;--amber:#ffbe55;--blue:#5a9cff;--cyan:#3ed6e8;--shadow:0 14px 35px rgba(0,0,0,.28)
}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:linear-gradient(180deg,#07101e,#0a1424 360px,#08101d);color:var(--text)}
a{color:#96c5ff;text-decoration:none}a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:20;background:rgba(7,14,27,.94);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.topin{max-width:1540px;margin:auto;padding:13px 18px;display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
.brand{font-size:20px;font-weight:850}.brand small{font-size:12px;color:var(--muted);font-weight:500;margin-left:8px}
.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:9px 13px;border-radius:10px;cursor:pointer;font-weight:700}
.btn:hover{border-color:#5377a8}.btn.primary{background:#155ccf;border-color:#2f7bf0}.btn:disabled{opacity:.55;cursor:wait}
.wrap{max-width:1540px;margin:18px auto;padding:0 18px 50px}.status{display:flex;gap:9px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:13px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--green)}.dot.busy{background:var(--amber);box-shadow:0 0 0 5px rgba(255,190,85,.12)}
.cards{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:11px}.card{background:linear-gradient(180deg,var(--panel),#0e1727);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow)}
.card .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}.card .v{font-size:24px;font-weight:850;margin-top:6px}.card .sub{font-size:12px;color:var(--muted);margin-top:5px}
.tabs{display:flex;gap:7px;margin:17px 0 13px;overflow:auto;padding-bottom:3px}.tab{white-space:nowrap;border:1px solid var(--line);background:#0f192a;color:#aab9ce;padding:9px 13px;border-radius:10px;cursor:pointer;font-weight:750}
.tab.active{background:#1d54a8;color:#fff;border-color:#4d8cf4}.section{display:none}.section.active{display:block}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:13px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:var(--shadow);overflow:hidden}.panel h3{margin:0 0 11px;font-size:16px}.panelhead{display:flex;gap:10px;justify-content:space-between;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.tablewrap{overflow:auto;max-height:630px}table{width:100%;border-collapse:collapse;min-width:780px}th,td{padding:9px 8px;border-bottom:1px solid #21334e;text-align:left;font-size:13px;vertical-align:top}
th{position:sticky;top:0;background:#142039;color:#a9bad2;z-index:1}tr:hover td{background:#112039}
.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px;font-weight:850}.bull{color:#71e6a0;background:rgba(53,208,127,.08);border-color:rgba(53,208,127,.36)}
.bear{color:#ff8791;background:rgba(255,102,117,.08);border-color:rgba(255,102,117,.36)}.mix{color:#ffd27f;background:rgba(255,190,85,.08);border-color:rgba(255,190,85,.36)}
.blue{color:#8bb8ff;background:rgba(90,156,255,.08);border-color:rgba(90,156,255,.36)}.pnlp{color:var(--green);font-weight:850}.pnln{color:var(--red);font-weight:850}
.score{font-weight:850}.muted{color:var(--muted)}.small{font-size:12px}.reason{max-width:430px;line-height:1.45}.empty{padding:22px;text-align:center;color:var(--muted)}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.input,.select{background:#0d1728;border:1px solid var(--line);color:var(--text);padding:8px 10px;border-radius:8px}.input{min-width:210px}
.newsitem{padding:12px 0;border-bottom:1px solid #20314b}.newstitle{font-weight:750;line-height:1.4;margin:6px 0}.newsmeta{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--muted)}
.newsdesc{font-size:12px;color:#b9c6d9;line-height:1.45}.progress{height:7px;background:#1d2c45;border-radius:9px;overflow:hidden}.progress i{display:block;height:100%;background:linear-gradient(90deg,#35d07f,#ffbe55,#ff6675)}
.meter{display:grid;grid-template-columns:120px 1fr 70px;gap:9px;align-items:center;margin:8px 0}.bar{height:9px;background:#1d2c45;border-radius:8px;overflow:hidden}.bar i{display:block;height:100%;background:#5a9cff}
.kv{display:grid;grid-template-columns:1fr auto;gap:7px;padding:7px 0;border-bottom:1px solid #20314b}.kv:last-child{border-bottom:0}
.toast{position:fixed;right:18px;bottom:18px;background:#101c31;border:1px solid #3a5377;border-radius:11px;padding:11px 14px;box-shadow:var(--shadow);display:none;max-width:440px;z-index:30}.toast.show{display:block}
.footer{color:var(--muted);font-size:12px;margin-top:18px}
@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr)}.grid2,.grid3{grid-template-columns:1fr}}
@media(max-width:620px){.wrap,.topin{padding-left:9px;padding-right:9px}.cards{grid-template-columns:1fr 1fr}.card .v{font-size:20px}.brand{font-size:17px}}
</style>
</head>
<body>
<div class="top"><div class="topin">
  <div class="brand">Coin Futures Paper Agent <small>V3.0 • Scanner + Paper Trading + News + Analytics</small></div>
  <div class="actions">
    <button class="btn primary" onclick="action('/scan/run','Đang quét thị trường...')">Quét ngay</button>
    <button class="btn" onclick="action('/paper/monitor','Đang cập nhật lệnh...')">Cập nhật lệnh</button>
    <button class="btn" onclick="action('/news/run','Đang cập nhật tin...')">Cập nhật tin</button>
    <button class="btn" onclick="loadAll()">Làm mới</button>
  </div>
</div></div>
<div class="wrap">
  <div class="status"><span id="statusDot" class="dot"></span><span id="status">Đang tải...</span></div>
  <div class="cards" id="cards"></div>

  <div class="tabs">
    <button class="tab active" data-tab="overview">Tổng quan</button>
    <button class="tab" data-tab="scanner">Scanner 50 coin</button>
    <button class="tab" data-tab="positions">Lệnh đang mở</button>
    <button class="tab" data-tab="performance">Hiệu suất</button>
    <button class="tab" data-tab="history">Lịch sử</button>
    <button class="tab" data-tab="news">Tin tức</button>
    <button class="tab" data-tab="reports">Báo cáo & Khắc phục</button>
  </div>

  <section id="overview" class="section active">
    <div class="grid2">
      <div class="panel"><div class="panelhead"><h3>Top LONG</h3><span id="scanTime" class="muted small"></span></div><div id="topLong"></div></div>
      <div class="panel"><h3>Top SHORT</h3><div id="topShort"></div></div>
    </div>
    <div class="grid3" style="margin-top:13px">
      <div class="panel"><h3>Trạng thái scanner</h3><div id="scannerState"></div></div>
      <div class="panel"><h3>Rủi ro tài khoản</h3><div id="riskBox"></div></div>
      <div class="panel"><h3>News 24h</h3><div id="newsBox"></div></div>
    </div>
  </section>

  <section id="scanner" class="section">
    <div class="panel">
      <div class="panelhead">
        <div><h3>Scanner 50 coin</h3><div class="muted small">Xếp theo score mạnh nhất. Có thể tìm nhanh coin hoặc lọc LONG/SHORT/WAIT.</div></div>
        <div class="controls"><input class="input" id="coinSearch" placeholder="BTC, SOL, XRP..." oninput="renderScanner()"><select class="select" id="biasFilter" onchange="renderScanner()"><option value="ALL">Tất cả</option><option value="LONG">LONG</option><option value="SHORT">SHORT</option><option value="WAIT">WAIT</option></select></div>
      </div>
      <div class="tablewrap" id="scannerTable"></div>
    </div>
  </section>

  <section id="positions" class="section"><div class="panel"><h3>Lệnh paper đang mở</h3><div class="tablewrap" id="positionsTable"></div></div></section>

  <section id="performance" class="section">
    <div class="grid2">
      <div class="panel"><h3>Hiệu suất theo ngày</h3><div id="dailyPerf"></div></div>
      <div class="panel"><h3>LONG vs SHORT</h3><div id="sidePerf"></div></div>
    </div>
    <div class="panel" style="margin-top:13px"><h3>Setup / lý do vào lệnh</h3><div class="muted small" style="margin-bottom:8px">Thống kê reason code xuất hiện trong các lệnh đã đóng. Dùng để biết setup nào đang hiệu quả hoặc đang kéo PnL xuống.</div><div class="tablewrap" id="setupPerf"></div></div>
  </section>

  <section id="history" class="section"><div class="panel"><h3>Lịch sử giao dịch</h3><div class="tablewrap" id="historyTable"></div></div></section>

  <section id="news" class="section">
    <div class="grid2">
      <div class="panel"><h3>Tổng hợp tin tức</h3><div id="newsSummary"></div></div>
      <div class="panel"><h3>Bộ lọc</h3><div class="controls"><select class="select" id="sentFilter" onchange="renderNews()"><option value="ALL">Mọi xu hướng</option><option value="BULLISH">Bullish</option><option value="BEARISH">Bearish</option><option value="NEUTRAL">Neutral</option></select><select class="select" id="impactFilter" onchange="renderNews()"><option value="0">Mọi impact</option><option value="75">Impact ≥ 75</option><option value="60">Impact ≥ 60</option></select><input class="input" id="newsSearch" placeholder="BTC, ETF, SEC..." oninput="renderNews()"></div></div>
    </div>
    <div class="panel" style="margin-top:13px"><h3>Dòng tin</h3><div id="newsList"></div></div>
  </section>

  <section id="reports" class="section">
    <div class="grid2">
      <div class="panel"><h3>Báo cáo ngày</h3><div id="reportsList"></div></div>
      <div class="panel"><h3>Đề xuất khắc phục</h3><div id="recommendations"></div></div>
    </div>
  </section>

  <div class="footer">Paper trading only. V3 hiển thị PnL chưa đóng theo giá gần nhất mà monitor đã lưu; đây không phải giá tick realtime.</div>
</div>
<div id="toast" class="toast"></div>
<script>
let D=null;
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const money=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=n=>Number(n||0).toFixed(1)+'%';
const price=n=>{n=Number(n||0);if(n>=1000)return n.toFixed(2);if(n>=1)return n.toFixed(4);if(n>=.01)return n.toFixed(6);return n.toPrecision(5)};
const dt=x=>{try{return new Date(x).toLocaleString('vi-VN',{hour12:false})}catch(e){return x||'-'}};
const badge=(t,k)=>'<span class="badge '+k+'">'+esc(t)+'</span>';
const pnlClass=n=>Number(n)>=0?'pnlp':'pnln';
const kind=x=>x==='LONG'||x==='BULLISH'?'bull':x==='SHORT'||x==='BEARISH'?'bear':'mix';
function toast(msg){const e=document.getElementById('toast');e.textContent=msg;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),3500)}
async function action(url,msg){toast(msg);document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=true);try{const r=await fetch(url,{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.detail||r.statusText);toast('Hoàn tất');await loadAll()}catch(e){toast('Lỗi: '+e.message)}finally{document.querySelectorAll('.actions .btn').forEach(b=>b.disabled=false)}}
async function loadAll(){try{const r=await fetch('/api/dashboard');if(!r.ok)throw new Error(r.statusText);D=await r.json();renderAll();const ss=D.scan_state||{};const busy=!!ss.running;document.getElementById('statusDot').className='dot'+(busy?' busy':'');document.getElementById('status').textContent=busy?'Scanner đang chạy...':('Agent online • V'+D.version+(D.settings.data_collection_mode?' • DATA COLLECTION MODE':'')+' • quét '+D.settings.scan_interval_min+' phút/lần • monitor '+D.settings.monitor_interval_sec+' giây/lần • '+new Date().toLocaleString('vi-VN'));}catch(e){document.getElementById('status').textContent='Không tải được dashboard: '+e.message}}
function renderAll(){renderCards();renderOverview();renderScanner();renderPositions();renderPerformance();renderHistory();renderNews();renderReports()}
function renderCards(){const a=D.analytics||{},s=D.trade_stats||{};const cards=[
 ['Equity',money(a.equity)+' USDT','Balance + PnL đang mở'],
 ['Paper balance',money(a.balance)+' USDT','PnL đã chốt vào balance'],
 ['PnL đang mở',(a.unrealized_pnl>=0?'+':'')+money(a.unrealized_pnl)+' USDT',D.open_positions.length+' lệnh đang chạy'],
 ['Realized PnL',(a.realized_pnl>=0?'+':'')+money(a.realized_pnl)+' USDT',s.closed+' lệnh đã đóng'],
 ['Win rate',pct(a.win_rate),a.wins+' thắng / '+a.losses+' thua'],
 ['Profit factor',Number(a.profit_factor||0).toFixed(2),'Avg '+Number(a.avg_r||0).toFixed(2)+'R'],
 ['Max drawdown',pct(a.max_drawdown_pct),money(a.max_drawdown_usdt)+' USDT'],
 ['Open risk',money(a.open_risk_usdt)+' USDT',money(a.open_notional)+' USDT notional']
];document.getElementById('cards').innerHTML=cards.map(x=>'<div class="card"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div><div class="sub">'+esc(x[2])+'</div></div>').join('')}
function topTable(xs,side){if(!xs?.length)return '<div class="empty">Chưa có coin đạt ngưỡng.</div>';return '<table><tr><th>Coin</th><th>Score</th><th>Giá</th><th>RSI</th><th>Vol</th><th>OI</th><th>Lý do</th></tr>'+xs.slice(0,8).map(x=>{const sc=side==='LONG'?x.long_score:x.short_score;const rs=side==='LONG'?x.reasons_long:x.reasons_short;return '<tr><td><b>'+esc(x.symbol)+'</b></td><td class="score">'+sc+'</td><td>'+price(x.price)+'</td><td>'+x.rsi_1h+'</td><td>'+Number(x.volume_ratio_1h||0).toFixed(2)+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td><td class="reason">'+esc((rs||[]).slice(0,3).join('; '))+'</td></tr>'}).join('')+'</table>'}
function renderOverview(){const scan=D.scan||{},ss=D.scan_state||{},a=D.analytics||{},ns=D.news_summary||{};document.getElementById('topLong').innerHTML=topTable(scan.top_long,'LONG');document.getElementById('topShort').innerHTML=topTable(scan.top_short,'SHORT');document.getElementById('scanTime').textContent=scan.created_at?'Scan: '+dt(scan.created_at):'Chưa scan';
 document.getElementById('scannerState').innerHTML='<div class="kv"><span>Trạng thái</span><b>'+esc(ss.running?'ĐANG QUÉT':ss.last_error?'LỖI':'SẴN SÀNG')+'</b></div><div class="kv"><span>Lần gần nhất</span><span>'+esc(ss.completed_at?dt(ss.completed_at):'-')+'</span></div><div class="kv"><span>Thời gian quét</span><span>'+esc(ss.duration_sec==null?'-':ss.duration_sec+' giây')+'</span></div><div class="kv"><span>Coin đã quét</span><span>'+Number(scan.symbols_scanned||ss.symbols_scanned||0)+'/'+D.settings.top_n_coins+'</span></div>'+(ss.last_error?'<div class="newsdesc pnln">'+esc(ss.last_error)+'</div>':'');
 const cm=!!D.settings.data_collection_mode;document.getElementById('riskBox').innerHTML='<div class="kv"><span>Chế độ</span><b>'+(cm?'THU THẬP DỮ LIỆU':'BÌNH THƯỜNG')+'</b></div><div class="kv"><span>Risk/lệnh</span><b>'+pct(cm?D.settings.collection_risk_per_trade_pct:D.settings.risk_per_trade_pct)+'</b></div><div class="kv"><span>Max lệnh mở</span><b>'+(cm?D.settings.collection_max_open_trades:D.settings.max_open_trades)+'</b></div><div class="kv"><span>Daily loss guard</span><b>'+(cm?'TẠM BỎ QUA':pct(D.settings.max_daily_loss_pct))+'</b></div><div class="kv"><span>Reward/Risk</span><b>'+Number(D.settings.reward_risk).toFixed(1)+'R</b></div>';
 document.getElementById('newsBox').innerHTML='<div class="kv"><span>Market bias</span><b>'+badge(ns.market_bias||'NO DATA',kind(ns.market_bias))+'</b></div><div class="kv"><span>Market score</span><b>'+Number(ns.market_score||0).toFixed(1)+'</b></div><div class="kv"><span>Risk</span><b>'+esc(ns.risk_level||'-')+'</b></div><div class="kv"><span>High-impact</span><b>'+Number(ns.high_impact||0)+'</b></div>'}
function renderScanner(){if(!D)return;const q=(document.getElementById('coinSearch')?.value||'').toUpperCase(),f=document.getElementById('biasFilter')?.value||'ALL';const xs=(D.scan?.all||[]).filter(x=>(!q||x.symbol.includes(q))&&(f==='ALL'||x.bias===f));if(!xs.length){document.getElementById('scannerTable').innerHTML='<div class="empty">Không có kết quả phù hợp.</div>';return}document.getElementById('scannerTable').innerHTML='<table><tr><th>#</th><th>Coin</th><th>Bias</th><th>LONG</th><th>SHORT</th><th>RSI</th><th>Volume</th><th>OI</th><th>Funding</th><th>ATR</th><th>Lý do mạnh</th></tr>'+xs.map((x,i)=>{const rs=x.bias==='LONG'?x.reasons_long:x.bias==='SHORT'?x.reasons_short:[];return '<tr><td>'+(i+1)+'</td><td><b>'+esc(x.symbol)+'</b><div class="muted small">'+price(x.price)+'</div></td><td>'+badge(x.bias,kind(x.bias))+'</td><td>'+x.long_score+'</td><td>'+x.short_score+'</td><td>'+x.rsi_1h+'</td><td>'+x.volume_ratio_1h+'x</td><td>'+Number(x.oi_change_pct||0).toFixed(2)+'%</td><td>'+(Number(x.funding_rate||0)*100).toFixed(4)+'%</td><td>'+x.atr_pct_1h+'%</td><td class="reason">'+esc((rs||[]).slice(0,4).join('; '))+'</td></tr>'}).join('')+'</table>'}
function renderPositions(){const xs=D.open_positions||[];if(!xs.length){document.getElementById('positionsTable').innerHTML='<div class="empty">Chưa có lệnh paper đang mở.</div>';return}document.getElementById('positionsTable').innerHTML='<table><tr><th>Coin</th><th>Side</th><th>Score</th><th>Entry</th><th>Giá gần nhất</th><th>PnL mở</th><th>R mở</th><th>SL</th><th>TP</th><th>Risk</th><th>Giữ</th><th>Lý do</th></tr>'+xs.map(x=>'<tr><td><b>'+esc(x.symbol)+'</b></td><td>'+badge(x.side,kind(x.side))+'</td><td>'+x.score+'</td><td>'+price(x.entry_price)+'</td><td>'+price(x.market_price)+'</td><td class="'+pnlClass(x.unrealized_pnl)+'">'+(x.unrealized_pnl>=0?'+':'')+money(x.unrealized_pnl)+'</td><td class="'+pnlClass(x.unrealized_r)+'">'+Number(x.unrealized_r||0).toFixed(2)+'R</td><td>'+price(x.stop_loss)+'</td><td>'+price(x.take_profit)+'</td><td>'+money(x.risk_usdt)+'</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td class="reason">'+esc(x.reason_text)+'</td></tr>').join('')+'</table>'}
function renderPerformance(){const a=D.analytics||{},ds=a.daily||[],ss=a.setups||[],sides=a.sides||[];document.getElementById('dailyPerf').innerHTML=ds.length?'<table><tr><th>Ngày</th><th>Lệnh</th><th>WR</th><th>PnL</th><th>Avg R</th></tr>'+[...ds].reverse().map(x=>'<tr><td>'+esc(x.date)+'</td><td>'+x.trades+'</td><td>'+pct(x.win_rate)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+(x.net_pnl>=0?'+':'')+money(x.net_pnl)+'</td><td>'+Number(x.avg_r).toFixed(2)+'R</td></tr>').join('')+'</table>':'<div class="empty">Chưa có dữ liệu.</div>';
 document.getElementById('sidePerf').innerHTML=sides.map(x=>'<div class="kv"><span>'+badge(x.side,kind(x.side))+' '+x.trades+' lệnh</span><span><b>'+pct(x.win_rate)+'</b> • <span class="'+pnlClass(x.net_pnl)+'">'+(x.net_pnl>=0?'+':'')+money(x.net_pnl)+'</span> • '+Number(x.avg_r).toFixed(2)+'R</span></div>').join('');
 document.getElementById('setupPerf').innerHTML=ss.length?'<table><tr><th>Setup</th><th>Lệnh</th><th>Thắng</th><th>Win rate</th><th>Net PnL</th><th>Avg R</th></tr>'+ss.map(x=>'<tr><td><b>'+esc(x.setup)+'</b></td><td>'+x.trades+'</td><td>'+x.wins+'</td><td>'+pct(x.win_rate)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+(x.net_pnl>=0?'+':'')+money(x.net_pnl)+'</td><td>'+Number(x.avg_r).toFixed(2)+'R</td></tr>').join('')+'</table>':'<div class="empty">Chưa đủ lệnh để thống kê setup.</div>'}
function renderHistory(){const xs=[...(D.trades||[])].reverse();if(!xs.length){document.getElementById('historyTable').innerHTML='<div class="empty">Chưa có lệnh đóng.</div>';return}document.getElementById('historyTable').innerHTML='<table><tr><th>ID</th><th>Coin</th><th>Side</th><th>Kết quả</th><th>PnL</th><th>R</th><th>Giữ</th><th>Score</th><th>Lý do vào</th><th>Postmortem</th></tr>'+xs.map(x=>{let loss='';try{loss=JSON.parse(x.loss_analysis||'[]').slice(0,3).join('; ')}catch(e){}return '<tr><td>#'+x.id+'</td><td><b>'+esc(x.symbol)+'</b></td><td>'+badge(x.side,kind(x.side))+'</td><td>'+esc(x.exit_reason)+'</td><td class="'+pnlClass(x.net_pnl)+'">'+(x.net_pnl>=0?'+':'')+money(x.net_pnl)+'</td><td>'+Number(x.r_multiple).toFixed(2)+'R</td><td>'+Math.round(Number(x.holding_minutes||0))+'m</td><td>'+Number(x.score||0).toFixed(1)+'</td><td class="reason">'+esc(x.reason_text)+'</td><td class="reason">'+esc(loss)+'</td></tr>'}).join('')+'</table>'}
function newsItem(n){const sy=(n.symbols||[]).map(s=>badge(s,'blue')).join(' ');return '<div class="newsitem"><div class="newsmeta">'+badge(n.sentiment,kind(n.sentiment))+' '+badge('Impact '+Number(n.impact_score).toFixed(0),Number(n.impact_score)>=75?'bear':'blue')+' '+badge(n.category,'blue')+' <span>'+esc(n.source)+'</span><span>•</span><span>'+dt(n.published_at)+'</span>'+sy+'</div><div class="newstitle"><a href="'+esc(n.url)+'" target="_blank" rel="noopener">'+esc(n.title)+'</a></div>'+(n.summary?'<div class="newsdesc">'+esc(n.summary.slice(0,300))+(n.summary.length>300?'…':'')+'</div>':'')+'<div class="progress"><i style="width:'+Math.min(100,Number(n.impact_score||0))+'%"></i></div></div>'}
function renderNews(){const ns=D.news_summary||{};document.getElementById('newsSummary').innerHTML='<div class="kv"><span>Bias</span><b>'+badge(ns.market_bias||'NO DATA',kind(ns.market_bias))+'</b></div><div class="kv"><span>Score</span><b>'+Number(ns.market_score||0).toFixed(1)+'</b></div><div class="kv"><span>Tin 24h</span><b>'+Number(ns.articles||0)+'</b></div><div class="kv"><span>Bull / Bear / Neutral</span><b>'+(ns.bullish||0)+' / '+(ns.bearish||0)+' / '+(ns.neutral||0)+'</b></div><div class="kv"><span>High impact</span><b>'+Number(ns.high_impact||0)+'</b></div>';const sf=document.getElementById('sentFilter')?.value||'ALL',imp=Number(document.getElementById('impactFilter')?.value||0),q=(document.getElementById('newsSearch')?.value||'').toLowerCase();const xs=(D.news||[]).filter(n=>(sf==='ALL'||n.sentiment===sf)&&Number(n.impact_score)>=imp&&(!q||((n.title+' '+n.summary+' '+(n.symbols||[]).join(' ')).toLowerCase().includes(q))));document.getElementById('newsList').innerHTML=xs.length?xs.map(newsItem).join(''):'<div class="empty">Không có tin phù hợp.</div>'}
function renderReports(){const rs=D.reports||[];document.getElementById('reportsList').innerHTML=rs.length?'<table><tr><th>Ngày</th><th>Lệnh</th><th>WR</th><th>PnL</th><th>PF</th><th>Avg R</th></tr>'+rs.map(r=>'<tr><td><a target="_blank" href="/reports/daily/'+esc(r.report_date)+'/markdown">'+esc(r.report_date)+'</a></td><td>'+r.trades+'</td><td>'+r.win_rate_pct+'%</td><td class="'+pnlClass(r.net_pnl)+'">'+(Number(r.net_pnl)>=0?'+':'')+money(r.net_pnl)+'</td><td>'+r.profit_factor+'</td><td>'+r.avg_r+'</td></tr>').join('')+'</table>':'<div class="empty">Chưa có báo cáo ngày.</div>';const rec=D.recommendations||[];document.getElementById('recommendations').innerHTML=rec.length?rec.map(x=>'<div class="newsitem"><div class="newstitle">'+esc(x.recommendation)+'</div><div class="newsdesc">'+esc(x.evidence)+'</div><div class="newsmeta">'+esc(x.source)+' • '+dt(x.created_at)+'</div></div>').join(''):'<div class="empty">Chưa có đề xuất.</div>'}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active')});
loadAll();setInterval(loadAll,30000);
</script>
</body>
</html>
"""
