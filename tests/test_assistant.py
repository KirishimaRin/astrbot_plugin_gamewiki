import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import pytest

from wiki.assistant import (
    CommandAssistant,
    clean_overview,
    literal_intent,
    parse_intent,
)
from wiki.games import PROFILES
from wiki.models import WikiError
from wiki.query import ALIASES


def page():
    return {
        "status": "ok",
        "title": "纳西妲",
        "query": "纳西妲",
        "question": "突破材料",
        "url": "https://wiki.biligame.com/ys/纳西妲",
        "evidence": [
            {
                "section": "突破",
                "text": "劫波莲 × 168\n摩拉 × 420000",
                "url": "https://wiki.biligame.com/ys/纳西妲#突破",
            }
        ],
    }


class Service:
    aliases = ALIASES

    def __init__(self, result=None):
        self.search = AsyncMock(return_value=page() if result is None else result)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("纳西妲", ("纳西妲", "")),
        ("日月前事", ("日月前事", "")),
        ("纳西妲 突破材料", ("纳西妲", "突破材料")),
        ("草神突破材料", ("草神", "草神突破材料")),
        ("能天使精英化材料", None),
        ("日月前事讲了什么", None),
        ("请问 纳西妲突破需要什么材料", None),
        ("给我讲讲日月前事", None),
        ("我想了解纳西妲", None),
        ("纳西妲是谁", None),
    ],
)
def test_literal_intent(text, expected):
    assert literal_intent(text, Service()) == expected


def test_model_intent_json_is_bounded():
    assert parse_intent(
        '```json\n{"query":"纳西妲","question":"突破材料"}\n```', "问题"
    ) == ("纳西妲", "突破材料")
    for reply in (
        '{"query":"https://example.com"}',
        '{"query":""}',
        "not JSON",
        '{"query":true}',
    ):
        with pytest.raises(ValueError):
            parse_intent(reply, "问题")


def test_overview_links_are_attached_by_code_and_invented_numbers_rejected():
    assert (
        clean_overview(
            "劫波莲168株。\n来源：https://fake.example", 750, page()["evidence"]
        )
        == "劫波莲168株。"
    )
    with pytest.raises(ValueError):
        clean_overview("劫波莲999株。", 750, page()["evidence"])
    assert clean_overview(
        "1. 劫波莲168株。\n2. 摩拉420000。", 750, page()["evidence"]
    ).startswith("1.")
    assert (
        clean_overview("177.1%", 750, [{"section": "技能", "text": "伤害 | 177.1%"}])
        == "177.1%"
    )


def test_encoded_sources_with_spaces_are_not_decoded_or_model_generated():
    from wiki.assistant import overview_text

    result = page()
    result["evidence"][0]["url"] = (
        "https://wiki.biligame.com/ys/Book%20Title#Chapter%201"
    )
    assert overview_text(result, "书籍简介。").endswith(result["evidence"][0]["url"])


def test_fallback_peels_game_heads_and_keeps_entities():
    from wiki.assistant import fallback_intent
    from wiki.games import game_words

    # Game-name heads are context, never the entity.
    assert fallback_intent("终末地武器获取", {}, game_words("zmd"))[0] == "武器获取"
    assert fallback_intent("原神纳西妲是谁", {}, game_words("ys"))[0] == "纳西妲"
    # Alias heads anchor the entity before unknown slang.
    assert fallback_intent("草神平A倍率", ALIASES)[0] == "草神"
    # A position-split query drops one dangling verb.
    assert fallback_intent("纳西妲用什么武器")[0] == "纳西妲"
    assert fallback_intent("纳西妲突破需要什么材料")[0] == "纳西妲"
    # New per-game aspect words split cleanly at the entity boundary.
    assert fallback_intent("纳西妲命之座效果")[0] == "纳西妲"
    assert fallback_intent("流萤星魂")[0] == "流萤"
    assert fallback_intent("流萤秘技")[0] == "流萤"
    assert fallback_intent("艾莲核心被动")[0] == "艾莲"
    assert fallback_intent("艾莲影画")[0] == "艾莲"
    assert fallback_intent("能天使基建技能")[0] == "能天使"
    # 卡池/寻访类问法由 pool 行触发词切分实体。
    assert fallback_intent("纳西妲复刻了吗")[0] == "纳西妲"


