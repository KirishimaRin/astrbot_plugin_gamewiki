"""Offline tests for the STS2.INFO / STS2FRONT Chinese editorial adapter."""

import asyncio
from pathlib import Path

import httpx
import pytest

from wiki.cache import Cache
from wiki.chineseguides import ChineseGuideService
from wiki.spirecodex import SpireCodexService

MECHANICS_HTML = """
<main>
  <article>
    <div><h3>03 易伤</h3><span>减益</span></div>
    <dl>
      <dt>效果</dt><dd>目标受到的攻击伤害提高 50%。</dd>
      <dt>叠加</dt><dd>增加持续回合，不继续提高倍率。</dd>
    </dl>
  </article>
  <h2>叠加规则：数值、持续时间与次数</h2>
  <p>数值直接相加，持续时间另行结算。</p>
  <h2>结算顺序：效果到底什么时候发生</h2>
  <p>攻击伤害先计算力量，再计算易伤。</p>
</main>
"""

GUIDES_HTML = """
<main>
  <a href="/zh/guides/ironclad-starter-guide">
    Character · Beginner · 8 min 铁甲战士入门攻略 铁甲的输出、防御、消耗和力量路线。
  </a>
  <a href="/zh/guides/ascension-guide">
    Beginner · 9 min 进阶指南 一至十级进阶怎么爬。
  </a>
</main>
"""

GUIDE_HTML = """
<html><body>
  <h1>铁甲战士入门攻略</h1>
  <article><p>铁甲战士靠力量和消耗取胜。</p></article>
</body></html>
"""

ASCENSION_HTML = """
<html><body>
  <h1>进阶指南</h1>
  <article><p>一至十级进阶需要逐级通关第三章解锁。</p></article>
</body></html>
"""

SILENT_HTML = """
<html><body>
  <h1>静默猎手</h1>
  <main><section><p>静默猎手靠奇巧和弃牌体系打出爆发。</p></section></main>
</body></html>
"""

IRONCLAD_HTML = """
<html><body>
  <h1>铁甲战士</h1>
  <main><section><p>铁甲战士靠力量和消耗取胜。</p></section></main>
</body></html>
"""

TIPS_HTML = """
<main>
  <a href="/zh-cn/tips/boss-guide/">
    BOSS 打法指南 每章首领的应对要点与危险招式。
  </a>
  <a href="/zh-cn/tips/shop-campfire-strategy/">
    商店与篝火策略 金币怎么花、篝火怎么选。
  </a>
  <a href="/zh-cn/tips/solo-vs-co-op/">
    先玩单人还是合作 单人更清晰，合作更适合一起玩。
  </a>
  <a href="/zh-cn/tips/best-combos/">
    最强卡牌组合 哪些连动真正值得围绕构筑。
  </a>
  <a href="/zh-cn/tips/enchantments/">
    附魔怎么选 附魔是长期成长系统。
  </a>
</main>
"""

TIP_HTML = """
<html><body>
  <h1>BOSS 打法指南</h1>
  <main><section><p>第一章首领注意力量叠加，按意图应对。</p></section></main>
</body></html>
"""


def make_service(tmp_path, calls=None):
    calls = calls if calls is not None else []

    def handler(request):
        calls.append(str(request.url))
        path = request.url.path
        if path == "/zh/mechanics":
            return httpx.Response(200, text=MECHANICS_HTML)
        if path == "/zh/guides":
            return httpx.Response(200, text=GUIDES_HTML)
        if path == "/zh/guides/ironclad-starter-guide":
            return httpx.Response(200, text=GUIDE_HTML)
        if path == "/zh-cn/characters/silent/":
            return httpx.Response(200, text=SILENT_HTML)
        if path == "/zh-cn/characters/ironclad/":
            return httpx.Response(200, text=IRONCLAD_HTML)
        return httpx.Response(404, text="Not Found")

    return (
        ChineseGuideService(
            Cache(Path(tmp_path)), timeout=2, transport=httpx.MockTransport(handler)
        ),
        calls,
    )


def test_mechanics_section_match_and_cache(tmp_path):
    service, calls = make_service(tmp_path)

    async def run():
        try:
            first = await service.mechanics("易伤倍率")
            second = await service.mechanics("易伤倍率")
            return first, second
        finally:
            await service.close()

    first, second = asyncio.run(run())
    assert first["title"] == "03 易伤"
    assert "50%" in first["text"]
    assert first["url"].endswith("/zh/mechanics")
    assert second == first
    assert len([url for url in calls if url.endswith("/zh/mechanics")]) == 1


