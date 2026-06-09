# Main Page Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `web/index.html` into the confirmed V7 normal-user layout, with an API-enabled enhancement state that only adds the agreed AI buttons and AI text modules.

**Architecture:** Keep the current static HTML + CSS + vanilla JavaScript structure. Reuse existing data loading, chart rendering, BV search, custom list, import/export, and filtering code, while changing the page layout, sort controls, comparison state, and optional AI UI state. Do not change backend API endpoints in this plan.

**Tech Stack:** HTML, CSS, vanilla JavaScript, ECharts, existing `server.py` static/API server.

---

## File Structure

- Modify `web/index.html`: rebuild the main-page DOM into the V7 layout and add stable IDs for new controls and sections.
- Modify `web/css/dashboard.css`: replace the current dashboard layout styles with the confirmed dark glass V7 layout, responsive rules, comparison rows, and optional AI module styles.
- Modify `web/js/app.js`: add sort mode, comparison slots, anchor navigation, optional AI enhancement toggling, and render functions for the new sections.
- Keep `web/css/shared.css`, `web/start.html`, `web/css/start.css`, and `server.py` unchanged.

## Implementation Tasks

### Task 1: Rebuild Page Structure

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Replace the header with the confirmed top navigation**

Use this structure near the top of `body`, replacing the current `<header class="header container">...</header>` block:

```html
<header class="top-header container">
  <div class="top-title">
    <p class="eyebrow">Bilibili Danmaku Dashboard</p>
    <h1>B站弹幕数据可视化</h1>
  </div>
  <div class="top-actions">
    <button id="loginBtn" type="button" class="header-btn">登入</button>
    <button id="menuBtn" type="button" class="header-btn icon-btn" aria-label="打开菜单">☰</button>
  </div>
</header>
```

- [ ] **Step 2: Replace the old video info bar position**

Remove the standalone `#videoInfoBar` section from above `<main>`. The video info area will be recreated inside `<main>` after the rank and action controls.

- [ ] **Step 3: Rebuild the main content skeleton**

Inside `<main class="container">`, use these top-level sections in this order:

```html
<section id="rankModule" class="rank-module">
  <div class="quick-row">
    <button id="jumpSearchBtn" type="button" class="quick-btn">搜索</button>
    <button id="jumpCompareBtn" type="button" class="quick-btn quick-btn-purple">对比</button>
  </div>
  <div class="rank-control-row">
    <div class="tab-group">
      <button id="hotTab" class="tab-btn active">热门榜单</button>
      <button id="customTab" class="tab-btn">自定义榜单<span id="customCount" class="badge">0/30</span></button>
    </div>
    <select id="sortModeSelect" aria-label="排序方式">
      <option value="official">官方排序</option>
      <option value="like">点赞数排序</option>
      <option value="favorite">收藏数排序</option>
      <option value="danmaku">弹幕数排序</option>
      <option value="coin">硬币数排序</option>
    </select>
  </div>
  <article class="panel rank-panel">
    <h2 id="rankTitle">排行视频标题及可视化数据对比</h2>
    <div id="rankChart" class="chart rank-chart"></div>
  </article>
</section>

<section class="action-row">
  <button id="searchHistoryJumpBtn" type="button" class="btn btn-ghost">搜索及历史查看</button>
  <div class="action-row-right">
    <button id="aiEvaluateCurrentBtn" type="button" class="btn btn-ai ai-only" hidden>AI评价</button>
    <button id="addToCompareBtn" type="button" class="btn btn-ghost">添加到对比中</button>
    <button id="addToCustomBtn" class="btn btn-ghost" title="添加到自定义榜单" type="button">添加到自定义榜单</button>
  </div>
</section>

<section id="videoInfoBar" class="video-detail-grid" aria-label="当前视频">
  <article class="panel video-card">
    <img id="videoCover" class="cover" src="" alt="" referrerpolicy="no-referrer" onerror="this.style.display='none'">
    <a id="videoTitleLink" class="title" href="#" target="_blank" rel="noopener">未选择视频</a>
    <span id="videoOwner" class="owner"></span>
    <select id="partSelect" class="part-select" style="display:none;" aria-label="分P选择"></select>
  </article>
  <article class="panel video-stat-card">
    <h2>当前视频数据</h2>
    <div id="currentVideoStats" class="metric-list"></div>
  </article>
  <article class="panel video-distribution-card">
    <h2>时间 / 长度分布</h2>
    <div id="timeChart" class="chart mini-chart"></div>
    <div id="lengthChart" class="chart mini-chart"></div>
  </article>
</section>
```

