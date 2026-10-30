"""Chinese editorial guides and mechanics from STS2.INFO.

Spire Codex localizes game data but its guides and mechanics articles are
English-only. STS2.INFO publishes Chinese editorial pages with the same game
data and explicitly cites Spire Codex. Only the requested page/section is
parsed and cached; a missing or changed page falls back to Spire Codex.
"""

import asyncio
import hashlib
import re
from urllib.parse import quote, unquote

import httpx
from bs4 import BeautifulSoup

from . import VERSION
from .cache import Cache

STS2INFO = "https://sts2.info"
STS2INFO_MECHANICS = STS2INFO + "/zh/mechanics"
STS2INFO_GUIDES = STS2INFO + "/zh/guides"
STS2FRONT = "https://sts2front.com"
STS2FRONT_CHARACTERS = STS2FRONT + "/zh-cn/characters"
CHARACTER_IDS = {
    "铁甲战士": "ironclad",
    "静默猎手": "silent",
    "故障机器人": "defect",
    "储君": "regent",
    "亡灵契约师": "necrobinder",
}
MECHANIC_SECTION_HINTS = {
    "伤害": ("结算顺序", "状态效果与结算机制"),
    "计算": ("结算顺序",),
    "结算": ("结算顺序",),
    "叠加": ("叠加规则",),
    "减益": ("减益、人工制品与施加顺序",),
}
STS2FRONT_BOILERPLATE = (
    "这篇文章围绕",
    "如果答案还依赖",
    "把它当作",
    "如果问题牵涉",
    "补丁可能改动",
    "验证说明",
    "快速总结",
    "本栏目更多",
    "快速回答",
    "快速信息",
    "继续阅读",
    "相关页面",
    "Sources",
)

MECHANIC_TOPICS = (
    "力量",
    "敏捷",
    "易伤",
    "虚弱",
    "脆弱",
    "中毒",
    "荆棘",
    "人工制品",
    "集中",
    "无实体",
    "缓冲",
    "活力",
    "再生",
    "镀层",
    "迟缓",
    "末日",
    "格挡",
    "暴走",
    "结算",
    "叠加",
    "减益",
    "机制",
    "规则",
    "伤害",
)
GUIDE_TOPICS = (
    "进阶",
    "卡组",
    "构筑",
    "路线",
    "商店",
    "金币",
    "篝火",
    "药水",
    "Boss",
    "BOSS",
    "精英",
    "Tier",
    "胜率",
    "先古",
    "纪元",
    "补丁",
    "新手",
    "攻略",
    "升级",
    "休息",
    "机制",
    "伤害",
    "格挡",
    "角色",
    "职业",
)
CHARACTER_ALIASES = {
    "铁甲战士": ("铁甲", "战士", "ironclad"),
    "静默猎手": ("静默", "猎人", "silent"),
    "故障机器人": ("故障", "机器人", "defect"),
    "储君": ("储君", "regent"),
    "亡灵契约师": ("亡灵", "死灵", "necrobinder"),
}


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _slug(text: str) -> str:
    return quote(str(text).strip(), safe="")