def test_mechanics_general_mechanism_returns_overview(tmp_path):
    service, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.mechanics("机制")
        finally:
            await service.close()

    result = asyncio.run(run())
    assert result["title"] == "状态效果与结算机制"
    assert "叠加规则" in result["text"] and "结算顺序" in result["text"]


def test_character_guide_prefers_sts2info_then_sts2front(tmp_path):
    service, _ = make_service(tmp_path)

    async def run():
        try:
            ironclad = await service.guide("铁甲战士攻略", "攻略", character="铁甲战士")
            silent = await service.guide("静默猎手攻略", "攻略", character="静默猎手")
            return ironclad, silent
        finally:
            await service.close()

    ironclad, silent = asyncio.run(run())
    assert ironclad["key"] == "cn:guide:sts2front:ironclad"
    assert "力量" in ironclad["text"]
    assert silent["key"] == "cn:guide:sts2front:silent"
    assert "奇巧" in silent["text"]


def test_read_round_trips_mechanic_and_guide_keys(tmp_path):
    service, _ = make_service(tmp_path)

    async def run():
        try:
            mechanic = await service.read(
                "cn:mechanic:sts2info:" + "%E6%98%93%E4%BC%A4"
            )
            guide = await service.read("cn:guide:sts2info:ironclad-starter-guide")
            silent = await service.read("cn:guide:sts2front:silent")
            return mechanic, guide, silent
        finally:
            await service.close()

    mechanic, guide, silent = asyncio.run(run())
    assert "50%" in mechanic["body_markdown"]
    assert "力量" in guide["content"]
    assert "奇巧" in silent["content"]
    assert service.url("cn:guide:sts2front:silent").endswith(
        "/zh-cn/characters/silent/"
    )


class FakeChinese:
    async def mechanics(self, text):
        if "伤害" in text or "易伤" in text:
            return {
                "key": "cn:mechanic:sts2info:" + "%E6%98%93%E4%BC%A4",
                "title": "03 易伤",
                "text": "目标受到的攻击伤害提高 50%。",
                "url": "https://sts2.info/zh/mechanics",
            }
        return None

    async def guide(self, query, question="", character=""):
        return {
            "key": "cn:guide:sts2front:silent",
            "title": "静默猎手",
            "text": "静默猎手靠奇巧和弃牌体系打出爆发。",
            "url": "https://sts2front.com/zh-cn/characters/silent/",
        }

    async def read(self, key):
        return {
            "id": key,
            "title": "03 易伤",
            "body_markdown": "目标受到的攻击伤害提高 50%。",
            "url": "https://sts2.info/zh/mechanics",
        }

    @staticmethod
    def url(key):
        return "https://sts2.info/zh/mechanics"


class DummyClient:
    async def get(self, path, params, ttl):
        return []

    def stats(self):
        return {}


class SlowChinese(FakeChinese):
    async def mechanics(self, text):
        await asyncio.sleep(2)
        return await super().mechanics(text)


def test_slow_chinese_source_does_not_break_the_query():
    service = SpireCodexService(DummyClient(), chinese=SlowChinese(), timeout=2)
    result = asyncio.run(service.search("伤害怎么计算", ""))
    assert result["status"] == "not_found"


def test_service_uses_chinese_mechanics_and_character_guide():
    chinese = FakeChinese()
    service = SpireCodexService(DummyClient(), chinese=chinese, timeout=2)

    mechanics = asyncio.run(service.search("伤害怎么计算", ""))
    assert mechanics["status"] == "ok"
    assert mechanics["title"] == "03 易伤"
    assert "50%" in "\n".join(item["text"] for item in mechanics["evidence"])

    character = asyncio.run(
        service._entry(
            "character",
            {
                "id": "SILENT",
                "name": "静默猎手",
                "starting_deck": [],
                "starting_relics": [],
            },
            "攻略",
            "",
        )
    )
    assert "攻略" in character["available_sections"]
    assert "奇巧" in "\n".join(item["text"] for item in character["evidence"])


def test_chinese_source_honors_429_cooldown(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "30"})

    service = ChineseGuideService(
        Cache(Path(tmp_path)), timeout=2, transport=httpx.MockTransport(handler)
    )

    async def run():
        try:
            with pytest.raises(httpx.HTTPError):
                await service.mechanics("机制")
            with pytest.raises(httpx.HTTPError):
                await service.mechanics("机制")
        finally:
            await service.close()

    asyncio.run(run())
    assert len(calls) == 1


