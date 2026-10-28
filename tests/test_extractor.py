from pathlib import Path

from wiki.extractor import evidence, extract_sections, project_level


def test_hidden_template_story_is_preserved():
    html = '<div class="mw-parser-output"><div id="toc">目录噪声</div><h2><span class="mw-headline" id="角色故事">角色故事</span></h2><table><tr><th>故事1</th></tr><tr><td style="display:none">隐藏故事原文</td></tr></table></div>'
    result = extract_sections(html, "角色")
    assert len(result) == 1
    assert "隐藏故事原文" in result[0].blocks[0]
    assert result[0].anchor == "角色故事"
    assert "目录噪声" not in str(result)


def test_table_spans_material_count_and_empty_column():
    html = """<h2>突破</h2><table><tr><th rowspan="2">阶段</th><th colspan="2">材料</th></tr><tr><td>LV1</td><td>LV2</td></tr><tr><td>20</td><td><div class="ys-iconLarge"><div class="ys-iconLTop">3</div><div class="ys-iconLBottom">劫波莲</div></div></td><td></td></tr></table>"""
    text = extract_sections(html, "角色")[0].blocks[0]
    assert "阶段 | 材料 | 材料" in text
    assert "阶段 | LV1 | LV2" in text
    assert "20 | 劫波莲 × 3 | " in text


def test_requested_level_is_bound_to_its_header():
    text = "详细属性 | LV1 | LV2 | LV10\n点按伤害 | 98.4% | 105.8% | 177.1%"
    assert project_level(text, "10级倍率") == "详细属性 | LV10\n点按伤害 | 177.1%"
    assert project_level(text, "LV2") == "详细属性 | LV2\n点按伤害 | 105.8%"
    assert project_level(text, "材料") == text


def test_character_fixture_material_and_talent_ranking():
    html = (Path(__file__).parent / "fixtures/character.html").read_text(
        encoding="utf-8"
    )
    sections = extract_sections(html, "纳西妲")
    snippets, _, _meta = evidence(sections, "突破材料总量", 4000)
    assert snippets[0]["section"] == "突破"
    assert "劫波莲 × 168" in snippets[0]["text"]
    snippets, _, _meta = evidence(sections, "元素战技10级倍率", 4000)
    assert "所闻遍计" in snippets[0]["section"]
    assert "点按伤害 | 177.1%" in snippets[0]["text"]
    assert "LV10" in snippets[0]["text"]
    assert "LV1 |" not in snippets[0]["text"]


def test_budget_and_specific_section():
    html = (
        "<h2>故事</h2><p>"
        + "关于神明的故事。" * 1000
        + "</p><h2>技能</h2><p>技能数值</p>"
    )
    sections = extract_sections(html, "角色")
    snippets, truncated, meta = evidence(sections, "神明", 1000, "故事")
    assert sum(len(s["text"]) for s in snippets) <= 1000
    assert truncated
    assert meta["mode"] == "section"
    snippets, truncated, meta = evidence(sections, "", 1000, "不存在")
    assert (snippets, truncated) == ([], False)
    assert meta["mode"] == "section"


def test_parser_comments_notices_and_empty_metadata_are_filtered():
    html = """<div class="mw-parser-output">
    <!-- NewPP limit report Cached time: 123 CPU time usage: 0.05 -->
    <div>本条目介绍的是：<b>任务道具</b><div><a href="/ys/合集#测试书">同名书</a></div></div>
    <div>首页 &gt; 任务道具一览 &gt; 测试书</div>
    <div class="bg-snm">如果是第一次来，按"Ctrl+D"可以收藏<br>按右上角“WIKI功能→编辑”</div>
    <table><tr><th colspan="2">测试书</th></tr>
    <tr><td colspan="2"><a href="/ys/文件:测试书.png"><img alt="测试书.png"></a></td></tr>
    <tr><th>描述</th><td>应保留的内容。</td></tr>
    <tr><th>获取方式</th><td></td></tr>
    <tr><th>相关活动</th><td>[[]]</td></tr></table>
    <h2>角色故事</h2><p style="display:none">应保留的折叠故事。</p>
    <!-- Saved in parser cache. Serialized with PHP. -->
    </div>"""
    related = []
    sections = extract_sections(html, "测试书", related)
    text = str(sections)
    assert "应保留的内容" in text
    assert "应保留的折叠故事" in text
    assert related == [{"title": "合集", "section": "测试书"}]
    for noise in (
        "NewPP",
        "Cached time",
        "Ctrl+D",
        "首页",
        "[[]]",
        ".png",
        "获取方式",
        "相关活动",
        "Serialized",
        "本条目介绍",
    ):
        assert noise not in text


def test_related_target_only_accepts_local_exact_chapter():
    related = []
    extract_sections(
        """<div>本条目介绍的是：道具
    <a href="https://evil.example/ys/合集#测试书">外站</a>
    <a href="/ys/合集#另一本书">其他书</a>
    <a href="/ys/合集#测试书">正文</a></div>""",
        "测试书",
        related,
    )
    assert related == [{"title": "合集", "section": "测试书"}]


def test_skill_kind_anchors_on_text_icon_then_order():
    html = (
        "<h2>天赋</h2>"
        '<div class="r-skill-title-1"><img src="/30px-%E6%99%AE%E9%80%9A%E6%94%BB%E5%87%BB%E5%9B%BE%E6%A0%87%C2%B7%E6%B3%95%E5%99%A8.png" alt="行相"></div><p>描述一。</p>'
        '<div class="r-skill-title-1">所闻遍计</div><p>描述二。</p>'
        '<div class="r-skill-title-1">心景幻成</div><p>描述三。</p>'
        '<div class="r-skill-title-1">净善摄受明论</div><p>描述四。</p>'
        '<div class="r-skill-title-1">普通攻击强化</div><p>描述五。</p>'
    )
    kinds = [s.title.split(" / ")[1] for s in extract_sections(html, "角色")]
    assert kinds == ["普通攻击", "元素战技", "元素爆发", "固有天赋", "固有天赋"]


def test_skill_kind_prefers_explicit_title_over_position():
    from wiki.extractor import classify_skill

    seen = []
    assert classify_skill("元素战技·演示", seen) == "元素战技"
    assert classify_skill("神里流·霜灭", seen) == "普通攻击"
    assert classify_skill("普通攻击强化", seen) == "固有天赋"


def test_cleaning_noise_counters_are_reported():
    html = (
        '<div class="mw-parser-output">'
        "<!-- NewPP limit report -->"
        '<nav id="toc">目录</nav>'
        "<div>本条目介绍的是：道具<a href='/ys/合集#测试书'>正文</a></div>"
        "<table><tr><th>描述</th><td>保留内容。</td></tr>"
        "<tr><th>空字段</th><td></td></tr></table>"
        '<table><tr><td><img src="/x.png" alt="x.png"></td></tr></table>'
        "</div>"
    )
    related, noise = [], {}
    extract_sections(html, "测试书", related, noise)
    assert noise["comments"] == 1
    assert noise["notices"] == 1
    assert noise["structural"] >= 1
    assert noise["filtered"] >= 1
    assert noise["images"] == 1
