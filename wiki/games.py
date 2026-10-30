"""Per-game profiles and fixed, allowlisted source endpoints.

Game codes stay stable when a game's preferred source changes. Shared rules
live in cleaning/selection; game terms and source addresses belong here.
"""

import re
from dataclasses import dataclass, field

YS_SPECIFICS = (
    (("突破材料", "突破"), "突破"),
    (("战技",), "元素战技"),
    (("大招", "爆发"), "元素爆发"),
    (("普攻", "普通攻击", "重击"), "普通攻击"),
    (("命之座", "命座"), "命之座"),
)


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
    # Fixed colloquialism rewrites applied to the question before parsing;
    # pairs of (slang, standard term). Never single-letter triggers.
    slang: tuple = ()
    # Search terms that redirect a card-like entry lookup (ys only).
    card_words: tuple = ()
    # 卡池/寻访类资讯重定向：问句或条目名命中关键词时，条目检索改走
    # 对应聚合页（当前池、历史一览、卡池一览等）。(关键词, 页面) 按序
    # 匹配、先命中先用，同一游戏可映射多个页面（如方舟 保底→寻访规则、
    # 卡池类→卡池一览）。终末地各站没有卡池聚合页，留空。
    pool_pages: tuple = ()
    # 命中这些名称时不重定向：方舟「寻访凭证」等是道具条目，不是卡池页。
    pool_exclude: tuple = ()
    # BWIKI 原神/星铁把配装推荐放在角色「/攻略」子页，主页只有跳转；
    # 问句命中 guide_aspects 时优先读子页，子页不存在再回主页。
    guide_suffix: str = ""
    guide_aspects: tuple = ()
    # Evidence card accent color (RGB); empty falls back to a neutral gray.
    accent: tuple = ()


# Slang shared by every game. 平A is universal player shorthand for the
# normal attack across all five titles.
GLOBAL_SLANG = (
    ("平A", "普攻"),
    ("平a", "普攻"),
    # 时间指代统一成“当前”，让“现在/今天/这期卡池”这类问法命中
    # 「（当前）」分节标题。都是时间状语，不影响实体与方面词。
    ("现在", "当前"),
    ("最新", "当前"),
    ("今天", "当前"),
    ("这期", "当前"),
    ("本期", "当前"),
    # “毕业面板/毕业武器”里的毕业是评价词，删掉后剩“面板/武器”照常命中。
    ("毕业", ""),
)

# 命座+精炼的社区简写（“1+1”“6+5”“0+1”）。映射到各游戏的命座分节：
# 武器精炼数据在武器页，角色页只能回答命座那一半，所以只取命座目标。
PLUS_SHORTHAND = re.compile(r"(?<!\d)([0-6])\s*\+\s*([0-5])(?!\d)")
PLUS_TARGETS = {"ys": "命之座", "sr": "星魂", "zzz": "意象影画"}

# 修饰语类黑话的替换目标会跟实体名连用：后缀位置（“纳西妲一命效果”）
# 替换成标准词才能命中方面词表，前缀位置（“满命魈”“一命那维莱特”）
# 替换会把修饰语焊进实体名（“命之座魈”），检索不到实体。只有这些目标
# 词需要做位置判定。
MODIFIER_TARGETS = frozenset(
    {"命之座", "星魂", "意象影画", "精英化", "专精", "潜能", "精炼5"}
)

# 比较连接词：归一的位置判定与 assistant 的比较拆分共用一份。
COMPARE_JOIN = re.compile(r"和|与|跟|还是|对比|比较|vs|VS|对|比起")

# “满命了”“满命哪个好”这类语气/疑问后缀属于安全位置。集合里的字都
# 不会成为条目名首字；实体首字（能天使的“能”、多莉的“多”、比利的
# “比”、W 等）必须排除，否则前缀保护被绕过。
SLANG_FOLLOW = "了吗呢么吧嘛啊呀的哪怎更值选什如需"

