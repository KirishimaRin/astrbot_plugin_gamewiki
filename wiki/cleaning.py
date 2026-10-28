"""Shared template-neutral cleaning for every content category."""

import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Comment

from .prts import prepare_prts

EMPTY = {"", "[]", "[[]]", "—", "-", "~", "null", "undefined", "None"}
UI_LABELS = {
    "折叠",
    "展开",
    "点击展开",
    "点击查看",
    "初始外观",
    "突破2阶后",
    "查看全部",
    "回到顶部",
    "回到目录",
    "回到顶部 回到目录",
}
NOTICE = re.compile(
    r'^(如果是第一次来|按右上角[“"\s]*WIKI功能|本条目介绍的是[：:]|首页\s*[>›»]|特产总览页面[：:]|圣遗物各部位属性请查看|以下内容可能存在主观性|下方攻略相关内容可能为编辑者)'
)


def valid_line(text: str) -> bool:
    stripped = text.strip()
    return (
        stripped not in EMPTY | UI_LABELS
        and not NOTICE.search(stripped)
        and not re.search(r"\{\{.*?\}\}|\[\[.*?\]\]", text)
        and not re.match(r'^[\[{].*"[\w]+"\s*:', text.strip(), re.S)
        and not re.fullmatch(r"[\w\-]+\.js", stripped)
        and not re.fullmatch(
            r"(?:文件|File):.+\.(?:png|webp|gif|jpe?g|svg)", stripped, re.I
        )
    )


def entity_name(text: str) -> str:
    """Strip category disambiguators, not the entity's actual name."""
    text = re.sub(r"^卡牌[：:]", "", text.strip())
    return re.sub(
        r"[（(](?:书籍|正文|故事|任务道具|道具|任务|角色|武器|卡牌)[）)]", "", text
    ).strip()


def clean_page(
    html: str,
    title: str,
    related: list | None,
    noise: dict | None = None,
    prefix: str = "ys",
    source: str = "bwiki",
):
    soup = BeautifulSoup(html, "html.parser")
    if source == "prts":
        prepare_prts(soup, title)
    for comment in list(soup.find_all(string=lambda v: isinstance(v, Comment))):
        if noise is not None:
            noise["comments"] = noise.get("comments", 0) + 1
        comment.extract()
    for text in list(soup.find_all(string=re.compile(r"本条目介绍的是[：:]"))):
        if not getattr(text, "parent", None):
            continue
        notice = text.find_parent(["div", "aside"])
        if notice is None or "mw-parser-output" in notice.get("class", []):
            continue
        if related is not None:
            site_prefix = "/w/" if source == "prts" else f"/{prefix}/"
            site_host = "prts.wiki" if source == "prts" else "wiki.biligame.com"
            for link in notice.find_all("a", href=True):
                url = urlsplit(unquote(link["href"]))
                target = url.path.removeprefix(site_prefix)
                if (
                    url.scheme not in {"", "https"}
                    or url.netloc not in {"", site_host}
                    or not url.path.startswith(site_prefix)
                    or url.query
                    or ":" in target
                    or target == title
                ):
                    continue
                identity = entity_name(url.fragment or target) == entity_name(title)
                if not identity:
                    continue
                item = {"title": target, "section": url.fragment}
                if item not in related:
                    related.append(item)
        if noise is not None:
            noise["notices"] = noise.get("notices", 0) + 1
        notice.decompose()
    for node in list(
        soup.select(
            "script,style,noscript,nav,header,footer,aside,form,button,input,select,.mw-editsection,#toc,#bread-edit,.resp-tabs-list,.visible-xs,.navbox,.navigation-not-searchable,.printfooter,#catlinks,#categoryData,#markerData,[type='application/json'],.map-dh,.cardSelectOption"
        )
    ):
        if node.attrs is not None:
            if noise is not None:
                noise["structural"] = noise.get("structural", 0) + 1
            node.decompose()
    # Remove small administrative containers; never delete a content-bearing root.
    for node in list(soup.find_all(["div", "p"])):
        if (
            node.attrs is None
            or "mw-parser-output" in node.get("class", [])
            or node.find(["table", "h2", "h3"])
        ):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        if NOTICE.search(text):
            if noise is not None:
                noise["notices"] = noise.get("notices", 0) + 1
            node.decompose()
    return soup
