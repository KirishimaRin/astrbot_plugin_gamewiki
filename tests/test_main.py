"""Offline coverage for main.py using the same stub modules as the contract check."""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from wiki.games import PROFILES
from wiki.limits import Limiter

ROOT = Path(__file__).resolve().parents[1]


def _install_stubs(data_dir: str):
    def install(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module
        return module

    class Event:
        def __init__(self, text="", *, admin=False, origin="test:GroupMessage:1"):
            self.message_str = text
            self._admin = admin
            self.unified_msg_origin = origin
            self.sent = []
            self.stopped = False

        def is_admin(self):
            return self._admin

        def get_sender_id(self):
            return "tester"

        def plain_result(self, text):
            return text

        async def send(self, result):
            self.sent.append(result)

        def stop_event(self):
            self.stopped = True

    def passthrough(*args, **kwargs):
        def decorate(handler):
            return handler

        return decorate

    install("astrbot")
    install("astrbot.api", AstrBotConfig=dict, logger=__import__("logging"))
    install(
        "astrbot.api.event",
        AstrMessageEvent=Event,
        filter=SimpleNamespace(
            command=passthrough,
            event_message_type=passthrough,
            EventMessageType=SimpleNamespace(ALL=1),
            llm_tool=passthrough,
            permission_type=passthrough,
            PermissionType=SimpleNamespace(ADMIN=1),
        ),
    )
    install(
        "astrbot.api.star",
        Star=type("Star", (), {"__init__": lambda s, c: None}),
        Context=object,
    )
    install("astrbot.core")
    install("astrbot.core.utils")
    install(
        "astrbot.core.utils.astrbot_path",
        get_astrbot_data_path=lambda: str(data_dir),
    )
    package = install("qa_plugin")
    package.__path__ = [str(ROOT)]
    spec = importlib.util.spec_from_file_location("qa_plugin.main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Each test replaces the root package, while imported submodules remain
    # cached. Python 3.10 mock.patch traverses parent attributes, so restore the
    # package links that a real import would establish on first load.
    package.wiki = sys.modules["qa_plugin.wiki"]
    package.main = module
    return module, Event


@pytest.fixture()
def plugin():
    with tempfile.TemporaryDirectory() as data_dir:
        module, Event = _install_stubs(data_dir)
        instance = module.GameWiki(
            object(),
            {
                "games": ["ys", "sr"],
                "user_cooldown_seconds": 0,
                # 关注结果内容的用例不叠加“正在查询”提示；提示本身另有专项用例。
                "query_notice": False,
            },
        )
        yield instance, Event, module
        asyncio.run(instance.terminate())


def test_number_clamps_out_of_range_and_bad_values(plugin):
    instance, _, _ = plugin
    assert 2 <= instance.brief_chars <= 1500
    bad = type(instance)(
        object(),
        {"reply_brief_chars": "abc", "reply_question_chars": 99999},
    )
    assert bad.brief_chars == 350
    assert bad.detailed_chars == 2000


@pytest.mark.parametrize(
    "config",
    [{}, {"games": []}, {"games": ["nope", 1]}, {"games": None}, {"games": "ys"}],
)
def test_games_default_and_invalid_config_enable_all_games(plugin, config):
    instance, _, module = plugin
    assert set(instance.services) == {"ys", "sr"}
    configured = type(instance)(object(), config)
    try:
        assert set(configured.services) == set(module.PROFILES)
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        assert schema["games"]["default"] == list(module.PROFILES)
    finally:
        asyncio.run(configured.terminate())


def test_sts2_command_and_tool_use_the_real_service(plugin):
    instance, Event, module = plugin
    relic = {
        "id": "BURNING_BLOOD",
        "name": "燃烧之血",
        "description": "在战斗结束时，回复[green]6[/green]点生命。",
        "rarity": "初始遗物",
        "pool": "ironclad",
        "image_url": "/static/images/relics/burning_blood.webp",
    }

    def handler(request):
        path = request.url.path
        if path == "/api/changelogs":
            return httpx.Response(200, json=[{"game_version": "1.3.1"}])
        if path == "/api/search":
            return httpx.Response(
                200,
                json={
                    "categories": [
                        {
                            "kind": "relic",
                            "items": [
                                {
                                    "name": "燃烧之血",
                                    "path": "/relics/burning_blood",
                                    "subtitle": "初始遗物 · ironclad",
                                }
                            ],
                        }
                    ]
                },
            )
        if path in {"/api/relics", "/api/relics/burning_blood"}:
            payload = [relic] if path == "/api/relics" else relic
            return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"detail": "Not Found"})

    client = module.SpireCodexClient(
        instance.cache, timeout=2, transport=httpx.MockTransport(handler)
    )
    service = module.SpireCodexService(client, timeout=2)
    instance.services["sts2"] = service

    async def check():
        try:
            event = Event("sts2 燃烧之血 效果")
            assert [r async for r in instance.wiki_command_sts2(event)] == []
            assert "燃烧之血" in event.sent[-1]
            assert "6" in event.sent[-1]
            page_id = next(iter(service._known))
            result = json.loads(
                await instance.wiki_read(Event(), page_id, "", "效果", "sts2")
            )
            assert result["status"] == "ok"
            assert result["title"] == "燃烧之血"
        finally:
            await client.close()

    asyncio.run(check())


