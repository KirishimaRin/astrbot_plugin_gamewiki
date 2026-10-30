"""Regression tests for evidence selection semantics."""

from wiki.extractor import extract_sections
from wiki.selection import LEVEL_HEADER, evidence, project_level


def _page(*sections):
    parts = [
        f'<h2><span class="mw-headline" id="{title}">{title}</span></h2>{body}'
        for title, body in sections
    ]
    return extract_sections(
        '<div class="mw-parser-output">' + "".join(parts) + "</div>", "条目"
    )


def test_zero_score_question_falls_back_to_best_section():
    sections = _page(("突破", "<p>突破需要材料。</p>"), ("故事", "<p>身世背景。</p>"))
    # No word overlaps the page at all; the old rule returned nothing.
    snippets, truncated, meta = evidence(sections, "这个角色怎么养成", 4000)
    assert snippets, "fallback must keep the best section available"
    assert meta["mode"] == "fallback"
    assert not truncated


def test_duplicate_section_titles_are_only_evidence_once():
    # BWIKI templates emit some headings twice; repeats must not burn budget.
    sections = _page(
        ("技能", "<p>技能等级说明一。</p>"),
        ("技能", "<p>技能等级说明二。</p>"),
        ("故事", "<p>身世。</p>"),
    )
    snippets, _, _ = evidence(sections, "技能", 4000)
    titles = [item["section"] for item in snippets]
    assert titles.count("技能") == 1


def test_focused_mode_keeps_budget_signal_clean():
    sections = _page(
        ("突破", "<p>突破材料列表。</p>"),
        ("角色故事", "<p>" + "身世。" * 30 + "</p>"),
        ("语音", "<p>" + "台词。" * 30 + "</p>"),
        ("名字来历", "<p>" + "来历。" * 30 + "</p>"),
    )
    snippets, truncated, meta = evidence(sections, "突破材料", 4000)
    assert snippets[0]["section"] == "突破"
    assert not truncated, "budget was never exhausted; truncation must stay false"
    assert meta["mode"] == "focused"
    assert meta["omitted_sections"] == 0, "irrelevant sections are dropped, not omitted"


def test_relevant_sections_beyond_three_are_disclosed_as_omitted():
    sections = _page(
        ("突破", "<p>突破材料一。</p>"),
        ("突破 / 汇总", "<p>突破材料二。</p>"),
        ("突破 / 备注", "<p>突破材料三。</p>"),
        ("突破 / 补充", "<p>突破材料四。</p>"),
    )
    _, truncated, meta = evidence(sections, "突破材料", 4000)
    assert meta["omitted_sections"] == 1
    assert not truncated


def test_intro_mode_meta():
    sections = _page(("介绍", "<p>基本说明。</p>"), ("角色故事", "<p>故事。</p>"))
    snippets, _, meta = evidence(sections, "", 4000, page_title="条目")
    assert meta["mode"] == "intro"
    assert "基本说明" in snippets[0]["text"]


def test_level_header_matches_whole_tokens():
    assert LEVEL_HEADER.search("等级 | 20级")
    assert LEVEL_HEADER.search("详细属性 | LV1 | LV2")
    assert not LEVEL_HEADER.search("详细属性 | LV10 | LV20")


def test_bare_level_without_context_is_not_projected():
    table = "等级 | 攻击力\n20级 | 100\n90级 | 608"
    assert project_level(table, "4级材料") == table
    assert "90级 | 608" in project_level(table, "90级属性")
    assert "90级 | 608" in project_level(table, "LV90")


def test_max_level_projects_the_table_s_own_highest_level():
    columns = "详细属性 | LV1 | LV10\n点按伤害 | 105.8% | 177.1%"
    assert project_level(columns, "满级伤害") == "详细属性 | LV10\n点按伤害 | 177.1%"
    rows = "等级 | 攻击力\n20级 | 100\n90级 | 608"
    assert "90级 | 608" in project_level(rows, "满级属性")
    # No level column to resolve against: keep the table intact.
    plain = "介绍 | 一些材料说明\n获取 | 采集"
    assert project_level(plain, "满级材料") == plain


