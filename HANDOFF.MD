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
