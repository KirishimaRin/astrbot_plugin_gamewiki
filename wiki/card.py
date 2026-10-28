"""Render the selected evidence as a plain text card image.

The card is drawn from evidence the pipeline already cleaned and bounded; no
upstream page is rendered and no browser is involved. Hosts without a usable
CJK font simply skip the card.
"""

import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
TITLE_SIZE = 30
SECTION_SIZE = 20
BODY_SIZE = 22
LINE_GAP = 8
SECTION_GAP = 18
MAX_SECTIONS = 6

INK = (31, 35, 40)
MUTED = (101, 109, 118)
FAINT = (163, 170, 180)
RULE = (208, 215, 222)

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


def render_card(title: str, source: str, sections: list[tuple[str, str]]):
    """Return PNG bytes, or None when the host has no usable font."""
    path = _font_path()
    if path is None:
        return None
    title_font = _font(path, TITLE_SIZE)
    section_font = _font(path, SECTION_SIZE)
    body_font = _font(path, BODY_SIZE)
    body_width = WIDTH - MARGIN * 2

    def line_height(font):
        ascent, descent = font.getmetrics()
        return ascent + descent + LINE_GAP

    section_height = line_height(section_font) - LINE_GAP
    body_height = line_height(body_font)

    blocks = []
    for name, text in sections[:MAX_SECTIONS]:
        blocks.append((name, wrap(text, body_font, body_width)))
    content_height = 0
    for index, (name, lines) in enumerate(blocks):
        if index:
            content_height += SECTION_GAP
        if name:
            content_height += section_height + 6
        content_height += body_height * len(lines)
    footer_space = MARGIN + BODY_SIZE if source else 0
    height = min(
        MARGIN + TITLE_SIZE + 10 + MARGIN + content_height + footer_space + MARGIN,
        MAX_HEIGHT,
    )
    truncated = height == MAX_HEIGHT and (
        MARGIN + TITLE_SIZE + 10 + MARGIN + content_height + footer_space + MARGIN
        > MAX_HEIGHT
    )

    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH - 1, height - 1], outline=RULE, width=2)

    y = MARGIN
    draw.text((MARGIN, y), title, font=title_font, fill=INK)
    y += TITLE_SIZE + 10
    draw.line([MARGIN, y, WIDTH - MARGIN, y], fill=RULE, width=1)
    y += MARGIN

    stop = height - footer_space
    for index, (name, lines) in enumerate(blocks):
        if y + body_height > stop:
            truncated = True
            break
        if index:
            y += SECTION_GAP
        if name:
            draw.text((MARGIN, y), name, font=section_font, fill=MUTED)
            y += section_height + 6
        for line in lines:
            draw.text((MARGIN, y), line, font=body_font, fill=INK)
            y += body_height

    if truncated:
        draw.text(
            (MARGIN, max(y, stop - body_height)), "……", font=body_font, fill=FAINT
        )
    if source:
        label = source if len(source) <= 30 else source[:29] + "…"
        draw.text(
            (WIDTH - MARGIN - body_font.getlength(label), height - MARGIN - BODY_SIZE),
            label,
            font=body_font,
            fill=FAINT,
        )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
