"""Offline tests for the Spire Codex (Slay the Spire 2) adapter."""

import asyncio

import httpx
import pytest

from wiki.cache import Cache
from wiki.formatter import format_command, format_compare
from wiki.games import default_source, source_api
from wiki.models import WikiError
from wiki.spirecodex import (
    BASE,
    KIND_CODES,
    SpireCodexClient,
    SpireCodexService,
    clean,
    effect_text,
    entry_id,
)

COLORS = ("ironclad", "silent", "regent", "necrobinder", "defect")
CARD_NAMES = {
    "ironclad": "铁甲战士",
    "silent": "静默猎手",
    "regent": "储君",
    "necrobinder": "亡灵契约师",
    "defect": "故障机器人",
}


def card(key, name, color, **extra):
    return {
        "id": key,
        "name": name,
        "description": "造成6点伤害。",
        "description_raw": "造成{Damage:diff()}点伤害。",
        "cost": 1,
        "type": "攻击",
        "rarity": "基础",
        "target": "AnyEnemy",
        "color": color,
        "keywords": None,
        "damage": 6,
        "block": None,
        "hit_count": None,
        "cards_draw": None,
        "energy_gain": None,
        "hp_loss": None,
        "powers_applied": None,
        "upgrade_description": "造成9点伤害。",
        "image_url": f"/static/images/cards/{key.lower()}.webp",
        "image_url_card": f"https://cdn.spire-codex.com/cards-full/stable/{key.lower()}.webp",
        **extra,
    }


