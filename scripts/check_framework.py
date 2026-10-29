"""Contract check against decorators and command filter from an AstrBot wheel.

This isolates actual registration code; it does not boot an AstrBot server.
Requires research/framework-check/{astrbot-*.whl,deps/docstring_parser}.
"""

import argparse
import ast
import asyncio
import enum
import importlib.util
import inspect
import json
import re
import sys
import tempfile
import types
import typing
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/framework-check/deps"))
import docstring_parser  # noqa: E402


def load_node(source, name, namespace):
    """Import one top-level definition from a pinned wheel file in isolation.

    The node is written to a temp file and loaded via importlib, so the check
    exercises the real framework code without importing its module's other
    dependencies; namespace supplies the stubbed globals it references.
    """
    tree = ast.parse(source)
    node = next(n for n in tree.body if getattr(n, "name", None) == name)
    body = ast.unparse(node)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"{name}.py"
        path.write_text("from __future__ import annotations\n" + body, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"wheel_check.{name}", path)
        module = importlib.util.module_from_spec(spec)
        module.__dict__.update(namespace)
        spec.loader.exec_module(module)
    return getattr(module, name)


def install_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module
    return module


def check_llm_tool_docstrings():
    """AstrBot builds tool schemas from the docstring Args section; a malformed
    docstring fails silently (parameters get dropped), so verify the format."""
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_tool = any(
            (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "llm_tool")
            or (isinstance(d, ast.Attribute) and d.attr == "llm_tool")
            for d in node.decorator_list
        )
        if not is_tool:
            continue
        doc = ast.get_docstring(node) or ""
        if "Args:" not in doc:
            problems.append(f"{node.name}: docstring has no Args section")
            continue
        for param in [a.arg for a in node.args.args][2:]:  # skip self, event
            if not re.search(rf"^\s*{param}\(\w+\)\s*:", doc, re.M):
                problems.append(
                    f"{node.name}: parameter {param} lacks a 'name(type):' line"
                )
    return problems


