"""Deterministic worker admission, cache and event loop regressions."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from wiki import kurobbs
from wiki.models import WikiError


def payload(text="技能伤害。"):
    return {
        "content": {
            "title": "测试角色",
            "modules": [
                {"title": "技能详情", "components": [{"content": f"<p>{text}</p>"}]}
            ],
        }
    }


def test_parse_and_evidence_run_off_loop_and_hot_cache_is_reused():
    async def run():
        event_thread = threading.get_ident()
        client = SimpleNamespace(get=AsyncMock(return_value=payload()))
        service = kurobbs.KuroBbsService(client)
        parse = kurobbs.modules_to_sections
        select = kurobbs.evidence

        def check_parse(*args, **kwargs):
            assert threading.get_ident() != event_thread
            return parse(*args, **kwargs)

        def check_evidence(*args, **kwargs):
            assert threading.get_ident() != event_thread
            return select(*args, **kwargs)

        with (
            patch.object(
                kurobbs, "modules_to_sections", side_effect=check_parse
            ) as parser,
            patch.object(kurobbs, "evidence", side_effect=check_evidence),
        ):
            cold = await service.read(123, "技能")
            hot = await service.read(123, "技能")
            assert hot["evidence"] == cold["evidence"]
            assert parser.call_count == 1
            assert service._counters["parse_cache_hits"] == 1
            assert await service.clear_parse_cache() == 1
            await service.read(123, "技能")
            assert parser.call_count == 2
            # A changed payload under the same entry/version must invalidate.
            client.get.return_value = payload("全新技能效果。")
            changed = await service.read(123, "技能")
            assert "全新技能" in str(changed["evidence"])
            assert parser.call_count == 3

    asyncio.run(run())


def test_timeout_keeps_worker_capacity_and_clear_does_not_repopulate():
    async def run():
        loop = asyncio.get_running_loop()
        entered = [asyncio.Event(), asyncio.Event()]
        release = threading.Event()
        calls_lock = threading.Lock()
        calls = 0
        parser = kurobbs.modules_to_sections

        def blocked(*args, **kwargs):
            nonlocal calls
            with calls_lock:
                index = calls
                calls += 1
            loop.call_soon_threadsafe(entered[index].set)
            assert release.wait(5), "test failed to release worker"
            return parser(*args, **kwargs)

        service = kurobbs.KuroBbsService(
            SimpleNamespace(get=AsyncMock(return_value=payload()))
        )
        with patch.object(kurobbs, "modules_to_sections", blocked):
            tasks = [asyncio.create_task(service.read(123, "技能")) for _ in range(2)]
            try:
                # If parsing runs on the event loop, it cannot deliver these
                # signals while the parser is blocked, so this check fails.
                await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered)), 2)
                tick = asyncio.Event()
                loop.call_soon(tick.set)
                await asyncio.wait_for(tick.wait(), 1)
                # Cancellation via wait_for models the same service timeout
                # without depending on how fast the machine enters a worker.
                for task in tasks:
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(task, 0.01)
                with pytest.raises(WikiError) as exc:
                    await service.read(124, "技能")
                assert exc.value.code == "busy"
                assert calls == 2 and len(service._workers) == 2
                await service.clear_parse_cache()
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.gather(*list(service._workers), return_exceptions=True)
            assert not service._parsed
        assert (await service.read(123, "技能"))["status"] == "ok"

    asyncio.run(run())


def test_parse_cache_ttl_count_and_byte_limits():
    async def run():
        client = SimpleNamespace(get=AsyncMock())
        service = kurobbs.KuroBbsService(client, page_ttl=100)
        for i in range(12):
            client.get.return_value = payload(f"技能 {i}")
            await service.read(123, "技能")
        assert len(service._parsed) == 8
        now = kurobbs.time.monotonic()
        # Adjust expiry directly to avoid a wall-clock sleep or speed threshold.
        for key, (_, size, parsed) in list(service._parsed.items()):
            service._parsed[key] = (now - 1, size, parsed)
        await service.read(123, "技能")
        assert len(service._parsed) == 1
        await service.clear_parse_cache()
        with patch.object(kurobbs, "PARSE_CACHE_BYTES", 1):
            await service.read(123, "技能")
            assert not service._parsed and service._parse_bytes == 0
        client.get.return_value = payload("x" * (8 << 20))
        with pytest.raises(WikiError) as exc:
            await service.read(123, "技能")
        assert exc.value.code == "invalid_response"

    asyncio.run(run())


def test_clear_while_worker_is_starting_prevents_cache_refill():
    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        service = kurobbs.KuroBbsService(
            SimpleNamespace(get=AsyncMock(return_value=payload()))
        )
        original = service._render_detail

        def blocked(*args):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return original(*args)

        with patch.object(service, "_render_detail", blocked):
            task = asyncio.create_task(service.read(123, "技能"))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                await service.clear_parse_cache()
            finally:
                release.set()
                await task
        assert not service._parsed and service._parse_bytes == 0

    asyncio.run(run())
