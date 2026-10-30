"""Multi-game profile, cache isolation and URL tests."""

import unittest
from urllib.parse import quote

import httpx

from wiki.cache import Cache
from wiki.client import WikiClient
from wiki.games import (
    PROFILES,
    YS,
    normalize_slang,
    parse_alias_config,
    source_api,
)
from wiki.models import Section, page_url
from wiki.query import QueryService


def test_profiles_cover_seven_games_with_unique_commands():
    assert set(PROFILES) == {"ys", "sr", "zzz", "arknights", "zmd", "sts2", "ww"}
    commands = [p.command for p in PROFILES.values()]
    assert len(commands) == len(set(commands))
    assert commands == ["ys", "sr", "zzz", "ark", "zmd", "sts2", "ww"]
    assert all(not profile.aliases for profile in PROFILES.values())
    assert YS.card_words, "only the Genshin profile routes card lookups"
    for code, profile in PROFILES.items():
        if code != "ys":
            assert not profile.card_words


def test_ww_profile_targets_the_wutheringwaves_site():
    assert PROFILES["ww"].name == "鸣潮"
    assert source_api("ww", "bwiki") == (
        "https://wiki.biligame.com/wutheringwaves/api.php"
    )
    assert page_url("共鸣者/今汐", code="ww") == (
        "https://wiki.biligame.com/wutheringwaves/"
        "%E5%85%B1%E9%B8%A3%E8%80%85/%E4%BB%8A%E6%B1%90"
    )
    # 链类黑话只在后缀位归一，前缀形式保持原样让实体可检索。
    assert normalize_slang("今汐六链效果", PROFILES["ww"]) == "今汐共鸣链效果"
    assert normalize_slang("满链今汐怎么样", PROFILES["ww"]) == "满链今汐怎么样"
    assert normalize_slang("今汐大招倍率", PROFILES["ww"]) == "今汐共鸣解放倍率"


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
    for question in (
        "流萤技能",
        "流萤战技",
        "流萤天赋",
        "流萤行迹",
        "流萤终结技",
        "流萤秘技",
    ):
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


def test_ark_archive_and_stats_cover_both_source_heading_schemes():
    from wiki.selection import evidence

    for archive, stats in (("干员档案", "属性"), ("人员档案", "基本属性")):
        sections = [
            Section("基本信息", "", ["阵营与姓名。"]),
            Section(archive, "", ["故事正文。"]),
            Section(stats, "", ["生命与攻击。"]),
        ]
        for question, expected in (("故事", archive), ("属性", stats)):
            snippets, _, meta = evidence(
                sections,
                question,
                4000,
                "",
                "能天使",
                PROFILES["arknights"].intents,
                PROFILES["arknights"].specifics,
            )
            assert [s["section"] for s in snippets] == [expected]
            assert meta["mode"] == "focused"


def test_prts_skill_unlock_navigation_does_not_displace_skill_three():
    from wiki.selection import evidence

    sections = [
        Section(
            "技能",
            "",
            ["技能1（精英0开放）", "技能2（精英1开放）", "技能3（精英2开放）"],
        ),
        *[
            Section(f"技能 / 技能{i}", "技能", [f"技能{i}的效果。倍率120%。"])
            for i in range(1, 4)
        ],
    ]
    snippets, _, _ = evidence(
        sections,
        "技能",
        6000,
        "",
        "能天使",
        PROFILES["arknights"].intents,
        PROFILES["arknights"].specifics,
    )
    assert [s["section"] for s in snippets] == [
        "技能 / 技能1",
        "技能 / 技能2",
        "技能 / 技能3",
    ]


def test_ys_specific_skill_and_ascension_questions_do_not_include_other_sections():
    from wiki.selection import evidence

    sections = [
        Section("突破", "", ["摩拉 × 20000"]),
        Section("技能升级材料", "", ["摩拉 × 12500"]),
        Section("天赋 / 普通攻击", "", ["普攻伤害。"]),
        Section(
            "天赋 / 固有天赋 / 某能力 角色突破等级1解锁", "", ["突破时解锁的被动。"]
        ),
        Section("天赋 / 元素战技", "", ["战技伤害。"]),
    ]
    for question, expected in (
        ("突破材料", "突破"),
        ("元素战技10级倍率", "天赋 / 元素战技"),
    ):
        snippets, _, _ = evidence(
            sections,
            question,
            6000,
            "",
            "纳西妲",
            PROFILES["ys"].intents,
            PROFILES["ys"].specifics,
        )
        assert [s["section"] for s in snippets] == [expected]


