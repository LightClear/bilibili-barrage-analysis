# B站弹幕数据可视化

本项目用于采集 B 站热门视频或指定 BV 号的视频弹幕，并使用 Python 完成数据清洗、统计分析，最后通过 HTML、JavaScript 和 ECharts 制作可交互的静态可视化页面。

## 功能目标

- 默认抓取 B 站每日热门前 50 个视频，生成示例数据。
- 支持输入单个 BV 号，单独抓取该视频弹幕。
- 统计弹幕总量、视频热度、词频、时间分布和弹幕长度分布。
- 生成 `web/data/dashboard.json`、`web/data/video_stats.json`、`web/data/danmaku_index.json` 和按视频拆分的弹幕 JSON，让网页无需后端服务即可展示结果。
- 使用 ECharts 实现动态动画、悬停提示、筛选和图表联动。
- 提供 DEMO 账号中心，支持登入、注册、个人资料、本地访问令牌、自带模型 API 和管理员操作。
- 热门榜单支持最近 14 天归档读取，主页面可按日期切换热门数据。
- 热门榜单弹幕按模块、日期和视频拆成独立 JSON，切换日期只加载榜单快照和统计，点击视频时再按需加载单视频弹幕。
- 历史归档榜单保持只读；从历史日期选中的视频如需最新数据，可使用“更新当前视频数据”，结果只进入页面历史缓存，不写回归档文件。
- BV 实时搜索使用本地后台任务显示采集进度，长视频或多分段弹幕不会只停留在“正在获取”。
- 当前账号开启 API 开关并保存自己的模型 Provider 后，可调用 AI 评价接口，对词云、弹幕内容、弹幕氛围和对比数据进行分析。
- 个人页面支持配置账号级屏蔽词，写入 `data/user_block_words/<账号>.txt`，主页面会按当前账号应用“全局 + 个人”屏蔽词。

## PPT 展示文档

用于制作项目介绍 PPT 的设计与架构材料已经整理到：

- `docs/presentation_materials_index.md`：PPT 材料索引和演示路线。
- `docs/presentation_project_design.md`：项目设计、功能边界和交互设计。
- `docs/presentation_architecture.md`：系统架构、模块职责、核心流程和安全权限。
- `docs/presentation_data_storage_and_interfaces.md`：弹幕储存结构、接口调用和释放清理机制。
- `docs/presentation_ppt_outline.md`：15 页 PPT 大纲、建议配图和讲解提示。

## 已完成的优化与安全改进

以下内容来自最近一次代码优化与安全审查，已经落到当前 DEMO 版本中。后续未解决问题单独保留在 `docs/code_optimization_security_review.md`。

### 服务端与任务处理

- `server.py` 已从单线程 `HTTPServer` 改为 `ThreadingHTTPServer`，BV 搜索、热门榜单刷新和 AI 请求不再阻塞所有其他接口。
- 服务端内存状态已加锁，包括 Session、演示身份、验证码、频率限制和用户自带模型 Provider 配置，降低多线程状态竞争风险；Session 读写已集中到 `SessionStore`，方便后续替换为 MySQL 或 Redis。
- 热门榜单采集已改为有限并发，默认 4 路、最高 8 路；单个视频失败会记录错误并继续处理其他视频。
- 热门榜单更新和 BV 搜索已接入内存后台任务：前端通过 `/api/jobs/status` 轮询进度，通过 `/api/jobs/result` 获取完整结果。
- BV 搜索任务会展示分段进度、已解析数量和失败诊断，长视频或多分段视频不会只停留在“正在获取”。
- BV 搜索支持可选“历史补抓”：配置 `BILI_SESSDATA` 或 `BILI_COOKIE` 后，后端会尝试获取历史弹幕日期索引和历史 protobuf 快照；未配置 Cookie、Cookie 失效、接口风控、索引为空、部分月份读取失败或快照失败时会返回分类诊断，且不伪装成全量。普通月份索引失败会跳过该月继续尝试，登录失效、权限不足和风控类错误会停止历史补抓。

### 账号、安全与权限

- 登录态已从单个全局账号改为服务端内存 Session，Cookie 使用 `HttpOnly`、`SameSite=Lax`，并带有服务端过期时间、最近访问时间登记和清理。
- 演示身份已从全局变量改为 Session 级状态，且 `/api/identity` 的身份切换只允许管理员或 owner 账号使用。
- 所有登录后的 POST 请求加入 Session 级 CSRF Token，前端自动携带 `X-CSRF-Token`，服务端做常量时间比较；同时保留同源 `Origin/Referer` 校验。
- 密码哈希已从无盐 SHA-256 升级为 PBKDF2-SHA256，每个密码使用独立随机 salt；旧 SHA-256 账号登录成功后会自动迁移，并移除 `demo_password` 字段。
- 登录接口加入基础撞库防护：连续失败 3 次要求 AI 验证码，失败 5 次后按 1 分钟、3 分钟、5 分钟递增式短时锁定。
- `owner` 权限已进入运行时代码：owner 继承管理员能力，只有 owner 可以授予、撤销或维护管理员权限；owner 账号不能通过后台提升产生，只能由服务器端初始化或手动创建。
- 账号写入已配合 `storage.write_json()` 的原子写入和 `AccountStore` 线程锁，降低并发修改时互相覆盖或写出半截 JSON 的风险。
- 响应头已加入 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、基础 `Permissions-Policy` 和保守 CSP；JSON 接口使用 `Cache-Control: no-store`。

### API Key 与 AI 分析

- 用户自带模型 API Key 已从进程内存迁移到 `data/secure/` 的账号级本机加密存储，不写入 `accounts.txt`、前端文件、README 或普通日志。打包版本不应携带 `data/secure/` 中的本机测试 Key、B站 Cookie 或加密密钥。
- 页面内置 DeepSeek、OpenAI、OpenRouter、SiliconFlow、Moonshot/Kimi、智谱 GLM 和自定义 OpenAI-compatible 模板；模板服务商只允许固定 HTTPS Base URL，自定义 Base URL 会阻止 localhost、内网和保留地址。
- 模型 Provider 配置按账号隔离保存；连接测试只验证低成本 JSON 返回，不提交弹幕内容。
- AI 分析支持省钱模式、深度摘要和全量原文。全量原文模式需要用户确认，最多提交 20000 条弹幕，并限制请求体约 3.4 MB。
- AI 评价支持缓存和“重新分析”：同账号、同模型、同模式、同数据会优先返回缓存，模型失败并回退本地分析时不会写入缓存；缓存 key 已包含 `analysis_prompt_version` 和 `local_stats_version`，提示词或统计摘要升级后不会误用旧缓存。
- AI 评价面板增加前端进度显示，展示摘要整理、请求提交、缓存命中和失败状态。
- AI 使用统计已记录本项目内部可确认的信息，包括请求次数、缓存命中、外部模型调用、失败回退、估算输入 token 和请求体大小；个人页只看自己的统计，只有 owner 可看全局摘要。项目不会读取第三方 API 余额或账单，费用以模型平台控制台为准。
- 用户可填写 300 字以内“分析要求”；后端会清洗控制字符、限制长度并拒绝疑似 API Key 或密钥，模型提示也明确把它视为不可信关注点。

### 前端性能与工程结构

