"""Offline tests for the KuroBBS (Wuthering Waves official wiki) adapter."""

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from wiki.cache import Cache
from wiki.kurobbs import (
    KuroBbsClient,
    KuroBbsService,
    html_text,
    modules_to_sections,
)
from wiki.models import WikiError
from wiki.sources import WuwaSources

# 精简自 2026-10-30 真实响应的合成 fixture：结构一致、数值缩短。
SEARCH_RECORDS = {
    "今汐": {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "results": {
                "records": [
                    {
                        "id": 14234,
                        "name": "今汐",
                        "content": {
                            "type": "vertical-figure",
                            "title": "今汐",
                            "star": "5",
                            "linkId": "1249040336606580736",
                        },
                    },
                    {
                        "id": 18152,
                        "name": "今汐",
                        "content": {
                            "type": "square-figure",
                            "title": "今汐",
                            "linkId": "1426299416359342080",
                        },
                    },
                    {
                        "id": 21564,
                        "name": "【WIKI】今汐角色攻略",
                        "content": {
                            "type": "kuro-post-component",
                            "linkId": "1331088925953253376",
                        },
                    },
                    {
                        "id": 18963,
                        "name": "今汐攻略",
                        "content": {
                            "type": "strategy-component",
                            "title": "今汐攻略",
                            "linkId": None,
                        },
                    },
                ]
            }
        },
    },
    "无妄者": {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "results": {
                "records": [
                    {
                        "id": 1,
                        "name": "无妄者",
                        "content": {
                            "type": "square-figure",
                            "title": "无妄者（声骸）",
                            "linkId": 111,
                        },
                    },
                    {
                        "id": 2,
                        "name": "无妄者",
                        "content": {
                            "type": "square-figure",
                            "title": "无妄者（敌人）",
                            "linkId": 222,
                        },
                    },
                ]
            }
        },
    },
    "空": {"code": 200, "msg": "操作成功", "data": {"results": {"records": []}}},
}