- [ ] **Step 4: Move search/filter content below video details**

Keep the existing BV search and filter controls, but wrap them in a stable search section:

```html
<section id="searchSection" class="section search-section">
  <!-- Existing BV 视频搜索 panel -->
  <!-- Existing 弹幕内容筛选 panel -->
</section>
<section id="aiCurrentTextPanel" class="panel ai-text-panel ai-only" hidden>
  <h2>AI评价</h2>
  <p id="aiCurrentText">AI评价的文字内容模块</p>
</section>
```

- [ ] **Step 5: Add the comparison section after search**

Add this section after the search section:

```html
<section id="compareSection" class="section compare-section">
  <article class="panel compare-panel">
    <div class="compare-title-row">
      <span></span>
      <h2>视频对比</h2>
      <button id="aiEvaluateCompareBtn" type="button" class="btn btn-ai ai-only" hidden>AI评价</button>
    </div>
    <div id="compareContent"></div>
    <section id="aiCompareTextPanel" class="ai-text-panel ai-only" hidden>
      <h3>AI评价</h3>
      <p id="aiCompareText">AI评价的文字内容模块</p>
    </section>
  </article>
</section>
```

- [ ] **Step 6: Keep supporting sections**

Keep the custom list management section after the comparison section:

```html
<section id="customManageSection" class="section" style="display:none;">
  <article class="panel">
    <h2>自定义榜单管理</h2>
    <p class="desc">管理自定义榜单中的视频，每个视频可单独移除</p>
    <div id="customVideoList" class="custom-list"></div>
  </article>
</section>
```

- [ ] **Step 7: Manually verify DOM IDs**

Check that every ID referenced in `web/js/app.js` still exists or will be updated in Task 3:

```text
hotTab, customTab, customCount, sortModeSelect, rankChart, jumpSearchBtn,
jumpCompareBtn, searchHistoryJumpBtn, aiEvaluateCurrentBtn, addToCompareBtn,
addToCustomBtn, videoInfoBar, videoCover, videoTitleLink, videoOwner,
partSelect, currentVideoStats, timeChart, lengthChart, searchSection,
compareSection, compareContent, aiEvaluateCompareBtn, aiCurrentTextPanel,
aiCompareTextPanel
```

### Task 2: Implement V7 and AI Styles

**Files:**
- Modify: `web/css/dashboard.css`

- [ ] **Step 1: Add layout variables and top header styles**

Add these styles after the `body` styles:

```css
.top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 36px 0 18px;
}

.top-title .eyebrow {
  margin: 0 0 6px;
  font-family: var(--font-novecento-cond-demibold);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #68f5ff;
}

.top-title h1 {
  margin: 0;
  font-size: 36px;
  font-weight: 900;
}

.top-actions {
  display: flex;
  gap: 10px;
}

.header-btn,
.quick-btn {
  padding: 10px 20px;
  border: 1px solid rgba(104, 245, 255, 0.35);
  border-radius: var(--radius-full);
  background: rgba(15, 23, 42, 0.72);
  color: #68f5ff;
  font-family: var(--font-cjk);
  font-weight: 700;
  cursor: pointer;
}

.icon-btn {
  width: 42px;
  padding-left: 0;
  padding-right: 0;
  color: #cbd5e1;
  border-color: rgba(148, 163, 184, 0.25);
}
```

