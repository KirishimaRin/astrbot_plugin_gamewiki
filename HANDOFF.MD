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
- 验证：`pytest -q` 409 passed；Ruff 通过；framework 4.5.7/4.29.3 通过；package 35 files/11,135,524 bytes；Spire Codex 冒烟 25/25；覆盖率审计诊断 52/54（仅“攻略/机制”因中文源超时回退英文），本地 `--strict` 阈值 80% 通过。
- 尚无备用源；Spire Codex 故障时只能明确报错。未改版本号。

## 杀戮尖塔2 计划内增强（2026-10-30）

- 事件 `pages` 分支：排除 `INITIAL`/`FINISH`，按页去重、选项按 `(标题,描述)` 去重，最多 3 页；`分支` 的 specifics 必须排在 `选项` 之前，否则“其他选项”会先被更宽的“选项”命中。
- 怪物 `attack_pattern.states` 转成 `出招顺序`：用 `moves` 的 `move_id→名称` 映射，cycle 按 `next` 走，conditional 只写“按条件选择”不展示 C# 条件；`_kind_hint` 把 出招/招式/意图/血量 归到 monster，用于区分同名怪物与遭遇。
- `page_id→(kind,id)` 的 `_known` 映射让搜索后的 `read` 直接取详情，不再拉整类索引；进程重启后仍回退索引。角色初始卡组继续用整卡索引，因为一次要解析 10 个 ID。
- 数据版本取 `/api/changelogs` 最新 `game_version`，缓存 1 小时；变化时清空 `_indexes` 与 `_known`。这是站点数据标记，不等于游戏 EA 版本号（`/api/beta/version` 才是 v0.11x 通道）。sts2 正文缓存默认 3600 秒，低于其他游戏的全局 6 小时。
- `spire_codex_base` / `spire_codex_cdn` 可指向自建实例；客户端设置 base 后同步更新 `_host`，429 冷却按新主机隔离。
- 真实响应 fixture 在 `tests/fixtures/spirecodex/`；`scripts/smoke_sts2.py` 做在线结构检查，已加入 CI `drift` 任务。
- 术语/充能球/苦痛/关键词/附魔：`/api/search` 常把它们归到 `reference` 或完全不返回；`_term_exact` 在 reference 或无结果时按精确名称查小型列表。术语链接统一指向 `/zhs/reference`，没有逐术语前端路由。通用分节把描述同时放进 `基本信息`，否则裸名称只显示分类字段。
- 搭配/推荐/胜率：仅当问题含 `搭配/推荐/选哪/胜率/强度/评分` 时请求 `/api/pairings`、`/api/draft-recs`、`/api/runs/scores`；pairings/draft 的比率是 0–1，scores 的 `win_rate` 已是百分数，两者不能共用同一个格式化函数。
- webp：`prepared_image(..., convert_webp=True)` 只对 sts2 启用；`_download` 仍负责下载与 JPEG 转换，转换失败时回退原始 URL。不要把该开关应用到其他游戏，避免不必要下载。
- 攻略/机制：`/api/search` 的 guide/mechanics 标题是英文，中文问题词（攻略/机制/规则/概率/BOSS/流派/卡组）先映射到英文关键词再搜；机械页面的搜索路径是 `/mechanics/{slug}`，API 详情是 `/api/mechanics/sections/{slug}`，两者不能共用一个 PATH。列表项用 `slug` 而不是 `id`，`_index`/`_detail` 统一补 `id` 后再算 page_id。
- 攻略/机制正文是英文 markdown，`_markdown_text` 只做标题/链接/粗体/行内代码的扁平化；概览模型负责中文总结。不要把英文正文直接当作中文答案。
- 仍未做：备用数据源、完整平台 webp 发送验收。

## 杀戮尖塔2 黑话与中文编辑源（2026-10-30）

