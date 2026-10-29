"""Render the selected evidence as a card image with a per-game accent.

The card is drawn from evidence the pipeline already cleaned and bounded; no
upstream page is rendered and no browser is involved. Hosts without a usable
CJK font simply skip the card.
"""

import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .layout import layout_blocks

FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)

WIDTH = 640
MARGIN = 28
MAX_HEIGHT = 1800
TITLE_SIZE = 32
SECTION_SIZE = 24
BODY_SIZE = 24
MAX_SECTIONS = 6

TICK_WIDTH = 4
TEXT_OFFSET = 12

INK = (31, 35, 40)
MUTED = (101, 109, 118)
RULE = (208, 215, 222)
ZEBRA = (246, 248, 251)
NEUTRAL = (96, 111, 131)

# Latin words stay whole; everything else may break between characters.
TOKEN = re.compile(r"[!-~]+|\s+|.")


def _font_path():
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


@lru_cache(maxsize=8)
def _face_index(path):
    # TTC collections often put Japanese first. Select the Simplified Chinese
    # face by family name rather than assuming every collection has one order.
    if Path(path).suffix.lower() == ".ttc":
        for index in range(10):
            try:
                family, _ = ImageFont.truetype(path, 12, index=index).getname()
            except OSError:
                break
            if family.endswith(" SC") or "简体" in family:
                return index
    return 0


def _weight_path(path, bold):
    if bold:
        path = str(path)
        stem = Path(path).stem
        candidates = (
            path.replace("-Regular", "-Bold"),
            str(Path(path).with_name(stem + "-Bold" + Path(path).suffix)),
            path.replace("msyh.ttc", "msyhbd.ttc"),
        )
        for candidate in candidates:
            if candidate != path and Path(candidate).is_file():
                return candidate
    return path


@lru_cache(maxsize=16)
def _font(path, size, bold=False):
    path = _weight_path(path, bold)
    return ImageFont.truetype(path, size, index=_face_index(path))