CARDS = [card(f"STRIKE_{color.upper()}", "打击", color) for color in COLORS] + [
    card("DEFEND_IRONCLAD", "防御", "ironclad", block=5, damage=None),
    card("BASH", "重击", "ironclad", damage=8),
    card("INFLAME", "燃烧", "ironclad", damage=None, description="获得2点力量。"),
]
RELICS = [
    {
        "id": "BURNING_BLOOD",
        "name": "燃烧之血",
        "description": "在战斗结束时，回复[green]6[/green]点生命。",
        "description_raw": "在战斗结束时，回复[green]{Heal}[/green]点生命。",
        "flavor": "[red]这个遗物的细节将在未来揭晓……[/red]",
        "rarity": "初始遗物",
        "pool": "ironclad",
        "merchant_price": None,
        "image_url": "/static/images/relics/burning_blood.webp",
    },
    {
        "id": "RED_SKULL",
        "name": "红头骨",
        "description": "生命值低于50%时，获得3点力量。",
        "rarity": "普通",
        "pool": "ironclad",
        "merchant_price": 150,
        "image_url": "/static/images/relics/red_skull.webp",
    },
]
CHARACTERS = [
    {
        "id": "IRONCLAD",
        "name": "铁甲战士",
        "description": "铁甲军团最后的士兵。",
        "starting_hp": 80,
        "starting_gold": 99,
        "max_energy": 3,
        "orb_slots": None,
        "starting_relics": ["BurningBlood"],
        "starting_deck": [
            "StrikeIronclad",
            "StrikeIronclad",
            "DefendIronclad",
            "Bash",
        ],
        "unlocks_after": None,
    }
]
GLOSSARY = [
    {
        "id": "BLOCK",
        "name": "格挡",
        "description": "在下个回合前，阻挡伤害。",
        "category": "combat",
    }
]
ORBS = [
    {
        "id": "DARK_ORB",
        "name": "黑暗",
        "description": "被动：回合结束时，将这个充能球的伤害增加6。",
        "description_raw": "被动：回合结束时，将这个充能球的伤害增加{Passive}。",
        "image_url": "/static/images/orbs/dark_orb.png",
    }
]
GUIDES = [
    {
        "id": "boss-guide",
        "slug": "boss-guide",
        "title": "Boss Guide: Every Boss Ranked by Deadliness",
        "author": "Spire Codex",
        "date": "2026-07-16",
        "category": "general",
        "tags": ["bosses", "strategy"],
        "summary": "Every boss ranked by how many runs it ends.",
        "difficulty": "intermediate",
        "content": "## Act 1\n\nWatch [[relic:Burning Blood]] and [the tier list](https://example.test).",
    }
]
MECHANICS = [
    {
        "slug": "combat-mechanics",
        "title": "Combat Mechanics",
        "description": "Hand size, energy, block decay and damage formulas.",
        "category": "mechanics",
        "order": 9,
        "body_markdown": "## Attack\n\n**Strength** adds damage.\n\n| Effect | Per stack |\n|---|---|\n| Strength | +1 |",
    }
]
ASCENSIONS = [
    {
        "id": "LEVEL_10",
        "level": 10,
        "name": "双重Boss",
        "description": "在第3幕末尾与两名首领战斗。",
    }
]
ACTS = [
    {
        "id": "OVERGROWTH",
        "name": "密林",
        "index": 0,
        "num_rooms": 15,
        "bosses": ["WRIGGLER"],
        "ancients": ["NEOW"],
        "events": ["ABYSSAL_BATHS"],
        "encounters": ["SLIMES_NORMAL", "ELITE_NORMAL"],
    }
]
ACHIEVEMENTS = [
    {
        "id": "ALL_CARDS_UPGRADED",
        "name": "完美牌组",
        "description": "以全部升级的牌组赢得一局游戏。",
        "category": "run",
        "character": None,
        "threshold": None,
        "condition": "Win with a fully-upgraded deck",
    }
]
UNLOCKS = {
    "characters": [
        {
            "id": "SILENT",
            "name": "静默猎手",
            "epoch_id": "SILENT1_EPOCH",
            "epoch_title": "迷雾压境",
            "era": "门扉",
            "unlock_info": "以铁甲战士完成一局游戏来揭示这个历史节点。",
        }
    ]
}
ENCOUNTERS = [
    {
        "id": "SLIMES_NORMAL",
        "name": "一大群史莱姆",
        "room_type": "Monster",
        "is_weak": False,
        "act": "Act 1 - Overgrowth",
    },
    {
        "id": "ELITE_NORMAL",
        "name": "密林精英",
        "room_type": "Elite",
        "is_weak": False,
        "act": "Act 1 - Overgrowth",
    },
]
MONSTERS = [
    {"id": "WRIGGLER", "name": "扭动虫", "type": "Elite", "min_hp": 10, "max_hp": 12}
]
EVENTS = [
    {
        "id": "ABYSSAL_BATHS",
        "name": "深渊浴场",
        "description": "池水灼烧。",
        "options": [],
        "pages": [],
    }
]
SEARCH = {
    "guide": {
        "query": "guide",
        "categories": [
            {
                "kind": "guide",
                "items": [
                    {
                        "name": "Boss Guide: Every Boss Ranked by Deadliness",
                        "path": "/guides/boss-guide",
                        "subtitle": "general",
                    }
                ],
            },
            {
                "kind": "mechanics",
                "items": [
                    {
                        "name": "Combat Mechanics",
                        "path": "/mechanics/combat-mechanics",
                        "subtitle": "mechanics",
                    }
                ],
            },
        ],
    },
    "mechanics": {
        "query": "mechanics",
        "categories": [
            {
                "kind": "mechanics",
                "items": [
                    {
                        "name": "Combat Mechanics",
                        "path": "/mechanics/combat-mechanics",
                        "subtitle": "mechanics",
                    }
                ],
            }
        ],
    },
    "红头骨": {
        "query": "红头骨",
        "categories": [
            {
                "kind": "relic",
                "items": [
                    {
                        "name": "红头骨",
                        "path": "/relics/red_skull",
                        "subtitle": "普通遗物 · ironclad",
                    }
                ],
            }
        ],
    },
    "重击": {
        "query": "重击",
        "categories": [
            {
                "kind": "card",
                "items": [
                    {
                        "name": "重击",
                        "path": "/cards/bash",
                        "subtitle": "ironclad · 攻击 · 基础",
                    }
                ],
            }
        ],
    },
    "防御": {
        "query": "防御",
        "categories": [
            {
                "kind": "card",
                "items": [
                    {
                        "name": "防御",
                        "path": "/cards/defend_ironclad",
                        "subtitle": "ironclad · 技能 · 基础",
                    }
                ],
            }
        ],
    },
    "格挡": {
        "query": "格挡",
        "categories": [
            {
                "kind": "reference",
                "items": [{"name": "守势", "path": "/reference", "subtitle": "Intent"}],
            }
        ],
    },
    "黑暗": {
        "query": "黑暗",
        "categories": [
            {
                "kind": "reference",
                "items": [{"name": "黑暗", "path": "/reference", "subtitle": "Orb"}],
            }
        ],
    },
    "燃烧之血": {
        "query": "燃烧之血",
        "categories": [
            {
                "label": "Relics",
                "kind": "relic",
                "items": [
                    {
                        "name": "燃烧之血",
                        "path": "/relics/burning_blood",
                        "subtitle": "初始遗物 · ironclad",
                    }
                ],
            }
        ],
    },
    "打击": {
        "query": "打击",
        "categories": [
            {
                "label": "Cards",
                "kind": "card",
                "items": [
                    {
                        "name": "打击",
                        "path": f"/cards/strike_{color}",
                        "subtitle": f"{color} · 攻击 · 基础",
                    }
                    for color in COLORS
                ],
            }
        ],
    },
    "铁甲战士": {
        "query": "铁甲战士",
        "categories": [
            {
                "label": "Characters",
                "kind": "character",
                "items": [
                    {
                        "name": "铁甲战士",
                        "path": "/characters/ironclad",
                        "subtitle": "",
                    }
                ],
            }
        ],
    },
    "Bash": {
        "query": "Bash",
        "categories": [
            {
                "label": "Cards",
                "kind": "card",
                "items": [
                    {
                        "name": "Bash",
                        "path": "/cards/bash",
                        "subtitle": "ironclad · Attack · Basic",
                    }
                ],
            }
        ],
    },
}


