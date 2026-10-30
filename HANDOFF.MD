# 维护交接

当前项目为 `KirishimaRin/astrbot_plugin_gamewiki`，显示名“游戏百科”，作者为 `KirishimaRin`。版本与发布记录见 [CHANGELOG](CHANGELOG.md)，使用方式见 [README](README.md)。初始版本为 v0.2.0。本文件记录当前维护约束。

## 项目身份与兼容

- 插件标识、仓库名、安装目录与 ZIP 根目录统一为 `astrbot_plugin_gamewiki`，入口类为 `GameWiki`。
- 只注册 `ys`、`sr`、`zzz`、`ark`、`zmd`；`ark` 的游戏代码为 `arknights`。管理参数为 `help`、`stats`、`clear-cache`、`session`、`doctor`。
- `genshinimpactsearch` 仅用于识别旧持久化目录；旧原神 AI 工具 `genshin_wiki_search/read` 为兼容接口。不要将这些有效兼容代码当作遗留拼写删除。
- 新配置默认全部五游戏启用；已有有效配置保留。会话白名单与管理员身份来自 AstrBot，管理员判断使用 `event.is_admin()`。
- README 描述当前行为，CHANGELOG 记录已发布变更，ROADMAP 只列当前状态与待办。

## 来源与查询

- 原神、星铁、绝区零使用 BWIKI；明日方舟 PRTS 优先、BWIKI 备用；终末地 AKEData 优先、BWIKI 备用。
- `WikiClient` 是 MediaWiki 客户端；其默认来源与 `games.default_source()` 仅用于 MediaWiki 请求，终末地主源由入口的 `AkeClient/AkeService + EndfieldSources` 编排。
- 主源搜索最多使用总查询预算60%且不超过8秒。无结果、无所问内容或异常时回退，提示须使用实际游戏和来源名称。
- 补读必须沿用搜索返回的 `source_key`，不能将某站 page_id 发到另一站。补读失败时不跨站，重新搜索才可切换来源。
- 只有精确名称可自动读取；模糊或纠错结果必须先让用户确认。同名头像不能压过 AKEData 干员记录。
- AKEData 通过 manifest.latest 选同一公开版本的数据表；中文文本 ID 保持整数精度，不通过浮点数转换。48位记录编号可被 JSON number 精确表示。
- 不读取需要令牌的 AKEData 模块或 Foresight 表；数值占位符只做受限算术解析，不能执行上游代码，无法解析时明确保留缺失标记。

## 缓存与图片

