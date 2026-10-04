from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .config import settings


def _ctx(trade: dict[str, Any]) -> dict[str, Any]:
    x = trade.get("entry_context", {})
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return {}
    return x or {}


def _codes(trade: dict[str, Any]) -> list[str]:
    x = trade.get("reason_codes", [])
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return []
    return x or []


def analyze_loss(trade: dict[str, Any]) -> tuple[list[str], list[str]]:
    if float(trade.get("net_pnl", 0)) >= 0:
        return [], []

    ctx = _ctx(trade)
    side = trade["side"]
    causes: list[str] = []
    fixes: list[str] = []

    btc = ctx.get("btc_regime")
    if (side == "LONG" and btc == "BEARISH") or (side == "SHORT" and btc == "BULLISH"):
        causes.append("Vào lệnh ngược BTC market regime.")
        fixes.append("Chặn lệnh ngược BTC regime hoặc yêu cầu score cao hơn ít nhất 8 điểm khi đi ngược.")

    vr = float(ctx.get("volume_ratio_1h") or 0)
    if vr < 1.10:
        causes.append(f"Volume xác nhận yếu (1h volume ratio {vr:.2f}x).")
        fixes.append("Thử yêu cầu volume ratio >= 1.10-1.20 cho các setup breakout/momentum.")

    oi = float(ctx.get("oi_change_pct") or 0)
    if oi < 0.5:
        causes.append(f"Open Interest không xác nhận rõ (OI {oi:+.2f}%).")
        fixes.append("Nâng điều kiện OI cho setup momentum; không bắt buộc OI với setup pullback/range.")

    funding = float(ctx.get("funding_rate") or 0)
    if side == "LONG" and funding > 0.0008:
        causes.append("Funding dương cao: phía Long có dấu hiệu đông.")
        fixes.append("Giảm điểm hoặc bỏ Long khi funding vượt ngưỡng crowding.")
    if side == "SHORT" and funding < -0.0008:
        causes.append("Funding âm sâu: phía Short có dấu hiệu đông.")
        fixes.append("Giảm điểm hoặc bỏ Short khi funding âm quá sâu.")

    atr_pct = float(ctx.get("atr_pct_1h") or 0)
    if atr_pct > 4.5:
        causes.append(f"Biến động cao (ATR 1h {atr_pct:.2f}%), dễ quét SL.")
        fixes.append("Giảm size hoặc bỏ setup khi ATR quá cao; có thể dùng stop rộng hơn nhưng giữ nguyên % rủi ro.")

    ext = float(ctx.get("distance_ema20_atr") or 0)
    if ext > 1.25:
        causes.append(f"Entry bị kéo xa EMA20 ({ext:.2f} ATR), có nguy cơ đuổi giá.")
        fixes.append("Chờ pullback/retest thay vì market-entry khi giá cách EMA20 > 1.25 ATR.")

    news = ctx.get("news_context") or {}
    news_bias = news.get("bias")
    news_score = float(news.get("score") or 0)
    high_news = int(news.get("high_impact") or 0)
    if side == "LONG" and news_bias == "BEARISH" and news_score <= -20:
        causes.append(f"Tin tức 24h nghiêng BEARISH ({news_score:+.1f}) trong lúc agent vào LONG.")
        fixes.append("Backtest thêm news-conflict filter: giảm điểm hoặc chờ xác nhận khi tin 24h đi ngược hướng lệnh.")
    if side == "SHORT" and news_bias == "BULLISH" and news_score >= 20:
        causes.append(f"Tin tức 24h nghiêng BULLISH ({news_score:+.1f}) trong lúc agent vào SHORT.")
        fixes.append("Backtest thêm news-conflict filter: giảm điểm hoặc chờ xác nhận khi tin 24h đi ngược hướng lệnh.")
    if high_news >= 2:
        causes.append(f"Có {high_news} tin high-impact liên quan coin trong 24h, biến động sự kiện có thể làm setup kỹ thuật kém ổn định.")
        fixes.append("Backtest giảm size hoặc tạm tránh entry trong cửa sổ có nhiều tin high-impact liên quan trực tiếp coin.")

    score = float(trade.get("score") or 0)
    if score < settings.score_threshold + 5:
        causes.append(f"Score chỉ vừa qua ngưỡng ({score:.1f}).")
        fixes.append("So sánh hiệu suất score 75-79 với >=80; nếu nhóm thấp kém rõ rệt thì nâng ngưỡng.")

    mfe_r = float(trade.get("mfe_r") or 0)
    if mfe_r >= 1.0 and trade.get("exit_reason") == "STOP_LOSS":
        causes.append(f"Lệnh từng lời {mfe_r:.2f}R nhưng cuối cùng quay lại SL.")
        fixes.append("Backtest phương án dời SL về hòa vốn sau +1R hoặc chốt một phần ở +1R.")

    codes = set(_codes(trade))
    if ("BREAKOUT_1H" in codes or "BREAKDOWN_1H" in codes) and float(trade.get("holding_minutes") or 0) < 240:
        causes.append("Setup breakout/breakdown thất bại nhanh, có thể là false break.")
        fixes.append("Backtest yêu cầu retest hoặc thêm 1 nến xác nhận sau breakout trước khi vào.")

    if not causes:
        causes.append("Không thấy lỗi điều kiện nổi bật; có thể là biến động ngẫu nhiên bình thường của chiến lược.")
        fixes.append("Không sửa rule chỉ vì một lệnh thua; chờ tối thiểu 20-30 lệnh cùng loại trước khi thay đổi.")

    return causes, list(dict.fromkeys(fixes))


