"""Normalize observed PRTS structures without executing page JavaScript."""

import hashlib
import json
import re
from urllib.parse import quote


def prepare_prts(soup, title):
    # Desktop and mobile tables duplicate facts; keep the desktop variant.
    for node in list(soup.select(".nodesktop, #calc, .charinfo-tooltip, .ak-tabs")):
        node.decompose()
    for cell in soup.select("table.nomobile [colspan]"):
        del cell["colspan"]
    for item in list(soup.select(".prts-item-icon")):
        link = item.select_one("a[title]")
        count = item.select_one("[class*='prts-item-quantity-label']")
        if link and count:
            item.replace_with(f" {link['title']} × {count.get_text(' ', strip=True)} ")

    for table in list(soup.select("table.itemInfo")):
        info = soup.new_tag("div")
        for image in list(table.find_all("img")):
            info.append(image.extract())
        pending = ""
        for row in table.find_all("tr"):
            headers = row.find_all("th", recursive=False)
            cells = row.find_all("td", recursive=False)
            if headers:
                pending = "、".join(h.get_text(" ", strip=True) for h in headers)
            value = " ".join(c.get_text(" ", strip=True) for c in cells).strip()
            if pending and value:
                paragraph = soup.new_tag("p")
                paragraph.string = f"{pending}：{value}"
                info.append(paragraph)
                pending = ""
        table.replace_with(info)

    wrapper = soup.select_one(".charinfo-container")
    if wrapper is None:
        return
    fields = {}
    for script in soup.find_all("script"):
        match = re.search(r"\bvar\s+char_info\s*=\s*\{", script.get_text())
        if not match:
            continue
        # Read only known scalar fields before cv; never evaluate script code.
        head = script.get_text()[match.end() :].split('"cv"', 1)[0][:4000]
        for key, value in re.findall(
            r'"(name|nameEn|star|group|class|branch|pos|tag|painter)"\s*:\s*("(?:\\.|[^"\\])*"|\d+)',
            head,
        ):
            fields[key] = json.loads(value)
        break
    replacement = soup.new_tag("div")
    if fields.get("name") == title:
        labels = {
            "name": "干员",
            "nameEn": "英文名",
            "group": "阵营",
            "class": "职业",
            "branch": "分支",
            "pos": "位置",
            "tag": "标签",
            "painter": "画师",
        }
        for key, label in labels.items():
            if fields.get(key):
                p = soup.new_tag("p")
                p.string = f"{label}：{fields[key]}"
                replacement.append(p)
        if isinstance(fields.get("star"), int):
            p = soup.new_tag("p")
            p.string = f"星级：{fields['star'] + 1}星"
            replacement.append(p)
        # PRTS's own charinfo script constructs its default portrait this way.
        stage = 2 if title in {"阿米娅(近卫)", "阿米娅(医疗)"} else 1
        filename = f"立绘_{title}_{stage}.png".replace(" ", "_")
        digest = hashlib.md5(filename.encode()).hexdigest()
        image = soup.new_tag(
            "img",
            src=f"https://media.prts.wiki/{digest[0]}/{digest[:2]}/{quote(filename)}",
        )
        image["alt"] = filename
        replacement.append(image)
    wrapper.replace_with(replacement)

    info = next(
        (h for h in soup.find_all("h2") if h.get_text(strip=True) == "干员信息"), None
    )
    if info:
        info.clear()
        info.string = "基本信息"
        info.append(soup.new_tag("span", id="干员信息"))

    # Preserve skill boundaries so later skills do not disappear behind skill 1.
    heading = next(
        (h for h in soup.find_all("h2") if h.get_text(strip=True) == "技能"), None
    )
    if heading:
        container = (
            heading.parent
            if "mw-heading" in heading.parent.get("class", [])
            else heading
        )
        index = 0
        for node in list(container.next_siblings):
            if getattr(node, "name", None) and (node.name == "h2" or node.find("h2")):
                break
            if getattr(node, "name", None) == "table" and "nomobile" in node.get(
                "class", []
            ):
                index += 1
                label = soup.new_tag("h3")
                label.string = f"技能{index}"
                # Link to the real parent heading, not a synthesized anchor.
                anchor = soup.new_tag("span", id=heading.get("id", "技能"))
                label.append(anchor)
                node.insert_before(label)