- 所有客户端共用一个有容量限制的 SQLite 缓存；缓存键包含游戏、来源与请求，AKEData 的表路径还包含版本。
- 正文在 TTL 内可能保持旧内容；不会通过后台轮询修订号即时失效。管理员 clear-cache 统一清正文、解析和图片缓存。
- MediaWiki 解压上限2 MiB，AKEData 单表上限32 MiB。429 冷却按实际上游主机共享，互不影响不同主机。
- AKEData 立绘最多下载24 MiB，最长边缩至1200像素并转 JPEG，压缩结果缓存6小时。图片最多同时处理两张；文字先发，临时图片必须保留到 event.send 完成后再删除。
- 不删除所有隐藏节点；折叠故事可能位于 display:none。表格要保留空列、rowspan/colspan、材料名与数量、技能等级与单位。
- PRTS 页面含数据脚本，使用 `wiki/prts.py` 提取已知字段，不执行页面 JavaScript。
- 立绘只在名称或身份类查询（是谁、简介、立绘等）时附带；方面问题、候选选择和分节补读由 `assistant.wants_image` 统一跳过，命令与 AI 工具路径一致。问题拆分的方面词汇以 `games.aspect_words()` 为单一来源，新增方面词加在 `GENERIC_ASPECTS` 或对应游戏 intents/specifics，不要改 assistant 的问题正则。
- 本地回退解析（`assistant.fallback_intent`）按顺序：剥 `games.GAME_WORDS` 游戏名前缀（循环、最长优先）→ 别名词锚定实体 → 首个方面词切分并去掉一个尾部单字动词（`TRAILING_VERBS`）。比较类问题（连接词＋`COMPARE_TAIL` 尾词）在检索前直接引导分开查询；尾词覆盖 哪个好/谁强/怎么选 与 练谁/抽谁/培养谁/先练/先抽，连接词表 `games.COMPARE_JOIN` 含 对/比起 并与归一的位置判定共用一份；条目名以连接词开头（如"和璞鸢"）时只给通用提示，不拆名。`project_level` 的"满级"解析为表格自身最高 LV 列或等级列最大行，无等级列则保持原样。原神武器精炼没有独立分节或精炼表：BWIKI 武器页把各档数值以斜杠列表内联在条目首段武器技能里，`project_level` 的 `REFINE_LEVEL`（精炼N/精N，1~5）走 `project_refine` 把每个五档列表替换成对应档那一项，档数不是 5 的斜杠列表（日期、成对数值）原样保留；若上游出现真正的精炼表再补列投影。
- 黑话归一（`games.normalize_slang`）在 `answer()` 入口、比较判定之前对整段输入生效：固定映射表在 `games.GLOBAL_SLANG` 与各 profile 的 `slang`（平A、E/Q技能、命/魂/画的序数/"满"/"0"/"几"形式、方舟 精/专阶段与满潜/几潜、专武→各游戏武器名、满精→精炼5、现在/今天/最新/这期/本期→当前），只改写问题不进入方面词表，E/Q 等触发词必须两字起步、永不使用单字母。命/魂/画/精/专/潜类修饰语只在后缀位置替换（`MODIFIER_TARGETS`＋`_safe_after_slang`：后接方面词、比较连接词、语气/疑问字、评价短语（`SLANG_FOLLOW_WORDS`：能用/够用/值得…）、标点或结尾才替换；单字“能”不能进安全集，否则绕过能天使的前缀保护）——"满命魈""一命那维莱特""专三能天使"这类前缀形式保持原样，实体才可检索；安全字集合不得加入实体名首字（能天使的"能"、多莉的"多"、比利的"比"）。归一两侧相同的比较问句退回通用提示。AI 工具路径在 `_tool_search/_tool_read` 对 question 应用同一 `normalize_slang`（`SourceRouter.profile` 取自主源），与命令路径行为一致；不要改 llm_tool docstring 的 Args 段（schema 依赖它）。
- 卡池/寻访资讯（`pool_pages`）在 `query._search` 做固定条目重定向：(关键词, 页面) 按序匹配、先命中先用，问句或条目名命中即改走聚合页——原神「祈愿」、星铁「跃迁」、绝区零「调频」（BWIKI，单映射）；方舟双映射：保底关键词先命中 PRTS「寻访规则」，其余寻访类走 PRTS「卡池一览」；终末地各站无聚合页，留空。pool intents 行触发词只放 UP/当期/当前/复刻/有什么/有哪些，不放"卡池"——"卡池保底"这类机制问题要靠自然评分落进机制/概率分节，放了会被标题段子集过滤挤掉；当前池标题排第一承接列表问法，历史一览兜底承接复刻问法。时间指代（现在/最新→当前）不归一就命不中「（当前）」分节标题，且模型返回的 intent question 也要在 `answer()` 里再归一。pool 关键词覆盖裸 up/UP、池子、武器池/角色池/光锥池/音擎池、混池、集录、定轨、常驻；`pool_exclude` 用于道具名（方舟 寻访凭证/寻访数据契约/寻访参数模型），命中即跳过整轮重定向，不要用删“寻访”关键词的方式绕过（会丢掉“寻访什么时候更新”）。注意 pool intents 行的通用触发词（当前/有什么/有哪些）会在任何页面上命中：`selection.evidence` 的“多意图即清空 fields”必须只统计标题确实出现在本页的意图（`page_parts` 判定），否则“胡桃现在怎么获得”会因 pool 行把获取类字段过滤一并清掉，证据块混入 CV/生日等无关行。
- 方舟「卡池一览」整页约 1 MB（低于 2 MiB 解压上限，可全量解析），冷查实测 2.3–2.5 秒；PRTS 慢响应或短时间高频探测时可能顶到 15 秒服务超时，属上游抖动而非路径缺陷，若常态化再考虑对聚合页做分节级解析。其「限时寻访」表新池子在前、按行截断保留表头与最新行；当前UP池由概览提示词携带的提问时刻北京时间（`assistant._now_text`，固定 UTC+8，载荷字段 now）按日期范围匹配，无进行中池子时模型据表说明最近一场及起止时间；该表依赖 PRTS 维持新池在前，源站排序变化需回访。
- 本地意图解析分两档置信度（`assistant.literal_intent_detail`）：显式“实体 问题”拆分、别名词命中为高置信；“没有已知问题词就把整句当条目名”为低置信。低置信检索 `not_found` 且输入 ≥4 字时回退模型再抽一次实体（`answer()` 里的一次重试），否则“胡桃语音”会直接报未找到；两三个字的裸名称不回退，避免为不存在的条目白花一次模型调用，也保住 `test_no_evidence_does_not_generate` 的约束。降级解析用 `TRAILING_MODIFIERS` 反复剥离等级/评价尾巴（90级、LV90、10级E、满级、升满、毕业、下次/下期/本期、满、要、的）；往这个正则里加单字前先确认它不是任何条目的末字。
- 命令查询的模型来源：配置 `model_provider`（服务提供商 ID）非空时固定使用它，为空时沿用 `context.get_current_chat_provider_id(umo=...)` 的会话模型。`generate()` 在固定模型调用抛错时回退会话模型一次并累加 `model_fallback_hits`（诊断可见），仍失败才由 `CommandAssistant` 降级原文摘录；回退只在“配置了模型且会话模型不同”时发生，不要改成无条件吞异常。默认值必须保持空串，升级用户行为不变。AI 工具路径仍不调用模型，此配置只影响命令路径。
- 配装内容的分节位置（2026-10-30 实测 BWIKI API）：原神角色主页有「角色搭配推荐」，但正文只有一句“已移动到新页面”，实际内容在「<角色>/攻略」（角色定位/配装推荐/简易推荐/深入详解/圣遗物/武器/阵容搭配）；星铁角色主页没有配装分节，内容同样在「<角色>/攻略」（…/遗器/光锥/阵容搭配）；绝区零不同，配装推荐/驱动盘套装/词条推荐/音擎推荐/阵容搭配直接内联在角色主页，不要给 zzz 配 `guide_suffix`。`query._search` 在问句命中 `guide_aspects`、标题无 `/`、且当前页 `available_sections` 含 `CHARACTER_SECTIONS`（角色页标记）时才尝试子页，子页缺失或 `section_not_found` 自动保留主页结果；不要去掉角色页标记判断，否则武器/道具页会为每个“武器”问题多发一次必然失败的请求。词条类问题在无独立分节时由 intents 标题行并入圣遗物/遗器分节。
- 同一会话窗口内同一图片 URL 只发送一次（600 秒，与追问话题 TTL 对齐，进程内存记录，重启清零）；发送失败不记入去重，下次查询可重试。
- 证据卡片（`wiki/card.py`）只由本地证据渲染，不渲染上游页面、不执行其 JavaScript；默认使用随插件提供的 MiSans Regular/Medium，字体与原始许可按打包白名单一起提供；所有字体不可用时返回 None 静默跳过。卡片与立绘互斥：身份类查询走立绘（`wants_image`），方面问题走卡片。
- AKEData 技能分节标题是"战技 / 名称"格式，泛称技能词依赖 ZMD intents 的标题映射行；AKEData 未指定等级的技能问题只保留首末两级数值（与基础属性首末规则一致），指定等级仍返回该级。卡片展示原文节选；发卡方面查询的正文只保留一两句概括（assistant 概览提示词按 has_card 分流），数值与材料由卡片承载，未发卡查询（立绘、fallback、仅概览）仍使用 150–250 字概览，完整证据由来源链接承载。
- 星铁 BWIKI 技能（含秘技）本体位于「行迹」；星魂数值本体是独立「星魂」表（名称|效果），「天赋 / …效果加成 [星魂N]」只是单魂加成详情，星魂问题经 intents 标题路径行（标题段精确匹配）路由到本体表，不要改成 specifics 子串映射（会把加成分节重新放回候选）。PRTS 角色故事使用「干员档案」，BWIKI 使用「人员档案」，用“档案”共同匹配；基建技能 PRTS 叫「后勤技能」、BWIKI 叫「基建技能」，specifics 映射名支持元组同时覆盖双源命名。原神命之座、绝区零意象影画/核心被动同理落在独立分节。显式 specifics 命中须获得正评分，不应靠给测试正文塞入问题关键词来规避 fallback。绝区零「意象影画」的长效果行卡片可能从行中截起（导航短行已被卡片跳过），属卡片排版既有行为，待卡片专项处理。
- 证据选择按标题保留首个分节以过滤模板重复；卡片沿用游戏主题色，原文摘录 fallback 时跳过发送。材料先按阶段与列恢复名称、数量对应，再排两列；不能直接按字符或相邻列拼接。卡片高度裁切需扣除分节标题、间距与省略行，逐行计算可容纳数量；仅检查 PNG 尺寸会漏掉正文越过来源的问题。

