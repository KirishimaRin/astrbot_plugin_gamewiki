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
def test_long_cards_share_the_height_budget():
    sections = [(f"分节 {index}", "很长的正文\n" * 20) for index in range(10)]
    png = card.render_card("标题", "来源", sections)
    width, height = Image.open(io.BytesIO(png)).size
    assert height <= card.MAX_HEIGHT


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
        if text in {"Source", "内容节选"}:
            continue
        assert xy[1] + font.getmetrics()[0] + font.getmetrics()[1] < source_y
    assert height <= card.MAX_HEIGHT
    assert all(any(text == f"Section {i}" for _, text, _ in drawn) for i in range(6))
    assert any("…" in text for _, text, _ in drawn)


def test_embedded_skill_tables_drop_navigation_and_keep_level_labels():
    text = (
        "普攻\n战技\n点击查看技能预览\n造成火属性伤害。\n普攻 - 闪燃推进\n"
        "详细属性 | LV1 | LV2 | LV10\n单体伤害 | 50% | 60% | 140%\n"
        "恢复生命。\n战技 - 底火斩击\n详细属性 | LV10\n伤害 | 280%"
    )
    groups = card._table_sections("行迹", text)
    assert groups == [
        (
            "普攻 - 闪燃推进",
            "造成火属性伤害。",
            [("单体伤害", "LV1 50%  /  LV10 140%")],
        ),
        ("战技 - 底火斩击", "恢复生命。", [("伤害", "LV10 280%")]),
    ]


def test_level_excerpts_keep_complete_fields_and_omit_overview_noise():
    prose, facts = card._content(
        "技能描述（等级1）：造成伤害。随后恢复生命。\n"
        "等级1：伤害倍率：20%；总失衡值：15\n"
        "……（其余22个等级略，可指定等级查询）\n"
        "等级12：终结技期间伤害倍率：81%；其他属性：18%",
        [],
    )
    assert prose == "造成伤害。"
    assert facts == [("等级1", "伤害倍率：20%"), ("等级12", "终结技期间伤害倍率：81%")]


def test_long_stat_fields_are_omitted_whole(latin_font, monkeypatch):
    drawn = []
    original = card.ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        drawn.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(card.ImageDraw.ImageDraw, "text", record)
    card.render_card(
        "Title",
        "Source",
        [("Skill", "Description.\n等级12：" + "condition " * 80 + "81%")],
    )
    assert "等级12" not in drawn
    assert "内容节选" in drawn


def test_empty_sections_render_a_title_only_card(latin_font):
    png = card.render_card("Only Title", "Source", [])
    assert png.startswith(b"\x89PNG")


@pytest.mark.skipif(not _has_cjk_font(), reason="no CJK font on this host")
def test_overlong_sections_are_capped_per_section():
    png = card.render_card("标题", "", [("长分节", "一行文字\n" * 40)])
    _, height = Image.open(io.BytesIO(png)).size
    assert height < card.MAX_HEIGHT


def test_empty_endpoint_levels_are_not_attached_to_values():
    groups = card._table_sections(
        "战技",
        "造成伤害。\n详细属性 | LV1 | LV2 | LV3\n伤害 | 20% | 30% | \n冷却 | 5秒 | | ",
    )
    assert groups[0][2] == [("伤害", "LV1 20%  /  LV2 30%"), ("冷却", "LV1 5秒")]


def test_material_columns_keep_stage_and_quoted_names():
    groups = card._structured_sections(
        "技能升级材料",
        "等级 | 所需材料 | 等级 | 所需材料\n1→2 | 「巧思」的教导 × 3 摩拉 × 12500 | 6→7 | 「巧思」的哲学 × 4 摩拉 × 120000",
    )
    assert groups == [
        ("技能升级材料 · 1→2", "", [("「巧思」的教导", "× 3"), ("摩拉", "× 12500")]),
        ("技能升级材料 · 6→7", "", [("「巧思」的哲学", "× 4"), ("摩拉", "× 120000")]),
    ]


def test_prts_stats_keep_stage_and_excluded_bonus_condition():
    groups = card._structured_sections(
        "属性",
        " | 精英0 1级 不包括 信赖 及 潜能 加成 | 精英2 满级 不包括 信赖 及 潜能 加成 | 信赖加成上限\n生命上限 | 711 | 1673 | \n攻击 | 183 | 540 | 90\n防御 | 57 | 161 | ",
    )
    assert groups[1] == (
        "属性 · 精英2 满级",
        "不包括 信赖 及 潜能 加成",
        [("生命上限", "1673"), ("攻击", "540"), ("防御", "161")],
    )


def test_projected_skill_level_keeps_description_cost_and_duration():
    groups = card._structured_sections(
        "技能 / 技能3",
        " | 过载模式 | 自动回复 自动触发\n等级 | 描述 显示算法 | 初始 预置的技力 | 消耗 需要的技力 | 持续 时间（秒）\n7 | 攻击变为5连射，技能会自动开启 | 20 | 38 | 15",
    )
    assert groups == [
        (
            "技能 / 技能3 · 过载模式 · 等级7",
            "攻击变为5连射，技能会自动开启",
            [("初始技力", "20"), ("消耗技力", "38"), ("持续时间", "15 秒")],
        )
    ]


def test_story_excerpt_uses_narrative_instead_of_unlock_navigation():
    prose, _ = card._content(
        "干员档案\n基础档案\n初始开放\n【代号】能天使【体检】确认为非感染者。\n客观履历\n初始开放\n能天使，拉特兰公民。企鹅物流成员。",
        [],
    )
    assert prose == "能天使，拉特兰公民。"


def test_material_grid_keeps_later_items_with_their_quantities(latin_font, monkeypatch):
    drawn = []
    original = card.ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        drawn.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(card.ImageDraw.ImageDraw, "text", capture)
    card.render_card(
        "Materials",
        "Source",
        [
            (
                "突破",
                "0~90级共计需要\n" + " ".join(f"item{i} × {i + 1}" for i in range(12)),
            )
        ],
    )
    assert "item11 × 12" in drawn
