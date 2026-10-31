# 开发与验证

## 项目结构

```text
main.py                  AstrBot 命令、工具、生命周期
metadata.yaml            名称、作者、版本、仓库与兼容范围
_conf_schema.json        WebUI 配置声明
wiki/client.py           固定站点 HTTP 客户端
wiki/cache.py            有界 SQLite 缓存
wiki/extractor.py        分节、表格、技能等级与证据选择
wiki/cleaning.py         所有类别共享的页面清洗与同名提示提取
wiki/selection.py        按问题意图选择分节、字段和等级表格
wiki/formatter.py        平台短摘录与来源展示
wiki/query.py            搜索、候选重排、重定向与查询编排
wiki/sources.py          PRTS/AKEData 优先、BWIKI 回退与来源固定
wiki/akedata.py          终末地公开版本数据表、中文文本与分节证据适配
wiki/spirecodex.py       杀戮尖塔2 Spire Codex REST 实体、分节证据与同名消歧
wiki/chineseguides.py    杀戮尖塔2 STS2.INFO/STS2FRONT 中文机制与攻略 HTML 适配
wiki/images.py           AKEData 立绘有界下载、压缩与临时文件清理
wiki/prts.py             PRTS 页面结构与干员元数据适配
wiki/assistant.py        命令意图解析与概览协调（每命令至多两次模型调用）
wiki/layout.py           跨游戏表格与正文排版
wiki/limits.py           单用户/全局调用限制
wiki/conversation.py     按会话与用户隔离的候选、已确认条目和过期回收
wiki/games.py            六游戏档案表与别名配置解析
wiki/models.py           页面与分节数据结构
tests/                   离线测试与合成 HTML 样例
scripts/                 打包、在线验证及框架契约检查
```

## 本地检查

在仓库根目录运行：

```bash
python -m pip install -c requirements-constraints.txt -r requirements-dev.txt
python -m ruff format main.py wiki tests scripts
python -m ruff check main.py wiki tests scripts
python -m pytest -q
python scripts/package.py
```

默认测试不访问网络。`tests/fixtures/character.html` 是自行编写的结构样例，用于验证模板分节、材料计数和等级列。HTTP 错误、取消隔离、缓存和去重由 MockTransport 覆盖。

GitHub Actions 在 Python 3.10、3.11、3.12、3.14 上执行格式检查、静态检查、离线测试与打包。

在线验证单独运行：

明日方舟审计直接检查 PRTS 主源，其余游戏检查 BWIKI；审计不以备用源成功掩盖主源漂移。生产查询的双源回退由 tests/test_sources.py 与公开命令回归覆盖。

```bash
python scripts/smoke.py
python scripts/audit_categories.py
python scripts/smoke_sts2.py
python scripts/audit_sts2_queries.py --strict
```

`smoke_sts2.py` 只使用 Spire Codex 的稳定结构化接口；`audit_sts2_queries.py` 覆盖实体、列表/排行、Boss 打法、获取与解锁等 65 条用户问法，中文源超时会回退英文，因此本地门禁默认按 80% 阈值判断，完整中文覆盖需在源站可用时另行验收。

smoke 脚本只读访问原神 BWIKI；跨游戏 audit 读取明日方舟 PRTS 和其余游戏 BWIKI，尚不覆盖 AKEData 主源。测试昵称、突破总量、指定技能等级、书籍、七圣召唤和不存在词。输出存入本地 `research/live-smoke.json`，该目录不提交到 Git。断言是结构性的：检查正确形状的行/分节存在（如 `点按伤害 | 百分比`），不校验具体数值；BWIKI 编辑者正常调整数值不会误报，站点结构或模板变化才会使断言失败。确因站点改版需要更新时，修改 `scripts/smoke.py` 的 `PATTERNS` 与 `scripts/audit_categories.py` 的 `CASES`，并先在真实页面确认。

CI 另含两个自动任务：`drift`（每周定时与手动触发）在云端连接上述 PRTS/BWIKI 来源运行两个脚本，站点改版当周即标红；`framework` 自动下载 AstrBot 4.5.7 与 4.29.3 wheel 执行契约检查，无需手工准备。`release` 在推送 `v*` 标签且全部矩阵与框架检查通过后打包并创建 GitHub Release。

跨类型脚本覆盖五款游戏、20 个查询的最终回复及工具证据，验证必需信息、无关信息、技术噪声和回复长度，结果保存到 `research/category-audit.json`。BWIKI 的 WAF 会间歇性拦截，脚本对每个用例间隔 3 秒并最多重试两次。HTTP 成功或命中标题只是接口检查，最终输出也必须通过内容断言。

## AstrBot 契约检查

安装完整 AstrBot 环境前，可检查实际框架的装饰器和命令解析：

