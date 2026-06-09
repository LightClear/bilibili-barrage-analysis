# app.js 分块化记录

本文档记录主功能页 `web/js/app.js` 的逐步拆分方案。目标不是一次性重写，而是在每一轮只抽出边界清晰、风险较低的模块，保证当前页面功能持续可运行。

## 拆分原则

- 先拆纯工具，再拆业务功能。
- 每次拆分只移动一类职责，避免同时改状态结构和页面行为。
- 保留当前无打包工具的静态页面模式，优先使用普通 `<script>` 顺序加载。
- 每次拆分后至少执行 `node --check` 和 `pytest`。
- 如果某个模块仍大量读写 `app.js` 的全局状态，先不强行抽出，等接口稳定后再拆。

## 当前模块

当前行数概况：

- `web/js/app-core.js`：约 257 行。
- `web/js/app-video-store.js`：约 359 行。
- `web/js/app-charts.js`：约 513 行。
- `web/js/app-ai.js`：约 410 行。
- `web/js/app-import-export.js`：约 322 行。
- `web/js/app.js`：约 1090 行。

这表示主页面低风险分块已经完成五轮。后续如果继续拆，应优先处理更细的交互协调层，而不是再大规模移动核心状态。

### `web/js/app-core.js`

第一轮已完成。

职责：

- 全局常量，例如接口地址、弹幕数量限制、AI 分析限制、任务状态集合。
- DOM 小工具，例如 `byId()`、`on()`。
- 格式化工具，例如 `formatNumber()`、`formatBytes()`、`formatTime()`。
- HTML 转义 `escapeHtml()`。
- JSON 请求封装 `requestJson()` 和 CSRF Header 拼接。
- 任务进度面板渲染，例如 BV 获取任务、热门日期刷新任务、AI 分析任务。

拆出原因：

- 这部分基本不包含业务状态判断。
- 很多功能都会调用这些工具，放在独立模块后可以减少 `app.js` 顶部噪音。
- 任务面板的渲染规则集中后，后续增加 AI 后台任务或其他任务类型时更容易复用。

### `web/js/app-charts.js`

第四轮已完成。

职责：

- ECharts 实例状态和初始化，例如 `charts`、`initCharts()`、`resizeAllCharts()`。
- 当前视频的播放时间分布、弹幕发送时间分布、长度分布和词频图。
- 用户弹幕贡献榜表格。
- 视频对比区的核心指标小图、弹幕时间分布和弹幕长度分布。
- 视频对比区图表实例复用，避免切换对比视频时重复 dispose/recreate。
- 图表和 AI 共用的统计缓存，例如 `statsCache`、`getVideoStats()`、`getCachedWordStats()`。

拆出原因：

- 图表渲染和统计计算已经形成独立职责，和 BV 搜索、导入导出、账号身份没有必要混在同一个主文件里。
- 当前视频图表、对比图表和 AI 摘要会复用同一批统计结果，集中到图表模块后更容易维护缓存失效规则。
- 独立后 `app.js` 从约 1972 行降到约 1458 行，主文件更接近“页面状态和业务流程协调器”。

当前边界：

- `app-charts.js` 仍会读取页面状态，例如 `currentVideo()`、`sendTimeMode`、`aiWordStatsByBvid`、`rankScrollTop`。
- 这是当前静态脚本加载模式下的保守拆分。后续如果继续演进，可以把这些依赖整理为更明确的状态接口。

### `web/js/app-video-store.js`

第五轮已完成。

职责：

- 视频元信息 helper，例如封面地址、视频简介、B 站视频页链接和封面占位图处理。
- 视频详情补抓和视频信息同步，例如 `hydrateVideoInfo()`、`updateVideoEverywhere()`。
- 当前视频入口，例如 `getCurrentBvid()`、`currentVideo()`、`currentVideoDanmakus()`。
- 视频查找和弹幕池懒索引，例如 `findVideo()`、`getDanmakusForVideo()`、`invalidateDanmakuPoolIndex()`。
- 搜索历史库和短期缓存释放，例如 `rememberVideo()`、`pruneSearchedData()`、`renderSearchHistory()`。
- 自定义榜单增删和管理列表，例如 `addToCustom()`、`removeFromCustom()`、`renderCustomManage()`。
- 账号屏蔽词对当前视频弹幕的前端过滤入口，例如 `applyActiveBlockWords()`、`setActiveBlockWords()`。

拆出原因：