- 主页面 ECharts resize 已加入 160 ms 防抖，减少窗口变化时的重复重绘。
- 弹幕池已建立按 `bvid/title` 的懒索引，图表、筛选、加入对比和当前视频取数不再每次全量扫描所有弹幕数组。
- 热门榜单弹幕已从前端全量 `danmakus.json` 拆为 `danmaku_index.json`、`video_stats.json` 和 `danmakus/<BVID>.json`；日期切换不再读取整份弹幕明细，单视频筛选、对比和 AI 分析才按需加载对应文件。
- 服务启动时会自动执行保守本地储存清理，管理员页也提供占用查看和手动清理入口。默认自动清理只处理已有拆分库替代的旧全量弹幕文件、运行时原始/处理弹幕副本、未被索引引用的弹幕分库、过期 AI 缓存；历史归档按保留天数删除需要管理员额外确认。
- 当前视频、发送时间、长度分布、词频、用户贡献榜、视频对比和 AI 摘要已复用轻量统计缓存；弹幕数据源或账号屏蔽词变化时会自动清空缓存。
- BV 搜索结果已由后端同步返回单视频统计，包括词频、视频内时间分布、长度分布和用户贡献榜；前端会在屏蔽词签名一致时优先使用服务端统计，缺失或不一致时再本地兜底。
- 新增 HTTP smoke 测试和前端资源结构测试，覆盖静态安全头、登录会话、CSRF 拦截、管理员权限拒绝和主页面分块脚本顺序。
- 视频对比区已改为稳定图表容器和 ECharts 实例复用，切换对比视频时优先使用 `setOption()` 更新数据，清空对比区时才释放图表实例。
- 弹幕筛选结果已分页渲染，默认每页 300 条，可选择 100 / 300 / 500，避免一次性把大量 DOM 写入页面。
- 导入 JSON 已增加前端白名单清洗、未知字段报告、文本截断、BV 号校验、弹幕关联校验和 200 万条弹幕本地处理上限。
- 主页面 JavaScript 已完成五轮分块：`app-core.js` 承接常量、DOM 工具、请求封装、格式化和任务面板；`app-video-store.js` 承接视频查找、弹幕池索引、搜索历史、自定义榜单和当前视频入口；`app-charts.js` 承接统计缓存、ECharts 初始化、当前视频图表、发送时间分布、用户贡献榜和对比图表；`app-ai.js` 承接 AI 分析流程；`app-import-export.js` 承接导入导出和导入数据清洗；`app.js` 继续保留页面状态、榜单、搜索、对比卡片和启动流程。
- MySQL 预备层已独立准备，包括 `database/mysql/001_schema.sql`、`database/mysql/README.md`、`config/mysql.example.json`、`src/db/mysql_config.py`、`src/db/mysql_health.py`、`src/db/mysql_apply_schema.py`、`src/db/mysql_migrate_from_files.py`、`src/db/mysql_export_to_files.py`、`src/db/mysql_bootstrap_owner.py` 和 `docs/database_migration_plan.md`；当前仍默认使用文件模式，避免 MySQL 未配置时影响展示。可用 `python -m src.db.mysql_health` 做只读连接检查，用 `python -m src.db.mysql_migrate_from_files` 做导入 dry-run。

## 目录结构

```text
大/
  data/
    raw/          # 原始采集数据
    processed/    # 清洗后的数据
    archive/      # 热门榜单按日期归档，弹幕按视频拆分
    user_block_words/ # 每个账号独立的个人屏蔽词
  config/
    block_words.txt # 全局弹幕屏蔽词，每行一个
    mysql.example.json # MySQL 连接配置示例，真实本地配置使用 mysql.local.json
  database/
    mysql/        # MySQL 表结构和数据库准备说明，当前尚未接入主流程
  docs/           # 设计文档、架构文档、PPT 展示材料和评估报告
  src/            # Python 源码
    db/           # MySQL 配置、健康检查、建表、文件导入、文件导出和 owner 初始化工具
  tests/          # 自动化测试
  web/
    css/          # 页面样式
    js/           # 可视化逻辑
    data/         # 前端读取的数据，包含 dashboard、统计索引和按视频拆分弹幕
      danmakus/   # 当前热门榜单按 BV 拆分的弹幕明细
```

## 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 运行方式

抓取热门视频弹幕并生成前端数据：

```bash
python -m src.main --mode popular --limit 50
```

抓取指定 BV 号：

```bash
python -m src.main --mode bv --bvid BV1xx411c7mD
```

使用离线示例数据生成网页数据：

```bash
python -m src.main --mode sample
```

生成数据后，直接打开 `web/index.html` 即可查看可视化页面。

如果要使用登入、注册、BV 实时搜索、视频详情补抓、管理员更新热门榜单等接口，需要启动本地开发服务器：

```bash
python server.py
```

如果 8000 端口已有旧服务，可以指定备用端口：

```bash
python server.py 8001
```

启动后访问：

```text
http://127.0.0.1:8000/start.html
http://127.0.0.1:8000/index.html
http://127.0.0.1:8000/login.html
```

## 主页面设计思路

主功能页面位于 `web/index.html`，样式主要由 `web/css/dashboard.css` 控制。主页面 JavaScript 正在逐步分块：`web/js/app-core.js` 承接常量、DOM 工具、请求封装、格式化和任务进度面板渲染；`web/js/app-video-store.js` 承接视频查找、弹幕池索引、搜索历史、自定义榜单和当前视频入口；`web/js/app-charts.js` 承接统计缓存、ECharts 初始化、当前视频图表、发送时间分布、用户贡献榜和对比图表；`web/js/app-ai.js` 承接 AI 数据整理、分析要求、当前视频/对比 AI 评价和 AI 词云回写；`web/js/app-import-export.js` 承接数据导出、导入白名单清洗、超限确认和导入问题报告；`web/js/app.js` 继续保留页面状态和核心业务流程。页面的目标不是只展示一份静态图表，而是把“热门榜单浏览、BV 视频实时搜索、历史查看、自定义榜单、弹幕筛选、视频对比”整合成一个连续的数据工作台。因此 JS 设计上采用了“全局状态 + 局部渲染函数 + 轻量后端接口补充”的方式，尽量让每个功能块可以独立刷新，又能共享同一份视频和弹幕数据。

分块化记录见 `docs/app_js_modularization_plan.md`。当前拆分策略是先移动低风险工具层，再逐步拆视频数据、图表统计、AI 分析和导入导出层，避免一次性重写导致页面功能回退。当前已经完成工具层、视频数据层、图表统计层、AI 分析层和导入导出层。

### 1. 页面启动流程

主页面启动入口是 `bootstrap()`。页面加载后会依次执行：

1. `initCharts()` 初始化 ECharts 实例和榜单滚动容器事件。
2. `setupEvents()` 绑定所有按钮、输入框、榜单切换、排序选择、导入导出等交互。
3. `bootstrap()` 读取 `web/data/dashboard.json`、`web/data/video_stats.json` 和 `web/data/danmaku_index.json`，同时通过 `/api/identity` 获取当前身份。
4. 初始化默认状态：进入热门榜单、当前未选择视频、清空搜索缓存。
5. 调用 `renderAll()`、`renderVideoInfo()`、`filterDanmakus()`、`renderSearchHistory()`、`renderCompareSection()` 完成首屏渲染；点击榜单视频后再加载该视频自己的弹幕明细。

这种启动方式的好处是：静态数据可以直接展示，后端服务存在时再逐步补充实时搜索、身份和视频详情；如果接口不可用，页面仍可以作为静态可视化页使用。

### 2. 前端状态设计

`app.js` 顶部集中定义了主页面状态：

