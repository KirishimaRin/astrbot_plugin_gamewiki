from wiki.formatter import format_command


def test_command_is_short_and_does_not_dump_candidates():
    result = {
        "status": "ok",
        "title": "测试书",
        "query": "测试书",
        "question": "测试书",
        "normalized_query": "测试书",
        "url": "https://wiki.biligame.com/ys/测试书",
        "evidence": [{"section": "测试书", "text": "正文第一句。" * 300}],
        "candidates": [{"title": "无关条目"}] * 4,
    }
    text = format_command(result)
    assert len(text) < 800
    assert "正文第一句" in text
    assert "来源：" in text
    assert "无关条目" not in text
    assert "缩小范围" not in text
    assert "节选" in text


def test_short_metadata_is_presented_without_empty_values():
    result = {
        "status": "ok",
        "title": "测试书",
        "url": "https://wiki.biligame.com/ys/测试书",
        "evidence": [{"section": "概览", "text": "测试书\n描述 | 正文\n版本 | "}],
    }
    text = format_command(result)
    assert "\n\n正文\n\n" in text
    assert "版本" not in text


def test_empty_evidence_suggests_available_sections():
    result = {
        "status": "section_not_found",
        "title": "测试书",
        "url": "https://wiki.biligame.com/ys/测试书",
        "evidence": [],
        "available_sections": ["突破", "角色故事", "天赋"],
    }
    text = format_command(result)
    assert "可尝试指定分节：突破、角色故事、天赋" in text


def test_omitted_sections_are_disclosed():
    result = {
        "status": "ok",
        "title": "测试书",
        "url": "https://wiki.biligame.com/ys/测试书",
        "evidence": [{"section": "突破", "text": "正文。"}],
        "selection": {"omitted_sections": 2},
    }
    text = format_command(result)
    assert "另有 2 个相关分节未展示" in text


def test_reply_budgets_are_configurable():
    result = {
        "status": "ok",
        "title": "测试书",
        "query": "测试书",
        "question": "这本书讲了什么",
        "url": "https://wiki.biligame.com/ys/测试书",
        "evidence": [{"section": "突破", "text": "这是一段足够长的正文。" * 200}],
    }
    short = format_command(result, brief=60, detailed=60)
    long = format_command(result, brief=60, detailed=1200)
    assert len(short) < len(long)
    assert "来源：" in short and "来源：" in long


def test_prose_has_separate_title_chapters_paragraphs_and_source():
    result = {
        "status": "ok",
        "title": "示例书",
        "url": "https://wiki.biligame.com/ys/示例书",
        "evidence": [
            {
                "section": "示例书",
                "text": "这是介绍。【第一章】这是第一段。【第二章】这是第二段。",
            }
        ],
    }
    text = format_command(result)
    assert text.startswith("【示例书】\n\n这是介绍。")
    assert "\n\n【第一章】\n\n这是第一段。" in text
    assert "\n\n【第二章】\n\n这是第二段。" in text
    assert text.endswith("\n\n来源：\nhttps://wiki.biligame.com/ys/示例书")


def test_long_sentences_are_grouped_into_readable_paragraphs():
    from wiki.layout import paragraphs

    original = "一段较长的文本，" * 35 + "结尾。"
    parts = paragraphs(original)
    assert len(parts) > 2
    assert all(len(p) <= 120 for p in parts)
    assert "".join(parts) == original


def test_talent_table_keeps_level_and_field_labels():
    result = {
        "status": "ok",
        "title": "示例角色",
        "url": "https://wiki.biligame.com/ys/示例角色",
        "evidence": [
            {
                "section": "元素战技",
                "text": "详细属性 | LV10\n伤害 | 177.1%\n冷却 | 6秒",
            }
        ],
    }
    text = format_command(result)
    assert "LV10\n伤害：177.1%\n冷却：6秒" in text
    assert "|" not in text


def test_stat_table_keeps_ascension_context_and_zero_values():
    from wiki.layout import table_blocks

    blocks = table_blocks(
        [
            "等级 | 攻击力 | 攻击力 | 暴击伤害",
            " | 突破前 | 突破后 | ",
            "90级 | 608 |  | 66.2%",
            "1级 | 0 | 46 | 0%",
        ]
    )
    assert "90级\n攻击力（突破前）：608\n暴击伤害：66.2%" in blocks
    assert "攻击力（突破前）：0" in blocks[1]
    assert "攻击力（突破后）：46" in blocks[1]


def test_multi_pair_metadata_is_not_mistaken_for_table_headers():
    from wiki.layout import table_blocks

    assert table_blocks(["元素属性 | 岩 | 攻击属性 | 火"]) == [
        "元素属性：岩\n攻击属性：火"
    ]


def test_truncating_fields_does_not_cut_half_a_value():
    from wiki.layout import excerpt

    assert excerpt("90级\n攻击力：608\n暴击伤害：66.2%", 18) == "90级\n攻击力：608"