# 修饰语后接评价类短语仍是后缀位置（"胡桃0命能用吗"）。这里只放
# 两字以上的短语：单字“能”是能天使的首字，必须保持前缀保护。
SLANG_FOLLOW_WORDS = ("能用", "够用", "值得", "好用", "毕业", "行不", "值不", "强不")


def _safe_after_slang(rest: str) -> bool:
    """True when a modifier slang occurrence sits in safe (suffix) position."""
    if not rest or not re.match(r"[一-鿿A-Za-z0-9]", rest):
        return True  # end of question, punctuation or whitespace
    if COMPARE_JOIN.match(rest) or rest[0] in SLANG_FOLLOW:
        return True
    if any(rest.startswith(word) for word in SLANG_FOLLOW_WORDS):
        return True
    return any(rest.startswith(word) for word in aspect_words())


def _pairs(suffix: str, target: str) -> tuple:
    """Enumerate 一~六 and 1~6 numbered slang forms for one suffix."""
    return tuple(
        (f"{n}{suffix}", target)
        for n in ("一", "二", "三", "四", "五", "六", "1", "2", "3", "4", "5", "6")
    )


YS = GameProfile(
    code="ys",
    name="原神",
    command="ys",
    # 卡池/祈愿资讯重定向到「祈愿」聚合页。行里不放“卡池”触发词：
    # “卡池保底”这类机制问题要靠自然评分落进机制分节，UP/有什么等
    # 列表型问法才路由到池一览（当前池分节排最前、历史兜底）。
    intents=(
        (
            ("UP", "up", "当期", "当前", "复刻", "有什么", "有哪些"),
            ("活动祈愿（当前）", "祈愿池一览", "历史活动祈愿一览"),
            (),
        ),
    ),
    specifics=YS_SPECIFICS,
    slang=(
        ("E技能", "战技"),
        ("e技能", "战技"),
        ("Q技能", "大招"),
        ("q技能", "大招"),
        *_pairs("命", "命之座"),
        ("满命", "命之座"),
        # 玩家简写：0命（无命座）、几命（问命座）；与一~六命同一目标。
        ("0命", "命之座"),
        ("几命", "命之座"),
        # 专武=角色专属武器；满精=精炼五档，交给 project_refine 取档。
        ("专武", "武器"),
        ("满精", "精炼5"),
    ),
    card_words=("七圣", "卡牌", "角色牌"),
    pool_pages=(
        (
            (
                "卡池",
                "祈愿",
                "UP池",
                "up池",
                "up",
                "UP",
                "抽卡",
                "池子",
                "武器池",
                "角色池",
                "混池",
                "定轨",
                "集录",
                "限定池",
                "常驻池",
                "常驻",
                "当期",
                "复刻",
                "保底",
            ),
            "祈愿",
        ),
    ),
    # 实测 BWIKI 原神角色页的「角色搭配推荐」只有跳转，正文在
    # 「<角色>/攻略」：角色定位 / 配装推荐 / 圣遗物 / 武器 / 阵容搭配。
    guide_suffix="/攻略",
    guide_aspects=("圣遗物", "武器", "配装", "词条", "阵容", "配队"),
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
        # 星魂数值本体是独立的「星魂」表（名称|效果）；「天赋 / …效果加成
        # [星魂N]」分节只是单魂加成详情，用标题路径精确匹配防止误路由。
        (("星魂",), ("星魂",), ()),
        # 卡池/跃迁资讯：见 YS 同名行的说明；历史一览排最前承接复刻问法。
        (
            ("UP", "up", "当期", "当前", "复刻", "有什么", "有哪些"),
            ("活动跃迁（当前）", "跃迁池一览", "历史活动跃迁一览"),
            (),
        ),
    ),
    specifics=(
        (("技能晋阶", "技能升级", "技能材料"), "技能晋阶材料"),
        (("角色晋阶", "晋阶"), "角色晋阶材料"),
        # BWIKI 星铁页面的技能（含秘技）本体都在「行迹」分节，泛称
        # 技能词统一路由过去。
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
                "秘技",
            ),
            "行迹",
        ),
    ),
    slang=(
        ("E技能", "战技"),
        ("e技能", "战技"),
        ("Q技能", "终结技"),
        ("q技能", "终结技"),
        *_pairs("魂", "星魂"),
        ("满魂", "星魂"),
        ("0魂", "星魂"),
        ("几魂", "星魂"),
        ("专武", "光锥"),
    ),
    pool_pages=(
        (
            (
                "卡池",
                "跃迁",
                "UP池",
                "up池",
                "up",
                "UP",
                "抽卡",
                "池子",
                "光锥池",
                "角色池",
                "限定池",
                "常驻池",
                "当期",
                "复刻",
                "保底",
            ),
            "跃迁",
        ),
    ),
    # 星铁同构：角色「/攻略」子页有 遗器 / 光锥 / 阵容搭配 / 简易推荐。
    guide_suffix="/攻略",
    guide_aspects=("遗器", "光锥", "配装", "词条", "阵容", "配队"),
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
        # 卡池/调频资讯：见 YS 同名行的说明。
        (
            ("UP", "up", "当期", "当前", "复刻", "有什么", "有哪些"),
            ("限定频段（当前）", "调频一览", "历史限定频段一览"),
            (),
        ),
    ),
    specifics=(
        (("终结技",), "终结技"),
        # 「影画」分节实名「意象影画」；核心被动位于
        # 「天赋 / 固有天赋 / 核心被动：…」。
        (("影画", "意象影画"), "意象影画"),
        (("核心被动",), "核心被动"),
    ),
    slang=(
        ("E技能", "特殊技"),
        ("e技能", "特殊技"),
        ("Q技能", "终结技"),
        ("q技能", "终结技"),
        *_pairs("画", "意象影画"),
        ("满画", "意象影画"),
        ("0画", "意象影画"),
        ("几画", "意象影画"),
        ("专武", "音擎"),
    ),
    pool_pages=(
        (
            (
                "卡池",
                "调频",
                "UP池",
                "up池",
                "up",
                "UP",
                "抽卡",
                "池子",
                "音擎池",
                "角色池",
                "限定池",
                "常驻池",
                "当期",
                "复刻",
                "保底",
            ),
            "调频",
        ),
    ),
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
        # 卡池资讯走 PRTS「卡池一览」聚合页（限时寻访/常驻标准寻访/
        # 常驻中坚寻访&中坚甄选/新人特惠寻访）；限时寻访表新池子在前，
        # 当前UP靠提示词里的提问时刻时间按日期范围匹配。
        (
            ("UP", "up", "当期", "当前", "复刻", "有什么", "有哪些"),
            ("限时寻访", "常驻标准寻访", "常驻中坚寻访&中坚甄选", "新人特惠寻访"),
            (),
        ),
    ),
    specifics=(
        (("专精", "技能升级", "技能材料"), "技能升级材料"),
        (("精英化",), "精英化"),
        # PRTS uses 干员档案; BWIKI uses 人员档案.
        (("故事", "身世", "背景", "经历", "剧情", "档案"), "档案"),
        (("属性", "面板"), "属性"),
        # 方舟的“命座”是潜能；满潜/几潜归一后落到独立「潜能」分节。
        (("潜能",), "潜能"),
        # 基建技能在 PRTS 叫「后勤技能」、BWIKI 叫「基建技能」，映射名
        # 用元组同时覆盖两源命名。
        (
            ("基建技能", "后勤技能", "基建", "后勤"),
            ("后勤技能", "基建技能"),
        ),
        (("技能3", "第三技能", "三技能"), "技能3"),
        (("技能2", "第二技能", "二技能"), "技能2"),
        (("技能1", "第一技能", "一技能"), "技能1"),
    ),
    slang=(
        # 精一/精二 只在方舟语境指精英化阶段；精炼一词不在此列。
        ("精一", "精英化"),
        ("精二", "精英化"),
        ("精1", "精英化"),
        ("精2", "精英化"),
        ("专一", "专精"),
        ("专二", "专精"),
        ("专三", "专精"),
        ("专1", "专精"),
        ("专2", "专精"),
        ("专3", "专精"),
        ("满潜", "潜能"),
        ("几潜", "潜能"),
        ("0潜", "潜能"),
    ),
    # 保底/概率类先命中「寻访规则」；其余寻访类走「卡池一览」。
    pool_pages=(
        (("保底",), "寻访规则"),
        (
            ("寻访", "卡池", "抽卡", "池子", "up", "UP", "当期", "复刻", "限定"),
            "卡池一览",
        ),
    ),
    # 寻访凭证等是道具条目，含“寻访”但不是卡池问题，不重定向。
    pool_exclude=("寻访凭证", "寻访数据契约", "寻访参数模型"),
    accent=(166, 134, 66),
)