## 框架与依赖

- 代码兼容 Python3.10+，使用者还需满足其 AstrBot 版本要求。真实契约检查覆盖 AstrBot4.5.7 与4.29.3；最低版本的模型与图片接口已核对，完整服务与平台验收按目标环境执行。
- llm_tool schema 从 docstring 的 Args 段生成，不能只依赖类型注解。命令发送完整文本消息，AI 补读不加用户冷却。
- 运行时依赖允许 `Pillow>=10,<14`。AstrBot 会保护当前核心环境已安装的依赖版本；不要因插件安装而降级核心包。
- CI：Python3.10测试 Pillow12.3，3.11+测试 Pillow13。Pillow13本身要求Python3.11+。
- `scripts/check_dependencies.py` 读取固定 wheel 的元数据，用已安装共享版本生成保护约束并 dry-run；此检查不启动完整 AstrBot。
- 测试替身重建 qa_plugin 根包时，必须恢复已缓存的子包属性，否则 Python3.10 的 mock.patch 无法按路径解析。

## 验证与发布

本地检查和目标环境验收见 [开发说明](docs/DEVELOPMENT.md)。默认测试不访问网络；在线脚本范围须按实际覆盖解释，不能将 BWIKI 备用源通过当作 AKEData 主源已验证。

- 改动版本时同步 VERSION、metadata、README、CHANGELOG；打包后核对作者、版本、仓库链接、requirements 和 ZIP 内容。
- CI 的 check 矩阵和 framework 全部通过后，release 才能创建发行包。
- 从 v0.2.0 初始提交开始，后续正常追加提交与 `vX.Y.Z` 版本标签；新正式 Release 显式标为 Latest，不创建滚动 latest/other 标签。
- 研究响应、虚拟环境、构建产物、缓存和本机环境配置保持忽略，不进入 Git 或安装包。公共仓库不保留服务器连接信息、认证说明或会话日志。