def aggregate_recommendations(trades: list[dict[str, Any]]) -> list[dict[str, str]]:
    if len(trades) < 10:
        return [{
            "recommendation": "Chưa đủ mẫu để thay rule.",
            "evidence": f"Mới có {len(trades)} lệnh đóng; nên có ít nhất 20-30 lệnh trước khi kết luận.",
        }]

    recs: list[dict[str, str]] = []
    by_side: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_side[t["side"]].append(t)

    for side, xs in by_side.items():
        if len(xs) >= 8:
            net = sum(float(t["net_pnl"]) for t in xs)
            wr = sum(float(t["net_pnl"]) > 0 for t in xs) / len(xs) * 100
            if net < 0 and wr < 40:
                recs.append({
                    "recommendation": f"Tạm nâng ngưỡng {side} thêm 5 điểm trong backtest/shadow test.",
                    "evidence": f"{side}: {len(xs)} lệnh, win rate {wr:.1f}%, net PnL {net:.2f} USDT.",
                })

    loss_causes = Counter()
    for t in trades:
        if float(t["net_pnl"]) < 0:
            causes, _ = analyze_loss(t)
            for c in causes:
                if "Volume xác nhận yếu" in c:
                    loss_causes["LOW_VOLUME"] += 1
                if "Open Interest không xác nhận" in c:
                    loss_causes["WEAK_OI"] += 1
                if "ngược BTC" in c:
                    loss_causes["BTC_CONFLICT"] += 1
                if "đuổi giá" in c:
                    loss_causes["CHASE"] += 1
                if "false break" in c:
                    loss_causes["FALSE_BREAK"] += 1
                if "lời" in c and "quay lại SL" in c:
                    loss_causes["GIVEBACK"] += 1

    losses = max(1, sum(float(t["net_pnl"]) < 0 for t in trades))
    if loss_causes["LOW_VOLUME"] / losses >= 0.35:
        recs.append({
            "recommendation": "Backtest tăng MIN_VOLUME_RATIO lên 1.10 hoặc 1.20.",
            "evidence": f"{loss_causes['LOW_VOLUME']}/{losses} lệnh thua có volume yếu.",
        })
    if loss_causes["WEAK_OI"] / losses >= 0.35:
        recs.append({
            "recommendation": "Backtest yêu cầu OI change >= 0.5% cho setup momentum.",
            "evidence": f"{loss_causes['WEAK_OI']}/{losses} lệnh thua thiếu OI xác nhận.",
        })
    if loss_causes["BTC_CONFLICT"] >= 2:
        recs.append({
            "recommendation": "Backtest chặn hoàn toàn lệnh đi ngược BTC regime.",
            "evidence": f"Có {loss_causes['BTC_CONFLICT']} lệnh thua đi ngược BTC regime.",
        })
    if loss_causes["CHASE"] >= 2:
        recs.append({
            "recommendation": "Backtest quy tắc không vào khi giá cách EMA20 > 1.25 ATR; chờ retest.",
            "evidence": f"Có {loss_causes['CHASE']} lệnh thua mang dấu hiệu đuổi giá.",
        })
    if loss_causes["FALSE_BREAK"] >= 2:
        recs.append({
            "recommendation": "Backtest thêm retest/1 nến xác nhận cho breakout.",
            "evidence": f"Có {loss_causes['FALSE_BREAK']} breakout thua nhanh.",
        })
    if loss_causes["GIVEBACK"] >= 2:
        recs.append({
            "recommendation": "Backtest dời SL hòa vốn hoặc chốt một phần khi đạt +1R.",
            "evidence": f"Có {loss_causes['GIVEBACK']} lệnh từng >= +1R nhưng đóng lỗ.",
        })

    return recs[:8] or [{
        "recommendation": "Giữ nguyên rule hiện tại và tiếp tục thu thập mẫu.",
        "evidence": "Chưa có mẫu lỗi lặp lại đủ mạnh để đề xuất chỉnh rule.",
    }]
