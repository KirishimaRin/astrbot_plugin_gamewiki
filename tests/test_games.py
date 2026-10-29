"""Multi-game profile, cache isolation and URL tests."""

import unittest
from urllib.parse import quote

import httpx

from wiki.cache import Cache
from wiki.client import WikiClient
from wiki.games import PROFILES, YS, parse_alias_config
from wiki.models import Section, page_url
from wiki.query import QueryService


def test_profiles_cover_five_games_with_unique_commands():
    assert set(PROFILES) == {"ys", "sr", "zzz", "arknights", "zmd"}
    commands = [p.command for p in PROFILES.values()]
    assert len(commands) == len(set(commands))
    assert commands == ["ys", "sr", "zzz", "ark", "zmd"]
    assert all(not profile.aliases for profile in PROFILES.values())
    assert YS.card_words, "only the Genshin profile routes card lookups"
    for code, profile in PROFILES.items():
        if code != "ys":
            assert not profile.card_words


def test_page_url_uses_the_game_code():
    assert page_url("纳西妲", code="ys").startswith("https://wiki.biligame.com/ys/")
    assert page_url("流萤", code="sr").startswith("https://wiki.biligame.com/sr/")
    assert page_url("能天使", "基本属性", "arknights").startswith(
        "https://prts.wiki/w/"
    )
    assert page_url("能天使", code="arknights", source="bwiki").startswith(
        "https://wiki.biligame.com/arknights/"
    )
    assert page_url("能天使", "基本属性", "arknights").endswith("#" + quote("基本属性"))


class TestGameIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        from pathlib import Path

        self.temp = tempfile.TemporaryDirectory()
        self.cache = Cache(Path(self.temp.name))
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        self.temp.cleanup()

    def client(self, game, handler):
        client = WikiClient(
            self.cache,
            timeout=1,
            transport=httpx.MockTransport(handler),
            game=game,
        )
        self.clients.append(client)
        return client

    async def test_same_params_on_two_wikis_do_not_share_cache(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, json={"query": {"search": []}})

        ys = self.client("ys", handler)
        sr = self.client("sr", handler)
        await ys.request({"action": "query"}, 600)
        await sr.request({"action": "query"}, 600)
        assert len(calls) == 2, "different wikis must not share a cache entry"
        assert "/ys/api.php" in calls[0] and "/sr/api.php" in calls[1]
        await ys.request({"action": "query"}, 600)
        assert len(calls) == 2  # ys hit its own cache

    async def test_service_uses_profile_url_and_keeps_aliases_local(self):
        class FakeClient:
            def __init__(self):
                self.requests = []

            def stats(self):
                return {
                    "upstream_requests": 0,
                    "cache_hits": 0,
                    "coalesced": 0,
                    "errors": {},
                }

            async def request(self, params, ttl):
                self.requests.append(params)
                if params["action"] == "query":
                    return {"query": {"search": [{"title": "流萤", "pageid": 7}]}}
                return {
                    "_fetched_at": "2026-10-26",
                    "parse": {
                        "title": "流萤",
                        "pageid": 7,
                        "revid": 1,
                        "text": "<h2>角色晋阶材料</h2><p>晋阶材料列表。</p>",
                    },
                }

        client = FakeClient()
        service = QueryService(
            client,
            profile=PROFILES["sr"],
            aliases={"流氓兔": "流萤"},
        )
        assert service.normalize("草神") == "草神", "Genshin nicknames must not leak"
        assert service.normalize("流氓兔") == "流萤"
        result = await service.search("流萤", "晋阶材料")
        assert result["game"] == "sr"
        assert result["url"].startswith("https://wiki.biligame.com/sr/")
        assert result["evidence"][0]["url"].startswith("https://wiki.biligame.com/sr/")
        await service.search("流萤", "七圣召唤卡牌技能")
        searches = [r for r in client.requests if r["action"] == "query"]
        assert searches[-1]["srsearch"] == "流萤", "sr has no card routing"


def test_alias_config_splits_global_and_per_game_entries():
    global_map, game_map = parse_alias_config(
        ["草神=纳西妲", "ys:牙膏=珊瑚宫心海", "sr:刃=刃", "坏行", "ys:=空名", "=空键"]
    )
    assert global_map == {"草神": "纳西妲"}
    assert game_map == {"ys": {"牙膏": "珊瑚宫心海"}, "sr": {"刃": "刃"}}


def test_user_alias_does_not_leak_across_games():
    global_map, game_map = parse_alias_config(["ys:草神=纳西妲"])
    assert "草神" not in global_map and "sr" not in game_map


