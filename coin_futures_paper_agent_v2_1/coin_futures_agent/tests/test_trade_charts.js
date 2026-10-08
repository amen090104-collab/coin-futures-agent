"use strict";
const assert = require("node:assert/strict");
const chart = require("../app/trade_charts.js");

const bars = [
  {open_time: 1000, close_time: 1999},
  {open_time: 2000, close_time: 2999},
  {open_time: 3000, close_time: 3999}
];
assert.equal(chart.candleIndex(bars, 1000), 0);
assert.equal(chart.candleIndex(bars, 1999), 0);
assert.equal(chart.candleIndex(bars, 2000), 1);
assert.equal(chart.candleIndex(bars, 2500), 1);
assert.equal(chart.candleIndex(bars, 4000), null);
const markers = chart.arrowsFromOverlays({
  overlays: [{
    trade_id: 11, strategy_id: "BASE_RR1",
    levels: {entry: 100, stop: 98, target: 102},
    markers: [
      {type: "ENTRY", candle_index: 0, side: "LONG", price: 100},
      {type: "EXIT", candle_index: 2, side: "LONG", price: 102,
       exit_reason: "TAKE_PROFIT", net_pnl: 10}
    ]
  }]
});
assert.equal(markers.length, 2);
assert.equal(markers[0].trade_id, 11);
assert.equal(markers[1].candle_index, 2);
assert.equal(chart.arrowGeometry(markers[0], {}, 90, 50, 140, 0).below, true);
assert.equal(chart.arrowGeometry(markers[1], {}, 90, 50, 140, 0).below, false);
console.log("TradeCharts marker and candle-alignment tests passed");