def test_sts2_chinese_sources_can_be_disabled(plugin):
    instance, _, _ = plugin
    enabled = type(instance)(object(), {"games": ["sts2"]})
    disabled = type(instance)(
        object(), {"games": ["sts2"], "sts2_chinese_sources": False}
    )
    try:
        assert enabled.services["sts2"].chinese is not None
        assert disabled.services["sts2"].chinese is None
    finally:
        asyncio.run(enabled.terminate())
        asyncio.run(disabled.terminate())


def test_sts2_custom_base_is_passed_to_client_and_service(plugin):
    instance, _, _ = plugin
    configured = type(instance)(
        object(),
        {"games": ["sts2"], "spire_codex_base": "https://example.test"},
    )
    try:
        assert configured.services["sts2"].base == "https://example.test"
        assert configured.clients[0].api == "https://example.test"
    finally:
        asyncio.run(configured.terminate())


def test_existing_games_subset_is_preserved_and_duplicates_are_ignored(plugin):
    instance, _, _ = plugin
    configured = type(instance)(object(), {"games": ["ys", "ys", "sr", "invalid"]})
    try:
        assert list(configured.services) == ["ys", "sr"]
        assert len(configured.clients) == 2
    finally:
        asyncio.run(configured.terminate())


def test_shared_cache_instance_across_clients(plugin):
    instance, _, _ = plugin
    assert instance.clients[0].cache is instance.clients[1].cache


def test_session_overrides_take_precedence(plugin):
    instance, Event, _ = plugin
    event = Event("", origin="test:GroupMessage:9")
    instance.session_overrides["test:GroupMessage:9"] = False
    assert instance._allowed(event) is False
    instance.session_overrides["test:GroupMessage:9"] = True
    assert instance._allowed(event) is True
    del instance.session_overrides["test:GroupMessage:9"]
    assert instance._allowed(event) is True, "no whitelist configured"
    instance.sessions = {"test:GroupMessage:1"}
    assert instance._allowed(Event("", origin="test:GroupMessage:2")) is False


def test_admin_bypasses_rate_limit(plugin):
    from wiki.models import WikiError

    instance, Event, _ = plugin
    instance.limiter = Limiter(cooldown=0, per_user=1, per_minute=1)
    for _ in range(5):
        instance._limited(Event("", admin=True))
    normal = Event("", admin=False)
    instance._limited(normal)
    with pytest.raises(WikiError):
        instance._limited(Event("", admin=False))


def test_tool_search_does_not_charge_disabled_games(plugin):
    instance, Event, _ = plugin
    calls = []

    def fake_limited(event, cooldown=True):
        calls.append(1)

    instance._limited = fake_limited
    result = asyncio.run(instance._tool_search(Event(), "x", "y", "zmd"))
    assert result["code"] == "game_disabled"
    assert not calls, "disabled games must not consume the rate budget"


def test_tool_read_converts_integral_float_page_id(plugin):
    instance, Event, _ = plugin
    captured = {}

    async def fake_read(page_id, question, section):
        captured["page_id"] = page_id
        return {"status": "ok"}

    instance.services["ys"].read = fake_read
    result = asyncio.run(instance._tool_read(Event(), 42.0, "", "问题", "ys"))
    assert result["status"] == "ok"
    assert captured["page_id"] == 42 and isinstance(captured["page_id"], int)


def test_run_maps_errors_for_the_user(plugin):
    instance, _, _ = plugin

    async def boom():
        raise ValueError("x")

    result = asyncio.run(instance._run(boom))
    assert result["status"] == "error" and result["code"] == "internal"

    async def timeout():
        raise asyncio.TimeoutError()

    result = asyncio.run(instance._run(timeout))
    assert result["code"] == "timeout"


def test_stats_text_lists_games(plugin):
    instance, _, _ = plugin
    text = instance._stats_text()
    assert "百科运行统计" in text and "[ys]" in text and "[sr]" in text


def test_session_override_persists_to_data_dir(plugin):
    instance, Event, _ = plugin

    async def admin(arg):
        event = Event(f"ys session {arg}", origin="test:GroupMessage:7", admin=True)
        async for _ in instance._admin_action(event, "session"):
            pass
        return event

    asyncio.run(admin("off"))
    assert instance.session_overrides["test:GroupMessage:7"] is False
    assert instance._allowed(Event("", origin="test:GroupMessage:7")) is False
    asyncio.run(admin("on"))
    assert instance.session_overrides["test:GroupMessage:7"] is True
    assert instance._allowed(Event("", origin="test:GroupMessage:7")) is True
    assert json.loads(
        (instance.data_dir / "session-overrides.json").read_text(encoding="utf-8")
    ) == {"test:GroupMessage:7": True}