def test_slang_is_normalized_before_intent_parsing():
    from wiki.assistant import fallback_intent
    from wiki.games import game_words, normalize_slang

    # The rewrite runs before parsing, so the existing aspect vocabulary
    # splits the rewritten question; slang words never join the vocabulary.
    for code, raw, question, query in (
        ("ys", "纳西妲一命效果", "纳西妲命之座效果", "纳西妲"),
        ("ys", "纳西妲E技能倍率", "纳西妲战技倍率", "纳西妲"),
        ("ys", "纳西妲q技能", "纳西妲大招", "纳西妲"),
        ("sr", "流萤二魂", "流萤星魂", "流萤"),
        ("sr", "流萤满魂伤害", "流萤星魂伤害", "流萤"),
        ("zzz", "艾莲2画", "艾莲意象影画", "艾莲"),
        ("arknights", "能天使精二材料", "能天使精英化材料", "能天使"),
        ("arknights", "能天使专三材料", "能天使专精材料", "能天使"),
        ("zmd", "庄方宜Q技能", "庄方宜终结技", "庄方宜"),
        ("zmd", "庄方宜平A倍率", "庄方宜普攻倍率", "庄方宜"),
    ):
        profile = PROFILES[code]
        text = normalize_slang(raw, profile)
        assert text == question, raw
        assert fallback_intent(text, {}, game_words(code))[0] == query, raw

    # Bare letters never trigger a rewrite.
    assert normalize_slang("纳西妲E", PROFILES["ys"]) == "纳西妲E"
    # Time references normalize so “现在卡池” hits the （当前） heading.
    assert normalize_slang("现在卡池有什么", PROFILES["ys"]) == "当前卡池有什么"


