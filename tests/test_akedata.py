"""Small synthetic tables exercise the public AKEData wire format."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from wiki.akedata import AkeClient, AkeService, entry_id, render
from wiki.cache import Cache
from wiki.models import WikiError
from wiki.sources import EndfieldSources

CHAR = "chr_0036_jsspsi"
NAME_ID = 7549422073270614678  # Must not lose precision through a JS number.
VERSION = "1.6.4@11343132-9"
PATH = "public/1.6.4/11343132-9/TableCfg"


def tables():
    return {
        "CharacterTable": {
            CHAR: {
                "name": {"id": NAME_ID, "text": ""},
                "rarity": 6,
                "engName": "Si",
                "profession": 4,
                "charTypeId": "Cryst",
                "attributes": [
                    {
                        "breakStage": 0,
                        "Attribute": {
                            "attrs": [
                                {"attrType": 0, "attrValue": 1},
                                {"attrType": 1, "attrValue": 500},
                                {"attrType": 39, "attrValue": 17.01},
                            ]
                        },
                    }
                ],
            }
        },
        "ItemTable": {
            "item_user_avatar_" + CHAR: {"name": {"id": NAME_ID}, "rarity": 4},
            "item_test": {
                "name": {"id": -9007199254740993},
                "rarity": 2,
                "desc": "测试材料",
            },
            "wpn_test": {"name": {"text": "测试武器"}, "rarity": 6},
        },
        "I18nTextTable_CN": {str(NAME_ID): "祀", "-9007199254740993": "培养试剂"},
        "CharGrowthTable": {
            CHAR: {
                "skillGroupMap": {
                    "skill": {
                        "name": {"text": "示例技能"},
                        "skillGroupType": 1,
                        "desc": {"text": "造成<@ba.cryst>{atk_scale:0%}</>伤害。"},
                        "skillIdList": ["skill"],
                    }
                },
                "skillLevelUp": [
                    {
                        "skillGroupId": "skill",
                        "level": 2,
                        "goldCost": 1000,
                        "itemBundle": [{"id": "item_test", "count": 6}],
                    }
                ],
            }
        },
        "SkillPatchTable": {
            "skill": {
                "SkillPatchDataBundle": [
                    {
                        "level": 1,
                        "blackboard": [{"key": "atk_scale", "value": 1.2}],
                        "subDescDataList": [
                            {"name": {"text": "伤害倍率"}, "desc": "120%"}
                        ],
                    }
                ]
            }
        },
        "CharProfessionTable": {"4": {"name": {"text": "辅助"}}},
        "CharTypeTable": {"Cryst": {"name": {"text": "寒冷"}}},
        "WeaponBasicTable": {"wpn_test": {"weaponDesc": {"text": "测试武器故事"}}},
    }


def setup(tmp_path, handler=None):
    calls = []
    data = tables()

    def respond(request):
        calls.append(request.url)
        assert request.url.host == "data.akedata.wiki"
        if handler:
            result = handler(request)
            if result is not None:
                return result
        if request.url.path == "/manifest.json":
            return httpx.Response(
                200,
                json={
                    "latest": VERSION,
                    "versions": [
                        {
                            "id": VERSION,
                            "tableCfgPath": PATH,
                            "publishedAt": "2026-10-27T10:04:23+08:00",
                        }
                    ],
                },
            )
        assert request.url.path.startswith("/" + PATH + "/")
        name = request.url.path.rsplit("/", 1)[1][:-5]
        return httpx.Response(200, json=data[name])

    client = AkeClient(Cache(tmp_path), transport=httpx.MockTransport(respond), pace=0)
    return client, AkeService(client), calls, data


def test_chinese_ids_skills_materials_candidates_and_source_reads(tmp_path):
    async def run():
        client, service, calls, _ = setup(tmp_path)
        try:
            result = await service.search("祀", "战技")
            assert result["status"] == "ok"
            assert result["source_key"] == "akedata"
            assert result["page_id"] == entry_id(CHAR)
            assert result["data_version"] == VERSION
            assert "plugin=character&id=" + CHAR in result["url"]
            assert result["image_url"].endswith("/characterportrait/" + CHAR + ".png")
            body = "\n".join(e["text"] for e in result["evidence"])
            assert "等级1" in body and "120%" in body
            assert "示例技能" in result["evidence"][0]["section"]
            assert "<@" not in body and "{atk_scale" not in body
            material = await service.read(result["page_id"], "培养材料")
            assert "培养试剂×6" in str(material["evidence"])
            assert "折金票×1000" in str(material["evidence"])
            count = len(calls)
            assert (await service.search("Si"))["title"] == "祀"
            assert len(calls) == count  # Versioned tables share the disk cache.
            assert (await service.search("培养"))["status"] == "needs_choice"
            assert (await service.search("不存在"))["status"] == "not_found"
            assert (await service.search("祀", "配队"))["status"] == "section_not_found"
            assert (await service.search("测试武器"))["status"] == "ok"
            assert (await service.search("测试武器", "技能"))[
                "status"
            ] == "section_not_found"
            with pytest.raises(WikiError, match="page_id"):
                await service.read(True)
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    ["timeout", "forbidden", "rate_limited", "not_found", "section_not_found"],
)
def test_endfield_fallback_and_pinned_reads(failure):
    async def run():
        class Service:
            aliases = {}
            search = AsyncMock()
            read = AsyncMock(return_value={"status": "ok"})

        primary, backup = Service(), Service()
        # Instance mocks must not share call history.
        primary.search = AsyncMock(return_value={"status": failure})
        backup.search = AsyncMock(return_value={"status": "ok"})
        primary.read, backup.read = (
            AsyncMock(),
            AsyncMock(return_value={"status": "ok"}),
        )
        if failure not in {"not_found", "section_not_found"}:
            primary.search.side_effect = WikiError(failure, "source unavailable")
        router = EndfieldSources(primary, backup)
        result = await router.search("祀")
        assert result["source_key"] == "bwiki" and result["fallback_from"] == "akedata"
        await router.read(7, source="bwiki")
        primary.read.assert_not_awaited()
        with pytest.raises(WikiError, match="source_key"):
            await router.read(7)
        primary.read.side_effect = WikiError("not_found", "missing")
        with pytest.raises(WikiError):
            await router.read(7, source="akedata")
        backup.read.assert_awaited_once_with(7, "", "")

    asyncio.run(run())


@pytest.mark.parametrize(
    "path",
    [
        "public/../foo/TableCfg",
        "https://evil.test/TableCfg",
        "public/1.6.4/../TableCfg",
    ],
)
def test_untrusted_manifest_cannot_choose_arbitrary_resources(tmp_path, path):
    async def run():
        def response(request):
            return httpx.Response(
                200,
                json={
                    "latest": VERSION,
                    "versions": [{"id": VERSION, "tableCfgPath": path}],
                },
            )

        client, service, calls, _ = setup(tmp_path, response)
        try:
            with pytest.raises(WikiError, match="版本清单"):
                await service.search("祀")
            assert len(calls) == 1
        finally:
            await client.close()

    asyncio.run(run())


def test_malformed_data_falls_back(tmp_path):
    async def run():
        client, primary, _, data = setup(tmp_path)
        backup = type(
            "Backup", (), {"search": AsyncMock(return_value={"status": "ok"})}
        )()
        try:
            data["CharGrowthTable"][CHAR] = []  # Valid JSON, unexpected schema.
            result = await EndfieldSources(primary, backup).search("祀")
            assert result["fallback_from"] == "akedata"
            assert client.source == "akedata"
            await client.cache.clear()
            with pytest.raises(WikiError):
                await client.request(
                    {"path": "/public/1.6.4/hotfix/TableCfg/SecretTable.json"}, 0
                )
        finally:
            await client.close()

    asyncio.run(run())


def test_placeholder_arithmetic_is_safe_and_missing_values_are_explicit():
    assert render("<@x>{ATK_SCALE*2:0.0%}</>", {"atk_scale": 0.125}) == "25.0%"
    assert render("{missing:0%}", {}) == "［数值未解析］"
    assert render('{__import__("os").getcwd()}', {}) == "［数值未解析］"
    assert render("{1/0}", {}) == "［数值未解析］"


def test_version_refresh_uses_new_snapshot_instead_of_old_table_cache(tmp_path):
    async def run():
        client, service, calls, data = setup(tmp_path)
        service.search_ttl = 0
        try:
            assert (await service.search("祀"))["data_version"] == VERSION
            replacement = PATH.replace("11343132-9", "next-hotfix")
            previous = client.http._transport

            async def updated(request):
                calls.append(request.url)
                if request.url.path == "/manifest.json":
                    return httpx.Response(
                        200,
                        json={
                            "latest": "next",
                            "versions": [
                                {
                                    "id": "next",
                                    "tableCfgPath": replacement,
                                }
                            ],
                        },
                    )
                assert replacement in request.url.path
                name = request.url.path.rsplit("/", 1)[1][:-5]
                return httpx.Response(200, json=data[name])

            client.http._transport = httpx.MockTransport(updated)
            result = await service.search("祀")
            assert result["data_version"] == "next"
            assert any(
                replacement + "/CharacterTable.json" in str(url) for url in calls
            )
            await previous.aclose()
        finally:
            await client.close()

    asyncio.run(run())


def test_requested_level_talents_potentials_and_unavailable_sections(tmp_path):
    async def run():
        client, service, _, data = setup(tmp_path)
        data["SkillPatchTable"]["skill"]["SkillPatchDataBundle"].append(
            {
                "level": 2,
                "blackboard": [{"key": "atk_scale", "value": 1.5}],
                "subDescDataList": [{"name": {"text": "伤害倍率"}, "desc": "150%"}],
            }
        )
        data["PotentialTalentEffectTable"] = {
            "talent": {
                "desc": {"text": "攻击力+{bonus:0%}。"},
                "dataList": [
                    {
                        "skillBbModifier": {
                            "bbKey": "bonus",
                            "floatValue": 0.2,
                            "modifyType": 1,
                        }
                    }
                ],
            }
        }
        data["CharacterPotentialTable"] = {
            CHAR: {
                "potentialUnlockBundle": [
                    {
                        "level": 1,
                        "name": {"text": "示例潜能"},
                        "potentialEffectId": "talent",
                    }
                ]
            }
        }
        data["CharGrowthTable"][CHAR]["talentNodeMap"] = {
            "talent": {
                "passiveSkillNodeInfo": {
                    "talentEffectId": "talent",
                    "name": {"text": "示例天赋"},
                    "level": 1,
                },
            }
        }
        try:
            result = await service.search("祀", "战技2级")
            assert "150%" in str(result["evidence"])
            assert "等级1" not in str(result["evidence"])
            for question in ("天赋", "潜能"):
                result = await service.search("祀", question)
                assert result["status"] == "ok"
                assert "20%" in str(result["evidence"])
                assert "未解析" not in str(result["evidence"])
            for question in ("战技99级", "配队"):
                result = await service.read(entry_id(CHAR), question, source="akedata")
                assert result["status"] == "section_not_found"
                assert result["title"] == "祀" and not result["evidence"]
                assert result["url"].startswith("https://www.akedata.wiki/")
        finally:
            await client.close()

    asyncio.run(run())


def test_tables_larger_than_mediawiki_response_limit_are_supported(tmp_path):
    async def run():
        client, _, _, _ = setup(
            tmp_path,
            lambda request: httpx.Response(200, json={"text": "a" * (3 << 20)}),
        )
        try:
            data = await client.request(
                {"path": "/" + PATH + "/CharacterTable.json"}, 0
            )
            assert len(data["text"]) == 3 << 20
        finally:
            await client.close()

    asyncio.run(run())


def test_generic_skill_questions_collapse_mid_levels(tmp_path):
    async def run():
        client, service, calls, data = setup(tmp_path)
        data["SkillPatchTable"]["skill"]["SkillPatchDataBundle"] = [
            {
                "level": level,
                "blackboard": [{"key": "atk_scale", "value": 1.0 + level}],
                "subDescDataList": [
                    {"name": {"text": "伤害倍率"}, "desc": f"{level * 10}%"}
                ],
            }
            for level in range(1, 7)
        ]
        try:
            result = await service.search("祀", "技能")
            body = "\n".join(e["text"] for e in result["evidence"])
            assert "等级1" in body and "等级6" in body
            assert "其余4个等级略" in body and "等级3" not in body
            focused = await service.search("祀", "技能3级")
            focused_body = "\n".join(e["text"] for e in focused["evidence"])
            assert "等级3" in focused_body and "其余" not in focused_body
        finally:
            await client.close()

    asyncio.run(run())
