import unittest

import pytest

from wiki.games import PROFILES
from wiki.models import WikiError
from wiki.query import QueryService, format_command


class FakeClient:
    def __init__(self, hits):
        self.hits = hits
        self.requests = []

    def stats(self):
        return {
            "upstream_requests": len(self.requests),
            "cache_hits": 0,
            "coalesced": 0,
            "errors": {},
        }

    async def request(self, params, ttl):
        self.requests.append(params)
        if params["action"] == "query":
            return {"query": {"search": self.hits}}
        return {
            "_fetched_at": "2026-10-26T12:00:00Z",
            "parse": {
                "title": "纳西妲",
                "pageid": params["pageid"],
                "revid": 42,
                "text": "<h2>突破</h2><p>劫波莲168</p>",
            },
        }


class TestQuery(unittest.IsolatedAsyncioTestCase):
    async def test_book_reading_follows_exact_chapter_but_item_query_stays(self):
        class BookClient:
            def __init__(self):
                self.requests = []

            async def request(self, params, ttl):
                self.requests.append(params)
                if params["action"] == "query":
                    return {"query": {"search": [{"title": "测试书", "pageid": 1}]}}
                if params.get("pageid") == 1:
                    title, page_id = "测试书", 1
                    html = '<div>本条目介绍的是：道具<a href="/ys/书籍合集#测试书">正文</a></div><p>道具描述。</p><!-- NewPP limit report -->'
                else:
                    title, page_id = "书籍合集", 2
                    html = "<h2>另一本书</h2><p>不相关内容</p><h2>测试书</h2><p>指定书籍的内容。</p>"
                return {
                    "_fetched_at": "2026-10-26",
                    "parse": {
                        "title": title,
                        "pageid": page_id,
                        "revid": 1,
                        "text": html,
                    },
                }

        client = BookClient()
        service = QueryService(client)
        result = await service.search("测试书", "这本书讲了什么")
        assert result["display_title"] == "测试书"
        assert result["title"] == "书籍合集"
        assert "指定书籍的内容" in str(result["evidence"])
        assert "不相关内容" not in str(result["evidence"])
        assert "NewPP" not in format_command(result)
        assert len(client.requests) == 3
        result = await service.search("测试书", "道具获取方式")
        assert result["title"] == "测试书"
        assert len(client.requests) == 5

    async def test_alias_and_canonical_ranking(self):
        client = FakeClient(
            [
                {"title": "卡牌：纳西妲", "pageid": 2},
                {"title": "纳西妲/攻略", "pageid": 3},
                {"title": "纳西妲", "pageid": 1},
            ]
        )
        result = await QueryService(client).search("草神", "突破材料")
        assert client.requests[0]["srsearch"] == "纳西妲"
        assert result["page_id"] == 1
        assert result["revision_id"] == 42
        assert result["evidence"][0]["url"].startswith("https://wiki.biligame.com/ys/")
        assert "草神 → 纳西妲" in format_command(result)

    async def test_card_alias(self):
        client = FakeClient([])
        await QueryService(client).search("草神", "七圣召唤卡牌技能")
        assert client.requests[0]["srsearch"] == "卡牌：纳西妲"
        await QueryService(client).search("纳西妲", "七圣召唤卡牌技能")
        assert client.requests[-1]["srsearch"] == "卡牌：纳西妲"

    async def test_parsed_cache_tracks_fetched_timestamp(self):
        from unittest.mock import patch

        from wiki.extractor import extract_sections

        client = FakeClient([])
        service = QueryService(client)
        with patch("wiki.query.extract_sections", wraps=extract_sections) as extract:
            await service.read(1, "突破")
            await service.read(1, "突破")
            assert extract.call_count == 1
            for page_id in range(2, 12):
                await service.read(page_id, "突破")
            assert len(service._parsed) == 8
            await service.read(1, "突破")
            assert extract.call_count == 12

    async def test_clear_parse_cache_forces_reparse(self):
        from unittest.mock import patch

        from wiki.extractor import extract_sections

        client = FakeClient([])
        service = QueryService(client)
        with patch("wiki.query.extract_sections", wraps=extract_sections) as extract:
            await service.read(1, "突破")
            await service.read(1, "突破")
            assert extract.call_count == 1
            cleared = await service.clear_parse_cache()
            assert cleared == 1
            await service.read(1, "突破")
            assert extract.call_count == 2

    async def test_no_results_does_not_read(self):
        client = FakeClient([])
        result = await QueryService(client).search("不存在")
        assert result["status"] == "not_found"
        # One original search plus one prefix-fallback retry (both empty).
        assert len(client.requests) == 2

    async def test_ambiguous_search_returns_candidates_without_reading(self):
        client = FakeClient(
            [{"title": "测试甲", "pageid": 1}, {"title": "测试乙", "pageid": 2}]
        )
        result = await QueryService(client).search("测试")
        assert result["status"] == "needs_choice"
        assert len(client.requests) == 1
        reply = format_command(result)
        assert "完整名称" in reply and "测试甲" in reply and "测试乙" in reply
        assert all(c["url"] in reply for c in result["candidates"])

    async def test_single_fuzzy_hit_requires_confirmation(self):
        # Live regression: zmd 祀 has no page; search matched 骏卫 only through
        # the word 雪祀 in its English voice lines. Never auto-read that.
        client = FakeClient([{"title": "骏卫", "pageid": 326, "snippet": "雪祀"}])
        result = await QueryService(client, profile=PROFILES["zmd"]).search("祀")
        assert result["status"] == "needs_choice"
        assert len(client.requests) == 1, "a fuzzy hit must not be auto-read"
        reply = format_command(result)
        assert "没有与「祀」同名" in reply and "骏卫" in reply
        assert "zmd/%E9%AA%8F%E5%8D%AB" in reply

    async def test_trailing_punctuation_still_matches_title(self):
        client = FakeClient([{"title": "纳西妲", "pageid": 1}])
        service = QueryService(client)
        for query in ("纳西妲。", "「纳西妲」", "纳西妲  "):
            result = await service.search(query)
            assert result["status"] == "ok", query
            assert result["title"] == "纳西妲"

    async def test_prefix_fallback_searches_without_last_char(self):
        class PrefixClient:
            def __init__(self):
                self.requests = []

            def stats(self):
                return {
                    "upstream_requests": 2,
                    "cache_hits": 0,
                    "coalesced": 0,
                    "errors": {},
                }

            async def request(self, params, ttl):
                self.requests.append(params)
                if params["srsearch"] == "纳西达":
                    return {"query": {"search": []}}
                assert params["srsearch"] == "纳西", "fallback drops the last char"
                return {"query": {"search": [{"title": "纳西妲", "pageid": 1}]}}

        client = PrefixClient()
        result = await QueryService(client).search("纳西达")
        assert result["status"] == "needs_choice"
        assert result["query"] == "纳西达"
        assert result["suggestion_used"] == "纳西"
        assert result["candidates"][0]["title"] == "纳西妲"
        assert "纳西达" in format_command(result)

    async def test_corrected_exact_hit_requires_confirmation_without_reading(self):
        for suggested in (False, True):
            with self.subTest(suggested=suggested):
                requests = []

                class CorrectionClient:
                    async def request(self, params, ttl):
                        requests.append(params)
                        assert params["action"] == "query", (
                            "must not read another entity"
                        )
                        if params["srsearch"] == "测试甲":
                            return {
                                "query": {
                                    "search": [],
                                    "searchinfo": {"suggestion": "测试"}
                                    if suggested
                                    else {},
                                }
                            }
                        assert params["srsearch"] == "测试"
                        return {"query": {"search": [{"title": "测试", "pageid": 1}]}}

                result = await QueryService(CorrectionClient()).search("测试甲", "技能")
                assert result["status"] == "needs_choice"
                assert result["query"] == "测试甲" and result["question"] == "技能"
                assert result["suggestion_used"] == "测试"
                assert len(requests) == 2
                reply = format_command(result)
                assert "测试甲" in reply and "纠错关键词「测试」" in reply

    async def test_empty_suggestion_result_does_not_trigger_another_retry(self):
        requests = []

        class EmptySuggestionClient:
            async def request(self, params, ttl):
                requests.append(params)
                return {"query": {"search": [], "searchinfo": {"suggestion": "另一个"}}}

        result = await QueryService(EmptySuggestionClient()).search("测试甲")
        assert result["status"] == "not_found" and result["query"] == "测试甲"
        assert len(requests) == 2

    async def test_cross_game_hint_on_other_wikis(self):
        class EmptyClient:
            def __init__(self):
                self.requests = []

            def stats(self):
                return {
                    "upstream_requests": 1,
                    "cache_hits": 0,
                    "coalesced": 0,
                    "errors": {},
                }

            async def request(self, params, ttl):
                self.requests.append(params)
                return {"query": {"search": []}}

        result = await QueryService(EmptyClient(), profile=PROFILES["sr"]).search(
            "草神"
        )
        assert result["status"] == "not_found"
        assert "/ys 纳西妲" in result["message"]
        reply = format_command(result)
        assert "/ys 纳西妲" in reply

    async def test_redirect_pages_resolve_to_their_target(self):
        # sr 三月七 is a redirect page; parse must follow it to Serval.
        seen = []

        class RedirectClient:
            def stats(self):
                return {
                    "upstream_requests": 2,
                    "cache_hits": 0,
                    "coalesced": 0,
                    "errors": {},
                }

            async def request(self, params, ttl):
                seen.append(params)
                if params["action"] == "query":
                    return {"query": {"search": [{"title": "三月七", "pageid": 9}]}}
                assert params.get("redirects") == 1, "parse must follow redirects"
                return {
                    "_fetched_at": "2026-10-27",
                    "parse": {
                        "title": "三月七(星穹铁道)",
                        "pageid": 42,
                        "revid": 7,
                        "text": "<h2>介绍</h2><p>重定向后的正文。</p>",
                    },
                }

        service = QueryService(RedirectClient(), profile=PROFILES["sr"])
        result = await service.search("三月七")
        assert result["status"] == "ok"
        assert result["title"] == "三月七(星穹铁道)"
        assert result["evidence"][0]["url"].startswith("https://wiki.biligame.com/sr/")

    async def test_tool_contract_prioritizes_real_section_sources(self):
        result = await QueryService(FakeClient([])).read(1, "突破")
        assert result["source_urls"] == [result["evidence"][0]["url"]]
        assert "#" in result["source_urls"][0]
        assert "概览" in result["instructions"] and "数量" in result["instructions"]

    async def test_invalid_input_and_page_id(self):
        service = QueryService(FakeClient([]))
        for value in ("", "x" * 101):
            with pytest.raises(WikiError):
                await service.search(value)
        for value in (-1, True, 1.5, "http://localhost"):
            with pytest.raises(WikiError):
                await service.read(value)

    async def test_section_not_found_and_custom_alias(self):
        service = QueryService(FakeClient([]), aliases={"白菜": "纳西妲"})
        assert service.normalize("白菜") == "纳西妲"
        result = await service.read(1, "故事", "不存在")
        assert result["status"] == "section_not_found"
        assert result["available_sections"] == ["突破"]
        assert result["selection"]["mode"] == "section"

    async def test_selection_meta_and_noise_are_returned(self):
        client = FakeClient([{"title": "纳西妲", "pageid": 1}])
        service = QueryService(client)
        result = await service.search("纳西妲", "突破材料")
        assert result["selection"]["mode"] == "focused"
        assert "突破" in result["selection"]["intents"]
        assert isinstance(result["selection"]["noise_filtered"], dict)
        stats = service.stats()
        assert stats["pages_parsed"] == 1
        result = await service.read(1, "突破")
        assert service.stats()["parse_cache_hits"] == 1

    async def test_zero_score_question_falls_back_instead_of_not_found(self):
        client = FakeClient([{"title": "纳西妲", "pageid": 1}])
        service = QueryService(client)
        result = await service.search("纳西妲", "这个角色怎么养成")
        assert result["status"] == "ok"
        assert result["evidence"], "fallback must return the best section"
        assert result["selection"]["mode"] == "fallback"
