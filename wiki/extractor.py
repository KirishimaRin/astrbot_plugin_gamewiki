"""Extract expanded template content, keeping table labels and hidden stories."""

import re
from urllib.parse import unquote, urlsplit

from bs4 import Comment, NavigableString, Tag

from .cleaning import clean_page, valid_line
from .models import Section
from .selection import evidence as evidence, project_level as project_level

SKILL_ORDER = ("普通攻击", "元素战技", "元素爆发")


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def classify_skill(name: str, seen: list, hint: str = "") -> str:
    """Anchor on explicit labels first; template order is only a fallback.

    Live BWIKI templates carry no kind label; the normal-attack icon is
    usually named 普通攻击图标·..., which is the one trustworthy signal.
    """
    for kind in SKILL_ORDER:
        if kind in name or (hint and kind in hint):
            if kind not in seen:
                seen.append(kind)
                return kind
            return "固有天赋"
    for kind in SKILL_ORDER:
        if kind not in seen:
            seen.append(kind)
            return kind
    return "固有天赋"


def cell_text(cell: Tag, noise: dict) -> str:
    # Material icons put the count ABOVE their label; pair these explicitly.
    for icon in list(cell.select(".ys-iconLarge")):
        label = icon.select_one(".ys-iconLBottom")
        count = icon.select_one(".ys-iconLTop")
        if label and count:
            icon.replace_with(
                f" {compact(label.get_text(' ', strip=True))} × "
                f"{compact(count.get_text(' ', strip=True))} "
            )
    for image in list(cell.find_all("img")):
        # An image-only item link may carry the only available material name.
        link = image.find_parent("a")
        label = str(image.get("alt", ""))
        if label and label in cell.get_text(" ", strip=True):
            image.decompose()
            noise["images"] = noise.get("images", 0) + 1
            continue
        stars = re.fullmatch(r"([1-5])星(?:\.png)?", label)
        if stars:
            image.replace_with(stars.group(1) + "星")
            continue
        if (
            link
            and not link.get_text(strip=True)
            and label
            and not re.search(r"\.(png|webp|gif|jpe?g)$", label, re.I)
        ):
            image.replace_with(f" {label} ")
        else:
            image.decompose()
            noise["images"] = noise.get("images", 0) + 1
    text = compact(cell.get_text(" ", strip=True))
    if len(text) <= 100 and not re.search(r"[。！？；]", text):
        text = re.sub(r"(?<!\S)([^\s|]{2,40})(?:\s+\1)+(?!\S)", r"\1", text)
    return "" if text in {"[[]]", "[]", "—", "-"} else text


def table_text(table: Tag, noise: dict) -> str:
    """Expand row/column spans into a bounded grid, preserving empty cells."""
    spans: dict[tuple[int, int], str] = {}
    rows = []
    for r, row in enumerate(
        tr for tr in table.find_all("tr") if tr.find_parent("table") is table
    ):
        if r >= 200:
            rows.append("[表格超过 200 行，后续省略]")
            break
        values, col = [], 0
        cells = row.find_all(["td", "th"], recursive=False)
        # Infobox key/value rows with no value are template placeholders, not facts.
        if len(cells) == 2 and cells[0].name == "th" and cells[1].name == "td":
            if not cell_text(cells[1], noise):
                noise["filtered"] = noise.get("filtered", 0) + 1
                continue
        if (
            len(cells) == 1
            and cells[0].name == "th"
            and compact(cells[0].get_text()) == "内容"
        ):
            noise["filtered"] = noise.get("filtered", 0) + 1
            continue
        for cell in cells:
            while (r, col) in spans:
                values.append(spans.pop((r, col)))
                col += 1
            text = cell_text(cell, noise)
            try:
                rowspan = max(1, min(200, int(str(cell.get("rowspan", 1)))))
                colspan = max(1, min(40, int(str(cell.get("colspan", 1)))))
            except ValueError:
                rowspan = colspan = 1
            for dc in range(colspan):
                if col + dc >= 40:
                    break
                values.append(text)
                for dr in range(1, rowspan):
                    spans[(r + dr, col + dc)] = text
            col += colspan
        while (r, col) in spans:
            values.append(spans.pop((r, col)))
            col += 1
        if any(values) and valid_line(" | ".join(values)):
            rows.append(values[0] if len(set(values)) == 1 else " | ".join(values))
        elif any(values):
            noise["filtered"] = noise.get("filtered", 0) + 1
    return "\n".join(rows)