class ChineseGuideService:
    def __init__(self, cache: Cache, *, timeout=15, transport=None):
        self.cache = cache
        self.timeout = timeout
        self.http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": f"AstrBot-GameWiki/{VERSION} (STS2 Chinese guide lookup)"
            },
            transport=transport,
        )
        self._pace = asyncio.Lock()
        self._next_request = 0.0
        self._pace_seconds = 0.4

    async def close(self):
        await self.http.aclose()

    async def _wait(self):
        async with self._pace:
            delay = self._next_request - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request = asyncio.get_running_loop().time() + self._pace_seconds

    async def _get(self, url: str, ttl: float, parser):
        key = "chineseguide:" + hashlib.sha256(url.encode()).hexdigest()
        saved = await self.cache.get(key)
        if isinstance(saved, dict) and "data" in saved:
            return saved["data"]
        for attempt in range(2):
            await self._wait()
            try:
                response = await self.http.get(url)
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 1:
                    raise
                await asyncio.sleep(0.5)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or attempt == 1:
                    raise
                await asyncio.sleep(0.5)
        data = parser(response.text)
        await self.cache.put(key, {"data": data}, ttl)
        return data

    @staticmethod
    def _parse_mechanics(html: str):
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find("main") or soup
        items = []
        for article in main.find_all("article"):
            heading = article.find("h3")
            if heading is None:
                continue
            title = _clean(heading.get_text(" ", strip=True))
            body = article.find("dl") or article
            text = _clean(body.get_text("\n", strip=True))
            if title and text:
                items.append({"title": title, "text": text, "kind": "status"})
        for heading in main.find_all("h2"):
            title = _clean(heading.get_text(" ", strip=True))
            if not title or title in {"本文目录"}:
                continue
            parts = []
            for sibling in heading.next_siblings:
                if getattr(sibling, "name", None) == "h2":
                    break
                if hasattr(sibling, "get_text"):
                    text = _clean(sibling.get_text(" ", strip=True))
                    if text:
                        parts.append(text)
            if parts:
                items.append(
                    {"title": title, "text": "\n".join(parts), "kind": "section"}
                )
        return items

    @staticmethod
    def _parse_guide_list(html: str):
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find("main") or soup
        items, seen = [], set()
        for link in main.select('a[href^="/zh/guides/"]'):
            href = link.get("href", "")
            slug = href.rsplit("/", 1)[-1]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            text = _clean(link.get_text(" ", strip=True))
            if not text:
                continue
            items.append(
                {
                    "title": text[:160],
                    "slug": slug,
                    "url": STS2INFO + href,
                    "text": text,
                }
            )
        return items

    @staticmethod
    def _parse_guide_page(html: str):
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("h1")
        title = _clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
        article = soup.find("article") or soup.find("main") or soup
        for tag in article.find_all(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        text = _clean(article.get_text("\n", strip=True))
        return {"title": title, "text": text}

    @staticmethod
    def _parse_sts2front_page(html: str):
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("h1")
        title = _clean(title_tag.get_text(" ", strip=True)) if title_tag else ""
        main = soup.find("main") or soup
        texts, seen = [], set()
        for section in main.find_all("section"):
            for tag in section.find_all(
                ["a", "nav", "header", "footer", "script", "style"]
            ):
                tag.decompose()
            text = _clean(section.get_text("\n", strip=True))
            text = re.sub(
                r"^.*?已验证\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*",
                "",
                text,
                flags=re.S,
            )
            lines = [
                line
                for line in text.splitlines()
                if line and not line.startswith(STS2FRONT_BOILERPLATE)
            ]
            text = _clean("\n".join(lines))
            if len(text) < 10 or text in seen:
                continue
            seen.add(text)
            texts.append(text)
        return {"title": title, "text": "\n\n".join(texts)}

    def _mechanic_score(self, item, question):
        title = item["title"]
        text = item["text"]
        score = 0
        for topic in MECHANIC_TOPICS:
            if topic in question:
                score += 3 if topic in title else 1 if topic in text else 0
        if item["kind"] == "section":
            for word, titles in MECHANIC_SECTION_HINTS.items():
                if word in question and any(hint in title for hint in titles):
                    score += 5
        if item["kind"] == "section" and any(
            word in question for word in ("机制", "规则", "结算", "叠加")
        ):
            score += (
                2
                if item["title"]
                in {
                    "叠加规则：数值、持续时间与次数",
                    "结算顺序：效果到底什么时候发生",
                    "减益、人工制品与施加顺序",
                    "最常见的规则误区",
                }
                else 0
            )
        return score

    async def mechanics(self, question: str):
        items = await self._get(STS2INFO_MECHANICS, 21600, self._parse_mechanics)
        if not items:
            return None
        if "机制" in question and not any(
            topic in question for topic in MECHANIC_TOPICS if topic != "机制"
        ):
            text = "\n\n".join(f"{item['title']}\n{item['text']}" for item in items[:4])
            return {
                "key": "cn:mechanic:sts2info:" + _slug("状态效果与结算机制"),
                "title": "状态效果与结算机制",
                "text": text[:5000],
                "url": STS2INFO_MECHANICS,
            }
        ranked = sorted(
            ((self._mechanic_score(item, question), item) for item in items),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] <= 0:
            return None
        best = ranked[0][1]
        return {
            "key": "cn:mechanic:sts2info:" + _slug(best["title"]),
            "title": best["title"],
            "text": best["text"],
            "url": STS2INFO_MECHANICS,
        }

    async def guide(self, query: str, question: str = "", character: str = ""):
        if character:
            # Character pages are smaller and cover all five characters
            # (STS2.INFO's guide list only has Ironclad/Defect).
            front = await self._sts2front_character(character)
            if front:
                return front
        items = await self._get(STS2INFO_GUIDES, 21600, self._parse_guide_list)
        if not items:
            return None
        text_query = f"{query} {question}"
        aliases = CHARACTER_ALIASES.get(character, ())
        ranked = []
        for item in items:
            text = item["text"]
            # 角色攻略必须标题里出现该角色；只在正文提到“猎手”的通用的
            # 先古/职业对比文章不能冒充静默猎手攻略。
            if aliases and not any(alias in item["title"].lower() for alias in aliases):
                continue
            score = sum(
                2 for word in GUIDE_TOPICS if word in text_query and word in text
            )
            if aliases:
                score += 4
            if score > 0:
                ranked.append((score, item))
        if not ranked:
            return await self._sts2front_character(character) if character else None
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        item = ranked[0][1]
        try:
            page = await self._get(item["url"], 21600, self._parse_guide_page)
        except (httpx.HTTPError, ValueError):
            return None
        return {
            "key": "cn:guide:sts2info:" + item["slug"],
            "title": page.get("title") or item["title"],
            "text": page.get("text", ""),
            "url": item["url"],
        }

    async def _sts2front_character(self, character: str):
        char_id = CHARACTER_IDS.get(character)
        if not char_id:
            return None
        url = f"{STS2FRONT_CHARACTERS}/{char_id}/"
        try:
            page = await self._get(url, 21600, self._parse_sts2front_page)
        except (httpx.HTTPError, ValueError):
            return None
        return {
            "key": f"cn:guide:sts2front:{char_id}",
            "title": page.get("title") or character,
            "text": page.get("text", ""),
            "url": url,
        }

    async def read(self, key: str):
        prefix = "cn:mechanic:sts2info:"
        if key.startswith(prefix):
            topic = unquote(key[len(prefix) :])
            result = await self.mechanics(topic)
            if result is None:
                return None
            return {
                "id": key,
                "title": result["title"],
                "body_markdown": result["text"],
                "url": result["url"],
            }
        prefix = "cn:guide:sts2info:"
        if key.startswith(prefix):
            slug = key[len(prefix) :]
            try:
                page = await self._get(
                    f"{STS2INFO_GUIDES}/{slug}", 21600, self._parse_guide_page
                )
            except (httpx.HTTPError, ValueError):
                return None
            return {
                "id": key,
                "title": page.get("title") or slug,
                "content": page.get("text", ""),
                "url": f"{STS2INFO_GUIDES}/{slug}",
            }
        prefix = "cn:guide:sts2front:"
        if key.startswith(prefix):
            char_id = key[len(prefix) :]
            url = f"{STS2FRONT_CHARACTERS}/{char_id}/"
            try:
                page = await self._get(url, 21600, self._parse_sts2front_page)
            except (httpx.HTTPError, ValueError):
                return None
            return {
                "id": key,
                "title": page.get("title") or char_id,
                "content": page.get("text", ""),
                "url": url,
            }
        return None

    @staticmethod
    def url(key: str) -> str:
        if key.startswith("cn:mechanic:sts2info:"):
            return STS2INFO_MECHANICS
        if key.startswith("cn:guide:sts2info:"):
            return f"{STS2INFO_GUIDES}/{key.split(':')[-1]}"
        if key.startswith("cn:guide:sts2front:"):
            return f"{STS2FRONT_CHARACTERS}/{key.split(':')[-1]}/"
        return ""
