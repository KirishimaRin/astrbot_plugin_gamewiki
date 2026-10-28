from pathlib import Path
from urllib.parse import unquote

import pytest

from wiki.extractor import evidence, extract_sections
from wiki.formatter import format_command
from wiki.games import PROFILES
from wiki.layout import layout_blocks, table_blocks


def test_horizontal_material_stages_keep_column_correspondence():
    assert table_blocks(
        [
            "20级 | 30级 | /",
            "5 思绪末屑 4000 信用点 | 10 思绪末屑 8000 信用点 | /",
        ]
    ) == ["20级\n思绪末屑 × 5\n信用点 × 4000", "30级\n思绪末屑 × 10\n信用点 × 8000"]


def test_upgrade_requirements_stay_with_their_stage():
    blocks = table_blocks(["1→2 | 2→3", "角色晋阶1 | 角色晋阶2", "材料甲 3 | 材料乙 6"])
    assert blocks == ["1→2\n角色晋阶1\n材料甲 3", "2→3\n角色晋阶2\n材料乙 6"]


def test_empty_weapon_icon_is_not_a_subheader():
    assert table_blocks(
        [
            "图标 | 武器名称 | 稀有度 | 武器种类",
            " | 测试剑 | 6星 | 单手剑",
        ]
    ) == ["武器名称：测试剑\n稀有度：6星\n武器种类：单手剑"]


def test_repeated_materials_remain_in_each_phase():
    text = format_command(
        {
            "status": "ok",
            "title": "角色",
            "url": "https://example.com",
            "evidence": [
                {
                    "section": "精英化",
                    "text": "精英阶段1\n龙门币 × 30000\n材料甲 × 5\n精英阶段2\n龙门币 × 30000\n材料甲 × 5",
                }
            ],
        }
    )
    assert text.count("龙门币 × 30000") == 2
    assert text.count("材料甲 × 5") == 2


def test_arknights_material_widgets_pair_names_and_counts():
    item = '<span class="itembox"><div class="itemattr">30000</div><div class="itemNOname">龙门币</div></span>'
    for wrapper in ("<div>{}</div>", "<table><tr><td>{}</td></tr></table>"):
        sections = extract_sections(
            "<h2>精英化提升</h2>" + wrapper.format(item), "角色", prefix="arknights"
        )
        assert "龙门币 × 30000" in str(sections)


def test_filter_controls_removed_but_catalog_data_kept():
    html = '<div class="map-dh">图鉴导航</div><table><tr><td><ul class="cardSelectOption"><li>全部武器</li></ul></td></tr></table><h2>武器</h2><table><tr><th>武器名称</th><th>稀有度</th></tr><tr><td>测试剑</td><td>6星</td></tr></table>'
    sections = str(extract_sections(html, "武器图鉴", prefix="zmd"))
    assert "图鉴导航" not in sections and "全部武器" not in sections
    assert "测试剑" in sections and "6星" in sections


def test_missing_image_file_labels_are_filtered_but_item_names_remain():
    sections = str(
        extract_sections(
            "<div>文件:武器立绘-测试.png</div><p>测试武器</p>", "音擎图鉴", prefix="zzz"
        )
    )
    assert "文件:" not in sections and "测试武器" in sections


def test_materials_and_short_facts_have_compact_lines():
    assert layout_blocks("等级需求\n50\n材料\n龙门币 × 30000\n材料甲 × 5") == [
        "等级需求：50",
        "龙门币 × 30000\n材料甲 × 5",
    ]
    assert layout_blocks("攻击力增加\n解锁新天赋") == ["攻击力增加\n解锁新天赋"]


def test_game_specific_queries_exclude_unrelated_upgrade_sections():
    for game, question, wanted, unwanted in [
        ("sr", "晋阶材料", "角色晋阶材料", "技能晋阶材料"),
        ("sr", "技能晋阶材料", "技能晋阶材料", "角色晋阶材料"),
        ("arknights", "精英化", "精英化提升", "技能升级消耗"),
    ]:
        profile = PROFILES[game]
        sections = extract_sections(
            f"<h2>{wanted}</h2><p>相关材料。</p><h2>{unwanted}</h2><p>其他材料。</p>",
            "角色",
            prefix=game,
        )
        snippets, _, _ = evidence(
            sections,
            question,
            4000,
            extra_intents=profile.intents,
            specifics=profile.specifics,
        )
        assert [s["section"] for s in snippets] == [wanted]


