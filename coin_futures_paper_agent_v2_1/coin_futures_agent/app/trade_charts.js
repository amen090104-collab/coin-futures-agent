/* V4.3.3 canvas charts: exact exchange-candle arrows, levels and replay.
 * The data source owns timestamp mapping; never move a marker to a nearest
 * candle when its actual interval is absent.
 */
(function (root) {
  "use strict";
  const UP = "#44dfaa", DOWN = "#ff7283", GOLD = "#ffd175", BLUE = "#7cb6ff";
  const states = {coin: null, trade: null};
  const fmt = value => {
    const n = Number(value);
    if (!Number.isFinite(n)) return "-";
    if (Math.abs(n) >= 1000) return n.toFixed(2);
    if (Math.abs(n) >= 1) return n.toFixed(4);
    if (Math.abs(n) >= 0.01) return n.toFixed(6);
    return n.toPrecision(5);
  };
  function candleIndex(candles, timestamp) {
    if (!candles || !candles.length) return null;
    const ms = typeof timestamp === "number" ? timestamp : Date.parse(timestamp);
    if (!Number.isFinite(ms)) return null;
    let lo = 0, hi = candles.length - 1, idx = -1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1;
      if (+candles[m].open_time <= ms) {idx = m; lo = m + 1;} else hi = m - 1;
    }
    return idx >= 0 && ms <= +candles[idx].close_time ? idx : null;
  }
  function arrowsFromOverlays(chart) {
    const all = [];
    for (const overlay of chart.overlays || []) {
      for (const marker of overlay.markers || []) {
        if (marker.candle_index === null || marker.candle_index === undefined) continue;
        all.push({
          ...marker, trade_id: overlay.trade_id || marker.trade_id,
          levels: overlay.levels || {}, overlay
        });
      }
    }
    return all;
  }
  function arrowGeometry(arrow, candle, x, yHigh, yLow, lane) {
    const isEntry = arrow.type === "ENTRY";
    const longSide = arrow.side === "LONG";
    const below = isEntry ? longSide : !longSide;
    const pointY = below ? yLow + 12 + lane * 27 : yHigh - 12 - lane * 27;
    return {x, pointY, below};
  }
  function labelExit(reason) {
    const s = String(reason || "EXIT");
    if (s === "TAKE_PROFIT") return "EXIT TP";
    if (s === "STOP_LOSS") return "EXIT SL";
    if (s === "NEWS_RISK_EXIT") return "EXIT NEWS";
    if (s === "BREAKEVEN_EXIT") return "EXIT BE";
    if (s === "TRAILING_STOP") return "EXIT TRAIL";
    if (s === "TIME_EXIT") return "EXIT TIME";
    return "EXIT " + s.replace(/_/g, " ").slice(0, 12);
  }
  function colorOf(m) {
    return m.type === "ENTRY" ? (m.side === "LONG" ? UP : DOWN) :
      (Number(m.net_pnl) > 0 ? UP : Number(m.net_pnl) < 0 ? DOWN : GOLD);
  }
  function filteredOverlays(state) {
    return (state.chart.overlays || []).filter(o =>
      !state.caseId || String(o.strategy_id) === state.caseId
    );
  }
  function fullBounds(state) {
    const n = (state.chart.candles || []).length;
    if (!n) return {start: 0, end: 0};
    const overlays = filteredOverlays(state);
    const marked = overlays.flatMap(o => (o.markers || []).map(m => m.candle_index))
      .filter(x => Number.isInteger(x));
    if (state.mode === "trade" && marked.length) {
      const first = Math.min(...marked), last = Math.max(...marked);
      return {start: Math.max(0, first - 35), end: Math.min(n - 1, last + 22)};
    }
    if (marked.length) {
      const last = Math.max(...marked);
      const mid = Math.min(n - 1, last + 16);
      return {start: Math.max(0, mid - 145), end: Math.min(n - 1, mid + 24)};
    }
    return {start: Math.max(0, n - 160), end: n - 1};
  }
  function view(state) {
    const count = (state.chart.candles || []).length;
    if (!count) return {start: 0, end: -1};
    const max = state.replaying ? Math.min(count - 1, state.cursor) : count - 1;
    let start = Math.max(0, Math.min(state.start, max));
    let end = Math.max(start, Math.min(state.end, max));
    if (state.replaying && end - start < 60) {
      end = max;
      start = Math.max(0, end - 110);
    }
    return {start, end};
  }
  function roundRect(ctx, x, y, w, h, radius) {
    const r = Math.min(radius, h / 2, w / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }
  function drawArrow(ctx, cx, py, below, color, title, amount) {
    const head = 12, base = below ? py + 17 : py - 17;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, py);
    ctx.lineTo(cx - head, base);
    ctx.lineTo(cx - 5, base);
    ctx.lineTo(cx - 5, base + (below ? 12 : -12));
    ctx.lineTo(cx + 5, base + (below ? 12 : -12));
    ctx.lineTo(cx + 5, base);
    ctx.lineTo(cx + head, base);
    ctx.closePath();
    ctx.fill();
    const caption = title + (amount > 1 ? " (+" + (amount - 1) + ")" : "");
    ctx.font = "bold 12px Segoe UI,Arial";
    const w = Math.min(180, ctx.measureText(caption).width + 16);
    const lx = cx - w / 2, ly = below ? base + 16 : base - 38;
    ctx.fillStyle = "rgba(7,18,33,.94)";
    ctx.strokeStyle = color;
    roundRect(ctx, lx, ly, w, 21, 5);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.fillText(caption, cx, ly + 15);
    return {x: lx - 8, y: Math.min(py, ly) - 8,
            width: w + 16, height: Math.abs(py - ly) + 37};
  }
  function tooltipText(items) {
    return items.map(m =>
      (m.type === "ENTRY" ? "▲ ENTRY" : "▼ " + labelExit(m.exit_reason)) +
      " · " + (m.strategy_id || "-") + " · #" + (m.trade_id || "OPEN") +
      "\n" + (m.event_time || "-") +
      "\n" + m.side + "  " + fmt(m.price) +
      "  | SL " + fmt(m.levels.stop) + " · TP " + fmt(m.levels.target) +
      (m.type === "EXIT" ? "\nPnL " + fmt(m.net_pnl) + " USDT  · " + fmt(m.r_multiple) + "R" : "")
    ).join("\n\n");
  }
  function chartState(mode) {return states[mode];}
  function mount(mode, chart) {
    const id = mode === "coin" ? "coinChart" : "tradeChart";
    const el = typeof document !== "undefined" ? document.getElementById(id) : null;
    if (!el) return;
    const old = states[mode];
    if (old && old.timer) clearInterval(old.timer);
    const state = {
      mode, el, chart: chart || {}, caseId: "",
      showArrows: true, showLevels: true, showPath: true,
      replaying: false, cursor: 0, timer: null, hitboxes: [], tooltip: null,
      dragX: null, dragStart: 0, dragEnd: 0, dragMoved: false
    };
    const b = fullBounds(state);
    state.start = b.start; state.end = b.end;
    states[mode] = state;
    el.onmousemove = evt => mouseMove(mode, evt);
    el.onmouseleave = () => hideTooltip(mode);
    el.onmousedown = evt => {state.dragX = evt.clientX; state.dragStart = state.start;
                                 state.dragEnd = state.end; state.dragMoved = false;};
    el.onmouseup = evt => {
      if (state.dragX === null) return;
      if (!state.dragMoved) clickMarker(mode, evt);
      state.dragX = null;
    };
    el.onclick = () => {}; // click is processed on mouseup only
    el.onwheel = evt => {
      evt.preventDefault();
      zoom(mode, evt.deltaY > 0 ? 1.25 : 0.8);
    };
    draw(mode);
  }
  function mouseMove(mode, evt) {
    const s = states[mode];
    if (!s) return;
    if (s.dragX !== null) {
      const n = (s.chart.candles || []).length;
      const width = Math.max(1, s.el.clientWidth - 110);
      const diff = Math.round((s.dragX - evt.clientX) * Math.max(1, s.dragEnd - s.dragStart) / width);
      const span = s.dragEnd - s.dragStart;
      s.start = Math.max(0, Math.min(Math.max(0, n - span - 1), s.dragStart + diff));
      s.end = Math.min(n - 1, s.start + span);
      s.dragMoved = s.dragMoved || Math.abs(s.dragX - evt.clientX) > 5;
      hideTooltip(mode);
      draw(mode);
      return;
    }
    const rect = s.el.getBoundingClientRect();
    const x = evt.clientX - rect.left, y = evt.clientY - rect.top;
    const items = s.hitboxes.filter(h =>
      x >= h.rect.x && x <= h.rect.x + h.rect.width &&
      y >= h.rect.y && y <= h.rect.y + h.rect.height
    ).flatMap(h => h.items);
    if (!items.length) {hideTooltip(mode); return;}
    if (!s.tooltip) {
      const t = document.createElement("div");
      t.style.cssText = "position:fixed;z-index:200;max-width:350px;pointer-events:none;" +
        "background:#081628;color:#eff5ff;border:1px solid #5c7796;border-radius:9px;" +
        "padding:10px 12px;white-space:pre-line;font:12px/1.5 Segoe UI,Arial;" +
        "box-shadow:0 6px 28px rgba(0,0,0,.5)";
      document.body.appendChild(t);
      s.tooltip = t;
    }
    s.tooltip.textContent = tooltipText(items);
    s.tooltip.style.left = Math.min(evt.clientX + 15, window.innerWidth - 365) + "px";
    s.tooltip.style.top = Math.min(evt.clientY + 15, window.innerHeight - 220) + "px";
    s.tooltip.style.display = "block";
  }
  function hideTooltip(mode) {
    const s = states[mode];
    if (s && s.tooltip) s.tooltip.style.display = "none";
  }
  function clickMarker(mode, evt) {
    const s = states[mode]; if (!s) return;
    const rect = s.el.getBoundingClientRect();
    const x = evt.clientX - rect.left, y = evt.clientY - rect.top;
    const target = s.hitboxes.find(h => x >= h.rect.x && x <= h.rect.x + h.rect.width &&
      y >= h.rect.y && y <= h.rect.y + h.rect.height);
    if (target && mode === "coin") {
      const marked = target.items.find(m => m.trade_id != null);
      if (marked && typeof window !== "undefined" && typeof window.openTrade === "function") {
        window.openTrade(Number(marked.trade_id));
      }
    }
  }
  function options(mode) {
    const s = states[mode]; if (!s) return;
    const prefix = mode === "coin" ? "coin" : "trade";
    const chk = (id, fallback) => {
      const x = document.getElementById(prefix + id);
      return x ? x.checked : fallback;
    };
    s.showArrows = chk("ShowArrows", true);
    s.showLevels = chk("ShowLevels", true);
    s.showPath = chk("ShowPath", true);
    if (mode === "coin") {
      const select = document.getElementById("coinCaseFilter");
      s.caseId = select ? select.value : "";
    }
    draw(mode);
  }
  function reset(mode) {
    const s = states[mode]; if (!s) return;
    const b = fullBounds(s); s.start = b.start; s.end = b.end;
    s.replaying = false; if (s.timer) clearInterval(s.timer); s.timer = null;
    draw(mode);
  }
  function zoom(mode, factor) {
    const s = states[mode]; if (!s) return;
    const n = (s.chart.candles || []).length;
    if (!n) return;
    const center = (s.start + s.end) / 2;
    const span = Math.min(n - 1, Math.max(24, Math.round((s.end - s.start) * factor)));
    s.start = Math.max(0, Math.min(n - 1 - span, Math.round(center - span / 2)));
    s.end = Math.min(n - 1, s.start + span);
    draw(mode);
  }
  function replayStart() {
    const s = states.trade;
    if (!s || !(s.chart.candles || []).length) return;
    if (s.timer) clearInterval(s.timer);
    s.replaying = true;
    const first = s.chart.entry_index;
    s.cursor = Number.isInteger(first) ? Math.max(0, first - 30) : Math.max(0, s.start);
    const speed = Number(document.getElementById("tradeReplaySpeed")?.value || 1);
    const ms = Math.max(60, 320 / speed);
    draw("trade");
    s.timer = setInterval(() => stepReplay(1), ms);
  }
  function replayPause() {
    const s = states.trade; if (!s) return;
    if (s.timer) clearInterval(s.timer);
    s.timer = null;
    const label = document.getElementById("tradeReplayStatus");
    if (label) label.textContent += " · PAUSED";
  }
  function stepReplay(amount) {
    const s = states.trade; if (!s) return;
    if (!s.replaying) {
      s.replaying = true;
      s.cursor = Math.max(0, (Number.isInteger(s.chart.entry_index) ? s.chart.entry_index : s.start) - 30);
    }
    s.cursor = Math.min((s.chart.candles || []).length - 1, Math.max(0, s.cursor + amount));
    if (s.cursor >= s.chart.candles.length - 1) replayPause();
    const span = Math.max(90, s.end - s.start);
    if (s.cursor > s.end - 10) {
      s.end = Math.min(s.chart.candles.length - 1, s.cursor + 10);
      s.start = Math.max(0, s.end - span);
    }
    draw("trade");
  }
  function replayReset() {
    const s = states.trade; if (!s) return;
    replayPause(); s.replaying = false;
    const b = fullBounds(s); s.start = b.start; s.end = b.end; draw("trade");
  }
  function draw(mode) {
    const s = states[mode]; if (!s) return;
    const canvas = s.el;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(320, rect.width), h = Math.max(240, rect.height);
    const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(w * pixelRatio); canvas.height = Math.round(h * pixelRatio);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#071426"; ctx.fillRect(0, 0, w, h);
    const candles = s.chart.candles || [];
    const bounds = view(s);
    const {start,end} = bounds;
    s.hitboxes = [];
    if (end < start || !candles.length) {
      ctx.fillStyle = GOLD;ctx.font="15px Segoe UI,Arial";
      ctx.fillText(s.chart.warning || "Không có dữ liệu nến cho khung này", 20, 35);
      return;
    }
    const pad = {left:72,right:30,top:55,bottom:35};
    const left = pad.left, right = w - pad.right, top = pad.top, bottom = h - pad.bottom;
    const shown = candles.slice(start,end+1);
    const extras = filteredOverlays(s).filter(o => {
      const a=o.entry_index, b=o.exit_index;
      return (Number.isInteger(a) && a<=end && a>=start) ||
             (Number.isInteger(b) && b<=end && b>=start);
    });
    let low = Math.min(...shown.map(c=>+c.low)), high = Math.max(...shown.map(c=>+c.high));
    if (s.showLevels) {
      for (const o of extras.slice(-8)) {
        for (const z of ["stop","target"]) {
          const p=+o.levels?.[z];
          if (Number.isFinite(p)) {low=Math.min(low,p);high=Math.max(high,p);}
        }
      }
    }
    const range = Math.max(high-low, Math.max(Math.abs(high),1)*0.0004);
    low -= range*.16; high += range*.16;
    const xof = i => left + (i-start+.5)*(right-left)/Math.max(1,end-start+1);
    const yof = p => bottom - (+p-low)/(high-low)*(bottom-top);
    ctx.font="11px Segoe UI,Arial";ctx.strokeStyle="#1e3450";
    ctx.fillStyle="#94aac6";
    for (let j=0;j<=5;j++) {
      const y=top+(bottom-top)*j/5, price=high-(high-low)*j/5;
      ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
      ctx.textAlign="left";ctx.fillText(fmt(price),6,y+4);
    }
    const candleWidth=Math.min(13,Math.max(1,(right-left)/(end-start+1)*.62));
    shown.forEach((c,j)=>{
      const i=start+j, cx=xof(i), up=(+c.close)>= (+c.open);
      const color=up?"#38d5a0":"#f56578";
      ctx.strokeStyle=color;ctx.lineWidth=Math.max(1,Math.min(2,candleWidth/4));
      ctx.beginPath();ctx.moveTo(cx,yof(c.high));ctx.lineTo(cx,yof(c.low));ctx.stroke();
      ctx.fillStyle=color;
      const y1=yof(c.open), y2=yof(c.close);
      ctx.fillRect(cx-candleWidth/2,Math.min(y1,y2),candleWidth,Math.max(1,Math.abs(y2-y1)));
    });
    const step=Math.max(1,Math.round((end-start)/6));
    for (let i=start;i<=end;i+=step) {
      const time=new Date(+candles[i].open_time);
      ctx.fillStyle="#90a6c4";ctx.textAlign="center";
      ctx.fillText(time.toLocaleString("vi-VN",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}),xof(i),h-10);
    }
    ctx.textAlign="left";
    if (s.showLevels || s.showPath) {
      extras.forEach(o=>{
        const a=o.entry_index, b=o.exit_index;
        const aVisible=Number.isInteger(a)&&a>=start&&a<=end;
        const bVisible=Number.isInteger(b)&&b>=start&&b<=end&&(!s.replaying||b<=s.cursor);
        const aPx=+o.levels?.entry, bPx=+o.levels?.exit;
        if (s.showLevels && aVisible && Number.isFinite(aPx)) {
          const xs=xof(a), xe=bVisible?xof(b):right;
          for(const [type,p,col] of [["SL",o.levels?.stop,DOWN],["TP",o.levels?.target,UP]]) {
            if(!Number.isFinite(+p)) continue;
            ctx.strokeStyle=col;ctx.lineWidth=1.6;ctx.setLineDash([6,6]);
            ctx.beginPath();ctx.moveTo(xs,yof(p));ctx.lineTo(xe,yof(p));ctx.stroke();
            ctx.setLineDash([]);
            if(mode==="trade"){ctx.fillStyle=col;ctx.font="bold 12px Segoe UI,Arial";
              ctx.fillText(type+" "+fmt(p),xs+6,yof(p)-5);}
          }
        }
        if (s.showPath && aVisible && bVisible && Number.isFinite(aPx) && Number.isFinite(bPx)) {
          ctx.strokeStyle=Number(o.markers?.find(m=>m.type==="EXIT")?.net_pnl)>=0?UP:DOWN;
          ctx.lineWidth=2.4;
          ctx.beginPath();ctx.moveTo(xof(a),yof(aPx));ctx.lineTo(xof(b),yof(bPx));ctx.stroke();
        }
      });
    }
    if(s.showArrows){
      const markers=arrowsFromOverlays({overlays: extras})
        .filter(m=>m.candle_index>=start && m.candle_index<=end &&
             (!s.replaying||m.candle_index<=s.cursor));
      const groups=new Map();
      for(const marker of markers){
        const key=marker.candle_index+":"+(marker.type==="ENTRY"?(marker.side==="LONG"?"below":"above"):(marker.side==="LONG"?"above":"below"));
        if(!groups.has(key))groups.set(key,[]);
        groups.get(key).push(marker);
      }
      groups.forEach(items=>{
        const first=items[0], index=first.candle_index;
        const candle=candles[index], cx=xof(index);
        const below=first.type==="ENTRY"?first.side==="LONG":first.side!=="LONG";
        const lane=Math.max(0,Math.min(3,groups.size>20?0:0));
        const geometry=arrowGeometry(first,candle,cx,yof(candle.high),yof(candle.low),lane);
        const title=first.type==="ENTRY"
          ? (first.side==="LONG"?"▲ LONG ENTRY":"▼ SHORT ENTRY")
          : labelExit(first.exit_reason);
        const hit=drawArrow(ctx,cx,geometry.pointY,geometry.below,colorOf(first),title,items.length);
        s.hitboxes.push({rect:hit,items});
      });
    }
    ctx.fillStyle="#c6d8ef";ctx.font="bold 12px Segoe UI,Arial";ctx.textAlign="left";
    const chartLabel=(s.chart.interval || "") + "  •  " + shown.length + " candles" +
      (s.caseId?"  •  "+s.caseId:"") + (s.replaying?"  •  REPLAY":"");
    ctx.fillText(chartLabel,left,25);
    if(s.chart.warning){ctx.fillStyle=GOLD;ctx.fillText(s.chart.warning,left,43);}
    if(mode==="trade"){
      const status=document.getElementById("tradeReplayStatus");
      if(status){
        const at=s.replaying ? candles[Math.min(s.cursor,candles.length-1)]?.close_time : null;
        status.textContent=s.replaying
          ? "Replay: "+(at?new Date(at).toLocaleString("vi-VN"):"-")+" · nến "+
            (s.cursor+1)+"/"+candles.length
          : "FULL CHART · Kéo ngang để xem lịch sử, lăn chuột để zoom";
      }
      const events=document.querySelectorAll("#tradeJournal [data-event-at]");
      events.forEach(el=>{
        const t=Date.parse(el.getAttribute("data-event-at"));
        const visible=!s.replaying || (Number.isFinite(t) &&
          t <= +candles[Math.max(0,Math.min(s.cursor,candles.length-1))]?.close_time);
        el.style.opacity=visible?"1":".32";
      });
    }
  }
  const api={mount,render:draw,options,reset,zoom,replayStart,replayPause,
             stepReplay,replayReset,candleIndex,arrowsFromOverlays,arrowGeometry,
             chartState};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root)root.TradeCharts=api;
})(typeof window!=="undefined"?window:null);