## 卡片可读性

- 不把原始分节连续铺成长图。内嵌 LV 表按原有技能标签拆块，移除该形态的导航短行；正文取首句，数值独立列出并保留等级、字段名及单位。
- 卡片每块最多四行描述，技能/属性最多三个字段、材料最多十二项（再受总高度预算约束），按区块数均分高度预算；数值字段过长时整条略去，不能截掉数值末尾或单位。首末等级可能是不同字段，须原样保留字段及条件，不推断为同指标的升级比较。
- 卡片底部标记“内容节选”，正文与数值的取舍只用于卡片，不回写检索证据；不新增模型调用。渲染验收要检查真实样本和所有区块的正文底界，不能只检查整图尺寸。

## 跨源卡片验收

- `research/recon-arknights-能天使.html` 是 BWIKI 样本，PRTS 样本为 `prts-exusiai.html` 或明确从 PRTS 主机抓取的 parse 响应；不得仅凭游戏名给样本标来源。PRTS 的属性标题为“属性”，故事标题为“干员档案”；BWIKI 分别为“基本属性”“人员档案”。
- BWIKI 方舟技能是 `.skill-table-grid` CSS 网格，清洗时转成保留等级列的表格并建立技能1/2/3分节；PRTS 父技能节只有解锁导航时跳过，避免占掉技能3的证据名额。
- 泛称“突破”只匹配突破分节，不能命中标题后缀中的“角色突破等级解锁”天赋。原神 specifics 与默认选择共用 `games.YS_SPECIFICS`，避免导入 selection 引发 games/models 循环。
- LV 表按每行非空端点保留对应等级；横排升级材料的“1→2 / 6→7”保持各自阶段，引用符号如“「巧思」的教导”属于名称。PRTS 属性标题里的“不包括信赖及潜能加成”是数值条件，显示时须保留。
- 只返回“概览”或 selection=fallback 的方面查询跳过卡片。当前汤汤 BWIKI 页未提取出独立方面节，技能区还有空图片/零数量占位，四类方面查询暂不发卡；该页分节适配仍待完善。
- `scripts/audit_cards.py` 回放真实 HTML/结果快照，经命令卡片分流并记录实际绘制文本，检查关键内容与所有文字边界；清单、来源响应和效果图放 research 或外部工作目录，不进 Git。

