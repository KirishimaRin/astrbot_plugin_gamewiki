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
RARITY_KEYS = {
    "基础": "Basic",
    "普通": "Common",
    "罕见": "Uncommon",
    "稀有": "Rare",
    "先古": "Ancient",
}
TYPE_KEYS = {"攻击": "Attack", "技能": "Skill", "能力": "Power"}


def card(key, name, color, **extra):
    entity = {
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
    entity["rarity_key"] = RARITY_KEYS.get(entity["rarity"], entity["rarity"])
    entity["type_key"] = TYPE_KEYS.get(entity["type"], entity["type"])
    return entity


CARDS = [card(f"STRIKE_{color.upper()}", "打击", color) for color in COLORS] + [
    card("DEFEND_IRONCLAD", "防御", "ironclad", block=5, damage=None),
    card("BASH", "重击", "ironclad", damage=8),
    card("INFLAME", "燃烧", "ironclad", damage=None, description="获得2点力量。"),
    card("BLUDGEON", "重砍", "ironclad", rarity="稀有", cost=3, damage=32),
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
    {
        "id": "RING_OF_SNAKES",
        "name": "蛇之环",
        "description": "每回合开始时，获得1点格挡。",
        "rarity": "初始遗物",
        "pool": "silent",
        "merchant_price": None,
        "image_url": "/static/images/relics/ring_of_snakes.webp",
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
    },
    {
        "id": "SILENT",
        "name": "静默猎手",
        "description": "静默猎手靠奇巧和弃牌。",
        "starting_hp": 70,
        "starting_gold": 99,
        "max_energy": 3,
        "orb_slots": None,
        "starting_relics": [],
        "starting_deck": [],
        "unlocks_after": None,
    },
]
GLOSSARY = [
    {
        "id": "BLOCK",
        "name": "格挡",
        "description": "在下个回合前，阻挡伤害。",
        "category": "combat",
    }
]
AFFLICTIONS = [
    {
        "id": "ASCENDERS_BANE",
        "name": "进阶之灾",
        "description": "不可移除的诅咒。",
        "category": "curse",
    },
    {
        "id": "DOUBT",
        "name": "疑虑",
        "description": "无法打出，回合结束时受到伤害。",
        "category": "curse",
    },
]
KEYWORDS = [{"id": "EXHAUST", "name": "消耗", "description": "本场战斗中不再出现。"}]
ENCHANTMENTS = [
    {
        "id": "SHARP",
        "name": "锋利",
        "description": "攻击牌额外造成1点伤害。",
        "card_type": "Attack",
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
CARD_RARITY_MECHANIC = {
    "slug": "card-rarity",
    "title": "Card Rarity Odds",
    "description": "Card reward rarity chances for each fight type.",
    "category": "mechanics",
    "order": 1,
    "body_markdown": "## Normal Fights\n\nCommon 60%.\n\nBoss rewards are always rare.",
}
SCORE_MECHANIC = {
    "slug": "score-formula",
    "title": "Scoring & Daily Leaderboards",
    "description": "How run score is calculated, plus the daily leaderboard.",
    "category": "mechanics",
    "order": 16,
    "body_markdown": "## Run Score\n\n10 pts per room, act multipliers apply.\n\n## Daily\n\nDaily runs rank on a leaderboard.",
}
UNKNOWN_ROOMS_MECHANIC = {
    "slug": "unknown-rooms",
    "title": "Unknown Room Probabilities",
    "description": "What each ? room can contain.",
    "category": "mechanics",
    "order": 7,
    "body_markdown": "## Unknown Rooms\n\nShop 22%, treasure 22%, rest 22%.",
}
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
    "relics": [
        {
            "id": "RED_SKULL",
            "name": "红头骨",
            "epoch_id": "RELIC1_EPOCH",
            "epoch_title": "涂鸦",
            "unlock_info": "通过积累分数来解锁。",
        }
    ],
    "characters": [
        {
            "id": "SILENT",
            "name": "静默猎手",
            "epoch_id": "SILENT1_EPOCH",
            "epoch_title": "迷雾压境",
            "era": "门扉",
            "unlock_info": "以铁甲战士完成一局游戏来揭示这个历史节点。",
        }
    ],
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
    {
        "id": "WRIGGLER",
        "name": "扭动虫",
        "type": "Elite",
        "min_hp": 10,
        "max_hp": 12,
        "min_hp_ascension": 11,
        "max_hp_ascension": 13,
        "innate_powers": [],
        "moves": [
            {
                "id": "BITE",
                "name": "撕咬",
                "intent": "Attack",
                "damage": {"normal": 7, "ascension": 8, "hit_count": None},
                "block": None,
                "heal": None,
                "powers": None,
            }
        ],
        "attack_pattern": {"type": "sequential", "initial_move": "BITE", "states": []},
    },
    {
        "id": "KNOWLEDGE_DEMON",
        "name": "知识恶魔",
        "type": "Boss",
        "min_hp": 160,
        "max_hp": 160,
        "min_hp_ascension": 168,
        "max_hp_ascension": 168,
        "innate_powers": [{"power": "力量", "amount": 3}],
        "moves": [
            {
                "id": "CURSE_OF_KNOWLEDGE",
                "name": "知识的诅咒",
                "intent": "Debuff",
                "damage": None,
                "block": None,
                "heal": None,
                "powers": None,
            },
            {
                "id": "SLAP",
                "name": "抽打",
                "intent": "Attack",
                "damage": {"normal": 17, "ascension": 18, "hit_count": 2},
                "block": None,
                "heal": None,
                "powers": None,
            },
        ],
        "attack_pattern": {
            "type": "conditional",
            "initial_move": "CURSE_OF_KNOWLEDGE",
            "states": [],
        },
    },
]
ANCIENT_POOLS = [
    {
        "id": "DARV",
        "name": "Darv",
        "description": "Has a large pool of powerful relics.",
        "selection": "3 from pool or 2 + Dusty Tome",
        "pools": [],
    }
]
EPOCHS = [
    {
        "id": "SILENT1_EPOCH",
        "title": "迷雾压境",
        "description": "静默猎手的历史节点。",
        "era_name": "门扉",
        "unlock_info": "以铁甲战士完成一局游戏。",
        "unlocks_cards": [],
        "unlocks_relics": [],
        "unlocks_potions": [],
        "story_id": "SILENT",
    }
]
STORIES = [{"id": "SILENT", "name": "静默猎手", "epochs": ["SILENT1_EPOCH"]}]
MERCHANT_CONFIG = {
    "card_removal": {
        "base_cost": 75,
        "price_increase": 25,
        "inflation_ascension": {
            "base_cost": 100,
            "price_increase": 50,
            "level": "Inflation",
        },
    },
    "cards": {
        "by_rarity": {
            "Common": {"base": 50, "min": 48, "max": 52},
            "Rare": {"base": 150, "min": 142, "max": 158},
        }
    },
    "relics": {"by_rarity": {"Common": {"base": 175, "min": 149, "max": 201}}},
    "potions": {"by_rarity": {"Common": {"base": 50, "min": 48, "max": 52}}},
    "fake_merchant": {"relic_cost": 50},
}
EVENTS = [
    {
        "id": "ABYSSAL_BATHS",
        "name": "深渊浴场",
        "description": "池水灼烧。",
        "options": [
            {
                "id": "LINGER",
                "title": "沉溺",
                "description": "获得2点最大生命，受到3点伤害。",
            },
            {"id": "EXIT_BATHS", "title": "离开浴场", "description": ""},
        ],
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
    "附魔怎么选": {
        "query": "附魔怎么选",
        "categories": [
            {
                "kind": "relic",
                "items": [
                    {
                        "name": "亮片",
                        "path": "/relics/sequins",
                        "subtitle": "先古遗物 · shared",
                    }
                ],
            }
        ],
    },
    "燃燒之血": {
        "query": "燃燒之血",
        "categories": [
            {
                "kind": "relic",
                "items": [
                    {
                        "name": "燃燒之血",
                        "path": "/relics/burning_blood",
                        "subtitle": "初始遺物 · ironclad",
                    }
                ],
            }
        ],
    },
    "静默猎手": {
        "query": "静默猎手",
        "categories": [
            {
                "kind": "character",
                "items": [
                    {
                        "name": "静默猎手",
                        "path": "/characters/silent",
                        "subtitle": "",
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
    "深渊浴场": {
        "query": "深渊浴场",
        "categories": [
            {
                "kind": "event",
                "items": [
                    {
                        "name": "深渊浴场",
                        "path": "/events/abyssal_baths",
                        "subtitle": "Shared",
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
    "诅咒": {
        "query": "诅咒",
        "categories": [
            {
                "kind": "affliction",
                "items": [
                    {
                        "name": "进阶之灾",
                        "path": "/afflictions/ascenders_bane",
                        "subtitle": "Curse",
                    },
                    {
                        "name": "疑虑",
                        "path": "/afflictions/doubt",
                        "subtitle": "Curse",
                    },
                ],
            }
        ],
    },
    "知识恶魔": {
        "query": "知识恶魔",
        "categories": [
            {
                "kind": "monster",
                "items": [
                    {
                        "name": "知识恶魔",
                        "path": "/monsters/knowledge_demon",
                        "subtitle": "Boss",
                    }
                ],
            },
            {
                "kind": "encounter",
                "items": [
                    {
                        "name": "知识恶魔",
                        "path": "/encounters/knowledge_demon_boss",
                        "subtitle": "Boss",
                    }
                ],
            },
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
            if q == "燃燒之血":
                if lang == "zhs":
                    return httpx.Response(200, json=SEARCH["燃烧之血"])
                return httpx.Response(200, json={"query": q, "categories": []})
            if payload is not None and (
                lang == "zhs" or q in {"Bash", "guide", "mechanics", "燃燒之血"}
            ):
                return httpx.Response(200, json=payload)
            return httpx.Response(200, json={"query": q, "categories": []})
        if path == "/api/changelogs":
            return httpx.Response(200, json=[{"game_version": "1.3.1", "tag": "1.3.1"}])
        if path == "/api/cards":
            items = CARDS
            if params.get("color"):
                items = [item for item in items if item.get("color") == params["color"]]
            if params.get("rarity"):
                items = [
                    item for item in items if item.get("rarity_key") == params["rarity"]
                ]
            if params.get("type"):
                items = [
                    item for item in items if item.get("type_key") == params["type"]
                ]
            return httpx.Response(200, json=items)
        if path.startswith("/api/cards/"):
            key = path.rsplit("/", 1)[-1].upper()
            entity = next((item for item in CARDS if item["id"] == key), None)
            return httpx.Response(
                200 if entity else 404,
                json=entity or {"detail": "Not Found"},
            )
        if path == "/api/relics":
            items = RELICS
            if params.get("pool"):
                items = [item for item in items if item.get("pool") == params["pool"]]
            return httpx.Response(200, json=items)
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
        if path == "/api/afflictions":
            return httpx.Response(200, json=AFFLICTIONS)
        if path == "/api/keywords":
            return httpx.Response(200, json=KEYWORDS)
        if path == "/api/enchantments":
            return httpx.Response(200, json=ENCHANTMENTS)
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
                200,
                json={
                    "INFLAME": {"win_rate": 43.6, "picks": 100, "score": 80},
                    "STRIKE_SILENT": {"win_rate": 52.0, "picks": 900, "score": 60},
                    "STRIKE_IRONCLAD": {"win_rate": 48.0, "picks": 800, "score": 55},
                    "BLUDGEON": {"win_rate": 61.0, "picks": 300, "score": 90},
                },
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
                    "events": [
                        {
                            "id": "ABYSSAL_BATHS",
                            "name": "Abyssal Baths",
                            "total": 1106091,
                            "options": [
                                {"id": "LINGER", "label": "Linger", "pct": 59.5},
                                {
                                    "id": "EXIT_BATHS",
                                    "label": "Exit Baths",
                                    "pct": 14.4,
                                },
                            ],
                        }
                    ],
                    "deaths": {
                        "encounters": [
                            {
                                "id": "KNOWLEDGE_DEMON_BOSS",
                                "name": "Knowledge Demon",
                                "count": 86329,
                                "pct": 5.5,
                            }
                        ]
                    },
                    "ancient_picks": [
                        {
                            "id": "ARCANE_SCROLL",
                            "name": "Arcane Scroll",
                            "pct": 3.3,
                            "take_rate": 56.8,
                        }
                    ],
                    "rest_sites": [
                        {
                            "id": "SMITH",
                            "label": "Smith",
                            "pct": 54.6,
                            "win_rate": 59.4,
                        }
                    ],
                    "most_removed": [{"id": "STRIKE", "name": "Strike", "pct": 51.1}],
                    "reward_skip_rate": 28.5,
                    "map_danger": [
                        {
                            "act": 0,
                            "types": {
                                "boss": {"death_rate": 8.56},
                                "elite": {"death_rate": 4.4},
                            },
                        }
                    ],
                    "survival": [
                        {"floor": 1, "alive_pct": 100.0},
                        {"floor": 10, "alive_pct": 89.7},
                    ],
                    "character_behavior": [
                        {
                            "id": "ironclad",
                            "removes_per_run": 3.21,
                            "rest": {"SMITH": 59.1, "HEAL": 33.3},
                        }
                    ],
                    "hopper_stolen": [{"id": "STRIKE", "name": "Strike", "pct": 1.1}],
                    "ascension_matrix": {
                        "ironclad": {
                            "0": {"win_rate": 24.3},
                            "10": {"win_rate": 20.9},
                        },
                        "silent": {"10": {"win_rate": 22.5, "runs": 100}},
                    },
                    "records": {
                        "fastest_win": {"run_time": 900, "run_hash": "x"},
                        "longest_run": {"run_time": 1958760, "run_hash": "y"},
                        "biggest_deck": {"size": 2224, "run_hash": "z"},
                    },
                    "data_through": "2026-10-30",
                },
            )
        if path == "/api/ascensions":
            return httpx.Response(200, json=ASCENSIONS)
        if path == "/api/epochs":
            return httpx.Response(200, json=EPOCHS)
        if path == "/api/stories":
            return httpx.Response(200, json=STORIES)
        if path == "/api/merchant/config":
            return httpx.Response(200, json=MERCHANT_CONFIG)
        if path == "/api/ancient-pools":
            return httpx.Response(200, json=ANCIENT_POOLS)
        if path == "/api/acts":
            return httpx.Response(200, json=ACTS)
        if path == "/api/achievements":
            return httpx.Response(200, json=ACHIEVEMENTS)
        if path == "/api/unlocks":
            return httpx.Response(200, json=UNLOCKS)
        if path == "/api/monsters":
            return httpx.Response(200, json=MONSTERS)
        if path.startswith("/api/monsters/"):
            key = path.rsplit("/", 1)[-1].upper()
            entity = next((item for item in MONSTERS if item["id"] == key), None)
            return httpx.Response(
                200 if entity else 404,
                json=entity or {"detail": "Not Found"},
            )
        if path == "/api/encounters":
            return httpx.Response(200, json=ENCOUNTERS)
        if path == "/api/events":
            return httpx.Response(200, json=EVENTS)
        if path == "/api/events/abyssal_baths":
            return httpx.Response(200, json=EVENTS[0])
        if path == "/api/guides":
            return httpx.Response(200, json=GUIDES)
        if path == "/api/guides/boss-guide":
            return httpx.Response(200, json=GUIDES[0])
        if path == "/api/mechanics/sections":
            return httpx.Response(200, json=MECHANICS)
        if path == "/api/mechanics/sections/combat-mechanics":
            return httpx.Response(200, json=MECHANICS[0])
        if path == "/api/mechanics/sections/card-rarity":
            return httpx.Response(200, json=CARD_RARITY_MECHANIC)
        if path == "/api/mechanics/sections/score-formula":
            return httpx.Response(200, json=SCORE_MECHANIC)
        if path == "/api/mechanics/sections/unknown-rooms":
            return httpx.Response(200, json=UNKNOWN_ROOMS_MECHANIC)
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
        == "一大群史莱姆 · 遭遇 · 普通战斗"
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


def test_event_choice_shows_community_share(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("深渊浴场", "选哪个")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "社区选择" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "沉溺：59.5%" in text
    assert "离开浴场：14.4%" in text
    assert "仅供参考" in text


def test_story_epoch_and_merchant_meta(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            story_list = await service.search("剧情", "")
            story = await service.search("静默猎手剧情", "")
            epoch = await service.search("迷雾压境 纪元", "")
            merchant = await service.search("商店价格", "")
            return story_list, story, epoch, merchant
        finally:
            await client.close()

    story_list, story, epoch, merchant = asyncio.run(run())
    assert story_list["status"] == "ok"
    assert "故事线" in story_list["available_sections"]
    assert "静默猎手" in "\n".join(item["text"] for item in story_list["evidence"])
    assert story["status"] == "ok"
    assert story["title"] == "静默猎手"
    assert "迷雾压境" in "\n".join(item["text"] for item in story["evidence"])
    assert epoch["status"] == "ok"
    assert epoch["title"] == "迷雾压境"
    assert "门扉" in "\n".join(item["text"] for item in epoch["evidence"])
    assert merchant["status"] == "ok"
    text = "\n".join(item["text"] for item in merchant["evidence"])
    assert "75" in text and "100" in text


def test_community_meta_queries(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            deaths = await service.search("哪些BOSS最容易死", "")
            rest = await service.search("篝火选什么", "")
            removed = await service.search("删什么牌", "")
            ancient = await service.search("先古祝福怎么选", "")
            skip = await service.search("跳过奖励", "")
            return deaths, rest, removed, ancient, skip
        finally:
            await client.close()

    deaths, rest, removed, ancient, skip = asyncio.run(run())
    assert deaths["status"] == "ok"
    assert "致命遭遇" in deaths["available_sections"]
    assert "Knowledge Demon" in "\n".join(item["text"] for item in deaths["evidence"])
    assert rest["status"] == "ok" and "篝火选择" in rest["available_sections"]
    assert "锻造" in "\n".join(item["text"] for item in rest["evidence"])
    assert removed["status"] == "ok" and "最常删除" in removed["available_sections"]
    assert "打击" in "\n".join(item["text"] for item in removed["evidence"])
    assert ancient["status"] == "ok" and "先古选取" in ancient["available_sections"]
    assert "Arcane Scroll" in "\n".join(item["text"] for item in ancient["evidence"])
    assert skip["status"] == "ok" and "28.5" in "\n".join(
        item["text"] for item in skip["evidence"]
    )


def test_qualified_same_name_card_is_disambiguated(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("打击（铁甲战士）", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "打击"


def test_compare_qualified_same_name_cards(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.compare("打击（铁甲战士）", "防御（铁甲战士）")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "compare"
    assert result["kind"] == "card"


def test_cross_kind_compare_includes_summaries(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.compare("燃烧之血", "重击")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "compare_unsupported"
    assert result["left"]["summary"]
    assert result["right"]["summary"]
    text = format_compare(result)
    assert "回复6点生命" in text and "造成6点伤害" in text


def test_ancient_list_meta(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("先古之民有哪些", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "先古之民"
    assert "先古列表" in result["available_sections"]
    assert "Darv" in "\n".join(item["text"] for item in result["evidence"])


def test_traditional_chinese_falls_back_to_zht(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("燃燒之血", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "燃烧之血"


def test_mixed_language_query_splits_trailing_aspect(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("Bash 效果", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "重击"


def test_extra_community_stats_queries(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            records = await service.search("最快通关记录", "")
            survival = await service.search("第几层存活率", "")
            mapping = await service.search("地图危险", "")
            hopper = await service.search("谁最常被偷", "")
            behavior = await service.search("角色行为", "")
            matrix = await service.search("进阶矩阵", "")
            return records, survival, mapping, hopper, behavior, matrix
        finally:
            await client.close()

    records, survival, mapping, hopper, behavior, matrix = asyncio.run(run())
    assert records["status"] == "ok" and "极限记录" in records["available_sections"]
    assert "15分" in "\n".join(item["text"] for item in records["evidence"])
    assert survival["status"] == "ok" and "生存曲线" in survival["available_sections"]
    assert mapping["status"] == "ok" and "地图危险" in mapping["available_sections"]
    assert "8.56%" in "\n".join(item["text"] for item in mapping["evidence"])
    assert hopper["status"] == "ok" and "被偷卡牌" in hopper["available_sections"]
    assert behavior["status"] == "ok" and "角色行为" in behavior["available_sections"]
    assert matrix["status"] == "ok" and "进阶矩阵" in matrix["available_sections"]
    assert "A10 20.9%" in "\n".join(item["text"] for item in matrix["evidence"])


def test_character_story_and_ascension_winrate(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            story = await service.search("静默猎手", "剧情")
            ascension = await service.search("静默猎手", "A10胜率")
            return story, ascension
        finally:
            await client.close()

    story, ascension = asyncio.run(run())
    assert story["status"] == "ok"
    assert "故事线" in story["available_sections"]
    assert ascension["status"] == "ok"
    assert "进阶胜率" in ascension["available_sections"]
    assert "22.5%" in "\n".join(item["text"] for item in ascension["evidence"])


def test_act_normal_encounters_and_merchant(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            act = await service.search("第一章", "有哪些普通怪")
            merchant = await service.search("商店", "买什么")
            return act, merchant
        finally:
            await client.close()

    act, merchant = asyncio.run(run())
    assert act["status"] == "ok"
    assert "普通遭遇" in act["available_sections"]
    assert "一大群史莱姆" in "\n".join(item["text"] for item in act["evidence"])
    assert merchant["status"] == "ok"
    assert "删牌服务" in merchant["available_sections"]


def test_unlock_overview_and_exact_achievement(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            unlock = await service.search("遗物", "怎么解锁")
            achievement = await service.search("完美牌组", "怎么完成")
            return unlock, achievement
        finally:
            await client.close()

    unlock, achievement = asyncio.run(run())
    assert unlock["status"] == "ok"
    assert "解锁列表" in unlock["available_sections"]
    assert "红头骨" in "\n".join(item["text"] for item in unlock["evidence"])
    assert achievement["status"] == "ok"
    assert achievement["title"] == "完美牌组"
    assert "条件" in achievement["available_sections"]


def test_relic_suitability_uses_community_sections(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("燃烧之血", "适合铁甲战士吗")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "胜率" in result["available_sections"]


def test_relic_pool_list_query(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("铁甲战士遗物池", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["url"] == f"{BASE}/zhs/relics"
    assert "遗物列表" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "燃烧之血" in text and "红头骨" in text
    assert "蛇之环" not in text


def test_relic_pool_list_scoped_by_character(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("静默猎手", "遗物池")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "静默猎手遗物池"
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "蛇之环" in text and "燃烧之血" not in text


def test_card_filter_list_query(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("铁甲战士所有稀有攻击牌", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "卡牌列表" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "重砍" in text
    assert "防御" not in text and "打击" not in text


def test_ranked_card_list_query(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("静默猎手卡牌胜率", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "静默猎手卡牌胜率排行"
    assert "胜率排行" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "打击：胜率 52%" in text
    assert "社区统计，仅供参考" in text


def test_generic_tier_query_ranks_cards_with_character_tags(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("当前版本Tier", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["url"] == f"{BASE}/zhs/stats/cards"
    assert "胜率排行" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    # 重砍 61% 排第一；五张“打击”必须带角色标签才能区分。
    assert text.index("重砍") < text.index("打击（铁甲战士）")
    assert "打击（静默猎手）" in text
    assert "社区统计，仅供参考" in text


def test_character_rank_list_query(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("角色胜率排行", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["url"] == f"{BASE}/zhs/stats"
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "铁甲战士：胜率 27.3%" in text
    assert "仅供参考" in text


def test_list_page_id_resolves_after_restart(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            search = await service.search("铁甲战士遗物池", "")
            page_id = search["page_id"]
            service._known.clear()
            return await service.read(page_id, "遗物列表")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "遗物列表" in result["available_sections"]
    assert "燃烧之血" in "\n".join(item["text"] for item in result["evidence"])


def test_card_list_question_keeps_entity_flow(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            removed = await service.search("删什么牌", "")
            deck = await service.search("铁甲战士", "初始卡组")
            return removed, deck
        finally:
            await client.close()

    removed, deck = asyncio.run(run())
    assert "最常删除" in removed["available_sections"]
    assert "初始卡组" in deck["available_sections"]


def test_monster_tactics_question_prefers_monster(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("知识恶魔", "怎么打")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "招式" in result["available_sections"]
    assert "打法要点" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "最高伤害招式：抽打（伤害 17×2，进阶 18）。" in text
    assert "首回合使用：知识的诅咒。" in text
    assert "开局带有：力量 3。" in text


def test_act_boss_tactics_section(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("第一章", "Boss怎么应对")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "BOSS应对" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "扭动虫" in text and "撕咬" in text


def test_card_acquisition_uses_mechanics(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("卡牌怎么获得", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "正文" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "60%" in text


def test_ascension_unlock_rules(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("进阶怎么解锁", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert "解锁规则" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "第三章" in text and "角色独立" in text
    assert result["url"] == f"{BASE}/zhs/unlocks"


def test_list_key_round_trip_and_intent_guards():
    specs = [
        {
            "mode": "list",
            "kind": "card",
            "color": "ironclad",
            "rarity": "Rare",
            "type": "Attack",
        },
        {"mode": "list", "kind": "relic", "color": "silent", "rarity": "", "type": ""},
        {"mode": "list", "kind": "potion", "color": "", "rarity": "", "type": ""},
        {"mode": "list", "kind": "affliction", "color": "", "rarity": "", "type": ""},
        {"mode": "list", "kind": "event", "color": "", "rarity": "", "type": ""},
        {"mode": "rank", "kind": "card", "color": "", "rarity": "", "type": ""},
        {"mode": "rank", "kind": "character", "color": "", "rarity": "", "type": ""},
        {
            "mode": "note",
            "kind": "relic",
            "color": "",
            "rarity": "",
            "type": "",
            "topic": "boss",
        },
    ]
    for spec in specs:
        key = SpireCodexService._list_key(spec)
        parsed = SpireCodexService._parse_list_key(key)
        assert parsed == spec, key
        assert key in SpireCodexService._list_keys()
    assert SpireCodexService._list_intent("静默猎手卡牌胜率", "") == {
        "mode": "rank",
        "kind": "card",
        "color": "silent",
    }
    # 这张牌胜率 / 删牌 / 卡组类问法不走列表。
    assert SpireCodexService._list_intent("燃烧这张牌胜率多少", "") is None
    assert SpireCodexService._list_intent("删什么牌", "") is None
    assert SpireCodexService._list_intent("铁甲战士", "初始卡组") is None
    assert SpireCodexService._list_intent("遗物", "怎么解锁") is None
    assert SpireCodexService._list_intent("卡牌稀有度概率", "") is None
    assert SpireCodexService._list_intent("静默猎手", "A10胜率") is None
    # 裸“胜率排行”保留攻略路径；带限定词才走社区排行。
    assert SpireCodexService._list_intent("胜率排行", "") is None
    assert SpireCodexService._list_intent("卡牌胜率排行", "") == {
        "mode": "rank",
        "kind": "card",
        "color": "",
    }
    assert SpireCodexService._list_intent("角色胜率排行", "") == {
        "mode": "rank",
        "kind": "character",
        "color": "",
    }


def test_score_and_daily_questions_reach_mechanics(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            score = await service.search("分数怎么算", "")
            daily = await service.search("每日挑战", "")
            return score, daily
        finally:
            await client.close()

    score, daily = asyncio.run(run())
    assert score["status"] == "ok"
    assert score["url"].endswith("/zhs/mechanics/score-formula")
    assert "正文" in score["available_sections"]
    assert daily["status"] == "ok"
    assert daily["url"].endswith("/zhs/mechanics/score-formula")


def test_unknown_room_question_reaches_mechanics(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("问号房有什么", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["url"].endswith("/zhs/mechanics/unknown-rooms")
    assert "正文" in result["available_sections"]


def test_reference_kind_list_queries(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            afflictions = await service.search("苦痛有哪些", "")
            orbs = await service.search("充能球有哪些", "")
            events = await service.search("事件有哪些", "")
            return afflictions, orbs, events
        finally:
            await client.close()

    afflictions, orbs, events = asyncio.run(run())
    assert afflictions["status"] == "ok"
    assert "苦痛列表" in afflictions["available_sections"]
    text = "\n".join(item["text"] for item in afflictions["evidence"])
    assert "进阶之灾" in text
    assert orbs["status"] == "ok" and "充能球列表" in orbs["available_sections"]
    assert "黑暗" in "\n".join(item["text"] for item in orbs["evidence"])
    assert events["status"] == "ok" and "事件列表" in events["available_sections"]
    assert "深渊浴场" in "\n".join(item["text"] for item in events["evidence"])
    assert events["url"] == f"{BASE}/zhs/events"


def test_definition_suffix_is_stripped(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("诅咒是什么", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    # “诅咒是什么”剥后缀后等价于裸“诅咒”：给苦痛候选而不是 not_found。
    assert result["status"] == "needs_choice"
    titles = [item["title"] for item in result["candidates"]]
    assert any("进阶之灾" in title or "疑虑" in title for title in titles)


def test_boss_relic_note_instead_of_full_list(tmp_path):
    service, client, _ = make_service(tmp_path)

    async def run():
        try:
            return await service.search("BOSS遗物有哪些", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "遗物分类说明"
    assert "稀有度分布" in result["available_sections"]
    text = "\n".join(item["text"] for item in result["evidence"])
    assert "不设 Boss 分类" in text
    assert "初始遗物：2 个" in text


class TipsChinese:
    """中文源替身：附魔问题返回 STS2FRONT tips 攻略，其余为空。"""

    async def guide(self, query, question="", character=""):
        if "附魔" in query:
            return {
                "key": "cn:guide:sts2front:tips:enchantments",
                "title": "附魔怎么选",
                "text": "附魔是长期成长系统，优先强化核心牌。",
                "url": "https://sts2front.com/zh-cn/tips/enchantments/",
            }
        return None

    async def mechanics(self, text):
        return None

    async def read(self, key):
        return {
            "id": key,
            "title": "附魔怎么选",
            "content": "附魔是长期成长系统，优先强化核心牌。",
            "url": "https://sts2front.com/zh-cn/tips/enchantments/",
        }

    @staticmethod
    def url(key):
        return "https://sts2front.com/zh-cn/tips/enchantments/"


def test_enchant_question_prefers_chinese_guide_over_noise(tmp_path):
    service, client, _ = make_service(tmp_path)
    service.chinese = TipsChinese()

    async def run():
        try:
            return await service.search("附魔怎么选", "")
        finally:
            await client.close()

    result = asyncio.run(run())
    assert result["status"] == "ok"
    assert result["title"] == "附魔怎么选"
    assert result["source"] == "杀戮尖塔2 STS2FRONT"
    assert "正文" in result["available_sections"]
    assert "核心牌" in "\n".join(item["text"] for item in result["evidence"])
