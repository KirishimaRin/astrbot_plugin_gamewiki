"""Validate and download upstream images; expose only owned temporary files."""

import asyncio
import base64
import hashlib
import io
import ipaddress
import socket
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin

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


# External values never become platform file arguments. Only files created below
# (and the separate local card renderer) enter the local-file sending interface.
MAX_BYTES = 24 << 20
TOTAL_TIMEOUT = 30
IMAGE_DOMAINS = (
    "spire-codex.com",
    "kurobbs.com",
    "kurogame.com",
    "kurogame.net",
    "biligame.com",
    "hdslb.com",
    "prts.wiki",
    "akedata.wiki",
)


def _is_public(address):
    ip = ipaddress.ip_address(address)
    return ip.is_global and not (
        ip.is_multicast or ip.is_reserved or getattr(ip, "is_site_local", False)
    )


def external_image_url(value, *, base="", origins=()):
    """Resolve source-relative paths and enforce the external URL boundary."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Invalid external image URL")
    if "\\" in value or any(ord(c) < 33 for c in value):
        raise ValueError("Invalid external image URL")
    # Relative references require an explicit upstream base; no value is
    # interpreted as a local filename.
    if value.startswith("/") and not value.startswith("//"):
        if not base:
            raise ValueError("Image URL requires source origin")
        value = urljoin(base.rstrip("/") + "/", value)
    elif base and not httpx.URL(value).scheme:
        value = urljoin(base.rstrip("/") + "/", value)
    url = httpx.URL(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.userinfo
        or url.fragment
    ):
        raise ValueError("Image URL must use HTTP(S) without credentials or fragment")
    try:
        address = ipaddress.ip_address(url.host)
    except ValueError:
        address = None
    if address is not None and not _is_public(address):
        raise ValueError("Image target is not public")
    configured = [httpx.URL(origin) for origin in (*origins, base) if origin]
    custom = any(
        (url.scheme, url.host, url.port) == (o.scheme, o.host, o.port)
        for o in configured
    )
    known = url.port in {None, 80, 443} and any(
        url.host == domain or url.host.endswith("." + domain)
        for domain in IMAGE_DOMAINS
    )
    if not (custom or known):
        raise ValueError("Image origin is not allowed")
    return str(url)


def optional_image_url(value, **kwargs):
    try:
        return external_image_url(value, **kwargs)
    except (ValueError, httpx.InvalidURL):
        return ""


async def _public_target(url):
    parsed = httpx.URL(url)
    records = await asyncio.get_running_loop().getaddrinfo(
        parsed.host,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    addresses = [record[4][0] for record in records]
    if not addresses or any(not _is_public(a) for a in addresses):
        raise ValueError("Image DNS target is not public")
    # Pin the checked address, keeping original Host and TLS SNI. This avoids a
    # second DNS lookup (and DNS rebinding) inside the HTTP transport.
    return parsed.copy_with(host=addresses[0]), parsed


async def _download(url, *, origins=(), transport=None):
    async with httpx.AsyncClient(
        timeout=8, follow_redirects=False, trust_env=False, transport=transport
    ) as client:
        for hop in range(4):
            url = external_image_url(url, origins=origins)
            target, original = await _public_target(url)
            async with client.stream(
                "GET",
                target,
                headers={"Host": original.netloc.decode("ascii")},
                extensions={"sni_hostname": original.host},
            ) as response:
                if response.is_redirect:
                    if hop == 3 or "location" not in response.headers:
                        raise ValueError("Too many image redirects")
                    url = external_image_url(
                        urljoin(url, response.headers["location"]), origins=origins
                    )
                    continue
                response.raise_for_status()
                if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                    raise ValueError("Image exceeds download limit")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Image exceeds download limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError("No image response")


@asynccontextmanager
async def prepared_image(url, cache=None, *, convert_webp=False, origins=()):
    url = external_image_url(url, origins=origins)
    portrait = url.startswith(ASSETS + "characterportrait/")
    webp = convert_webp and url.lower().split("?", 1)[0].endswith(".webp")
    key = (
        "safe-image-v2:"
        + hashlib.sha256(f"{portrait}:{webp}:{url}".encode()).hexdigest()
    )
    saved = await cache.get(key) if cache else None
    body = None
    if isinstance(saved, dict):
        try:
            body = base64.b64decode(saved["image"], validate=True)
            if len(body) > MAX_BYTES:
                body = None
        except (KeyError, ValueError, TypeError):
            pass
    if not body:

        async def prepare():
            raw = (
                await _download(url, origins=origins)
                if origins
                else await _download(url)
            )
            if portrait or webp:
                return await asyncio.to_thread(_resize, raw)

            # Validate image bytes before handing a generated file to AstrBot.
            def verify():
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 16_000_000:
                        raise ValueError("Image dimensions exceed limit")
                    image.verify()

            await asyncio.to_thread(verify)
            return raw

        body = await asyncio.wait_for(prepare(), TOTAL_TIMEOUT)
        if cache:
            await cache.put(
                key, {"image": base64.b64encode(body).decode("ascii")}, 21600
            )

    def suffix():
        with Image.open(io.BytesIO(body)) as image:
            return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}.get(
                image.format, ".img"
            )

    extension = await asyncio.to_thread(suffix)
    with tempfile.TemporaryDirectory(prefix="gamewiki-image-") as directory:
        path = Path(directory) / ("image" + extension)
        await asyncio.to_thread(path.write_bytes, body)
        yield str(path)