- `dashboardData`：从 `dashboard.json` 读取的汇总数据和热门视频列表。
- `danmakus`：当前热门日期中已经按需加载到前端内存的单视频弹幕明细，不再代表整份榜单弹幕。
- `hotDanmakuIndex` / `loadedHotDanmakuKeys`：热门榜单单视频弹幕文件索引和已加载集合，用于避免重复请求同一个日期下的同一个视频。
- `searchedVideos` / `searchedDanmakus`：BV 搜索和历史查看产生的本地视频库，当前保留 15 个未固定视频。
- `customVideos` / `customDanmakus`：用户加入自定义榜单的视频和弹幕。
- `compareVideos`：视频对比区使用的视频，最多保留 A、B 两个。
- `selectedBvid`：历史搜索或 BV 搜索选中的视频。
- `focusBvid`：榜单点击时临时聚焦的视频。
- `activeList`：当前榜单来源，取值为 `hot` 或 `custom`。
- `sortMode`：榜单排序方式，热门榜单支持官方排序，自定义榜单隐藏官方排序。
- `currentRole`：普通用户、API 用户、管理员或 owner 演示身份；AI 按钮是否显示还会额外读取后端返回的 `ai_available`。
- `pageCache`：多 P 视频的分 P 信息和分 P 弹幕缓存。
- `danmakuPoolIndex`：前端内部的弹幕池索引，按 `bvid` 和 `title` 懒构建，用于避免每次筛选、图表刷新、加入对比时重复扫描全部弹幕数组。
- `statsCache` / `statsDataVersion`：当前视频和对比视频的统计缓存，保存时间分布、发送时间分布、长度分布、词频和用户贡献榜。弹幕池失效或账号屏蔽词变化时会递增版本并清空缓存。
- `videoInfoHydrationTried`：记录已经尝试补抓详情的视频，避免连续重复请求。

这里没有引入复杂框架，而是使用明确的全局状态，是因为项目页面规模适中，功能之间的数据共享很频繁。直接状态配合清晰的渲染函数，更容易观察数据流，也方便后续把某些状态迁移到后端或本地存储。

### 3. 视频数据查找和弹幕数据合并

页面里同一个视频可能来自多个地方：热门榜单、BV 搜索历史、自定义榜单、视频对比。为了避免每个模块都维护一套查找逻辑，JS 统一使用：

- `findVideo(bvid)`：按“搜索库 -> 自定义榜单 -> 热门榜单 -> 对比列表”的顺序查找视频。
- `getDanmakusForVideo(video)`：从搜索弹幕、自定义弹幕和已加载的热门弹幕中合并当前视频弹幕。热门榜单视频在首次查看、加入对比、加入自定义榜单或 AI 分析前，会通过 `ensureVideoDanmakusLoaded()` 先加载该视频自己的弹幕文件。
- `uniqueRows(rows)`：按 `bvid/cid/time/user_hash/content` 去重，避免同一个视频被多次迁移后重复统计。
- `currentVideo()` / `currentVideoDanmakus()`：为当前选中视频提供统一入口。

这样设计后，图表、筛选、简介、对比等模块不关心视频来自哪个库，只需要读取“当前视频”和“当前视频弹幕”。热门榜单本身只常驻视频列表、单视频统计和弹幕文件索引；弹幕明细只在用户真正操作某个视频时进入内存。被查看过的视频会迁移进 `searchedVideos`，形成独立于热门榜单和自定义榜单之外的历史库。凡是已加载热门弹幕、搜索弹幕或自定义弹幕发生变化，都会调用 `invalidateDanmakuPoolIndex()` 让索引失效；下一次读取时再重建，避免维护多份复杂状态。

### 4. BV 搜索、历史记录和本地缓存

BV 搜索由 `fetchBvid()` 负责。当前版本不再让主请求一直等待弹幕采集完成，而是先调用 `/api/jobs/search` 创建后台任务，拿到 `job_id` 后由 `startBvidJobPolling()` 轮询 `/api/jobs/status`。任务面板会显示当前阶段、进度条、最近事件和已解析弹幕数；任务成功后再通过 `/api/jobs/result` 读取完整视频信息、分 P 列表、当前 cid 和弹幕数据。这样即使长视频或多分段视频需要较久处理，页面也能看到正在进行到哪一步。

前端拿到完整结果后会做几件事：

1. 将视频写入 `searchedVideos`。
2. 将该视频弹幕写入 `searchedDanmakus`。
3. 将分 P 信息、分 P 弹幕和服务端统计写入 `pageCache`。
4. 写入 `searchHistory`，用于“最近搜索”标签。
5. 设置 `selectedBvid`，刷新当前视频、图表和筛选结果。

后端会同时返回弹幕采集诊断信息和单视频统计。诊断信息包括 B 站统计弹幕数、实际获取数、采集来源和覆盖比例，主页面会在“当前视频数据”下方显示“弹幕采集诊断”面板。单视频统计包括词频、视频内时间分布、长度分布和用户贡献榜，后端会先按当前账号生效屏蔽词过滤再统计；前端只有在统计携带的屏蔽词签名与当前页面一致时才复用，否则重新本地计算，避免账号屏蔽词变化后图表与弹幕列表不一致。当前 DEMO 使用公开视频分段接口，并在失败时回退旧 XML 接口；这能绕开旧 XML 接口约 3600 条的常见限制，但公开视频分段接口仍不等于历史累计全量。因此老视频或百万弹幕视频可能只能拿到公开视频接口可返回的弹幕池。

为解决老视频和百万弹幕视频的缺口，BV 搜索栏增加了“历史补抓”选项。该功能会尝试调用 B 站历史弹幕日期索引和历史弹幕 protobuf 快照接口，把历史快照中新增的弹幕去重合并到当前结果中。历史接口需要登录 Cookie，因此服务端必须通过环境变量配置其一：

```powershell
$env:BILI_SESSDATA="你的 SESSDATA"
# 或者复制完整 Cookie：
$env:BILI_COOKIE="SESSDATA=...; bili_jct=...; ..."
```

可选限制：

```powershell
$env:BILI_HISTORY_MAX_MONTHS="180"  # 最多检查多少个月，默认 180
$env:BILI_HISTORY_MAX_DATES="180"   # 最多下载多少个历史快照日期，默认 180
```

Cookie 不会写入前端、README 或账号文件，只由当前 server.py 进程读取。未配置 Cookie 时，即使勾选“历史补抓”，页面也会给出“需要 BILI_SESSDATA 或 BILI_COOKIE”的诊断，而不会假装已经拿到全量历史弹幕。历史补抓结果会额外返回 `history_error_type`，目前包括 `auth_required`、`cookie_invalid`、`risk_control`、`index_empty`、`index_partial`、`index_failed`、`snapshot_failed`、`parse_failed`、`row_limit` 等分类，便于判断是配置问题、风控问题、索引为空、部分月份失败还是快照下载问题。普通月份索引返回 `请求错误` 时会跳过该月继续尝试其他月份；如果所有月份都失败，页面会保留当前公开视频接口结果并提示历史索引失败。所有 BV 搜索结果仍受 200 万条弹幕上限保护。

个人页面也提供“B站历史弹幕补抓”配置区。用户可以保存本账号自己的 `BILI_SESSDATA` 或完整 `BILI_COOKIE`，后端会写入 `data/secure/bili_cookies.json` 的本机加密存储，只返回配置状态、类型、更新时间和脱敏预览，不回显原文。BV 搜索任务会优先使用当前账号保存的凭证；未配置账号凭证时，再回退到服务端环境变量。管理员不能查看普通用户保存的 B 站 Cookie 原文。

旧的 `/api/search?bvid=...` 同步接口仍然保留，主要用于兼容和多 P 切换时的直接读取。后续如果要让分 P 切换也显示完整进度，可以把 `switchPart()` 改成同样提交 `/api/jobs/search` 并携带 `cid`。

缓存释放由 `pruneSearchedData()` 控制。当前策略是：历史/搜索库最多保留 15 个未固定视频；如果视频已经加入自定义榜单或视频对比，则认为它被固定，不会被自动释放。这个策略让“查看过的数据”能短期保留，同时避免页面因无限累积弹幕数据而越来越卡。

### 5. 热门榜单日期切换

热门榜单设计上不是只保存当天数据，而是支持最近 14 天归档。Python 侧由 `src/archive.py` 的 `ArchiveStore` 和 `src/danmaku_store.py` 管理归档目录：

