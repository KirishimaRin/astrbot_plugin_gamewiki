"""Read-only live BWIKI Wuthering Waves checks: python scripts/smoke_ww.py."""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki.cache import Cache  # noqa: E402
from wiki.client import WikiClient  # noqa: E402
from wiki.games import PROFILES  # noqa: E402
from wiki.query import QueryService  # noqa: E402

# Structural expectations against the BWIKI wutheringwaves site: sections are
# editor-maintained, so a failure means the page shape moved or the query no
# longer reaches its intended section. (query, question, expected)
# expected 匹配 available_sections 或 evidence 文本；None 只要求命中条目。
CASES = (
    ("今汐", "", None),
    ("今汐", "90级基础属性", "基础属性"),
    ("今汐", "共鸣链1效果", "共鸣链"),
    ("今汐", "大招倍率", "技能详情"),
    ("今汐", "语音", "语音"),
    ("卡卡罗", "档案", "档案"),
    ("苍鳞千嶂", "突破材料", None),
    ("彻空冥雷", "2件套效果", "2件套效果"),
    ("呼咻咻", "声骸技能", None),
    ("无妄者", "", None),
    ("鸣潮知识不存在测试词", "", None),
)


async def main():
    records, failed = [], False
    with tempfile.TemporaryDirectory() as directory:
        client = WikiClient(Cache(Path(directory)), game="ww", source="bwiki")
        service = QueryService(client, profile=PROFILES["ww"])
        try:
            for query, question, expected in CASES:
                result = None
                for attempt in range(3):
                    start = time.perf_counter()
                    try:
                        result = await service.search(query, question)
                        break
                    except Exception as exc:  # noqa: BLE001 - smoke reports failures
                        last = f"{type(exc).__name__}: {exc}"
                        if attempt < 2:
                            await asyncio.sleep(2)
                if result is None:
                    failed = True
                    records.append(
                        {
                            "query": query,
                            "question": question,
                            "error": last,
                            "ok": False,
                        }
                    )
                    continue
                status = result.get("status")
                if status == "needs_choice":
                    # 无妄者同时命中 敌人/无妄者 与 声骸/无妄者：同名候选
                    # 是预期行为；不存在的测试词也是预期 not_found。
                    ok = ("无妄者" == query) or ("不存在" in query)
                    if not ok and result.get("candidates"):
                        # 允许兜底选择第一个候选后校验预期。
                        result = await service.read(
                            result["candidates"][0]["page_id"], question
                        )
                        status = result.get("status")
                sections = result.get("available_sections") or []
                evidence = "\n".join(
                    item.get("text", "") for item in result.get("evidence", [])
                )
                if "不存在" in query:
                    ok = status == "not_found"
                elif expected:
                    ok = status == "ok" and (
                        expected in sections or expected in evidence
                    )
                else:
                    ok = status == "ok"
                if not ok:
                    failed = True
                records.append(
                    {
                        "query": query,
                        "question": question,
                        "status": status,
                        "title": result.get("title"),
                        "sections": sections,
                        "seconds": round(time.perf_counter() - start, 2),
                        "ok": ok,
                    }
                )
        finally:
            await client.close()
    output = Path("research/ww-smoke.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(records, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
