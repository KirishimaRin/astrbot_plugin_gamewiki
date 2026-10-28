"""Fixed-origin asynchronous MediaWiki client with request coalescing."""

import asyncio
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from . import VERSION
from .cache import Cache
from .games import PROFILES, default_source, source_api
from .models import WikiError

MAX_BYTES = 2 * 1024 * 1024


class WikiClient:
    # BWIKI games share one WAF; PRTS has its own host and independent backoff.
    _blocked: dict[str, float] = {}

    def __init__(
        self,
        cache: Cache,
        timeout: float = 8,
        transport=None,
        concurrency: int = 2,
        pace: float = 0.3,
        game: str = "ys",
        source: str = "",
    ):
        self.cache = cache
        self.timeout = timeout
        self.game = game
        self.game_name = PROFILES[game].name
        self.source = source or default_source(game)
        self.source_name = {"prts": "PRTS", "bwiki": "BWIKI", "akedata": "AKEData"}.get(
            self.source, self.source
        )
        self.api = source_api(game, self.source)
        self._host = httpx.URL(self.api).host
        self.http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": f"AstrBot-GameWiki/{VERSION} ({self.source_name} lookup)"
            },
            transport=transport,
        )
        self._slots = asyncio.Semaphore(max(1, int(concurrency)))
        self._pace_seconds = max(0.0, float(pace))
        self._pace = asyncio.Lock()
        self._next_request = 0.0
        self._pending: dict[str, asyncio.Task] = {}
        self._counters = {"upstream_requests": 0, "cache_hits": 0, "coalesced": 0}
        self._errors: dict[str, int] = {}

    def stats(self) -> dict:
        return {
            "game": self.game,
            "source": self.source,
            **self._counters,
            "errors": dict(self._errors),
        }

    def health(self) -> dict:
        """Local status only; this method never starts an upstream request."""
        return {
            "blocked_seconds": max(
                0, math.ceil(self._blocked.get(self._host, 0.0) - time.monotonic())
            ),
            "pending": len(self._pending),
            "closed": self.http.is_closed,
        }

    def _count_error(self, code: str):
        self._errors[code] = self._errors.get(code, 0) + 1

    async def close(self):
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.http.aclose()

    async def request(self, params: dict, ttl: float) -> dict:
        params = {**params, "format": "json", "formatversion": 2}
        # The game code prefixes the key so two wikis never share an entry.
        key = hashlib.sha256(
            (
                (self.game if self.source == "bwiki" else f"{self.source}:{self.game}")
                + json.dumps(params, sort_keys=True, ensure_ascii=False)
            ).encode()
        ).hexdigest()
        cached = await self.cache.get(key)
        if cached is not None:
            self._counters["cache_hits"] += 1
            return cached
        task = self._pending.get(key)
        if task is None:
            if len(self._pending) >= 16:
                self._count_error("busy")
                raise WikiError("busy", "百科查询繁忙，请稍后重试。")
            task = asyncio.create_task(
                asyncio.wait_for(
                    self._fetch_and_cache(params, ttl, key),
                    self.timeout * 3 + self._pace_seconds * 3 + 6,
                )
            )
            self._pending[key] = task

            def finished(done):
                self._pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Also consume errors if all callers timed out.

            task.add_done_callback(finished)
        else:
            self._counters["coalesced"] += 1
        # One cancelled caller must not cancel other users' shared request.
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done() and task.cancelled():
                # The shared task hit its outer budget, not this caller.
                raise WikiError(
                    "timeout", f"{self.source_name} 连接超时，请稍后重试。"
                ) from None
            raise

    async def _fetch_and_cache(self, params, ttl, key):
        try:
            async with self._slots:
                result = await self._fetch(params)
        except WikiError as exc:
            self._count_error(exc.code)
            raise
        empty = result.get("query", {}).get("search") == []
        await self.cache.put(key, result, min(ttl, 60) if empty else ttl)
        return result

    async def _wait_turn(self):
        async with self._pace:
            blocked = WikiClient._blocked.get(self._host, 0.0)
            if time.monotonic() < blocked:
                raise WikiError(
                    "rate_limited", f"{self.source_name} 暂时限流，请稍后重试。"
                )
            delay = self._next_request - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request = time.monotonic() + self._pace_seconds

    def _retry_after(self, header: str) -> float:
        try:
            return max(1, min(300, float(header)))
        except ValueError:
            try:
                dt = parsedate_to_datetime(header)
                return max(1, min(300, dt.timestamp() - time.time()))
            except (TypeError, ValueError, OverflowError):
                return 30

    async def _fetch(self, params):
        # The BWIKI WAF intermittently answers 5xx challenges; retry politely.
        for attempt in range(3):
            await self._wait_turn()
            try:
                # asyncio.wait_for also bounds slowly streamed responses on Python 3.10.
                return await asyncio.wait_for(self._read(params), self.timeout)
            except (httpx.TimeoutException, httpx.NetworkError, asyncio.TimeoutError):
                if attempt == 2:
                    raise WikiError(
                        "timeout", f"{self.source_name} 连接超时，请稍后重试。"
                    ) from None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt == 2:
                    raise WikiError(
                        "upstream", f"{self.source_name} 服务暂时异常，请稍后重试。"
                    ) from None
            if attempt < 2:
                await asyncio.sleep((0.3, 1.0)[attempt])
        raise WikiError("upstream", f"{self.source_name} 服务暂时异常。")

    async def _read(self, params):
        return await self._read_json(self.api, params, MAX_BYTES)

    async def _read_json(self, url, params, max_bytes):
        async with self.http.stream("GET", url, params=params) as response:
            self._counters["upstream_requests"] += 1
            if response.status_code == 403:
                raise WikiError(
                    "forbidden", f"{self.source_name} 拒绝了本次访问，请稍后重试。"
                )
            if response.status_code == 429:
                delay = self._retry_after(response.headers.get("Retry-After", "30"))
                WikiClient._blocked[self._host] = time.monotonic() + delay
                raise WikiError(
                    "rate_limited",
                    f"{self.source_name} 暂时限流，请约 {int(delay)} 秒后重试。",
                )
            if 300 <= response.status_code < 400:
                raise WikiError(
                    "redirect", f"{self.source_name} 接口地址发生跳转，需检查插件适配。"
                )
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise WikiError("too_large", "词条内容过大，请换用更具体的条目。")
                chunks.append(chunk)
        try:
            result = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError):
            raise WikiError(
                "invalid_response", f"{self.source_name} 返回了非 JSON 内容。"
            ) from None
        if not isinstance(result, dict):
            raise WikiError(
                "invalid_response", f"{self.source_name} 返回的数据格式异常。"
            )
        if "error" in result:
            code = result["error"].get("code", "unknown")
            if code in {"missingtitle", "nosuchpageid", "invalidpageid"}:
                raise WikiError("not_found", f"未找到该{self.game_name}词条。")
            raise WikiError("api_error", f"{self.source_name} 暂时无法读取该词条。")
        result["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        return result