ZMD = GameProfile(
    code="zmd",
    name="明日方舟:终末地",
    command="zmd",
    # 终末地各站（AKEData/BWIKI）没有卡池/调频聚合页，不设 pool_pages。
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
    slang=(
        ("E技能", "战技"),
        ("e技能", "战技"),
        ("Q技能", "终结技"),
        ("q技能", "终结技"),
        # 终末地同样有潜能系统，与方舟同一套简写。
        ("满潜", "潜能"),
        ("几潜", "潜能"),
        ("0潜", "潜能"),
    ),
    accent=(196, 148, 38),
)

STS2 = GameProfile(
    code="sts2",
    name="杀戮尖塔2",
    command="sts2",
    # Spire Codex 的实体不是角色/武器，而是卡牌、遗物、药水、怪物、事件和
    # 角色。分节名由 SpireCodexService 生成，intents 只负责把问题词映射到
    # 这些分节；不要在这里放“生命”“角色”这类容易出现在条目名里的单字。
    intents=(
        (("费用", "耗能", "能量", "星费"), ("基本信息",), ()),
        (("伤害", "格挡", "抽牌", "数值", "倍率"), ("数值", "效果"), ()),
        (("效果", "作用", "干嘛", "做什么"), ("效果",), ()),
        (("升级", "强化"), ("升级后",), ()),
        (("招式", "意图", "技能"), ("招式",), ()),
        (("出招", "顺序", "循环", "攻击模式"), ("出招顺序",), ()),
        (("出现", "遭遇", "哪个幕", "幕"), ("出现遭遇", "基本信息"), ()),
        (("选项", "选择", "前置", "条件"), ("选项", "基本信息"), ()),
        (("分支", "后续", "其他选项", "会怎样", "继续"), ("分支",), ()),
        (("初始", "起始", "开局"), ("基本信息", "初始遗物", "初始卡组"), ()),
        (("解锁",), ("解锁条件",), ()),
        (("获取", "获得", "来源"), ("基本信息",), ()),
        (("血量", "生命值", "HP", "hp"), ("基本信息",), ()),
        (("稀有度", "类型", "关键词"), ("基本信息",), ()),
    ),
    specifics=(
        (("费用", "耗能", "能量"), "基本信息"),
        (("伤害", "格挡", "抽牌", "数值"), "数值"),
        (("升级", "强化"), "升级后"),
        (("招式", "意图", "技能"), "招式"),
        (("出招", "顺序", "循环", "攻击模式"), "出招顺序"),
        (("出现", "遭遇", "幕"), "出现遭遇"),
        # 放在“选项”之前：问“其他选项”时不能先被更宽的“选项”命中。
        (("分支", "后续", "其他选项", "会怎样"), "分支"),
        (("选项", "选择"), "选项"),
        (("前置", "条件"), "基本信息"),
        (("初始", "起始", "开局"), ("基本信息", "初始遗物", "初始卡组")),
        (("解锁",), "解锁条件"),
        (("获取", "获得", "来源"), "基本信息"),
        (("血量", "生命值", "HP", "hp"), "基本信息"),
        (("稀有度", "类型", "关键词"), "基本信息"),
        (("效果", "作用"), "效果"),
    ),
    # 这些是精确昵称，不走 normalize_slang 的子串替换，避免“铁甲战士”
    # 被“战士”二次改写。
    site_aliases={
        "战士": "铁甲战士",
        "铁甲": "铁甲战士",
        "猎人": "静默猎手",
        "机器人": "故障机器人",
        "死灵": "亡灵契约师",
        "死灵法师": "亡灵契约师",
        "摄政王": "储君",
    },
    accent=(170, 52, 44),
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
    "配装",
    "强度",
    # 装备体系各游戏叫法不同，统一当方面词，避免粘进实体名。
    "圣遗物",
    "遗器",
    "驱动盘",
    "光锥",
    "音擎",
    "邦布",
    "专武",
    "词条",
    "副词条",
    "主词条",
    # 基础信息类问法，切出实体后由正文命中「基本信息」。
    "生日",
    "CV",
    "声优",
    "身高",
    "年龄",
)