```text
data/archive/YYYY-MM-DD/today_hot_videos.json
data/archive/YYYY-MM-DD/danmaku_index.json
data/archive/YYYY-MM-DD/video_stats.json
data/archive/YYYY-MM-DD/danmakus/<BVID>.json
data/archive/YYYY-MM-DD/today_danmakus.json  # 旧归档兼容读取，不再作为新写入格式
```

命令行 `python -m src.main --mode popular --limit 50` 会先保存当天热门视频和按视频拆分的弹幕库，再只把当天数据导出到 `web/data/dashboard.json`、`web/data/danmaku_index.json`、`web/data/video_stats.json` 和 `web/data/danmakus/<BVID>.json`。历史归档不再混入“今日榜单”，需要通过日期选择框单独读取。旧归档如果仍只有 `today_danmakus.json`，服务端第一次读取时会补齐拆分库。

服务端也提供了对应接口：

- `/api/popular-dates`：返回当前榜单和已有归档日期。
- `/api/popular-date?date=current`：返回当前导出的轻量热门数据、弹幕索引和单视频统计，不返回整份弹幕明细。
- `/api/popular-date?date=YYYY-MM-DD`：读取指定日期的归档，返回轻量 dashboard、弹幕索引和单视频统计；响应中的 `danmakus` 固定为空数组，保持旧前端字段兼容。
- `/api/video-danmakus?date=current&bvid=BV...`：按需返回当前热门榜单中单个视频的弹幕明细。
- `/api/video-danmakus?date=YYYY-MM-DD&bvid=BV...`：按需返回指定归档日期下单个视频的弹幕明细。
- `/api/jobs/refresh-popular`：管理员或 owner 创建当前热门榜单更新任务，更新后写入当天归档，并只导出当天热门数据。旧的 `/api/refresh-popular` 同步入口已停用并返回 410。

前端在热门榜单排序方式左侧放置日期选择框，只在“热门榜单”标签下显示，切换到“自定义榜单”时隐藏。切换日期时只替换榜单、统计和弹幕索引，并清空当前日期已加载的热门弹幕；当前正在查看的视频会先迁移到历史库，防止榜单数据源变化后当前视频详情直接丢失。

### 6. 视频详情补抓

热门榜单的离线 JSON 不一定包含完整字段，例如封面、点赞、硬币、简介等可能缺失。为此页面增加了轻量补抓逻辑：

- `needsVideoInfoHydration(video)` 判断视频是否缺少封面、简介或核心指标。
- `hydrateVideoInfo(video)` 调用 `/api/video-info?bvid=...` 获取详情。
- `updateVideoEverywhere(info)` 把补抓结果同步到热门榜单、搜索库、自定义榜单和对比列表里的同一视频。

这样做的目的不是每次都强制请求接口，而是在用户真正查看某个视频时再补数据。简介栏也是基于这个逻辑：如果本地没有简介，会先显示“正在获取视频简介...”，接口成功后自动替换成真实简介。

### 7. 榜单设计

榜单由 `renderRankChart()` 渲染。虽然早期可用 ECharts 柱状图实现，但当前热门榜单计划展示 50 个视频，单纯图表不利于阅读长标题和滚动查看，所以改为原生滚动列表：

- `getVideoRank(videos)` 根据 `sortMode` 返回排序后的视频。
- 每个榜单项包含排名、标题、弹幕/播放信息和一条比例条。
- `rankScrollTop` 记录滚动位置，避免点击视频后榜单回到顶部或跳到底部。
- `markActiveRankItem()` 只更新当前选中样式，不重新排序当前 DOM。
- 自定义榜单中 `syncSortOptions()` 会隐藏“官方排序”，因为自定义榜单没有稳定的官方 rank。

这种设计牺牲了一点纯图表感，但换来了更好的可读性和更低的滚动成本。

### 8. 当前视频区渲染

当前视频区由 `renderVideoInfo()` 负责，包含封面、标题、UP 主、分 P 选择、核心数据和简介。

- `setVideoCover(video)` 优先使用真实封面，缺失时使用 `web/images/video_placeholder_16x9.png`。
- `renderCurrentVideoStats(video)` 展示播放、点赞、收藏、弹幕、硬币和总长度。
- `renderVideoDescription(video)` 展示视频简介。
- 多 P 视频通过 `pageCache` 和 `partSelect` 控制，切换时调用 `switchPart()` 请求对应 cid 的弹幕。

未选择视频时不会隐藏整个区域，而是显示占位封面、标题“没有选择视频”和 0 数据。这样页面结构稳定，不会因为没有选择视频而出现大面积跳动。

### 9. 图表和统计

主页面图表分为当前视频图表和对比图表两类。

当前视频图表包括：

- `renderTimeChart()`：按视频内分钟统计弹幕时间分布。它会结合视频总长度生成横轴，即使某些分钟没有弹幕也保留刻度。
- `renderLengthChart()`：按弹幕文本长度分为 `1-5`、`6-10`、`11-20`、`20+` 四档。
- `renderWordChart()`：优先使用 BV 搜索返回的服务端词频；缺失时调用 `buildWordStats()` 本地统计高频关键词。
- `renderUserRanking()`：优先使用服务端用户排行；缺失时按 `user_hash` 本地统计用户弹幕贡献榜。

静态榜单、导入数据或旧接口结果没有服务端单视频统计时，词频会回退到 `tokenizeDanmaku()` 轻量切词：英文和数字按连续串处理，中文短句按 2 字窗口拆分，再用 `STOP_WORDS` 去掉常见无意义词。这样保留了离线可用性，也避免旧数据结构无法显示图表。

### 10. 弹幕筛选

弹幕筛选由 `filterDanmakus()` 和 `renderSearchResults()` 组成：

- 内容关键词使用 `includes()` 做包含匹配。
- `user_hash` 使用精确匹配。
- 排序支持按视频内出现时间和 `user_hash`。
- 发送时间、颜色列通过复选框控制显示。
- 普通用户本地筛选有 2 秒间隔限制，管理员不受限制；BV 视频搜索间隔来自当前登录账号的 `search_interval_seconds`，默认 10 秒，可由管理员修改。

筛选只作用于 `currentVideoDanmakus()`，也就是当前选中视频的弹幕。这样搜索历史、榜单选择和分 P 切换都能自然改变筛选范围。

### 11. 视频对比设计

视频对比由 `compareVideos` 保存，最多两个视频。用户点击“添加到对比中”时：

1. 当前视频会先通过 `rememberVideo()` 进入搜索库，避免离开榜单后数据丢失。
2. 如果对比区已有两个不同视频，会弹出 `confirmReplaceCompare()`，确认后替换最早加入的视频。
3. `renderCompareSection()` 生成 A/B 视频卡、核心指标卡片和图表容器。
4. `renderCompareCharts(a, b)` 生成每个指标的横向对比图，以及弹幕时间分布和长度分布图。

核心指标不是放在一张大表里，而是每个指标单独一张卡片。卡片上半部分展示 A/B 数字和差值，下半部分展示横向条形图。这样可以避免不同指标量级差异太大时挤在一个图里看不清，也更符合“每个指标独立比较”的阅读方式。

对比时间分布使用 `buildTimeSeries(rows, duration)`。它不只看弹幕出现过的最大分钟，也会参考视频总长度，所以两个视频时长不一致时，图表会延伸到更长视频结束，而不是在较短视频结束处提前截断。

### 12. 账号中心与身份权限

账号中心位于 `web/login.html`，核心逻辑在 `web/js/login.js`，样式在 `web/css/login.css`。它包含三个状态：

