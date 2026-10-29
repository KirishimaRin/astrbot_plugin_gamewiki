"""Per-game profiles and fixed, allowlisted source endpoints.

Game codes stay stable when a game's preferred source changes. Shared rules
live in cleaning/selection; game terms and source addresses belong here.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameProfile:
    code: str
    name: str
    command: str
    aliases: tuple = ()
    site_aliases: dict = field(default_factory=dict)
    # Extra intent rows appended to selection.INTENTS for this site.
    intents: tuple = ()
    # Question trigger words routed to a specific skill/section label.
    specifics: tuple = ()
    # Search terms that redirect a card-like entry lookup (ys only).
    card_words: tuple = ()
    # Evidence card accent color (RGB); empty falls back to a neutral gray.
    accent: tuple = ()


YS = GameProfile(
    code="ys",
    name="原神",
    command="ys",
    intents=(),
    card_words=("七圣", "卡牌", "角色牌"),
    accent=(64, 145, 108),
)

SR = GameProfile(
    code="sr",
    name="崩坏:星穹铁道",
    command="sr",
    intents=(
        (
            ("晋阶", "突破", "升级材料", "培养材料"),
            ("角色晋阶材料", "技能晋阶材料", "晋阶材料"),
            (),
        ),
    ),
    specifics=(
        (("技能晋阶", "技能升级", "技能材料"), "技能晋阶材料"),
        (("角色晋阶", "晋阶"), "角色晋阶材料"),
        # BWIKI 星铁页面的「天赋 / …效果加成」分节是星魂/额外能力加成，
        # 技能数值本体在「行迹」分节，泛称技能词统一路由过去。
        (
            (
                "技能",
                "战技",
                "终结技",
                "大招",
                "普攻",
                "普通攻击",
                "天赋",
                "倍率",
                "行迹",
            ),
            "行迹",
        ),
    ),
    accent=(126, 88, 242),
)

ZZZ = GameProfile(
    code="zzz",
    name="绝区零",
    command="zzz",
    intents=(
        (
            ("晋阶", "突破", "升级材料", "培养材料"),
            ("角色晋阶材料", "晋阶材料"),
            (),
        ),
        (("技能", "特殊技", "终结技", "倍率"), ("技能",), ()),
    ),
    specifics=((("终结技",), "终结技"),),
    accent=(240, 124, 44),
)

ARKNIGHTS = GameProfile(
    code="arknights",
    name="明日方舟",
    command="ark",
    intents=(
        (
            ("精英化", "突破", "升级材料", "培养材料"),
            ("精英化材料", "精英化提升", "技能升级消耗"),
            (),
        ),
        (("技能", "天赋", "倍率", "模组"), ("技能", "天赋", "干员模组"), ()),
        (
            ("获取", "获得", "来源"),
            ("获得方式", "获取方式", "获取途径", "基础信息"),
            (),
        ),
    ),
    specifics=(
        (("专精", "技能升级", "技能材料"), "技能升级材料"),
        (("精英化",), "精英化"),
        # PRTS 干员页没有「角色故事」分节，正文档案在「人员档案」，
        # 「干员模组」命中的只是模块剧情。
        (("故事", "身世", "背景", "经历", "剧情", "档案"), "人员档案"),
        (("技能3", "第三技能", "三技能"), "技能3"),
        (("技能2", "第二技能", "二技能"), "技能2"),
        (("技能1", "第一技能", "一技能"), "技能1"),
    ),
    accent=(166, 134, 66),
)

ZMD = GameProfile(
    code="zmd",
    name="明日方舟:终末地",
    command="zmd",
    # AKEData titles skill sections "战技 / 惊霆诀"-style, so the generic
    # skill words need their own heading row beyond selection.INTENTS.
    intents=((("技能", "倍率", "伤害"), ("战技", "终结技", "普通攻击", "连携技"), ()),),
    specifics=(
        (("终结技", "大招"), "终结技"),
        (("战技",), "战技"),
        (("连携",), "连携技"),
        (("普攻", "普通攻击"), "普通攻击"),
        (("天赋",), "天赋"),
        (("潜能",), "潜能"),
        (("突破", "培养材料", "升级材料", "技能材料"), "培养材料"),
        (("属性", "面板"), "基础属性"),
    ),
    accent=(196, 148, 38),
)

# Aspect words shared by every game. The question splitter in assistant.py
# builds its vocabulary from here plus the per-game intents, so a new aspect
# word teaches intent parsing for all games at once and cannot drift from
# section selection.
GENERIC_ASPECTS = (
    "材料",
    "故事",
    "剧情",
    "用途",
    "简介",
    "描述",
    "效果",
    "总量",
    "出处",
    "流程",
    "武器",
    "图鉴",
    "立绘",
    "头像",
    "配队",
)

PROFILES = {p.code: p for p in (YS, SR, ZZZ, ARKNIGHTS, ZMD)}


def aspect_words() -> tuple:
    """Every word that marks a query as an aspect question, not a bare name."""
    words = set(GENERIC_ASPECTS)
    for profile in PROFILES.values():
        for row in (*profile.intents, *profile.specifics):
            words.update(row[0])
    # Longest first so multi-word terms win over their prefixes.
    return tuple(sorted(words, key=len, reverse=True))


def resolve(code: str) -> GameProfile:
    return PROFILES[code]


def api_url(code: str) -> str:
    return source_api(code, default_source(code))


def default_source(code: str) -> str:
    return "prts" if code == "arknights" else "bwiki"


def source_api(code: str, source: str) -> str:
    if source == "akedata" and code == "zmd":
        return "https://data.akedata.wiki/manifest.json"
    if source == "prts" and code == "arknights":
        return "https://prts.wiki/api.php"
    if source == "bwiki" and code in PROFILES:
        return f"https://wiki.biligame.com/{code}/api.php"
    raise ValueError("Unsupported wiki source")


def parse_alias_config(lines):
    """Split alias entries into global and per-game maps.

    ``ys:草神=纳西妲`` binds an alias to one game; entries without a game
    prefix apply everywhere (documented behavior).
    """
    global_aliases, game_aliases = {}, {}
    for line in lines:
        if isinstance(line, str) and "=" in line:
            target, title = (v.strip() for v in line.split("=", 1))
            if not target or not title or len(target) > 60 or len(title) > 100:
                continue
            if ":" in target:
                game, name = (v.strip() for v in target.split(":", 1))
                if game in PROFILES and name:
                    game_aliases.setdefault(game, {})[name] = title
                continue
            global_aliases[target] = title
    return global_aliases, game_aliases
