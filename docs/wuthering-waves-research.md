# 鸣潮接入可行性调研（2026-10-30，分支 `feature/wuthering-waves-wiki`）

结论：可行。候选主源为库街区官方 wiki REST API（guest 可读、全结构化 JSON），BWIKI 鸣潮站可作为低成本先行方案或备用源。两者均已实测通过，下文为实测契约与接入约束。

## 候选源实测

### 库街区官方 wiki（wiki.kurobbs.com / api.kurobbs.com）

- 认证与请求头（全部 guest 实测 200，无需登录 token）：
  - `wiki_type: 9`（9 = 鸣潮；战双为 2，来自前端 games 表 `[{name:"鸣潮", id:9, key:"mc", gameId:3}]`）
  - `source: h5`；`Content-Type: application/x-www-form-urlencoded;charset=UTF-8`
  - 浏览器前端还带 `devcode` 头；实测缺省不影响 guest 读取，实现时建议带一个固定随机值
  - UA 用浏览器 UA；无 robots.txt（404），未见公开 API 条款——按需抓取、短节选、来源标注，不镜像全文
- 已验证端点（POST，表单参数）：
  - `/wiki/core/catalogue/item/search`，参数 `keyword=<关键词>`（不是 searchText，传 searchText 会报"wiki库类型不能为空"）
  - `/wiki/core/catalogue/item/getPage`，参数 `catalogueId=<id>&page=1&limit=N`
  - `/wiki/core/catalogue/item/getEntryDetail`，参数 `id=<雪花ID>`
  - `/wiki/core/catalogue/config/getTree`（整棵目录树，含全部图鉴与攻略分类）
  - `/wiki/core/homepage/getPage`（首页配置 JSON）
- 两个关键 ID 坑：
  - search/getPage 返回的 `record.id`（如 14234）是目录卡片号，**不是**词条 ID；用它请求详情返回"当前词条不存在"
  - 真正的词条 ID 是 `record.content.linkId`（19 位雪花 ID，如 `1233430505140629504`），URL 形如 `/mc/item/<linkId>`。小整数卡片号查详情还会触发服务端慢路径直至超时
  - search 结果混有多种卡片 type（vertical-figure / strategy-component / kuro-post-component 等），同名候选多（"今汐"14 条），必须按 type 过滤 + 精确名称优先
- 数据覆盖（catalogue tree 实测）：共鸣者 1105、武器 1106、声骸 1107、合鸣效果 1219、敌人 1158、道具/素材/补给/资源、逐角色攻略 1384、玩法攻略、区域探索、剧情合集、成就合集、名词注释、游戏机制等约 30 个一级/二级分类
- 词条内容结构（`data.content`）：
  - 角色：modules = 基础资料 / 角色养成 / 角色养成推荐 / 角色档案 / 角色语音，另有 story（剧情），单词条约 350 KB
  - 武器：武器信息 / 突破材料（约 32 KB）
  - 声骸：基本信息 / 声骸技能 / 声骸掉落位置
  - modules 为结构化 JSON（含富文本与图片 URL，alicdn PNG，无 webp 兼容问题）
- 已观测异常行为：同头组合下个别请求间歇性超时（checkVersion/getEntryList/getEntryList 曾挂起 12 秒，同端点稍后恢复）；实现须沿用现有超时/重试/429 冷却约定
- 接入成本：需要独立 client（仿 `spirecodex.py` 模式，不复用 WikiClient MediaWiki 层），估计为主要工程量所在

### BWIKI 鸣潮站（wiki.biligame.com/wutheringwaves）

- 站点存在且开放：MediaWiki 1.37，`api.php` guest 可用；统计 6271 页面 / 1633 条目 / 3998 图片
- 注意路径：站点前缀是 `wutheringwaves` 而非 `ww`；`source_api()` 现按 `{code}` 拼 URL，需为该站加一条特判（同 prts/akedata 先例）
- 命名空间约定与既有游戏不同：
  - 角色页 `共鸣者/<名>`，语音页 `共鸣者/<名>/语音`；声骸套装 `声骸合鸣/<名>`
  - 角色页分节实测：基本资料、服饰、基础属性、出招说明、技能详情、共鸣链、档案、语音
  - 没有 `/攻略` 子页（`共鸣者/今汐/攻略` missing）——配装类问法无子页可穿透，`guide_suffix` 留空
- 声骸合鸣页用干净模板：`{{声骸合鸣 |名称=… |2件套效果=… |5件套效果=…}}`，正则/模板解析成本低
- 复用成本极低：`WikiClient + QueryService` 全套（缓存/回退/节流/证据选择/卡片）直接适用，新增 GameProfile + GAME_WORDS + 一条 source_api 特判即可走通命令路径
- 风险沿用既有认知：BWIKI 间歇性 WAF（已有自动重试）；社区站内容更新速度依赖编辑者

### hakush.in（未验证）

- 本机 DNS 无法解析 `api.hakush.in`，未能实测；据公开资料为结构化 JSON（角色/武器/声骸数值）但无中文攻略正文。若引入只能作数值备选，优先级低。

## 接入建议

分两步走：

1. 先接 BWIKI（`ww` 游戏代码、`/ww` 命令），复用全部现有基础设施，走通六→第七款游戏的命令与 AI 工具路径；黑话归一补 鸣潮 专属（"大招/解放"→共鸣解放、"链1~6"→共鸣链序数、"声骸套装"→声骸合鸣 等）。
2. 再评估库街区 client 作为主源（仿 ark=PRTS / zmd=AKEData 的主备模式）：官方数据在养成材料、数值表、逐角色攻略上显著更全，但需要独立解析器与同名词型消歧；BWIKI 降级为备用源。

命名注意：游戏代码用 `ww`，但 BWIKI 路径是 `wutheringwaves`；库街区内部 key 是 `mc`（与 Minecraft 缩写冲突），不要用作游戏代码。
