"""Lightweight Paper A-F and Reverse research dashboard. No candle/replay/entry-point UI."""
DASHBOARD_HTML_LEAN = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Bot · 6 Case Paper + Reverse</title>
<style>
:root{color-scheme:dark;--bg:#09131f;--panel:#132338;--border:#294058;--text:#e6f0f9;--muted:#9db0c4;--accent:#67b9f5;--good:#62dba5;--bad:#ff999b}
*{box-sizing:border-box}body{font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:var(--text);background:var(--bg);margin:0}
header{padding:18px max(20px,3vw);border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}
h1{font-size:21px;margin:0}h2{font-size:18px;margin:0 0 12px}h3{font-size:14px;margin:0 0 10px}
small,.muted{color:var(--muted)}main{max-width:1400px;margin:auto;padding:20px}
nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}
button{border:1px solid var(--border);background:var(--panel);color:var(--text);border-radius:8px;padding:8px 12px;cursor:pointer;font:inherit}
button:hover,button.active{border-color:var(--accent);color:#fff}button:disabled{opacity:.55;cursor:wait}
.view{display:none}.view.active{display:block}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.panel,.case{border:1px solid var(--border);border-radius:11px;background:var(--panel);padding:16px;min-width:0}
.case .name{font-weight:700}.case .money{font-size:25px;font-weight:700;margin:5px 0}.good{color:var(--good)}.bad{color:var(--bad)}
.stats{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px}
.toolbar{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:14px}
.tablewrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:10px;border-bottom:1px solid var(--border);white-space:nowrap}th{color:var(--muted);font-weight:600}
.notice{border:1px solid #8c7042;background:#2a251d;border-radius:9px;padding:11px;margin:12px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:12px}
#feedback{font-size:13px;color:var(--muted)}.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:10px 0 16px}
.metric{background:#0c1a2a;border:1px solid var(--border);border-radius:8px;padding:12px}
.metric strong{display:block;font-size:19px}footer{font-size:12px;color:var(--muted);padding:18px 0}
@media(max-width:850px){.grid,.kv{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.grid,.kv{grid-template-columns:1fr}h1{font-size:17px}}
</style></head>
<body>
<header><div><h1>Trading Bot · 6 Case Paper + Reverse Research</h1><small>Chỉ mô phỏng · Không giao dịch tiền thật · Không biểu đồ nến</small></div>
<div class="toolbar"><span id="build">Đang kiểm tra phiên bản...</span><button type="button" id="refresh">Làm mới</button></div></header>
<main>
<div class="notice" id="warning" style="display:none"></div>
<nav aria-label="Các khu vực">
<button type="button" class="active" data-tab="overview">6 Case Paper</button>
<button type="button" data-tab="scanner">Quét tín hiệu</button>

<button type="button" data-tab="history">Lịch sử / Báo cáo</button>
<button type="button" data-tab="system">Hệ thống</button></nav>
<section id="overview" class="view active"><h2>Hiệu suất mô phỏng A–F</h2>
<div class="toolbar"><button type="button" data-action="/scan/run">Quét Futures</button><button type="button" data-action="/paper/monitor">Kiểm tra lệnh</button><span id="updated" class="muted"></span></div>
<div class="grid" id="cases">Đang tải...</div>
<div class="panel" style="margin-top:14px"><h3>Lệnh Paper đang mở</h3><div class="tablewrap" id="positions"></div></div></section>
<section id="scanner" class="view"><h2>Tín hiệu Futures</h2><p class="muted">Score là đầu vào để 6 case thử nghiệm; không phải dự báo xác suất thắng.</p>
<div class="toolbar"><button type="button" data-action="/scan/run">Quét lại</button><span id="scanSummary"></span></div>
<div class="panel tablewrap" id="signals"></div></section>
<section id="history" class="view"><h2>Lịch sử và báo cáo</h2><p class="muted">Thông tin lệnh dạng bảng; không tải hình nến hoặc phần phát lại điểm khớp và thoát lệnh.</p>
<div class="notice" id="localHistoryInfo">Tự lưu trên máy: reports/YYYY-MM-DD/trade-history.csv và .json · GitHub: tắt</div>
<div class="panel"><h3>Giao dịch đã đóng gần đây</h3><div class="tablewrap" id="trades"></div></div>
<div class="panel" style="margin-top:12px"><h3>Báo cáo gần đây</h3><div class="toolbar"><button type="button" data-action="/reports/recover/yesterday">Tạo bù báo cáo hôm qua</button></div><div id="reports"></div></div></section>
<section id="system" class="view"><h2>Tình trạng hệ thống</h2>
<div class="toolbar"><button type="button" data-action="/system/backup">Sao lưu database</button><span id="feedback"></span></div>
<div class="kv" id="systemMetrics"></div><div class="panel"><h3>Tác vụ và tình trạng</h3><div class="tablewrap" id="jobs"></div></div>
<p class="muted">Trading Bot chỉ chạy 6 Case Paper. Reverse Research là một chương trình riêng chạy song song. Kết quả nằm trong reverse_research_data/latest.json trên ổ đĩa máy tính.</p>
<p class="muted">Cập nhật mã bằng update.bat trên máy tính, không có chức năng phát lệnh thật.</p></section>
<footer>Dữ liệu thắng/thua từ tài khoản Paper; không suy ra hiệu quả giao dịch thực. Dữ liệu cũ và cấu hình A–F được giữ nguyên.</footer>
</main>
<script>
'use strict';
let state=null, activeTab='overview';
const el=id=>document.getElementById(id);
const esc=x=>String(x===null||x===undefined?'—':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(x,d=2)=>Number.isFinite(Number(x))?Number(x).toLocaleString('vi-VN',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
const money=x=>'<span class="'+(Number(x)>0?'good':Number(x)<0?'bad':'')+'">'+(Number(x)>0?'+':'')+number(x)+' USDT</span>';
const tab=(id)=>{activeTab=id;document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));/* Reverse research now runs in an independent process. */};
function table(cols,rows){return '<table><thead><tr>'+cols.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+ (rows.length?rows.join(''):'<tr><td colspan="'+cols.length+'" class="muted">Chưa có dữ liệu.</td></tr>')+'</tbody></table>'}
function render(){
 if(!state)return;const d=state;
 el('build').textContent=esc((d.build||{}).version||'V5')+' · PAPER/SHADOW';
 el('updated').textContent='Cập nhật: '+new Date().toLocaleTimeString('vi-VN');
 const warnings=[];if((d.missing_case_ids||[]).length)warnings.push('Thiếu cấu hình: '+d.missing_case_ids.join(', ')+'. Không tự tạo hoặc ghi đè Case E/F.');
 if((d.legacy_open_positions||0)>0)warnings.push('Còn '+d.legacy_open_positions+' lệnh đang mở từ case ngoài A–F. Hệ thống vẫn giám sát các lệnh cũ.');
 if(!d.strategy_battle_enabled)warnings.push('STRATEGY_BATTLE_ENABLED=false: cần bật khi vận hành 6 Case.');
 el('warning').textContent=warnings.join(' ');el('warning').style.display=warnings.length?'block':'none';
 const cases=d.cases||[];
 el('cases').innerHTML=cases.map(c=>{
  const a=c.analytics||{};return '<article class="case"><div class="name">'+esc(c.short_name||c.strategy_id)+' · '+esc(c.name||c.strategy_id)+'</div>'+
   '<div class="money">'+money(a.realized_pnl)+'</div><div class="stats"><span>Đóng '+esc(a.closed||0)+'</span><span>Winrate '+number(a.win_rate,1)+'%</span><span>PF '+number(a.profit_factor)+'</span><span>Expectancy '+number(a.expectancy_r,3)+'R</span></div>'+
   '<small>'+(c.enabled?'Đang mô phỏng':'Đã tắt mở lệnh mới')+'</small></article>'
 }).join('')||'<div class="notice">Chưa có tài khoản Paper A–F.</div>';
 el('positions').innerHTML=table(['Case','Coin','Hướng','Giá vào','SL','TP','PnL tạm tính'],(d.open_positions||[]).slice(0,60).map(p=>
  '<tr><td>'+esc(p.strategy_id)+'</td><td>'+esc(p.symbol)+'</td><td>'+esc(p.side)+'</td><td>'+number(p.entry_price,5)+'</td><td>'+number(p.stop_loss,5)+'</td><td>'+number(p.take_profit,5)+'</td><td>'+money(p.unrealized_pnl||0)+'</td></tr>'));
 const scan=d.scan||{},list=scan.all||[];
 el('scanSummary').textContent=esc(scan.created_at||'Chưa quét')+' · '+esc(scan.symbols_scanned||list.length)+' coin';
 el('signals').innerHTML=table(['Coin','Hướng nguồn','Score LONG','Score SHORT','RSI 1h','ATR 1h %'],list.slice(0,60).map(s=>'<tr><td>'+esc(s.symbol)+'</td><td>'+esc(s.bias)+'</td><td>'+number(s.long_score,1)+'</td><td>'+number(s.short_score,1)+'</td><td>'+number(s.rsi_1h,1)+'</td><td>'+number(s.atr_pct_1h,2)+'</td></tr>'));
 el('trades').innerHTML=table(['Đóng lúc','Case','Coin','Hướng','PnL','R','Lý do thoát'],(d.trades||[]).slice().reverse().slice(0,70).map(t=>
  '<tr><td>'+esc(t.closed_at)+'</td><td>'+esc(t.strategy_id)+'</td><td>'+esc(t.symbol)+'</td><td>'+esc(t.side)+'</td><td>'+money(t.net_pnl)+'</td><td>'+number(t.r_multiple,2)+'</td><td>'+esc(t.exit_reason)+'</td></tr>'));
 el('reports').innerHTML=table(['Ngày','Tạo lúc'],(d.reports||[]).slice(0,14).map(x=>'<tr><td>'+esc(x.report_date)+'</td><td>'+esc(x.created_at)+'</td></tr>'));
 const system=d.system||{},net=system.network||{},backup=system.last_backup||{};
 el('systemMetrics').innerHTML='<div class="metric">Kết nối<strong>'+esc(net.status||'UNKNOWN')+'</strong></div><div class="metric">Tác vụ<strong>'+esc((system.scheduler||{}).status||'UNKNOWN')+'</strong></div><div class="metric">Sao lưu<strong>'+esc(backup.status||'Xem log')+'</strong></div>';
 const jobs=system.jobs||{};
 el('jobs').innerHTML=table(['Tác vụ','Trạng thái','Cập nhật'],Object.entries(jobs).map(([k,v])=>{v=v||{};return '<tr><td>'+esc(k)+'</td><td>'+esc(v.status)+'</td><td>'+esc(v.at||v.last_run)+'</td></tr>'}));
}
async function load(){
 try{const r=await fetch('/api/lean',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);state=await r.json();render();}
 catch(e){el('warning').textContent='Không đọc được dữ liệu Agent: '+e.message;el('warning').style.display='block';}
}
async function post(path,button){
 button.disabled=true;el('feedback').textContent='Đang xử lý '+path;
 try{const r=await fetch(path,{method:'POST'});if(!r.ok)throw new Error('HTTP '+r.status);el('feedback').textContent='Đã gọi '+path+'; chờ tác vụ hoàn thành. Đang làm mới...';await load();/* Research is an independent process. */}
 catch(e){el('feedback').textContent='Tác vụ bị lỗi: '+e.message;}finally{button.disabled=false}
}
document.querySelectorAll('[data-tab]').forEach(x=>x.addEventListener('click',()=>tab(x.dataset.tab)));
document.querySelectorAll('[data-action]').forEach(x=>x.addEventListener('click',()=>post(x.dataset.action,x)));
el('refresh').addEventListener('click',()=>load());
load();setInterval(()=>{load();/* No in-process Reverse refresh. */},45000);
</script></body></html>"""