## 卡片字体

- Noto CJK 的 TTC 默认 index=0 是 JP 字形；按字体 family 名发现 SC 简体字形，不依赖固定集合顺序。标题和分节使用同字体家族的真实 Bold，正文 Regular；缺 Bold 时使用 Regular，不做描边伪粗体。字形索引和字体对象都缓存，避免每张卡片扫描集合。
- 默认字体已改为随软件提供的 MiSans 原始文件及许可；宿主可选覆盖字体。视觉验收使用原始 PNG；把卡片缩小后转低质量 JPEG 会使笔画发糊，字体效果应单独用无损样图确认。

## MiSans 部署适配

- 卡片通过 `font_dir=self.data_dir / "fonts"` 读取插件数据目录里的 `MiSans-Regular.ttf/otf`，标题在同家族中优先 Medium、再 Bold、再 Regular；现有 Noto 等字体继续使用 Bold。优先数据目录中的字体，再内置 MiSans，最后系统字体；目录沿用现有 legacy 数据目录选择，不硬编码部署根目录。
- 默认 MiSans 与官方许可随插件打包，运行时不下载字体、不要求系统字体安装或 fc-cache；可选覆盖字体由宿主数据卷持久保存。`doctor` 在工作线程检查并显示实际字体路径、family 和字重。字体损坏需回退下一可用文件；字体探测按文件修订缓存，重载插件清字体缓存以支持同路径替换。

- 默认 MiSans 必须实装并进入 ZIP，不能仅提供“有文件才优先”的路径适配。内置路径从模块位置计算，避免依赖工作目录。`assets/fonts/` 只打包 Regular、Medium、官方许可 PDF 和字体来源说明；保持字体原字节，SHA-256 见字体 README。官方全字体 ZIP 约228 MB，更新资源时只取这两个原始文件，不把下载包、其他字重或 PDF 工具依赖纳入仓库和安装包；压缩后的插件 ZIP 仍须小于16,000,000字节（16 MB）。

## 字体附加插件调研（2026-10-29，尚未实施）

- 当前 HEAD 5c35391 的 `git archive --format=zip HEAD` 为 11,071,187 字节；内存重封装移除 fonts 项后为 94,793 字节；仅现有字体、许可和来源说明 ZIP 为 10,976,080 字节。拆成可选普通 AstrBot 字体插件可显著缩小主包；现有默认内置字体要求在实施前继续有效。
- 不要用 dist 中任意历史 ZIP 推断当前大小：本机同时留有旧名称、旧版本的无字体产物。发布脚本产物与 Git 归档都应分别验证；官方文档写 16MB，本项目脚本当前按 16 MiB 检查，后续建议统一保守按 16,000,000 字节设置阈值。
- `get_registered_star(name)` 已核对 AstrBot 4.5.7 源码及 4.29.3 wheel；字体附加插件可用自定义只读描述协议连接。调用前检查 activated/star_cls；不能只在主插件构造时发现，也不要硬编码跨插件 import 或安装根目录。
- 任意家族字体需显式提供正文/标题路径和 TTC face index，不能继续依赖 MiSans 文件名及字重字符串替换。当前字体对象缓存以路径为键，资源替换或附加插件重载时需要按 revision/实例变化失效；中文覆盖与新字体布局须单独验收。
- 本次仅完成研究，未改运行逻辑、字体默认值和安装包资源。报告保存在工作区 answers 的 2026-10-29-font-addons.html。

## 官方开发规范审查（2026-10-29）