@pytest.mark.parametrize("game", ["ys", "sr", "zzz", "arknights", "zmd", "sts2"])
def test_public_commands_can_disable_inspect_and_restore_session(plugin, game):
    instance, Event, module = plugin
    profile = module.PROFILES[game]

    async def check():
        handler = getattr(instance, f"wiki_command_{game}")
        instance._limited = lambda *args, **kwargs: pytest.fail("admin consumed quota")
        for argument, expected in (("off", False), ("status", False), ("on", True)):
            event = Event(f"{profile.command} session {argument}", admin=True)
            assert [r async for r in handler(event)] == []
            assert instance.session_overrides[event.unified_msg_origin] is expected
            assert len(event.sent) == 1
            assert ("开启" if expected else "关闭") in event.sent[0]
            if not expected:
                query = Event(f"{profile.command} 纳西妲")
                assert "未启用" in [r async for r in handler(query)][0]

        denied = Event(f"{profile.command} session off")
        assert "管理员" in [r async for r in handler(denied)][0]
        assert instance._allowed(denied)
        invalid = Event(f"{profile.command} session invalid", admin=True)
        assert [r async for r in handler(invalid)] == []
        assert "用法" in invalid.sent[0]
        status = Event(f"{profile.command} session", admin=True)
        assert [r async for r in handler(status)] == []
        assert "开启" in status.sent[0]

    asyncio.run(check())


@pytest.mark.parametrize("layout", ["fresh", "legacy", "new", "both", "canonical"])
def test_session_switch_survives_reload_for_all_directory_layouts(plugin, layout):
    instance, Event, module = plugin
    root = Path(module.get_astrbot_data_path()) / "plugin_data"
    if layout in {"legacy", "both"}:
        (root / "genshinimpactsearch").mkdir(parents=True)
    if layout in {"new", "both"}:
        (root / "gamewiki").mkdir(parents=True)
    if layout == "canonical":
        for name in ("astrbot_plugin_gamewiki", "gamewiki", "genshinimpactsearch"):
            (root / name).mkdir(parents=True)

    async def check():
        first = type(instance)(object(), {})
        second = None
        try:
            event = Event("ys session off", admin=True)
            assert [r async for r in first.wiki_command_ys(event)] == []
            selected = (
                "genshinimpactsearch"
                if layout == "legacy"
                else "gamewiki"
                if layout in {"new", "both"}
                else "astrbot_plugin_gamewiki"
            )
            assert first.data_dir == root / selected
            assert (first.data_dir / "session-overrides.json").is_file()
            await first.cache.put("upgrade-check", {"kept": True}, 60)
            fonts = first.data_dir / "fonts"
            fonts.mkdir()
            (fonts / "override.ttf").write_bytes(b"existing-font-override")
            second = type(instance)(object(), {})
            assert not second._allowed(event)
            assert await second.cache.get("upgrade-check") == {"kept": True}
            assert (second.data_dir / "fonts" / "override.ttf").read_bytes() == (
                b"existing-font-override"
            )
        finally:
            await first.terminate()
            if second:
                await second.terminate()

    asyncio.run(check())


@pytest.mark.parametrize("raw", ["[]", "null", '"text"', "{invalid"])
def test_invalid_session_file_does_not_break_startup(plugin, raw):
    instance, _, _ = plugin
    instance.data_dir.mkdir(parents=True)
    (instance.data_dir / "session-overrides.json").write_text(raw, encoding="utf-8")
    assert instance._load_session_overrides(instance.data_dir) == {}


def test_session_file_accepts_only_boolean_values(plugin):
    instance, _, _ = plugin
    instance.data_dir.mkdir(parents=True)
    (instance.data_dir / "session-overrides.json").write_text(
        json.dumps({"off": False, "on": True, "string": "false", "number": 1}),
        encoding="utf-8",
    )
    assert instance._load_session_overrides(instance.data_dir) == {
        "off": False,
        "on": True,
    }


def test_failed_session_save_keeps_previous_file_and_notifies_admin(plugin):
    instance, Event, _ = plugin
    assert instance._save_session_overrides(instance.data_dir)
    original = (instance.data_dir / "session-overrides.json").read_bytes()

    async def check():
        event = Event("ys session off", admin=True)
        with patch.object(Path, "replace", side_effect=OSError("read-only")):
            assert [r async for r in instance.wiki_command_ys(event)] == []
        assert "仅本次运行生效" in event.sent[0]
        assert not instance._allowed(event)
        assert (instance.data_dir / "session-overrides.json").read_bytes() == original

    asyncio.run(check())


@pytest.mark.parametrize("error", ["wiki", "timeout", "unexpected", "long_input"])
def test_public_command_sends_error_reply_without_secondary_exception(plugin, error):
    instance, Event, module = plugin
    errors = {
        "wiki": module.WikiError("upstream", "模拟上游错误"),
        "timeout": asyncio.TimeoutError(),
        "unexpected": RuntimeError("模拟异常"),
    }
    if error != "long_input":
        instance.services["ys"].search = AsyncMock(side_effect=errors[error])
    text = "名" * 301 if error == "long_input" else "纳西妲"
    event = Event(f"ys {text}")
    replies = asyncio.run(_collect(instance.wiki_command_ys(event)))
    assert replies == []
    expected = {
        "wiki": "模拟上游错误",
        "timeout": "查询超时",
        "unexpected": "百科查询异常",
        "long_input": "1–300",
    }
    assert len(event.sent) == 1 and expected[error] in event.sent[0]


async def _collect(handler):
    return [reply async for reply in handler]