- [ ] **Step 2: Add rank module styles**

Add:

```css
.rank-module {
  overflow: hidden;
  margin-bottom: 12px;
  border-radius: var(--radius-lg);
  background: rgba(10, 18, 40, 0.64);
  border: 1px solid rgba(255, 255, 255, 0.09);
}

.quick-row {
  display: flex;
  gap: 14px;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.quick-btn-purple {
  color: #c4b5fd;
  border-color: rgba(167, 139, 250, 0.35);
}

.rank-control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.rank-panel {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background:
    linear-gradient(135deg, rgba(56, 189, 248, 0.20), rgba(167, 139, 250, 0.16));
  text-align: center;
}

.rank-panel h2 {
  margin-bottom: 10px;
  font-size: 22px;
  font-weight: 900;
}

.rank-chart {
  height: 360px;
}
```

- [ ] **Step 3: Add action row and detail grid styles**

Add:

```css
.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(10, 18, 40, 0.58);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.action-row-right {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-ai {
  border-color: rgba(251, 191, 36, 0.4);
  background: rgba(251, 191, 36, 0.1);
  color: #fde68a;
}

.video-detail-grid {
  display: grid;
  grid-template-columns: 1.05fr 0.74fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.video-card .cover {
  width: 100%;
  height: 160px;
  border-radius: 14px;
  object-fit: cover;
  background: rgba(148, 163, 184, 0.08);
}

.video-card .title {
  display: block;
  margin-top: 12px;
  font-weight: 800;
  color: var(--text-primary);
}

.metric-list {
  display: grid;
  gap: 10px;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.mini-chart {
  height: 150px;
}
```

- [ ] **Step 4: Add comparison styles**

Add:

```css
.compare-panel {
  overflow: hidden;
  padding: 0;
}

.compare-title-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.compare-title-row h2 {
  margin: 0;
  text-align: center;
}

.compare-title-row .btn-ai {
  justify-self: end;
}

.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.compare-cell {
  padding: 16px;
  text-align: center;
}

.compare-cell:first-child {
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.compare-cover {
  width: 100%;
  height: 180px;
  border-radius: 18px;
  object-fit: cover;
  background: rgba(148, 163, 184, 0.08);
}

.compare-chart {
  height: 86px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.compare-full-row {
  min-height: 92px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-weight: 800;
}

.ai-text-panel {
  min-height: 112px;
  margin-top: 12px;
  padding: 18px;
  border: 1px dashed rgba(251, 191, 36, 0.38);
  border-radius: var(--radius-lg);
  background: rgba(251, 191, 36, 0.07);
  color: #fde68a;
  text-align: center;
}
```

- [ ] **Step 5: Add responsive rules**

Add inside the existing `@media (max-width: 760px)` block:

```css
.top-header,
.action-row,
.rank-control-row {
  align-items: stretch;
  flex-direction: column;
}

.top-actions,
.action-row-right,
.quick-row {
  width: 100%;
  flex-wrap: wrap;
}

.video-detail-grid {
  grid-template-columns: 1fr;
}

.compare-grid {
  grid-template-columns: 1fr;
}

.compare-cell:first-child {
  border-right: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
```

### Task 3: Update JavaScript State and Events

**Files:**
- Modify: `web/js/app.js`

- [ ] **Step 1: Add new state near existing globals**

Add after `let activeList = "hot";`:

```js
let sortMode = "official";
let compareVideos = [];
let apiEnabled = false;
```

- [ ] **Step 2: Add metric helpers after `formatNumber`**

Add:

```js
function metricValue(video, key) {
  if (!video) return 0;
  const aliases = {
    view: ["view", "views"],
    like: ["like", "likes"],
    favorite: ["favorite", "favorites", "fav"],
    danmaku: ["danmaku", "danmaku_count"],
    coin: ["coin", "coins"],
  };
  const keys = aliases[key] || [key];
  for (const name of keys) {
    if (video[name] !== undefined && video[name] !== null) return Number(video[name] || 0);
  }
  return 0;
}
```

