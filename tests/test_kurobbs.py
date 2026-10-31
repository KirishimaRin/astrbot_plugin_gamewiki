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
from wiki.games import PROFILES
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
    # 推荐模块的四个 tab 各自成节，复合问句才不会被武器推荐正文挤掉。
    assert titles == ["基本信息", "武器推荐", "声骸推荐", "语音"]
    assert image == "https://img.example/lihui.png"
    assert "时和岁稔＞苍鳞千嶂" in sections[1].blocks[0]
    assert "毕业配装 | 浮星祛暗2+5" in sections[2].blocks[0]
    voice = sections[3]
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
            assert "声骸推荐" in result["available_sections"]
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


def test_list_catalogue_prefers_the_longer_category_name():
    from wiki.kurobbs import _list_catalogue

    # 「声骸合鸣有哪些」必须命中合鸣（1219），不能被更短的「声骸」抢走。
    assert _list_catalogue("声骸合鸣有哪些") == 1219
    assert _list_catalogue("声骸有哪些") == 1107
    assert _list_catalogue("武器图鉴") == 1106
    assert _list_catalogue("今汐") == 0


def test_split_aspect_moves_trailing_aspect_into_the_question():
    from wiki.kurobbs import _split_aspect

    assert _split_aspect("今汐共鸣链效果") == ("今汐", "共鸣链效果")
    assert _split_aspect("今汐武器") == ("今汐", "武器")
    # 词条名本身以方面词开头时不拆。
    assert _split_aspect("声骸系统入门") == ("声骸系统入门", "")


def test_level_and_skill_blocks_are_filtered_to_the_asked_one():
    from wiki.models import Section
    from wiki.kurobbs import _prefer_level_block, _prefer_skill_block

    level = Section(
        "等级属性", "", ["【1级】\n基础生命 866", "【90级】\n基础生命 10825"]
    )
    _prefer_level_block([level], "毕业面板")
    assert level.blocks == ["【90级】\n基础生命 10825"]

    skills = Section(
        "技能详情",
        "",
        ["【常态攻击】\n普攻", "【共鸣解放】\n移岁诛邪", "【延奏技能】\n驭时"],
    )
    _prefer_skill_block([skills], "共鸣解放倍率")
    assert skills.blocks == ["【共鸣解放】\n移岁诛邪"]

    skills2 = Section("技能详情", "", ["【常态攻击】\n普攻", "【共鸣解放】\n移岁诛邪"])
    _prefer_skill_block([skills2], "普攻倍率")
    assert skills2.blocks == ["【常态攻击】\n普攻"]


def test_catalogue_list_reads_the_whole_category(tmp_path):
    def handler(request):
        if request.url.path == "/wiki/core/catalogue/item/getPage":
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "results": {
                            "records": [
                                {"id": 1, "name": "彻空冥雷"},
                                {"id": 2, "name": "浮星祛暗"},
                                {"id": 3, "name": "彻空冥雷"},
                            ]
                        }
                    },
                },
            )
        return httpx.Response(404, json={})

    async def run():
        client = make_client(tmp_path, handler)
        service = KuroBbsService(client)
        try:
            result = await service.search("声骸合鸣", "有哪些")
            assert result["status"] == "ok"
            assert result["page_id"] == 1219
            assert "共 2 项" in result["evidence"][0]["text"]
            assert "彻空冥雷" in result["evidence"][0]["text"]
            # page_id 是分类号，补读可重建同一份清单。
            again = await service.read(1219)
            assert again["status"] == "ok"
            assert "浮星祛暗" in again["evidence"][0]["text"]
        finally:
            await client.close()

    asyncio.run(run())


def test_profile_aliases_apply_to_the_kurobbs_service(tmp_path):
    client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
    service = KuroBbsService(client)
    assert service.aliases["汐汐"] == "今汐"
    assert service.aliases["深塔"] == "逆境深塔"
    asyncio.run(client.close())


HOMEPAGE = {
    "code": 200,
    "data": {
        "contentJson": {
            "sideModules": [
                {
                    "title": "角色活动唤取",
                    "content": {
                        "tabs": [
                            {
                                "name": "测试角色池",
                                "countDown": {
                                    "dateRange": [
                                        "2026-10-22 10:00",
                                        "2026-11-11 11:59",
                                    ]
                                },
                                "imgs": [
                                    {"linkConfig": {"entryId": "1001"}},
                                    {"linkConfig": {"entryId": "1002"}},
                                ],
                            }
                        ]
                    },
                },
                {
                    "title": "武器活动唤取",
                    "content": {
                        "tabs": [
                            {
                                "name": "测试武器池",
                                "countDown": {
                                    "dateRange": [
                                        "2026-10-22 10:00",
                                        "2026-11-11 11:59",
                                    ]
                                },
                                "imgs": [{"linkConfig": {"entryId": "2001"}}],
                            }
                        ]
                    },
                },
            ]
        }
    },
}
CATALOGUE_RECORDS = {
    1105: [
        {"name": "甲", "content": {"linkId": "1001", "star": "5"}},
        {"name": "乙", "content": {"linkId": "1002", "star": "4"}},
    ],
    1106: [{"name": "乙武", "content": {"linkId": "2001", "star": "5"}}],
}


