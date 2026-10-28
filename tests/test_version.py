"""Version numbers must stay in sync across all hand-maintained places."""

import re
from pathlib import Path

import yaml

from wiki import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent_across_metadata_changelog_readme_and_user_agent():
    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert metadata["version"] == f"v{VERSION}"

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## v{re.escape(VERSION)} — ", changelog, re.M)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"当前版本：**v{VERSION}**" in readme

    client = (ROOT / "wiki/client.py").read_text(encoding="utf-8")
    assert "from . import VERSION" in client, "User-Agent must embed the VERSION"


def test_plugin_identity_is_unified_under_the_new_name():

    metadata = yaml.safe_load((ROOT / "metadata.yaml").read_text(encoding="utf-8"))
    assert metadata["name"] == "astrbot_plugin_gamewiki"
    assert metadata["repo"] == "https://github.com/KirishimaRin/astrbot_plugin_gamewiki"
    assert metadata["author"] == "KirishimaRin"
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 KirishimaRin" in license_text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "插件标识：`astrbot_plugin_gamewiki`" in readme
    assert "astrbot_plugin_genshinimpactsearch" not in readme

    client = (ROOT / "wiki/client.py").read_text(encoding="utf-8")
    assert "AstrBot-GameWiki/" in client
    assert "GenshinImpactSearch" not in client

    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "class GameWiki" in main_src
    # The legacy data directory may only appear in the compatibility fallback.
    assert main_src.count("genshinimpactsearch") == 1

    package = (ROOT / "scripts/package.py").read_text(encoding="utf-8")
    assert "astrbot_plugin_genshinimpactsearch" not in package