def _wiki_page(title="纳西妲", page_id=42):
    return {
        "status": "ok",
        "title": title,
        "page_id": page_id,
        "url": f"https://wiki.biligame.com/ys/{title}",
        "available_sections": ["突破", "元素战技"],
        "evidence": [{"section": "突破", "text": "需要劫波莲。"}],
    }


@pytest.mark.parametrize("game", ["ys", "sr", "zzz", "arknights", "zmd", "sts2"])
def test_numbered_choices_and_plain_followups_use_selected_page_id(plugin, game):
    instance, Event, module = plugin
    search = AsyncMock(
        return_value={
            "status": "needs_choice",
            "query": "测试",
            "question": "突破材料",
            "candidates": [
                {"title": "目标角色", "page_id": 9, "url": "https://example.test/9"}
            ],
        }
    )
    read = AsyncMock(return_value=_wiki_page("目标角色", 9))
    instance.services[game] = SimpleNamespace(search=search, read=read)
    handler = getattr(instance, f"wiki_command_{game}")
    command = module.PROFILES[game].command

    async def check():
        query = Event(f"{command} 测试 突破材料")
        assert [r async for r in handler(query)] == []
        assert "1. 目标角色" in query.sent[0] and "2分钟内回复编号" in query.sent[0]
        choice = Event("1")
        await instance.wiki_followup(choice)
        assert choice.stopped and choice.message_str == "1"
        read.assert_awaited_once_with(9, "突破材料")
        assert "已选择【目标角色】" in choice.sent[0]
        followup = Event("战技10级呢")
        await instance.wiki_followup(followup)
        assert followup.stopped
        assert "继续查询【目标角色】" in followup.sent[0]
        assert read.await_args.args == (9, "战技10级呢")
        command_followup = Event(f"{command} 突破材料呢")
        assert [r async for r in handler(command_followup)] == []
        assert read.await_args.args == (9, "突破材料呢")
        assert search.await_count == 1

    asyncio.run(check())


@pytest.mark.parametrize("source", ["prts", "bwiki"])
def test_ark_candidates_and_followups_keep_their_source(plugin, source):
    instance, Event, module = plugin
    candidates = {
        "status": "needs_choice",
        "query": "测试",
        "question": "技能",
        "candidates": [
            {"title": "能天使", "page_id": 7, "url": "https://example.test/7"}
        ],
    }
    primary = SimpleNamespace(
        aliases={},
        search=AsyncMock(return_value=candidates),
        read=AsyncMock(return_value=_wiki_page("能天使", 7)),
    )
    backup = SimpleNamespace(
        aliases={},
        search=AsyncMock(return_value=candidates),
        read=AsyncMock(return_value=_wiki_page("能天使", 7)),
    )
    if source == "bwiki":
        primary.search.return_value = {"status": "not_found"}
    instance.services["arknights"] = module.ArknightsSources(primary, backup)

    async def check():
        initial = Event("ark 测试 技能")
        await _collect(instance.wiki_command_arknights(initial))
        if source == "bwiki":
            assert "已改用明日方舟 BWIKI" in initial.sent[0]
        chosen = Event("1")
        await instance.wiki_followup(chosen)
        followup = Event("技能3倍率")
        await instance.wiki_followup(followup)
        selected, other = (primary, backup) if source == "prts" else (backup, primary)
        assert selected.read.await_count == 2
        assert selected.read.await_args.args == (7, "技能3倍率", "")
        other.read.assert_not_awaited()
        assert instance.recent_sources["arknights"] == source

    asyncio.run(check())


def test_ark_tool_reads_require_explicit_source(plugin):
    instance, Event, module = plugin
    profile = PROFILES["arknights"]
    primary = SimpleNamespace(
        aliases={}, profile=profile, read=AsyncMock(return_value=_wiki_page())
    )
    backup = SimpleNamespace(
        aliases={}, profile=profile, read=AsyncMock(return_value=_wiki_page())
    )
    instance.services["arknights"] = module.ArknightsSources(primary, backup)

    async def check():
        result = json.loads(
            await instance.wiki_read(Event(), 42, "", "技能", "arknights")
        )
        assert result["code"] == "bad_input"
        primary.read.assert_not_awaited()
        backup.read.assert_not_awaited()
        result = json.loads(
            await instance.wiki_read(Event(), 42, "", "技能", "arknights", "bwiki")
        )
        assert result["source_key"] == "bwiki"
        backup.read.assert_awaited_once_with(42, "技能", "")
        primary.read.assert_not_awaited()

    asyncio.run(check())


def test_choices_are_isolated_and_do_not_consume_unrelated_messages(plugin):
    instance, Event, _ = plugin
    service = instance.services["ys"]
    service.search = AsyncMock(
        return_value={
            "status": "needs_choice",
            "query": "测试",
            "question": "技能",
            "candidates": [
                {"title": "角色", "page_id": 9, "url": "https://example.test/9"}
            ],
        }
    )
    service.read = AsyncMock(return_value=_wiki_page("角色", 9))

    async def check():
        await _collect(instance.wiki_command_ys(Event("ys 测试 技能")))
        other_user = Event("1")
        other_user.get_sender_id = lambda: "other-user"
        other_group = Event("1", origin="other:GroupMessage:2")
        for event in (other_user, other_group, Event("天气怎么样"), Event("/ys 1")):
            await instance.wiki_followup(event)
            assert not event.stopped and not event.sent
        invalid = Event("ys 2")
        assert "1–1" in (await _collect(instance.wiki_command_ys(invalid)))[0]
        wrong_game = Event("sr 1")
        assert "属于原神" in (await _collect(instance.wiki_command_sr(wrong_game)))[0]
        service.read.assert_not_awaited()
        assert service.search.await_count == 1
        correct = Event("ys 1")
        assert await _collect(instance.wiki_command_ys(correct)) == []
        assert "已选择" in correct.sent[0]

    asyncio.run(check())