- 未登入：显示账号密码登入，以及注册入口。
- 已登入：显示个人资料、账号脱敏、权限、邮箱脱敏、性别、生日、注册时间、最近登入时间、API 状态、BV 搜索间隔和个人屏蔽词设置。
- 管理员或 owner 账号：额外显示管理员界面。owner 继承管理员能力，并且是唯一可以授予、撤销或维护管理员/owner 权限的角色。

页面背景按状态区分，路径固定在 `web/images/`：

- 未登入背景：`web/images/login_background_01.png`。
- 已登入个人页面背景：`web/images/user_background_01.png`。

`login.js` 在 `renderSession()` 中根据是否登入给 `body` 切换 `account-mode` 类，`login.css` 使用 `--login-bg-image` 变量决定加载哪张背景图。因此两张图片只要放在上述路径，刷新页面即可生效。

账号规则由 `src/account_demo.py` 控制：

- 账号：6-20 位，支持字母、数字、下划线，可以是纯数字。
- 用户名：2-16 个字符。
- 密码：8-32 位，必须同时包含字母和数字。
- 邮箱：使用普通邮箱格式校验。
- 注册需要邮箱验证码和 AI 验证码。当前验证码是 DEMO：邮箱验证码由后端生成并返回给前端展示，不真正发送邮件；AI 验证码使用简单数学题。

账号数据保存在 `data/accounts.txt`，文件是 JSON 文本，便于课程项目查看和调试。默认账号：

```text
项目负责人：owner_demo / Owner12345
管理员：admin_demo / Admin12345
普通用户：user_demo / User12345
```

密码校验使用 `hashlib.pbkdf2_hmac` 生成带随机 salt 的 PBKDF2-SHA256 哈希，格式为 `pbkdf2_sha256$迭代次数$salt$hash`。旧版无盐 SHA-256 账号仍可登录，登录成功后会自动迁移为新哈希，并移除账号文件中的 `demo_password` 字段。该设计已经明显优于普通 SHA-256，但真实公网项目仍建议继续加入密码修改、密码重置、登录失败日志和更完整的风控策略。

登录接口带有基础撞库防护。后端按“账号 + IP”记录失败状态：连续失败 3 次后，登录表单会要求 AI 验证码；连续失败 5 次后，该组合会被短时锁定，并按 1 分钟、3 分钟、5 分钟递增，第三次及之后保持 5 分钟。同时服务端还保留 IP 和账号维度的短窗口频率限制，避免脚本高速试错。错误提示保持泛化，不向用户区分“账号不存在”和“密码错误”。

登录态由 `server.py` 生成 `HttpOnly`、`SameSite=Lax` 的本地会话 Cookie，并通过 `src/session_store.py` 的 `MemorySessionStore` 保存 Cookie token 到账号、CSRF Token、演示身份、创建时间、最近访问时间和过期时间的映射。这样比早期的单个全局登录账号更接近真实多用户访问方式，也避免一个浏览器登录后影响另一个浏览器的账号状态。因为这是 DEMO，默认实现仍是进程内存存储，服务器重启后需要重新登入；后续接入 MySQL 时应实现同接口的 MySQL Session Store。

主功能页顶部不再放身份切换按钮。登入按钮会根据 `/api/account/session` 返回的会话状态显示为“登入”或“个人页面”。功能页里的演示身份由管理员界面切换，但 AI 入口是否显示还会读取后端返回的 `ai_available`：当前账号必须开启 API 开关并保存自己的模型 Provider。演示身份只影响功能页展示，不改变当前登录账号是否拥有管理员页面权限。

个人页面的屏蔽词设置通过 `/api/account/block-words` 读取和保存。前端 textarea 支持每行一个词，后端会去空行、去重复并限制最多 200 个词。个人屏蔽词按账号写入 `data/user_block_words/<账号>.txt`，不会影响其他用户；管理员页可维护 `config/block_words.txt` 全局屏蔽词。个人页会显示个人、全局和最终生效数量。主页面启动后会读取当前账号的 `effective_words`，也就是“全局屏蔽词 + 当前账号个人屏蔽词”，并在当前视频图表、弹幕筛选和 AI 分析输入中按 `drop` 方式过滤命中弹幕。

### 13. API 接入设计

账号中心提供 API 接入开关和本地访问令牌：

- 用户开启 API 后，后端生成一个本地访问令牌，用于 DEMO 鉴权预留，不是第三方模型 API Key。
- 用户可以复制、重置或关闭自己的本地访问令牌。
- API 开关只能由账号本人在个人页面修改，管理员和 owner 不能替普通用户开关 API。
- 主页面 AI 功能必须同时满足“API 开关已开启”和“当前账号已保存模型 Provider”。

当前本地访问令牌是本地演示字段，用于后续真实接口鉴权预留；提交、展示或部署前建议删除或隐藏，避免与真实 API Key 混淆。个人页还提供“自带模型 API”，用于用户填写自己的 DeepSeek、OpenAI 或其他 OpenAI-compatible Key。真实 Key 不写入 `accounts.txt`、不进入前端文件、不写入文档；后端会保存到 `data/secure/api_providers.json`，其中 Key 字段经过本机密钥加密，页面只显示脱敏后的 Key。

模型接入逻辑位于 `src/ai_provider.py`，账号级加密保存位于 `src/secure_provider_store.py`。后端按 OpenAI 兼容格式请求：

```text
POST <Base URL>/chat/completions
model: 用户选择或模板默认模型
```

当前页面内置 DeepSeek、OpenAI、OpenRouter、SiliconFlow、Moonshot/Kimi、智谱 GLM 和自定义 OpenAI-compatible 模板。模板服务商只能使用固定官方 Base URL；自定义 Base URL 必须是 HTTPS，并阻止 `localhost`、内网 IP 和保留地址，避免后端被误用为内网探测工具。Provider 配置按账号隔离保存，后端始终从当前登录 Session 取账号，不接受前端传入账号来决定使用谁的 Key。

用户测试流程：

1. 在账号中心开启“启用 API”。
2. 在“自带模型 API”里选择服务商模板，填入 API Key、Base URL 和模型名。保存后再次修改同一服务商的模型名可以不重新输入 Key；切换服务商时必须重新输入 Key。
3. 点击“保存自带 API”，必要时点击“测试连接”。
4. 回到主功能页，选择 AI 分析模式，选择视频后点击“AI评价”。

AI 评价统一走 `/api/ai/analyze`。如果用户已配置自带模型服务，后端优先调用对应 OpenAI-compatible 接口；如果未配置、网络失败、Key 无效或模型返回格式不合格，会自动回退到 `src/ai_analysis.py` 的本地分析，保证页面不崩。

主页面提供三种 AI 分析模式：

- 省钱模式：默认模式。前端先用全部已加载弹幕做本地统计，再只把指标、候选词、短句候选、峰值样本和代表弹幕交给 AI，适合日常使用和控制费用。
- 深度摘要：扩大短句候选和弹幕样本数量，仍不直接发送全部原文，适合希望 AI 看得更细但不想承担全量原文成本的场景。
- 全量原文：在用户确认后，把当前已加载弹幕原文一并提交给模型。该模式最多支持 20000 条弹幕，并限制请求体约 3.4 MB；超限时页面会提示改用深度摘要模式。

AI 评价面板增加了“分析要求”输入框，当前视频和视频对比各自独立。用户可以写 300 字以内的关注点，例如“重点分析许愿类弹幕”“比较两边观众氛围和峰值原因”。这段文字会随默认提示一起提交给后端，但后端会先清洗控制字符、限制长度并拒绝疑似 API Key 或长密钥；模型提示也明确把它视为“不可信的关注点”，只能调整总结重点，不能覆盖 JSON 输出格式、证据约束或安全规则。不同分析要求会进入缓存 key，因此改要求后不会误用旧报告。

