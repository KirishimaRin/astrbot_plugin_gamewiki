# 游戏百科 · AstrBot 插件

[![CI](https://github.com/KirishimaRin/astrbot_plugin_gamewiki/actions/workflows/ci.yml/badge.svg)](https://github.com/KirishimaRin/astrbot_plugin_gamewiki/actions/workflows/ci.yml)

查询原神、崩坏星穹铁道、绝区零、明日方舟与明日方舟终末地的角色、技能、材料、书籍和任务资料，向聊天模型返回相关正文与来源链接。明日方舟优先使用 PRTS，异常或无结果时回退 BWIKI；终末地优先 AKEData、BWIKI 兜底；原神、星铁和绝区零使用 BWIKI。

当前版本：**v0.2.0**；作者：**KirishimaRin**。初始版本为 v0.2.0。插件标识：`astrbot_plugin_gamewiki`。持续改进计划见 [ROADMAP](docs/ROADMAP.md)。

GitHub 仓库、插件标识与 ZIP 包名统一为 `astrbot_plugin_gamewiki`。

## 功能

- 多游戏查询：五款游戏共用一套管线，游戏由命令或工具参数指定，配置控制启用范围。
- 命令查询：五个英文入口支持名称或完整问题，由当前会话模型整理中文概览并附 Wiki 链接。
- AI 工具：自然语言搜索条目，并按 page_id 补读分节。
- 角色昵称：原神内置常用昵称，支持在 WebUI 增加映射。
- 内容提取：保留折叠故事、材料数量与表格列名，支持指定技能等级。
- 措辞兜底：问题用词与正文无重叠时回退最相关分节，并标注命中模式。
- 纠错与跨游戏提示：无结果时给出“您是不是要找”建议；用原神昵称查其他游戏时提示对应 `/ys` 条目。
- 图片回复：优先选择与条目名匹配的角色立绘，过滤星级条、头像和界面图标，可配置关闭。
- 调用限制：单用户冷却与配额、全局每分钟上限，管理员豁免，防刷屏护站点。
- 管理命令：查看运行统计、一键清空缓存。
- 连续查询：候选编号选择、已确认条目的分节追问，按会话和用户隔离并自动过期。
- 本地诊断：管理员查看会话规则、缓存读写、上游退避及最近模型降级原因。
- 查询缓存：异步请求、同请求合并、持久化缓存与有界解析缓存。
- 证据追溯：返回来源 URL、页面修订号、抓取时间、分节选择与截断标记。
- 终末地双来源：AKEData 优先读取中文公开版本数据，异常、无条目或暂不支持的问题回退 BWIKI；立绘压缩后发送。
- 明日方舟双来源：PRTS 优先查询，异常或无结果时回退 BWIKI；候选、追问和引用固定实际来源，避免跨站 page_id 混用。

## 环境要求

| 项目 | 要求 |
|---|---|
| AstrBot | 元数据声明 `>=4.5.7,<5` |
| Python | 插件代码 3.10+；同时满足所用 AstrBot 版本要求 |
| 依赖 | `httpx>=0.27,<1`、`beautifulsoup4>=4.12,<5`、`Pillow>=10,<14` |
| 网络 | 服务器可访问 `https://data.akedata.wiki/`、`https://www.akedata.wiki/`、`https://prts.wiki/api.php` 和 `https://wiki.biligame.com/{ys,sr,zzz,arknights,zmd}/api.php`；图片需能访问页面提供的 CDN |
| AI 问答 | 模型支持工具调用，当前人格允许查询工具 |
| 凭据 | 公开百科查询无需 API Key、UID 或米游社 Cookie |

命令查询的概览默认约150–250字，材料与数值使用短列表。模型不可用或超时则返回“原文摘录”。AI 工具由当前对话模型组织回答，工具内部不额外调用摘要模型。BWIKI 的 WAF 会间歇性拦截请求（HTTP 567），插件内置重试与缓存。

插件使用统一文本事件和回复接口，平台适配由 AstrBot 提供。已检查 AstrBot 4.29.3 的工具注册及命令过滤代码；完整服务加载、实际模型调用和平台展示在目标环境验收。

## 安装

在 AstrBot WebUI 的插件管理中选择通过链接安装，填写：

```text
https://github.com/KirishimaRin/astrbot_plugin_gamewiki
```

安装后启用插件，确认依赖安装完成且没有加载错误。

也可上传从源码构建的 `astrbot_plugin_gamewiki-v0.2.0.zip`。构建方法见 [开发说明](docs/DEVELOPMENT.md)。

源码调试时将仓库放入 AstrBot 的 `data/plugins/astrbot_plugin_gamewiki/`，在 WebUI 重载插件。Docker 环境的实际路径取决于数据卷映射。

## 命令

默认命令前缀为 `/`，自定义前缀时按 AstrBot 配置使用。

WebUI 的“插件行为 → 指令/指令组”显示以下 **5 个主命令**，与当前注册入口一致：

| WebUI 主命令 | 游戏 | 查询示例 |
|---|---|---|
| `ys` | 原神 | `/ys 纳西妲突破需要什么材料` |
| `sr` | 星穹铁道 | `/sr 流萤 晋阶材料` |
| `zzz` | 绝区零 | `/zzz 艾莲怎么获取` |
| `ark` | 明日方舟 | `/ark 能天使精英化材料` |
| `zmd` | 终末地 | `/zmd 武器图鉴` |

命令参数使用英文；`ark` 对应内部游戏代码 `arknights`。

五个入口均支持 `help`、`stats`、`clear-cache`。无参数或 `/ys help` 显示帮助；`/ys stats` 查看统计，`/ys clear-cache` 清理缓存。后两项仅限管理员，操作范围覆盖已启用的全部游戏；可从任一游戏入口进入。

管理员可用 `/ys session on`、`/ys session off`、`/ys session status` 控制和查看当前会话状态，也可从其他游戏入口操作。`/ys session reset` 清除手工开关，恢复跟随配置；status 显示最终是否可用及来自手工开关、白名单还是默认配置。手工开关优先于配置白名单并持久化；关闭的会话仍允许管理员执行管理操作。保存失败时会明确提示仅本次运行生效。

`/ys doctor` 为管理员提供本地诊断：启用游戏、活动数据目录、缓存读取和目录写入、有效缓存容量、会话模型是否已选择、上游按主机共享的限流剩余时间，以及最近命令、实际来源与模型降级原因。检查使用临时数据库验证写入后自动删除，不改动已有缓存，不请求 Wiki，也不调用模型生成；“模型已选择”不代表实际调用已经验证。

五个命令始终注册并显示，实际启用范围由配置 `games` 决定。默认启用全部五款游戏：`["ys", "sr", "zzz", "arknights", "zmd"]`，可按需删减；空列表或无有效游戏时回退为全部启用。已有安装保存的有效游戏范围会保留；旧配置若只有 `["ys"]`，升级后需在 WebUI 将其改为上述完整列表才能全部启用。

支持完整问题（`/ys 日月前事讲了什么`）以及名称加问题（`/ys 纳西妲 元素战技10级倍率`）。只输入名称时给简介；明确问题、昵称和参数写法可由本地规则直接识别，其余由会话模型解析。

命令结果为“标题 → 问题概览或短列表 → 查看原文链接”，优先指向相关章节。模型只依据检索资料回答，保留数量、单位、等级和条件；原文存在截断时会传给模型。书籍仍可补读对应正文承载页。同名不明确时返回候选名称和链接，请使用完整名称重查。

### 候选选择与分节追问

默认启用 `conversation_enabled`。命令给出候选后，2分钟内可直接回复编号（如 `2`），或发送 `/ys 2`；选择时按候选的 page_id 读取，并保留原问题。确认条目后，10分钟内可直接问“突破材料呢”“战技10级呢”，也可发送 `/ys 突破材料呢`。追问直接补读当前条目，不再次搜索或解析条目名称，回复注明游戏和条目；每次成功查询刷新条目有效期。

上下文按会话和发送者隔离，最多保留256份，仅在内存中保存，插件重载后清空；不能识别发送者时不启用上下文。无前缀的编号只在该用户有有效候选时处理，无前缀的分节问题只在有已确认条目时处理，其他消息交回原聊天流程。选择和追问仍受普通查询冷却、配额与会话权限限制。

输入另一个完整条目名会替换当前上下文。跨游戏追问会提示先指定目标游戏的条目，并清除旧条目上下文；候选编号不会跨游戏选择。过期后可重新查询名称。关闭 `conversation_enabled` 后使用完整名称查询，候选仍显示但不接管编号或追问。

模型不可用、超时或生成内容异常时，回复标明“原文摘录”，默认名称查询约350字、带问题约750字，字数可配置。命令直接发送单条完整消息，保留换行，不经过全局分段、文字转图或结果修饰。

MediaWiki 页面共用清洗与证据选择规则；AKEData 直接关联结构化数据表：删除导航、解析日志、空模板字段、未展开的模板和地图 JSON；保留表格单位、等级和折叠故事。默认查询优先介绍或基础信息，获取问题筛选来源、刷新或掉落字段，指定等级时保留对应行/列与表头。不会用无关章节补满回复。

跨类型在线回归覆盖角色、武器、材料、圣遗物、怪物、任务和书籍，运行 `python scripts/audit_categories.py` 可复查最终命令输出与工具证据。

## AI 工具

在当前人格中启用：

| 工具 | 参数 | 作用 |
|---|---|---|
| `wiki_search` | `query`、`question`、`game` | 搜索指定游戏，自动读取首选条目，返回其他候选 |
| `wiki_read` | `page_id`、`section`、`question`、`game`、`source` | 按搜索结果补读；section 为空时自动选择分节 |
| `genshin_wiki_search` | `query`、`question` | 旧版原神专用搜索，等价于 `game=ys`，保留兼容 |
| `genshin_wiki_read` | `page_id`、`section`、`question` | 旧版原神专用补读，保留兼容 |

`query` 填简短名称或关键词，`question` 填完整问题，`game` 填 `ys`/`sr`/`zzz`/`arknights`/`zmd`（须在配置 `games` 中启用），`page_id` 使用搜索返回的正整数。

**明日方舟和终末地补读必须同时填写 `source`**，值取搜索结果的 `source_key`：明日方舟为 `prts` 或 `bwiki`，终末地为 `akedata` 或 `bwiki`；其余三款游戏可留空。跨站点 page_id 不通用，缺少来源时会提示补充，不会猜测。命令编号选择与追问会自动保留来源，无需用户填写。升级后应重载插件以刷新工具参数。

自然语言示例：“查一下草神突破需要哪些材料，附来源。”“日月前事讲了什么？”“流萤的晋阶材料要哪些？”

工具返回 JSON 字符串，包含标题、page_id、修订号、抓取时间、`source_urls`、可用分节、正文证据和截断状态。`instructions` 要求模型提供约150–250字概览并附实际页面或章节链接。模型可按 page_id 补读同一条目的分节；`needs_choice` 表示需要用户明确候选。工具内部不调用摘要模型。

## 配置

在 WebUI 的插件配置中修改：

| 配置项 | 默认值 | 范围与说明 |
|---|---|---|
| `games` | `["ys", "sr", "zzz", "arknights", "zmd"]` | 默认全部启用；可按需删减，已有有效配置保留 |
| `conversation_enabled` | true | 候选编号与条目追问；候选2分钟、条目10分钟过期 |
| `timeout_seconds` | 8 | 单次 HTTP 超时，2–15 秒 |
| `query_timeout_seconds` | 15 | 完整查询超时，5–30 秒 |
| `search_cache_seconds` | 600 | 搜索缓存，0–3600 秒 |
| `page_cache_seconds` | 21600 | 正文缓存，0–86400 秒 |
| `max_evidence_chars` | 6000 | 工具正文预算，1000–8000 字符 |
| `model_timeout_seconds` | 20 | 每次模型调用超时，2–60秒；包含会话模型选择时间 |
| `overview_chars` | 250 | 命令模型概览目标上限，150–500字；材料列表可适当超出 |
| `reply_brief_chars` | 350 | 降级原文摘录字数（名称查询），200–1500 |
| `reply_question_chars` | 750 | 降级原文摘录字数（带问题），300–2000 |
| `upstream_concurrency` | 2 | 对站点的并发请求数，1–8 |
| `upstream_pace_seconds` | 0.3 | 请求启动间隔，0.1–2 秒 |
| `user_cooldown_seconds` | 5 | 单用户查询冷却，0–60 秒，0 关闭；AI 补读不冷却 |
| `user_rate_limit` | 6 | 单用户每分钟查询上限，0–60，0 关闭 |
| `global_rate_limit` | 30 | 全插件每分钟查询上限，0–300，0 关闭 |
| `debug_log` | false | 按查询输出分节选择与噪声过滤明细 |
| `image_reply` | true | 命令随附条目图片，失败降级纯文本 |
| `enabled_sessions` | `[]` | 会话白名单，留空不限制；填 `平台:类型:会话ID` |
| `aliases` | `[]` | 列表，每项为 `昵称=正式条目名`，覆盖内置映射 |

触发限制时回复“请 N 秒后再试”；AstrBot 管理员不受调用限制。`stats` 与 `clear-cache` 是命令的管理员保留参数。

自定义昵称示例：

```json
{
  "aliases": ["白菜=纳西妲", "龙王=那维莱特"]
}
```

内置昵称包括草神、小草神、小吉祥草王、帝君、岩王爷、风神、雷神、水龙王、芙芙和胡堂主。涉及人物身份或剧情消歧时，建议使用正式名称。

## 数据与性能

SQLite 缓存位于 AstrBot 的 `data/plugin_data/gamewiki/wiki-cache.sqlite3`（从旧版本升级时自动沿用旧 `genshinimpactsearch` 目录），最多 128 条记录、总容量 64 MiB（超出按最近使用淘汰）。内存最多保留 8 个已解析页面。插件更新后持久化缓存继续保留。

默认每个数据源客户端最多 2 个并发请求，请求启动间隔为 0.3 秒，均可配置。相同请求合并；MediaWiki 空结果最多缓存 60 秒，解压后的响应上限为 2 MiB；AKEData 每张数据表上限为 32 MiB。立绘下载最多 24 MiB，最多同时处理两张。超时或临时 5xx 最多重试两次（共 3 次尝试），403 返回错误，429 按 Retry-After 暂停访问且同一上游主机共享冷却。

命令最多调用模型两次（理解问题、生成概览），明确名称或参数写法通常只调用一次。热查询缓存的是检索资料，概览仍使用当前会话模型生成。开启 `debug_log` 可查看每次命令的 `model_calls`、`model_seconds`、`total_seconds` 和降级状态；模型调用按正常提供商计费。每次模型调用独立超时，因此总耗时还包含检索和另一阶段的模型时间。

缓存有效期设为 0 时不再写入新缓存。既有缓存到原过期时间失效；立即刷新可由管理员执行 `/ys clear-cache`，统一清理正文、解析结果与压缩立绘缓存。

性能取决于来源站点、缓存和模型响应时间，需在实际部署服务器测量，方法见 [开发说明](docs/DEVELOPMENT.md)。

## 常见问题

**插件加载失败：** 检查 AstrBot 版本、Python 环境和依赖安装日志，修复后在 WebUI 重载。

**AI 没有调用工具：** 检查插件是否启用、当前配置是否允许插件、模型是否支持工具调用、当前人格是否启用 `wiki_search` 与 `wiki_read`。先用命令检查查询链路。

**更新时报 DependencyConflictError：** 本版支持部署环境受保护的 Pillow 13。不要手工降级 AstrBot 的核心依赖。若仍报错，请提供冲突中的包名与核心保护版本。

**查询超时、403 或 429：** 检查运行服务器到实际来源 AKEData、PRTS 或 BWIKI 的连通性。限流时按提示等待，避免重复触发。

**查到相似名称：** 查看返回的其他候选，使用正式名称或通过工具的 page_id 指定页面。卡牌问题请写明“七圣召唤”或“卡牌”（仅原神）。

**出现纠错候选：** 原查询无结果时，插件最多尝试一个建议词或去尾字前缀。纠错后即使精确命中，也先展示候选及纠错关键词，请确认后使用完整名称重查。

**查询的游戏报“未启用”：** 在插件配置 `games` 中加入对应代码（`sr`/`zzz`/`arknights`/`zmd`），保存后即可使用。

**摘录不完整：** 工具按字符预算选取相关片段，返回中的 `selection` 字段说明命中了哪些分节、还有多少相关分节未展示。缩小问题范围，用 `wiki_read` 携带对应的 game/source 指定分节，或直接用回复里提示的可查分节名。

**技能分类异常：** 原神页面优先按技能文本与图标识别普通攻击、元素战技与元素爆发，无法识别时才按模板顺序回退；其他游戏使用各自术语，AKEData 使用数据表技能分类。可尝试按完整技能名查询。站点模板变化时请附查询词反馈。

## 开发与反馈

开发环境、测试、打包、框架检查和部署验收见 [DEVELOPMENT.md](docs/DEVELOPMENT.md)。修改前先阅读 [HANDOFF.MD](HANDOFF.MD)，持续改进计划见 [ROADMAP.md](docs/ROADMAP.md)。版本变更见 [CHANGELOG.md](CHANGELOG.md)。

在 [Issues](https://github.com/KirishimaRin/astrbot_plugin_gamewiki/issues) 反馈时提供 AstrBot 版本、插件版本、消息平台、完整查询词、复现步骤和相关日志。

## 来源与许可

终末地通过 AKEData 公开版本清单和 JSON 数据表读取中文资料，BWIKI 兜底；明日方舟优先 PRTS，其余三款游戏使用 BWIKI。MediaWiki 来源读取展开正文；AKEData 直接关联中文文本、数值表和图片资源：

| 游戏 | 站点 | 查询接口 |
|---|---|---|
| 原神 | [原神 BWIKI](https://wiki.biligame.com/ys/) | `https://wiki.biligame.com/ys/api.php` |
| 崩坏：星穹铁道 | [星铁 BWIKI](https://wiki.biligame.com/sr/) | `https://wiki.biligame.com/sr/api.php` |
| 绝区零 | [绝区零 BWIKI](https://wiki.biligame.com/zzz/) | `https://wiki.biligame.com/zzz/api.php` |
| 明日方舟 | [PRTS（优先）](https://prts.wiki/w/首页)、[BWIKI（备用）](https://wiki.biligame.com/arknights/) | `https://prts.wiki/api.php`；备用 `https://wiki.biligame.com/arknights/api.php` |
| 明日方舟：终末地 | [AKEData（优先）](https://www.akedata.wiki/)、[BWIKI（备用）](https://wiki.biligame.com/zmd/) | `https://data.akedata.wiki/manifest.json` 和版本化数据表；备用 `https://wiki.biligame.com/zmd/api.php` |

PRTS 查询先检查精确标题，再进行全文搜索；搜索异常、超时、无结果或无正文时，在完整查询时间预算内回退 BWIKI，并提示实际回退。主源最多使用查询预算的60%且不超过8秒，给备用源留出时间；候选仍需用户确认。补读始终固定原来源，失败时请重新搜索，不将原 page_id 发给另一站。缓存按游戏和来源隔离，PRTS 限流不影响 BWIKI 的退避状态。

AKEData 支持干员基础属性、分等级技能、天赋、潜能、培养材料与档案，以及道具介绍和武器简介/故事。按 manifest.latest 选取同一公开版本的全部数据表；每10分钟检查版本（随搜索缓存配置），数据表按版本缓存。不会读取需要令牌的模块或前瞻数据。配队攻略、获取途径、基建效果与武器详细数值暂交 BWIKI；备用站缺少内容时仍会明确反馈。

终末地和明日方舟共用相同的回退预算与来源固定补读规则。`wiki_read` 必须携带搜索返回的 `source_key`：终末地为 `akedata` 或 `bwiki`；明日方舟为 `prts` 或 `bwiki`。当前条目的补读不会更换来源，需要换源时重新搜索。首次 AKEData 查询需下载较大的数据表，后续命中本地缓存；立绘缩至最长1200像素并转 JPEG 后发送，压缩后的图片缓存6小时，临时文件在发送结束后删除；文字先行发送，不等待立绘下载。安装依赖包含 Pillow；图片失败仍正常发送文字。

终末地森空岛 Wiki 已做可用性探测：2026-10-28 本机首页返回200，但匿名搜索和目录接口均返回401，因此未接入；终末地当前优先 AKEData，BWIKI 备用。此结论仅针对当前请求方式，未接入其网页 SDK 签名或设备校验。

- 回答应保留来源链接，文字与游戏素材的权利归对应权利人。
- 查询接口遵循 [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Main_page)，插件接口参考 [AstrBot 官方开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)。
- 调研时参考了 [astrbot_plugin_gameinfo](https://github.com/zhewang448/astrbot_plugin_gameinfo) 的 Wiki 查询交互，以及 [genshin-db](https://github.com/theBowja/genshin-db) 的结构化数据方案。本版查询实现自行编写，实际数据源为上表中的 AKEData、PRTS 与 BWIKI。
- 插件源代码使用 [MIT License](LICENSE)。许可证适用于本仓库代码；原神及 Wiki 页面内容遵循各自适用的权利与使用规则。