def make_service(tmp_path, calls=None):
    calls = calls if calls is not None else []

    def handler(request):
        path = request.url.path
        params = request.url.params
        calls.append((path, params.get("lang"), params.get("q")))
        if path == "/api/search":
            q, lang = params.get("q"), params.get("lang")
            payload = SEARCH.get(q)
            if payload is not None and (
                lang == "zhs" or q in {"Bash", "guide", "mechanics"}
            ):
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json={"query": q, "categories": []})
        if path == "/api/changelogs":
            return httpx.Response(200, json=[{"game_version": "1.3.1", "tag": "1.3.1"}])
        if path == "/api/cards":
            return httpx.Response(200, json=CARDS)
        if path.startswith("/api/cards/"):
            key = path.rsplit("/", 1)[-1].upper()
            entity = next((item for item in CARDS if item["id"] == key), None)
            return httpx.Response(
                200 if entity else 404,
                json=entity or {"detail": "Not Found"},
            )
        if path == "/api/relics":
            return httpx.Response(200, json=RELICS)
        if path.startswith("/api/relics/"):
            key = path.rsplit("/", 1)[-1].upper()
            entity = next((item for item in RELICS if item["id"] == key), None)
            return httpx.Response(
                200 if entity else 404,
                json=entity or {"detail": "Not Found"},
            )
        if path == "/api/characters":
            return httpx.Response(200, json=CHARACTERS)
        if path.startswith("/api/characters/"):
            key = path.rsplit("/", 1)[-1].upper()
            entity = next((item for item in CHARACTERS if item["id"] == key), None)
            return httpx.Response(
                200 if entity else 404,
                json=entity or {"detail": "Not Found"},
            )
        if path == "/api/glossary":
            return httpx.Response(200, json=GLOSSARY)
        if path == "/api/glossary/block":
            return httpx.Response(200, json=GLOSSARY[0])
        if path == "/api/orbs":
            return httpx.Response(200, json=ORBS)
        if path == "/api/orbs/dark_orb":
            return httpx.Response(200, json=ORBS[0])
        if path in {"/api/afflictions", "/api/keywords", "/api/enchantments"}:
            return httpx.Response(200, json=[])
        if path == "/api/pairings/cards/inflame":
            return httpx.Response(
                200,
                json={
                    "partners": {
                        "cards": [
                            {
                                "id": "SETUP_STRIKE",
                                "name": "预备打击",
                                "winrate": 0.3665,
                                "co": 15741,
                            }
                        ]
                    }
                },
            )
        if path == "/api/draft-recs/cards/inflame":
            return httpx.Response(
                200,
                json={
                    "recommends": [
                        {
                            "id": "CELESTIAL_MIGHT",
                            "name": "天穹之力",
                            "pref": 0.159,
                            "winrate": 0.4762,
                        }
                    ]
                },
            )
        if path == "/api/runs/scores/cards":
            return httpx.Response(
                200, json={"INFLAME": {"win_rate": 43.6, "picks": 100, "score": 80}}
            )
        if path == "/api/runs/scores/relics":
            return httpx.Response(
                200,
                json={
                    "BURNING_BLOOD": {
                        "win_rate": 40.0,
                        "picks": 100,
                        "score": 70,
                    },
                    "RED_SKULL": {"win_rate": 50.0, "picks": 80, "score": 80},
                },
            )
        if path == "/api/runs/community-stats":
            return httpx.Response(
                200,
                json={
                    "by_character": [
                        {
                            "id": "ironclad",
                            "win_rate": 27.3,
                            "share": 23.0,
                            "runs": 517627,
                        }
                    ],
                    "by_ascension": [
                        {
                            "ascension": 10,
                            "runs": 635753,
                            "wins": 134403,
                            "abandoned": 58810,
                            "win_rate": 21.1,
                        }
                    ],
                },
            )
        if path == "/api/ascensions":
            return httpx.Response(200, json=ASCENSIONS)
        if path == "/api/acts":
            return httpx.Response(200, json=ACTS)
        if path == "/api/achievements":
            return httpx.Response(200, json=ACHIEVEMENTS)
        if path == "/api/unlocks":
            return httpx.Response(200, json=UNLOCKS)
        if path == "/api/monsters":
            return httpx.Response(200, json=MONSTERS)
        if path == "/api/encounters":
            return httpx.Response(200, json=ENCOUNTERS)
        if path == "/api/events":
            return httpx.Response(200, json=EVENTS)
        if path == "/api/guides":
            return httpx.Response(200, json=GUIDES)
        if path == "/api/guides/boss-guide":
            return httpx.Response(200, json=GUIDES[0])
        if path == "/api/mechanics/sections":
            return httpx.Response(200, json=MECHANICS)
        if path == "/api/mechanics/sections/combat-mechanics":
            return httpx.Response(200, json=MECHANICS[0])
        return httpx.Response(404, json={"detail": "Not Found"})

    client = SpireCodexClient(
        Cache(tmp_path), timeout=2, transport=httpx.MockTransport(handler)
    )
    return SpireCodexService(client, timeout=10), client, calls


