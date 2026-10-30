"""Read-only STS2 user-question coverage audit.

Runs representative Chinese questions against the live Spire Codex / Chinese
editorial sources and reports whether each reaches a useful status/section.
Default is diagnostic (exit 0); pass --strict to fail below the threshold.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki.cache import Cache  # noqa: E402
from wiki.chineseguides import ChineseGuideService  # noqa: E402
from wiki.spirecodex import SpireCodexClient, SpireCodexService  # noqa: E402

# (query, question, expected section/text in the result or candidates)
SEARCH_CASES = (
    ("燃烧之血", "效果", "效果"),
    ("打击", "", "打击"),
    ("铁甲战士", "初始卡组", "初始卡组"),
    ("树叶史莱姆（中）", "招式", "招式"),
    ("水晶球", "选项", "选项"),
    ("格挡", "", "效果"),
    ("黑暗", "", "效果"),
    ("魂缚", "", "效果"),
    ("锋利", "", "效果"),
    ("燃烧", "搭配", "搭配"),
    ("燃烧", "胜率", "胜率"),
    ("攻略", "", "正文"),
    ("机制", "", "正文"),
    ("伤害怎么计算", "", "正文"),
    ("易伤倍率", "", "效果"),
    ("商店价格", "", "删牌服务"),
    ("卡牌稀有度概率", "", "机制"),
    ("补丁更新", "", "攻略"),
    ("胜率排行", "", "攻略"),
    ("静默猎手", "攻略", "攻略"),
    ("铁甲战士", "攻略", "攻略"),
    ("进阶10", "", "社区胜率"),
    ("A10", "", "社区胜率"),
    ("成就", "", "成就列表"),
    ("怎么解锁静默猎手", "", "解锁条件"),
    ("第一章有什么精英", "", "精英"),
    ("剧情", "", "故事线"),
    ("静默猎手剧情", "", "故事线"),
    ("迷雾压境 纪元", "", "故事"),
    ("先古祝福怎么选", "", "先古选取"),
    ("哪些BOSS最容易死", "", "致命遭遇"),
    ("篝火选什么", "", "篝火选择"),
    ("删什么牌", "", "最常删除"),
    ("跳过奖励", "", "奖励跳过率"),
    ("深渊浴场", "选哪个", "社区选择"),
    ("先古之民有哪些", "", "先古列表"),
    ("燃燒之血", "", "效果"),
    ("Bash 效果", "", "效果"),
)
COMPARE_CASES = (
    ("燃烧", "痛击"),
    ("燃烧之血", "红头骨"),
    ("打击（铁甲战士）", "防御（铁甲战士）"),
)


async def main(strict=False, threshold=0.8):
    records, passed = [], 0
    with tempfile.TemporaryDirectory() as directory:
        cache = Cache(Path(directory))
        client = SpireCodexClient(cache, timeout=20)
        chinese = ChineseGuideService(cache, timeout=30)
        service = SpireCodexService(client, timeout=45, chinese=chinese)
        try:
            for query, question, expected in SEARCH_CASES:
                try:
                    result = await service.search(query, question)
                    status = result.get("status", "")
                    sections = result.get("available_sections") or []
                    text = "\n".join(
                        item.get("text", "") for item in result.get("evidence", [])
                    )
                    candidates = "\n".join(
                        item.get("title", "") for item in result.get("candidates", [])
                    )
                    ok = status in {"ok", "needs_choice"} and expected in (
                        "\n".join(sections) + "\n" + text + "\n" + candidates
                    )
                    passed += int(ok)
                    records.append(
                        {
                            "query": query,
                            "question": question,
                            "status": status,
                            "expected": expected,
                            "ok": ok,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    records.append(
                        {
                            "query": query,
                            "question": question,
                            "error": f"{type(exc).__name__}: {exc}",
                            "ok": False,
                        }
                    )
            for left, right in COMPARE_CASES:
                try:
                    result = await service.compare(left, right)
                    ok = result.get("status") == "compare" and bool(
                        result.get("dimensions")
                    )
                    passed += int(ok)
                    records.append(
                        {
                            "query": f"{left} vs {right}",
                            "status": result.get("status"),
                            "dimensions": len(result.get("dimensions") or []),
                            "ok": ok,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    records.append(
                        {
                            "query": f"{left} vs {right}",
                            "error": f"{type(exc).__name__}: {exc}",
                            "ok": False,
                        }
                    )
        finally:
            await client.close()
            await chinese.close()

    total = len(records)
    rate = passed / total if total else 0.0
    output = Path("research/sts2-coverage.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"STS2 coverage: {passed}/{total} ({rate:.0%})")
    for record in records:
        if not record["ok"]:
            print("FAIL", json.dumps(record, ensure_ascii=False))
    if strict and rate < threshold:
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.strict, args.threshold)))
