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
        try:
            result = await asyncio.wait_for(
                self.primary.search(query, question), min(8, self.timeout * 0.6)
            )
            if result.get("status") not in {"not_found", "section_not_found"}:
                return self._annotate(result, self.primary_source)
        except WikiError as exc:
            if exc.code == "bad_input":
                raise
        except asyncio.TimeoutError:
            pass
        self.fallbacks += 1
        result = self._annotate(await self.fallback.search(query, question), "bwiki")
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
