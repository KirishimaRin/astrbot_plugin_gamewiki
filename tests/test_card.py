"""Offline coverage for the local evidence card renderer."""

import io
from pathlib import Path

import pytest
from PIL import Image

from wiki import card

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def test_render_card_skips_hosts_without_fonts(monkeypatch):
    monkeypatch.setattr(card, "_font_path", lambda: None)
    assert card.render_card("标题", "来源", [("分节", "正文")]) is None


@pytest.fixture()
def latin_font(monkeypatch):
    if not Path(DEJAVU).exists():
        pytest.skip("no font available for card rendering")
    monkeypatch.setattr(card, "_font_path", lambda: DEJAVU)


def test_wrap_keeps_latin_words_whole(latin_font):
    font = card._font(DEJAVU, card.BODY_SIZE)
    lines = card.wrap("Damage 320% critical chance", font, 120)
    joined = " ".join(lines)
    for word in ("Damage", "320%", "critical", "chance"):
        assert word in joined, word
    for line in lines:
        assert font.getlength(line) <= 120 + font.getlength("chance")


def _has_cjk_font():
    return card._font_path() is not None


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_render_card_draws_cjk_sections_within_bounds():
    sections = [
        ("战技 / 汤汤", "对前方敌人造成伤害\n等级10：伤害 320% · 冷却 12秒"),
        ("培养材料", "汤汤突破材料清单：\n裂开的骨头 × 12"),
    ]
    png = card.render_card("汤汤", "终末地 AKEData", sections)
    assert png.startswith(b"\x89PNG")
    width, height = Image.open(io.BytesIO(png)).size
    assert width == card.WIDTH
    assert height <= card.MAX_HEIGHT


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_accent_colors_the_header_band():
    accent = (196, 40, 40)
    png = card.render_card("汤汤", "", [("战技", "伤害 320%")], accent)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    assert image.getpixel((card.WIDTH // 2, 10)) == accent
    assert image.getpixel((card.MARGIN, 10)) == accent


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_cards_without_an_accent_use_the_neutral_band():
    png = card.render_card("汤汤", "", [("战技", "伤害 320%")])
    image = Image.open(io.BytesIO(png)).convert("RGB")
    assert image.getpixel((card.WIDTH // 2, 10)) == card.NEUTRAL


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_zebra_striping_keeps_body_text_readable():
    sections = [
        ("分节一", "第一段正文。\n第二行。"),
        ("分节二", "第二段正文。\n第二行。"),
    ]
    png = card.render_card("标题", "", sections, (64, 145, 108))
    image = Image.open(io.BytesIO(png)).convert("RGB")
    colors = {
        image.getpixel((card.WIDTH - card.MARGIN - 6, y))
        for y in range(10, image.height - 10)
    }
    assert (246, 248, 251) in colors, "the second block should carry a zebra fill"


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_long_cards_are_truncated_at_the_height_cap():
    sections = [(f"分节 {index}", "很长的正文\n" * 20) for index in range(10)]
    png = card.render_card("标题", "来源", sections)
    width, height = Image.open(io.BytesIO(png)).size
    assert height == card.MAX_HEIGHT


def test_height_truncation_keeps_text_above_the_source(latin_font, monkeypatch):
    drawn = []
    original = card.ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        drawn.append((xy, text, kwargs["font"]))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(card.ImageDraw.ImageDraw, "text", record)
    png = card.render_card(
        "Title", "Source", [(f"Section {i}", "Body\n" * 16) for i in range(6)]
    )
    height = Image.open(io.BytesIO(png)).height
    source_y = next(xy[1] for xy, text, _ in drawn if text == "Source")
    for xy, text, font in drawn:
        if text == "Source":
            continue
        assert xy[1] + font.getmetrics()[0] + font.getmetrics()[1] < source_y
    assert height == card.MAX_HEIGHT
    assert any(text == "……" for _, text, _ in drawn)


def test_empty_sections_render_a_title_only_card(latin_font):
    png = card.render_card("Only Title", "Source", [])
    assert png.startswith(b"\x89PNG")


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_overlong_sections_are_capped_per_section():
    png = card.render_card("标题", "", [("长分节", "一行文字\n" * 40)])
    _, height = Image.open(io.BytesIO(png)).size
    assert height < card.MAX_HEIGHT