- 进阶黑话：`A10/a10/N10/n10/难度10/进阶十` 统一为 `进阶10`；`A0/N0` 为 `进阶0`；`双Boss/双首领` 为 `进阶10`，已有 `进阶10` 时去掉重复描述。`进阶之灾` 不带数字，必须保持卡牌名，不能归一成进阶5。
- 升级黑话：`火堆敲牌/敲牌/锻造/敲` → `升级`，`敲位` → `升级优先级`，`睡觉` → `休息`。长词必须排在单字“敲”之前；已核对 Spire Codex 实体名不含“敲/锻造/难度/敲位”，单字替换不会误伤条目。
- 服务层 `_search` 也会对 query 调用 `normalize_slang`，因为 AI 工具可能直接把 `A10`/`敲牌` 当 query 传入；命令路径仍先归一整段输入。
- 中文源：STS2.INFO 的 `/zh/mechanics` 按 `article` 卡片（状态名 + 效果/叠加/克制/协同）与 `h2` 分节解析；`/zh/guides` 列表按 `a[href^="/zh/guides/"]` 解析。STS2FRONT 仅在角色攻略缺失时兜底，读取 `/zh-cn/characters/{id}/` 的 `section`，过滤导航/来源/模板段落。
- 中文源 HTML 较大（机制页约 440 KB、攻略列表约 350 KB），必须缓存 6 小时；`_chinese_timeout` 只给可选源 `min(8, timeout/2)` 秒，超时后回退 Spire Codex 英文，不能让中文源拖垮整个查询。
- 概念路由：`伤害/易伤/格挡/商店/金币/稀有度/地图/精英/补丁/更新/胜率/排行/进阶/章节/解锁` 等出现在 **query** 时才覆盖模糊实体候选；实体名后面的方面词（“史莱姆 伤害”）仍走实体候选，避免把怪物问题路由到机制页。
- `GUIDE_TERMS` 同时作为中文→英文兜底映射：伤害→combat、稀有度→rarity、商店→shop、金币→gold、地图→map、精英→elites、补丁/更新→patch、胜率/排行/Tier→tier、解锁→unlock、升级→upgrade。
- `sts2_chinese_sources` 默认开启；`sts2_chinese_timeout_seconds` 默认 20 秒。关闭后只使用 Spire Codex 英文攻略/机制。

## 杀戮尖塔2 对比方案 D（2026-10-30）

- B 层默认不调用模型：`SpireCodexService.compare()` 先分别精确搜索两个条目，类型不同返回 `compare_unsupported`，任一边歧义/未命中返回 `compare_unavailable`，都交给 `format_compare()` 给出分开查询提示。
- 只比较 card/card、relic/relic、character/character；卡牌维度是类型/稀有度/费用/目标/角色/关键词/伤害/格挡/效果/升级后，遗物是稀有度/池/价格/效果/风味，角色是初始生命/金币/能量/球槽/初始遗物/解锁。
- 社区数据：卡牌/遗物读 `/api/runs/scores/{cards|relics}`，角色读 `/api/runs/community-stats` 的 `by_character`；读取失败只省略社区行，不影响字段对比。
- C 层只在问题含“为什么/怎么选/适合/值得/推荐/理由”时调用模型，prompt 要求只使用给出的字段和效果、不编造联动/数值、最多 200 字；模型失败保留 B 层结果并记 fallback。
- `A10和N10` 归一后相同，助手直接回答“同一条目/等级”，不调用 compare；STS2 的“有什么区别”走对比，其他游戏仍保留原分开查询提示。
- `wiki_compare` 工具目前只支持 `game=sts2`，参数 `query_a/query_b/question/game`；框架契约检查已通过 4.5.7 与 4.29.3。

## 杀戮尖塔2 进度/Meta 查询（2026-10-30）