def test_bwiki_operator_css_grids_preserve_levels_and_skill_boundaries():
    html = '<h2><span id="技能">技能</span></h2>' + "".join(
        f'<div class="switch-tab-content operator"><p>技能名{i} 自动回复 自动触发</p><div class="skill-table-grid skill-table-header"><div>等级</div><div>描述</div><div>初始</div><div>消耗</div><div>持续</div></div><div class="skill-table-grid"><div>1</div><div>攻击变为{i}连射</div><div>20</div><div>50</div><div>15</div></div></div>'
        for i in range(1, 4)
    )
    from wiki.extractor import extract_sections

    sections = extract_sections(html, "干员", prefix="arknights", source="bwiki")
    skill = next(s for s in sections if s.title == "技能 / 技能3")
    assert "1 | 攻击变为3连射 | 20 | 50 | 15" in "\n".join(skill.blocks)
    assert "自动触发" in "\n".join(skill.blocks)


def test_sr_eidolon_question_reaches_the_eidolon_table():
    from wiki.selection import evidence

    # 星魂数值本体是独立的「星魂」表；「天赋 / …效果加成 [星魂N]」只是
    # 单魂加成详情，不得因问题带“效果”而压过本体。
    sections = [
        Section("概览", "intro", ["角色概览。"]),
        Section("行迹", "trace", ["战技倍率 120%。"]),
        Section(
            "星魂", "eidolon", ["名称 | 效果\n我曾安眠，赤染之茧 | 无视目标15%的防御"]
        ),
        Section(
            "天赋 / 元素战技 / 自破碎的天空坠落 效果加成 [星魂2]",
            "eidolon2",
            ["施放强化战技时无视目标15%的防御。"],
        ),
    ]
    for question in ("流萤星魂", "流萤星魂效果"):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "流萤",
            PROFILES["sr"].intents,
            PROFILES["sr"].specifics,
        )
        assert [item["section"] for item in snippets] == ["星魂"], question
        assert selection["mode"] != "fallback", question


def test_ys_constellation_question_reaches_the_constellation_section():
    from wiki.selection import evidence

    sections = [
        Section("概览", "intro", ["角色概览。"]),
        Section("命之座", "constellation", ["1命 | 效果描述"]),
        Section("天赋 / 元素战技", "skill", ["战技伤害。"]),
    ]
    for question in ("纳西妲命之座", "纳西妲命座", "纳西妲命之座效果"):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "纳西妲",
            PROFILES["ys"].intents,
            PROFILES["ys"].specifics,
        )
        assert [item["section"] for item in snippets] == ["命之座"], question
        assert selection["mode"] != "fallback", question


def test_zzz_cinema_and_core_passive_questions_route_to_their_sections():
    from wiki.selection import evidence

    sections = [
        Section("概览", "intro", ["角色概览。"]),
        Section("意象影画", "cinema", ["1画 | 效果描述"]),
        Section("天赋 / 固有天赋 / 核心被动：凌牙厉齿", "passive", ["被动效果描述。"]),
        Section("技能", "skill", ["特殊技描述。"]),
    ]
    for question, expected in (
        ("艾莲影画", "意象影画"),
        ("艾莲影画效果", "意象影画"),
        ("艾莲核心被动", "天赋 / 固有天赋 / 核心被动：凌牙厉齿"),
        ("艾莲核心被动效果", "天赋 / 固有天赋 / 核心被动：凌牙厉齿"),
    ):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "艾莲",
            PROFILES["zzz"].intents,
            PROFILES["zzz"].specifics,
        )
        assert [item["section"] for item in snippets] == [expected], question
        assert selection["mode"] != "fallback", question


def test_ark_base_skill_question_reaches_both_source_sections():
    from wiki.selection import evidence

    # PRTS 叫「后勤技能」、BWIKI 叫「基建技能」，同一个问题两源都要命中。
    prts = [
        Section("技能", "skill", ["技能导航。"]),
        Section("技能 / 技能1", "skill1", ["等级 | 描述\n1 | 3连射"]),
        Section("技能 / 技能2", "skill2", ["等级 | 描述\n1 | 4连射"]),
        Section("技能 / 技能3", "skill3", ["等级 | 描述\n1 | 5连射"]),
        Section(
            "后勤技能",
            "base",
            ["条件 | 房间 | 描述\n精英0 | 贸易站 | 订单获取效率 +20%"],
        ),
    ]
    bwiki = prts[:-1] + [
        Section(
            "基建技能",
            "base",
            ["条件 | 房间 | 描述\n精英0 | 贸易站 | 订单获取效率 +20%"],
        )
    ]
    for sections, expected in ((prts, "后勤技能"), (bwiki, "基建技能")):
        for question in ("能天使基建技能", "能天使后勤技能", "能天使基建"):
            snippets, _, selection = evidence(
                sections,
                question,
                3000,
                "",
                "能天使",
                PROFILES["arknights"].intents,
                PROFILES["arknights"].specifics,
            )
            assert [item["section"] for item in snippets] == [expected], question
            assert selection["mode"] != "fallback", question