- 对照官方 plugin-new、最小实例、配置、AI、存储及发布文档：主体要求已落实。存储章节使用完整插件名作为 plugin_data 子目录，当前实现仍为 gamewiki/兼容 genshinimpactsearch；后续对齐需保留缓存、会话开关与字体覆盖路径，不能直接改名丢失旧数据。
- 打包脚本仍按16 MiB检查，官方发布页写16MB；建议统一保守阈值16,000,000字节。本轮打包（追加本节之前）33文件、11,072,040字节，当前体积通过。
- 本轮 Ruff check/format 通过（44文件），pytest 288 passed + 2 subtests；4.29.3真实wheel契约和受保护共享依赖dry-run通过。4.5.7最低版本仍需完整运行验收；不要将局部契约检查写成完整服务或跨版本验收。
- 仅审查，未改业务代码。详细报告：/data/workspace/answers/2026-10-29-astrbot-compliance.html。

## 开发规范修正（2026-10-29）

- 新安装使用 data/plugin_data/astrbot_plugin_gamewiki；已有完整名称目录优先，否则依次沿用 gamewiki、genshinimpactsearch，保留原缓存、会话开关与字体覆盖，不搬移或合并旧目录。不要把旧目录兼容路径改成仅兼容最早名称，否则此前 gamewiki 安装会丢失设置。
- 发布脚本阈值改为16,000,000字节，达到阈值即拒绝；此前审查和字体调研中的16 MiB状态为历史记录。
- scripts/check_framework.py 用 --version 显式选择4.5.7或4.29.3，默认4.29.3；CI下载并检查两版wheel。最低版也已通过现有真实装饰器、命令过滤器、工具schema、管理权限、模型编排和卸载契约。完整服务、外部模型与平台验收仍使用 docs/DEVELOPMENT.md 中的步骤。
- 修正验收：Ruff check及format通过，pytest 289 passed + 2 subtests；新增完整名称目录优先与缓存/会话/字体跨重载保留回归。4.5.7和4.29.3契约检查均通过，打包成功。

## v0.2.5 版本提交

- VERSION、metadata、README 与 CHANGELOG 同步为 v0.2.5，包含本次开发规范修正；按用户指定版本跳至0.2.5，不补造0.2.3/0.2.4发布记录。

## v0.3.0 版本提交

- VERSION、metadata、README 与 CHANGELOG 同步为 v0.3.0。本版包含黑话归一、卡池聚合页、攻略子页、独立模型配置（`model_provider`）、配装与基础信息方面词、比较与未命中重试等改动，文档由外部 agent 重写后经本仓库校对。
- 发布走既有流程：提交后打 `v0.3.0` 标签并推送，CI 的 `release` 任务校验标签与 metadata 一致、从 CHANGELOG 的 `## v0.3.0 —` 段落生成 Release Notes、打包 ZIP 并标记 Latest。

## v0.3.0 发布修正

- CI framework 契约检查发现：`SourceRouter.profile` 取 `primary.profile`，而终末地主源 `AkeService` 没有该属性，导致 `/zmd` 的 AI 工具路径在归一 question 时 AttributeError。已给 `AkeService` 补 `profile = ZMD`，并补 `满潜/几潜/0潜` 的终末地归一；`scripts/check_framework.py` 的 Service 桩补 `profile`。新增 `test_zmd_tool_read_uses_the_endfield_profile` 防止回归。今后给 SourceRouter 增加依赖主源属性的逻辑时，必须同时确认 QueryService 与 AkeService 两侧契约。

## v0.3.1 版本（查询开始提示）

- metadata、README、CHANGELOG 同步为 v0.3.1。
- `query_notice`（默认 true）：限流校验通过后、`conversations.begin` 之前发送“正在查询<游戏名>百科，请稍候…”。放在 `_limited` 之后是刻意的——帮助、管理员指令、未启用会话、选择编号越界、限流拒绝都在此之前即时返回，不应先发提示。发送失败只记 debug 日志，不能中断查询。候选选择与追问同样会发提示；测试 fixture 显式关闭 `query_notice` 以聚焦结果断言，提示本身有专项用例。framework 契约脚本里所有 `event.sent` 断言已改为先校验提示、再校验结果。