async def main():
    docstring_problems = check_llm_tool_docstrings()
    assert not docstring_problems, docstring_problems
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("4.5.7", "4.29.3"), default="4.29.3")
    version = parser.parse_args().version
    wheel = ROOT / f"research/framework-check/astrbot-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        registration = archive.read(
            "astrbot/core/star/register/star_handler.py"
        ).decode()
        commands = archive.read("astrbot/core/star/filter/command.py").decode()
        message_types = archive.read(
            "astrbot/core/star/filter/event_message_type.py"
        ).decode()
    tools = {}

    def add_func(name, args, description, handler):
        tools[name] = {"args": args, "description": description, "handler": handler}

    env = {
        "docstring_parser": docstring_parser,
        "re": re,
        "PY_TO_JSON_TYPE": {"str": "string", "int": "number"},
        "SUPPORTED_TYPES": {"string", "number", "boolean", "array", "object"},
        "llm_tools": SimpleNamespace(add_func=add_func),
        "EventType": SimpleNamespace(OnCallingFuncToolEvent=1),
        "get_handler_or_create": lambda handler, _: SimpleNamespace(handler=handler),
    }
    llm_tool = load_node(registration, "register_llm_tool", env)
    command_env = {
        "HandlerFilter": object,
        "inspect": inspect,
        "types": types,
        "typing": typing,
        "re": re,
        "GreedyStr": type("GreedyStr", (str,), {}),
        "unwrap_optional": lambda a: typing.get_args(a),
    }
    command_type = load_node(commands, "CommandFilter", command_env)
    event_message_type = load_node(message_types, "EventMessageType", {"enum": enum})
    message_type_filter = load_node(
        message_types,
        "EventMessageTypeFilter",
        {
            "HandlerFilter": object,
            "MESSAGE_TYPE_2_EVENT_MESSAGE_TYPE": {
                "group": event_message_type.GROUP_MESSAGE
            },
        },
    )
    message_filters = []

    def register_message_type(handler, event_type, **kwargs):
        metadata = SimpleNamespace(event_filters=[])
        message_filters.append(metadata)
        return metadata

    message_type = load_node(
        registration,
        "register_event_message_type",
        {
            "get_handler_or_create": register_message_type,
            "EventType": SimpleNamespace(AdapterMessageEvent=1),
            "EventMessageTypeFilter": message_type_filter,
        },
    )
    filters = []
    registered = []

    def command(name, alias=None):
        def decorate(handler):
            registered.append((name, alias))
            filters.append(command_type(name, alias, SimpleNamespace(handler=handler)))
            return handler

        return decorate

    class Event:
        is_at_or_wake_command = True

        def __init__(self, text):
            self.message_str = text
            self.extra = {}
            self.sent = []
            self.stopped = False

        def get_message_str(self):
            return self.message_str

        def set_extra(self, key, value):
            self.extra[key] = value

        def plain_result(self, text):
            return text

        async def send(self, result):
            self.sent.append(result)

        def get_message_type(self):
            return "group"

        def stop_event(self):
            self.stopped = True

        def is_admin(self):
            return False

        def get_sender_id(self):
            return "tester"

        unified_msg_origin = "test:GroupMessage:10001"

    class Star:
        def __init__(self, context):
            self.context = context

    with tempfile.TemporaryDirectory() as directory:
        install_module("astrbot")
        install_module(
            "astrbot.api", AstrBotConfig=dict, logger=SimpleNamespace(exception=print)
        )
        install_module(
            "astrbot.api.event",
            AstrMessageEvent=Event,
            filter=SimpleNamespace(
                command=command,
                llm_tool=llm_tool,
                event_message_type=message_type,
                EventMessageType=event_message_type,
            ),
        )
        install_module("astrbot.api.star", Star=Star, Context=object)
        install_module("astrbot.core")
        install_module("astrbot.core.utils")
        install_module(
            "astrbot.core.utils.astrbot_path", get_astrbot_data_path=lambda: directory
        )
        package = install_module("qa_plugin")
        package.__path__ = [str(ROOT)]
        spec = importlib.util.spec_from_file_location(
            "qa_plugin.main", ROOT / "main.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        plugin = module.GameWiki(
            object(),
            {"user_cooldown_seconds": 0, "user_rate_limit": 0, "games": ["ys", "sr"]},
        )
        assert len(message_filters) == 1
        assert message_filters[0].event_filters[0].filter(Event("1"), {})

        class Service:
            command_query = staticmethod(lambda text: tuple(text.split(maxsplit=1)))

            async def clear_parse_cache(self):
                return 0

            async def search(self, query, question):
                return {"status": "not_found", "message": f"{query}|{question}"}

            async def read(self, page_id, question, section):
                return {"status": "not_found", "message": f"{page_id}|{section}"}

            def stats(self):
                return {"errors": {}}

        plugin.services = {"ys": Service(), "sr": Service()}
        for old_parameter in ("统计", "清缓存"):
            event = Event(f"ys {old_parameter}")
            event.is_admin = lambda: True
            assert [r async for r in plugin.wiki_command_ys(event)] == []
            assert event.sent == [f"{old_parameter}|"], (
                "old Chinese parameters must not run admin actions"
            )
        cases = (
            (0, plugin.wiki_command_ys, "ys 草神 突破 材料", "草神|突破 材料"),
            (1, plugin.wiki_command_sr, "sr 流萤 晋阶材料", "流萤|晋阶材料"),
        )
        for filter_index, handler, text, expected in cases:
            event = Event(text)
            assert filters[filter_index].filter(event, {})
            result = [r async for r in handler(event, **event.extra["parsed_params"])]
            assert result == [] and event.sent == [expected], (text, result, event.sent)
        assert registered == [
            (name, None) for name in ("ys", "sr", "zzz", "ark", "zmd")
        ]
        for old in (
            "原神百科",
            "yswiki",
            "星铁百科",
            "srwiki",
            "绝区零百科",
            "zzzwiki",
            "明日方舟百科",
            "方舟百科",
            "arkwiki",
            "终末地百科",
            "终末地",
            "zmdwiki",
            "星穹铁道百科",
        ):
            assert not any(f.filter(Event(old + " 测试"), {}) for f in filters), old
        help_event = Event("ys")
        result = [r async for r in plugin.wiki_command_ys(help_event)]
        assert result == [] and "用法" in help_event.sent[0]
        assert "\n例：" in help_event.sent[0]
        admin_event = Event("ys stats")
        admin_event.is_admin = lambda: True
        assert [r async for r in plugin.wiki_command_ys(admin_event)] == []
        assert len(admin_event.sent) == 1 and "\n限流窗口：" in admin_event.sent[0]
        result = [r async for r in plugin.wiki_command_zmd(Event("zmd 流萤"))]
        assert "未启用" in result[0], "zmd is not in the config games list"

        class LayoutService(Service):
            async def search(self, query, question):
                return {
                    "status": "ok",
                    "title": "排版样例",
                    "url": "https://wiki.biligame.com/ys/排版样例",
                    "query": query,
                    "question": question,
                    "evidence": [
                        {"section": "概览", "text": "简介第一句。【章节甲】章节正文。"}
                    ],
                }

        for code, profile in module.PROFILES.items():
            plugin.services[code] = LayoutService()
            formatted_event = Event(f"{profile.command} 排版样例 简介")
            handler = getattr(plugin, f"wiki_command_{code}")
            assert [r async for r in handler(formatted_event)] == []
            assert len(formatted_event.sent) == 1, code
            assert formatted_event.sent[0].startswith("【排版样例】\n\n"), code
            assert "原文摘录" in formatted_event.sent[0], code
            assert "\n\n【章节甲】\n\n" in formatted_event.sent[0], code
            assert "\n\n来源：\nhttps://" in formatted_event.sent[0], code
            for word in ("stats", "clear-cache"):
                denied = [r async for r in handler(Event(f"{profile.command} {word}"))]
                assert "管理员" in denied[0], (code, word)
                admin = Event(f"{profile.command} {word}")
                admin.is_admin = lambda: True
                response = [r async for r in handler(admin)]
                assert (
                    (admin.sent and "百科运行统计" in admin.sent[0])
                    if word == "stats"
                    else "已清理缓存" in response[0]
                )
            help_event = Event(f"{profile.command} help")
            assert [r async for r in handler(help_event)] == []
            assert f"/{profile.command} help" in help_event.sent[0]

        class ModelContext:
            calls = []

            async def get_current_chat_provider_id(self, umo):
                assert umo == Event.unified_msg_origin
                return "session-provider"

            async def llm_generate(self, *, chat_provider_id, prompt):
                assert chat_provider_id == "session-provider"
                self.calls.append(prompt)
                body = (
                    json.dumps({"query": "排版样例", "question": "简介"})
                    if "解析器" in prompt
                    else "根据资料整理的概览。"
                )
                return SimpleNamespace(completion_text=body)

        plugin.context = ModelContext()
        event = Event("ys 排版样例讲了什么")
        assert [r async for r in plugin.wiki_command_ys(event)] == []
        assert "根据资料整理的概览" in event.sent[0]
        assert "查看原文：" in event.sent[0] and len(plugin.context.calls) == 2
        plugin.sessions = {"another-session"}
        denied = [r async for r in plugin.wiki_command_ys(Event("ys help"))]
        assert "当前会话未启用" in denied[0]
        plugin.sessions = set()
        plugin.services = {"ys": Service(), "sr": Service()}
        assert [p["name"] for p in tools["genshin_wiki_search"]["args"]] == [
            "query",
            "question",
        ]
        assert [p["name"] for p in tools["genshin_wiki_read"]["args"]] == [
            "page_id",
            "section",
            "question",
        ]
        assert tools["genshin_wiki_read"]["args"][0]["type"] == "number"
        assert [p["name"] for p in tools["wiki_search"]["args"]] == [
            "query",
            "question",
            "game",
        ]
        assert [p["name"] for p in tools["wiki_read"]["args"]] == [
            "page_id",
            "section",
            "question",
            "game",
            "source",
        ]
        result = json.loads(await plugin.wiki_search(Event(""), "草神", "突破", "ys"))
        assert result["message"] == "草神|突破"
        result = json.loads(
            await plugin.wiki_search(Event(""), "流萤", "晋阶材料", "sr")
        )
        assert result["message"] == "流萤|晋阶材料"
        result = json.loads(await plugin.wiki_search(Event(""), "流萤", "技能", "zmd"))
        assert result["code"] == "game_disabled"
        assert len(plugin.context.calls) == 2, "tools must not call the overview model"
        await plugin.terminate()
        from unittest.mock import AsyncMock

        endfield = module.GameWiki(
            object(), {"games": ["zmd"], "user_cooldown_seconds": 0}
        )
        try:
            router = endfield.services["zmd"]
            assert router.primary.client.source == "akedata"
            assert router.fallback.client.source == "bwiki"
            router.primary.read = AsyncMock(
                return_value={"status": "ok", "title": "祀"}
            )
            router.fallback.read = AsyncMock()
            result = json.loads(
                await endfield.wiki_read(Event(""), 123, "", "技能", "zmd", "akedata")
            )
            assert result["source_key"] == "akedata"
            router.fallback.read.assert_not_awaited()
            result = json.loads(
                await endfield.wiki_read(Event(""), 123, "", "技能", "zmd")
            )
            assert result["code"] == "bad_input"
        finally:
            await endfield.terminate()
    print(
        json.dumps(
            {
                "wheel": wheel.name,
                "checks": [
                    "llm_tool docstring Args format",
                    "real decorator schemas",
                    "real all-message decorator and event type filter",
                    "five English-only commands and removed aliases",
                    "multi-game commands and routing",
                    "multi-word command",
                    "formatted command sent once without result re-segmentation",
                    "help",
                    "disabled game hint",
                    "tool string return",
                    "session model overview and at most two calls",
                    "English help/admin parameters and session whitelist",
                    "tool calls do not invoke overview model",
                    "Endfield source initialization and pinned tool reads",
                    "unload",
                ],
            }
        )
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
