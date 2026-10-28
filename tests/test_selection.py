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
