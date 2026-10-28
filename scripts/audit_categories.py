"""Read-only category audit with assertions on evidence and final output.

Covers every enabled game profile. Assertions are structural: they check that
a row/section of the right shape exists, not specific game values. When a
BWIKI rebalances numbers this audit stays green; when the site changes
structure or templates it fails, and the CASES table below is the single
place to review and update. BWIKI's WAF intermittently answers 5xx, so each
case is retried with pacing.
"""

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki.cache import Cache  # noqa: E402
from wiki.client import WikiClient  # noqa: E402
from wiki.models import WikiError  # noqa: E402
from wiki.games import PROFILES  # noqa: E402
from wiki.query import QueryService, format_command  # noqa: E402

# (game, query, question, required literals, forbidden literals, patterns)
CASES = [
    ("ys", "钟离", "", ["往生堂"], ["角色故事", "推荐说明"], []),
    ("ys", "护摩之杖", "", ["生命值提升"], ["祈愿 -", "推荐说明"], []),
    ("ys", "劫波莲", "", ["攀援植物"], ["同类素材", "配方介绍"], []),
    ("ys", "翠绿之影", "", ["2件套", "4件套"], ["圣遗物故事", "推荐角色"], []),
    ("ys", "若陀龙王", "", ["古老巨龙"], ["进入战斗", "清算一切"], []),
    ("ys", "安提戈努斯", "", ["寻找", "渊下宫"], ["派蒙："], []),
    ("ys", "提瓦特游览指南", "", ["卷数"], ["达达乌帕谷"], []),
    (
        "ys",
        "护摩之杖",
        "90级属性",
        ["90级"],
        ["20级", "推荐角色"],
        [r"\d{3,4}(\.\d+)?"],
    ),
    ("ys", "护摩之杖", "获取方式", ["限定祈愿"], ["推荐说明"], []),
    ("ys", "劫波莲", "获取方式", ["野外采集"], ["同类素材", "生论派"], []),
    ("ys", "翠绿之影", "获取方式", ["铭记之谷"], ["推荐角色", "野花"], []),
    (
        "ys",
        "纳西妲",
        "元素战技10级倍率",
        ["LV10", "元素战技"],
        ["LV1 |"],
        # The formatter renders single-pipe rows as "键：值"; evidence keeps "|".
        [r"点按伤害\s*[|：]\s*[\d.]+%"],
    ),
    ("ys", "日月前事", "", ["编年史"], ["任务道具", "获取方式"], []),
    ("sr", "流萤", "晋阶材料", ["角色晋阶材料", "信用点"], [], []),
    # The cleaned intro describes rarity via "5星光锥", not the removed filter label.
    ("sr", "光锥图鉴", "", ["光锥"], ["CardSelectTr"], [r"[345]星光锥"]),
    ("zzz", "艾莲", "晋阶材料", ["角色晋阶材料"], [], []),
    # Verify actual catalog entries; rarity filter controls are intentionally removed.
    ("zzz", "音擎图鉴", "", ["音擎", "拘缚者"], ["CardSelectTr", "文件:武器立绘"], []),
    ("arknights", "能天使", "精英化", ["精英化"], [], []),
    ("arknights", "术师芯片", "获取方式", ["掉落", "PR-B-1"], [], []),
    ("zmd", "武器图鉴", "", ["武器名称", "稀有度"], ["CardSelectTr"], []),
    # 祀 has no zmd page; the only content match is 骏卫 (via 雪祀). The reply
    # must ask for confirmation instead of answering with the wrong entity.
    ("zmd", "祀", "", ["没有与「祀」同名", "骏卫"], [], [], "needs_choice"),
    # 三月七 is a redirect page; the parse API must resolve it to the target.
    ("sr", "三月七", "", ["三月七•存护", "稀有度"], [], []),
]
NOISE = [
    "NewPP",
    "Cached time",
    "Serialized with PHP",
    "Ctrl+D",
    "{{{",
    "[[文件:",
    "markType",
    "[[]]",
]


TRANSIENT = {"timeout", "upstream", "rate_limited", "busy", "too_large"}


async def run_case(service, query, question):
    """Retry only transient upstream failures; deterministic errors fail fast."""
    last = None
    for attempt in range(3):
        try:
            return await service.search(query, question or query), None
        except WikiError as exc:
            if exc.code not in TRANSIENT:
                return None, exc
            last = exc
            if attempt < 2:
                await asyncio.sleep(8 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001 - audit reports any failure
            last = exc
            if attempt < 2:
                await asyncio.sleep(8)
    return None, last


async def main():
    records = []
    games = sorted({case[0] for case in CASES})
    with tempfile.TemporaryDirectory() as directory:
        clients = {
            game: WikiClient(Cache(Path(directory)), game=game) for game in games
        }
        services = {
            game: QueryService(client, profile=PROFILES[game])
            for game, client in clients.items()
        }
        try:
            for case in CASES:
                game, query, question, required, forbidden, patterns = case[:6]
                expected_status = case[6] if len(case) > 6 else "ok"
                await asyncio.sleep(3)
                result, error = await run_case(services[game], query, question)
                if error is not None:
                    raise AssertionError(
                        f"{game} {query}: upstream kept failing: {error}"
                    )
                output = format_command(result)
                all_text = output + str(result.get("evidence", []))
                assert result["status"] == expected_status, (
                    game,
                    query,
                    result,
                )
                for word in required:
                    assert word in output, (game, query, question, "missing", word)
                for word in forbidden:
                    assert word not in output, (
                        game,
                        query,
                        question,
                        "unrelated",
                        word,
                    )
                for pattern in patterns:
                    assert re.search(pattern, output), (
                        game,
                        query,
                        question,
                        "pattern missing",
                        pattern,
                    )
                for word in NOISE:
                    assert word not in all_text, (game, query, question, "noise", word)
                assert len(output) <= 1200
                records.append(
                    {
                        "game": game,
                        "query": query,
                        "question": question,
                        "output": output,
                    }
                )
                print(f"PASS {game} {query} {question}", flush=True)
        finally:
            stats = {g: c.stats() for g, c in clients.items()}
            for client in clients.values():
                await client.close()
    target = Path(__file__).resolve().parents[1] / "research/category-audit.json"
    target.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(stats, ensure_ascii=False))
    print(f"{len(records)} cases passed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