def test_pool_redirect_pages_cover_four_games():
    assert PROFILES["ys"].pool_pages[0][1] == "祈愿"
    assert "卡池" in PROFILES["ys"].pool_pages[0][0]
    assert PROFILES["sr"].pool_pages[0][1] == "跃迁"
    assert PROFILES["zzz"].pool_pages[0][1] == "调频"
    # 方舟双映射：保底先命中「寻访规则」，其余寻访类走「卡池一览」。
    assert PROFILES["arknights"].pool_pages[0] == (("保底",), "寻访规则")
    assert PROFILES["arknights"].pool_pages[1][1] == "卡池一览"
    # 终末地各站没有卡池聚合页。
    assert not PROFILES["zmd"].pool_pages


def test_pool_questions_route_to_their_pool_sections():
    from wiki.selection import evidence

    # 「祈愿」聚合页分节：机制分节不在 pool intents 行里，机制类问题
    # 靠自然评分命中；列表型问题按标题段子集路由，历史兜底承接复刻。
    sections = [
        Section("概览", "intro", ["祈愿介绍。"]),
        Section("简介 / 祈愿机制 / 保底机制", "mech", ["卡池90抽必出五星。"]),
        Section("祈愿池一览 / 活动祈愿（当前）", "current", ["本期UP：玛薇卡。"]),
        Section("祈愿池一览 / 常驻祈愿", "standard", ["常驻祈愿池。"]),
        Section("历史活动祈愿一览", "history", ["纳西妲复刻记录。"]),
    ]
    for question, first in (
        ("当前卡池有什么", "祈愿池一览 / 活动祈愿（当前）"),
        ("纳西妲复刻了吗", "历史活动祈愿一览"),
        ("卡池保底是多少", "简介 / 祈愿机制 / 保底机制"),
    ):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "祈愿",
            PROFILES["ys"].intents,
            PROFILES["ys"].specifics,
        )
        assert snippets, question
        assert snippets[0]["section"] == first, question
        assert selection["mode"] != "fallback", question


def test_ark_pool_questions_reach_the_pool_hub_table():
    from wiki.selection import evidence

    # PRTS「卡池一览」分节：列表型寻访问题落进限时寻访表（新池子在前，
    # 由提示词里的 now 按日期范围匹配当前池）。
    sections = [
        Section("概览", "intro", ["卡池一览介绍。"]),
        Section(
            "限时寻访", "limited", ["海渊巡游 | 2026-10-09 12:00~ 2026-10-23 03:59"]
        ),
        Section("常驻标准寻访", "standard", ["常驻池构成。"]),
        Section("常驻中坚寻访&中坚甄选", "mid", ["中坚池构成。"]),
        Section("新人特惠寻访", "newbie", ["新人池构成。"]),
    ]
    for question in ("当前卡池有什么", "当前寻访有什么", "卡池UP是谁"):
        snippets, _, selection = evidence(
            sections,
            question,
            3000,
            "",
            "卡池一览",
            PROFILES["arknights"].intents,
            PROFILES["arknights"].specifics,
        )
        assert snippets, question
        assert snippets[0]["section"] == "限时寻访", question
        assert selection["mode"] != "fallback", question


def test_modifier_slang_keeps_prefix_entities_searchable():
    """前缀位置的修饰语不替换，实体保持可检索。"""
    from wiki.assistant import fallback_intent
    from wiki.games import game_words, normalize_slang

    # 满命/一命/六命 直接跟实体名时替换会把修饰语焊进实体（“命之座魈”）。
    cases = (
        ("满命魈强度怎么样", "ys", "命之座魈"),
        ("一命那维莱特面板", "ys", "命之座那维莱特"),
        ("六命钟离配装", "ys", "命之座钟离"),
        ("1魂流萤", "sr", "星魂流萤"),
        ("2画艾莲", "zzz", "意象影画艾莲"),
        ("专三能天使", "arknights", "专精能天使"),
        ("精二陈", "arknights", "精英化陈"),
    )
    for raw, code, fused in cases:
        text = normalize_slang(raw, PROFILES[code])
        assert text == raw and fused not in text, raw
    # 保护之后问题仍按实体切分：方面词（强度/面板/配装）承接拆分。
    assert fallback_intent("满命魈强度怎么样", (), game_words("ys"))[0] == "满命魈"
    assert (
        fallback_intent("一命那维莱特面板", (), game_words("ys"))[0] == "一命那维莱特"
    )
    assert fallback_intent("六命钟离配装", (), game_words("ys"))[0] == "六命钟离"


