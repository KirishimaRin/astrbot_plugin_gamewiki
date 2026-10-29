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
- 同一会话窗口内同一图片 URL 只发送一次（600 秒，与追问话题 TTL 对齐，进程内存记录，重启清零）；发送失败不记入去重，下次查询可重试。
- 证据卡片（`wiki/card.py`）只由本地证据渲染，不渲染上游页面、不执行其 JavaScript；中文字体按 `FONT_CANDIDATES` 路径发现，缺字体时返回 None 静默跳过，不要把字体文件打进安装包。卡片与立绘互斥：身份类查询走立绘（`wants_image`），方面问题走卡片。
- AKEData 技能分节标题是"战技 / 名称"格式，泛称技能词依赖 ZMD intents 的标题映射行；AKEData 未指定等级的技能问题只保留首末两级数值（与基础属性首末规则一致），指定等级仍返回该级。卡片展示原文节选，完整证据仍由文本回复与来源承载。
- 星铁 BWIKI 技能本体位于「行迹」，不要把「天赋 / …效果加成」当成技能本体；PRTS 角色故事使用「干员档案」，BWIKI 使用「人员档案」，用“档案”共同匹配。显式 specifics 命中须获得正评分，不应靠给测试正文塞入问题关键词来规避 fallback。
- 证据选择按标题保留首个分节以过滤模板重复；卡片沿用游戏主题色，原文摘录 fallback 时跳过发送。材料先按阶段与列恢复名称、数量对应，再排两列；不能直接按字符或相邻列拼接。卡片高度裁切需扣除分节标题、间距与省略行，逐行计算可容纳数量；仅检查 PNG 尺寸会漏掉正文越过来源的问题。

## 框架与依赖

- 代码兼容 Python3.10+，使用者还需满足其 AstrBot 版本要求。真实契约检查固定 AstrBot4.29.3；4.5.7 wheel 中已核对当前模型与图片接口存在，不代表所有版本完整部署验收。
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