def test_expired_choices_and_topic_cannot_be_reused(plugin):
    instance, Event, _ = plugin
    service = instance.services["ys"]
    service.search = AsyncMock(return_value=_wiki_page())
    service.read = AsyncMock()

    async def check():
        with patch("qa_plugin.wiki.conversation.time.monotonic", return_value=100):
            await _collect(instance.wiki_command_ys(Event("ys 纳西妲")))
        with patch("qa_plugin.wiki.conversation.time.monotonic", return_value=701):
            event = Event("突破材料呢")
            await instance.wiki_followup(event)
            assert not event.sent and not event.stopped
            reply = await _collect(instance.wiki_command_ys(Event("ys 突破材料呢")))
            assert "上下文已过期" in reply[0]
            reply = await _collect(instance.wiki_command_ys(Event("ys 1")))
            assert "候选已过期" in reply[0]
        service.read.assert_not_awaited()

    asyncio.run(check())


def test_explicit_new_entity_and_game_replace_topic_without_leaking_context(plugin):
    instance, Event, _ = plugin
    instance.services["ys"].search = AsyncMock(return_value=_wiki_page())
    instance.services["ys"].read = AsyncMock()
    instance.services["sr"].search = AsyncMock(return_value=_wiki_page("流萤", 7))
    instance.services["sr"].read = AsyncMock(return_value=_wiki_page("流萤", 7))

    async def check():
        await _collect(instance.wiki_command_ys(Event("ys 纳西妲")))
        wrong = await _collect(instance.wiki_command_sr(Event("sr 突破材料呢")))
        assert "已切换" in wrong[0]
        instance.services["sr"].read.assert_not_awaited()
        no_topic = Event("突破材料呢")
        await instance.wiki_followup(no_topic)
        assert not no_topic.stopped and not no_topic.sent
        await _collect(instance.wiki_command_sr(Event("sr 流萤")))
        followup = Event("战技10级呢")
        await instance.wiki_followup(followup)
        assert "流萤" in followup.sent[0] and "崩坏" in followup.sent[0]
        instance.services["sr"].read.assert_awaited_once_with(7, "战技10级呢")
        instance.services["ys"].read.assert_not_awaited()

    asyncio.run(check())


def test_candidate_expiration_and_missing_sender_do_not_share_state(plugin):
    instance, Event, _ = plugin
    instance.services["ys"].search = AsyncMock(
        return_value={
            "status": "needs_choice",
            "query": "测试",
            "question": "",
            "candidates": [
                {"title": "角色", "page_id": 9, "url": "https://example.test/9"}
            ],
        }
    )
    instance.services["ys"].read = AsyncMock()

    async def check():
        unknown = Event("ys 测试")
        unknown.get_sender_id = lambda: ""
        await _collect(instance.wiki_command_ys(unknown))
        assert "2分钟内回复编号" not in unknown.sent[0]
        assert not instance.conversations._entries
        with patch("qa_plugin.wiki.conversation.time.monotonic", return_value=100):
            await _collect(instance.wiki_command_ys(Event("ys 测试")))
        with patch("qa_plugin.wiki.conversation.time.monotonic", return_value=221):
            plain = Event("1")
            await instance.wiki_followup(plain)
            assert not plain.stopped and not plain.sent
            reply = await _collect(instance.wiki_command_ys(Event("ys 1")))
            assert "候选已过期" in reply[0]
        instance.services["ys"].read.assert_not_awaited()

    asyncio.run(check())


def test_conversation_toggle_and_limits_apply_to_plain_replies(plugin):
    instance, Event, _ = plugin
    service = instance.services["ys"]
    service.search = AsyncMock(return_value=_wiki_page())
    service.read = AsyncMock(return_value=_wiki_page())

    async def check():
        await _collect(instance.wiki_command_ys(Event("ys 纳西妲")))
        instance.conversation_enabled = False
        event = Event("突破材料呢")
        await instance.wiki_followup(event)
        assert not event.stopped and not event.sent
        instance.conversation_enabled = True
        instance.limiter = type(instance.limiter)(cooldown=0, per_user=1)
        instance._limited(Event(""))
        limited = Event("突破材料呢")
        await instance.wiki_followup(limited)
        assert limited.stopped and "上限" in limited.sent[0]
        service.read.assert_not_awaited()
        instance.session_overrides[limited.unified_msg_origin] = False
        disabled = Event("突破材料呢")
        await instance.wiki_followup(disabled)
        assert not disabled.stopped and not disabled.sent

    asyncio.run(check())