- [ ] **Step 3: Replace `getVideoRank`**

Replace the existing `getVideoRank(videos)` with:

```js
function getVideoRank(videos) {
  const sorted = [...videos];
  if (sortMode === "official") {
    sorted.sort((a, b) => (a.rank || 999999) - (b.rank || 999999));
    return sorted;
  }
  sorted.sort((a, b) => metricValue(b, sortMode) - metricValue(a, sortMode));
  return sorted;
}
```

- [ ] **Step 4: Add new event listeners inside `setupEvents`**

First add safe DOM helpers before `setupEvents`:

```js
function byId(id) {
  return document.getElementById(id);
}

function on(id, event, handler) {
  const el = byId(id);
  if (el) el.addEventListener(event, handler);
}
```

Then rewrite `setupEvents` so removed legacy nodes cannot crash the page:

```js
function setupEvents() {
  on("hotTab", "click", () => switchList("hot"));
  on("customTab", "click", () => switchList("custom"));
  on("sortModeSelect", "change", (e) => {
    sortMode = e.target.value;
    renderAll();
  });
  on("jumpSearchBtn", "click", () => scrollToSection("searchSection"));
  on("jumpCompareBtn", "click", () => scrollToSection("compareSection"));
  on("searchHistoryJumpBtn", "click", () => scrollToSection("searchSection"));
  on("addToCompareBtn", "click", () => addToCompare(focusBvid || selectedBvid));
  on("loginBtn", "click", () => alert("登入页面将在后续版本中添加"));
  on("menuBtn", "click", () => alert("菜单功能将在后续版本中添加"));
  on("fetchBvidBtn", "click", () => fetchBvid());
  on("searchBtn", "click", () => filterDanmakus());
  on("releaseBtn", "click", () => releaseQueryData());
  on("resetBtn", "click", resetSearch);
  on("exportBtn", "click", () => exportData());
  on("importFile", "change", (e) => importData(e.target.files[0]));
  on("partSelect", "change", (e) => switchPart(selectedBvid, Number(e.target.value)));
  on("showSendTime", "change", () => renderSearchResults());
  on("showColor", "change", () => renderSearchResults());
  on("addToCustomBtn", "click", () => addToCustom(focusBvid || selectedBvid));
  on("aiEvaluateCurrentBtn", "click", () => toggleAiPanel("aiCurrentTextPanel"));
  on("aiEvaluateCompareBtn", "click", () => toggleAiPanel("aiCompareTextPanel"));
}
```

- [ ] **Step 5: Add navigation helpers**

Add after `setupEvents`:

```js
function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function toggleAiPanel(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.hidden = !el.hidden;
}
```

### Task 4: Render Current Video and Comparison

**Files:**
- Modify: `web/js/app.js`

- [ ] **Step 1: Update `renderVideoInfo` for the new detail grid**

Keep the existing cover/title/owner/part-select logic, but remove `bar.style.display = "flex"` and use:

```js
bar.style.display = "grid";
```

Also add this before the function returns:

```js
renderCurrentVideoStats(video);
```

- [ ] **Step 1b: Remove legacy `backBtn` and `videoFilter` dependencies**

Update rank click behavior so it no longer touches `backBtn`:

```js
charts.rank.on("click", (params) => {
  const videos = getVideoRank(activeVideos());
  const video = videos[params.dataIndex];
  if (!video) return;
  focusBvid = video.bvid;
  selectedBvid = video.bvid;
  renderAll();
  renderVideoInfo();
  filterDanmakus();
});
```

Update `renderAll()` so it no longer calls `populateFilter()`:

```js
function renderAll() {
  renderSummary();
  renderFilterBar();
  renderRankChart();
  renderTimeChart();
  renderLengthChart();
  renderWordChart();
  renderUserRanking();
  renderCustomManage();
  updateCustomCount();
  renderCompareSection();
  applyApiEnhancementState();
}
```

