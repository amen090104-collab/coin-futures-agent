"""Opt-in public historical data smoke. No agent DB, .env output, orders or model training."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from .rei_v3_market import FuturesHistory, HistoryError
from .rei_v3_store import init
from .reverse_intelligence_research import timestamp

DEFAULT_CASES = (("BTCUSDT", "2025-11-20T04:17:00Z", "1h"),
                 ("ETHUSDT", "2026-10-08T12:17:00Z", "15m"),
                 ("BTCUSDT", "2026-10-19T08:17:00Z", "4h"))


async def smoke(db, cases=DEFAULT_CASES, *, history=None):
    owned = history is None
    history = history or FuturesHistory(db)
    results = []
    try:
        for symbol, at, interval in cases:
            observed = timestamp(at)
            result = {"symbol": symbol, "feature_asof_utc": at, "interval": interval}
            try:
                bars, proof = await history.bars(symbol, interval, observed)
                result.update(status="VERIFIED", completed_bars=len(bars),
                              max_close_ms=int(bars.iloc[-1].close_time), provenance=proof)
            except HistoryError as exc:
                result.update(status="UNVERIFIED", reason=str(exc))
            results.append(result)
    finally:
        if owned:
            await history.close()
    verified = sum(r["status"] == "VERIFIED" for r in results)
    return {"mode": "PUBLIC_HISTORY_ONLY", "network_attempted": True, "cases": results,
            "verified_windows": verified, "attempted_windows": len(results),
            "status": "VERIFIED" if verified == len(results) else "PARTIAL" if verified else "BLOCKED",
            "requests": history.http.events,
            "release_market_evidence": verified == len(results),
            "model_or_profitability_validated": False,
            "pending": [] if verified == len(results) else ["Chạy lại smoke trên máy có quyền truy cập REST/archive chính thức; chưa xác nhận nến thật."]}


def main():
    parser=argparse.ArgumentParser(description="Smoke public futures chỉ khi chủ động chạy, không đọc DB giao dịch.")
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    if args.output_dir.exists():
        parser.error('Chọn thư mục mới; không ghi đè bằng chứng smoke cũ.')
    args.output_dir.mkdir(parents=True)
    with closing(sqlite3.connect(args.output_dir/'public-history-cache.db')) as db:
        init(db)
        result=asyncio.run(smoke(db))
    (args.output_dir/'smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','verified_windows','attempted_windows','pending')},ensure_ascii=False))
    return 0 if result['release_market_evidence'] else 2


if __name__=='__main__':
    raise SystemExit(main())