def banner_handler(request):
    path = request.url.path
    if path == "/wiki/core/homepage/getPage":
        return httpx.Response(200, json=HOMEPAGE)
    if path == "/wiki/core/catalogue/item/getPage":
        form = parse_qs(request.content.decode("utf-8"))
        cid = int(form["catalogueId"][0])
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {"results": {"records": CATALOGUE_RECORDS.get(cid, [])}},
            },
        )
    return httpx.Response(404, json={})


def test_current_banners_come_from_the_official_homepage(tmp_path):
    async def run():
        client = make_client(tmp_path, banner_handler)
        service = KuroBbsService(client)
        try:
            result = await service.search("现在UP什么")
            assert result["status"] == "ok"
            assert result["page_id"] == 900001
            assert result["available_sections"] == ["角色活动唤取", "武器活动唤取"]
            text = "\n".join(item["text"] for item in result["evidence"])
            assert "测试角色池" in text and "甲（5★）" in text
            assert "2026-10-22 10:00 ~ 2026-11-11 11:59" in text
            assert "测试武器池" in text and "乙武（5★）" in text
            # 武器池只给武器唤取，角色池只给角色唤取。
            weapon = await service.search("武器池")
            assert [i["section"] for i in weapon["evidence"]] == ["武器活动唤取"]
            character = await service.search("角色池")
            assert [i["section"] for i in character["evidence"]] == ["角色活动唤取"]
            # 补读同一个 page_id 可重建。
            again = await service.read(900001)
            assert again["status"] == "ok"
            assert "测试角色池" in again["evidence"][0]["text"]
        finally:
            await client.close()

    asyncio.run(run())


def test_router_keeps_primary_not_found_when_fallback_errors(tmp_path):
    class NotFoundPrimary:
        source = "kurobbs"
        aliases = {}
        profile = PROFILES["ww"]

        async def search(self, query, question=""):
            return {"status": "not_found", "query": query, "message": "未找到"}

        async def read(self, page_id, question="", section="", *, source=""):
            return {"status": "not_found"}

        async def clear_parse_cache(self):
            return 0

        def stats(self):
            return {"upstream_requests": 0, "cache_hits": 0, "errors": {}}

    class BrokenFallback(NotFoundPrimary):
        async def search(self, query, question=""):
            raise WikiError("upstream", "BWIKI 服务暂时异常，请稍后重试。")

    async def run():
        router = WuwaSources(NotFoundPrimary(), BrokenFallback(), timeout=5)
        result = await router.search("不存在的词")
        # 主源已判定未找到，兜底源故障不该把结论变成上游错误。
        assert result["status"] == "not_found"
        assert result["source_key"] == "kurobbs"

    asyncio.run(run())


TREE = {
    "code": 200,
    "data": {
        "id": 9,
        "name": "全部",
        "children": [
            {
                "id": 1293,
                "name": "活动合集",
                "children": [
                    {"id": 1631, "name": "3.6版本活动", "children": []},
                    {"id": 1643, "name": "3.7版本活动", "children": []},
                ],
            }
        ],
    },
}


def activity_handler(request):
    path = request.url.path
    if path == "/wiki/core/catalogue/config/getTree":
        return httpx.Response(200, json=TREE)
    if path == "/wiki/core/catalogue/item/getPage":
        form = parse_qs(request.content.decode("utf-8"))
        cid = int(form["catalogueId"][0])
        records = {
            1643: [
                {"name": "「朝月赠礼」活动说明"},
                {"name": "「心影映花」活动说明"},
                {"name": "「朝月赠礼」活动说明"},
            ]
        }.get(cid, [])
        return httpx.Response(
            200, json={"code": 200, "data": {"results": {"records": records}}}
        )
    return httpx.Response(404, json={})


