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
SECTION_SIZE = 25
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
def _font(path, size):
    return ImageFont.truetype(path, size)


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
                value = f"{cells[1]} {row[1]}"
                if len(cells) > 2:
                    value += f"  /  {cells[-1]} {row[-1]}"
                rows.append((row[0], value))
            end += 1
        if rows:
            groups.append((label, "\n".join(prose), rows))
        start = end
    return groups or [(name, text, [])]


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
    prose = "\n".join(descriptions)
    first = re.match(r".*?[。！？]", prose, re.S)
    if first:
        prose = first[0]
    return prose, facts[:2]


def render_card(
    title: str, source: str, sections: list[tuple[str, str]], accent: tuple = ()
):
    """Return a compact excerpt card, or None without a usable CJK font."""
    path = _font_path()
    if path is None:
        return None
    accent = tuple(accent) if accent else NEUTRAL
    title_font = _font(path, TITLE_SIZE)
    section_font = _font(path, SECTION_SIZE)
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
        for group in _table_sections(name, text)
    ]
    groups = groups[:MAX_SECTIONS]
    # Share the height budget across topics, so the first skill cannot consume
    # all of the space and hide the remaining topics.
    top = 94
    budget = (MAX_HEIGHT - top - 74) // max(1, len(groups)) - 18
    blocks = []
    for name, text, table_rows in groups:
        prose, facts = _content(text, table_rows)
        heading = (
            bounded(name.replace(" / ", " · "), section_font, body_width, 2)
            if name
            else []
        )
        heading_h = len(heading) * 36
        rows = []
        used = heading_h + 58
        # Reserve readable space for two numerical rows before sizing prose.
        for key, value in facts:
            key_lines = wrap(key, small_font, 146)
            value_lines = wrap(value, body_font, body_width - 166)
            # Never cut a numerical field mid-value or remove its unit.
            if len(key_lines) > 2 or len(value_lines) > 2:
                continue
            row_h = max(len(key_lines) * 29, len(value_lines) * 35) + 16
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
        blocks.append((heading, lines, rows, block_h))

    band_height = 12
    height = min(MAX_HEIGHT, top + sum(b[3] for b in blocks) + 18 * len(blocks) + 74)
    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH - 1, band_height], fill=accent)
    label = bounded(title.strip(), title_font, WIDTH - MARGIN * 2, 1)[0]
    draw.text((MARGIN, 29), label, font=title_font, fill=INK)
    y = top
    for index, (heading, lines, rows, block_h) in enumerate(blocks):
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
                draw.text((text_x, y + 9 + i * 29), line, font=small_font, fill=MUTED)
            for i, line in enumerate(values):
                draw.text(
                    (text_x + 166, y + 5 + i * 35), line, font=body_font, fill=INK
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