- 新增 `ascension/act/achievement/unlock` 四类：进阶按 `level` 精确匹配，章节按“第X章/幕/精英/BOSS”触发，成就返回全部成就列表，解锁按 `/api/unlocks` 分类展平后按角色名匹配。
- `_meta_result` 只在没有精确实体时运行；`第一章有什么精英` 需要同时出现章节词与精英/BOSS/幕，避免裸“荣耀/密林”被误判成章节。
- 解锁/成就列表的完整信息同时放进 `基本信息`，因为裸名称查询的 evidence 默认只取第一段；`解锁条件` 仍保留为独立分节供追问。
- `wiki_read` 的 `page_id` 对 `achievement=ALL` 和 `unlock` 做特殊解析；`unlock` 链接指向 `/zhs/timeline`，其余进阶/章节/成就使用实体页。
- 本轮仍复用 `SpireCodexService` 的 `Section/evidence` 契约，没有新增工具；`wiki_compare` 与 `wiki_search/read` 继续并行。

## 杀戮尖塔2 事件社区选择（2026-10-30）

- 事件页在问题含“选哪个/怎么选/选择/选项/社区选择”时读取 `/api/runs/community-stats` 的 `events`，按事件 ID 匹配选项 ID，输出社区选择占比。
- 选项中文名先取顶层 `options`，再 `setdefault` 合并 `pages[].options`；深渊浴场的 LINGER/EXIT_BATHS 只在分支页出现，不能只读顶层。
- 只展示选择占比，不推断“最优”；固定附“共 N 次选择，占比仅供参考”。`data_through` 可作为后续统一口径字段。
- `选哪个/怎么选/社区选择` 的 specifics 必须排在“选项”之前，否则会被更宽的“选项”先命中。

## 杀戮尖塔2 剧情/纪元与商店（2026-10-30）

- 剧情：`story` 实体来自 `/api/stories`，`_story_sections` 用 `epochs` 关联 `/api/epochs`；裸“剧情/故事”返回全部故事线，角色名+剧情返回该角色故事，具体故事标题直接命中。
- 纪元：`epoch` 实体来自 `/api/epochs`，展示名称/时代/年份/解锁方式/故事；`解锁内容` 关联卡牌、遗物、药水 ID；`_url` 统一指向 `/zhs/timeline`。
- 商店：`/api/merchant/config` 是单对象，`_detail("merchant", "MERCHANT")` 特殊读取；按删牌、卡牌、遗物、药水、假商人分节；稀有度英文键用 `RARITY_NAMES` 转中文。
- `_names` 对空 ID 列表直接返回，避免为无解锁内容的纪元请求卡牌/药水全表。
- 文本字段统一过 `clean()`，避免 `[red]` 等游戏 BBCode 进入回答。

## 杀戮尖塔2 社区统计与覆盖率审计（2026-10-30）

- `community` 合成实体覆盖：致命遭遇（`deaths.encounters`）、先古选取（`ancient_picks`）、篝火选择（`rest_sites`）、最常删除（`most_removed`）、奖励跳过率（`reward_skip_rate`）；`_meta_result` 用“致命/容易死/篝火/删什么/先古祝福/跳过奖励”触发。
- 统计名称优先用实体索引解析中文：致命遭遇查 encounter，先Ancient查 relic，最常删除查 card；解析不到时回退 stats 里的英文 name。篝火 label 用 `REST_NAMES` 映射，未知标签保留原文。
- 中文攻略源只处理构筑/路线/商店/新手/进阶/先古等主题；补丁、Tier、稀有度、解锁等改走 Spire Codex 专属英文页，避免模糊中文攻略抢占。
- `scripts/audit_sts2_queries.py` 固定 37 条用户问法，覆盖实体、方面、中文源、Meta、事件、社区统计与对比；`--strict` 默认 80% 阈值，当前 37/37。已加入 CI drift 并输出 `research/sts2-coverage.json`。
- 中文源首次抓取大页面可能较慢；`_chinese_timeout` 调整为 `min(20, timeout*0.8)`，超时仍回退英文。

## 杀戮尖塔2 对比与先古补强（2026-10-30）