def test_truncated_true_only_when_budget_cuts_content():
    sections = _page(("故事", "<p>" + "关于神明的故事。" * 400 + "</p>"))
    _, truncated, meta = evidence(sections, "神明", 1000)
    assert truncated
    assert meta["mode"] == "focused"


def test_empty_sections_do_not_crash_focused_lookup():
    # A page whose every block was filtered leaves zero sections; a focused
    # question must return an empty result, not raise IndexError.
    snippets, truncated, meta = evidence([], "突破材料", 4000)
    assert (snippets, truncated) == ([], False)
    assert meta["mode"] == "empty"


def test_refine_rank_projects_inline_rank_lists():
    # 真实 BWIKI 原神武器页没有精炼分节或精炼表：各精炼档数值以斜杠
    # 列表内联在条目首段武器技能里。精炼N/精N 投影保留每档列表的第N项。
    block = (
        "武器技能 - 无羁的朱赤之蝶\n"
        "生命值提升20%/25%/30%/35%/40%。此外，提供0.8%/1%/1.2%/1.4%/1.6%的攻击力加成。"
    )
    assert (
        project_level(block, "护摩之杖精炼5效果")
        == "武器技能 - 无羁的朱赤之蝶\n生命值提升40%。此外，提供1.6%的攻击力加成。"
    )
    assert project_level("生命值提升20%/25%/30%/35%/40%", "精2") == "生命值提升25%"
    # 档数不是 5 的斜杠列表（日期、成对数值）原样保留。
    dates = "祈愿 - 2024/10/29 18:00 ~ 2024/11/19 14:59"
    assert project_level(dates, "精炼3") == dates
    pair = "攻击力 46-608 / 暴击伤害 14.4%-66.2%"
    assert project_level(pair, "精炼1") == pair


def test_refine_question_selects_the_weapon_intro_with_rank_values():
    from wiki.games import PROFILES
    from wiki.models import Section

    sections = [
        Section(
            "护摩之杖",
            "intro",
            [
                "武器技能 - 无羁的朱赤之蝶",
                "生命值提升20%/25%/30%/35%/40%。此外，提供0.8%/1%/1.2%/1.4%/1.6%的攻击力加成。",
            ],
        ),
        Section(
            "详细面板", "panel", ["等级 | 基础攻击力 | 暴击伤害\n90级 | 608 | 66.2%"]
        ),
        Section("突破材料", "mat", ["漆黑陨铁的一粒 × 5"]),
        Section("故事", "story", ["武器故事。"]),
    ]
    for question in ("护摩之杖精炼5效果", "护摩之杖精5效果"):
        snippets, _, meta = evidence(
            sections, question, 3000, "", "护摩之杖", (), PROFILES["ys"].specifics
        )
        assert [s["section"] for s in snippets] == ["护摩之杖"], question
        assert meta["mode"] != "fallback", question
        assert "40%" in snippets[0]["text"] and "1.6%" in snippets[0]["text"], question
        assert "25%" not in snippets[0]["text"] and "0.8%" not in snippets[0]["text"]


def test_pool_intents_do_not_disable_acquisition_fields():
    """A generic pool trigger (当前/有什么) must not count as a second intent."""
    from wiki.games import PROFILES, YS_SPECIFICS
    from wiki.models import Section

    sections = [
        Section("简介", "intro", ["胡桃是往生堂七十七代堂主。"]),
        Section(
            "基本信息",
            "basic",
            [
                "名称 | 胡桃\n来源 | 祈愿\n获取 | 活动祈愿\n出现地点 | 璃月\n"
                "中文CV | 陶典\n生日 | 7月15日"
            ],
        ),
    ]
    # 归一后“现在”变“当前”，命中 pool intents 行；该行标题不在此页，
    # 不应因此清空获取类字段过滤。
    for question in ("胡桃现在怎么获得", "胡桃有什么获取途径"):
        snippets, _, meta = evidence(
            sections, question, 3000, "", "胡桃", PROFILES["ys"].intents, YS_SPECIFICS
        )
        assert snippets, question
        text = snippets[0]["text"]
        assert "中文CV" not in text and "生日" not in text, question
        assert "获取 | 活动祈愿" in text, question