```bash
python -m pip download --no-deps --dest research/framework-check astrbot==4.5.7
python -m pip download --no-deps --dest research/framework-check astrbot==4.29.3
python -m pip install --no-deps --target research/framework-check/deps docstring-parser==0.18.0
python scripts/check_framework.py --version 4.5.7
python scripts/check_framework.py --version 4.29.3
```

脚本从官方 wheel 提取 `register_llm_tool` 和 `CommandFilter`，外部上下文使用隔离替身。检查四个工具 schema（包括 wiki_read.source）、七个游戏命令与 wikihelp、op 入口、全部旧命令失配、完整问题、帮助、英文管理参数和权限、会话白名单、单条完整消息发送、模型调用上限及卸载。完整服务验收使用下节步骤。

## 目标环境验收

1. 安装插件，确认没有加载错误。
2. 发送 `/ys 纳西妲突破需要什么材料`、`/ys 纳西妲 元素战技10级倍率`、`/ys 日月前事讲了什么`，检查概览、数值和来源链接；用其他四游戏命令分别查询材料或条目。
3. 在当前人格启用 wiki_search、wiki_read，使用支持工具调用的聊天模型；旧版 genshin_wiki_* 工具继续兼容。
4. 自然语言询问角色技能、书籍和卡牌，检查工具调用与引用。
5. 通过工具的 page_id 补读分节，检查追问。
6. 重载插件，检查缓存保留、客户端关闭及后续查询。
7. 检查 `/wikihelp` 统一帮助、七个游戏入口的帮助跳转及 `/op stats`、`/op clear-cache`，普通用户管理拒绝、未启用游戏提示与会话白名单；检查旧命令由本插件移除。
8. 临时选择不可用测试提供商，核对“原文摘录”降级；恢复原会话配置。配置变更前记录原值。
9. 查询模糊名称得到候选后，通过命令编号和无前缀编号分别选择；换用户、换群、超过2分钟后不得复用。
10. 确认条目后通过命令和无前缀消息追问技能或材料；检查目标提示、10分钟过期、新条目替换与跨游戏保护。普通用户仍受冷却/配额限制。
11. 管理员关闭会话后执行 `session reset`，检查恢复白名单/默认配置且重载保留；普通用户不能操作。执行 `doctor` 查看状态，确认不发上游或模型生成请求。
12. `/ark 能天使 精英化材料` 优先返回 PRTS 的资料和链接；模拟主源失败时回退 BWIKI 并提示。选择候选、追问以及 wiki_read 补读时必须沿用原 source_key，不得将 PRTS page_id 发到 BWIKI。检查两来源缓存与主机退避互不污染。

13. `/zmd 汤汤 战技10级` 优先返回 AKEData，并使用终末地术语；查询武器图鉴等主源未覆盖条目时回退 BWIKI，提示不得误写成明日方舟或 PRTS。确认文字先发、立绘可见，来源固定补读不跨站。

部署验收记录冷查询和热查询的 p50/p95、进程内存、缓存命中和上游请求数。模型生成时间单独统计。同名查询应合并，热查询应避免访问上游。仅检索热查询 p95 目标小于 200 ms，需在部署服务器测量。

热查询耗时区分“仅检索”和“包含模型”的端到端耗时，200ms目标只针对仅检索。`debug_log` 记录命令 model_calls/model_seconds/total_seconds/fallback；每个命令独立记录，不累加进程历史。纯名称或明确参数通常一次模型调用，完整问题最多两次，各自受 model_timeout_seconds 限制。不使用浏览器；检索缓存不存储人格相关的模型概览。

模型由 AstrBot 的 get_current_chat_provider_id(umo=...) 选择，llm_generate(chat_provider_id=..., prompt=...) 调用。问题理解仅接收JSON对象；概览只接收正文，来源链接由检索结果附加。列表编号不作事实数字检查，正文出现证据外的阿拉伯数字则降级。该检查只检测新增数字，材料与数量的对应关系仍需真实模型验收。

## 对齐官方规范

| 官方要求 | 本项目做法 |
|---|---|
| 插件名小写、推荐前缀 | `astrbot_plugin_gamewiki` |
| 完整元数据与仓库信息 | `metadata.yaml` |
| 声明额外依赖与配置 | `requirements.txt`、`_conf_schema.json` |
| 异步网络访问 | 复用 `httpx.AsyncClient` |
| 持久化数据放 data | `data/plugin_data/astrbot_plugin_gamewiki/`（升级依次沿用 gamewiki、genshinimpactsearch 旧目录；完整名称目录优先） |
| 错误处理与测试 | WikiError、超时/限流处理、pytest |
| 提交前 Ruff 格式化 | 本地命令与 CI |
| 来源与许可说明 | README、LICENSE |
| 发布 ZIP 小于 16 MB | 按 16,000,000 字节保守检查，研究依赖不入库 |

### LLM 工具 docstring 契约

