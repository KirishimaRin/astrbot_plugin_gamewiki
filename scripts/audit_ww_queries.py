"""Read-only Wuthering Waves user-question coverage audit.

Runs representative player questions against the live 库街区 official wiki
(KuroBBS, primary) with BWIKI wutheringwaves as the pinned fallback, and
reports whether each reaches a useful status/section. Default is diagnostic
(exit 0); pass --strict to fail below the threshold.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki.cache import Cache  # noqa: E402
from wiki.client import WikiClient  # noqa: E402
from wiki.games import PROFILES  # noqa: E402
from wiki.kurobbs import KuroBbsClient, KuroBbsService  # noqa: E402
from wiki.query import QueryService  # noqa: E402
from wiki.sources import WuwaSources  # noqa: E402

# Reuse parsed pages across runs: cold fetches occasionally trip the BWIKI
# WAF, which reads as a false coverage failure. Lives in gitignored research/.
CACHE_DIR = Path(__file__).resolve().parents[1] / "research" / "ww-cache"

# 从玩家会去 wiki 搜的角度枚举（角色/武器/声骸/敌人/道具/卡池/黑话）。
# expected 是结果 sections/evidence/candidates 里应出现的片段。
SEARCH_CASES = (
    # —— 角色 ——
    ("今汐", "", "今汐"),
    ("卡卡罗", "", "卡卡罗"),
    ("今汐", "是谁", "今汐"),
    ("今汐", "90级基础属性", "等级属性"),
    ("卡卡罗", "面板", "等级属性"),
    ("今汐", "技能倍率", "技能详情"),
    ("今汐", "大招倍率", "技能详情"),
    ("今汐", "E技能倍率", "技能详情"),
    ("今汐", "共鸣链效果", "共鸣链"),
    ("今汐", "六链", "共鸣链"),
    ("今汐", "几链", "共鸣链"),
    ("今汐", "突破材料", "突破材料"),
    ("今汐", "语音", "语音"),
    ("卡卡罗", "背景故事", "档案"),
    ("忌炎", "生日", "基本信息"),
    ("炽霞", "CV", "基本信息"),
    ("今汐", "服饰", "服饰"),
    ("安可", "共鸣技能", "技能详情"),
    # —— 武器 ——
    ("苍鳞千嶂", "", "苍鳞千嶂"),
    ("苍鳞千嶂", "技能", "技能"),
    ("苍鳞千嶂", "突破材料", "突破材料"),
    ("苍鳞千嶂", "适合谁", "可用角色"),
    # —— 声骸 ——
    ("彻空冥雷", "2件套效果", "2件套效果"),
    ("彻空冥雷", "5件套效果", "5件套效果"),
    ("呼咻咻", "声骸技能", "呼咻咻"),
    ("无妄者", "声骸", "声骸"),
    # —— 敌人 ——
    ("无妄者", "怎么打", "无妄者"),
    ("无妄者", "", "关于无妄者"),
    # —— 道具 ——
    ("贝币", "怎么获得", "贝币"),
    ("贝币", "", "贝币"),
    # —— 卡池 ——
    ("现在UP什么", "", "UP记录"),
    ("复刻", "", "UP记录"),
    # —— 库街区主源（官方攻略）——
    ("今汐", "声骸搭配", "声骸"),
    ("今汐", "武器推荐", "时和岁稔"),
    ("今汐", "配队推荐", "配队"),
    ("今汐", "毕业面板", "90级"),
    ("今汐", "六链效果", "共鸣链"),
    ("声骸", "有哪些", "声骸列表"),
    ("武器", "有哪些", "武器列表"),
    ("卡卡罗", "技能加点", "技能加点"),
    # —— 回退 BWIKI（等级属性表/突破总消耗在 BWIKI 模板里）——
    ("卡卡罗", "90级面板", "90级"),
    ("今汐", "突破材料", "突破材料"),
    # —— 容错 ——
    ("鸣潮知识不存在测试词", "", "未找到"),
)


async def main(strict=False, threshold=0.8):
    records, passed = [], 0
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = Cache(CACHE_DIR)
    kuro = KuroBbsClient(cache, timeout=15)
    kuro_service = KuroBbsService(kuro, timeout=30)
    bwiki = QueryService(
        WikiClient(cache, timeout=15, game="ww", source="bwiki"),
        profile=PROFILES["ww"],
    )
    service = WuwaSources(kuro_service, bwiki, timeout=40)
    try:
        for query, question, expected in SEARCH_CASES:
            try:
                result = None
                error = ""
                # BWIKI 的 WAF 对连发请求敏感：失败退避后整例重试一次。
                for attempt in range(2):
                    try:
                        result = await service.search(query, question)
                        break
                    except Exception as exc:  # noqa: BLE001
                        error = f"{type(exc).__name__}: {exc}"
                        result = None
                        if attempt < 1:
                            await asyncio.sleep(15)
                if result is None:
                    raise RuntimeError(error) from None
                status = result.get("status", "")
                sections = result.get("available_sections") or []
                text = "\n".join(
                    item.get("text", "") for item in result.get("evidence", [])
                )
                candidates = "\n".join(
                    item.get("title", "") for item in result.get("candidates", [])
                )
                haystack = (
                    "\n".join(sections)
                    + "\n"
                    + text
                    + "\n"
                    + candidates
                    + "\n"
                    + str(result.get("message", ""))
                )
                ok = status in {"ok", "needs_choice", "not_found"} and (
                    expected in haystack
                )
                passed += int(ok)
                records.append(
                    {
                        "query": query,
                        "question": question,
                        "status": status,
                        "title": result.get("title"),
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
            # BWIKI 的 WAF 对高频请求敏感；用例间稍作停顿。
            await asyncio.sleep(2.0)
    finally:
        await kuro.close()

    total = len(records)
    rate = passed / total if total else 0.0
    output = Path("research/ww-coverage.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"WW coverage: {passed}/{total} ({rate:.0%})")
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
