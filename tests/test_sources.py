import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from wiki.cache import Cache
from wiki.client import WikiClient
from wiki.extractor import evidence, extract_sections
from wiki.games import ARKNIGHTS, api_url, source_api
from wiki.models import WikiError
from wiki.query import QueryService
from wiki.sources import ArknightsSources

HTML = (Path(__file__).parent / "fixtures" / "prts-operator.html").read_text(
    encoding="utf-8"
)


def service(result=None):
    return SimpleNamespace(
        aliases={},
        search=AsyncMock(return_value=result or {"status": "ok", "page_id": 1}),
        read=AsyncMock(return_value={"status": "ok", "page_id": 1}),
        clear_parse_cache=AsyncMock(return_value=1),
        stats=lambda: {"game": "arknights", "upstream_requests": 1, "errors": {}},
    )


@pytest.mark.parametrize("status", ["ok", "needs_choice"])
def test_prts_success_and_candidates_do_not_use_bwiki(status):
    primary, backup = service({"status": status}), service()
    router = ArknightsSources(primary, backup)
    result = asyncio.run(router.search("能天使", "技能"))
    assert result["source_key"] == "prts" and "prts" in result["instructions"]
    backup.search.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    ["not_found", "section_not_found", "timeout", "forbidden", "rate_limited"],
)
def test_prts_unavailable_or_no_content_falls_back_to_bwiki(failure):
    primary, backup = service(), service()
    if failure in {"not_found", "section_not_found"}:
        primary.search.return_value = {"status": failure}
    else:
        primary.search.side_effect = WikiError(failure, "PRTS 暂不可用")
    router = ArknightsSources(primary, backup)
    result = asyncio.run(router.search("能天使", "精英化材料"))
    assert result["source_key"] == "bwiki" and result["fallback_from"] == "prts"
    backup.search.assert_awaited_once_with("能天使", "精英化材料")


def test_primary_timeout_leaves_budget_for_fallback_and_bad_input_is_not_retried():
    primary, backup = service(), service()

    async def slow(*args):
        await asyncio.sleep(1)

    primary.search.side_effect = slow
    router = ArknightsSources(primary, backup, timeout=0.05)
    assert asyncio.run(router.search("能天使"))["source_key"] == "bwiki"
    primary.search.side_effect = WikiError("bad_input", "输入错误")
    backup.search.reset_mock()
    with pytest.raises(WikiError):
        asyncio.run(router.search(""))
    backup.search.assert_not_awaited()


@pytest.mark.parametrize("source", ["prts", "bwiki"])
def test_page_ids_are_pinned_to_the_explicit_source(source):
    primary, backup = service(), service()
    router = ArknightsSources(primary, backup)
    result = asyncio.run(router.read(7, "技能", source=source))
    selected, other = (primary, backup) if source == "prts" else (backup, primary)
    selected.read.assert_awaited_once_with(7, "技能", "")
    other.read.assert_not_awaited()
    assert result["source_key"] == source
    selected.read.side_effect = WikiError("timeout", "超时")
    with pytest.raises(WikiError):
        asyncio.run(router.read(7, source=source))
    other.read.assert_not_awaited()


def test_read_without_source_is_rejected_and_shared_cache_stats_are_aggregated():
    primary, backup = service(), service()
    router = ArknightsSources(primary, backup)
    with pytest.raises(WikiError, match="source_key"):
        asyncio.run(router.read(1))
    primary.read.assert_not_awaited()
    backup.read.assert_not_awaited()
    assert router.stats()["upstream_requests"] == 2
    assert asyncio.run(router.clear_parse_cache()) == 2