- “当前视频来自哪里”是主页面最容易引发 bug 的问题，涉及热门榜单、BV 搜索、自定义榜单、历史库和对比列表。
- 把视频查找、弹幕合并、历史缓存释放集中后，图表、AI、搜索和对比都能通过同一组入口读取数据。
- 独立后 `app.js` 从约 1458 行降到约 1090 行，主文件主要保留页面启动、榜单切换、搜索任务、筛选表格和对比卡片协调。

当前边界：

- `app-video-store.js` 仍会调用 `renderAll()`、`renderVideoInfo()`、`filterDanmakus()` 等页面刷新函数。
- 这是为了保持现有行为不变。若后续引入框架或明确状态接口，可以把“数据变更后刷新哪些区域”进一步收窄为统一调度函数。

### `web/js/app-ai.js`

第二轮已完成。

职责：

- AI 分析模式读取与显示，例如省钱模式、深度摘要、全量原文。
- AI 分析要求输入框的文本清洗和字数统计。
- 当前视频与对比视频的 AI 请求数据整理。
- 词频候选、短句候选、峰值弹幕样本和全量原文模式数据压缩。
- 当前视频 AI 评价和对比 AI 评价的请求流程。
- AI 返回词云数据后写入 `aiWordStatsByBvid` 并触发词云重绘。

拆出原因：

- AI 评价流程已经形成独立用户工作流，包含输入要求、数据摘要、请求、缓存提示和词云更新。
- 这部分代码改动频率较高，后续可能继续接入后台任务、更多分析模式或模型返回校验。
- 独立后可以让主 `app.js` 更聚焦页面状态、榜单、搜索、图表和对比结构。

当前边界：

- `app-ai.js` 仍读取页面中的视频状态和图表函数，例如 `currentVideo()`、`getVideoStats()`、`getCachedWordStats()`、`renderWordChart()`。
- 这是有意保守处理。后续如果引入明确状态接口，再把这些读取接口收窄。

### `web/js/app-import-export.js`

第三轮已完成。

职责：

- 导出当前热门榜单、搜索历史库、自定义榜单和对应弹幕数据。
- 导入 JSON 前的白名单字段校验、BV 号校验、文本截断、数字清洗和封面地址清洗。
- 导入数据总量确认、大文件确认、超限拒绝和导入问题报告。
- 导入成功后合并视频与弹幕，并触发现有页面刷新函数。

拆出原因：

- 导入导出代码以数据清洗为主，和榜单渲染、图表绘制、AI 评价的直接耦合较低。
- 该部分安全规则较多，独立后更容易后续补单元测试和兼容旧版导出格式。
- 拆出后 `app.js` 少约 300 行，主文件能更聚焦页面状态与核心交互。

当前边界：

- `app-import-export.js` 仍会在导入成功后调用 `renderAll()`、`renderVideoInfo()`、`filterDanmakus()` 等主页面刷新函数。
- 这是为了保持现有行为不变。后续如果补齐前端 E2E，可以再把导入后的合并和刷新入口整理成更明确的接口。

### `web/js/app.js`

当前仍负责主功能页的核心业务流程：

- 页面状态。
- BV 搜索和任务轮询。
- 弹幕筛选。
- 视频对比。
- 页面启动流程。

## 后续拆分顺序建议

当前不建议继续为了拆分而拆分。剩余的 `app.js` 主要是页面协调逻辑，如果继续移动，建议先补前端 E2E 测试，再考虑：

- `app-search.js`：BV 搜索任务、分 P 切换、任务轮询。
- `app-compare.js`：对比卡片 HTML、添加/移除对比、替换确认。
- `app-filters.js`：弹幕筛选表格、分页、排序。

这些模块比前五轮更依赖页面状态，拆分前最好先确认测试覆盖。

## 当前验证记录

第一轮拆分后已执行：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。

第二轮拆分后已执行：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app-ai.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。

第三轮拆分后已执行：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app-ai.js
node --check .\web\js\app-import-export.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。

统计缓存补强后已执行同一组检查：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app-ai.js
node --check .\web\js\app-import-export.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。

第四轮图表模块拆分后已执行：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app-charts.js
node --check .\web\js\app-ai.js
node --check .\web\js\app-import-export.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。

第五轮视频数据模块拆分后已执行：

```powershell
node --check .\web\js\app-core.js
node --check .\web\js\app-video-store.js
node --check .\web\js\app-charts.js
node --check .\web\js\app-ai.js
node --check .\web\js\app-import-export.js
node --check .\web\js\app.js
python -m pytest .\tests
```

结果：`77 passed`。
