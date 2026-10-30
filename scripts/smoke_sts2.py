"""Read-only live Spire Codex checks: python scripts/smoke_sts2.py."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki.cache import Cache  # noqa: E402
from wiki.chineseguides import ChineseGuideService  # noqa: E402
from wiki.spirecodex import SpireCodexClient, SpireCodexService  # noqa: E402

# Structural expectations, not exact values: Spire Codex updates with the
# game's early-access patches. A failure means the site shape changed or a
# query stopped reaching its intended section.
CASES = (
    ("燃烧之血", "效果", "效果"),
    ("打击", "", None),
    ("树叶史莱姆（中）", "招式", "招式"),
    ("水晶球", "选项", "选项"),
    ("铁甲战士", "初始卡组", "初始卡组"),
    ("扭动虫", "出招顺序", "出招顺序"),
    ("深渊浴场", "其他选项", "分支"),
    ("格挡", "", "效果"),
    ("黑暗", "", "效果"),
    ("燃烧", "搭配", "搭配"),
    ("燃烧", "胜率", "胜率"),
    ("攻略", "", "正文"),
    ("机制", "", "正文"),
    ("伤害怎么计算", "", "正文"),
    ("静默猎手", "攻略", "攻略"),
)
COMPARE_CASES = (("燃烧", "痛击"), ("燃烧之血", "红头骨"))


async def main():
    records, failed = [], False
    with tempfile.TemporaryDirectory() as directory:
        cache = Cache(Path(directory))
        client = SpireCodexClient(cache, timeout=20)
        chinese = ChineseGuideService(cache, timeout=20)
        service = SpireCodexService(client, timeout=40, chinese=chinese)
        try:
            for name, question, expected in CASES:
                try:
                    result = await service.search(name, question)
                    if result.get("status") == "needs_choice":
                        result = await service.read(
                            result["candidates"][0]["page_id"], question
                        )
                    sections = result.get("available_sections") or []
                    evidence = "\n".join(
                        item.get("text", "") for item in result.get("evidence", [])
                    )
                    ok = result.get("status") == "ok" and (
                        expected is None or expected in sections or expected in evidence
                    )
                    if not ok:
                        failed = True
                    records.append(
                        {
                            "query": name,
                            "question": question,
                            "status": result.get("status"),
                            "title": result.get("title"),
                            "sections": sections,
                            "ok": ok,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - smoke reports any failure
                    failed = True
                    records.append(
                        {
                            "query": name,
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
                    if not ok:
                        failed = True
                    records.append(
                        {
                            "query": f"{left} vs {right}",
                            "status": result.get("status"),
                            "dimensions": len(result.get("dimensions") or []),
                            "ok": ok,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    failed = True
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
    output = Path("research/sts2-smoke.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(records, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
