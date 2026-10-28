"""Multi-game profile, cache isolation and URL tests."""

import unittest
from urllib.parse import quote

import httpx

from wiki.cache import Cache
from wiki.client import WikiClient
from wiki.games import PROFILES, YS, parse_alias_config
from wiki.models import page_url
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