def test_modifier_slang_still_rewrites_suffix_positions():
    """后缀位置（实体名之后）的修饰语照常归一，不因保护而漏改。"""
    from wiki.games import normalize_slang

    cases = (
        ("纳西妲一命效果", "纳西妲命之座效果", "ys"),
        ("流萤二魂效果", "流萤星魂效果", "sr"),
        ("钟离满命配装", "钟离命之座配装", "ys"),
        ("纳西妲满命了吗", "纳西妲命之座了吗", "ys"),
        ("满命需要多少材料", "命之座需要多少材料", "ys"),
        ("流萤满魂伤害", "流萤星魂伤害", "sr"),
        ("艾莲2画", "艾莲意象影画", "zzz"),
        ("能天使专三材料", "能天使专精材料", "arknights"),
        # 比较连接词也是安全后缀：两侧归一成同一词后退回通用提示。
        ("精一和精二哪个好", "精英化和精英化哪个好", "arknights"),
    )
    for raw, expected, code in cases:
        assert normalize_slang(raw, PROFILES[code]) == expected, raw


def test_time_slang_adds_today_and_this_round():
    from wiki.games import normalize_slang

    for raw in ("现在卡池有什么", "今天卡池有什么", "这期卡池有什么", "本期卡池有什么"):
        assert normalize_slang(raw, PROFILES["ys"]) == "当前卡池有什么", raw
    assert normalize_slang("最新up池有什么", PROFILES["sr"]) == "当前up池有什么"


def test_pool_words_cover_lowercase_up():
    # “UP池”的大小写变体也要触发池子重定向与池 intents 行。
    for code in ("ys", "sr", "zzz"):
        words = [w for entry in PROFILES[code].pool_pages for w in entry[0]]
        assert "up池" in words, code
    for code in ("ys", "sr", "zzz", "arknights"):
        triggers = [t for row in PROFILES[code].intents for t in row[0]]
        assert "up" in triggers, code


def test_constellation_and_potential_shorthand_normalizes():
    """0命/几命/满潜 等玩家简写与一~六命同一套归一。"""
    from wiki.games import normalize_slang

    cases = (
        ("胡桃0命能用吗", "胡桃命之座能用吗", "ys"),
        ("胡桃几命", "胡桃命之座", "ys"),
        ("流萤0魂能用吗", "流萤星魂能用吗", "sr"),
        ("流萤几魂", "流萤星魂", "sr"),
        ("安比几画", "安比意象影画", "zzz"),
        ("安比满画", "安比意象影画", "zzz"),
        ("能天使满潜", "能天使潜能", "arknights"),
        ("能天使几潜", "能天使潜能", "arknights"),
    )
    for raw, expected, code in cases:
        assert normalize_slang(raw, PROFILES[code]) == expected, raw
    # 前缀位置仍保护实体（“0命胡桃”不是“命之座胡桃”）。
    assert normalize_slang("0命胡桃", PROFILES["ys"]) == "0命胡桃"
    assert normalize_slang("满潜银灰", PROFILES["arknights"]) == "满潜银灰"


def test_equipment_slang_maps_to_each_game_weapon_term():
    from wiki.games import normalize_slang

    for code, term in (("ys", "武器"), ("sr", "光锥"), ("zzz", "音擎")):
        assert normalize_slang("纳西妲专武是什么", PROFILES[code]) == (
            f"纳西妲{term}是什么"
        ), code
    # 满精=精炼五档；交给 selection.project_refine 取档。
    assert normalize_slang("护摩满精效果", PROFILES["ys"]) == "护摩精炼5效果"


def test_pool_words_cover_bare_up_and_pool_phrasings():
    """裸 up、池子、武器池、混池、定轨 等高频问法也要重定向。"""
    for code in ("ys", "sr", "zzz", "arknights"):
        words = [w for entry in PROFILES[code].pool_pages for w in entry[0]]
        for word in ("up", "UP", "池子"):
            assert word in words, (code, word)
    ys_words = [w for entry in PROFILES["ys"].pool_pages for w in entry[0]]
    for word in ("武器池", "角色池", "混池", "定轨", "集录", "常驻"):
        assert word in ys_words, word
    assert "光锥池" in [w for e in PROFILES["sr"].pool_pages for w in e[0]]
    assert "音擎池" in [w for e in PROFILES["zzz"].pool_pages for w in e[0]]


