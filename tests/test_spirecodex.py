"""Offline tests for the Spire Codex (Slay the Spire 2) adapter."""

import asyncio

import httpx
import pytest

from wiki.cache import Cache
from wiki.formatter import format_command
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
    }
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
SEARCH = {
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
            if payload is not None and (lang == "zhs" or q == "Bash"):
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json={"query": q, "categories": []})
        if path == "/api/cards":
            return httpx.Response(200, json=CARDS)
        if path == "/api/relics":
            return httpx.Response(200, json=RELICS)
        if path == "/api/characters":
            return httpx.Response(200, json=CHARACTERS)
        return httpx.Response(404, json={"detail": "Not Found"})

    client = SpireCodexClient(
        Cache(tmp_path), timeout=2, transport=httpx.MockTransport(handler)
    )
    return SpireCodexService(client, timeout=2), client, calls


def test_profile_source_and_page_id_contract():
    assert default_source("sts2") == "spirecodex"
    assert source_api("sts2", "spirecodex") == BASE
    page_id = entry_id("card", "STRIKE_IRONCLAD")
    assert page_id >> 48 == KIND_CODES["card"]
    assert 0 < page_id < 2**53
    assert page_id != entry_id("relic", "STRIKE_IRONCLAD")


def test_character_and_encounter_labels_and_images():
    assert (
        SpireCodexService._label(
            {"name": "一大群史莱姆", "kind": "encounter", "subtitle": "Monster"}
        )
        == "一大群史莱姆 · 普通战斗"
    )
    assert (
        SpireCodexService._image_url("character", {"id": "IRONCLAD"})
        == "https://cdn.spire-codex.com/characters/combat_ironclad.webp"
    )


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
    assert ("/api/cards", "zhs", None) in calls


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
    assert ("/api/cards", "zhs", None) in calls


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
