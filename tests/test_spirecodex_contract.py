"""Contract tests against recorded Spire Codex responses.

The hand-written tests in test_spirecodex.py pin our parsing assumptions.
These fixtures are real payloads, so a field rename or shape change upstream
is caught offline before it reaches a live query.
"""

import asyncio
import json
from pathlib import Path

import httpx

from wiki.cache import Cache
from wiki.card import render_card
from wiki.spirecodex import SpireCodexClient, SpireCodexService, entry_id

FIXTURES = Path(__file__).parent / "fixtures" / "spirecodex"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


CARD = load("card_strike_ironclad.json")
RELIC = load("relic_burning_blood.json")
LEAF = load("monster_leaf_slime_m.json")
WRIGGLER = load("monster_wriggler.json")
EVENT = load("event_abyssal_baths.json")
CHARACTER = load("character_ironclad.json")
SEARCH_STRIKE = load("search_strike.json")
CHANGELOGS = load("changelogs.json")


def make_service(tmp_path):
    def handler(request):
        path = request.url.path
        if path == "/api/changelogs":
            return httpx.Response(200, json=CHANGELOGS)
        if path == "/api/search":
            return httpx.Response(200, json=SEARCH_STRIKE)
        if path == "/api/cards":
            return httpx.Response(200, json=[CARD])
        if path == "/api/cards/strike_ironclad":
            return httpx.Response(200, json=CARD)
        if path == "/api/relics":
            return httpx.Response(200, json=[RELIC])
        if path == "/api/relics/burning_blood":
            return httpx.Response(200, json=RELIC)
        if path == "/api/monsters":
            return httpx.Response(200, json=[LEAF, WRIGGLER])
        if path == "/api/monsters/leaf_slime_m":
            return httpx.Response(200, json=LEAF)
        if path == "/api/monsters/wriggler":
            return httpx.Response(200, json=WRIGGLER)
        if path == "/api/events":
            return httpx.Response(200, json=[EVENT])
        if path == "/api/events/abyssal_baths":
            return httpx.Response(200, json=EVENT)
        if path == "/api/characters":
            return httpx.Response(200, json=[CHARACTER])
        if path == "/api/characters/ironclad":
            return httpx.Response(200, json=CHARACTER)
        return httpx.Response(404, json={"detail": "Not Found"})

    client = SpireCodexClient(
        Cache(tmp_path), timeout=2, transport=httpx.MockTransport(handler)
    )
    return SpireCodexService(client, timeout=2), client


def run(tmp_path, operation):
    service, client = make_service(tmp_path)

    async def wrapped():
        try:
            return await operation(service)
        finally:
            await client.close()

    return asyncio.run(wrapped())


def test_recorded_card_parses_and_sets_data_version(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("card", "STRIKE_IRONCLAD"), "伤害"),
    )
    assert result["status"] == "ok"
    assert result["title"] == "打击"
    assert result["data_version"] == "1.3.1"
    assert "数值" in result["available_sections"]
    assert any("6" in item["text"] for item in result["evidence"])


def test_recorded_relic_renders_evidence_card(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("relic", "BURNING_BLOOD"), "效果"),
    )
    sections = [(item["section"], item["text"]) for item in result["evidence"]]
    png = render_card(
        result["title"],
        result["source"],
        sections,
        (170, 52, 44),
        font_dir=Path("assets/fonts"),
    )
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_recorded_relic_parses(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("relic", "BURNING_BLOOD"), "效果"),
    )
    assert result["status"] == "ok"
    assert result["title"] == "燃烧之血"
    assert any("6" in item["text"] for item in result["evidence"])
    assert result["image_url"].endswith("/static/images/relics/burning_blood.webp")


def test_recorded_monster_attack_pattern_has_names_not_ids(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("monster", "WRIGGLER"), "出招顺序"),
    )
    assert result["status"] == "ok"
    assert "出招顺序" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "污秽啃咬" in text or "扭动" in text
    assert "NASTY_BITE" not in text and "WRIGGLE_MOVE" not in text


def test_recorded_event_branches_are_rendered(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("event", "ABYSSAL_BATHS"), "其他选项"),
    )
    assert result["status"] == "ok"
    assert "分支" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "沉溺" in text or "离开浴场" in text
    assert "INITIAL" not in text


def test_recorded_character_deck_resolves_card_names(tmp_path):
    result = run(
        tmp_path,
        lambda service: service.read(entry_id("character", "IRONCLAD"), "初始卡组"),
    )
    assert result["status"] == "ok"
    assert "初始卡组" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "打击" in text


def test_recorded_search_deduplicates_and_labels_cards(tmp_path):
    result = run(tmp_path, lambda service: service.search("打击", ""))
    assert result["status"] == "needs_choice"
    titles = [item["title"] for item in result["candidates"]]
    assert len(titles) == len(set(titles)) == 5
    assert all(title.startswith("打击 · ") for title in titles)


def test_kind_prefix_is_stripped_before_search(tmp_path):
    result = run(tmp_path, lambda service: service.search("卡牌 打击", ""))
    assert result["status"] == "needs_choice"
    assert result["query"] == "卡牌 打击"
    assert result["normalized_query"] == "打击"