AI 评价按钮默认优先读取缓存。缓存位于 `data/ai_analysis/cache/`，缓存 key 会包含当前账号、模型服务、模型名、分析模式、请求数据、`analysis_prompt_version` 和 `local_stats_version`。若同一批数据已经分析过，再次点击“AI评价”会直接返回缓存结果，减少重复 API 开支；点击“重新分析”会发送 `force_refresh`，明确绕过缓存。若第三方模型调用失败并回退本地分析，该次结果不会写入缓存，避免一次网络超时影响后续重试。

主页面的 AI 评价区域也增加了轻量任务面板。它不会改变 `/api/ai/analyze` 的稳定接口，而是在前端把“整理摘要、提交请求、等待结果、命中缓存或失败”几个阶段可视化出来。这样用户能看到当前是在本地生成摘要，还是已经进入模型请求等待阶段。真正的 AI 后台任务接口可以在后续 MySQL/任务队列接入时继续扩展。

当前本地 AI 评价会分析：

- 当前视频：全部已加载弹幕、词云关键词、弹幕长度、时间峰值、播放/点赞/硬币/收藏/视频长度等指标，并给出氛围判断和建议。
- 视频对比：A/B 两个视频的弹幕规模、氛围、峰值分钟和共同关键词。

词云不是完全交给 AI 随机生成。前端和后端会先基于全部已加载弹幕生成候选词频、短句候选和代表弹幕，再把这些证据交给模型服务。模型负责两类处理：

- 清洗连接词、语气词、泛词和重复切片。
- 对含义相同但字面不同的弹幕做语义聚类，例如把“许愿千冶刃不歪”和“许愿刃叔千冶形态不歪，出必还愿”合并成“许愿刃不歪”一类主题。

模型返回可校验的 `words` 数组，每个词包含 `name`、`value` 和 `reason`。后端只接受有候选词、短句候选或代表弹幕作为证据的结果；校验通过后，主页面“高频关键词”图表会切换为 AI 清洗后的词云数据；校验失败则继续使用本地词频。

每次 AI 分析后，后端会保存最新结果文件，便于调试或课程展示；这些路径不会展示在用户侧 AI 评价文字里：

```text
data/ai_analysis/current_<BV号>_report.txt
data/ai_analysis/current_<BV号>_words.json
data/ai_analysis/compare_latest_report.txt
data/ai_analysis/cache/<hash>.json
```

AI 报告 artifact 还会写入 `analysis_prompt_version` 和 `local_stats_version`。文件模式下最多保留最近 40 个 `current_*` / `compare_*` 报告和词云文件，超出后自动删除较旧 artifact；这个清理不影响 `cache/` 目录和 `usage_stats.json`。

接入真实 API 时仍建议做到：

- API Key 只保存在后端，不直接暴露第三方真实密钥。
- 前端只保存本平台生成的用户 Key。
- 后端用用户 Key 判断权限，再调用真实 API。
- 对真实 API 增加频率限制、错误提示和日志记录。

推荐后续真实接入方式：保留 `/api/ai/analyze` 的请求体结构，让前端继续提交 `scope`、`video`、`danmakus`、`words`、`length_buckets` 和 `time_series`。后端先用 Python 汇总大体量弹幕，再把摘要、关键词、峰值区间和代表弹幕交给真实模型，避免把过长原始弹幕一次性传给第三方 API。

### 14. 管理员界面

管理员界面只在登录账号 `role=admin` 或 `role=owner` 时显示，普通用户看不到。owner 会被主功能页视为管理员演示身份，因此拥有管理员功能页的所有能力；普通管理员可以维护普通账号，但不能修改管理员或 owner 账号，也不能把普通用户提升为管理员。owner 可以授予或回收 admin，但不能通过后台把任何账号提升为 owner。当前 DEMO 管理员功能包括：

- 演示身份切换：在普通用户、API 用户、管理员之间切换功能页演示权限；只有 owner 可以切换 owner 演示身份。
- 热门榜单更新：管理员页调用 `/api/jobs/refresh-popular` 创建后台任务，按默认 50 个视频重新抓取热门榜单并写入当天归档；主页面“今日榜单”只展示这次抓到的当天数据，历史归档通过日期下拉框单独查看。管理员页面会显示进度条、当前步骤、事件列表、失败警告和导出统计。旧的 `/api/refresh-popular` 同步接口已停用。
- 服务器状态查看：显示服务器时间、当前演示身份、当前账号、账号数量、归档日期数和关键数据文件状态；服务器时间会在管理员页按秒实时递增显示。
- 账号权限及数据修改：查看账号列表，修改账号角色、禁用状态和 BV 搜索间隔。API 开关只能账号本人修改；只有 owner 可以修改管理员账号；owner 不能在页面中撤销或禁用自己的 owner 权限，避免误操作造成最高权限丢失。
- 全局屏蔽词维护：管理员可在页面中编辑 `config/block_words.txt`，它会叠加到所有账号的个人屏蔽词上。
- AI 缓存管理：查看 `data/ai_analysis/cache/` 的缓存数量、占用空间和最近缓存时间，可清理 7 天前缓存或在确认后清空缓存。清理只影响缓存，不删除最新 AI 报告文件。
- 本地储存清理：服务启动时会自动清理已有拆分库替代的旧全量弹幕、运行时原始/处理弹幕副本、孤儿分库和过期缓存；管理员页可查看当前榜单分库、旧 `danmakus.json`、历史归档、AI 缓存和报告占用，也可先预览再手动执行清理。归档旧 `today_danmakus.json` 只有在对应日期的拆分库完整时才会清理；历史归档目录删除按日期目录判断，并要求勾选确认。临时关闭启动自动清理可设置 `STORAGE_AUTO_CLEANUP=0`。
- AI 调用统计：个人只能查看自己的 AI 使用记录；全局 AI 使用统计只对 owner 开放。它不读取第三方平台 API 余额或账单，费用仍以模型平台控制台为准。

这部分不是完整后台系统，但接口边界已经按后续替换数据库的方式预留：账号数据现在写入 `data/accounts.txt`，后续可以把 `AccountStore` 替换成数据库实现，前端和接口结构不需要大改。

热门榜单更新现在先使用 `src/job_manager.py` 的内存任务表实现进度可视化，不依赖 MySQL。MySQL 预备结构中已经加入 `jobs` 和 `job_events` 两张任务表，后续接入数据库时可以把同样的任务状态落盘。

### 15. 导入导出和后端接口预留

页面提供 `exportData()` 和 `importData()`，用于把热门数据、搜索数据、自定义榜单导出为 JSON 或重新导入。对比列表不参与导出和导入，因为对比视频可以从单视频查看处重新加入，避免导出文件携带过多临时状态。

导入时会先经过前端清洗层，再通过 `mergeArray()` 去重合并，不直接覆盖已有数据。清洗规则包括：只接受页面需要的视频和弹幕字段；未知字段会被忽略并在导入完成后提示；过长标题、简介、封面地址、用户哈希和弹幕内容会被截断；视频必须带合法 BV 号；弹幕必须带内容，并且要能通过 `bvid` 或 `title` 关联到视频。弹幕总量仍保留 200 万条本地处理上限，大文件和大批量弹幕会弹出确认提示。

后端接口集中在 `API_ENDPOINTS`：

