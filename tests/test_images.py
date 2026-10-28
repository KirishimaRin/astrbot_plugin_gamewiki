import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from wiki.images import _resize, prepared_image
from wiki.akedata import ASSETS


def test_large_transparent_portrait_is_resized_and_temporary_file_is_removed():
    source = io.BytesIO()
    Image.new("RGBA", (2048, 2048), (0, 0, 0, 0)).save(source, format="PNG")
    body = _resize(source.getvalue())
    assert len(body) < 1 << 20
    with Image.open(io.BytesIO(body)) as image:
        assert image.size == (1200, 1200)
        assert image.getpixel((0, 0)) == (255, 255, 255)

    async def run():
        with patch("wiki.images._download", AsyncMock(return_value=body)):
            async with prepared_image(ASSETS + "characterportrait/test.png") as path:
                assert Path(path).is_file()
                saved = path
            assert not Path(saved).exists()
        with patch("wiki.images._download", AsyncMock()) as download:
            async with prepared_image("https://example.org/image.png") as path:
                assert path == "https://example.org/image.png"
            download.assert_not_awaited()

    asyncio.run(run())


def test_invalid_portrait_is_rejected():
    with pytest.raises(OSError):
        _resize(b"not an image")


def test_compressed_image_cache_and_failed_send_cleanup(tmp_path):
    from wiki.cache import Cache

    async def run():
        cache = Cache(tmp_path)
        download = AsyncMock(return_value=b"jpeg fixture")
        url = ASSETS + "characterportrait/test.png"
        with patch("wiki.images._download", download):
            async with prepared_image(url, cache) as path:
                assert Path(path).read_bytes() == b"jpeg fixture"
            with pytest.raises(RuntimeError):
                async with prepared_image(url, cache) as path:
                    saved = path
                    raise RuntimeError("send failed")
            assert not Path(saved).exists()
            download.assert_awaited_once_with(url)
            await cache.clear()
            async with prepared_image(url, cache):
                pass
            assert download.await_count == 2

    asyncio.run(run())