- 同名限定：`打击（铁甲战士）/打击·铁甲战士` 先按限定词拆分，再在候选标签中过滤；`树叶史莱姆（中）` 的括号是实体名，限定词不在角色/类型白名单时不拆。`compare()` 复用 `search()`，因此同名卡比较可直接带角色限定。
- 跨类型对比不再只给链接：`compare_unsupported` 会附两边效果摘要，仍不判断“谁更强”。
- C 层模型结论先过 `clean_overview`：正文中的数字必须出现在对比结果 JSON 里，否则丢弃模型段落并记 fallback，只保留 B 层数据。
- 先古：`先古之民有哪些` 返回先古列表；`先古祝福怎么选` 走社区选取统计；`ancient-pools` 详情仍按实体读取，前端链接统一 `/zhs/ancients`。
- CI 稳定性：中文源在云端可能超时，`smoke_sts2.py` 只保留 Spire Codex 稳定用例；`audit_sts2_queries.py` 在 CI 中无 `--strict` 运行并输出报告，本地需要门禁时加 `--strict`。当前诊断 37/39，失败项是中文源超时回退英文的“攻略/机制”。

## 杀戮尖塔2 语言与查询拆分修正（2026-10-30）

- 多语言搜索不能只保留最后一个语言的 `data`：纯中文会依次请求 zhs/zht，若 zht 为空，`data` 会变成空响应，导致 `has_reference` 误判、术语回退失效。必须让 `data` 跟随实际选中的 `items`（`fallback_data`）。
- 繁体：`_langs` 对 CJK 追加 `zht`；Spire Codex 的 zht 搜索很稀疏，若 zht 无结果而 zhs 只有一个候选且查询含繁体特征字，可把该候选视为精确匹配。`_detail` 仍用 zhs，输出简体正文。
- 无空格方面词拆分：`_split_aspect` 让 `Bash 效果`、`燃烧之血效果` 在 AI 工具直接调用时也能拆出 query/question；`剧情/故事/机制/攻略/成就/解锁/商店/价格/先古/胜率` 等元/攻略词必须跳过，否则“静默猎手剧情”会被拆成角色名后落到角色页。
- 同名限定：`_split_qualified` 只在括号/分隔符后的限定词属于角色或类型白名单时拆分，`树叶史莱姆（中）` 这类真实条目名不能被误拆。

## 杀戮尖塔2 扩展社区统计（2026-10-30）

- 新增 `map/survival/behavior/hopper/matrix/records` 六类：地图按幕输出普通/精英/Boss 死亡率，生存曲线取 1/5/10/.../50 层，角色行为显示平均删牌与锻造/休息占比，被偷卡牌解析中文卡名，进阶矩阵按角色列出 A0–A10 胜率，记录显示最快通关/最长一局/最大卡组。
- `_split_kind_prefix` 现在要求类型词后有空格或分隔符；“角色行为”“遗物效果”不能被当成“角色/遗物 + 实体”拆开，否则会丢掉整词概念。
- 社区统计的摘要行同时放进 `基本信息`，裸名称查询不会只看到“统计截至”一行。

## 杀戮尖塔2 中文源 429 与图片发送（2026-10-30）

- `ChineseGuideService` 记录按主机冷却：429 时读取 `Retry-After`，在冷却期内直接抛 `httpx.ConnectError`，不再重复打源站；调用方回退 Spire Codex 英文。
- 新增 webp 发送 wiring 测试：`_send_entry_image(..., convert_webp=True)` 必须把开关传给 `prepared_image`；真实转码本身由 `tests/test_images.py` 覆盖。

## 杀戮尖塔2 中文源条款确认（2026-10-30）

- Spire Codex：`API_TERMS.md` 明确公共 API 免费供社区使用（含商业项目），注明来源“鼓励但不强制”；无 SLA、schema 可能随补丁变化；游戏数据版权归 Mega Crit，禁止用数据重编译/重打包/再分发游戏。现有使用方式符合。
- STS2.INFO：未找到 terms/privacy/license 页面；robots `Allow: /` 并提供 sitemap；页脚声明“粉丝攻略站，所有游戏内容版权归 MegaCrit 所有，数据来源 Spire Codex”。没有对编辑正文的再分发授权。
- STS2FRONT：未找到 terms/privacy/contact 页面；robots `Allow: /` 并提供 sitemap；页面声明内容来自 Mega Crit 官方发布、游戏内数据和社区报告，同样没有明确的正文再分发授权。
- 结论：抓取技术上被 robots 允许，但正文没有显式授权。当前只做按需抓取、短节选（`EXCERPT_CHARS=2500`）、来源标注和原文链接，不镜像、不打包全文；`sts2_chinese_sources=false` 可完全回退 Spire Codex 英文。若插件进行商业分发或大规模运营，应先联系站点运营方取得授权。
- 测试 fixture 只使用合成 HTML 片段，不把 STS2.INFO/STS2FRONT 整页纳入仓库或安装包。

