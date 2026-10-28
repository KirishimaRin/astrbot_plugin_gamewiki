"""Prepare AKEData's large, transparent portraits for chat image uploads."""

import asyncio
import base64
import hashlib
import io
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from PIL import Image

from .akedata import ASSETS


def _resize(body):
    with Image.open(io.BytesIO(body)) as original:
        if original.width * original.height > 16_000_000:
            raise ValueError("Portrait dimensions exceed limit")
        image = original.convert("RGBA")
        image.thumbnail((1200, 1200))
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        output = io.BytesIO()
        background.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()


async def _download(url):
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 24 << 20:
                    raise ValueError("Portrait exceeds download limit")
                chunks.append(chunk)
    return await asyncio.to_thread(_resize, b"".join(chunks))


@asynccontextmanager
async def prepared_image(url, cache=None):
    if not url.startswith(ASSETS + "characterportrait/"):
        yield url
        return
    # The file must survive until the platform has consumed event.send().
    key = "akedata-portrait:" + hashlib.sha256(url.encode()).hexdigest()
    saved = await cache.get(key) if cache else None
    body = None
    if isinstance(saved, dict):
        try:
            body = base64.b64decode(saved["jpeg"], validate=True)
        except (KeyError, ValueError, TypeError):
            pass
    if not body:
        body = await asyncio.wait_for(_download(url), timeout=30)
        if cache:
            await cache.put(
                key, {"jpeg": base64.b64encode(body).decode("ascii")}, 21600
            )
    with tempfile.TemporaryDirectory(prefix="gamewiki-portrait-") as directory:
        path = Path(directory) / "portrait.jpg"
        await asyncio.to_thread(path.write_bytes, body)
        yield str(path)
