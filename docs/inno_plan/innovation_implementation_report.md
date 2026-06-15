# 创新点落地实现报告

> 对应计划：`docs/inno_plan/selected_innovation_landing_plan.md`  
> 实现分支：`feature/innovation-plan-execution`  
> 实现日期：2026-06-09

---

## 一、已落地能力

本轮已完成三个“便于实现”的创新点主链路：

1. **弹幕真实回放 + 情绪心电图双轨道**
   - 后端新增弹幕回放轨道构造与情绪时间线聚合。
   - 前端新增“弹幕回放”面板，包含 Canvas 弹幕轨道、播放 / 暂停、时间拖动条、情绪心电图。
   - 接口：`GET /api/playback/track?date=current&bvid=...`

2. **轻量弹幕情感分类器**
   - 新增本地情绪词典配置：`config/sentiment_words.json`。
   - 新增 `classify_sentiment`、`classify_danmaku_sentiments`、`build_sentiment_timeline`。
   - 默认零外部依赖，LLM 不可用时仍可生成情绪趋势。

3. **跨视频关键词桑基迁移图 + 主题河流**
   - 新增跨视频分析模块：`src/cross_video_analyzer.py`。
   - 后端从最近归档数据生成关键词-视频 Sankey、themeRiver 数据和样本弹幕。
   - 前端新增“跨视频关键词传播”面板，包含桑基图、主题河流、关键词样本弹幕。
   - 接口：`GET /api/cross-video/keywords?days=14&top_k=30&row_limit=5000`

---

## 二、主要文件变更

### 后端

- `src/analyzer.py`
  - 新增本地情绪词典加载。
  - 新增情绪分类、弹幕情绪批处理、情绪时间线聚合。
  - 新增 Canvas 回放所需的弹幕轨道构造。

- `src/cross_video_analyzer.py`
  - 新增跨视频关键词分词统计。
  - 新增桑基图节点 / 边数据构造。
  - 新增主题河流数据构造。
  - 新增关键词样本弹幕收集。

- `server.py`
  - 新增 `/api/playback/track`。
  - 新增 `/api/cross-video/keywords`。
  - 跨视频接口支持 `row_limit`，避免演示时读取归档全量弹幕过慢。

### 前端

- `web/index.html`
  - 新增弹幕回放面板。
  - 新增跨视频关键词传播面板。
  - 新增 `web/js/app-playback.js` 加载。

- `web/js/app-playback.js`
  - 新增播放状态管理。
  - 新增回放接口加载、Canvas 轨道绘制、情绪心电图渲染。

- `web/js/app-charts.js`
  - 新增跨视频接口加载。
  - 新增 ECharts Sankey 和 themeRiver 渲染。
  - 新增关键词样本弹幕联动展示。

- `web/js/app-core.js`
  - 新增 `playbackTrack` 与 `crossVideoKeywords` API 常量。

- `web/js/app.js`
  - 在主渲染流程中接入回放面板和跨视频面板刷新。

- `web/css/dashboard.css`
  - 新增回放面板与跨视频传播面板样式。

### 测试

- `tests/test_analyzer.py`
  - 覆盖情绪分类、否定词 / 强度词、情绪时间线、回放轨道。

- `tests/test_cross_video_analyzer.py`
  - 覆盖跨视频 Sankey、主题河流和样本弹幕。

- `tests/test_server_http_smoke.py`
  - 覆盖播放接口、跨视频接口、`row_limit` 采样。

- `tests/test_frontend_assets.py`
  - 覆盖新增前端脚本加载顺序、回放 DOM、跨视频 DOM 和 API 常量。

---

## 三、演示步骤

1. 启动服务：

   ```powershell
   $env:STORAGE_AUTO_CLEANUP='0'
   $env:PYTHONDONTWRITEBYTECODE='1'
   .\venv\Scripts\python.exe server.py 8017
   ```

2. 打开：

   ```text
   http://127.0.0.1:8017/index.html
   ```

3. 展示顺序：
   - 点击热门榜单中的任意视频。
   - 在“弹幕回放”面板点击播放，展示弹幕沿时间轨道出现。
   - 拖动时间条，观察弹幕轨道和情绪心电图同步变化。
   - 下滑到“跨视频关键词传播”，展示关键词-视频桑基图、主题河流和样本弹幕。

---

## 四、验证结果

- 完整测试套件：`151 passed`。
- 浏览器验证：
  - 页面可加载。
  - 回放面板和跨视频面板尺寸正常。
  - 选择视频后回放接口可加载 1,631 条轨道弹幕。
  - 回放播放按钮加载后可用。
  - 跨视频面板 6 秒内完成真实归档数据加载。
  - 浏览器控制台无 error。

---

## 五、已知取舍

- 情绪分类为本地词典规则，适合趋势展示，不宣称高精度语义理解。
- 跨视频接口默认使用 `row_limit=5000` 做每个归档日采样，优先保证演示响应速度。
- 跨视频关键词第一阶段使用裸关键词；后续可接入梗知识库做规范化 slug。