## 杀戮尖塔2 用户问法补强（2026-10-30）

- 角色页：问题含“剧情/故事”时关联 `/api/stories` 与 `/api/epochs` 追加“故事线”；问题含“胜率”且带 `A10/进阶N/难度N` 时读 `ascension_matrix` 追加“进阶胜率”。
- 章节页：普通怪问法映射到“普通遭遇”，不再只列 BOSS/精英/事件；`_act_sections` 过滤 `room_type == Monster`。
- 商店“买什么/买啥/价格/多少钱”在精确实体之前优先走 merchant 配置，避免被术语“商店”截走。
- 解锁总览：`遗物/卡牌/角色/药水 + 怎么解锁` 在精确实体前走 `/api/unlocks` 分类列表；`unlock` 的 `ALL_*` page_id 由 `_detail` 特殊还原。
- 具体成就名（如“完美牌组 怎么完成”）在 `/api/achievements` 中精确匹配，不再要求问题里出现“成就”二字。
- `适合/值得/值不值` 纳入卡牌/遗物社区分节触发词；`_split_kind_prefix` 要求分隔符，`角色行为`/`遗物效果` 不再被拆。
- 遭遇候选标签加“遭遇 ·”，与同名怪物候选区分。

## 杀戮尖塔2 列表/排行与 Boss 打法（2026-10-30）

- 列表/排行是合成 kind `list`：`PATHS` 末尾追加 `"list": "lists"`（追加在末尾，已有 KIND_CODES 与历史 page_id 不变）；`_detail("list", key)` 按 key 还原，key 形如 `RELICS_POOL_IRONCLAD`、`CARDS_COLOR_IRONCLAD_RARITY_RARE_TYPE_ATTACK`、`RANK_CARDS_COLOR_SILENT`，全大写、值段不含下划线。`_read` 在 `_known` 丢失（进程重启）时用 `_list_keys()` 枚举闭集重新哈希还原，不依赖不存在的 /api/lists。
- 列表直接用 API 过滤参数：`/api/cards?color=&rarity=&type=`、`/api/relics?pool=`（rarity/type 用英文 key：Basic/Common/Uncommon/Rare/Ancient 与 Attack/Skill/Power，带 lang=zhs）。排行数据来自 `/api/runs/scores/{cards|relics}`（win_rate 已是百分数），角色胜率来自 community-stats 的 `by_character`；排行数据失败时降级为普通列表并注明“暂无社区对局数据”。
- `_list_intent` 在 `_search` 里、多语言搜索之前执行，命中即整题走列表。守卫：文本含“删”（社区统计）或 卡组/牌组/牌堆（初始卡组问法）不进列表；裸“胜率排行”保留攻略路径（既有 audit 用例），泛化 Tier 需 表/榜/当前/版本/中文/Tier 等话题词；角色+胜率+A10 仍走进阶胜率分支。“这张牌胜率多少”因无角色且无话题词保持实体问法。
- 裸名称列表查询会把 question 设为分节名（遗物列表/卡牌列表/胜率排行），让 evidence 命中列表分节；列表分节首几行同时放进 `基本信息`，与解锁/成就总览同一模式。跨角色列表每行带角色标签，五张“打击”可区分；单角色列表带费用/稀有度标签。
- Boss 打法：`_monster_tactics` 只用 moves/attack_pattern/innate_powers 生成（最高伤害招式、首回合招式、随机/条件出招、固有能力、进阶生命），没有逐 Boss 社区攻略数据，不编造。注意 act.bosses 的 ID 是 `{NAME}_BOSS`（遭遇 ID），怪物索引是 `{NAME}`；`_boss_tactics` 依次尝试原 ID、归一化、去 `_BOSS` 后缀。
- 进阶解锁规则文本（ASCENSION_RULES）是本适配器的编辑性总结，Spire Codex 无该页面；“进阶怎么解锁”合成 `ascension/UNLOCK` 实体，链接 /zhs/unlocks。实测澄清：进阶/成就实体页链接并非 404——正确路由是 /zhs/ascensions/level_10 与 /zhs/achievements/all_cards_upgraded（API id `LEVEL_10`/`ALL_CARDS_UPGRADED` 经 `.lower()` 后正好命中）；此前记录的 404 是探测时手拼了 `/ascensions/10`、`/achievements/all-cards-upgraded` 这类错误形态。
- “卡牌/遗物/药水怎么获得”走对应机制页（card-rarity/relic-distribution/potion-drop-rates），英文正文由概览模型总结；specifics 的 获取/获得 行目标改为元组（正文/摘要/基本信息），实体页无正文分节时行为不变。
- STS2 intents/specifics 新增：排行→胜率排行、有哪些/哪些/列表/遗物池→列表分节、怎么打/打法/应对→打法要点/BOSS应对。打法行必须排在 BOSS 行之前，否则“Boss怎么应对”先命中纯名单；“怎么打/打法/应对”因此成为全局方面词，其他游戏“X怎么打”也会拆成实体+方面（行为正确）。
- 怪物 min/max_hp 的进阶上限可能为 null，显示统一用 `or '?'` 兜底，避免“399–None”。
- 验证：pytest 422 passed；Ruff format/check 通过；framework 4.5.7/4.29.3 通过；package 35 files/11,142,278 bytes；smoke_sts2 30/30；audit 63/65（未过项为中文源超时回退英文的“攻略/机制”，与既有诊断一致）。未改版本号。