def test_current_version_activities_use_the_newest_tree_node(tmp_path):
    async def run():
        client = make_client(tmp_path, activity_handler)
        service = KuroBbsService(client)
        try:
            result = await service.search("现在有什么活动")
            assert result["status"] == "ok"
            assert result["page_id"] == 900002
            # 取 id 最大的版本节点（3.7），不是 3.6。
            assert result["title"] == "3.7版本活动"
            text = result["evidence"][0]["text"]
            assert "共 2 项" in text
            assert "朝月赠礼" in text and "心影映花" in text
            again = await service.read(900002)
            assert again["status"] == "ok"
            assert "3.7版本活动" == again["title"]
        finally:
            await client.close()

    asyncio.run(run())


def test_activity_item_questions_do_not_hit_the_activity_list(tmp_path):
    from wiki.kurobbs import _activity_question

    assert _activity_question("现在有什么活动")
    assert not _activity_question("活动道具有哪些")
    assert not _activity_question("朝月赠礼活动说明")


def test_prefixed_candidates_pick_the_richest_entry(tmp_path):
    """两三条前缀候选时探测详情，自动读内容最丰富的；空壳词条仍回候选。"""
    search_payloads = {
        "声骸系统": {
            "code": 200,
            "data": {
                "results": {
                    "records": [
                        {
                            "id": 1,
                            "name": "声骸系统详解",
                            "content": {
                                "type": "horizontal-figure",
                                "title": "声骸系统详解",
                                "linkId": "301",
                            },
                        },
                        {
                            "id": 2,
                            "name": "声骸系统入门",
                            "content": {
                                "type": "horizontal-figure",
                                "title": "声骸系统入门",
                                "linkId": "302",
                            },
                        },
                    ]
                }
            },
        },
        "索拉等级": {
            "code": 200,
            "data": {
                "results": {
                    "records": [
                        {
                            "id": 1,
                            "name": "索拉等级提升・一",
                            "content": {
                                "type": "text-list-small",
                                "title": "索拉等级提升・一",
                                "linkId": "401",
                            },
                        },
                        {
                            "id": 2,
                            "name": "索拉等级提升・二",
                            "content": {
                                "type": "text-list-small",
                                "title": "索拉等级提升・二",
                                "linkId": "402",
                            },
                        },
                    ]
                }
            },
        },
    }
    details = {
        301: {
            "code": 200,
            "data": {
                "content": {
                    "title": "声骸系统详解",
                    "modules": [
                        {
                            "title": "概览",
                            "components": [{"content": "<p>详解正文</p>"}],
                        }
                    ],
                }
            },
        },
        302: {
            "code": 200,
            "data": {
                "content": {
                    "title": "声骸系统入门",
                    "modules": [
                        {
                            "title": "概览",
                            "components": [{"content": "<p>入门正文更丰富</p>"}],
                        },
                        {
                            "title": "进阶",
                            "components": [{"content": "<p>进阶说明</p>"}],
                        },
                    ],
                }
            },
        },
        # 401/402 有意缺席：详情 404 走 WikiError → 视为空壳。
    }

    def handler(request):
        path = request.url.path
        if path == "/wiki/core/catalogue/item/search":
            form = parse_qs(request.content.decode("utf-8"))
            keyword = form["keyword"][0]
            return httpx.Response(200, json=search_payloads[keyword])
        if path == "/wiki/core/catalogue/item/getEntryDetail":
            form = parse_qs(request.content.decode("utf-8"))
            entry_id = int(form["id"][0])
            payload = details.get(entry_id)
            if payload is None:
                return httpx.Response(
                    200, json={"code": 2031, "msg": "当前词条不存在", "data": None}
                )
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    async def run():
        client = make_client(tmp_path, handler)
        service = KuroBbsService(client)
        try:
            result = await service.search("声骸系统")
            assert result["status"] == "ok"
            # 两篇都有正文：取模块更多的「入门」。
            assert result["title"] == "声骸系统入门"
            # 空壳词条（详情不存在）不自动读，交回候选。
            stub = await service.search("索拉等级")
            assert stub["status"] == "needs_choice"
            assert {c["title"] for c in stub["candidates"]} == {
                "索拉等级提升・一",
                "索拉等级提升・二",
            }
        finally:
            await client.close()

    asyncio.run(run())


def test_system_concept_aliases_resolve_on_the_primary(tmp_path):
    client = make_client(tmp_path, kuro_handler(SEARCH_RECORDS))
    service = KuroBbsService(client)
    assert service.aliases["深渊"] == "逆境深塔"
    assert service.aliases["每日任务"] == "活跃度"
    assert service.aliases["体力"] == "结晶溶剂"
    assert service.aliases["数据坞"] == "数据坞等级"
    asyncio.run(client.close())
