"""Official Binance USD-M OHLCV archives, checksum verified; no symbol substitution."""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import re
import time
import zipfile

import httpx

POLICY = "official-um-archives-v1"
BASE = "https://data.binance.vision/data/futures/um"
MAX_ZIP = 8*1024*1024
MAX_CSV = 32*1024*1024


class HistoryError(ValueError):
    pass


class PublicHistoryHTTP:
    """Bounded bytes, requests, attempts and Retry-After; a budget can resume from cache."""
    def __init__(self, client, sleep=asyncio.sleep, max_requests=160):
        self.client, self.sleep, self.max_requests = client, sleep, max_requests
        self.requests = 0
        self.events = []

    async def get(self, url, *, params=None, max_bytes=MAX_ZIP):
        for attempt in range(3):
            if self.requests >= self.max_requests:
                raise HistoryError("HISTORY_REQUEST_BUDGET")
            self.requests += 1
            try:
                async with self.client.stream("GET", url, params=params) as response:
                    code = response.status_code
                    self.events.append({"host": httpx.URL(url).host, "path": httpx.URL(url).path, "http_status": code})
                    if code in (403, 451):
                        raise HistoryError("HISTORY_ACCESS_UNAVAILABLE")
                    if code in (400, 404):
                        raise HistoryError("HISTORY_REMOTE_NOT_FOUND")
                    if code in (418, 429):
                        try:
                            retry = float(response.headers.get("Retry-After", "1"))
                        except ValueError:
                            retry = 30.
                        if not 0 <= retry <= 30 or attempt == 2:
                            raise HistoryError("RATE_LIMIT_RETRY_LATER")
                        await self.sleep(max(1., retry))
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise HistoryError("HISTORY_RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                await self.sleep(.25)
                return b"".join(chunks)
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.RequestError):
                    self.events.append({"host": httpx.URL(url).host, "path": httpx.URL(url).path, "error": type(exc).__name__})
                if attempt == 2:
                    raise HistoryError("HISTORY_NETWORK_UNAVAILABLE") from None
                await self.sleep(2**attempt)
        raise HistoryError("HISTORY_NETWORK_UNAVAILABLE")


def unpack(data, filename):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            expected = filename[:-4]+".csv"
            if (len(infos) != 1 or infos[0].filename != expected or infos[0].is_dir()
                    or infos[0].file_size > MAX_CSV
                    or ((infos[0].external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError
            raw = archive.read(infos[0])
        return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (ValueError, OSError, UnicodeError, zipfile.BadZipFile, RuntimeError):
        raise HistoryError("INVALID_OFFICIAL_ARCHIVE") from None


def next_month(date):
    return date.replace(year=date.year+1, month=1) if date.month == 12 else date.replace(month=date.month+1)


class OfficialArchives:
    def __init__(self, db, http, clock=time.time):
        self.db, self.http, self.clock = db, http, clock

    async def file(self, symbol, interval, period, date):
        filename = f"{symbol}-{interval}-{date}.zip"
        key = f"{period}/{symbol}/{interval}/{filename}"
        url = BASE+"/"+key
        old = self.db.execute("SELECT sha256,compressed,provenance FROM rei_v3_archives WHERE archive_key=?", (key,)).fetchone()
        if old:
            checksum, data, proof = old[0], old[1], json.loads(old[2])
            if hashlib.sha256(data).hexdigest() != checksum:
                raise HistoryError("ARCHIVE_CACHE_CHECKSUM_MISMATCH")
        else:
            data = await self.http.get(url)
            check = await self.http.get(url+".CHECKSUM", max_bytes=2048)
            try:
                match = re.fullmatch(r"\s*([a-fA-F0-9]{64})\s+\*?([^\s]+)\s*", check.decode("ascii"))
                if not match or match[2] != filename or hashlib.sha256(data).hexdigest() != match[1].lower():
                    raise ValueError
                checksum = match[1].lower()
            except (ValueError, UnicodeError):
                raise HistoryError("OFFICIAL_ARCHIVE_CHECKSUM_MISMATCH") from None
            unpack(data, filename)  # Bound and validate container before persisting.
            proof = {"provider": "binance-official-usdm-archive", "url": url, "sha256": checksum,
                     "checksum_url": url+".CHECKSUM", "fetched_at_ms": int(self.clock()*1000),
                     "symbol": symbol, "interval": interval, "policy": POLICY}
            self.db.execute("INSERT OR IGNORE INTO rei_v3_archives VALUES(?,?,?,?)", (key, checksum, data, json.dumps(proof)))
            self.db.commit()
        return unpack(data, filename), proof

    async def window(self, symbol, interval, start, end):
        # Monthly first; an absent monthly archive may be available as official daily files.
        date = datetime.fromtimestamp(start/1000, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result, sources = [], []
        while int(date.timestamp()*1000) <= end:
            following = next_month(date)
            first = max(start, int(date.timestamp()*1000))
            last = min(end, int(following.timestamp()*1000)-1)
            try:
                rows, proof = await self.file(symbol, interval, "monthly/klines", date.strftime("%Y-%m"))
                segments = [(rows, proof)]
            except HistoryError as exc:
                if str(exc) != "HISTORY_REMOTE_NOT_FOUND":
                    raise
                segments = []
                day = datetime.fromtimestamp(first/1000, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                while int(day.timestamp()*1000) <= last:
                    try:
                        segments.append(await self.file(symbol, interval, "daily/klines", day.strftime("%Y-%m-%d")))
                    except HistoryError as daily_error:
                        if str(daily_error) == "HISTORY_REMOTE_NOT_FOUND":
                            recent = datetime.fromtimestamp(self.clock(), timezone.utc)-day < timedelta(days=2)
                            raise HistoryError("ARCHIVE_PENDING_PUBLICATION" if recent else "ARCHIVE_HISTORY_UNAVAILABLE") from None
                        raise
                    day += timedelta(days=1)
            for rows, proof in segments:
                sources.append(proof)
                for row in rows:
                    if not row or row[0].lower() in {"open_time", "open time"}:
                        continue
                    try:
                        opened = int(row[0])
                        if first <= opened <= last:
                            if len(row) < 7 or int(row[6]) > end:
                                raise ValueError
                            result.append(row)
                    except (ValueError, IndexError):
                        raise HistoryError("INVALID_ARCHIVE_CANDLE") from None
            date = following
        result.sort(key=lambda r: int(r[0]))
        if len({int(r[0]) for r in result}) != len(result):
            raise HistoryError("DUPLICATE_ARCHIVE_CANDLE")
        return result, {"provider": "binance-official-usdm-archives", "archives": sources,
                        "selected_start_ms": start, "selected_end_ms": end, "policy": POLICY}