PROFILES = {p.code: p for p in (YS, SR, ZZZ, ARKNIGHTS, ZMD, STS2)}

# Game-name heads users prepend ("原神纳西妲是谁"); they are context, never
# the entity, so local parsing peels them before splitting a question.
GAME_WORDS = {
    "ys": ("原神",),
    "sr": ("崩坏:星穹铁道", "星穹铁道", "星铁"),
    "zzz": ("绝区零",),
    "arknights": ("明日方舟", "方舟"),
    "zmd": ("明日方舟:终末地", "明日方舟", "终末地"),
    "sts2": ("杀戮尖塔2", "尖塔2", "STS2", "sts2", "杀戮尖塔"),
}


def game_words(code: str) -> tuple:
    return GAME_WORDS.get(code, ())


def _rewrite_positioned(text: str, pattern: re.Pattern, new: str) -> str:
    """Rewrite matches only in suffix position; keep prefix matches verbatim."""
    pieces, pos = [], 0
    for match in pattern.finditer(text):
        if _safe_after_slang(text[match.end() :]):
            pieces.append(text[pos : match.start()])
            pieces.append(new)
        else:
            # Prefix position: keep the slang so the entity stays intact.
            pieces.append(text[pos : match.end()])
        pos = match.end()
    pieces.append(text[pos:])
    return "".join(pieces)


