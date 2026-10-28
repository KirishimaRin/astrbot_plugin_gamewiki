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


class TestCommandAssistant(unittest.IsolatedAsyncioTestCase):
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
            _, metrics = await CommandAssistant(AsyncMock()).answer(
                text, PROFILES["ys"], service
            )
            assert metrics["image_url"] == "https://example.org/p.png", text

    async def test_aspect_questions_skip_the_portrait(self):
        for text in ("纳西妲 突破材料", "纳西妲武器图鉴"):
            _, metrics = await CommandAssistant(AsyncMock()).answer(
                text, PROFILES["ys"], Service(self.image_page())
            )
            assert "image_url" not in metrics, text
            assert metrics["image_decision"] == "aspect_query", text

    async def test_followup_and_selection_reads_keep_the_original_decision(self):
        for question, expected in (("突破材料呢", False), ("", True)):
            service = Service()
            service.read = AsyncMock(return_value=self.image_page())
            _, metrics = await CommandAssistant(AsyncMock()).answer(
                question or "纳西妲",
                PROFILES["ys"],
                service,
                page_id=42,
                question=question,
            )
            assert ("image_url" in metrics) is expected, question

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