## 杀戮尖塔2 中文攻略源修复（2026-10-30）

- 根因实测：`sts2.info/zh/guides`（攻略列表页）对 Python httpx 的 TLS 指纹**确定性 503**（curl 同 UA 200、浏览器 UA 被拖挂超时、httpx 恒 503），`/zh/mechanics` 与 STS2FRONT 全部 200 正常。历史上“攻略/机制”两条 audit 用例间歇失败，主要就是该页被 WAF 指纹拦截，而非网络慢或 UA 被拒。
- 修复：`ChineseGuideService.guide()` 改为两级列表源——STS2.INFO 可达时仍优先（既有测试路径不变），列表请求失败或无命中时回退 STS2FRONT 的 `/zh-cn/tips/` 索引（中文攻略：Boss 打法、商店/篝火策略、Tier、解锁等），文章页沿用 `_parse_sts2front_page`。tips 的 key 是 `cn:guide:sts2front:tips:{slug}`，`read()`/`url()` 按最长前缀先匹配；`_entry` 的来源标签因前缀包含 `cn:guide:sts2front:` 自动落到“杀戮尖塔2 STS2FRONT”。列表解析抽成 `_parse_link_list(html, prefix, origin)` 共用，URL 保留源站原始斜杠形态。
- 重试策略：中文源 5xx 只重试一次（WAF 拦截不会在 0.5 秒内消失，尽快落到下一来源）；超时/网络错误重试三次。429 行为不变（按 Retry-After 冷却）。
- 排序同义扩展：用户问“攻略”，STS2FRONT tips 标题多用“指南/打法/路线”，`_ranked_guide` 按 `GUIDE_SYNONYMS` 扩展查询词后再打分，否则中文命中恒为空。
- 挂起防护：STS2.INFO 的 `/zh/guides` 还有第三种形态——既不 503 也不响应（tarpit）。`guide()` 给第一个源的列表请求单独设 `min(4, timeout/4)` 秒上限（可达时实测 ≈0.3s），超时即切 STS2FRONT，避免耗尽整个中文超时预算；离线测试 `test_guide_sts2info_tarpit_falls_back_to_tips` 用异步 handler 模拟挂起。
- `scripts/audit_sts2_queries.py` 改用持久缓存 `research/sts2-cache/`（research/ 已整体 gitignore）：中文大页面冷抓偶发触发限流会读成假覆盖失败，缓存后本地复跑稳定；CI drift 每次仍冷跑、保持诊断性质。smoke 维持临时目录（全部为 Spire Codex 稳定用例）。
- 澄清记录：进阶/成就实体页链接从未损坏（`/zhs/ascensions/level_10`、`/zhs/achievements/all_cards_upgraded` 均 200），此前“404”是探测时手拼错误 URL 形态所致；`_url` 的 `.lower()` 恰好生成正确路由，无需改动。
- 验证：pytest 425 passed；Ruff 通过；冷缓存与热缓存 audit 均 **65/65**；smoke 30/30。未改版本号。