- `/api/search`：BV 搜索和弹幕抓取。
- `/api/video-info`：补抓视频封面、指标和简介。
- `/api/identity`：身份读取和切换。
- `/api/account/session`：读取当前登录状态。
- `/api/account/login`、`/api/account/register`、`/api/account/logout`：账号登入、注册和退出。
- `/api/account/email-code`、`/api/account/ai-captcha`：DEMO 验证码。
- `/api/account/profile`：更新个人资料。
- `/api/account/api-toggle`、`/api/account/api-reset`：当前账号 API 开关和本地访问令牌重置。
- `/api/account/block-words`：读取和保存当前账号的个人屏蔽词配置，落盘到 `data/user_block_words/<账号>.txt`，同时返回全局和最终生效屏蔽词。
- `/api/admin/block-words`：管理员读取和保存全局屏蔽词，落盘到 `config/block_words.txt`。
- `/api/admin/ai-cache`、`/api/admin/ai-cache/clear`：管理员查看和清理 AI 分析缓存。
- `/api/admin/storage-usage`、`/api/admin/storage-cleanup`：管理员查看本地文件模式占用，并预览或执行旧弹幕文件、运行时弹幕副本、孤儿分库、过期缓存和确认后的历史归档清理。
- `/api/account/ai-provider`：读取、保存或清除当前用户的自带模型 API 配置，真实 Key 存在 `data/secure/` 的本机加密存储中，返回给前端时只显示脱敏值。
- `/api/account/ai-provider/test`：使用当前或新填写的模型配置做一次低成本连接测试。
- `/api/admin/status`、`/api/admin/users`、`/api/admin/users/update`：管理员状态和账号管理；owner 继承管理员接口权限，并独占高权限账号管理；API 开关不能由管理员代改。
- `/api/jobs/refresh-popular`、`/api/jobs/search`：创建当前热门榜单更新任务和 BV 搜索任务。
- `/api/jobs/status`、`/api/jobs/result`、`/api/jobs/recent`：轮询任务状态、读取完整任务结果和读取最近任务；普通用户只能读取自己创建的任务，管理员和 owner 可读取管理任务。
- `/api/popular-dates`、`/api/popular-date`：热门榜单日期和轻量榜单数据读取。
- `/api/video-danmakus`：按日期和 BV 号读取单个热门榜单视频的弹幕明细。
- `/api/ai/analyze`：AI 评价统一入口，支持缓存、强制重新分析和三种分析模式；当前可调用用户自带 OpenAI-compatible 模型服务，也可回退本地分析。
- `/api/compare`：预留给后续后端对比分析。
- `/api/background-image`：预留给背景图配置。

目前对比图表仍由前端实时计算，文字评价走 `/api/ai/analyze`。后续如果需要更复杂的分析，例如情绪分类、关键词聚类、AI 总结等，可以继续扩展该接口，前端只负责渲染返回结构。

### 16. 主要设计取舍

- 使用原生 JS 而不是前端框架：项目交互规模可控，原生实现更容易部署成静态页面，也减少依赖安装和课程环境差异。
- 使用集中状态而不是分散 DOM 状态：视频、弹幕、榜单、历史和对比之间共享数据很多，集中状态更容易保证切换后数据不丢失。
- 图表数据优先复用后端单视频统计，缺失时才从当前已加载弹幕实时计算；这样日期切换不用扫描整份弹幕，同时仍能兼容导入数据和旧归档。
- 热门榜单弹幕按需加载：牺牲少量首次点击延迟，换取日期切换和资源释放的稳定速度。
- 搜索数据限制为 15 个：在交互体验和内存占用之间折中。
- 视频详情按需补抓：首屏快，缺什么补什么，静态模式也能降级使用。
- 榜单使用原生滚动列表：更适合长标题和 50 条视频的阅读，比压缩在单张图表中更稳定。
- 账号系统当前仍使用 txt 存储：满足 DEMO 和课程展示。MySQL 表结构已先独立准备，后续替换数据库时优先通过仓储层替换 `AccountStore`，稳定前不影响文件模式。
- AI 评价先做本地兜底：在没有真实 API Key 的情况下也能展示完整流程；正式接入时保留接口路径和前端数据结构。
- 屏蔽词放到个人页：它属于用户更容易理解和管理的偏好设置。当前版本已按账号独立存储，避免一个用户的偏好影响其他用户；全局屏蔽词仍保留给系统级过滤。

### 17. 代码回顾与安全审查

本项目的代码可以按四层理解：采集与处理层、服务端接口层、前端交互层、测试与文档层。

采集与处理层位于 `src/`：

- `collector.py` 负责访问 B 站接口，获取视频信息、分 P 列表和弹幕 XML。
- `parser.py` 把弹幕 XML 转成结构化 JSON，保留时间、颜色、发送时间、用户哈希和内容。
- `filter.py` 负责屏蔽词读取和弹幕删除/打码。
- `analyzer.py` 负责构建 dashboard 汇总数据和 BV 搜索单视频统计，例如视频指标、词频、时间分布、长度分布和用户贡献榜等。
- `danmaku_store.py` 负责按模块、日期和 BV 号拆分弹幕 JSON，并生成 `danmaku_index.json` 和 `video_stats.json`。
- `archive.py` 管理最近 14 天热门榜单归档，并调用拆分弹幕库写入归档目录。
- `pipeline.py` 把采集、过滤、分析和前端导出串起来，前端弹幕导出使用按视频拆分格式。
- `main.py` 提供命令行入口，支持 sample、popular、bv 等模式。
- `ai_analysis.py` 提供无外部模型时的本地兜底分析。
- `ai_provider.py` 管理用户自带 OpenAI-compatible API 的配置校验、请求调用、JSON 返回解析和词云语义合并。
- `secure_provider_store.py` 管理账号级模型 API Key 的本机加密保存。
- `account_demo.py` 管理 DEMO 账号、密码哈希、API Key、账号权限和搜索间隔。
- `session_store.py` 管理登录会话、CSRF Token、演示身份和过期清理；当前默认内存实现，接口形状按 MySQL `sessions` 表预留。
- `job_manager.py` 管理文件模式下的内存后台任务，目前用于热门榜单更新和 BV 搜索进度可视化。较大的 BV 搜索结果会暂存在服务端内存结果池中，前端通过 `/api/jobs/result` 读取后释放；后续可迁移到 MySQL 的 `jobs/job_events`，大结果建议落到文件或对象存储。

服务端接口集中在 `server.py`。它同时承担静态文件服务和本地 API 服务：

- 静态资源只从 `web/` 目录提供，项目根目录下的 `data/accounts.txt` 和 `data/secure/` 不会被当作静态文件直接暴露。
- 所有 JSON 接口统一返回 `Content-Type: application/json; charset=utf-8`。
- JSON 接口增加 `Cache-Control: no-store`，避免账号状态、API Key 脱敏信息、AI 配置状态被浏览器或代理缓存。
- 响应头增加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、基础 `Permissions-Policy` 和保守 CSP，限制页面被 iframe 嵌入和资源来源。
- 登录态使用 `HttpOnly`、`SameSite=Lax` Cookie，而不是由前端保存账号或密码。
- 用户自带模型 Key 不写入 `accounts.txt`，而是写入 `data/secure/api_providers.json` 的加密字段，页面只显示脱敏值；`data/secure/` 已加入 `.gitignore`。
- 模板服务商只允许固定 HTTPS Base URL；自定义 OpenAI-compatible Base URL 会阻止 localhost、内网和保留地址，降低 SSRF 风险。
- AI 分析失败时不把异常堆栈或技术错误直接展示给用户，而是回退本地分析。

前端交互层位于 `web/`：

- `start.html`、`start.css`、`start.js` 负责开始页，背景图路径为 `web/images/start_background_01.png`。
- `index.html`、`dashboard.css`、`app-core.js`、`app-video-store.js`、`app-charts.js`、`app-ai.js`、`app-import-export.js`、`app.js` 负责主功能页，包含榜单、搜索、历史、筛选、当前视频、图表、对比、导入导出和 AI 评价。
- `login.html`、`login.css`、`login.js` 负责账号中心、个人页、API 接入、屏蔽词和管理员界面。
- 前端动态插入用户可控文本时使用 `escapeHtml()`；这次回顾中移除了主页面的动态内联 `onclick`，改为事件委托和 `data-*` 属性。
- 视频跳转链接不再信任导入数据里的 `video_url`，而是按当前视频 `bvid` 统一生成 `https://www.bilibili.com/video/<bvid>`，降低导入恶意 JSON 后出现危险链接的风险。