def normalize_slang(text: str, profile: GameProfile) -> str:
    """Rewrite fixed colloquialisms so existing vocabulary and mappings apply.

    Rewriting happens before parsing: slang words are not vocabulary, and an
    unresolved suffix would otherwise split into a wrong entity. Modifier
    slang (命/魂/画/精/专 stages) only rewrites in suffix position — followed
    by an aspect word, comparison connector, particle, punctuation or the
    end of the question — so "满命魈" keeps the entity searchable while
    "纳西妲一命效果" still resolves to 命之座.
    """
    for old, new in (*GLOBAL_SLANG, *profile.slang):
        if new not in MODIFIER_TARGETS:
            text = text.replace(old, new)
            continue
        text = _rewrite_positioned(text, re.compile(re.escape(old)), new)
    plus = PLUS_TARGETS.get(profile.code)
    if plus:
        text = _rewrite_positioned(text, PLUS_SHORTHAND, plus)
    return text


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
    if code == "sts2":
        return "spirecodex"
    return "prts" if code == "arknights" else "bwiki"


def source_api(code: str, source: str) -> str:
    if source == "akedata" and code == "zmd":
        return "https://data.akedata.wiki/manifest.json"
    if source == "prts" and code == "arknights":
        return "https://prts.wiki/api.php"
    if source == "spirecodex" and code == "sts2":
        return "https://spire-codex.com"
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