Keep `populateFilter()` only if other code still calls it, but it should not be part of the normal render path after the new layout removes `videoFilter`.

- [ ] **Step 2: Add `renderCurrentVideoStats`**

Add after `renderVideoInfo`:

```js
function renderCurrentVideoStats(video) {
  const box = document.getElementById("currentVideoStats");
  if (!box || !video) return;
  const rows = [
    ["播放", metricValue(video, "view")],
    ["点赞", metricValue(video, "like")],
    ["收藏", metricValue(video, "favorite")],
    ["弹幕", metricValue(video, "danmaku")],
    ["硬币", metricValue(video, "coin")],
  ];
  box.innerHTML = rows.map(([label, value]) => `
    <div class="metric-item">
      <span>${label}</span>
      <strong>${formatNumber(value)}</strong>
    </div>
  `).join("");
}
```

- [ ] **Step 3: Add compare state functions**

Add:

```js
function addToCompare(bvid) {
  if (!bvid || bvid === "all") return;
  const video = findVideo(bvid);
  if (!video) return;
  compareVideos = compareVideos.filter((v) => v.bvid !== video.bvid);
  compareVideos.unshift(video);
  compareVideos = compareVideos.slice(0, 2);
  renderCompareSection();
  scrollToSection("compareSection");
}

function removeFromCompare(bvid) {
  compareVideos = compareVideos.filter((v) => v.bvid !== bvid);
  renderCompareSection();
}
```

- [ ] **Step 4: Add `renderCompareSection`**

Add:

```js
function renderCompareSection() {
  const container = document.getElementById("compareContent");
  if (!container) return;
  const [a, b] = compareVideos;
  if (!a && !b) {
    container.innerHTML = '<div class="compare-full-row">请先从当前视频中添加对比视频</div>';
    return;
  }
  const renderVideo = (video, label) => video ? `
    <div class="compare-cell">
      ${video.cover_url ? `<img class="compare-cover" src="${video.cover_url}" alt="${label} 视频封面" referrerpolicy="no-referrer">` : `<div class="compare-cover">${label} 视频封面</div>`}
    </div>
  ` : `<div class="compare-cell"><div class="compare-cover">${label} 视频封面</div></div>`;
  const title = (video, label) => video ? (video.title || video.bvid || label) : `${label} 标题`;
  const remove = (video) => video ? `<button class="btn btn-ghost" onclick="removeFromCompare('${video.bvid}')">移出按钮</button>` : "";
  const metricRow = (name, key) => `
    <div class="compare-grid">
      <div class="compare-cell">${a ? formatNumber(metricValue(a, key)) : `A ${name}`}</div>
      <div class="compare-cell">${b ? formatNumber(metricValue(b, key)) : `B ${name}`}</div>
    </div>
    <div class="compare-chart">${name}图表</div>
  `;
  container.innerHTML = `
    <div class="compare-grid">${renderVideo(a, "A")}${renderVideo(b, "B")}</div>
    <div class="compare-grid">
      <div class="compare-cell">${title(a, "A")}</div>
      <div class="compare-cell">${title(b, "B")}</div>
    </div>
    <div class="compare-grid">
      <div class="compare-cell">${remove(a)}</div>
      <div class="compare-cell">${remove(b)}</div>
    </div>
    ${metricRow("播放", "view")}
    ${metricRow("点赞", "like")}
    ${metricRow("收藏", "favorite")}
    ${metricRow("弹幕数", "danmaku")}
    ${metricRow("硬币", "coin")}
    <div class="compare-full-row">弹幕时间分布</div>
    <div class="compare-full-row">关键词差异</div>
  `;
}
```

- [ ] **Step 5: Call comparison rendering from `renderAll`**

Add before the end of `renderAll()`:

```js
renderCompareSection();
applyApiEnhancementState();
```

### Task 5: AI Enhancement State

**Files:**
- Modify: `web/js/app.js`

- [ ] **Step 1: Add API state detection**

Add:

