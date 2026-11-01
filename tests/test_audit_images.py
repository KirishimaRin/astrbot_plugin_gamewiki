"""External image boundary: all network traffic is simulated."""

import asyncio
import io
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PIL import Image

from wiki import images
from wiki.kurobbs import _figure_url
from wiki.spirecodex import SpireCodexService

URL = "https://cdn.spire-codex.com/image.png"


def png():
    out = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(out, format="PNG")
    return out.getvalue()


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/image.png",
        "image.png",
        "C:\\image.png",
        "ftp://spire-codex.com/a",
        "http://127.0.0.1/a",
        "http://10.0.0.1/a",
        "http://169.254.169.254/a",
        "http://[::1]/a",
        "http://[::ffff:127.0.0.1]/a",
        "https://evil.example/a",
        "https://spire-codex.com.evil.example/a",
        "https://a@spire-codex.com/a",
        "https://spire-codex.com:8443/a",
        " https://spire-codex.com/a",
    ],
)
def test_external_url_rejects_unsafe_values(url):
    async def run():
        with patch.object(images, "_download", AsyncMock()) as download:
            with pytest.raises(ValueError):
                async with images.prepared_image(url):
                    pytest.fail("unsafe value reached image sender")
            download.assert_not_awaited()

    asyncio.run(run())


def test_local_file_never_reaches_external_sender(tmp_path):
    path = tmp_path / "owned.png"
    path.write_bytes(png())

    async def run():
        with pytest.raises(ValueError):
            async with images.prepared_image(str(path)):
                pytest.fail("local file accepted as upstream image")

    asyncio.run(run())
    service = SpireCodexService(SimpleNamespace())
    # Source-relative URLs are resolved to HTTP, never kept as local paths.
    assert service._image_url("card", {"image_url_card": str(path)}).startswith(
        "https://"
    )
    assert (
        _figure_url(
            {"components": [{"role": {"figures": [{"url": "file://" + str(path)}]}}]}
        )
        == ""
    )


def test_relative_images_and_custom_public_origins():
    service = SpireCodexService(SimpleNamespace(), base="https://mirror.example:8443")
    assert (
        service._image_url("card", {"image_url_card": "/cards/a.webp"})
        == "https://mirror.example:8443/cards/a.webp"
    )
    assert service._image_url("card", {"image_url_card": "http://127.0.0.1/a"}) == ""
    assert (
        images.external_image_url("//cdn.spire-codex.com/a", base=service.base)
        == "https://cdn.spire-codex.com/a"
    )
    assert (
        _figure_url(
            {"components": [{"role": {"figures": [{"url": "/a.png"}]}}]},
            "https://mirror.example",
        )
        == "https://mirror.example/a.png"
    )


def test_dns_validation_and_pinned_transport():
    async def run():
        loop = asyncio.get_running_loop()
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]
        seen = []

        def handler(request):
            seen.append(request)
            assert request.url.host == "93.184.216.34"
            assert request.headers["host"] == "cdn.spire-codex.com"
            assert request.extensions["sni_hostname"] == "cdn.spire-codex.com"
            return httpx.Response(200, content=png())

        with patch.object(
            loop, "getaddrinfo", AsyncMock(return_value=addresses)
        ) as dns:
            body = await images._download(URL, transport=httpx.MockTransport(handler))
            assert body == png()
            dns.assert_awaited_once()
        addresses.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)))
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=addresses)):
            with pytest.raises(ValueError, match="DNS"):
                await images._download(URL, transport=httpx.MockTransport(handler))
        assert len(seen) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "location", ["http://127.0.0.1/a", "https://evil.example/a", "file:///tmp/a"]
)
def test_redirect_target_is_checked_before_request(location):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": location})

        with patch.object(
            images,
            "_public_target",
            AsyncMock(return_value=(httpx.URL(URL), httpx.URL(URL))),
        ):
            with pytest.raises(ValueError):
                await images._download(URL, transport=httpx.MockTransport(handler))
        assert len(calls) == 1

    asyncio.run(run())


def test_redirect_hop_limit_and_allowed_relative_redirect():
    async def run():
        async def target(url):
            return httpx.URL(url), httpx.URL(url)

        requests = []

        def handler(request):
            requests.append(request.url.path)
            return (
                httpx.Response(302, headers={"location": "/next"})
                if request.url.path != "/next"
                else httpx.Response(200, content=png())
            )

        with patch.object(images, "_public_target", target):
            assert (
                await images._download(URL, transport=httpx.MockTransport(handler))
                == png()
            )
            assert requests == ["/image.png", "/next"]
            transport = httpx.MockTransport(
                lambda req: httpx.Response(302, headers={"location": "/loop"})
            )
            with pytest.raises(ValueError, match="redirect"):
                await images._download(URL, transport=transport)

    asyncio.run(run())


@pytest.mark.parametrize("declared", [False, True])
def test_response_size_limit(declared):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 6
            yield b"y" * 6

    async def run():
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-length": "12"} if declared else {},
                stream=Stream(),
            )

        with (
            patch.object(images, "MAX_BYTES", 10),
            patch.object(
                images,
                "_public_target",
                AsyncMock(return_value=(httpx.URL(URL), httpx.URL(URL))),
            ),
        ):
            with pytest.raises(ValueError, match="limit"):
                await images._download(URL, transport=httpx.MockTransport(handler))

    asyncio.run(run())


def test_total_timeout_and_temporary_file_lifetime():
    async def run():
        async def stalled(url):
            await asyncio.Event().wait()

        with (
            patch.object(images, "TOTAL_TIMEOUT", 0.01),
            patch.object(images, "_download", stalled),
        ):
            with pytest.raises(asyncio.TimeoutError):
                async with images.prepared_image(URL):
                    pytest.fail("stalled download completed")
        with patch.object(images, "_download", AsyncMock(return_value=png())):
            with pytest.raises(RuntimeError):
                async with images.prepared_image(URL) as path:
                    assert Path(path).read_bytes() == png()
                    raise RuntimeError("send failed")
            assert not Path(path).exists()

    asyncio.run(run())