def test_aspect_words_cover_equipment_and_basic_info():
    from wiki.games import aspect_words

    words = set(aspect_words())
    for word in (
        "圣遗物",
        "遗器",
        "驱动盘",
        "光锥",
        "音擎",
        "邦布",
        "专武",
        "词条",
        "副词条",
        "生日",
        "CV",
        "声优",
        "身高",
        "年龄",
    ):
        assert word in words, word


def test_constellation_plus_refine_shorthand():
    """社区简写 N+M（命座+精炼）归一到命座分节，前缀位置仍保护实体。"""
    from wiki.games import normalize_slang

    cases = (
        ("胡桃1+1够用吗", "胡桃命之座够用吗", "ys"),
        ("胡桃6+5", "胡桃命之座", "ys"),
        ("流萤0+1", "流萤星魂", "sr"),
        ("艾莲2+1", "艾莲意象影画", "zzz"),
    )
    for raw, expected, code in cases:
        assert normalize_slang(raw, PROFILES[code]) == expected, raw
    assert normalize_slang("1+1胡桃", PROFILES["ys"]) == "1+1胡桃"
    # 方舟没有命座简写，保持原样。
    assert normalize_slang("能天使1+1", PROFILES["arknights"]) == "能天使1+1"


def test_graduation_slang_is_dropped():
    from wiki.games import normalize_slang

    for raw, expected in (
        ("胡桃毕业面板", "胡桃面板"),
        ("胡桃毕业武器", "胡桃武器"),
        ("纳西妲毕业圣遗物", "纳西妲圣遗物"),
    ):
        assert normalize_slang(raw, PROFILES["ys"]) == expected, raw


def test_equipment_questions_route_to_real_guide_sections():
    """按实测 BWIKI 分节标题验证配装类问题落到正确分节。"""
    from wiki.selection import Section, evidence

    def page(titles):
        return [Section(t, t, [f"{t}内容。"]) for t in titles]

    cases = (
        (
            "ys",
            ["角色定位", "配装推荐", "圣遗物", "武器", "阵容搭配"],
            [
                ("胡桃圣遗物", "圣遗物"),
                ("胡桃武器推荐", "武器"),
                ("胡桃配队", "阵容搭配"),
            ],
        ),
        (
            "sr",
            ["角色定位", "配装推荐", "遗器", "光锥", "阵容搭配"],
            [("流萤遗器", "遗器"), ("流萤光锥推荐", "光锥"), ("流萤配队", "阵容搭配")],
        ),
        (
            "zzz",
            ["属性数据", "配装推荐", "驱动盘套装", "词条推荐", "音擎推荐", "阵容搭配"],
            [
                ("艾莲驱动盘", "驱动盘套装"),
                ("艾莲音擎推荐", "音擎推荐"),
                ("艾莲词条", "词条推荐"),
                ("艾莲配队", "阵容搭配"),
            ],
        ),
    )
    for code, titles, questions in cases:
        profile = PROFILES[code]
        for question, expected in questions:
            snippets, _, meta = evidence(
                page(titles),
                question,
                3000,
                "",
                "角色",
                profile.intents,
                profile.specifics,
            )
            assert [s["section"] for s in snippets][:1] == [expected], question
            assert meta["mode"] != "fallback", question


def test_sts2_ascension_and_upgrade_slang():
    """A/N/难度/双Boss 与敲牌黑话必须归一，进阶之灾保持卡牌名。"""
    from wiki.games import normalize_slang

    cases = (
        ("A10双Boss怎么打", "进阶10怎么打"),
        ("n10胜率", "进阶10胜率"),
        ("难度10怎么解锁", "进阶10怎么解锁"),
        ("进阶十怎么解锁", "进阶10怎么解锁"),
        ("A0怎么开", "进阶0怎么开"),
        ("双Boss是什么", "进阶10是什么"),
        ("进阶之灾怎么删", "进阶之灾怎么删"),
        ("进阶9和进阶10区别", "进阶9和进阶10区别"),
        ("打击敲了效果", "打击升级了效果"),
        ("敲位不够", "升级优先级不够"),
        ("火堆敲牌还是睡觉", "升级还是休息"),
        ("锻造和睡觉", "升级和休息"),
    )
    for raw, expected in cases:
        assert normalize_slang(raw, PROFILES["sts2"]) == expected, raw