def wrap(text: str, font, max_width: int) -> list[str]:
    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for token in TOKEN.findall(paragraph):
            if current and font.getlength(current + token) <= max_width:
                current += token
                continue
            if current:
                lines.append(current.rstrip())
                current = ""
            while font.getlength(token) > max_width and len(token) > 1:
                half = max(1, int(len(token) * max_width / font.getlength(token)))
                lines.append(token[:half])
                token = token[half:]
            current = token
        lines.append(current.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return lines or [""]


def _table_sections(name, text):
    """Split embedded skill tables using their existing labels and descriptions."""
    lines = text.splitlines()
    groups, start = [], 0
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2 or not all(re.fullmatch(r"LV\d+", c) for c in cells[1:]):
            continue
        # BWIKI emits the named skill label immediately before its level table.
        previous = lines[i - 1].strip() if i else ""
        labelled = re.match(
            r"^(?:强化)?(?:普攻|战技|终结技|秘技|天赋)\s*[-—]\s*\S", previous
        )
        label = previous if labelled else name
        prose = [
            v
            for v in lines[start : i - 1 if labelled else i]
            if re.search(r"[。！？]", v)
        ]
        rows, end = [], i + 1
        while end < len(lines) and "|" in lines[end]:
            row = [c.strip() for c in lines[end].split("|")]
            if len(row) == len(cells):
                populated = [j for j in range(1, len(row)) if row[j]]
                if populated:
                    low, high = populated[0], populated[-1]
                    value = f"{cells[low]} {row[low]}"
                    if high != low:
                        value += f"  /  {cells[high]} {row[high]}"
                    rows.append((row[0], value))
            end += 1
        if rows:
            groups.append((label, "\n".join(prose), rows))
        start = end
    return groups or [(name, text, [])]


MATERIAL = re.compile(r"([\w·「」（）()\-]{1,40})\s*×\s*(\d+(?:\.\d+)?(?:万|亿|w)?)")


def _structured_sections(name, text):
    """Adapt observed material lists and vertical/horizontal stat tables."""
    if text.strip() and all(
        v.strip() in {"未加强", "加强", "描述"} for v in text.splitlines()
    ):
        return []
    if re.search(r"材料|突破|精英化", name) and MATERIAL.search(
        "\n".join(layout_blocks(text))
    ):
        paired = []
        for line in text.splitlines():
            cells = [v.strip() for v in line.split("|")]
            for j in range(len(cells) - 1):
                if re.fullmatch(r"(?:精英阶段)?\d+[→➜]\d+", cells[j]):
                    pairs = [
                        (m[1], "× " + m[2]) for m in MATERIAL.finditer(cells[j + 1])
                    ]
                    if pairs:
                        paired.append((name + " · " + cells[j], "", pairs))
        if paired:
            return paired[:2]
        groups, label = [], name
        for block in layout_blocks(text):
            matches = list(MATERIAL.finditer(block))
            if not matches:
                stages = re.findall(
                    r"精英阶段\s*\d+|\d+级|[^\n]*(?:总计|共计)[^\n]*|升级所需经验",
                    block,
                )
                if stages:
                    label = stages[-1]
                continue
            prefix = block[: matches[0].start()].strip(" ：:\n")
            if prefix:
                prefix = prefix.splitlines()[0]
                label = label + " · " + prefix if label == "升级所需经验" else prefix
            pairs = list(dict.fromkeys((m[1], "× " + m[2]) for m in matches))
            groups.append((name + " · " + label if label != name else name, "", pairs))
        totals = [g for g in groups if re.search(r"总计|共计", g[0])]
        return totals[:2] or groups[:2]

    lines = text.splitlines()
    for i, line in enumerate(lines):
        header = [v.strip() for v in line.split("|")]
        if header[0] not in {"等级", "", "详细属性"} or len(header) < 3:
            continue
        rows = []
        for raw in lines[i + 1 :]:
            if "|" not in raw:
                break
            row = [v.strip() for v in raw.split("|")]
            if len(row) == len(header):
                rows.append(row)
        if not rows:
            continue
        if any(h.startswith("描述") for h in header):
            row = next(
                (r for r in rows if re.fullmatch(r"\d+|Rank [ⅠⅡⅢ]+", r[0])), None
            )
            if row is None:
                continue
            skill = [v.strip() for v in lines[0].split("|")]
            label = skill[1] if len(skill) > 1 and not skill[0] else ""
            facts = []
            for j, h in enumerate(header):
                if h.startswith(("初始", "消耗", "持续")) and row[j]:
                    key = (
                        "初始技力"
                        if h.startswith("初始")
                        else "消耗技力"
                        if h.startswith("消耗")
                        else "持续时间"
                    )
                    value = re.sub(r"^(?:初始|消耗|持续)\s*", "", row[j])
                    facts.append(
                        (
                            key,
                            value
                            + (
                                " 秒"
                                if key == "持续时间" and not value.endswith(("秒", "s"))
                                else ""
                            ),
                        )
                    )
            return [
                (
                    name + (" · " + label if label else "") + " · 等级" + row[0],
                    row[1],
                    facts,
                )
            ]
        if header[0] == "等级":
            # A subheader carries before/after ascension labels; never lose it.
            sub = rows[0] if rows and rows[0][0] in {"", "等级"} else None
            candidates = [
                r
                for r in rows
                if re.fullmatch(r"\d+(?:级)?", r[0])
                and sum(bool(v) for v in r[1:]) >= 3
            ]
            if not candidates:
                continue
            result = []
            for row in (
                [candidates[0], candidates[-1]] if len(candidates) > 1 else candidates
            ):
                facts, seen = [], set()
                for j in range(1, len(header)):
                    if header[j] in seen or not row[j]:
                        continue
                    seen.add(header[j])
                    label = header[j] + (" · " + sub[j] if sub and sub[j] else "")
                    facts.append((label, row[j]))
                result.append(
                    (name + " · " + row[0].removesuffix("级") + "级", "", facts[:3])
                )
            return result
        if not header[0] and any("精" in h or "MAX" in h for h in header[1:]):
            cols = [
                j
                for j in range(1, len(header))
                if header[j] and not header[j].startswith("信赖")
            ]
            return (
                [
                    (
                        name + " · " + header[j].split(" 不包括")[0],
                        "不包括" + header[j].split(" 不包括", 1)[1]
                        if " 不包括" in header[j]
                        else "",
                        [(r[0], r[j]) for r in rows if r[0] and r[j]][:3],
                    )
                    for j in dict.fromkeys([cols[0], cols[-1]])
                ]
                if cols
                else []
            )
    return _table_sections(name, text)


def _content(text, table_rows):
    """Select literal excerpts; no generated summaries or inferred values."""
    descriptions, facts = [], list(table_rows)
    text = "\n".join(layout_blocks(text)) if "|" in text else text
    for line in text.splitlines():
        line = line.strip()
        if not line or "其余" in line and "等级略" in line:
            continue
        level = re.match(r"^(等级\d+)\s*[：:]\s*(.+)", line)
        if level:
            # Keep complete fields, including units and conditions, with a level.
            fields = re.split(r"[；;]\s*", level[2])
            facts.append((level[1], fields[0]))
        else:
            line = re.sub(r"^技能描述（等级\d+）\s*[：:]\s*", "", line)
            descriptions.append(line)
    # Use the first complete sentence when possible; subsequent prose stays in
    # the text reply/source. Never splice two unrelated clauses into a summary.
    narrative = [
        line
        for line in descriptions
        if re.search(r"[。！？]", line) and not line.startswith("【")
    ]
    prose = narrative[0] if narrative else "\n".join(descriptions)
    first = re.match(r".*?[。！？]", prose, re.S)
    if first:
        prose = first[0]
    return prose, facts[:12] if facts and all(
        v.startswith("× ") for _, v in facts
    ) else facts[:3]


def render_card(
    title: str, source: str, sections: list[tuple[str, str]], accent: tuple = ()
):
    """Return a compact excerpt card, or None without a usable CJK font."""
    path = _font_path()
    if path is None:
        return None
    accent = tuple(accent) if accent else NEUTRAL
    title_font = _font(path, TITLE_SIZE, bold=True)
    section_font = _font(path, SECTION_SIZE, bold=True)
    body_font = _font(path, BODY_SIZE)
    small_font = _font(path, 18)
    text_x = MARGIN + TEXT_OFFSET
    body_width = WIDTH - text_x * 2
    line_height = 39

    def bounded(text, font, width, count):
        lines = wrap(text, font, width)
        if len(lines) <= count:
            return lines
        lines = lines[:count]
        last = lines[-1].rstrip("，；、 ")
        while last and font.getlength(last + "…") > width:
            last = last[:-1]
        lines[-1] = last + "…"
        return lines

    groups = [
        group
        for name, text in sections[:MAX_SECTIONS]
        for group in _structured_sections(name, text)
    ]
    groups = groups[:MAX_SECTIONS]
    # Share the height budget across topics, so the first skill cannot consume
    # all of the space and hide the remaining topics.
    top = 94
    budget = (MAX_HEIGHT - top - 74) // max(1, len(groups)) - 18
    blocks = []
    for name, text, table_rows in groups:
        prose, facts = _content(text, table_rows)
        material_grid = bool(facts) and all(
            value.startswith("× ") for _, value in facts
        )
        parts = name.split(" / ")
        if parts[0] == "天赋" and len(parts) >= 3:
            name = parts[-1] if "：" in parts[-1] else " · ".join(parts[-2:])
        elif parts[0] == "技能" and len(parts) == 2:
            name = parts[-1]
        heading = (
            bounded(name.replace(" / ", " · "), section_font, body_width, 2)
            if name
            else []
        )
        heading_h = len(heading) * 36
        rows = []
        used = heading_h + 58
        if material_grid:
            facts = [
                (
                    f"{facts[i][0]} {facts[i][1]}",
                    f"{facts[i + 1][0]} {facts[i + 1][1]}"
                    if i + 1 < len(facts)
                    else "",
                )
                for i in range(0, len(facts), 2)
            ]
        for key, value in facts:
            key_lines = wrap(
                key,
                body_font if material_grid else small_font,
                (body_width - 20) // 2 if material_grid else 146,
            )
            value_lines = wrap(
                value,
                body_font,
                (body_width - 20) // 2 if material_grid else body_width - 166,
            )
            # Never cut a numerical field mid-value or remove its unit.
            if len(key_lines) > 2 or len(value_lines) > 2:
                continue
            row_h = (
                max(
                    len(key_lines) * (35 if material_grid else 29),
                    len(value_lines) * 35,
                )
                + 16
            )
            if used + row_h + line_height > budget:
                break
            rows.append((key_lines, value_lines, row_h))
            used += row_h
        count = max(1, min(4, (budget - used) // line_height))
        lines = bounded(prose, body_font, body_width, count) if prose else []
        block_h = (
            16
            + heading_h
            + (12 if heading else 0)
            + len(lines) * line_height
            + (12 if rows else 0)
            + sum(r[2] for r in rows)
            + 18
        )
        blocks.append((heading, lines, rows, block_h, material_grid))

    band_height = 12
    height = min(MAX_HEIGHT, top + sum(b[3] for b in blocks) + 18 * len(blocks) + 74)
    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH - 1, band_height], fill=accent)
    label = bounded(title.strip(), title_font, WIDTH - MARGIN * 2, 1)[0]
    draw.text((MARGIN, 29), label, font=title_font, fill=INK)
    y = top
    for index, (heading, lines, rows, block_h, material_grid) in enumerate(blocks):
        if index % 2:
            draw.rounded_rectangle(
                [MARGIN - 8, y, WIDTH - MARGIN + 8, y + block_h], radius=12, fill=ZEBRA
            )
        y += 16
        if heading:
            draw.rectangle([MARGIN, y + 5, MARGIN + TICK_WIDTH, y + 28], fill=accent)
            for line in heading:
                draw.text((text_x, y), line, font=section_font, fill=INK)
                y += 36
            y += 12
        for line in lines:
            draw.text((text_x, y), line, font=body_font, fill=INK)
            y += line_height
        if rows:
            y += 12
        for keys, values, row_h in rows:
            draw.line([text_x, y, WIDTH - text_x, y], fill=RULE)
            for i, line in enumerate(keys):
                draw.text(
                    (text_x, y + 5 + i * (35 if material_grid else 29)),
                    line,
                    font=body_font if material_grid else small_font,
                    fill=INK if material_grid else MUTED,
                )
            for i, line in enumerate(values):
                draw.text(
                    (
                        text_x + ((body_width + 20) // 2 if material_grid else 166),
                        y + 5 + i * 35,
                    ),
                    line,
                    font=body_font,
                    fill=INK,
                )
            y += row_h
        y += 36
    footer_y = height - 46
    draw.text((MARGIN, footer_y), "内容节选", font=small_font, fill=MUTED)
    if source:
        tag = bounded(source, small_font, WIDTH // 2, 1)[0]
        draw.text(
            (WIDTH - MARGIN - small_font.getlength(tag), footer_y),
            tag,
            font=small_font,
            fill=MUTED,
        )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