def test_doctor_handles_provider_timeout_and_cache_failure(plugin):
    instance, Event, _ = plugin
    instance.model_timeout = 0.01
    instance.cache.health = AsyncMock(
        return_value={
            "readable": False,
            "writable": False,
            "entries": 0,
            "bytes": 0,
        }
    )

    async def slow(**kwargs):
        await asyncio.sleep(1)

    instance.context = SimpleNamespace(get_current_chat_provider_id=slow)
    event = Event("ys doctor", admin=True)
    assert asyncio.run(_collect(instance.wiki_command_ys(event))) == []
    assert "读取失败" in event.sent[0] and "缓存读取：失败" in event.sent[0]


@pytest.mark.parametrize("whitelist_allows", [False, True])
def test_session_reset_restores_config_and_persists(plugin, whitelist_allows):
    instance, Event, _ = plugin
    event = Event("ys session reset", admin=True)
    instance.sessions = {event.unified_msg_origin} if whitelist_allows else {"other"}
    instance.session_overrides[event.unified_msg_origin] = not whitelist_allows
    assert asyncio.run(_collect(instance.wiki_command_ys(event))) == []
    assert instance._allowed(event) is whitelist_allows
    assert "跟随配置" in event.sent[0] and "配置白名单" in event.sent[0]
    assert instance._load_session_overrides(instance.data_dir) == {}


def test_doctor_is_admin_only_local_and_reports_degradation(plugin):
    instance, Event, _ = plugin
    provider = AsyncMock(return_value="configured-provider")
    instance.context = SimpleNamespace(get_current_chat_provider_id=provider)
    instance.recent_outcomes["ys"] = "overview_rejected"
    for client in instance.clients:
        client._fetch = AsyncMock(side_effect=AssertionError("unexpected network"))

    async def check():
        denied = await _collect(instance.wiki_command_ys(Event("ys doctor")))
        assert "管理员" in denied[0]
        provider.assert_not_awaited()
        event = Event("ys doctor", admin=True)
        instance.session_overrides[event.unified_msg_origin] = False
        assert await _collect(instance.wiki_command_ys(event)) == []
        assert "ys, sr" in event.sent[0]
        assert "缓存读取：正常" in event.sent[0] and "目录写入：正常" in event.sent[0]
        assert "未验证实际调用" in event.sent[0] and "数字校验" in event.sent[0]
        assert "关闭" in event.sent[0]
        for client in instance.clients:
            client._fetch.assert_not_awaited()
        provider.side_effect = RuntimeError("private-provider-detail")
        event = Event("ys doctor", admin=True)
        await _collect(instance.wiki_command_ys(event))
        assert (
            "读取失败" in event.sent[0]
            and "private-provider-detail" not in event.sent[0]
        )

    asyncio.run(check())


def test_clear_cache_clears_shared_http_cache_once(plugin):
    instance, Event, _ = plugin
    instance.cache.clear = AsyncMock(return_value=7)
    for service in instance.services.values():
        service.clear_parse_cache = AsyncMock(return_value=2)
    replies = asyncio.run(
        _collect(instance.wiki_command_ys(Event("ys clear-cache", admin=True)))
    )
    instance.cache.clear.assert_awaited_once()
    assert "HTTP 条目 7 条" in replies[0] and "已解析页面 4 个" in replies[0]
    for service in instance.services.values():
        service.clear_parse_cache.assert_awaited_once()


def test_entry_image_is_sent_once_per_topic_window(plugin):
    import contextlib

    instance, Event, module = plugin
    downloads = []

    @contextlib.asynccontextmanager
    async def fake_image(url, cache=None):
        downloads.append(url)
        yield "/tmp/fake-portrait.jpg"

    event = Event("")
    event.image_result = lambda path: ("image", path)
    with patch.object(module, "prepared_image", fake_image):
        asyncio.run(instance._send_entry_image(event, "https://example.org/a.png"))
        asyncio.run(instance._send_entry_image(event, "https://example.org/a.png"))
        asyncio.run(instance._send_entry_image(event, "https://example.org/b.png"))
    assert downloads == ["https://example.org/a.png", "https://example.org/b.png"]


def test_failed_image_send_is_not_marked_as_sent(plugin):
    import contextlib

    instance, Event, module = plugin

    @contextlib.asynccontextmanager
    async def failing_image(url, cache=None):
        raise RuntimeError("download failed")
        yield ""

    event = Event("")
    with patch.object(module, "prepared_image", failing_image):
        asyncio.run(instance._send_entry_image(event, "https://example.org/a.png"))
    assert not instance._recent_images


def test_evidence_card_is_rendered_locally_and_sent(plugin):
    instance, Event, module = plugin
    event = Event("")
    event.image_result = lambda path: ("image", path)
    accent = (196, 148, 38)

    def fake_render(title, source, sections, accent_arg=(), *, font_dir=None):
        assert title == "汤汤" and source == "终末地 AKEData"
        assert sections == [("战技", "伤害 320%")]
        assert accent_arg == accent
        assert font_dir == instance.data_dir / "fonts"
        return b"\x89PNG-fake"

    with patch.object(module, "render_card", fake_render):
        asyncio.run(
            instance._send_card(
                event,
                {
                    "title": "汤汤",
                    "source": "终末地 AKEData",
                    "sections": [("战技", "伤害 320%")],
                },
                accent,
            )
        )
    assert event.sent == [("image", str(event.sent[0][1]))]


