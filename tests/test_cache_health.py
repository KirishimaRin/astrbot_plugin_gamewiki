import asyncio
from unittest.mock import patch

from wiki.cache import Cache


def test_doctor_cache_probe_preserves_cache_and_removes_temporary_files(tmp_path):
    cache = Cache(tmp_path / "data")

    async def check():
        empty = await cache.health()
        assert empty == {"readable": True, "writable": True, "entries": 0, "bytes": 0}
        assert not cache.path.exists(), "doctor must not create the production cache"
        await cache.put("existing", {"text": "缓存资料"}, 600)
        health = await cache.health()
        assert health["readable"] and health["writable"] and health["entries"] == 1
        assert health["bytes"] > 0
        assert await cache.get("existing") == {"text": "缓存资料"}
        assert not list(cache.path.parent.glob(".doctor-*"))

    asyncio.run(check())


def test_doctor_reports_corrupt_cache_and_unwritable_directory(tmp_path):
    cache = Cache(tmp_path)
    cache.path.write_bytes(b"not a database")
    assert not asyncio.run(cache.health())["readable"]
    with patch("wiki.cache.tempfile.TemporaryDirectory", side_effect=OSError("denied")):
        assert not asyncio.run(cache.health())["writable"]