class TestCommandAssistant(unittest.IsolatedAsyncioTestCase):
    async def test_slang_questions_normalized_before_search(self):
        service, generate = Service(), AsyncMock(side_effect=TimeoutError)
        await CommandAssistant(generate).answer(
            "艾梅莉埃平A倍率", PROFILES["ys"], service
        )
        assert service.search.await_args.args == ("艾梅莉埃", "艾梅莉埃普攻倍率")

    async def test_comparison_questions_get_split_guidance_not_a_search(self):
        service, generate = Service(), AsyncMock()
        reply, metrics = await CommandAssistant(generate).answer(
            "草神和艾梅莉埃哪个好", PROFILES["ys"], service
        )
        service.search.assert_not_awaited()
        generate.assert_not_awaited()
        assert "/ys 草神" in reply and "/ys 艾梅莉埃" in reply
        assert metrics["outcome"] == "comparison" and not metrics["fallback"]

    async def test_unsplittable_comparison_gets_generic_guidance(self):
        service, generate = Service(), AsyncMock()
        reply, _ = await CommandAssistant(generate).answer(
            "和璞鸢和护摩之杖哪个好", PROFILES["ys"], service
        )
        service.search.assert_not_awaited()
        assert "请分开查询" in reply and "/ys" not in reply

    async def test_comparison_collapsed_by_slang_gets_generic_guidance(self):
        # 精一/精二 both rewrite to 精英化; naming it twice is noise.
        service, generate = Service(), AsyncMock()
        reply, _ = await CommandAssistant(generate).answer(
            "精一和精二哪个好", PROFILES["arknights"], service
        )
        service.search.assert_not_awaited()
        generate.assert_not_awaited()
        assert "请分开查询" in reply
        assert reply.count("精英化") == 0

    async def test_selected_page_skips_search_and_intent_model(self):
        result = {**page(), "page_id": 42}
        service = Service()
        service.read = AsyncMock(return_value=result)
        generate = AsyncMock(return_value="需要劫波莲168株。")
        observed = []
        reply, metrics = await CommandAssistant(generate).answer(
            "战技10级呢",
            PROFILES["ys"],
            service,
            page_id=42,
            question="战技10级呢",
            on_result=observed.append,
        )
        service.search.assert_not_awaited()
        service.read.assert_awaited_once_with(42, "战技10级呢")
        assert generate.await_count == 1
        assert observed[0]["question"] == "战技10级呢"
        assert metrics["outcome"] == "ok" and "劫波莲168" in reply

    async def test_rejected_overview_exposes_a_safe_diagnostic_reason(self):
        reply, metrics = await CommandAssistant(AsyncMock(return_value="999株")).answer(
            "纳西妲 突破材料", PROFILES["ys"], Service()
        )
        assert "原文摘录" in reply
        assert metrics["fallback_reason"] == "overview_rejected"

    async def test_explicit_query_uses_one_model_call_and_section_source(self):
        generate = AsyncMock(return_value="需要劫波莲168株、摩拉420000。")
        service = Service()
        reply, metrics = await CommandAssistant(generate).answer(
            "纳西妲 突破材料", PROFILES["ys"], service
        )
        service.search.assert_awaited_once_with("纳西妲", "突破材料")
        assert generate.await_count == 1 == metrics["model_calls"]
        assert reply.startswith("【纳西妲】\n\n需要")
        assert reply.endswith("查看原文：\nhttps://wiki.biligame.com/ys/纳西妲#突破")
        assert metrics["model_seconds"] <= metrics["total_seconds"]

    async def test_complete_question_uses_two_calls(self):
        generate = AsyncMock(
            side_effect=[
                json.dumps({"query": "纳西妲", "question": "突破材料"}),
                "劫波莲168株。",
            ]
        )
        service = Service()
        reply, metrics = await CommandAssistant(generate).answer(
            "纳西妲突破需要什么材料", PROFILES["ys"], service
        )
        assert generate.await_count == metrics["model_calls"] == 2
        service.search.assert_awaited_once_with("纳西妲", "突破材料")
        assert "劫波莲168" in reply

    async def test_all_games_share_the_overview_path(self):
        for profile in PROFILES.values():
            generate = AsyncMock(return_value="相关资料概览。")
            reply, metrics = await CommandAssistant(generate).answer(
                "测试条目", profile, Service()
            )
            assert "相关资料概览" in reply and metrics["model_calls"] == 1

    async def test_model_failure_returns_labeled_excerpt_and_no_nested_call(self):
        for failure in (RuntimeError("offline"), "", "劫波莲999株。", "x" * 800):
            generate = (
                AsyncMock(side_effect=failure)
                if isinstance(failure, Exception)
                else AsyncMock(return_value=failure)
            )
            reply, metrics = await CommandAssistant(generate).answer(
                "纳西妲 突破材料", PROFILES["ys"], Service()
            )
            assert "原文摘录" in reply and "劫波莲 × 168" in reply
            assert "#突破" in reply and metrics["fallback"]
            assert generate.await_count == 1

    async def test_intent_failure_uses_entity_prefix_and_skips_summary(self):
        for failure in (RuntimeError("offline"), "invalid json"):
            generate = (
                AsyncMock(side_effect=failure)
                if isinstance(failure, Exception)
                else AsyncMock(return_value=failure)
            )
            service = Service()
            reply, metrics = await CommandAssistant(generate).answer(
                "纳西妲突破需要什么材料", PROFILES["ys"], service
            )
            service.search.assert_awaited_once_with("纳西妲", "纳西妲突破需要什么材料")
            assert "原文摘录" in reply and generate.await_count == 1
            assert metrics["fallback"]

    async def test_timeout_cancels_generation_and_falls_back(self):
        cancelled = asyncio.Event()

        async def generate(prompt):
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()

        reply, metrics = await CommandAssistant(generate, model_timeout=0.01).answer(
            "纳西妲", PROFILES["ys"], Service()
        )
        assert cancelled.is_set() and metrics["fallback"] and "原文摘录" in reply

    async def test_no_evidence_does_not_generate(self):
        generate = AsyncMock()
        for result in (
            {"status": "not_found", "message": "未找到"},
            {
                "status": "needs_choice",
                "candidates": [
                    {"title": "角色甲", "url": "https://wiki.biligame.com/ys/角色甲"}
                ],
            },
            {
                **page(),
                "status": "section_not_found",
                "evidence": [],
                "available_sections": ["故事"],
            },
        ):
            reply, metrics = await CommandAssistant(generate).answer(
                "角色", PROFILES["ys"], Service(result)
            )
            assert reply and metrics["model_calls"] == 0
        generate.assert_not_awaited()

    async def test_missing_answer_is_preserved_as_a_short_explanation(self):
        generate = AsyncMock(
            return_value="当前资料只有材料名称和数量，缺少采集位置。请查看原文。"
        )
        reply, _ = await CommandAssistant(generate).answer(
            "纳西妲 采集材料", PROFILES["ys"], Service()
        )
        assert "缺少采集位置" in reply and "#突破" in reply

    async def test_invalid_input_does_not_query_or_generate(self):
        service, generate = Service(), AsyncMock()
        for text in ("", "x" * 301):
            with pytest.raises(WikiError):
                await CommandAssistant(generate).answer(text, PROFILES["ys"], service)
        service.search.assert_not_awaited()
        generate.assert_not_awaited()