def test_evidence_card_carries_the_game_accent(plugin):
    from wiki.games import PROFILES

    instance, Event, module = plugin
    service = instance.services["ys"]
    service.search = AsyncMock(return_value=_wiki_page())
    provider = AsyncMock(return_value="configured-provider")
    instance.context = SimpleNamespace(
        get_current_chat_provider_id=provider,
        llm_generate=AsyncMock(
            return_value=SimpleNamespace(completion_text="需要劫波莲。")
        ),
    )
    event = Event("ys 纳西妲 突破")
    event.image_result = lambda path: ("image", path)
    captured = {}

    def fake_render(title, source, sections, accent=(), *, font_dir=None):
        captured["accent"] = accent
        return b"\x89PNG-fake"

    with patch.object(module, "render_card", fake_render):
        asyncio.run(_collect(instance.wiki_command_ys(event)))
    assert captured["accent"] == PROFILES["ys"].accent
    assert len(event.sent) == 2 and event.sent[1][0] == "image"


def test_evidence_card_is_skipped_when_the_reply_falls_back_to_excerpt(plugin):
    instance, Event, module = plugin
    service = instance.services["ys"]
    service.search = AsyncMock(return_value=_wiki_page())
    # object() context makes every model call fail, forcing the excerpt path.
    event = Event("ys 纳西妲突破")
    event.image_result = lambda path: ("image", path)

    with patch.object(module, "render_card") as render:
        asyncio.run(_collect(instance.wiki_command_ys(event)))
    render.assert_not_called()
    assert len(event.sent) == 1 and "劫波莲" in event.sent[0]


def test_evidence_card_without_font_or_on_error_sends_nothing(plugin):
    instance, Event, module = plugin
    event = Event("")
    with patch.object(module, "render_card", lambda *a, **kw: None):
        asyncio.run(
            instance._send_card(event, {"title": "t", "source": "s", "sections": []})
        )
    with patch.object(
        module, "render_card", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x"))
    ):
        asyncio.run(
            instance._send_card(event, {"title": "t", "source": "s", "sections": []})
        )
    assert event.sent == []


def test_doctor_reports_the_plugin_directory_font(plugin):
    instance, Event, module = plugin
    regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not regular.exists():
        pytest.skip("no font for the local font directory check")
    directory = instance.data_dir / "fonts"
    directory.mkdir(parents=True)
    font = directory / "MiSans-Regular.ttf"
    font.write_bytes(regular.read_bytes())
    text = asyncio.run(instance._doctor_text(Event("ys doctor")))
    assert str(directory) in text
    assert str(font) in text
    assert "DejaVu Sans" in text


def test_tool_search_normalizes_question_slang(plugin):
    # AI 工具路径与命令路径同一套黑话归一，README 的自然语言示例
    # （"纳西妲平A倍率"）在工具路径同样命中原神普攻分节。
    instance, Event, _ = plugin
    captured = {}

    async def fake_search(query, question=""):
        captured["question"] = question
        return {"status": "ok"}

    instance.services["ys"].search = fake_search
    result = asyncio.run(
        instance._tool_search(Event(), "纳西妲", "纳西妲平A倍率", "ys")
    )
    assert result["status"] == "ok"
    assert captured["question"] == "纳西妲普攻倍率"


def test_tool_read_normalizes_question_slang(plugin):
    instance, Event, module = plugin
    captured = {}

    async def fake_read(page_id, question, section):
        captured["question"] = question
        return {"status": "ok"}

    instance.services["ys"].read = fake_read
    result = asyncio.run(instance._tool_read(Event(), 42, "", "满命效果", "ys"))
    assert result["status"] == "ok"
    assert captured["question"] == "命之座效果"

    # 双源游戏走 SourceRouter，profile 取自主源服务。
    async def router_read(page_id, question, section, source=""):
        captured["question"] = question
        return {"status": "ok", "source_key": source}

    ark_profile = PROFILES["arknights"]
    instance.services["arknights"] = module.ArknightsSources(
        SimpleNamespace(aliases={}, profile=ark_profile, read=router_read),
        SimpleNamespace(aliases={}, profile=ark_profile, read=router_read),
    )
    result = asyncio.run(
        instance._tool_read(Event(), 42, "", "专三材料", "arknights", "prts")
    )
    assert result["source_key"] == "prts"
    assert captured["question"] == "专精材料"


def test_schema_declares_model_provider_default(plugin):
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    assert schema["model_provider"]["type"] == "string"
    assert schema["model_provider"]["default"] == ""
    # WebUI 用官方提供商选择器渲染下拉框；留空=跟随会话模型。
    assert schema["model_provider"]["_special"] == "select_provider"


def test_configured_model_overrides_the_session_model(plugin):
    instance, Event, _ = plugin
    configured = type(instance)(
        object(),
        {"games": ["ys"], "user_cooldown_seconds": 0, "model_provider": "my-model"},
    )
    try:
        configured.services["ys"].search = AsyncMock(return_value=_wiki_page())
        session = AsyncMock(return_value="session-model")
        llm = AsyncMock(return_value=SimpleNamespace(completion_text="需要劫波莲。"))
        configured.context = SimpleNamespace(
            get_current_chat_provider_id=session, llm_generate=llm
        )
        asyncio.run(_collect(configured.wiki_command_ys(Event("ys 纳西妲 突破"))))
        assert llm.await_args.kwargs["chat_provider_id"] == "my-model"
        session.assert_not_awaited()
    finally:
        asyncio.run(configured.terminate())


