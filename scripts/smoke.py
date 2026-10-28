"""Read-only live BWIKI checks: python scripts/smoke.py."""

import asyncio
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki.cache import Cache  # noqa: E402
from wiki.client import WikiClient  # noqa: E402
from wiki.query import QueryService  # noqa: E402

# Structural patterns, not exact numbers: BWIKI editors legitimately rebalance
# values. If a pattern fails, first confirm on the live page whether the site
# changed, then update the pattern here.
PATTERNS = {
    "material_total": r"劫波莲\s*×\s*\d+",
    "skill_percent": r"点按伤害\s*\|\s*[\d.]+%",
}


async def main():
    records = []
    with tempfile.TemporaryDirectory() as directory:
        client = WikiClient(Cache(Path(directory)))
        service = QueryService(client)
        try:
            cases = [
                ("草神", "突破材料总量"),
                ("纳西妲", "元素战技10级倍率"),
                ("日月前事", "这本书讲了什么"),
                ("纳西妲", "七圣召唤卡牌技能"),
                ("原神知识不存在测试词", ""),
            ]
            for query, question in cases:
                # The WAF intermittently answers 5xx; retry like the audit.
                result = None
                for attempt in range(3):
                    start = time.perf_counter()
                    try:
                        result = await service.search(query, question)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        if attempt < 2:
                            await asyncio.sleep(8)
                assert result is not None, (query, last_error)
                result = result
                records.append(
                    {
                        "query": query,
                        "question": question,
                        "seconds": round(time.perf_counter() - start, 4),
                        "result": result,
                    }
                )
                assert result["status"] in {"ok", "not_found"}, result
            assert records[0]["result"]["title"] == "纳西妲"
            assert re.search(
                PATTERNS["material_total"], str(records[0]["result"]["evidence"])
            ), "material total row with a quantity is expected"
            skill = records[1]["result"]
            assert "元素战技" in skill["evidence"][0]["section"], (
                "the second talent must still be labeled 元素战技"
            )
            assert "所闻遍计" in skill["evidence"][0]["section"]
            assert re.search(PATTERNS["skill_percent"], skill["evidence"][0]["text"]), (
                "a tap-damage percentage row is expected"
            )
            assert skill["selection"]["mode"] == "focused"
            assert records[2]["result"]["display_title"] == "日月前事"
            assert records[2]["result"]["title"] == "白夜国馆藏"
            assert all(
                "日月前事" in e["section"] for e in records[2]["result"]["evidence"]
            )
            from wiki.formatter import format_command

            excerpt = format_command(records[2]["result"])
            assert not any(
                noise in excerpt
                for noise in (
                    "NewPP",
                    "Cached time",
                    "Ctrl+D",
                    "[[]]",
                    ".png",
                    "本条目介绍",
                )
            )
            (
                Path(__file__).resolve().parents[1] / "research/command-preview.txt"
            ).write_text(excerpt, encoding="utf-8")
            assert records[3]["result"]["title"] == "卡牌：纳西妲"
            assert records[4]["result"]["status"] == "not_found"
            cold = client.stats()["upstream_requests"]
            warm = []
            for _ in range(5):
                start = time.perf_counter()
                await service.search("草神", "突破材料总量")
                warm.append(time.perf_counter() - start)
            assert client.stats()["upstream_requests"] == cold, (
                "warm cache unexpectedly called upstream"
            )
        finally:
            stats = client.stats()
            await client.close()
    report = {
        "cases": [{k: v for k, v in r.items() if k != "result"} for r in records],
        "upstream_requests": stats["upstream_requests"],
        "cache_hits": stats["cache_hits"],
        "coalesced": stats["coalesced"],
        "errors": stats["errors"],
        "warm_median_ms": round(statistics.median(warm) * 1000, 2),
        "warm_max_ms": round(max(warm) * 1000, 2),
    }
    destination = Path(__file__).resolve().parents[1] / "research" / "live-smoke.json"
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False
        )
    )
    for case, record in zip(
        [
            "material",
            "skill",
            "book",
            "card",
            "not_found",
        ],
        records,
    ):
        print(
            case,
            record["result"]["status"],
            record["result"].get("title"),
            record["seconds"],
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