def test_zmd_generic_skill_question_reaches_akedata_skill_sections():
    from wiki.selection import evidence

    sections = [
        Section("基本信息", "info", ["干员基础信息。"]),
        Section("战技 / 惊霆诀", "skill1", ["战技描述与等级数值。"]),
        Section("终结技 / 万钧风雷", "ult", ["终结技描述与等级数值。"]),
        Section("普通攻击 / 疾电法", "basic", ["普攻描述。"]),
        Section("培养材料", "mat", ["突破材料清单。"]),
    ]
    for question in ("庄方宜技能", "庄方宜倍率", "庄方宜伤害"):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "庄方宜",
            PROFILES["zmd"].intents,
            PROFILES["zmd"].specifics,
        )
        picked = {item["section"] for item in snippets}
        assert picked == {"战技 / 惊霆诀", "终结技 / 万钧风雷", "普通攻击 / 疾电法"}, (
            question
        )
        assert selection["mode"] != "fallback", question


def test_zmd_specific_material_question_still_routes_to_materials():
    from wiki.selection import evidence

    sections = [
        Section("战技 / 惊霆诀", "skill1", ["战技描述。"]),
        Section("培养材料", "mat", ["龙门币 × 120000"]),
    ]
    snippets, _, _ = evidence(
        sections,
        "庄方宜技能材料",
        3000,
        "",
        "庄方宜",
        PROFILES["zmd"].intents,
        PROFILES["zmd"].specifics,
    )
    assert [item["section"] for item in snippets] == ["培养材料"]


def test_sr_generic_skill_words_reach_the_trace_section():
    from wiki.selection import evidence

    # BWIKI 星铁页面的「天赋 / …效果加成」分节是星魂/额外能力加成，
    # 技能数值本体只在「行迹」。
    sections = [
        Section("概览", "intro", ["角色概览。"]),
        Section(
            "行迹",
            "trace",
            ["自破碎的天空坠落，造成火属性伤害 120%。"],
        ),
        Section("星魂", "eidolon", ["星魂效果。"]),
        Section(
            "天赋 / 固有天赋 / α模组-偏时迸发 效果加成 [额外能力1]",
            "extra1",
            ["额外能力效果加成。"],
        ),
        Section("角色晋阶材料", "mat1", ["思绪末屑 ×5"]),
        Section("技能晋阶材料", "mat2", ["步离犬牙 ×3"]),
    ]
    for question in ("流萤技能", "流萤战技", "流萤天赋", "流萤行迹", "流萤终结技"):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "流萤",
            PROFILES["sr"].intents,
            PROFILES["sr"].specifics,
        )
        assert [item["section"] for item in snippets] == ["行迹"], question
        assert selection["mode"] != "fallback", question


def test_sr_material_questions_still_route_to_material_sections():
    from wiki.selection import evidence

    sections = [
        Section("行迹", "trace", ["战技倍率。"]),
        Section("角色晋阶材料", "mat1", ["思绪末屑 ×5"]),
        Section("技能晋阶材料", "mat2", ["步离犬牙 ×3"]),
    ]
    for question, expected in (
        ("流萤突破材料", "角色晋阶材料"),
        ("流萤技能材料", "技能晋阶材料"),
        ("流萤技能升级", "技能晋阶材料"),
    ):
        snippets, _, _ = evidence(
            sections,
            question,
            3000,
            "",
            "流萤",
            PROFILES["sr"].intents,
            PROFILES["sr"].specifics,
        )
        assert expected in [item["section"] for item in snippets], question


def test_ark_story_question_reaches_the_archive_section():
    from wiki.selection import evidence

    # PRTS 干员页没有「角色故事」分节；「干员模组」只承载模块剧情。
    sections = [
        Section("概览", "intro", ["干员概览。"]),
        Section("干员模组", "mod", ["模组故事：某段剧情。"]),
        Section("人员档案", "archive", ["基础档案与故事正文。"]),
        Section("技能", "skill", ["技能说明。"]),
    ]
    for question in ("能天使故事", "能天使背景", "能天使档案"):
        snippets, _, _ = evidence(
            sections,
            question,
            3000,
            "",
            "能天使",
            PROFILES["arknights"].intents,
            PROFILES["arknights"].specifics,
        )
        assert [item["section"] for item in snippets] == ["人员档案"], question


def test_every_game_profile_declares_a_card_accent():
    for profile in PROFILES.values():
        assert len(profile.accent) == 3, profile.code
        assert all(0 <= channel <= 255 for channel in profile.accent), profile.code