def test_configured_model_falls_back_to_the_session_model(plugin):
    instance, Event, _ = plugin
    configured = type(instance)(
        object(),
        {"games": ["ys"], "user_cooldown_seconds": 0, "model_provider": "my-model"},
    )
    try:
        configured.services["ys"].search = AsyncMock(return_value=_wiki_page())
        session = AsyncMock(return_value="session-model")
        llm = AsyncMock(
            side_effect=[
                RuntimeError("unknown provider"),
                SimpleNamespace(completion_text="需要劫波莲。"),
            ]
        )
        configured.context = SimpleNamespace(
            get_current_chat_provider_id=session, llm_generate=llm
        )
        asyncio.run(_collect(configured.wiki_command_ys(Event("ys 纳西妲 突破"))))
        assert [call.kwargs["chat_provider_id"] for call in llm.await_args_list] == [
            "my-model",
            "session-model",
        ]
        assert configured.model_fallback_hits == 1
    finally:
        asyncio.run(configured.terminate())


def test_doctor_reports_the_configured_model(plugin):
    instance, Event, _ = plugin
    instance.model_provider = "my-model"
    instance.model_fallback_hits = 2
    instance.context = SimpleNamespace(
        get_current_chat_provider_id=AsyncMock(return_value="session-model")
    )
    text = asyncio.run(instance._doctor_text(Event()))
    assert "插件模型：固定使用 my-model" in text
    assert "已回退会话模型 2 次" in text


def test_zmd_tool_read_uses_the_endfield_profile(plugin):
    """EndfieldSources.profile 取自主源；AkeService 必须带 profile 契约。"""
    instance, Event, _ = plugin
    configured = type(instance)(
        object(), {"games": ["zmd"], "user_cooldown_seconds": 0}
    )
    try:
        router = configured.services["zmd"]
        assert router.profile.code == "zmd"
        captured = {}

        async def fake_read(page_id, question, section):
            captured["question"] = question
            return {"status": "ok", "title": "祀"}

        router.primary.read = fake_read
        result = asyncio.run(
            configured._tool_read(Event(), 123, "", "满潜", "zmd", "akedata")
        )
        assert result["status"] == "ok"
        assert captured["question"] == "潜能"
    finally:
        asyncio.run(configured.terminate())


def test_query_notice_precedes_the_answer(plugin):
    instance, Event, _ = plugin
    configured = type(instance)(
        object(),
        {"games": ["ys"], "user_cooldown_seconds": 0, "image_reply": False},
    )
    try:
        configured.services["ys"].search = AsyncMock(return_value=_wiki_page())
        configured.context = SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="p"),
            llm_generate=AsyncMock(
                return_value=SimpleNamespace(completion_text="需要劫波莲。")
            ),
        )
        event = Event("ys 纳西妲 突破")
        asyncio.run(_collect(configured.wiki_command_ys(event)))
        assert event.sent[0] == "正在查询原神百科，请稍候…"
        assert len(event.sent) == 2 and "劫波莲" in event.sent[1]
    finally:
        asyncio.run(configured.terminate())


def test_query_notice_can_be_disabled(plugin):
    instance, Event, _ = plugin
    configured = type(instance)(
        object(),
        {
            "games": ["ys"],
            "user_cooldown_seconds": 0,
            "image_reply": False,
            "query_notice": False,
        },
    )
    try:
        configured.services["ys"].search = AsyncMock(return_value=_wiki_page())
        configured.context = SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="p"),
            llm_generate=AsyncMock(
                return_value=SimpleNamespace(completion_text="需要劫波莲。")
            ),
        )
        event = Event("ys 纳西妲 突破")
        asyncio.run(_collect(configured.wiki_command_ys(event)))
        assert len(event.sent) == 1 and "正在查询" not in event.sent[0]
    finally:
        asyncio.run(configured.terminate())


def test_query_notice_is_skipped_for_help(plugin):
    instance, Event, _ = plugin
    configured = type(instance)(object(), {"games": ["ys"]})
    try:
        event = Event("ys help")
        asyncio.run(_collect(configured.wiki_command_ys(event)))
        assert len(event.sent) == 1 and "用法：" in event.sent[0]
    finally:
        asyncio.run(configured.terminate())


def test_wiki_compare_tool_only_supports_sts2(plugin):
    instance, Event, module = plugin
    instance.services["sts2"] = SimpleNamespace(
        profile=module.PROFILES["sts2"],
        compare=AsyncMock(return_value={"status": "compare", "game": "sts2"}),
    )
    ok = json.loads(
        asyncio.run(instance.wiki_compare(Event(), "燃烧之血", "红头骨", "", "sts2"))
    )
    assert ok["status"] == "compare"
    unsupported = json.loads(
        asyncio.run(instance.wiki_compare(Event(), "草神", "钟离", "", "ys"))
    )
    assert unsupported["code"] == "unsupported"