## 杀戮尖塔2 数据源调研（2026-10-30，尚未实施）

- 结论：可行，主源选 Spire Codex 公共 REST API（https://spire-codex.com/api），不走 MediaWiki。BWIKI `slaythespire2` 站点统计 116 页面/0 条目；灰机 `sts2.huijiwiki.com` 的 `api.php` 与页面均被 Cloudflare 挑战页拦截且 robots 限制 AI 抓取；wanwiki 同样被 Cloudflare 拦截；urarawin 是静态 HTML、无 API，仅可作后续备选。
- API 事实：`?lang=zhs` 返回游戏官方简中；`/api/stats` 为 cards 577、relics 296、monsters 115、events 66、potions 63、characters 5；`/api/search` 每类最多 5 条且会命中描述，候选必须精确名称优先；`/api/rate-limits` 无 Key 为 300/min per endpoint（开发者页写 15/min，属旧值）；当前 beta 数据版本 v0.111.0，游戏仍处 EA，schema 无 SLA。
- 接入约束：新建 `wiki/spirecodex.py`，不要直接复用 `WikiClient` 的 JSON 层——`_read_json` 只接受 dict、`_fetch_and_cache` 假设 `query.search`、`request()` 会附加 MediaWiki 参数；列表端点返回数组。实体 ID 为 UPPER_SNAKE，但角色 `starting_deck/starting_relics` 是 PascalCase，需归一化。同名卡（如“打击”五角色各一张）必须带角色/类型消歧。
- 清洗：描述含 `[gold]/[blue]/[sine]/[jitter]/[font_size=22]` 等游戏内 BBCode，需只删标签保留文字；能力 `description` 可能丢数值（如 Strength 的 `[blue][/blue]`），需用 `description_raw` 或明确标注。
- 范围：v1 卡牌/遗物/药水/怪物/事件/角色；命令 `/sts2`，游戏代码 `sts2`；无备用源，失败时明确报错；证据卡片与卡图可复用现有路径，webp 需确认平台兼容。
- 本次仅调研，未改运行逻辑；报告在 /data/workspace/answers/2026-10-30-sts2-wiki-research.html。

## 杀戮尖塔2 接入实现（2026-10-30，分支 `feature/slay-the-spire-2-wiki`）

- `SpireCodexService` 不是 MediaWiki：`WikiClient.get(path, params, ttl)` 复用缓存/合并/节流；`_is_empty`/`_validate_payload` 钩子区分数组响应。不要直接把 `request()` 用于 Spire Codex（会附加 `format=json`）。
- `entry_id` 对 key 做 `.upper()`：搜索路径是小写 `strike_ironclad`，实体 ID 是大写 `STRIKE_IRONCLAD`；去掉归一会让 `read` 找不到候选。page_id 用 4-bit kind + 48-bit digest，`read` 通过对应 kind 的索引还原。
- `_read` 拉取整类索引（卡牌约 655 KB），内存 `_indexes` + SQLite 双层缓存；不要改成逐个详情请求，角色初始卡组需要整卡索引。
- 角色 `starting_deck/starting_relics` 是 PascalCase；`_normalize_id` 只对非 UPPER_SNAKE 插入下划线，避免 `BURNING_BLOOD` 被拆成单字母。
- 搜索会命中描述且同名实体多：`search` 必须精确名称优先；同名候选带角色/类型标签，并设置 `choice_intro`，不能沿用“没有同名条目”的默认文案。
- BBCode：`clean()` 把 `[energy:N]` 转 `N费`、空强调对 `[blue][/blue]` 转 `X`；能力 `description` 可能丢数值，`effect_text` 先 `description` 后 `description_raw`。不要把 `[gold]` 等标签原样送进卡片或模型。
- `_tool_read` 对 sts2 单独处理：source 留空或 `spirecodex`；不要走 `read_from_source`（它只认 bwiki 且会拒绝其他游戏）。
- 验证：`pytest -q` 356 passed；Ruff 通过；framework 4.5.7/4.29.3 通过；package 34 files/11,100,102 bytes；真实 API 冒烟覆盖遗物、同名卡、怪物、事件、角色初始卡组、能力。
- 尚无备用源；Spire Codex 故障时只能明确报错。未改版本号。
