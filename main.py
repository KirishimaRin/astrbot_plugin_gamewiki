"""AstrBot entry points for commands and model-facing evidence tools."""

import asyncio
import json
import tempfile
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .wiki.cache import Cache
from .wiki.assistant import CommandAssistant
from .wiki.card import clear_font_cache, font_description, render_card
from .wiki.client import WikiClient
from .wiki.conversation import NUMBER, Conversations, is_followup, looks_like_followup
from .wiki.games import PROFILES, GameProfile, parse_alias_config
from .wiki.images import prepared_image
from .wiki.limits import Limiter
from .wiki.models import WikiError
from .wiki.query import QueryService
from .wiki.sources import ArknightsSources, EndfieldSources
from .wiki.akedata import AkeClient, AkeService

ADMIN_WORDS = {"stats", "clear-cache", "session", "doctor"}
# Aligns with the conversation topic lifetime: followups inside one topic
# never resend the same picture, a fresh topic later may.
IMAGE_DEDUP_TTL = 600


class GameWiki(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        def number(key, default, low, high):
            try:
                value = float(config.get(key, default))
                return max(low, min(high, value))
            except (TypeError, ValueError):
                return default

        global_aliases, game_aliases = parse_alias_config(config.get("aliases", []))
        self.sessions = {
            s.strip()
            for s in config.get("enabled_sessions", [])
            if isinstance(s, str) and s.strip()
        }
        self.debug_log = bool(config.get("debug_log", False))
        self.image_reply = bool(config.get("image_reply", True))
        self.conversation_enabled = bool(config.get("conversation_enabled", True))
        self.conversations = Conversations()
        self.recent_outcomes: dict[str, str] = {}
        self.recent_sources: dict[str, str] = {}
        self.brief_chars = int(number("reply_brief_chars", 350, 200, 1500))
        self.detailed_chars = int(number("reply_question_chars", 750, 300, 2000))
        self.model_timeout = number("model_timeout_seconds", 20, 2, 60)
        self.overview_chars = int(number("overview_chars", 250, 150, 500))
        directory = Path(get_astrbot_data_path()) / "plugin_data" / "gamewiki"
        legacy = Path(get_astrbot_data_path()) / "plugin_data" / "genshinimpactsearch"
        if not directory.exists() and legacy.exists():
            # An upgraded install keeps its cache and session switches.
            directory = legacy
        self.data_dir = directory
        clear_font_cache()
        configured_games = config.get("games", list(PROFILES))
        if not isinstance(configured_games, list):
            configured_games = list(PROFILES)
        games = list(
            dict.fromkeys(
                g for g in configured_games if isinstance(g, str) and g in PROFILES
            )
        ) or list(PROFILES)
        # Every client shares one Cache: they write one sqlite file, and
        # clear-cache must count and drop each entry exactly once.
        cache = Cache(directory)
        self.cache = cache
        self.services: dict[str, QueryService | ArknightsSources | EndfieldSources] = {}
        self.clients: list[WikiClient] = []
        self._image_slots = asyncio.Semaphore(2)
        # Sent portraits within one chat, kept until the conversation topic
        # would have expired; restarts reset it.
        self._recent_images: dict[tuple[str, str], float] = {}

        def build_service(code, source):
            profile = PROFILES[code]
            client = WikiClient(
                cache,
                number("timeout_seconds", 8, 2, 15),
                concurrency=int(number("upstream_concurrency", 2, 1, 8)),
                pace=number("upstream_pace_seconds", 0.3, 0.1, 2),
                game=code,
                source=source,
            )
            self.clients.append(client)
            return QueryService(
                client,
                profile=profile,
                aliases={**global_aliases, **game_aliases.get(code, {})},
                timeout=number("query_timeout_seconds", 15, 5, 30),
                search_ttl=number("search_cache_seconds", 600, 0, 3600),
                page_ttl=number("page_cache_seconds", 21600, 0, 86400),
                max_chars=int(number("max_evidence_chars", 6000, 1000, 8000)),
            )

        for code in games:
            if code == "arknights":
                self.services[code] = ArknightsSources(
                    build_service(code, "prts"),
                    build_service(code, "bwiki"),
                    timeout=number("query_timeout_seconds", 15, 5, 30),
                )
            elif code == "zmd":
                client = AkeClient(
                    cache,
                    number("timeout_seconds", 8, 2, 15),
                    concurrency=int(number("upstream_concurrency", 2, 1, 8)),
                    pace=number("upstream_pace_seconds", 0.3, 0.1, 2),
                )
                self.clients.append(client)
                primary = AkeService(
                    client,
                    aliases={**global_aliases, **game_aliases.get(code, {})},
                    timeout=number("query_timeout_seconds", 15, 5, 30),
                    search_ttl=number("search_cache_seconds", 600, 0, 3600),
                    page_ttl=number("page_cache_seconds", 21600, 0, 86400),
                    max_chars=int(number("max_evidence_chars", 6000, 1000, 8000)),
                )
                self.services[code] = EndfieldSources(
                    primary,
                    build_service(code, "bwiki"),
                    timeout=number("query_timeout_seconds", 15, 5, 30),
                )
            else:
                self.services[code] = build_service(code, "bwiki")
        self.limiter = Limiter(
            cooldown=number("user_cooldown_seconds", 5, 0, 60),
            per_user=int(number("user_rate_limit", 6, 0, 60)),
            per_minute=int(number("global_rate_limit", 30, 0, 300)),
        )
        self.session_overrides = self._load_session_overrides(directory)

    def _load_session_overrides(self, directory: Path) -> dict:
        path = directory / "session-overrides.json"
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                return {}
            return {k: v for k, v in values.items() if isinstance(v, bool)}
        except (OSError, ValueError):
            return {}

    def _save_session_overrides(self, directory: Path) -> bool:
        path = directory / "session-overrides.json"
        temporary = path.with_suffix(".json.tmp")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(self.session_overrides, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(path)
        except OSError:
            logger.warning("会话开关持久化失败", exc_info=True)
            return False
        return True

    async def terminate(self):
        for client in self.clients:
            await client.close()

    def _allowed(self, event: AstrMessageEvent) -> bool:
        origin = event.unified_msg_origin
        override = self.session_overrides.get(origin)
        if override is not None:
            # An in-group admin switch takes precedence over the whitelist.
            return override
        return not self.sessions or origin in self.sessions

    def _limited(self, event: AstrMessageEvent, cooldown: bool = True) -> None:
        # Administrators are exempt so they can always debug a busy bot.
        if not event.is_admin():
            user = event.get_sender_id() or event.unified_msg_origin
            self.limiter.check(user, cooldown=cooldown)

    def _debug(self, result: dict) -> None:
        if self.debug_log and isinstance(result, dict) and result.get("selection"):
            logger.info(
                f"百科 selection: {json.dumps(result['selection'], ensure_ascii=False)}"
            )

    async def _run(self, action, *args):
        try:
            result = await action(*args)
            self._debug(result)
            return result
        except WikiError as exc:
            return {"status": "error", "code": exc.code, "message": str(exc)}
        except asyncio.TimeoutError:
            return {
                "status": "error",
                "code": "timeout",
                "message": "百科查询超时，请稍后重试。",
            }
        except Exception:
            logger.exception("百科查询发生异常")
            return {
                "status": "error",
                "code": "internal",
                "message": "百科查询异常，请查看插件日志。",
            }

    def _stats_text(self) -> str:
        lines = ["百科运行统计"]
        for code, service in self.services.items():
            data = service.stats()
            errors = data.pop("errors", {})
            lines.append(
                f"[{data.get('game', code)}] 上游 {data.get('upstream_requests', 0)} 次，"
                f"HTTP 缓存命中 {data.get('cache_hits', 0)}，合并 {data.get('coalesced', 0)}，"
                f"解析 {data.get('pages_parsed', 0)}（复用 {data.get('parse_cache_hits', 0)}）"
            )
            if errors:
                lines.append(
                    "  错误：" + "、".join(f"{k} {v}" for k, v in errors.items())
                )
        data = self.limiter.stats()
        lines.append(
            f"限流窗口：{data['window_calls']} 次 / 活跃用户 {data['tracked_users']}"
        )
        return "\n".join(lines)

    def _session_status(self, event: AstrMessageEvent) -> str:
        state = self.session_overrides.get(event.unified_msg_origin)
        source = (
            "手工开关"
            if state is not None
            else "配置白名单"
            if self.sessions
            else "默认配置"
        )
        mode = "" if state is not None else "（跟随配置）"
        return f"本会话百科查询：{'开启' if self._allowed(event) else '关闭'}{mode}；来源：{source}"

    async def _doctor_text(self, event: AstrMessageEvent) -> str:
        health = await self.cache.health()
        font = await asyncio.to_thread(font_description, self.data_dir / "fonts")
        lines = [
            "百科诊断（本地检查，不请求 Wiki，不调用模型生成）",
            f"启用游戏：{', '.join(self.services)}",
            self._session_status(event),
            f"数据目录：{self.data_dir}",
            f"字体目录：{self.data_dir / 'fonts'}",
            f"卡片字体：{font}",
            f"缓存读取：{'正常' if health['readable'] else '失败'}；"
            f"目录写入：{'正常' if health['writable'] else '失败'}",
            f"有效缓存：{health['entries']} 条 / {health['bytes']} 字节",
        ]
        try:
            provider = await asyncio.wait_for(
                self.context.get_current_chat_provider_id(umo=event.unified_msg_origin),
                timeout=self.model_timeout,
            )
            lines.append(
                f"会话模型配置：{'已选择（未验证实际调用）' if provider else '未选择'}"
            )
        except Exception:
            lines.append("会话模型配置：读取失败，命令可降级为原文摘录")
        for client in self.clients:
            info = client.health()
            lines.append(
                f"[{client.game}/{client.source}] 上游共享退避剩余 {info['blocked_seconds']} 秒；"
                f"进行中请求 {info['pending']}；客户端{'已关闭' if info['closed'] else '可用'}"
            )
            errors = client.stats().get("errors", {})
            if errors:
                lines.append(
                    "  累计错误：" + "、".join(f"{k} {v}" for k, v in errors.items())
                )
        reasons = {
            "intent_timeout": "问题解析模型超时",
            "intent_failed": "问题解析模型不可用或输出无效",
            "overview_timeout": "概览模型超时",
            "overview_rejected": "概览未通过长度或数字校验",
            "overview_failed": "概览模型不可用",
        }
        for game, outcome in self.recent_outcomes.items():
            lines.append(f"[{game}] 最近命令状态：{reasons.get(outcome, outcome)}")
            if self.recent_sources.get(game):
                lines.append(f"  最近来源：{self.recent_sources[game]}")
        if "arknights" in self.services:
            lines.append(
                "明日方舟搜索：PRTS 优先；不可用或无结果时回退 BWIKI，补读固定原来源"
            )
        if "zmd" in self.services:
            lines.append(
                "终末地搜索：AKEData 优先；异常、无结果或缺少所问内容时回退 BWIKI，补读固定原来源"
            )
        if not self.recent_outcomes:
            lines.append("最近命令状态：暂无记录")
        return "\n".join(lines)

    async def _admin_action(self, event: AstrMessageEvent, word: str):
        if not event.is_admin():
            yield event.plain_result("该操作仅限 AstrBot 管理员使用。")
            return
        if word == "stats":
            await event.send(event.plain_result(self._stats_text()))
            return
        if word == "doctor":
            await event.send(event.plain_result(await self._doctor_text(event)))
            return
        if word == "session":
            tail = event.message_str.split(maxsplit=2)
            arg = tail[2].strip().lower() if len(tail) > 2 else "status"
            origin = event.unified_msg_origin
            if arg == "status":
                await event.send(event.plain_result(self._session_status(event)))
                return
            if arg not in {"on", "off", "reset"}:
                await event.send(
                    event.plain_result("用法：/游戏 session on|off|status|reset")
                )
                return
            if arg == "reset":
                self.session_overrides.pop(origin, None)
            else:
                self.session_overrides[origin] = arg == "on"
            saved = self._save_session_overrides(self.data_dir)
            notice = "" if saved else "保存失败，仅本次运行生效，重启后可能恢复原状态。"
            await event.send(
                event.plain_result(self._session_status(event) + f"。{notice}")
            )
            return
        cleared = await self.cache.clear()
        parse_total = sum([await s.clear_parse_cache() for s in self.services.values()])
        yield event.plain_result(
            f"已清理缓存：HTTP 条目 {cleared} 条；已解析页面 {parse_total} 个。"
        )

    async def _wiki_command(
        self, event: AstrMessageEvent, profile: GameProfile, *, command_text=None
    ):
        """Shared handler: one wiki command per game profile."""
        # Parse the whole tail ourselves so multi-word questions are preserved.
        message = (event.message_str if command_text is None else command_text).strip()
        parts = message.split(maxsplit=1)
        word = parts[1].strip() if len(parts) > 1 else ""
        admin_word = word.split(maxsplit=1)[0] if word else ""
        if admin_word in ADMIN_WORDS:
            if admin_word != "session" and word != admin_word:
                yield event.plain_result(f"用法：/{profile.command} {admin_word}")
                return
            async for reply in self._admin_action(event, admin_word):
                yield reply
            return
        if not self._allowed(event):
            yield event.plain_result(
                "当前会话未启用百科查询，请在插件配置中添加本会话。"
            )
            return
        if len(parts) < 2 or parts[1].strip() == "help":
            await event.send(
                event.plain_result(
                    f"用法：/{profile.command} 名称或完整问题\n"
                    f"例：/{profile.command} 条目名 获取方式\n"
                    f"帮助：/{profile.command} help\n"
                    f"候选：/{profile.command} 编号；追问：/{profile.command} 突破材料呢\n"
                    f"管理员：/{profile.command} stats / /{profile.command} clear-cache / "
                    f"/{profile.command} doctor / /{profile.command} session on|off|status|reset"
                )
            )
            return
        service = self.services.get(profile.code)
        if service is None:
            yield event.plain_result(
                f"{profile.name}百科未启用，请在插件配置 games 中加入 {profile.code}。"
            )
            return
        sender = event.get_sender_id()
        key = (event.unified_msg_origin, sender) if sender else None
        state = (
            self.conversations.get(key) if self.conversation_enabled and key else None
        )
        page_id, question, notice, source = None, "", "", ""
        selection = self.conversation_enabled and bool(NUMBER.fullmatch(word))
        followup = is_followup(word, state)
        if selection:
            if state is None or not state.candidates:
                yield event.plain_result("没有待选候选或候选已过期，请重新查询名称。")
                return
            if state.game != profile.code:
                yield event.plain_result(
                    f"当前候选属于{PROFILES[state.game].name}，请使用 /{PROFILES[state.game].command} 编号，"
                    "或输入当前游戏的完整条目名。"
                )
                return
            index = int(word) - 1
            if not 0 <= index < len(state.candidates):
                yield event.plain_result(f"请选择 1–{len(state.candidates)} 的编号。")
                return
            chosen = state.candidates[index]
            page_id, question = chosen["page_id"], state.question
            source = state.source
            word = chosen["title"]
            notice = f"已选择【{word}】（{profile.name}）\n\n"
        elif followup:
            if state.game != profile.code:
                self.conversations.forget(key)
                yield event.plain_result(
                    f"上一条目属于{PROFILES[state.game].name}；已切换到{profile.name}，请先输入完整条目名。"
                )
                return
            page_id, question = state.page_id, word
            source = state.source
            notice = f"继续查询【{state.title}】（{profile.name}）\n\n"
        elif self.conversation_enabled and looks_like_followup(word):
            yield event.plain_result(
                "没有可追问的条目或上下文已过期，请先输入完整条目名。"
            )
            return
        try:
            self._limited(event)
        except WikiError as exc:
            yield event.plain_result(str(exc))
            return
        ticket = (
            self.conversations.begin(key, preserve=selection or followup)
            if self.conversation_enabled and key
            else None
        )

        def on_result(result):
            self._debug(result)
            if self.conversation_enabled and key and ticket:
                result["command"] = profile.command
                self.conversations.remember(key, ticket, profile.code, result)

        provider_id = None

        async def generate(prompt):
            nonlocal provider_id
            if provider_id is None:
                provider_id = await self.context.get_current_chat_provider_id(
                    umo=event.unified_msg_origin
                )
            if not provider_id:
                raise RuntimeError("当前会话未配置聊天模型")
            response = await self.context.llm_generate(
                chat_provider_id=provider_id, prompt=prompt
            )
            return response.completion_text

        assistant = CommandAssistant(
            generate,
            model_timeout=self.model_timeout,
            summary_chars=self.overview_chars,
            brief=self.brief_chars,
            detailed=self.detailed_chars,
        )
        metrics = {}
        self.recent_sources.pop(profile.code, None)
        try:
            text, metrics = await assistant.answer(
                word,
                profile,
                service,
                page_id=page_id,
                question=question,
                source=source,
                on_result=on_result,
            )
            self.recent_outcomes[profile.code] = metrics.get(
                "fallback_reason", metrics.get("outcome", "unknown")
            )
            self.recent_sources[profile.code] = metrics.get("source_key", "")
            if self.debug_log:
                logger.info(f"百科 command: {json.dumps(metrics, ensure_ascii=False)}")
        except WikiError as exc:
            text = str(exc)
            self.recent_outcomes[profile.code] = exc.code
        except asyncio.TimeoutError:
            text = "百科查询超时，请稍后重试。"
            self.recent_outcomes[profile.code] = "timeout"
        except Exception:
            logger.exception("百科命令查询发生异常")
            text = "百科查询异常，请查看插件日志。"
            self.recent_outcomes[profile.code] = "internal"
        # Deliver the answer before downloading a cold, potentially large portrait.
        # Send the formatted reply intact; the result pipeline may strip whitespace.
        await event.send(event.plain_result(notice + text))
        image_url = metrics.get("image_url") if isinstance(metrics, dict) else ""
        if self.image_reply and image_url:
            await self._send_entry_image(event, image_url)
        card = metrics.get("card") if isinstance(metrics, dict) else None
        # The excerpt fallback already quotes the evidence verbatim; a card of
        # the same text would be a pure duplicate.
        if self.image_reply and card and not metrics.get("fallback"):
            await self._send_card(event, card, profile.accent)

    async def _send_card(self, event: AstrMessageEvent, card: dict, accent: tuple = ()):
        # Rendered locally from validated evidence; no font means no card.
        try:
            async with self._image_slots:
                png = await asyncio.to_thread(
                    render_card,
                    card["title"],
                    card["source"],
                    card["sections"],
                    accent,
                    font_dir=self.data_dir / "fonts",
                )
                if not png:
                    return
                with tempfile.TemporaryDirectory(prefix="gamewiki-card-") as directory:
                    path = Path(directory) / "card.png"
                    path.write_bytes(png)
                    await event.send(event.image_result(str(path)))
        except Exception:
            logger.debug("证据卡片发送失败，忽略", exc_info=True)

    async def _send_entry_image(self, event: AstrMessageEvent, image_url: str):
        key = (event.unified_msg_origin, image_url)
        now = time.monotonic()
        last = self._recent_images.get(key)
        if last is not None and now - last < IMAGE_DEDUP_TTL:
            return
        try:
            async with self._image_slots:
                async with prepared_image(image_url, self.cache) as image:
                    await event.send(event.image_result(image))
        except Exception:
            logger.debug("条目图片发送失败，忽略", exc_info=True)
            return
        self._recent_images[key] = now
        if len(self._recent_images) > 256:
            cutoff = now - IMAGE_DEDUP_TTL
            for stale, sent in list(self._recent_images.items()):
                if sent <= cutoff:
                    del self._recent_images[stale]
            while len(self._recent_images) > 256:
                self._recent_images.pop(next(iter(self._recent_images)))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def wiki_followup(self, event: AstrMessageEvent):
        """Continue only an active user's numbered choice or short section question."""
        if not self.conversation_enabled or not self._allowed(event):
            return
        sender = event.get_sender_id()
        if not sender:
            return
        key = (event.unified_msg_origin, sender)
        state = self.conversations.get(key)
        text = event.message_str.strip()
        if state is None or not (
            (state.candidates and NUMBER.fullmatch(text)) or is_followup(text, state)
        ):
            return
        # Reuse the same command path for permissions, limits, and rendering.
        event.stop_event()
        async for reply in self._wiki_command(
            event,
            PROFILES[state.game],
            command_text=f"{PROFILES[state.game].command} {text}",
        ):
            await event.send(reply)

    @filter.command("ys")
    async def wiki_command_ys(self, event: AstrMessageEvent):
        """ys 名称或问题：查询原神 BWIKI，返回概览和来源。

        管理员参数：stats / clear-cache；帮助：help。
        """
        async for reply in self._wiki_command(event, PROFILES["ys"]):
            yield reply

    @filter.command("sr")
    async def wiki_command_sr(self, event: AstrMessageEvent):
        """sr 名称或问题：查询星穹铁道，返回概览和来源。"""
        async for reply in self._wiki_command(event, PROFILES["sr"]):
            yield reply

    @filter.command("zzz")
    async def wiki_command_zzz(self, event: AstrMessageEvent):
        """zzz 名称或问题：查询绝区零，返回概览和来源。"""
        async for reply in self._wiki_command(event, PROFILES["zzz"]):
            yield reply

    @filter.command("ark")
    async def wiki_command_arknights(self, event: AstrMessageEvent):
        """ark 名称或问题：查询明日方舟，返回概览和来源。"""
        async for reply in self._wiki_command(event, PROFILES["arknights"]):
            yield reply

    @filter.command("zmd")
    async def wiki_command_zmd(self, event: AstrMessageEvent):
        """zmd 名称或问题：查询终末地，返回概览和来源。"""
        async for reply in self._wiki_command(event, PROFILES["zmd"]):
            yield reply

    async def _tool_search(self, event, query, question, game):
        if not self._allowed(event):
            return {
                "status": "error",
                "code": "disabled",
                "message": "当前会话未启用百科查询。",
            }
        service = self.services.get(game)
        if service is None:
            # Validate the game before charging the caller's rate budget.
            return {
                "status": "error",
                "code": "game_disabled",
                "message": f"{game} 未启用，当前可用：{', '.join(self.services)}。",
            }
        try:
            self._limited(event)
        except WikiError as exc:
            return {"status": "error", "code": exc.code, "message": str(exc)}
        return await self._run(service.search, query, question)

    async def _tool_read(self, event, page_id, section, question, game, source=""):
        if not self._allowed(event):
            return {
                "status": "error",
                "code": "disabled",
                "message": "当前会话未启用百科查询。",
            }
        service = self.services.get(game)
        if service is None:
            return {
                "status": "error",
                "code": "game_disabled",
                "message": f"{game} 未启用，当前可用：{', '.join(self.services)}。",
            }
        try:
            # Reads ride along a search inside one AI turn, so no cooldown.
            self._limited(event, cooldown=False)
        except WikiError as exc:
            return {"status": "error", "code": exc.code, "message": str(exc)}
        # JSON Schema's number type may arrive as an integral float.
        if isinstance(page_id, float) and page_id.is_integer():
            page_id = int(page_id)
        if game in {"arknights", "zmd"} or source:

            async def read_from_source():
                if game not in {"arknights", "zmd"} and source != "bwiki":
                    raise WikiError("bad_input", "该游戏仅支持 bwiki 来源。")
                if game in {"arknights", "zmd"}:
                    return await service.read(page_id, question, section, source=source)
                return await service.read(page_id, question, section)

            return await self._run(read_from_source)
        return await self._run(service.read, page_id, question, section)

    @filter.llm_tool(name="wiki_search")
    async def wiki_search(
        self, event: AstrMessageEvent, query: str, question: str, game: str
    ) -> str:
        """查询游戏 Wiki，返回候选条目和相关正文证据。

        用于角色、技能、材料、任务、书籍和剧情知识问题，游戏由 game 指定。
        query 填名称或简短关键词，完整问题填 question。
        question 尽量使用条目用语，如“突破材料”“获取方式”“天赋”“技能”。
        回答需要引用返回的 URL，证据不足时可补查其他候选条目。

        Args:
            query(string): 角色名、昵称、书名、任务名或简短关键词。
            question(string): 用户的完整问题，用于选择相关分节。
            game(string): 游戏代码，可用值见插件配置 games。
        """
        result = await self._tool_search(event, query, question, game)
        return json.dumps(result, ensure_ascii=False)

    @filter.llm_tool(name="wiki_read")
    async def wiki_read(
        self,
        event: AstrMessageEvent,
        page_id: int,
        section: str,
        question: str,
        game: str,
        source: str = "",
    ) -> str:
        """按搜索结果的 page_id 补读 Wiki 指定分节，游戏由 game 指定。

        section 可使用 available_sections 中的分节名，空字符串表示自动选择。

        Args:
            page_id(number): 搜索结果中的整数 page_id。
            section(string): 分节名称，空字符串表示按问题自动筛选。
            question(string): 要解答的问题。
            game(string): 与搜索结果相同的游戏代码。
            source(string): 明日方舟和终末地必须填写搜索返回的 source_key（prts、akedata 或 bwiki），其他游戏可留空。
        """
        result = await self._tool_read(event, page_id, section, question, game, source)
        return json.dumps(result, ensure_ascii=False)

    @filter.llm_tool(name="genshin_wiki_search")
    async def genshin_wiki_search(
        self, event: AstrMessageEvent, query: str, question: str
    ) -> str:
        """查询原神 BWIKI，返回候选条目和相关正文证据。

        用于原神角色、技能、材料、任务、书籍和剧情知识问题。
        query 填名称或简短关键词，完整问题填 question。
        question 尽量使用条目用语，如“突破材料”“获取方式”“天赋”“技能”。
        回答需要引用返回的 URL，证据不足时可补查其他候选条目。

        Args:
            query(string): 角色名、昵称、书名、任务名或简短关键词。
            question(string): 用户的完整问题，用于选择相关分节。
        """
        return await self.wiki_search(event, query, question, "ys")

    @filter.llm_tool(name="genshin_wiki_read")
    async def genshin_wiki_read(
        self, event: AstrMessageEvent, page_id: int, section: str, question: str
    ) -> str:
        """按搜索结果的 page_id 补读原神 BWIKI 指定分节。

        section 可使用 available_sections 中的分节名，空字符串表示自动选择。

        Args:
            page_id(number): 搜索结果中的整数 page_id。
            section(string): 分节名称，空字符串表示按问题自动筛选。
            question(string): 要解答的问题。
        """
        return await self.wiki_read(event, page_id, section, question, "ys")