def test_guide_list_falls_back_to_sts2front_tips(tmp_path):
    """sts2.info/zh/guides WAF-blocks Python clients (deterministic 503)."""

    def handler(request):
        path = request.url.path
        if path == "/zh/guides":
            return httpx.Response(503, text="blocked")
        if path == "/zh-cn/tips/":
            return httpx.Response(200, text=TIPS_HTML)
        if path == "/zh-cn/tips/boss-guide/":
            return httpx.Response(200, text=TIP_HTML)
        return httpx.Response(404, text="Not Found")

    service = ChineseGuideService(
        Cache(Path(tmp_path)), timeout=5, transport=httpx.MockTransport(handler)
    )

    async def run():
        try:
            guide = await service.guide("BOSS攻略", "攻略")
            read = await service.read(guide["key"])
            return guide, read
        finally:
            await service.close()

    guide, read = asyncio.run(run())
    assert guide["key"] == "cn:guide:sts2front:tips:boss-guide"
    assert guide["url"].endswith("/zh-cn/tips/boss-guide/")
    assert "意图" in guide["text"]
    assert "力量叠加" in read["content"]
    assert service.url("cn:guide:sts2front:tips:boss-guide").endswith(
        "/zh-cn/tips/boss-guide/"
    )


def test_guide_sts2info_still_wins_when_reachable(tmp_path):
    def handler(request):
        path = request.url.path
        if path == "/zh/guides":
            return httpx.Response(200, text=GUIDES_HTML)
        if path == "/zh/guides/ascension-guide":
            return httpx.Response(200, text=ASCENSION_HTML)
        if path == "/zh-cn/tips/":
            raise AssertionError("reachable STS2.INFO must short-circuit the fallback")
        return httpx.Response(404, text="Not Found")

    service = ChineseGuideService(
        Cache(Path(tmp_path)), timeout=5, transport=httpx.MockTransport(handler)
    )

    async def run():
        try:
            return await service.guide("进阶", "")
        finally:
            await service.close()

    guide = asyncio.run(run())
    assert guide["key"] == "cn:guide:sts2info:ascension-guide"
    assert "逐级" in guide["text"]


def test_guide_sts2info_tarpit_falls_back_to_tips(tmp_path):
    async def handler(request):
        path = request.url.path
        if path == "/zh/guides":
            await asyncio.sleep(30)  # WAF tarpit: neither 503 nor a response
            return httpx.Response(200, text=GUIDES_HTML)
        if path == "/zh-cn/tips/":
            return httpx.Response(200, text=TIPS_HTML)
        if path == "/zh-cn/tips/boss-guide/":
            return httpx.Response(200, text=TIP_HTML)
        return httpx.Response(404, text="Not Found")

    service = ChineseGuideService(
        Cache(Path(tmp_path)), timeout=4, transport=httpx.MockTransport(handler)
    )

    async def run():
        try:
            return await asyncio.wait_for(service.guide("BOSS攻略", "攻略"), 15)
        finally:
            await service.close()

    guide = asyncio.run(run())
    assert guide["key"] == "cn:guide:sts2front:tips:boss-guide"


def test_tips_ranking_matches_coop_deck_and_enchant_questions(tmp_path):
    def handler(request):
        path = request.url.path
        if path == "/zh/guides":
            return httpx.Response(503, text="blocked")
        if path == "/zh-cn/tips/":
            return httpx.Response(200, text=TIPS_HTML)
        if path == "/zh-cn/tips/solo-vs-co-op/":
            return httpx.Response(200, text=TIP_HTML)
        if path == "/zh-cn/tips/best-combos/":
            return httpx.Response(
                200,
                text="<html><body><h1>最强卡牌组合</h1><main><section>"
                "<p>围绕一张核心卡构筑，而不是全拿。</p></section></main></body></html>",
            )
        if path == "/zh-cn/tips/enchantments/":
            return httpx.Response(
                200,
                text="<html><body><h1>附魔怎么选</h1><main><section>"
                "<p>附魔优先强化核心输出牌。</p></section></main></body></html>",
            )
        return httpx.Response(404, text="Not Found")

    service = ChineseGuideService(
        Cache(Path(tmp_path)), timeout=5, transport=httpx.MockTransport(handler)
    )

    async def run():
        try:
            coop = await service.guide("联机怎么玩", "")
            deck = await service.guide("卡组推荐", "")
            enchant = await service.guide("附魔怎么选", "")
            return coop, deck, enchant
        finally:
            await service.close()

    coop, deck, enchant = asyncio.run(run())
    assert coop["key"] == "cn:guide:sts2front:tips:solo-vs-co-op"
    assert deck["key"] == "cn:guide:sts2front:tips:best-combos"
    assert enchant["key"] == "cn:guide:sts2front:tips:enchantments"