DETAIL = {
    "code": 200,
    "msg": "操作成功",
    "data": {
        "currentVersion": 3,
        "content": {
            "title": "今汐",
            "modules": [
                {
                    "title": "基础资料",
                    "components": [
                        {
                            "role": {
                                "title": "今汐",
                                "info": [
                                    {"text": "性别：女"},
                                    {"text": "武器：长刃"},
                                ],
                                "figures": [
                                    {
                                        "url": "https://img.example/lihui.png",
                                        "name": "立绘",
                                    }
                                ],
                            }
                        }
                    ],
                },
                {
                    "title": "角色养成推荐",
                    "components": [
                        {
                            "type": "tabs-component",
                            "tabs": [
                                {
                                    "title": "武器推荐",
                                    "content": "<p>时和岁稔＞苍鳞千嶂</p>",
                                },
                                {
                                    "title": "声骸推荐",
                                    "content": (
                                        "<table><tr><td>毕业配装</td>"
                                        "<td>浮星祛暗2+5</td></tr></table>"
                                    ),
                                },
                            ],
                        }
                    ],
                },
                {
                    "title": "角色语音",
                    "components": [
                        {
                            "type": "audio-component",
                            "mediaTabs": [
                                {
                                    "title": "中文：一口井",
                                    "mediaList": [
                                        {
                                            "audioTitle": "心声1",
                                            "content": "你好，漂泊者。",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    },
}


def make_client(tmp_path, handler):
    transport = httpx.MockTransport(handler)
    return KuroBbsClient(Cache(tmp_path), timeout=5, transport=transport)


def kuro_handler(search_payloads, status_map=None):
    details = {
        111: {
            "code": 200,
            "msg": "操作成功",
            "data": {
                "content": {
                    "title": "无妄者（声骸）",
                    "modules": [
                        {
                            "title": "声骸技能",
                            "components": [
                                {"content": "<p>变形攻击，造成湮灭伤害。</p>"}
                            ],
                        }
                    ],
                }
            },
        },
        222: {
            "code": 200,
            "msg": "操作成功",
            "data": {
                "content": {
                    "title": "无妄者（敌人）",
                    "modules": [
                        {
                            "title": "关于无妄者",
                            "components": [
                                {"content": "<p>海啸级残象，湮灭抗性提高。</p>"}
                            ],
                        }
                    ],
                }
            },
        },
    }

    def handler(request):
        path = request.url.path
        if path == "/wiki/core/catalogue/item/search":
            form = parse_qs(request.content.decode("utf-8"))
            keyword = form["keyword"][0]
            payload = search_payloads.get(keyword, SEARCH_RECORDS["空"])
            status = (status_map or {}).get(("search", keyword))
            return httpx.Response(status if status else 200, json=payload)
        if path == "/wiki/core/catalogue/item/getEntryDetail":
            form = parse_qs(request.content.decode("utf-8"))
            entry_id = int(form["id"][0])
            payload = details.get(entry_id)
            if payload is None and entry_id == 1249040336606580736:
                payload = DETAIL
            if payload is None:
                return httpx.Response(
                    200, json={"code": 2031, "msg": "当前词条不存在", "data": None}
                )
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return handler


def test_html_text_flattens_tables_and_prose():
    html = (
        "<p>过渡配装 COST 44111</p>"
        "<table><tr><td>毕业配装</td><td>浮星祛暗 2 浮星祛暗 5</td></tr>"
        '<tr><td colspan="2">推荐内容仅供参考</td></tr></table>'
    )
    text = html_text(html)
    assert "过渡配装 COST 44111" in text
    assert "毕业配装 | 浮星祛暗 2 浮星祛暗 5" in text
    assert "推荐内容仅供参考" in text
    assert "<" not in text and "&nbsp;" not in text


def test_modules_map_to_shared_section_titles_and_extract_voice():
    sections, image = modules_to_sections(DETAIL["data"]["content"]["modules"])
    titles = [s.title for s in sections]
    assert titles == ["基本信息", "养成推荐", "语音"]
    assert image == "https://img.example/lihui.png"
    guide = sections[1]
    assert "【武器推荐】" in guide.blocks[0]
    assert "时和岁稔＞苍鳞千嶂" in guide.blocks[0]
    assert "毕业配装 | 浮星祛暗2+5" in guide.blocks[1]
    voice = sections[2]
    assert "心声1 | 你好，漂泊者。" in voice.blocks[0]


def test_search_exact_single_hit_auto_reads(tmp_path):
    async def run():
        client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
        service = KuroBbsService(client)
        try:
            result = await service.search("今汐", "声骸搭配")
            assert result["status"] == "ok"
            assert result["title"] == "今汐"
            assert result["page_id"] == 1249040336606580736
            assert result["url"].endswith("/mc/item/1249040336606580736")
            assert "养成推荐" in result["available_sections"]
            assert any("浮星祛暗" in item["text"] for item in result["evidence"])
            # 社区帖卡片（kuro-post-component）不进候选。
            assert all("角色攻略" not in c["title"] for c in result["candidates"])
        finally:
            await client.close()

    asyncio.run(run())


def test_search_same_name_entries_auto_read_with_kind_hint(tmp_path):
    async def run():
        # 无妄者同时有（声骸）/（敌人）词条：裸名称默认敌人本体优先；
        # 问句带类型词时按官方标题后缀优先。
        client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
        service = KuroBbsService(client)
        try:
            bare = await service.search("无妄者")
            assert bare["status"] == "ok"
            assert bare["title"] == "无妄者（敌人）"
            assert {c["title"] for c in bare["candidates"]} >= {
                "无妄者（声骸）",
                "无妄者（敌人）",
            }
            echo = await service.search("无妄者", "声骸技能")
            assert echo["title"] == "无妄者（声骸）"
            enemy = await service.search("无妄者", "怎么打")
            assert enemy["title"] == "无妄者（敌人）"
        finally:
            await client.close()

    asyncio.run(run())


def test_search_without_hits_reports_not_found(tmp_path):
    async def run():
        client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
        service = KuroBbsService(client)
        try:
            result = await service.search("不存在词")
            assert result["status"] == "not_found"
            assert "未找到" in result["message"]
        finally:
            await client.close()

    asyncio.run(run())


def test_read_validates_page_id_and_source(tmp_path):
    async def run():
        client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
        service = KuroBbsService(client)
        try:
            with pytest.raises(WikiError) as exc:
                await service.read(1249040336606580736, source="bwiki")
            assert exc.value.code == "bad_input"
            with pytest.raises(WikiError) as exc:
                await service.read(0)
            assert exc.value.code == "bad_input"
            result = await service.read(1249040336606580736, "声骸搭配")
            assert result["status"] == "ok"
            assert result["source_key"] == "kurobbs"
        finally:
            await client.close()

    asyncio.run(run())


def test_client_maps_error_codes(tmp_path):
    def missing(request):
        return httpx.Response(
            200, json={"code": 2031, "msg": "当前词条不存在", "data": None}
        )

    async def run():
        client = make_client(tmp_path, missing)
        try:
            with pytest.raises(WikiError) as exc:
                await client.get(
                    "/wiki/core/catalogue/item/getEntryDetail",
                    {"data": {"id": "1"}},
                    60,
                )
            assert exc.value.code == "not_found"
        finally:
            await client.close()

        def broken(request):
            return httpx.Response(
                200, json={"code": 500, "msg": "系统异常", "data": None}
            )

        bad = KuroBbsClient(
            Cache(tmp_path / "b"), timeout=5, transport=httpx.MockTransport(broken)
        )
        try:
            with pytest.raises(WikiError) as exc:
                await bad.get("/wiki/core/catalogue/item/search", {"data": {}}, 60)
            assert exc.value.code == "api_error"
        finally:
            await bad.close()

    asyncio.run(run())


def test_router_falls_back_to_bwiki(tmp_path):
    def broken(request):
        return httpx.Response(200, json={"code": 500, "msg": "系统异常", "data": None})

    async def run():
        primary = KuroBbsService(
            KuroBbsClient(
                Cache(tmp_path / "p"),
                timeout=5,
                transport=httpx.MockTransport(broken),
            )
        )

        class BwikiStub:
            source = "bwiki"

            async def search(self, query, question=""):
                return {"status": "ok", "title": query, "game": "ww"}

            async def read(self, page_id, question="", section="", *, source=""):
                return {"status": "ok", "title": str(page_id), "game": "ww"}

            async def clear_parse_cache(self):
                return 0

            def stats(self):
                return {"upstream_requests": 0, "cache_hits": 0, "errors": {}}

        router = WuwaSources(primary, BwikiStub(), timeout=5)
        try:
            result = await router.search("今汐")
            assert result["source_key"] == "bwiki"
            assert result["fallback_from"] == "kurobbs"
            assert router.fallbacks == 1
            with pytest.raises(WikiError) as exc:
                await router.read(1, source="prts")
            assert exc.value.code == "bad_input"
        finally:
            await primary.close()

    asyncio.run(run())
