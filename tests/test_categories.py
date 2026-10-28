"""Category-independent regressions using synthetic content, not named-page patches."""

import pytest

from wiki.extractor import extract_sections
from wiki.selection import evidence, project_level


@pytest.mark.parametrize(
    "title,body,expected",
    [
        (
            "角色甲",
            "<h2>角色甲</h2><table><tr><th>介绍</th><td>角色说明。</td></tr></table>",
            "角色说明",
        ),
        (
            "武器乙",
            '<h2>武器乙</h2><p>攻击力 600</p><div class="card-title3">获取途径</div><p>限定祈愿</p>',
            "攻击力 600",
        ),
        (
            "材料丙",
            "<h2>基本信息</h2><table><tr><th>描述</th><td>山崖花朵</td></tr><tr><th>合成</th><td>{{{材料}}}</td></tr></table>",
            "山崖花朵",
        ),
        (
            "套装丁",
            '<div class="title">基础属性</div><p>2件套：元素伤害提升。</p><div class="title">推荐角色</div><p>角色丙</p>',
            "2件套",
        ),
        (
            "怪物戊",
            "<h2>介绍</h2><p>古老的巨龙。</p><h2>怪物戊语音</h2><p>怪物戊战斗台词</p>",
            "古老的巨龙",
        ),
        (
            "任务己",
            "<table><tr><th>任务描述</th><td>寻找遗失的物品。</td></tr></table><h2>任务剧情</h2><p>角色对话</p>",
            "寻找遗失的物品",
        ),
        (
            "书籍庚",
            "<h2>简介</h2><p>旅行者的游记。</p><h2>第一章</h2><p>旅途开始。</p>",
            "旅行者的游记",
        ),
    ],
)
def test_shared_cleaning_and_default_selection(title, body, expected):
    html = (
        '<div class="mw-parser-output"><nav>全站导航</nav><!-- NewPP CPU time -->'
        + body
        + '<div id="categoryData">{"data":[{"markType":1}]}</div></div>'
    )
    sections = extract_sections(html, title)
    snippets, _, _meta = evidence(sections, "", 1500, page_title=title)
    text = str(snippets)
    assert expected in text
    for noise in ("全站导航", "NewPP", "markType", "{{{", "战斗台词", "角色对话"):
        assert noise not in text


def test_acquisition_selects_fields_instead_of_description_and_related_lists():
    sections = extract_sections(
        "<h2>基本信息</h2><table><tr><th>描述</th><td>长篇背景</td></tr><tr><th>来源</th><td>野外采集</td></tr><tr><th>刷新时间</th><td>46小时</td></tr><tr><th>同类素材</th><td>材料甲 材料乙</td></tr></table>",
        "材料",
    )
    snippets, _, _meta = evidence(sections, "获取方式", 1500)
    text = str(snippets)
    assert "野外采集" in text and "46小时" in text
    assert "长篇背景" not in text and "材料乙" not in text


def test_plain_acquisition_section_retains_value_without_trigger_words():
    sections = extract_sections(
        '<div class="card-title3">获取途径</div><p>限定祈愿</p>', "武器"
    )
    snippets, _, _meta = evidence(sections, "获取方式", 1500)
    assert "限定祈愿" in str(snippets)


def test_requested_level_excludes_other_levels_and_recommendations():
    html = "<h2>详细面板</h2><table><tr><th>等级</th><th>攻击力</th></tr><tr><td>20级</td><td>100</td></tr><tr><td>90级</td><td>608</td></tr></table><h2>推荐角色</h2><p>人物甲适合此武器</p>"
    snippets, _, _meta = evidence(extract_sections(html, "武器"), "90级属性", 1500)
    text = str(snippets)
    assert "90级 | 608" in text
    assert "20级" not in text and "人物甲" not in text


def test_multilevel_table_keeps_ascension_subheaders():
    table = (
        "等级 | 攻击力 | 攻击力\n | 突破前 | 突破后\n20级 | 100 | 150\n90级 | 608 | "
    )
    result = project_level(table, "90级属性")
    assert "突破前 | 突破后" in result
    assert "90级" in result and "20级" not in result


def test_plain_book_disambiguation_is_not_tied_to_a_specific_title():
    related = []
    extract_sections(
        '<div>本条目介绍的是：道具<a href="/ys/虚构书（书籍）">阅读正文</a></div>',
        "虚构书",
        related,
    )
    assert related == [{"title": "虚构书（书籍）", "section": ""}]