## 杀戮尖塔2 系统级问法补全（2026-10-30）

- 按「用户会在 wiki 搜什么」逐类验证后补齐系统级/概述型问题，全部走既有机制页与列表机器，无新数据源：
  - `分数怎么算`、`每日挑战`、`问号房有什么` → CONCEPT_MECHANICS 直连机制页 slug（score-formula / unknown-rooms；地图生成、篝火选项同理）。daily 没有独立页，score-formula 正文含每日榜单。
  - `苦痛/充能球/关键词/附魔/事件有哪些` → `_list_intent` 新增 REFERENCE_LIST_KINDS，合成 list kind 走 `_reference_list_sections`（`_index(kind,"zhs")` 整表，行格式 `名称：描述前60字`）。key 为 RELICS/AFFLICTIONS/ORBS/KEYWORDS/ENCHANTMENTS/EVENTS。
  - `联机/多人/合作怎么玩`、`卡组推荐`、`附魔怎么选` → CHINESE_GUIDE_WORDS 加 附魔/联机/多人/合作，GUIDE_TOPICS 加 组合/选牌/开荒/时间线 等，GUIDE_SYNONYMS 加 卡组↔构筑/组合/选牌、联机↔合作/多人/单人；tips 标题「先玩单人还是合作」「最强卡牌组合」「附魔怎么选」得以命中。
  - `诅咒是什么` 等释义问法在 `_search` 归一后剥「是什么意思/是什么」后缀（剩余 ≥2 字才剥），裸词走 term_exact 候选。
  - `BOSS遗物有哪些` → `_list_intent` note 模式（RELICS_NOTE_BOSS），给「STS2 不设 Boss 遗物分类 + 稀有度分布计数」，不再误导性返回全量遗物。注意括号：`kind=="relic" and ("boss" in text.lower() or "首领" in text)`，先前漏括号会让裸「首领」误触发。
- 附魔类概念问法必须同时在 CONCEPT_WORDS（拦截 /api/search 描述命中带来的无关遗物候选）与 CHINESE_GUIDE_WORDS（放行中文攻略尝试），缺一个就会退回噪声候选或 not_found。
- 验证：pytest 432 passed；Ruff 通过；framework 4.5.7/4.29.3 通过；package 35 files/11,149,065 bytes；smoke 33/33；audit 75/75（含全部新增系统级问法）。未改版本号。

## v0.4.0 版本（杀戮尖塔2接入与文档整理）

- VERSION、metadata、README 与 CHANGELOG 同步为 v0.4.0。
- 合并杀戮尖塔2特性分支（PR #2），新增第六款游戏支持——杀戮尖塔2（`sts2`，命令 `/sts2`）。
- 接入 Spire Codex REST API 及 STS2.INFO / STS2FRONT 双级中文攻略兜底。
- 新增大模型对比工具 `wiki_compare` 及同名消歧与社区胜率数据支持。
- 全量整理 README、CHANGELOG 与 ROADMAP 文档，保持无 emoji、自然客观的技术风格。

