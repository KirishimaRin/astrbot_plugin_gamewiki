"""Present a short, readable excerpt instead of dumping retrieval internals."""

import re

from .layout import excerpt, layout_blocks


def source_links(result: dict) -> list[str]:
    urls = [item.get("url") for item in result.get("evidence", [])]
    return list(dict.fromkeys([u for u in urls if u] or [result["url"]]))[:2]


def _compare_metrics_text(metrics: dict) -> str:
    parts = []
    if metrics.get("win_rate") is not None:
        parts.append(f"胜率 {metrics['win_rate']}%")
    if metrics.get("share") is not None:
        parts.append(f"占比 {metrics['share']}%")
    if metrics.get("picks") is not None:
        parts.append(f"选取 {metrics['picks']} 次")
    if metrics.get("runs") is not None:
        parts.append(f"{metrics['runs']} 局")
    if metrics.get("score") is not None:
        parts.append(f"评分 {metrics['score']}")
    return "，".join(parts)


def format_compare(result: dict) -> str:
    """Render the deterministic B-layer comparison; C narrative is appended by the caller."""
    status = result.get("status")
    if status == "compare":
        left, right = result.get("left", {}), result.get("right", {})
        lines = [f"【对比】{left.get('title')} vs {right.get('title')}", ""]
        for dimension in result.get("dimensions", []):
            lines.append(
                f"{dimension['label']}：{dimension['left']} ｜ {dimension['right']}"
            )
        left_metrics = _compare_metrics_text(left.get("metrics") or {})
        right_metrics = _compare_metrics_text(right.get("metrics") or {})
        if left_metrics or right_metrics:
            lines.append("")
            lines.append(
                f"社区数据：{left.get('title')} {left_metrics or '—'}；{right.get('title')} {right_metrics or '—'}"
            )
        lines.append("")
        lines.append("来源：\n" + "\n".join(result.get("source_urls", [])))
        return "\n".join(lines)
    if status == "compare_unsupported":
        left, right = result.get("left", {}), result.get("right", {})

        def line(side):
            title = side.get("title", "")
            summary = side.get("summary")
            if summary:
                return f"{title}：{summary}\n{side.get('url', '')}"
            return f"{title}：{side.get('url', '')}"

        return (
            f"{result.get('message', '这两个条目不能直接比较。')}\n\n"
            f"{line(left)}\n\n{line(right)}"
        )
    if status == "compare_unavailable":
        left, right = result.get("left", {}), result.get("right", {})
        queries = [
            item.get("query")
            for item in (left, right)
            if isinstance(item, dict) and item.get("query")
        ]
        suffix = ""
        if len(queries) == 2:
            suffix = "\n\n请分开查询：" + "、".join(
                f"/sts2 {query}" for query in queries
            )
        return result.get("message", "对比失败，请先分别确认条目名称。") + suffix
    return result.get("message", "对比失败。")


def format_command(
    result: dict, limit=1200, brief=350, detailed=750, excerpt_label=False
):
    if result["status"] in {"error", "not_found"}:
        return result["message"]
    if result["status"] == "needs_choice":
        query = result.get("query", "")
        choices = "\n\n".join(
            "\n".join(
                filter(
                    None,
                    (
                        f"{index}. {item['title']}",
                        item.get("snippet", "")[:60],
                        item["url"],
                    ),
                )
            )
            for index, item in enumerate(result["candidates"][:5], 1)
        )
        intro = result.get("choice_intro") or (
            f"没有与「{query}」同名的条目，以下是搜索到的相关条目，"
            "请确认后使用完整名称重新查询："
        )
        reply = intro + "\n\n" + choices
        if result.get("suggestion_used"):
            reply += (
                f"\n\n已尝试纠错关键词「{result['suggestion_used']}」，请确认目标条目。"
            )
        if result.get("hint"):
            reply += "\n\n" + result["hint"]
        if result.get("command"):
            reply += f"\n\n2分钟内回复编号，或发送 /{result['command']} 编号选择条目。"
        return reply
    title = result.get("display_title", result["title"])
    source = "来源：\n" + "\n".join(source_links(result))
    header = f"【{title}】"
    if excerpt_label:
        header += "\n\n原文摘录"
    query = result.get("query")
    normalized = result.get("normalized_query")
    if (
        query
        and normalized
        and query != normalized
        and not normalized.startswith("卡牌：")
    ):
        header += f"（{query} → {normalized}）"
    question = result.get("question", "")
    budget = min(
        detailed if question and question != query else brief,
        limit - len(header) - len(source) - 160,
    )
    blocks, titles, used = [], {title, result["title"]}, 0
    shortened = False
    for item in result.get("evidence", [])[:2]:
        clean = []
        for line in item["text"].splitlines():
            line = line.strip()
            if not line or line in titles:
                continue
            clean.append(line)
        arranged = layout_blocks("\n".join(clean))
        selected = []
        for index, block in enumerate(arranged):
            room = budget - used
            if room <= 0:
                shortened = True
                break
            if re.fullmatch(r"【[^】]+】", block) and index + 1 < len(arranged):
                next_block = arranged[index + 1]
                first_sentence = re.split(r"(?<=[。！？])", next_block, maxsplit=1)[0]
                if len(block) + len(first_sentence) + 2 > room:
                    shortened = True
                    break
            if len(block) > room:
                block = excerpt(block, room)
                shortened = True
            if block:
                selected.append(block)
                used += len(block) + 2
            if shortened:
                break
        if selected:
            heading = item["section"]
            redundant = {
                "概览",
                title,
                "基本信息",
                "基础属性",
                "介绍",
                "简介",
                "详细面板",
            }
            heading = "·".join(heading.split(" / ")[-2:])
            label = "" if heading in redundant else f"【{heading}】\n"
            blocks.append(label + "\n\n".join(selected))
        if shortened:
            break
    if not blocks:
        hint = "、".join(result.get("available_sections", [])[:6])
        text = "此条目没有可展示的正文"
        if hint:
            text += f"，可尝试指定分节：{hint}"
        blocks.append(text + "，请查看来源页面。")
    else:
        omitted = (result.get("selection") or {}).get("omitted_sections", 0)
        if omitted:
            blocks[-1] += f"\n…（另有 {omitted} 个相关分节未展示）"
    if shortened and not blocks[-1].startswith("此条目没有可展示的正文"):
        blocks[-1] += "\n…（节选）"
    return "\n\n".join([header, *blocks, source])