```js
function applyApiEnhancementState() {
  apiEnabled = window.localStorage.getItem("danmaku_api_enabled") === "1";
  document.querySelectorAll(".ai-only").forEach((el) => {
    el.hidden = !apiEnabled;
  });
  if (!apiEnabled) {
    const currentPanel = document.getElementById("aiCurrentTextPanel");
    const comparePanel = document.getElementById("aiCompareTextPanel");
    if (currentPanel) currentPanel.hidden = true;
    if (comparePanel) comparePanel.hidden = true;
  }
}
```

- [ ] **Step 2: Add a temporary local enable path for testing**

Do not bind this to `menuBtn` because `menuBtn` already has a click alert. For manual testing, use the browser console:

```js
localStorage.setItem("danmaku_api_enabled", "1");
location.reload();
```

To disable:

```js
localStorage.setItem("danmaku_api_enabled", "0");
location.reload();
```

- [ ] **Step 3: Keep AI enhancement strictly additive**

Verify that the only AI-specific selectors are:

```text
aiEvaluateCurrentBtn
aiCurrentTextPanel
aiEvaluateCompareBtn
aiCompareTextPanel
.ai-only
```

No AI code should move or recreate V7 base layout nodes.

### Task 6: Manual Verification

**Files:**
- Verify: `web/index.html`
- Verify: `web/css/dashboard.css`
- Verify: `web/js/app.js`

- [ ] **Step 1: Start the dev server**

Run:

```powershell
python server.py
```

Expected:

```text
服务已启动：http://127.0.0.1:8000/start.html
旧版入口：http://127.0.0.1:8000/index.html
```

- [ ] **Step 2: Open the main page**

Open:

```text
http://127.0.0.1:8000/index.html
```

Expected:

```text
Top header appears with title on the left and 登入 / menu buttons on the right.
Rank module appears in V7 order.
AI buttons are hidden by default.
```

- [ ] **Step 3: Test sort modes**

Change the sort select through:

```text
官方排序 → 点赞数排序 → 收藏数排序 → 弹幕数排序 → 硬币数排序
```

Expected:

```text
The rank chart updates without JavaScript console errors.
Missing favorite or coin data displays as 0 and does not break rendering.
```

- [ ] **Step 4: Test anchor buttons**

Click:

```text
搜索
对比
搜索及历史查看
```

Expected:

```text
The page scrolls smoothly to the search section or comparison section.
```

- [ ] **Step 5: Test comparison**

Click a ranked video, then click:

```text
添加到对比中
```

Repeat with another video.

Expected:

```text
Two comparison slots display A/B covers, titles, remove buttons, metric rows, chart placeholders, 弹幕时间分布, and 关键词差异.
```

- [ ] **Step 6: Test remove from comparison**

Click:

```text
移出按钮
```

Expected:

```text
The selected video is removed from the comparison group and the remaining slot stays visible.
```

- [ ] **Step 7: Test AI enhancement toggle**

In the browser console, run:

```js
localStorage.setItem("danmaku_api_enabled", "1");
location.reload();
```

Expected:

```text
AI评价 buttons become visible in exactly two places:
1. The leftmost button in the right side of the 搜索及历史查看 action row.
2. The far right of the 视频对比 title row.
```

Then run:

```js
localStorage.setItem("danmaku_api_enabled", "0");
location.reload();
```

Expected:

```text
AI buttons and AI text panels are hidden again.
```

- [ ] **Step 8: Run existing Python tests**

Run:

```powershell
python -m pytest tests
```

Expected:

```text
All existing tests pass.
```

## Self-Review Notes

- Spec coverage: the plan covers V7 layout, sorting, current video data, search anchors, comparison group, removal, and AI enhancement as a strictly additive state.
- Placeholder scan: no implementation step uses TBD/TODO/fill-in language.
- Type consistency: new IDs and functions are named consistently across HTML, CSS, and JS tasks.
- Commit note: do not create git commits unless the user explicitly requests a commit.