def first_image(soup, title: str = "") -> str:
    """Prefer the entry's own portrait over rarity strips and interface icons."""
    chosen, best = "", -1
    for img in soup.select("img[src]"):
        src = str(img.get("src", ""))
        if src.startswith("//"):
            src = "https:" + src
        try:
            url = urlsplit(src)
        except ValueError:
            continue
        if url.scheme not in {"http", "https"} or not url.netloc:
            continue
        path = unquote(url.path)
        if re.search(r"\.(gif|svg)$", path, re.I):
            continue
        link = img.find_parent("a")
        label = " ".join(
            (str(img.get("alt", "")), str(link.get("title", "")) if link else "", path)
        )
        if re.search(
            r"图标|头像|徽标|星级|稀有度|(?:[1-6一二三四五六]星)\.(?:png|webp|jpe?g)|"
            r"(?:^|[/\s_-])(?:icon|logo|rarity|stars?)(?:[\s_.\d/-]|$)",
            label,
            re.I,
        ):
            continue
        subject = bool(title and title in label)
        portrait = bool(
            re.search(
                r"立绘|立画|角色卡|全身像|portrait|splash|gacha|(?:^|[\s/_])pack[\s_]|\bskin\b",
                label,
                re.I,
            )
        )
        rank = 3 if subject and portrait else 2 if subject else 1 if portrait else 0
        if not portrait:
            try:
                width, height = int(img.get("width", 0)), int(img.get("height", 0))
            except (ValueError, TypeError):
                width = height = 0
            if (width and width <= 64) or (height and height <= 64):
                continue
            if width and height and width / height >= 4:
                continue
        if rank <= best:
            continue
        if "/thumb/" in src:
            src = re.sub(r"/\d+px-", "/640px-", src)
        chosen, best = src, rank
    return chosen


def extract_sections(
    html: str,
    title: str,
    related: list | None = None,
    noise: dict | None = None,
    prefix: str = "ys",
    meta: dict | None = None,
    source: str = "bwiki",
) -> list[Section]:
    if noise is None:
        noise = {}
    soup = clean_page(html, title, related, noise, prefix, source)
    if meta is not None:
        # Table extraction removes images; capture the portrait before traversal.
        meta["image_url"] = first_image(soup, title)
    # Bind site material widgets before generic div traversal separates their labels.
    for container, label_selector, count_selector in [
        (".itembox", ".itemNOname", ".itemattr"),
        (".ys-iconLarge", ".ys-iconLBottom", ".ys-iconLTop"),
    ]:
        for item in list(soup.select(container)):
            if item.attrs is None:
                continue
            label, count = (
                item.select_one(label_selector),
                item.select_one(count_selector),
            )
            if label and count:
                text = f"{compact(label.get_text(' ', strip=True))} × {compact(count.get_text(' ', strip=True))}"
                node = soup.new_tag("p")
                node.string = text
                item.replace_with(node)
    sections = [Section("概览", "")]
    path: dict[int, str] = {}
    buffer: list[str] = []
    seen: list = []

    def flush():
        text = compact("".join(buffer))
        buffer.clear()
        if not text or text in sections[-1].blocks[-1:]:
            return
        if valid_line(text) and not text.startswith("请上传文件"):
            sections[-1].blocks.append(text)
        else:
            noise["filtered"] = noise.get("filtered", 0) + 1

    def walk(node):
        nonlocal seen
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            buffer.append(str(node))
            return
        if not isinstance(node, Tag):
            return
        if node.name == "img":
            return
        if (
            node.name == "div"
            and set(node.get("class", [])) & {"title", "card-title3"}
            and compact(node.get_text(" ", strip=True))
            in {
                "基础属性",
                "获取方式",
                "获取途径",
                "武器介绍",
                "武器类型",
                "卡池信息",
                "圣遗物故事",
                "推荐角色",
                "精炼材料",
                "武器TAG",
                "实装版本",
            }
        ):
            flush()
            sections.append(Section(compact(node.get_text(" ", strip=True)), ""))
            return
        if node.name in {"h2", "h3", "h4", "h5", "h6"}:
            flush()
            level = int(node.name[1])
            heading = compact(node.get_text(" ", strip=True))
            if heading == "天赋":
                seen = []
            path[level] = heading
            for key in list(path):
                if key > level:
                    del path[key]
            anchor_node = node.select_one(".mw-headline[id]") or node.find(id=True)
            anchor = str(anchor_node.get("id", "")) if anchor_node else heading
            sections.append(Section(" / ".join(path.values()), anchor))
            return
        if "r-skill-title-1" in node.get("class", []):
            flush()
            skill = compact(node.get_text(" ", strip=True))
            hint = ""
            icon = node.select_one("img[src]")
            if icon:
                hint = (
                    unquote(str(icon.get("src", ""))) + " " + str(icon.get("alt", ""))
                )
            kind = classify_skill(skill, seen, hint)
            sections.append(Section(f"天赋 / {kind} / {skill}", "天赋"))
            return
        if node.name == "table":
            flush()
            text = table_text(node, noise)
            if text:
                sections[-1].blocks.append(text)
            return
        if node.name in {"br", "hr"}:
            flush()
            return
        if node.name in {"p", "div", "li", "ul", "ol", "dl"}:
            flush()
        for child in list(node.children):
            walk(child)
        if node.name in {"p", "div", "li", "ul", "ol", "dl"}:
            flush()

    walk(soup.select_one(".mw-parser-output") or soup)
    flush()
    return [s for s in sections if s.blocks and s.title != "目录"]