def test_prts_and_bwiki_cache_entries_and_rate_limits_are_isolated(tmp_path):
    async def check():
        cache = Cache(tmp_path)
        calls = []

        def respond(request):
            calls.append(request.url.host)
            return httpx.Response(200, json={"query": {"search": []}})

        primary = WikiClient(
            cache,
            game="arknights",
            source="prts",
            transport=httpx.MockTransport(respond),
        )
        backup = WikiClient(
            cache,
            game="arknights",
            source="bwiki",
            transport=httpx.MockTransport(respond),
        )
        previous = dict(WikiClient._blocked)
        try:
            params = {"action": "query", "list": "search", "srsearch": "能天使"}
            await primary.request(params, 600)
            await backup.request(params, 600)
            await primary.request(params, 600)
            assert calls == ["prts.wiki", "wiki.biligame.com"]
            import time

            WikiClient._blocked[primary._host] = time.monotonic() + 30
            assert primary.health()["blocked_seconds"] > 0
            assert backup.health()["blocked_seconds"] == 0
        finally:
            WikiClient._blocked.clear()
            WikiClient._blocked.update(previous)
            await primary.close()
            await backup.close()

    asyncio.run(check())


def test_prts_exact_title_lookup_precedes_full_text_search_and_keeps_source_links(
    tmp_path,
):
    async def check():
        requests = []

        def respond(request):
            params = request.url.params
            requests.append(dict(params))
            assert request.url.host == "prts.wiki"
            if params["action"] == "query":
                assert params["titles"] == "能天使" and "list" not in params
                return httpx.Response(
                    200,
                    json={"query": {"pages": [{"title": "能天使", "pageid": 1769}]}},
                )
            assert params["pageid"] == "1769"
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "能天使",
                        "pageid": 1769,
                        "revid": 442591,
                        "text": HTML,
                    }
                },
            )

        client = WikiClient(
            Cache(tmp_path),
            game="arknights",
            transport=httpx.MockTransport(respond),
            pace=0,
        )
        try:
            query = QueryService(client, profile=ARKNIGHTS)
            result = await query.search("能天使", "精英化材料")
            assert result["source_key"] == "prts" and result["page_id"] == 1769
            assert result["url"].startswith("https://prts.wiki/w/")
            assert all(
                url.startswith("https://prts.wiki/w/") for url in result["source_urls"]
            )
            assert "龙门币 × 3w" in result["evidence"][0]["text"]
            assert "狙击芯片 × 5" in result["evidence"][0]["text"]
            assert len(requests) == 2
            with pytest.raises(WikiError):
                await query.read(1769, source="bwiki")
        finally:
            await client.close()

    asyncio.run(check())


def test_prts_dynamic_info_portrait_skills_and_material_names_are_preserved():
    meta = {}
    sections = extract_sections(
        HTML, "能天使", prefix="arknights", meta=meta, source="prts"
    )
    intro = evidence(
        sections, "", 1000, "", "能天使", ARKNIGHTS.intents, ARKNIGHTS.specifics
    )[0]
    assert "狙击" in str(intro) and "6星" in str(intro)
    assert "异格一览" not in str(intro) and "查看立绘" not in str(intro)
    assert meta["image_url"].startswith("https://media.prts.wiki/b/bd/")
    skills = evidence(
        sections,
        "技能3倍率",
        1000,
        "",
        "能天使",
        ARKNIGHTS.intents,
        ARKNIGHTS.specifics,
    )[0]
    assert "过载模式" in str(skills) and "冲锋模式" not in str(skills)
    assert all(item["anchor"] == "技能" for item in skills)
    assert "重复移动版" not in str(sections)
    assert api_url("arknights") == "https://prts.wiki/api.php"
    assert (
        source_api("arknights", "bwiki")
        == "https://wiki.biligame.com/arknights/api.php"
    )


def test_prts_material_acquisition_keeps_the_drop_stage_with_its_label():
    html = (
        '<h2 id="基础信息">基础信息</h2><table class="itemInfo">'
        "<tr><th>用途</th></tr><tr><td>用于术师精英化。</td></tr>"
        '<tr><th colspan="2">概率掉落</th></tr><tr><td class="hlist"><a title="PR-B-1 干涉">PR-B-1 干涉</a></td></tr>'
        "</table><h2>材料掉落</h2><p>动态统计控件。</p>"
    )
    sections = extract_sections(html, "术师芯片", prefix="arknights", source="prts")
    result = evidence(
        sections,
        "获取方式",
        1000,
        "",
        "术师芯片",
        ARKNIGHTS.intents,
        ARKNIGHTS.specifics,
    )[0]
    assert "概率掉落：PR-B-1 干涉" in str(result)
    assert "动态统计控件" not in str(result)