def test_profile_source_and_page_id_contract():
    assert default_source("sts2") == "spirecodex"
    assert source_api("sts2", "spirecodex") == BASE
    page_id = entry_id("card", "STRIKE_IRONCLAD")
    assert page_id >> 48 == KIND_CODES["card"]
    assert 0 < page_id < 2**53
    assert page_id != entry_id("relic", "STRIKE_IRONCLAD")


def test_character_and_encounter_labels_and_images(tmp_path):
    assert (
        SpireCodexService._label(
            {"name": "一大群史莱姆", "kind": "encounter", "subtitle": "Monster"}
        )
        == "一大群史莱姆 · 普通战斗"
    )
    service, client, _ = make_service(tmp_path)
    try:
        assert (
            service._image_url("character", {"id": "IRONCLAD"})
            == "https://cdn.spire-codex.com/characters/combat_ironclad.webp"
        )
    finally:
        asyncio.run(client.close())


def test_custom_base_and_version_marker(tmp_path):
    service, client, _ = make_service(tmp_path)
    try:
        service.base = "https://example.test"
        service.cdn = "https://cdn.example.test"
        assert (
            service._url("relic", "BURNING_BLOOD")
            == "https://example.test/zhs/relics/burning_blood"
        )
        assert (
            service._image_url("character", {"id": "IRONCLAD"})
            == "https://cdn.example.test/characters/combat_ironclad.webp"
        )

        service._version_value = "old"
        service._indexes[("card", "zhs")] = [{"id": "STALE"}]
        service._known[1] = ("card", "STALE")
        value = asyncio.run(service._version())
        assert value == "1.3.1"
        assert service._indexes == {}
        assert service._known == {}
    finally:
        asyncio.run(client.close())


