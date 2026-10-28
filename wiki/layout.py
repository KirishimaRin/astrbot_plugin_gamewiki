"""Plain-text layout that stays readable in chat clients without Markdown."""

import re

STAGE = re.compile(r"(?:\d+级|\d+\s*[→➜]\s*\d+)")


def material_lines(text: str) -> list[str]:
    pattern = r"(\d+(?:\.\d+)?(?:万|亿)?)\s+([^\d\s]+)"
    items = re.findall(pattern, text)
    if items and not re.sub(pattern, "", text).strip():
        return [f"{name} × {count}" for count, name in items]
    return [text]


def stage_blocks(rows: list[list[str]]) -> list[str]:
    """Transpose level/upgrade columns without pairing neighboring columns."""
    output, headers, values = [], [], []

    def flush():
        for heading, items in zip(headers, values):
            if STAGE.fullmatch(heading) and items:
                output.append("\n".join([heading, *items]))

    for row in rows:
        if (
            len(row) > 1
            and any(STAGE.fullmatch(v) for v in row)
            and all(STAGE.fullmatch(v) or v in {"", "/"} for v in row)
        ):
            flush()
            headers, values = row, [[] for _ in row]
        elif headers:
            # Ragged rows (short or long) still belong to their columns; pad
            # or truncate instead of dropping the whole row.
            row = list(row[: len(headers)]) + [""] * (len(headers) - len(row))
            for index, value in enumerate(row):
                if value and value != "/":
                    values[index].extend(material_lines(value))
    flush()
    return output


def paragraphs(text: str, width=90) -> list[str]:
    """Keep chapter labels separate, and group prose at sentence boundaries."""
    text = re.sub(r"\s*(【[^】\n]{1,60}】)\s*", r"\n\n\1\n\n", text)
    output = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"【[^】]+】", line):
            output.append(line)
            continue
        sentences = re.findall(r".+?(?:[。！？][”’」』]?|$)", line)
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > width:
                output.append(current)
                current = ""
            # Very long sentences may be broken at a clause, preserving punctuation.
            while len(sentence) > width + 30:
                stops = [sentence.rfind(p, width // 2, width + 1) for p in "，；、"]
                cut = max(stops) + 1
                if cut <= 0:
                    cut = width
                output.append(sentence[:cut])
                sentence = sentence[cut:]
            current += sentence
        if current:
            output.append(current)
    return output


def table_blocks(lines: list[str]) -> list[str]:
    """Render table values with their headers instead of ASCII column separators."""
    rows = [[cell.strip() for cell in line.split("|")] for line in lines]
    if any(
        len(row) > 1
        and any(STAGE.fullmatch(v) for v in row)
        and all(STAGE.fullmatch(v) or v in {"", "/"} for v in row)
        for row in rows
    ):
        return stage_blocks(rows)
    header = rows[0]
    if len(header) == 2 and re.fullmatch(r"LV\d+", header[1], re.I):
        fields = [f"{row[0]}：{row[1]}" for row in rows[1:] if len(row) == 2 and row[1]]
        return [f"{header[1]}\n" + "\n".join(fields)] if fields else []
    grid = (
        header[0] in {"等级", "详细属性", "属性", "阶段"}
        or ("稀有度" in header and any("名称" in h for h in header))
        or all(re.fullmatch(r"LV\d+", h, re.I) for h in header[1:])
    )
    if len(header) > 2 and grid:
        subheader = (
            rows[1]
            if len(rows) > 1
            and not rows[1][0]
            and any(v in {"突破前", "突破后", "基础值", "提升值"} for v in rows[1])
            else None
        )
        labels = list(header)
        if subheader:
            labels = [
                f"{h}（{subheader[i]}）" if i < len(subheader) and subheader[i] else h
                for i, h in enumerate(header)
            ]
        output = []
        name_column = next((i for i, name in enumerate(header) if "名称" in name), 0)
        for row in rows[2 if subheader else 1 :]:
            fields = [
                f"{labels[i]}：{value}"
                for i, value in enumerate(row)
                if value
                and i != name_column
                and i < len(labels)
                and labels[i] != "图标"
            ]
            if fields:
                label = (
                    row[name_column]
                    if header[0] in {"等级", "详细属性", "阶段"}
                    else f"{header[name_column]}：{row[name_column]}"
                )
                output.append("\n".join([label, *fields]))
        return output
    output, fields = [], []
    for row in rows:
        if len(row) > 2:
            pairs = (
                list(zip(row[::2], row[1::2]))
                if len(row) % 2 == 0
                else [(row[0], " / ".join(v for v in row[1:] if v))]
            )
            fields.extend(f"{key}：{value}" for key, value in pairs if value and key)
            continue
        if len(row) != 2 or not row[1] or not row[0]:
            continue
        key, value = row
        if key in {"描述", "介绍", "任务描述"} or len(value) > 90:
            if fields:
                output.append("\n".join(fields))
                fields = []
            prefix = "" if key in {"描述", "介绍", "任务描述"} else key + "："
            output.extend(paragraphs(prefix + value))
        else:
            fields.append(f"{key}：{value}")
    if fields:
        output.append("\n".join(fields))
    return output


def layout_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks, index = [], 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if "|" in line:
            table = []
            while index < len(lines) and "|" in lines[index]:
                table.append(lines[index])
                index += 1
            blocks.extend(table_blocks(table))
        elif re.fullmatch(r".{1,40} × [\d.万亿]+", line):
            materials = []
            while index < len(lines) and re.fullmatch(
                r".{1,40} × [\d.万亿]+", lines[index].strip()
            ):
                materials.append(lines[index].strip())
                index += 1
            blocks.append("\n".join(materials))
        elif (
            line in {"等级需求", "等级要求"}
            and index + 1 < len(lines)
            and lines[index + 1].strip().isdigit()
        ):
            blocks.append(f"{line}：{lines[index + 1].strip()}")
            index += 2
        elif line == "材料" and index + 1 < len(lines) and " × " in lines[index + 1]:
            index += 1
        else:
            group = []
            while index < len(lines):
                candidate = lines[index].strip()
                if (
                    not candidate
                    or len(candidate) > 28
                    or "|" in candidate
                    or " × " in candidate
                    or re.match(
                        r"【|精英阶段|总计|升级所需经验|等级需求|等级要求|材料$",
                        candidate,
                    )
                    or STAGE.fullmatch(candidate)
                ):
                    break
                group.append(candidate)
                index += 1
            if len(group) > 1:
                blocks.append("\n".join(group))
                continue
            if group:
                index -= 1
            materials = material_lines(line)
            blocks.extend(
                ["\n".join(materials)] if len(materials) > 1 else paragraphs(line)
            )
            index += 1
    return blocks


def excerpt(text: str, room: int) -> str:
    """Cut at a complete sentence or field, without leaving a half table value."""
    if len(text) <= room:
        return text
    if "\n" in text:
        kept = []
        for line in text.splitlines():
            if len("\n".join([*kept, line])) > room:
                break
            kept.append(line)
        if len(kept) > 1:
            return "\n".join(kept)
        return ""
    candidate = text[:room]
    stop = max(candidate.rfind(p) for p in "。！？")
    return candidate[: stop + 1] if stop >= room // 3 else candidate