def test_cjk_numerals_are_normalized_for_fact_check():
    from wiki.assistant import clean_overview, normalize_cn_numbers

    assert normalize_cn_numbers("十二万") == "120000"
    assert normalize_cn_numbers("三百五十") == "350"
    evidence = [{"text": "摩拉 × 120000", "section": "突破"}]
    passed = clean_overview("需要摩拉十二万。", 200, evidence)
    assert "摩拉" in passed
    with pytest.raises(ValueError):
        clean_overview("需要摩拉九十八万。", 200, evidence)


@pytest.mark.parametrize(
    "game,source,label", [("zmd", "akedata", "AKEData"), ("arknights", "prts", "PRTS")]
)
@pytest.mark.parametrize("status", ["ok", "not_found"])
def test_source_fallback_notice_uses_the_actual_game_and_origin(
    game, source, label, status
):
    async def run():
        result = {**page(), "fallback_from": source, "source_key": "bwiki"}
        if status == "not_found":
            result.update(status=status, message="未找到相关条目。")
        service = Service(result)
        reply, _ = await CommandAssistant(
            AsyncMock(return_value="需要劫波莲168株。")
        ).answer("角色", PROFILES[game], service)
        assert reply.startswith(
            f"{label} 未能提供结果，已改用{PROFILES[game].name} BWIKI。"
        )
        if game == "zmd":
            assert "PRTS" not in reply
            assert "已改用明日方舟 BWIKI" not in reply

    asyncio.run(run())