def test_specific_triggers_are_word_tuples():
    for profile in PROFILES.values():
        assert all(isinstance(words, tuple) for words, _ in profile.specifics)


def test_ragged_rows_keep_their_stage_values():
    assert table_blocks(
        [
            "20级 | 30级 | 40级",
            "材料甲 5 | 材料乙 6",
        ]
    ) == ["20级\n材料甲 5", "30级\n材料乙 6"]


def test_empty_first_cell_does_not_emit_keyless_pairs():
    assert table_blocks([" | 120 / 80"]) == []


def test_first_real_image_is_captured_as_entry_card():
    meta = {}
    html = (
        '<div class="mw-parser-output">'
        '<img src="/thumb/icons/x.png/30px-x.png" width="30" alt="图标">'
        '<img src="//patchwiki.biligame.com/images/ys/0/06/abc.png" width="80" alt="纳西妲">'
        "<p>正文。</p></div>"
    )
    extract_sections(html, "角色", meta=meta)
    assert meta["image_url"].startswith("https://patchwiki.biligame.com/")
    assert "/640px-" not in meta["image_url"], "non-thumb URL stays untouched"


def test_thumb_urls_are_upscaled_and_iconless_pages_have_no_image():
    meta = {}
    extract_sections(
        '<div class="mw-parser-output"><img src="//patchwiki.biligame.com/images/ys/thumb/a/aa/x.png/80px-x.png" width="80"></div>',
        "角色",
        meta=meta,
    )
    assert "/640px-x.png" in meta["image_url"]
    meta2 = {}
    extract_sections(
        "<div class='mw-parser-output'><p>无图。</p></div>", "角色", meta=meta2
    )
    assert meta2["image_url"] == ""


def test_zmd_character_uses_portrait_instead_of_rarity_strip():
    html = (Path(__file__).parent / "fixtures" / "zmd-character-images.html").read_text(
        encoding="utf-8"
    )
    meta = {}
    extract_sections(html, "汤汤", prefix="zmd", meta=meta)
    assert "640px-汤汤立绘.png" in unquote(meta["image_url"])
    assert "b57cii2mgn9tvts5f0wdetdulrbyqug" not in meta["image_url"]


@pytest.mark.parametrize(
    "game,title",
    [("ys", "纳西妲"), ("sr", "流萤"), ("zzz", "艾莲"), ("arknights", "能天使")],
)
def test_entry_portrait_is_selected_before_tables_remove_images(game, title):
    html = (
        '<div class="mw-parser-output">'
        '<img alt="其他角色立绘.png" src="https://example.test/other.png" width="800">'
        '<img alt="Icon profession.png" src="https://example.test/profession.png" width="100">'
        "<table><tr><td>角色资料</td><td>"
        f'<img alt="{title}立绘.png" src="https://example.test/portrait.png" width="800">'
        "</td></tr></table><p>角色介绍。</p></div>"
    )
    meta = {}
    extract_sections(html, title, prefix=game, meta=meta)
    assert meta["image_url"] == "https://example.test/portrait.png"


def test_encoded_portrait_filename_is_used_when_alt_is_missing():
    meta = {}
    extract_sections(
        '<img alt="背景.png" src="https://example.test/background.png">'
        '<img src="https://example.test/%E6%B1%A4%E6%B1%A4%E7%AB%8B%E7%BB%98.png">',
        "汤汤",
        prefix="zmd",
        meta=meta,
    )
    assert "汤汤立绘.png" in unquote(meta["image_url"])


def test_rarity_strips_and_small_ui_icons_do_not_become_entry_images():
    meta = {}
    extract_sections(
        '<img alt="6星.png" src="https://example.test/rarity.png" width="425" height="70">'
        '<img alt="力量.png" src="https://example.test/stat.png" width="30" height="30">'
        '<img alt="角色头像.png" src="https://example.test/avatar.png" width="256">'
        '<img src="https://example.test/unknown-strip.png" width="425" height="70">',
        "汤汤",
        prefix="zmd",
        meta=meta,
    )
    assert meta["image_url"] == ""


def test_skin_art_is_preferred_to_named_avatar_and_invalid_sources_are_skipped():
    meta = {}
    extract_sections(
        '<img src="https://[invalid">'
        '<img alt="能天使05.png" src="https://example.test/avatar.png" width="100">'
        '<img alt="Pack 能天使 skin 0 0.png" src="https://example.test/portrait.png" width="1024">',
        "能天使",
        prefix="arknights",
        meta=meta,
    )
    assert meta["image_url"] == "https://example.test/portrait.png"
