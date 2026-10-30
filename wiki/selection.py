"""Rank evidence by question intent while preserving structured facts."""

import re
from .models import Section
from .games import YS_SPECIFICS


def terms(text: str) -> set[str]:
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower())
    result = set(parts)
    for part in parts:
        if re.search(r"[\u4e00-\u9fff]", part):
            result.update(part[i : i + 2] for i in range(len(part) - 1))
    return result


INTENTS = [
    (("流程", "步骤", "怎么做"), ("任务过程", "任务流程", "任务步骤"), ()),
    (
        ("获取", "哪里", "在哪", "来源", "采集", "掉落", "怎么获得"),
        ("获取方式", "获取途径", "基本信息", "任务流程", "任务过程"),
        ("来源", "获取", "出现地点", "刷新", "触发", "接取", "掉落"),
    ),
    (
        ("属性", "面板", "攻击力", "暴击", "血量", "抗性"),
        ("详细面板", "属性数据", "基础属性", "基本信息", "抗性"),
        (),
    ),
    (("效果", "套装", "2件", "4件"), ("基础属性", "套装效果"), ()),
    (("突破", "升级材料", "培养材料"), ("突破", "突破材料", "技能升级材料"), ()),
    (
        ("技能", "战技", "大招", "普攻", "天赋", "倍率"),
        ("天赋", "BOSS技能", "技能"),
        (),
    ),
    (
        ("故事", "身世", "背景", "关系"),
        ("角色故事", "故事", "圣遗物故事", "任务剧情", "介绍"),
        (),
    ),
    (("推荐", "适合", "配队", "搭配"), ("推荐角色", "角色搭配推荐", "搭配"), ()),
    # 配装类分节：原神/星铁在「<角色>/攻略」子页，绝区零在角色主页内联。
    (
        ("圣遗物", "遗器", "驱动盘"),
        ("圣遗物", "遗器", "驱动盘套装", "驱动盘"),
        (),
    ),
    (("武器", "光锥", "音擎", "专武"), ("武器", "光锥", "音擎推荐", "音擎"), ()),
    # 原神/星铁没有独立词条分节，词条建议并入圣遗物/遗器分节。
    (
        ("词条", "副词条", "主词条"),
        ("词条推荐", "词条", "圣遗物", "遗器", "驱动盘套装"),
        (),
    ),
    (("配队", "阵容", "搭配"), ("阵容搭配", "角色搭配推荐", "搭配"), ()),
]

# A level table is one that carries a level column header; LV10 must not
# match the LV1 probe.
LEVEL_HEADER = re.compile(r"LV1(?!\d)|等级\s*\|")
# A bare "N级" in a question only projects when the question is about
# numbers (talents, ascension, stats), not about materials or lore.
LEVEL_CONTEXT = re.compile(
    r"技能|天赋|战技|大招|普攻|爆发|倍率|属性|面板|伤害|攻击|防御|生命|突破"
)


def select_lines(block: str, fields: tuple, default: bool) -> str:
    lines = block.splitlines()
    if fields:
        chosen = []
        for line in lines:
            cells = [v.strip() for v in line.split("|")]
            if len(cells) >= 2 and len(cells) % 2 == 0:
                for key, value in zip(cells[::2], cells[1::2]):
                    if value and any(word in key for word in fields):
                        chosen.append(f"{key} | {value}")
            elif any(word in line for word in fields):
                chosen.append(line)
        return "\n".join(chosen)
    if (
        default
        and sum(" | " in line for line in lines) > 1
        and not any(LEVEL_HEADER.search(line) for line in lines)
    ):
        low = (
            "TAG",
            "系列素材",
            "同类素材",
            "相关食物",
            "相关武器",
            "中文CV",
            "日文CV",
            "英文CV",
            "韩文CV",
        )
        lines = [line for line in lines if not line.startswith(low)]
        lines.sort(
            key=lambda line: (
                0 if line.startswith(("介绍 |", "描述 |", "任务描述 |")) else 1
            )
        )
    # Collapse repeated colspan values, never numeric level tables.
    if not any(LEVEL_HEADER.search(line) for line in lines):
        for i, line in enumerate(lines):
            cells = [v.strip() for v in line.split("|")]
            if len(cells) > 2 and len(set(cells[1:])) == 1:
                lines[i] = f"{cells[0]} | {cells[1]}"
    return "\n".join(lines)