官方通过解析 docstring 的 `Args:` 段生成工具参数 schema，**不读取类型注解**；格式错误会静默生成空 schema，参数被丢弃。本项目所有 `llm_tool` 遵循 `参数名(类型): 描述` 格式，且 `scripts/check_framework.py` 用真实 wheel 的 `register_llm_tool` 验证生成的 schema，并对 docstring 做静态格式校验（缺 `Args:` 段或参数缺行即失败）。

### 配置声明字段

`_conf_schema.json` 支持 `type`、`description`、`hint`、`default`、`options`、`slider`（数值范围）、`secret` 等字段。当前配置的取值范围在 `main.py` 读取时钳制；后续新增配置应使用 `slider`/`hint` 等规范字段让 WebUI 直接呈现。

### 权限与会话

官方提供 `@filter.permission_type(filter.PermissionType.ADMIN)` 装饰器限制整条命令仅管理员可用；发送者 ID 从 `event.message_obj.sender` 获取。官方 session_waiter 是多轮对话接管机制，不是会话白名单。

`support_platforms` 和 `logo.png` 是官方可选项。插件只使用统一文本事件与回复接口，省略平台白名单，允许按已接入平台使用；展示效果在目标平台验证。

参考：[开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[最小实例与生命周期](https://docs.astrbot.app/dev/star/guides/simple.html)、[发布说明](https://docs.astrbot.app/dev/star/plugin-publish.html)、[工具接口](https://docs.astrbot.app/dev/star/guides/ai.html)、[插件配置](https://docs.astrbot.app/dev/star/guides/plugin-config.html)、[消息事件](https://docs.astrbot.app/dev/star/guides/listen-message-event.html)、[存储规范](https://docs.astrbot.app/dev/star/guides/storage.html)。

## 版本与提交

版本号收口在 `wiki/__init__.py` 的 `VERSION`；`tests/test_version.py` 断言 `metadata.yaml`、CHANGELOG 最新条目、README 版本行与 `VERSION` 四处一致，漏改一处测试即失败。打包脚本从元数据读取名称和版本。作者及 MIT 首行使用 KirishimaRin，安装包包含当前维护说明。初始版本为 `v0.2.0`，Git 标签使用同一名称；推送标签会触发 CI 的 `release` 任务自动构建 ZIP 并创建 GitHub Release。

运行检查后提交并推送代码和标签。检查脚本默认读取 AstrBot 4.29.3 wheel，可用 --version 4.5.7 显式检查最低版本；CI 对两个版本均执行契约检查，避免同目录的其他版本被误选。GitHub 仓库与标签用于源码分发；GitHub Release 和 AstrBot Cloud 插件市场是独立发布步骤。

发布保留 `v0.x.x` 版本标签，最新正式 Release 标为 `Latest`，此前 Release 保留为历史版本；不创建滚动的 `latest` 或 `other` Git 标签。正常的新版本发布由 CI 显式传入 `--latest`。如需补发历史版本，应另行使用 `--latest=false`，避免替换最新版本标记。

提交问题时提供 AstrBot 版本、插件版本、平台、完整查询词、复现步骤和日志。修改前先阅读 `HANDOFF.MD`。


## 核心共享依赖兼容检查

CI 的 framework 任务在下载 AstrBot 4.29.3 wheel 后运行 `python scripts/check_dependencies.py`。该脚本读取真实 Requires-Dist，提取与插件共享的包，以当前 CI 安装版本生成保护约束，再对插件 requirements 执行 `pip install --dry-run --ignore-installed --no-deps` 联合求解。这模拟受保护版本的直接依赖兼容，不安装完整 AstrBot 服务。当前3.11+测试 Pillow13，3.10测试12.3；Pillow13自身要求Python3.11+。`requirements-constraints.txt` 仅用于开发/CI，不随插件ZIP安装。

## 卡片跨源回放

`scripts/audit_cards.py` 接收本地 JSON 清单，覆盖实际提取、证据选择、命令卡片分流和 PNG 绘制。每项含 `id/game/source/title/question/url`，以及相对清单目录的 `html_path`（HTML 或 MediaWiki parse JSON）或 `result_path`（检索结果 JSON）。可用 `required_sections`、`required_text` 检查选中分节与真实绘制文本；`expect_skip` 标记已知页面缺少可用方面节的用例。

```bash
python scripts/audit_cards.py research/card-cases.json --output research/card-review
```

脚本对绘制文字检查左右及底部边界，记录渲染时间、所选分节、实际文字和 PNG 路径。用例逐项报告；遇到断言失败继续收集结果，最终返回非零退出码。模型概览使用固定回复。审计前记录快照的实际来源主机，不用 BWIKI 页面替代 PRTS 主源；未发卡用例单独计数。真实页面快照和渲染产物保持忽略；离线测试用合成结构覆盖这些来源形态。