测试层位于 `tests/`：

- 覆盖采集器、解析器、过滤器、分析器、归档、管道、账号逻辑、权限控制、AI 本地分析、模型 Provider 配置校验和加密存储等核心逻辑。
- 新增本地 HTTP smoke 测试：使用临时账号文件启动测试服务器，验证 `index.html` 安全响应头、登录 Cookie、CSRF 拦截和普通用户访问管理员接口被拒绝。
- 新增前端资源结构测试：检查 `index.html` 的分块 JS 加载顺序，以及 `login.html` 关键 CSS/JS 文件存在。
- 当前仍未引入 Playwright，因此浏览器真实交互和视觉回归仍主要依赖人工检查；这是为了稳定 1.1 文件模式，不额外引入 Node 依赖。

本次安全修复覆盖了以下问题：

- 修复单个全局登录账号导致的跨浏览器状态串扰，改为服务端内存会话 Cookie。
- 密码哈希升级为带随机 salt 的 PBKDF2-SHA256，并兼容旧 SHA-256 登录后自动迁移。
- 登录接口加入失败次数惩罚、验证码门槛和 1/3/5 分钟递增式短时锁定，降低撞库脚本连续试错风险。
- 个人屏蔽词改为账号级文件库，避免一个用户的设置影响其他用户。
- 用户自带模型 API 改为账号级本机加密存储，并限制模板 Base URL；自定义 Base URL 增加 HTTPS、localhost、内网和保留地址校验。
- 移除主功能页动态列表中的内联事件处理器，降低 XSS 扩散面。
- 统一生成 B 站视频跳转链接，避免导入数据携带任意跳转协议。
- 给 JSON 接口增加不缓存策略，给服务端响应增加基础安全头。
- 服务端内存 Session 增加 `SessionStore` 封装、创建时间、最近访问时间、过期时间登记和清理；Cookie 过期后服务端对应 token、CSRF Token 和演示身份状态会一起移除。

## 1.1 文件模式稳定版报告

1.1 版本目标是先把不依赖 MySQL 的功能稳定下来，保证演示时即使没有数据库也能完整运行。当前完成状态如下：

- 主页面：热门榜单、日期切换、BV 搜索、历史补抓诊断、自定义榜单、当前视频数据、弹幕筛选、图表、视频对比、导入导出和 AI 评价均保留文件模式运行。
- 账号中心：登录、注册、个人资料、账号级屏蔽词、自带模型 API、管理员界面、owner 权限边界和热门榜单任务进度可视化已经完成。
- 安全基础：Session Cookie、CSRF Token、同源校验、PBKDF2 密码哈希、登录失败递进锁定、模型 API Key 本机加密保存、本地访问令牌重命名提醒、静态目录隔离和 JSON no-store 已完成。
- 数据稳定性：BV 搜索和热门榜单更新使用后台任务；热门榜单弹幕按日期和视频拆分存储，日期切换只加载轻量索引；搜索库保留 15 个未固定视频；百万弹幕本地处理上限统一为 200 万条；AI 全量原文模式单次最多 20000 条弹幕。
- AI 稳定性：支持省钱模式、深度摘要和全量原文；支持用户分析要求但会进行安全清洗；支持缓存、重新分析、失败回退、版本化缓存 key 和 artifact 保留策略。
- 测试覆盖：Python 单元测试覆盖核心业务函数；HTTP smoke 测试覆盖会话、安全和管理员边界；前端资源测试覆盖主页面脚本顺序。

1.1 版本仍保留的边界：

- 不接入 MySQL 主流程，账号、Session、热门归档、AI 配置和缓存仍默认使用文件或内存。
- 不承诺 B 站历史弹幕必定全量，历史补抓依赖 Cookie、B 站接口策略和快照可用性。
- 不引入 Playwright，浏览器真实交互和视觉回归在 1.1 阶段仍以人工验收为主。
- 不继续扩展 AI 调用额度、计费或更复杂的 AI 使用管理。

仍然保留的 DEMO 级限制：

- 密码哈希已经从 SHA-256 升级为 PBKDF2，但真实项目仍建议引入 bcrypt 或 argon2、密码重置、登录失败日志和异常登录告警。
- 账号数据仍是 `data/accounts.txt`，虽然已有原子写入和线程锁，但没有数据库事务和审计日志；真实部署应改为数据库。
- 会话管理已抽到 `SessionStore`，但当前默认后端仍是单进程内存，服务重启后失效，多进程部署也不会共享会话；真实项目仍应实现 MySQL/Redis 持久化 Store 或改用签名会话。
- 已在同源 `Origin/Referer` 校验基础上增加 Session 级 CSRF Token：登录/注册成功和会话读取会返回 `csrf_token`，前端所有登录后的 POST 会带 `X-CSRF-Token`。真实部署到公网前仍应配合 HTTPS 和更完整的会话持久化。
- 管理员“演示身份切换”是 Session 级 DEMO 功能，它是为了课程展示方便，不是生产权限模型。
- 真实模型 Key 已做本地加密落盘，但如果 `data/secure/server_secret.key` 和 `data/secure/api_providers.json` 同时泄露，仍可能被离线解密；真实部署应使用系统密钥环、KMS 或数据库字段级加密，并增加调用日志脱敏、额度限制和审计。
- 前端导入 JSON 已增加基础 schema 清洗、字段白名单、未知字段报告和文本截断，但它仍是本地演示工具；真实产品如果允许用户上传到服务器，还需要在服务端重复校验并记录审计日志。

## 打包前检查

当前打包准备版本已经移除本机保存过的测试模型 API、B站 Cookie 和本机加密密钥文件。以下文件或目录不应进入最终提交、压缩包或公开展示材料：

```text
data/secure/
config/mysql.local.json
.env
```

`data/secure/` 用于运行时保存账号级模型 Provider、B站历史补抓 Cookie 和本机加密密钥。删除后不会影响页面启动，只是所有账号需要在个人页面重新保存自带模型 API 或 B站历史补抓凭证。`data/secure/` 已写入 `.gitignore`，但手动打包时仍要确认压缩包中没有该目录。

AI 分析缓存和报告位于：

```text
data/ai_analysis/
```

这些文件不包含模型 API Key，但可能包含测试时生成的报告文本、词云结果和调用统计。课程展示可以保留，用于说明 AI 分析流程；如果希望交付一个更干净的包，可以删除 `data/ai_analysis/cache/` 和旧报告文件，程序会在下次分析时重新生成。

打包前建议执行：

```bash
python -m pytest tests
python server.py 8002
```

启动后访问 `http://127.0.0.1:8002/start.html`、`http://127.0.0.1:8002/index.html` 和 `http://127.0.0.1:8002/login.html` 做一次人工检查。默认演示账号仍为 `owner_demo / Owner12345`、`admin_demo / Admin12345`、`user_demo / User12345`。如果打包给他人运行，模型 API 和 B站历史补抓凭证需要由使用者在个人页面重新填写。

## 测试

```bash
python -m pytest tests
```

## 使用评估文档

项目使用过程中的客观优点、不足、适用场景和后续改进建议见：

```text
docs/usage_evaluation.md
```

更完整的代码优化、安全风险、性能瓶颈和后续扩展审查见：

```text
docs/code_optimization_security_review.md
```

MySQL 数据库迁移计划见：

```text
docs/database_migration_plan.md
database/mysql/README.md
database/mysql/001_schema.sql
```