def evidence(
    sections: list[Section],
    question: str,
    limit: int,
    section: str = "",
    page_title: str = "",
    extra_intents: tuple = (),
    specifics: tuple = YS_SPECIFICS,
):
    """Choose useful sections first; do not pad a focused answer with unrelated text."""
    wanted = terms(question)
    table = (*INTENTS, *extra_intents)
    intents = [entry for entry in table if any(word in question for word in entry[0])]
    triggers = sorted(
        {word for entry in table for word in entry[0] if word in question}
    )
    headings = tuple(h for _, names, _ in intents for h in names)
    fields = tuple(f for _, _, names in intents for f in names)
    specific = next(
        (name for triggers, name in specifics if any(t in question for t in triggers)),
        "",
    )
    # A mapping name may be a tuple when sources disagree on the same
    # section (PRTS 后勤技能 vs BWIKI 基建技能).
    specific_names = tuple(specific) if isinstance(specific, tuple) else (specific,)
    candidates = [s for s in sections if not section or section in s.title]
    # PRTS's parent skill section only lists unlock navigation. Its child
    # sections carry the actual skills, including skill 3.
    candidates = [
        s
        for s in candidates
        if not (
            s.blocks
            and all(re.fullmatch(r"技能\d+（精英\d+开放）", b) for b in s.blocks)
        )
    ]
    # Page templates can emit one heading twice (BWIKI repeats 行迹/技能晋阶
    # 材料 blocks); the first copy is authoritative and repeats only burn the
    # evidence budget and the card layout.
    seen_titles = set()
    candidates = [
        s
        for s in candidates
        if s.title not in seen_titles and not seen_titles.add(s.title)
    ]

    def meta(mode, used_sections, omitted=0):
        return {
            "mode": mode,
            "intents": triggers,
            "sections": used_sections,
            "omitted_sections": omitted,
        }

    # A numeric/statistics question needs a table, not acquisition-only fields.
    # Only intents whose headings exist on this page can contribute: the pool
    # intents row matches generic words (当前/有什么) on every page, and
    # counting it here would drop acquisition field filtering for ordinary
    # questions such as "胡桃现在怎么获得".
    page_parts = {p.strip() for s in candidates for p in s.title.split("/")}
    contributing = [
        entry
        for entry in intents
        if not entry[1] or any(h in page_parts for h in entry[1])
    ]
    if len(contributing) > 1:
        fields = ()

    if section and not candidates:
        return [], False, meta("section", [])
    if specific:
        subset = [
            s
            for s in candidates
            if (
                any(part.strip().startswith("突破") for part in s.title.split("/"))
                if specific == "突破"
                else any(name in s.title for name in specific_names)
            )
        ]
        if subset:
            candidates = subset
    elif headings and not section:
        subset = [
            s
            for s in candidates
            if any(h in [p.strip() for p in s.title.split("/")] for h in headings)
        ]
        if subset:
            candidates = subset

    def score(item):
        if not question:
            priorities = {
                page_title: 100,
                "基本信息": 90,
                "基础信息": 90,
                "基础属性": 85,
                "介绍": 95,
                "简介": 95,
                "概览": 10,
            }
            return priorities.get(item.title, 0)
        heading_score = max(
            (100 - i for i, h in enumerate(headings) if h in item.title), default=0
        )
        if specific and any(name in item.title for name in specific_names):
            heading_score = max(heading_score, 100)
        return (
            heading_score
            + 3 * len(wanted & terms(item.title))
            + min(10, len(wanted & terms(" ".join(item.blocks))))
        )

    ranked = sorted(
        enumerate(candidates), key=lambda p: (score(p[1]), -p[0]), reverse=True
    )
    # Default lookup is an introduction. A focused lookup keeps only relevant
    # sections; with no positive score at all it falls back to the best one
    # instead of failing outright.
    mode = "section" if section else ("intro" if not question else "focused")
    if not question:
        ranked = ranked[:1]
    elif not section and ranked:
        top = score(ranked[0][1])
        focused = [(i, s) for i, s in ranked if score(s) > 0 and score(s) >= top * 0.6]
        if focused:
            ranked = focused
        else:
            ranked = ranked[:1]
            mode = "fallback"
    omitted = max(0, len(ranked) - 3) if question else 0
    snippets, used, cut = [], 0, False
    for _, item in ranked[:3]:
        item_fields = (
            ()
            if any(
                name in item.title
                for name in ("获取方式", "获取途径", "任务过程", "任务流程")
            )
            else fields
        )
        blocks = [
            (i, select_lines(project_level(b, question), item_fields, not question))
            for i, b in enumerate(item.blocks)
        ]
        blocks = [(i, b) for i, b in blocks if b]
        if not question and blocks and " | " in blocks[0][1]:
            blocks = blocks[:1]
        if question:
            blocks.sort(key=lambda p: len(wanted & terms(p[1])), reverse=True)
        selected, section_used = [], 0
        for index, block in blocks:
            room = min(limit - used, 2400 - section_used) - 1
            if room <= 0:
                cut = True
                break
            if len(block) > room:
                lines = block.splitlines()
                if " | " in block:
                    kept, size = [lines[0]], len(lines[0])
                    for line in lines[1:]:
                        if size + len(line) + 1 <= room:
                            kept.append(line)
                            size += len(line) + 1
                    if len(kept) < 2:
                        cut = True
                        continue
                    block = "\n".join(kept)
                else:
                    matches = [block.find(t) for t in wanted if t in block]
                    start = max(0, min(matches) - 100) if matches else 0
                    block = block[start : start + room]
                cut = True
            selected.append((index, block))
            used += len(block) + 1
            section_used += len(block) + 1
        if selected:
            snippets.append(
                {
                    "section": item.title,
                    "anchor": item.anchor,
                    "text": "\n".join(b for _, b in sorted(selected)),
                }
            )
    if not snippets:
        mode = "section" if section else ("intro" if not question else "empty")
    return snippets, cut, meta(mode, [s["section"] for s in snippets], omitted)


