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
MAX_LINES_PER_SECTION = 16

BORDER = 2
TICK_WIDTH = 4
TEXT_OFFSET = 12
BAND_PAD = 13

INK = (31, 35, 40)
MUTED = (101, 109, 118)
FAINT = (163, 170, 180)
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


def render_card(
    title: str, source: str, sections: list[tuple[str, str]], accent: tuple = ()
):
    """Return PNG bytes, or None when the host has no usable font."""
    path = _font_path()
    if path is None:
        return None
    accent = tuple(accent) if accent else NEUTRAL
    title_font = _font(path, TITLE_SIZE)
    section_font = _font(path, SECTION_SIZE)
    body_font = _font(path, BODY_SIZE)
    text_x = MARGIN + TEXT_OFFSET
    body_width = WIDTH - text_x - MARGIN

    def line_height(font):
        ascent, descent = font.getmetrics()
        return ascent + descent + LINE_GAP

    section_height = line_height(section_font) - LINE_GAP
    body_height = line_height(body_font)

    label = title.strip()
    if label and title_font.getlength(label) > WIDTH - MARGIN * 2:
        while label and title_font.getlength(label + "…") > WIDTH - MARGIN * 2:
            label = label[:-1]
        label += "…"

    blocks = []
    for name, text in sections[:MAX_SECTIONS]:
        lines = wrap(text, body_font, body_width)
        if len(lines) > MAX_LINES_PER_SECTION:
            # Long lore sections bow out; the text reply carries the rest.
            lines = [*lines[: MAX_LINES_PER_SECTION - 1], "……"]
        blocks.append((name, lines))

    def block_height(name, lines):
        return (section_height + 6 if name else 0) + body_height * len(lines)

    band_height = TITLE_SIZE + BAND_PAD * 2
    content_height = 0
    for index, (name, lines) in enumerate(blocks):
        if index:
            content_height += SECTION_GAP
        content_height += block_height(name, lines)
    footer_space = MARGIN + BODY_SIZE if source else 0
    natural = (
        BORDER + band_height + MARGIN + content_height + footer_space + MARGIN + BORDER
    )
    height = min(natural, MAX_HEIGHT)
    truncated = natural > height or len(sections) > MAX_SECTIONS

    image = Image.new("RGB", (WIDTH, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH - 1, height - 1], outline=RULE, width=BORDER)
    # The accent band carries the game identity; the body stays light for chat
    # compression legibility.
    draw.rectangle(
        [BORDER, BORDER, WIDTH - 1 - BORDER, BORDER + band_height], fill=accent
    )
    draw.text((MARGIN, BORDER + BAND_PAD), label, font=title_font, fill="white")

    y = BORDER + band_height + MARGIN
    stop = height - footer_space - BORDER
    content_stop = stop - body_height if truncated else stop
    for index, (name, lines) in enumerate(blocks):
        if index:
            y += SECTION_GAP
        heading_height = section_height + 6 if name else 0
        available_lines = max(0, (content_stop - y - heading_height) // body_height)
        fits = lines[:available_lines]
        if not fits:
            truncated = True
            break
        if len(fits) < len(lines):
            truncated = True
        drawn = block_height(name, fits)
        if index % 2:
            draw.rectangle(
                [
                    BORDER,
                    y - 4,
                    WIDTH - 1 - BORDER,
                    min(y + drawn + 4, stop + 4),
                ],
                fill=ZEBRA,
            )
        if name:
            draw.rectangle(
                [MARGIN, y + 2, MARGIN + TICK_WIDTH, y + section_height], fill=accent
            )
            draw.text((text_x, y), name, font=section_font, fill=INK)
            y += section_height + 6
        for line in fits:
            draw.text((text_x, y), line, font=body_font, fill=INK)
            y += body_height
        if len(fits) < len(lines):
            break

    if truncated:
        draw.text((text_x, stop - body_height), "……", font=body_font, fill=FAINT)
    if source:
        tag = source if len(source) <= 30 else source[:29] + "…"
        draw.text(
            (WIDTH - MARGIN - body_font.getlength(tag), height - MARGIN - BODY_SIZE),
            tag,
            font=body_font,
            fill=FAINT,
        )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
