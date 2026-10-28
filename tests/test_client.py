import asyncio
import unittest

import httpx
import pytest

from wiki.cache import Cache
from wiki.client import MAX_BYTES, WikiClient
from wiki.models import WikiError


class TestClient(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path

        self.temp = tempfile.TemporaryDirectory()
        self.cache = Cache(Path(self.temp.name))
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        WikiClient._blocked.clear()
        self.temp.cleanup()

    def client(self, handler, timeout=1):
        client = WikiClient(
            self.cache, timeout=timeout, transport=httpx.MockTransport(handler)
        )
        self.clients.append(client)
        return client

    async def test_health_reports_shared_backoff_without_network(self):
        import time

        def unexpected(request):
            raise AssertionError("health must not send requests")

        client = self.client(unexpected)
        WikiClient._blocked[client._host] = time.monotonic() + 30
        health = client.health()
        assert 29 <= health["blocked_seconds"] <= 30
        assert health["pending"] == 0 and not health["closed"]
        assert client.stats()["upstream_requests"] == 0
        await client.close()
        assert client.health()["closed"]

    async def test_shared_request_and_disk_cache(self):
        calls = []

        async def handler(request):
            calls.append(request)
            await asyncio.sleep(0.02)
            return httpx.Response(200, json={"query": {"search": []}})

        client = self.client(handler)
        params = {"action": "query"}
        results = await asyncio.gather(*(client.request(params, 600) for _ in range(8)))
        assert len(calls) == 1
        assert all(r == results[0] for r in results)
        await client.request(params, 600)
        assert len(calls) == 1

    async def test_cancelled_waiter_does_not_cancel_other(self):
        async def handler(request):
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"query": {"search": []}})

        client = self.client(handler)
        a = asyncio.create_task(client.request({"action": "query"}, 60))
        b = asyncio.create_task(client.request({"action": "query"}, 60))
        await asyncio.sleep(0.02)
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        assert (await b)["query"]["search"] == []

    async def test_forbidden_no_retry(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(403)

        with pytest.raises(WikiError) as exc:
            await self.client(handler).request({}, 0)
        assert exc.value.code == "forbidden"
        assert len(calls) == 1

    async def test_rate_limit_blocks_followup_request(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "10"})

        client = self.client(handler)
        for params in ({"a": 1}, {"a": 2}):
            with pytest.raises(WikiError) as exc:
                await client.request(params, 0)
            assert exc.value.code == "rate_limited"
        assert len(calls) == 1

    async def test_transient_server_failure_retries_once(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(502 if len(calls) == 1 else 200, json={"parse": {}})

        assert "parse" in await self.client(handler).request({}, 0)
        assert len(calls) == 2

    async def test_invalid_json_and_oversize(self):
        for content, code in [
            (b"<html>captcha</html>", "invalid_response"),
            (b"a" * (MAX_BYTES + 1), "too_large"),
        ]:
            client = self.client(lambda r: httpx.Response(200, content=content))
            with pytest.raises(WikiError) as exc:
                await client.request({}, 0)
            assert exc.value.code == code

    async def test_timeout_is_bounded(self):
        async def handler(request):
            await asyncio.sleep(10)

        with pytest.raises(WikiError) as exc:
            await self.client(handler, timeout=0.02).request({}, 0)
        assert exc.value.code == "timeout"

    async def test_cache_expiration_and_limit(self):
        self.cache.max_entries = 2
        for i in range(3):
            await self.cache.put(str(i), {"i": i}, 60)
        assert await self.cache.get("0") is None
        assert await self.cache.get("2") == {"i": 2}
        await self.cache.put("expired", {}, -1)
        assert await self.cache.get("expired") is None

    async def test_get_refreshes_recency_for_lru_eviction(self):
        self.cache.max_entries = 2
        await self.cache.put("a", {"a": 1}, 60)
        await self.cache.put("b", {"b": 2}, 60)
        await self.cache.get("a")  # a is now the most recent entry
        await self.cache.put("c", {"c": 3}, 60)
        assert await self.cache.get("a") == {"a": 1}
        assert await self.cache.get("b") is None

    async def test_byte_budget_evicts_oldest_and_skips_oversize(self):
        self.cache.max_bytes = 1000
        await self.cache.put("a", {"v": "x" * 500}, 60)
        await self.cache.put("b", {"v": "x" * 500}, 60)
        assert await self.cache.get("a") is None, "oldest entry evicted by budget"
        assert await self.cache.get("b") == {"v": "x" * 500}
        await self.cache.put("big", {"v": "x" * 2000}, 60)
        assert await self.cache.get("big") is None, "oversize entry is not cached"

    async def test_stats_track_cache_coalescing_and_errors(self):
        calls = []

        async def handler(request):
            calls.append(request)
            return httpx.Response(403)

        client = self.client(handler)
        with pytest.raises(WikiError):
            await client.request({"action": "query"}, 0)
        with pytest.raises(WikiError):
            await client.request({"action": "query"}, 0)  # 403 is never cached
        stats = client.stats()
        assert stats["upstream_requests"] == 2
        assert stats["errors"]["forbidden"] == 2
        assert stats["cache_hits"] == 0
        assert stats["coalesced"] == 0

        async def ok_handler(request):
            return httpx.Response(200, json={"query": {"search": []}})

        client = self.client(ok_handler)
        await asyncio.gather(*(client.request({"a": 1}, 600) for _ in range(3)))
        await client.request({"a": 1}, 600)
        stats = client.stats()
        assert stats["upstream_requests"] == 1
        assert stats["coalesced"] == 2
        assert stats["cache_hits"] == 1

    async def test_redirect_and_mediawiki_error_payloads(self):
        client = self.client(
            lambda r: httpx.Response(302, headers={"Location": "https://x/"})
        )
        with pytest.raises(WikiError) as exc:
            await client.request({}, 0)
        assert exc.value.code == "redirect"
        client = self.client(
            lambda r: httpx.Response(200, json={"error": {"code": "invalidpageid"}})
        )
        with pytest.raises(WikiError) as exc:
            await client.request({}, 0)
        assert exc.value.code == "not_found"
        client = self.client(
            lambda r: httpx.Response(200, json={"error": {"code": "unknownx"}})
        )
        with pytest.raises(WikiError) as exc:
            await client.request({}, 0)
        assert exc.value.code == "api_error"

    async def test_cache_clear_reports_and_empties(self):
        await self.cache.put("a", {"a": 1}, 60)
        assert await self.cache.get("a") == {"a": 1}
        assert await self.cache.clear() == 1
        assert await self.cache.get("a") is None
        assert await self.cache.clear() == 0

    async def test_concurrency_and_pace_parameters_are_applied(self):
        client = WikiClient(
            self.cache,
            timeout=1,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            concurrency=3,
            pace=0.01,
        )
        self.clients.append(client)
        assert client._slots._value == 3
        assert client._pace_seconds == 0.01

    async def test_wal_mode_is_enabled(self):
        import sqlite3

        await self.cache.put("k", {"v": 1}, 60)  # trigger a real connection
        conn = sqlite3.connect(self.cache.path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode == "wal"

    async def test_429_blocks_other_game_clients_too(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "10"})

        first = self.client(handler)
        with pytest.raises(WikiError) as exc:
            await first.request({"a": 1}, 0)
        assert exc.value.code == "rate_limited"
        # A different game client hits the same WAF host and must cool down
        # without sending anything.
        other = WikiClient(
            self.cache,
            timeout=1,
            transport=httpx.MockTransport(handler),
            game="sr",
        )
        self.clients.append(other)
        with pytest.raises(WikiError) as exc:
            await other.request({"b": 2}, 0)
        assert exc.value.code == "rate_limited"
        assert len(calls) == 1

    async def test_outer_budget_survives_the_full_retry_ladder(self):
        # timeout=0.05 with pace=1.2 makes the retry ladder outlast the old
        # outer budget; the shared task was cancelled and callers saw a bare
        # CancelledError instead of a WikiError.
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(502)

        client = WikiClient(
            self.cache,
            timeout=0.05,
            transport=httpx.MockTransport(handler),
            pace=1.2,
        )
        self.clients.append(client)
        with pytest.raises(WikiError) as exc:
            await client.request({"a": 1}, 0)
        assert exc.value.code == "upstream"
        assert len(calls) == 3, "every retry attempt must reach the wire"