def test_bbcode_and_empty_values_are_cleaned():
    assert clean("[gold]6[/gold]点伤害") == "6点伤害"
    assert clean("[energy:1]") == "1费"
    assert clean("[sine][blue]“你好”[/blue][/sine]") == "“你好”"
    assert clean("[blue][/blue]") == "X"
    assert effect_text({"description": "获得[blue][/blue]点力量。"}) == (
        "获得X点力量。"
    )


def test_exact_relic_search_returns_sections_and_source(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("燃烧之血", "效果")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "燃烧之血"
    assert result["game"] == "sts2"
    assert result["source_key"] == "spirecodex"
    assert result["url"] == f"{BASE}/zhs/relics/burning_blood"
    assert "效果" in result["available_sections"]
    assert any(item["section"] == "效果" for item in result["evidence"])
    assert result["image_url"] == f"{BASE}/static/images/relics/burning_blood.webp"


def test_duplicate_card_names_become_numbered_candidates(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("打击", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "needs_choice"
    assert len(result["candidates"]) == 5
    titles = [item["title"] for item in result["candidates"]]
    assert all(title.startswith("打击 · ") for title in titles)
    assert any("铁甲战士" in title for title in titles)
    assert all(isinstance(item["page_id"], int) for item in result["candidates"])
    assert "找到多个" in format_command(result)
    assert "没有与" not in format_command(result)


def test_read_resolves_page_id_through_the_kind_index(tmp_path):
    service, client, calls = make_service(tmp_path)

    async def run():
        try:
            search = await service.search("打击", "")
            result = await service.read(search["candidates"][0]["page_id"], "伤害")
            return search, result
        finally:
            await client.close()

    search, result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "打击"
    assert "数值" in result["available_sections"]
    assert any("6" in item["text"] for item in result["evidence"])
    assert ("/api/cards/strike_ironclad", "zhs", None) in calls


def test_character_initial_deck_resolves_pascal_case_ids(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("铁甲战士", "初始卡组")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "初始卡组" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "打击" in text and "重击" in text
    assert "StrikeIronclad" not in text
    assert "初始遗物" in result["available_sections"]
    assert "燃烧之血" in "\n".join(item["text"] for item in result["evidence"])


def test_english_query_searches_eng_then_reads_chinese(tmp_path):
    service, client, calls = make_service(tmp_path)

    async def run():
        try:
            return await service.search("Bash", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "重击"
    assert ("/api/search", "eng", "Bash") in calls
    assert ("/api/cards/bash", "zhs", None) in calls


def test_repeated_search_uses_cache_and_in_memory_index(tmp_path):
    service, client, calls = make_service(tmp_path)

    async def run():
        try:
            await service.search("燃烧之血", "效果")
            first = len(calls)
            await service.search("燃烧之血", "效果")
            return first, len(calls)
        finally:
            await client.close()

    first, second = asyncio.run(run())
    assert first == second, "a repeated query must not hit the upstream again"


def test_community_sections_are_fetched_for_recommendation_questions(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            result = await service.read(entry_id("card", "INFLAME"), "", "搭配")
            assert "搭配" in result["available_sections"]
            assert "推荐" in result["available_sections"]
            assert "胜率" in result["available_sections"]
            pairing = "\n".join(item["text"] for item in result["evidence"])
            assert "预备打击" in pairing and "36.6%" in pairing
            draft = await service.read(entry_id("card", "INFLAME"), "", "推荐")
            assert "天穹之力" in "\n".join(item["text"] for item in draft["evidence"])
            score = await service.read(entry_id("card", "INFLAME"), "", "胜率")
            assert "43.6%" in "\n".join(item["text"] for item in score["evidence"])
        finally:
            await client.close()

    asyncio.run(run())


def test_guide_question_returns_guide_and_mechanics(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            search = await service.search("攻略", "")
            return search, await service.read(
                search["candidates"][0]["page_id"], "攻略"
            )
        finally:
            await client.close()

    search, result = asyncio.run(run())
    assert search["status"] == "needs_choice"
    titles = [item["title"] for item in search["candidates"]]
    assert any("Boss Guide" in title for title in titles)
    assert any("Combat Mechanics" in title for title in titles)
    assert result["status"] == "ok"
    assert "正文" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "Burning Blood" in text
    assert "[[" not in text and "##" not in text
    assert result["url"].endswith("/zhs/guides/boss-guide")


def test_mechanic_markdown_is_flattened(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.read(entry_id("mechanic", "combat-mechanics"), "机制")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["url"].endswith("/zhs/mechanics/combat-mechanics")
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "Strength adds damage" in text
    assert "**" not in text and "##" not in text


def test_glossary_reference_falls_back_to_term(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("格挡", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "格挡"
    assert result["url"] == f"{BASE}/zhs/reference"
    assert any("阻挡伤害" in item["text"] for item in result["evidence"])


def test_orb_reference_falls_back_to_term(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("黑暗", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "黑暗"
    assert result["url"] == f"{BASE}/zhs/orbs/dark_orb"
    assert result["image_url"] == f"{BASE}/static/images/orbs/dark_orb.png"


def test_read_rejects_foreign_ids_and_sources(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            with pytest.raises(WikiError):
                await service.read(0)
            with pytest.raises(WikiError):
                await service.read(entry_id("card", "STRIKE_IRONCLAD"), source="bwiki")
            with pytest.raises(WikiError):
                await service.read(entry_id("relic", "MISSING"))
        finally:
            await client.close()

    asyncio.run(run())


def test_compare_two_relics_returns_dimensions_and_metrics(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.compare("燃烧之血", "红头骨")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "compare"
    assert result["kind"] == "relic"
    labels = [item["label"] for item in result["dimensions"]]
    assert "稀有度" in labels and "效果" in labels
    assert result["left"]["metrics"]["win_rate"] == 40.0
    assert result["right"]["metrics"]["win_rate"] == 50.0


def test_compare_two_cards(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.compare("重击", "防御")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "compare"
    assert result["kind"] == "card"
    labels = [item["label"] for item in result["dimensions"]]
    assert "费用" in labels and "效果" in labels


def test_compare_cross_kind_and_ambiguous_are_explained(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            cross = await service.compare("燃烧之血", "重击")
            ambiguous = await service.compare("打击", "防御")
            return cross, ambiguous
        finally:
            await client.close()

    cross, ambiguous = asyncio.run(run())
    assert cross["status"] == "compare_unsupported"
    assert "类型不同" in format_compare(cross)
    assert ambiguous["status"] == "compare_unavailable"
    assert "分开查询" in format_compare(ambiguous)


def test_format_compare_renders_data_and_sources(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.compare("燃烧之血", "红头骨")
        finally:
            await client.close()

    text = format_compare(asyncio.run(run()))
    assert "【对比】燃烧之血 vs 红头骨" in text
    assert "稀有度" in text and "｜" in text
    assert "社区数据" in text and "来源" in text


def test_meta_ascension_achievement_unlock_and_act(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            ascension = await service.search("A10", "")
            achievement = await service.search("成就", "")
            unlock = await service.search("怎么解锁静默猎手", "")
            act = await service.search("第一章有什么精英", "")
            return ascension, achievement, unlock, act
        finally:
            await client.close()

    ascension, achievement, unlock, act = asyncio.run(run())
    assert ascension["status"] == "ok"
    assert ascension["title"] == "进阶10 双重Boss"
    assert "社区胜率" in ascension["available_sections"]
    assert achievement["status"] == "ok"
    assert "成就列表" in achievement["available_sections"]
    assert "完美牌组" in "\n".join(item["text"] for item in achievement["evidence"])
    assert unlock["status"] == "ok"
    assert "解锁条件" in unlock["available_sections"]
    assert "铁甲战士" in "\n".join(item["text"] for item in unlock["evidence"])
    assert act["status"] == "ok"
    assert act["title"] == "密林"
    assert "BOSS" in act["available_sections"]
    assert "精英" in act["available_sections"]
