"""Primary-first searches with source-pinned reads and bounded BWIKI fallback."""

import asyncio

from .models import WikiError


class SourceRouter:
    def __init__(self, primary, fallback, *, timeout=15):
        self.primary, self.fallback = primary, fallback
        self.aliases = primary.aliases
        self.timeout = timeout
        self.fallbacks = 0

    @property
    def profile(self):
        # Both sources serve the same game; question normalization uses it.
        return self.primary.profile

    @staticmethod
    def _annotate(result, source):
        result = {**result, "source_key": source}
        result["instructions"] = result.get("instructions", "") + (
            f" 补读时 wiki_read 的 source 参数必须填写 {source}，page_id 仅在此来源内有效。"
        )
        return result

    async def _search(self, query, question):
        primary_result = None
        try:
            primary_result = await asyncio.wait_for(
                self.primary.search(query, question), min(8, self.timeout * 0.6)
            )
            if primary_result.get("status") not in {"not_found", "section_not_found"}:
                return self._annotate(primary_result, self.primary_source)
        except WikiError as exc:
            if exc.code == "bad_input":
                raise
        except asyncio.TimeoutError:
            pass
        self.fallbacks += 1
        try:
            result = await self.fallback.search(query, question)
        except WikiError:
            # 主源已经明确“没有这个词条/分节”时，兜底源故障不改变这个
            # 结论：返回主源的 not_found 比抛上游错误更准确（BWIKI 的 WAF
            # 是间歇性的，用户不该因此看到“服务异常”）。
            if primary_result is not None:
                return self._annotate(primary_result, self.primary_source)
            raise
        result = self._annotate(result, "bwiki")
        result["fallback_from"] = self.primary_source
        return result

    async def search(self, query, question=""):
        return await asyncio.wait_for(self._search(query, question), self.timeout)

    async def read(self, page_id, question="", section="", *, source=""):
        if source not in {self.primary_source, "bwiki"}:
            raise WikiError(
                "bad_input",
                f"{self.game_name}补读请传入搜索结果的 source_key"
                f"（{self.primary_source} 或 bwiki），避免跨站点读取错误条目。",
            )
        service = self.primary if source == self.primary_source else self.fallback
        # Never send a source's page_id to another wiki, even on a network error.
        return self._annotate(await service.read(page_id, question, section), source)

    async def clear_parse_cache(self):
        return (
            await self.primary.clear_parse_cache()
            + await self.fallback.clear_parse_cache()
        )

    def stats(self):
        data = {"game": self.game, "errors": {}, "fallbacks": self.fallbacks}
        for service in (self.primary, self.fallback):
            for key, value in service.stats().items():
                if key == "errors":
                    for code, count in value.items():
                        data["errors"][code] = data["errors"].get(code, 0) + count
                elif isinstance(value, int):
                    data[key] = data.get(key, 0) + value
        return data


class ArknightsSources(SourceRouter):
    primary_source = "prts"
    game = "arknights"
    game_name = "明日方舟"


class EndfieldSources(SourceRouter):
    primary_source = "akedata"
    game = "zmd"
    game_name = "终末地"


class WuwaSources(SourceRouter):
    primary_source = "kurobbs"
    game = "ww"
    game_name = "鸣潮"

    async def search(self, query, question=""):
        # 主源会在服务层把「今汐满链效果」拆成实体+方面；兜底源收到的是
        # 原始整串，会搜不到。这里先拆好，两侧用同一对参数。
        from .kurobbs import _split_aspect
        from .games import normalize_slang

        query = normalize_slang(query, self.profile)
        question = normalize_slang(question, self.profile) if question else question
        if not question:
            query, question = _split_aspect(query)
        return await super().search(query, question)