class TestImageGating(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def image_page(**overrides):
        result = page()
        result["image_url"] = "https://example.org/p.png"
        result.update(overrides)
        return result

    async def test_name_and_identity_queries_attach_the_portrait(self):
        for text in ("纳西妲", "纳西妲 简介", "纳西妲是谁"):
            service = Service(self.image_page())
            _, metrics = await CommandAssistant(AsyncMock(return_value="{}")).answer(
                text, PROFILES["ys"], service
            )
            assert metrics["image_url"] == "https://example.org/p.png", text

    async def test_aspect_questions_get_an_evidence_card_not_the_portrait(self):
        for text in ("纳西妲 突破材料", "纳西妲武器图鉴"):
            _, metrics = await CommandAssistant(AsyncMock(return_value="{}")).answer(
                text, PROFILES["ys"], Service(self.image_page())
            )
            assert "image_url" not in metrics, text
            assert metrics["card"]["title"] == "纳西妲", text
            assert metrics["card"]["sections"] == [
                ("突破", "劫波莲 × 168\n摩拉 × 420000")
            ], text

    async def test_card_replies_generate_a_compact_overview(self):
        prompts = []

        async def generate(prompt):
            prompts.append(prompt)
            return "需要劫波莲168株。"

        reply, metrics = await CommandAssistant(generate).answer(
            "纳西妲 突破材料", PROFILES["ys"], Service()
        )
        assert metrics["card"] and len(prompts) == 1
        assert "证据卡片" in prompts[0] and "150–" not in prompts[0]
        # 提问时刻的北京时间随载荷下发，卡池/活动按日期范围对照匹配。
        assert '"now"' in prompts[0]
        assert reply.startswith("【纳西妲】\n\n需要劫波莲168株。")

    async def test_identity_and_fallback_queries_keep_the_full_overview(self):
        for text, result in (
            ("纳西妲 简介", self.image_page()),
            ("纳西妲 技能", {**page(), "selection": {"mode": "fallback"}}),
        ):
            prompts = []

            async def generate(prompt):
                prompts.append(prompt)
                return "相关概览正文。"

            _, metrics = await CommandAssistant(generate).answer(
                text, PROFILES["ys"], Service(result)
            )
            assert "card" not in metrics, text
            assert "150–" in prompts[-1] and "证据卡片" not in prompts[-1], text
            assert '"now"' in prompts[-1], text

    async def test_followup_and_selection_reads_keep_the_original_decision(self):
        for question, portrait in (("突破材料呢", False), ("", True)):
            service = Service()
            service.read = AsyncMock(return_value=self.image_page())
            _, metrics = await CommandAssistant(AsyncMock()).answer(
                question or "纳西妲",
                PROFILES["ys"],
                service,
                page_id=42,
                question=question,
            )
            assert ("image_url" in metrics) is portrait, question
            assert ("card" in metrics) is not portrait, question

    async def test_aspect_vocabulary_is_derived_from_game_profiles(self):
        from wiki.assistant import IDENTITY, QUESTION
        from wiki.games import aspect_words

        words = aspect_words()
        for word in ("武器", "图鉴", "立绘", "头像", "配队", "技能", "材料"):
            assert word in words, word
        assert QUESTION.search("汤汤武器")
        assert QUESTION.search("汤汤配队")
        assert IDENTITY.search("汤汤立绘")
        # Bare names still parse as entities, not questions.
        assert literal_intent("汤汤武器", Service()) is None


@pytest.mark.parametrize("mode,section", [("fallback", "故事"), ("focused", "概览")])
def test_unstructured_or_fallback_evidence_does_not_get_an_aspect_card(mode, section):
    async def run():
        result = page()
        result["evidence"] = [{"section": section, "text": "职业术师，武器手铳。"}]
        result["selection"] = {"mode": mode}
        _, metrics = await CommandAssistant(
            AsyncMock(return_value="请查看原文中的相关资料。")
        ).answer("纳西妲 技能", PROFILES["ys"], Service(result))
        assert "card" not in metrics
        assert "image_url" not in metrics

    asyncio.run(run())


class TestComparisonWords(unittest.IsolatedAsyncioTestCase):
    async def test_practice_and_pull_tails_split_two_names(self):
        # 练谁/抽谁/培养谁/先练/先抽 也是比较问法，漏网会走检索并拆错名。
        for text, a, b in (
            ("纳西妲和万叶练谁", "纳西妲", "万叶"),
            ("万叶和宵宫先抽哪个", "万叶", "宵宫"),
            ("钟离和胡桃培养谁", "钟离", "胡桃"),
            ("纳西妲和万叶先练哪个", "纳西妲", "万叶"),
        ):
            service, generate = Service(), AsyncMock()
            reply, metrics = await CommandAssistant(generate).answer(
                text, PROFILES["ys"], service
            )
            service.search.assert_not_awaited()
            generate.assert_not_awaited()
            assert f"/ys {a}" in reply and f"/ys {b}" in reply, text
            assert metrics["outcome"] == "comparison", text

    async def test_dui_joiner_splits_names(self):
        # “钟离对胡桃哪个强”：对 作连接词拆出两个条目名。
        service, generate = Service(), AsyncMock()
        reply, _ = await CommandAssistant(generate).answer(
            "钟离对胡桃哪个强", PROFILES["ys"], service
        )
        service.search.assert_not_awaited()
        assert "/ys 钟离" in reply and "/ys 胡桃" in reply

    async def test_joiner_headed_names_stay_generic(self):
        # “和璞鸢和护摩之杖哪个好”：开头是连接词的条目名不拆名，只给通用提示。
        service, generate = Service(), AsyncMock()
        reply, _ = await CommandAssistant(generate).answer(
            "和璞鸢和护摩之杖哪个好", PROFILES["ys"], service
        )
        service.search.assert_not_awaited()
        assert "请分开查询" in reply and "/ys" not in reply


def test_fallback_strips_level_and_evaluation_tails():
    from wiki.assistant import fallback_intent

    # 等级/评价类尾巴不属于实体，模型不可用时也不该污染查询。
    for raw in (
        "胡桃90级面板",
        "胡桃10级E伤害",
        "胡桃升满要多少材料",
        "胡桃满级面板",
        "胡桃下次复刻",
        "胡桃的圣遗物",
    ):
        assert fallback_intent(raw)[0] == "胡桃", raw
    # 前缀保护与正常实体不受影响。
    assert fallback_intent("满命魈强度怎么样")[0] == "满命魈"
    assert fallback_intent("能天使模组")[0] == "能天使"


class TestUnknownTailRetry(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tail_retries_through_the_model(self):
        calls = []

        async def search(query, question=""):
            calls.append(query)
            if query == "胡桃":
                return page()
            return {"status": "not_found", "query": query, "message": "未找到"}

        service = Service()
        service.search = search
        generate = AsyncMock(
            side_effect=[
                json.dumps({"query": "胡桃", "question": "胡桃语音"}),
                "语音台词收录在角色页。",
            ]
        )
        reply, metrics = await CommandAssistant(generate).answer(
            "胡桃语音", PROFILES["ys"], service
        )
        assert calls == ["胡桃语音", "胡桃"]
        assert metrics["model_calls"] == 2
        assert reply

    async def test_short_bare_names_do_not_spend_a_model_call(self):
        service = Service({"status": "not_found", "message": "未找到"})
        generate = AsyncMock()
        reply, metrics = await CommandAssistant(generate).answer(
            "角色", PROFILES["ys"], service
        )
        assert reply and metrics["model_calls"] == 0
        generate.assert_not_awaited()

    async def test_confident_intents_do_not_retry(self):
        service = Service({"status": "not_found", "message": "未找到"})
        generate = AsyncMock()
        await CommandAssistant(generate).answer(
            "纳西妲 突破材料", PROFILES["ys"], service
        )
        assert service.search.await_count == 1
        generate.assert_not_awaited()


class TestSTS2Comparison(unittest.IsolatedAsyncioTestCase):
    async def test_sts2_comparison_uses_field_data(self):
        service, generate = Service(), AsyncMock()
        service.compare = AsyncMock(
            return_value={
                "status": "compare",
                "game": "sts2",
                "kind": "relic",
                "query": "燃烧之血 vs 红头骨",
                "left": {
                    "title": "燃烧之血",
                    "url": "https://example.test/a",
                    "metrics": {"win_rate": 40.0},
                },
                "right": {
                    "title": "红头骨",
                    "url": "https://example.test/b",
                    "metrics": {"win_rate": 50.0},
                },
                "dimensions": [
                    {"label": "稀有度", "left": "初始遗物", "right": "普通"}
                ],
                "source_urls": ["https://example.test/a", "https://example.test/b"],
            }
        )
        reply, metrics = await CommandAssistant(generate).answer(
            "燃烧之血和红头骨哪个好", PROFILES["sts2"], service
        )
        service.compare.assert_awaited_once()
        assert "【对比】燃烧之血 vs 红头骨" in reply
        assert "稀有度" in reply and "社区数据" in reply
        generate.assert_not_awaited()
        assert metrics["outcome"] == "comparison"

    async def test_sts2_comparison_with_why_adds_model_narrative(self):
        service, generate = (
            Service(),
            AsyncMock(return_value="需要低血量爆发时，红头骨更合适。"),
        )
        service.compare = AsyncMock(
            return_value={
                "status": "compare",
                "game": "sts2",
                "kind": "relic",
                "query": "燃烧之血 vs 红头骨",
                "left": {"title": "燃烧之血", "url": "a", "metrics": {}},
                "right": {"title": "红头骨", "url": "b", "metrics": {}},
                "dimensions": [
                    {"label": "稀有度", "left": "初始遗物", "right": "普通"}
                ],
                "source_urls": ["a", "b"],
            }
        )
        reply, metrics = await CommandAssistant(generate).answer(
            "燃烧之血和红头骨哪个好为什么", PROFILES["sts2"], service
        )
        assert "【对比】" in reply and "红头骨更合适" in reply
        generate.assert_awaited_once()
        assert metrics["model_calls"] == 1

    async def test_sts2_equal_ascension_spellings_are_explained(self):
        service, generate = Service(), AsyncMock()
        reply, metrics = await CommandAssistant(generate).answer(
            "A10和N10有什么区别", PROFILES["sts2"], service
        )
        service.compare.assert_not_awaited() if hasattr(service, "compare") else None
        assert "同一条目/等级" in reply and "进阶10" in reply
        generate.assert_not_awaited()
        assert metrics["outcome"] == "comparison"

    async def test_sts2_difference_question_uses_comparison(self):
        service, generate = Service(), AsyncMock()
        service.compare = AsyncMock(
            return_value={
                "status": "compare",
                "game": "sts2",
                "kind": "relic",
                "query": "燃烧之血 vs 红头骨",
                "left": {"title": "燃烧之血", "url": "a", "metrics": {}},
                "right": {"title": "红头骨", "url": "b", "metrics": {}},
                "dimensions": [
                    {"label": "稀有度", "left": "初始遗物", "right": "普通"}
                ],
                "source_urls": ["a", "b"],
            }
        )
        reply, _ = await CommandAssistant(generate).answer(
            "燃烧之血和红头骨有什么区别", PROFILES["sts2"], service
        )
        service.compare.assert_awaited_once()
        assert "【对比】" in reply and "稀有度" in reply

    async def test_sts2_comparison_rejects_unbacked_numbers(self):
        service, generate = (
            Service(),
            AsyncMock(return_value="红头骨胜率 99.9%，明显更强。"),
        )
        service.compare = AsyncMock(
            return_value={
                "status": "compare",
                "game": "sts2",
                "kind": "relic",
                "query": "燃烧之血 vs 红头骨",
                "left": {
                    "title": "燃烧之血",
                    "url": "a",
                    "metrics": {"win_rate": 40.0},
                },
                "right": {"title": "红头骨", "url": "b", "metrics": {"win_rate": 50.0}},
                "dimensions": [
                    {"label": "稀有度", "left": "初始遗物", "right": "普通"}
                ],
                "source_urls": ["a", "b"],
            }
        )
        reply, metrics = await CommandAssistant(generate).answer(
            "燃烧之血和红头骨哪个好为什么", PROFILES["sts2"], service
        )
        assert "99.9" not in reply
        assert metrics["fallback"] is True