def _max_level(lines: list[str]) -> int | None:
    """Resolve 满级 to the highest level the table itself carries."""
    header = [v.strip() for v in lines[0].split("|")]
    columns = [
        int(m.group(1)) for cell in header if (m := re.fullmatch(r"LV(\d{1,2})", cell))
    ]
    if columns:
        return max(columns)
    for index, line in enumerate(lines):
        cells = [v.strip() for v in line.split("|")]
        if "等级" not in cells:
            continue
        values = []
        for row in lines[index + 1 :]:
            row_cells = [v.strip() for v in row.split("|")]
            for col, name in enumerate(cells):
                if (
                    name == "等级"
                    and col < len(row_cells)
                    and (m := re.fullmatch(r"(\d{1,3})(?:级)?", row_cells[col]))
                ):
                    values.append(int(m.group(1)))
        if values:
            return max(values)
    return None


# 精炼等级只可能是 1~5；“精N”要求“精”后紧跟数字，不碰“精锻”“精粹”。
REFINE_LEVEL = re.compile(r"精炼\s*([1-5])|精([1-5])(?!\d)")
# BWIKI 原神武器页没有精炼分节：各精炼档数值以斜杠列表内联在条目首段
# 武器技能里（“20%/25%/30%/35%/40%”）。精炼投影把每个五档列表替换成
# 对应档的那一项；档数不是 5 的列表（日期、成对数值等）原样保留。
REFINE_VALUES = re.compile(r"\d+(?:\.\d+)?(?:%|点)?(?:/\d+(?:\.\d+)?(?:%|点)?)+")


def project_refine(block: str, level: int) -> str:
    """Keep only the requested refinement rank of each inline rank list."""

    def pick(match):
        items = match.group(0).split("/")
        return items[level - 1] if len(items) == 5 else match.group(0)

    return REFINE_VALUES.sub(pick, block)


def project_level(block: str, question: str) -> str:
    """Select a requested talent level while retaining its attribute column."""
    refine = REFINE_LEVEL.search(question)
    if refine:
        return project_refine(block, int(refine.group(1) or refine.group(2)))
    match = re.search(r"(?:[lL][vV]\s*(\d{1,2})|(\d{1,2})\s*级)", question)
    maxed = bool(re.search(r"满级", question))
    if (not match and not maxed) or "\n" not in block:
        return block
    # Explicit "LV10" is unambiguous; a bare "N级" needs talent/stat context.
    if (
        match
        and match.group(1) is None
        and not LEVEL_CONTEXT.search(question)
        and not maxed
    ):
        return block
    lines = block.splitlines()
    level = int(match.group(1) or match.group(2)) if match else _max_level(lines)
    if level is None:
        return block
    header = [v.strip() for v in lines[0].split("|")]
    wanted = f"LV{level}"
    if wanted not in header:
        for i, line in enumerate(lines):
            columns = [v.strip() for v in line.split("|")]
            if "等级" not in columns:
                continue
            matches = [line]
            for row in lines[i + 1 :]:
                cells = [v.strip() for v in row.split("|")]
                for col, name in enumerate(columns):
                    if (
                        name == "等级"
                        and col < len(cells)
                        and cells[col] in {str(level), f"{level}级"}
                    ):
                        matches.append(
                            " | ".join(cells[col : col + 2])
                            if columns.count("等级") > 1
                            else row
                        )
            if len(matches) > 1:
                heading = " | ".join(columns[:2]) if columns.count("等级") > 1 else line
                subheaders = []
                for row in lines[i + 1 :]:
                    cells = [v.strip() for v in row.split("|")]
                    if cells and re.fullmatch(r"\d+(?:级)?|初始", cells[0]):
                        break
                    if cells and not cells[0] and any(cells):
                        subheaders.append(row)
                return "\n".join([*lines[:i], heading, *subheaders, *matches[1:]])
        return block
    col = header.index(wanted)
    projected = []
    for line in lines:
        cells = [v.strip() for v in line.split("|")]
        if len(cells) > col:
            projected.append(f"{cells[0]} | {cells[col]}")
    return "\n".join(projected)
