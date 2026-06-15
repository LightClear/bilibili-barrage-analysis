let dashboardData = null;
let danmakus = [];
let searchedVideos = [];
let searchedDanmakus = [];
let customVideos = [];
let customDanmakus = [];
let searchHistory = [];
let pageCache = {};
let danmakuPoolIndex = null;
let selectedBvid = "all";
let focusBvid = null;
let activeList = "hot";
let sortMode = "official";
let compareVideos = [];
let currentQueryRows = [];
let searchResultPage = 1;
let currentRole = "normal";
let accountSession = null;
let lastBvidFetchAt = null;
let lastLocalSearchAt = null;
let videoInfoHydrationTried = new Set();
let rankScrollTop = 0;
let hotDate = "current";
let hotDanmakuIndex = null;
let loadedHotDanmakuKeys = new Set();
let aiWordStatsByBvid = {};
let sendTimeMode = "auto";
let activeBlockWords = [];
let csrfToken = "";
let currentAiAvailable = false;
let searchResultPageSize = 300;
let bvidJobPollTimer = null;
let hotDateJobPollTimer = null;

function confirmReplaceCompare(oldest) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.innerHTML = `
      <div class="confirm-card" role="dialog" aria-modal="true">
        <h3>替换对比视频</h3>
        <p>视频对比已有两个视频，是否替换最先加入的「${escapeHtml(videoLabel(oldest))}」？</p>
        <div class="confirm-actions">
          <button type="button" class="btn btn-ghost" data-confirm="cancel">取消</button>
          <button type="button" class="btn btn-compare" data-confirm="ok">确认替换</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (event) => {
      const action = event.target.dataset.confirm;
      if (!action && !event.target.classList.contains("confirm-overlay")) return;
      overlay.remove();
      resolve(action === "ok");
    });
  });
}

function getVideoRank(videos) {
  const sorted = [...videos];
  if (sortMode === "official") {
    sorted.sort((a, b) => (a.rank || 999999) - (b.rank || 999999));
    return sorted;
  }
  sorted.sort((a, b) => metricValue(b, sortMode) - metricValue(a, sortMode));
  return sorted;
}

async function loadJSON(path) {
  const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`无法读取 ${path}`);
  return r.json();
}

async function loadOptionalJSON(path, fallback = null) {
  try {
    return await loadJSON(path);
  } catch {
    return fallback;
  }
}

function applyVideoStatsToDashboard(stats, index = null) {
  const videos = dashboardData?.raw_videos || [];
  videos.forEach((video) => {
    const bvid = String(video.bvid || "");
    if (stats?.[bvid]) video.stats = stats[bvid];
    const meta = index?.videos?.[bvid];
    if (meta) {
      video.danmaku_store = {
        file: meta.file || "",
        count: Number(meta.count || 0),
      };
    }
  });
}

function normalizeDashboardData(data) {
  const dash = data && typeof data === "object" ? data : {};
  if (!Array.isArray(dash.raw_videos)) {
    dash.raw_videos = Array.isArray(dash.videos)
      ? dash.videos
      : (Array.isArray(dash.hot_videos) ? dash.hot_videos : []);
  }
  return dash;
}

async function loadAllData() {
  const [dash, stats, index] = await Promise.all([
    loadJSON("./data/dashboard.json"),
    loadOptionalJSON("./data/video_stats.json", {}),
    loadOptionalJSON("./data/danmaku_index.json", null),
  ]);
  dashboardData = normalizeDashboardData(dash);
  hotDanmakuIndex = index;
  applyVideoStatsToDashboard(stats, index);
  danmakus = [];
  loadedHotDanmakuKeys = new Set();
  invalidateDanmakuPoolIndex();
}

function setupEvents() {
  on("hotTab", "click", () => switchList("hot"));
  on("customTab", "click", () => switchList("custom"));
  on("sortModeSelect", "change", (e) => {
    sortMode = e.target.value;
    syncSortOptions();
    rankScrollTop = 0;
    renderAll();
  });
  on("hotDateSelect", "change", (e) => loadPopularDate(e.target.value));
  on("refreshHotDateDataBtn", "click", () => refreshHotDateData());
  on("jumpSearchBtn", "click", () => scrollToSection("searchSection"));
  on("jumpCompareBtn", "click", () => scrollToSection("compareSection"));
  on("addToCompareBtn", "click", () => addToCompare(focusBvid || selectedBvid));
  on("addToCustomBtn", "click", () => addToCustom(focusBvid || selectedBvid));
  on("identityNormalBtn", "click", () => setIdentity("normal"));
  on("identityApiBtn", "click", () => setIdentity("api"));
  on("identityAdminBtn", "click", () => setIdentity("admin"));
  on("identityOwnerBtn", "click", () => setIdentity("owner"));
  on("aiEvaluateCurrentBtn", "click", () => evaluateCurrentVideo(false));
  on("aiForceCurrentBtn", "click", () => evaluateCurrentVideo(true));
  on("aiEvaluateCompareBtn", "click", () => evaluateCompareVideos(false));
  on("aiForceCompareBtn", "click", () => evaluateCompareVideos(true));
  on("aiCurrentRequirement", "input", () => updateAiRequirementCount("current"));
  on("aiCompareRequirement", "input", () => updateAiRequirementCount("compare"));
  on("fetchBvidBtn", "click", () => fetchBvid());
  on("refreshCurrentVideoBtn", "click", () => refreshCurrentVideoData());
  on("searchBtn", "click", () => filterDanmakus({ enforceInterval: true }));
  on("resetBtn", "click", resetSearch);
  on("exportBtn", "click", () => exportData());
  on("importBtn", "click", () => byId("importFile")?.click());
  on("importFile", "change", (e) => importData(e.target.files[0]));
  on("partSelect", "change", (e) => switchPart(selectedBvid, Number(e.target.value)));
  on("showSendTime", "change", () => renderSearchResults());
  on("showColor", "change", () => renderSearchResults());
  if (typeof setupPlaybackEvents === "function") setupPlaybackEvents();
  on("reloadCrossVideoBtn", "click", () => renderCrossVideoPanel({ force: true }));
  on("sortSelect", "change", () => filterDanmakus());
  on("searchPageSize", "change", () => {
    const value = Number(byId("searchPageSize").value);
    searchResultPageSize = [100, 300, 500].includes(value) ? value : SEARCH_RESULT_PAGE_SIZE;
    searchResultPage = 1;
    renderSearchResults();
  });
  on("prevSearchPage", "click", () => setSearchPage(searchResultPage - 1));
  on("nextSearchPage", "click", () => setSearchPage(searchResultPage + 1));
  const sendTimeTabs = byId("sendTimeModeTabs");
  if (sendTimeTabs) {
    sendTimeTabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-send-time-mode]");
      if (!button) return;
      sendTimeMode = button.dataset.sendTimeMode || "auto";
      syncSendTimeModeButtons();
      renderSendTimeChart();
    });
  }
  const customList = byId("customVideoList");
  if (customList) {
    customList.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-custom]");
      if (button) removeFromCustom(button.dataset.bvid);
    });
  }
  const historyTags = byId("historyTags");
  if (historyTags) {
    historyTags.addEventListener("click", (event) => {
      const tag = event.target.closest("[data-history-bvid]");
      if (tag) selectHistory(tag.dataset.bvid);
    });
  }
  const compareContent = byId("compareContent");
  if (compareContent) {
    compareContent.addEventListener("click", (event) => {
      const button = event.target.closest("[data-compare-remove]");
      if (button) removeFromCompare(button.dataset.bvid);
    });
  }
  on("bvidSearchInput", "keydown", (e) => {
    if (e.key === "Enter") fetchBvid();
  });
}

function scrollToSection(id) {
  const el = byId(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadIdentity() {
  const fallbackRole = localStorage.getItem(IDENTITY_STORAGE_KEY) || "normal";
  try {
    const resp = await fetch(API_ENDPOINTS.identity, { cache: "no-store" });
    const result = await resp.json();
    applyIdentity(result.ok ? result.role : fallbackRole, result.ok ? result.ai_available : undefined);
  } catch {
    applyIdentity(fallbackRole, fallbackRole === "api");
  }
}

async function setIdentity(role) {
  localStorage.setItem(IDENTITY_STORAGE_KEY, role);
  try {
    const resp = await fetch(API_ENDPOINTS.identity, {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ role }),
    });
    const result = await resp.json();
    applyIdentity(result.ok ? result.role : role, result.ok ? result.ai_available : undefined);
  } catch {
    applyIdentity(role, role === "api");
  }
}

function applyIdentity(role, aiAvailable = undefined) {
  currentRole = ["normal", "api", "admin", "owner"].includes(role) ? role : "normal";
  if (typeof aiAvailable === "boolean") {
    currentAiAvailable = aiAvailable;
  }
  document.querySelectorAll(".identity-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.role === currentRole);
  });
  document.querySelectorAll(".ai-only").forEach((el) => {
    el.hidden = !currentAiAvailable;
  });
  syncSortOptions();
  syncDebugPanelVisibility();
}

async function loadAccountSession() {
  try {
    const resp = await fetch(API_ENDPOINTS.accountSession, { cache: "no-store" });
    accountSession = await resp.json();
    csrfToken = accountSession?.logged_in ? (accountSession.csrf_token || "") : "";
    await loadActiveBlockWords();
  } catch {
    accountSession = { ok: false, logged_in: false, user: null };
    activeBlockWords = [];
    csrfToken = "";
  }
  renderLoginEntry();
  syncDebugPanelVisibility();
}

async function loadActiveBlockWords() {
  setActiveBlockWords([]);
  if (!accountSession?.ok || !accountSession.logged_in) return;
  try {
    const resp = await fetch(API_ENDPOINTS.blockWords, { cache: "no-store" });
    const data = await resp.json();
    if (data.ok) setActiveBlockWords(data.effective_words);
  } catch {
    setActiveBlockWords([]);
  }
}

function renderLoginEntry() {
  const btn = byId("loginBtn");
  if (!btn) return;
  btn.href = "./login.html";
  if (accountSession?.ok && accountSession.logged_in) {
    btn.textContent = "个人页面";
    btn.title = accountSession.user?.username || "个人页面";
  } else {
    btn.textContent = "登入";
    btn.removeAttribute("title");
  }
}

function isAdmin() {
  return currentRole === "admin" || currentRole === "owner";
}

function isOwner() {
  return currentRole === "owner";
}

function isPrivilegedAccount() {
  const role = accountSession?.user?.role;
  return accountSession?.logged_in && (role === "admin" || role === "owner");
}

function canViewDebugPanels() {
  return isPrivilegedAccount();
}

function syncDebugPanelVisibility() {
  if (canViewDebugPanels()) {
    renderFetchDiagnostics(currentVideo());
    return;
  }
  ["bvidTaskPanel", "hotDateTaskPanel"].forEach((id) => {
    const panel = byId(id);
    if (panel) panel.hidden = true;
  });
  const diagnostics = byId("danmakuFetchDiagnostics");
  if (diagnostics) {
    diagnostics.hidden = true;
    diagnostics.innerHTML = "";
  }
}

function canRefreshHotDateData(date = hotDate) {
  if (date === "current") {
    return accountSession?.logged_in || isAdmin();
  }
  return false;
}

function switchList(list) {
  activeList = list;
  rankScrollTop = 0;
  byId("hotTab").classList.toggle("active", list === "hot");
  byId("customTab").classList.toggle("active", list === "custom");
  byId("customManageSection").style.display = list === "custom" ? "" : "none";
  syncSortOptions();
  renderAll();
  renderVideoInfo();
  filterDanmakus();
}

function syncSortOptions() {
  const select = byId("sortModeSelect");
  const officialOption = byId("officialSortOption");
  const dateControl = byId("hotDateControl");
  const dateRefreshButton = byId("refreshHotDateDataBtn");
  const dateLimitSelect = byId("popularLimitSelect");
  const dateTaskPanel = byId("hotDateTaskPanel");
  if (!select || !officialOption) return;
  const isCustom = activeList === "custom";
  if (dateControl) dateControl.hidden = isCustom;
  const showRefresh = !isCustom && canRefreshHotDateData(byId("hotDateSelect")?.value || hotDate || "current");
  if (dateRefreshButton) dateRefreshButton.hidden = !showRefresh;
  if (dateLimitSelect) dateLimitSelect.hidden = !showRefresh;
  if (dateTaskPanel && isCustom) dateTaskPanel.hidden = true;
  officialOption.hidden = isCustom;
  officialOption.disabled = isCustom;
  if (isCustom && sortMode === "official") {
    sortMode = "danmaku";
  }
  select.value = sortMode;
}

async function loadPopularDates() {
  const select = byId("hotDateSelect");
  if (!select) return;
  try {
    const resp = await fetch(API_ENDPOINTS.popularDates, { cache: "no-store" });
    const result = await resp.json();
    if (!result.ok) return;
    select.innerHTML = result.dates.map((item) =>
      `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`
    ).join("");
    select.value = hotDate;
    syncSortOptions();
  } catch {
    // 静态打开页面时保留“当前榜单”选项。
  }
}

async function loadPopularDate(date, force = false) {
  if (!date || (!force && date === hotDate)) return;
  const selected = currentVideo();
  if (selected) rememberVideo(selected, currentVideoDanmakus());
  const title = byId("rankTitle");
  const previousTitle = title ? title.textContent : "";
  if (title) title.textContent = "正在切换热门榜单日期...";
  try {
    const resp = await fetch(`${API_ENDPOINTS.popularDate}?date=${encodeURIComponent(date)}`, { cache: "no-store" });
    const result = await resp.json();
    if (!result.ok) throw new Error(result.error || "切换日期失败");
    dashboardData = normalizeDashboardData(result.dashboard);
    hotDanmakuIndex = result.danmaku_index || null;
    applyVideoStatsToDashboard(result.video_stats || {}, hotDanmakuIndex);
    danmakus = [];
    loadedHotDanmakuKeys = new Set();
    invalidateDanmakuPoolIndex();
    hotDate = date;
    rankScrollTop = 0;
    syncSortOptions();
    renderAll();
    if (title) {
      title.textContent = date === "current" ? "排行视频标题及可视化数据对比" : `${date} 热门榜单视频标题及可视化数据对比`;
    }
    renderVideoInfo();
    filterDanmakus();
  } catch (err) {
    if (title) title.textContent = previousTitle;
    const select = byId("hotDateSelect");
    if (select) select.value = hotDate;
    syncSortOptions();
    alert(err.message);
  }
}

function setHotDateRefreshBusy(isBusy) {
  const button = byId("refreshHotDateDataBtn");
  const limitSelect = byId("popularLimitSelect");
  if (button) button.disabled = Boolean(isBusy);
  if (limitSelect) limitSelect.disabled = Boolean(isBusy);
}

function stopHotDateJobPolling() {
  if (hotDateJobPollTimer) {
    clearInterval(hotDateJobPollTimer);
    hotDateJobPollTimer = null;
  }
}

function hotDateJobTitle(date, done = false) {
  const prefix = date === "current" ? "当前热门榜单" : `${date} 归档榜单`;
  return `${prefix}${done ? "更新完成" : "数据更新"}`;
}

async function finishHotDateJob(job, date) {
  stopHotDateJobPolling();
  setHotDateRefreshBusy(false);
  const title = hotDateJobTitle(date, job.status === "success");
  if (job.status === "success") {
    renderJobTask("hotDate", { ...job, progress: 100 }, title);
    await loadPopularDates();
    await loadPopularDate(date, true);
    const select = byId("hotDateSelect");
    if (select) select.value = date;
    return;
  }
  renderJobTask("hotDate", job, `${date === "current" ? "当前热门榜单" : `${date} 归档榜单`}更新失败`);
}

async function pollHotDateJobStatus(jobId, date) {
  const data = await requestJson(`${API_ENDPOINTS.jobStatus}?job_id=${encodeURIComponent(jobId)}`);
  const job = data.job;
  renderJobTask("hotDate", job, hotDateJobTitle(date));
  if (TERMINAL_JOB_STATUSES.has(job.status)) {
    await finishHotDateJob(job, date);
  }
}

function startHotDateJobPolling(jobId, date) {
  stopHotDateJobPolling();
  pollHotDateJobStatus(jobId, date).catch((err) => {
    stopHotDateJobPolling();
    setHotDateRefreshBusy(false);
    renderTaskState("hotDate", {
      title: hotDateJobTitle(date),
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["日期", date]],
      events: [taskEvent(err.message, "error")],
    });
  });
  hotDateJobPollTimer = setInterval(() => {
    pollHotDateJobStatus(jobId, date).catch((err) => {
      stopHotDateJobPolling();
      setHotDateRefreshBusy(false);
      renderTaskState("hotDate", {
        title: hotDateJobTitle(date),
        status: "failed",
        progress: 100,
        message: err.message,
        metrics: [["日期", date]],
        events: [taskEvent(err.message, "error")],
      });
    });
  }, 1000);
}

async function refreshHotDateData() {
  if (activeList !== "hot") return;
  const select = byId("hotDateSelect");
  const date = select?.value || hotDate || "current";
  const isCurrent = date === "current";
  if (!isCurrent) {
    renderTaskState("hotDate", {
      title: `${date} 归档榜单只读`,
      status: "failed",
      progress: 100,
      message: "已归档榜单保持只读；如需新数据，请选择视频后使用“更新当前视频数据”。",
      metrics: [["日期", date]],
      events: [taskEvent("历史归档文件未修改", "warn")],
    });
    return;
  }
  if (!canRefreshHotDateData(date)) {
    renderTaskState("hotDate", {
      title: `${isCurrent ? "当前热门榜单" : `${date} 归档榜单`}更新受限`,
      status: "failed",
      progress: 100,
      message: isCurrent ? "需要管理员或 owner 权限" : "已归档榜单保持只读；请使用当前视频数据更新",
      metrics: [["日期", isCurrent ? "当前榜单" : date]],
      events: [taskEvent(isCurrent ? "当前榜单更新权限不足" : "历史归档数据不允许写回", "error")],
    });
    return;
  }
  setHotDateRefreshBusy(true);
  renderTaskState("hotDate", {
    title: hotDateJobTitle(date),
    status: "running",
    progress: 4,
    message: isCurrent
      ? "正在提交当前热门榜单更新任务"
      : "正在提交历史归档视频数据刷新任务",
    metrics: [["日期", isCurrent ? "当前榜单" : date], ["模式", isCurrent ? "重建当天热门榜单" : "保留历史排序，仅更新视频数据"]],
    events: [taskEvent(isCurrent ? "准备更新当前热门榜单" : `准备刷新 ${date} 的归档视频数据`)],
  });
  try {
    const limit = parseInt(byId("popularLimitSelect")?.value || "50", 10) || 50;
    const data = await requestJson(API_ENDPOINTS.refreshPopularJob, {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
    renderJobTask("hotDate", data.job, hotDateJobTitle(date));
    startHotDateJobPolling(data.job.job_id, date);
  } catch (err) {
    setHotDateRefreshBusy(false);
    renderTaskState("hotDate", {
      title: `${isCurrent ? "当前热门榜单" : `${date} 归档榜单`}更新失败`,
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["日期", isCurrent ? "当前榜单" : date]],
      events: [taskEvent(err.message, "error")],
    });
  }
}

function markActiveRankItem() {
  const current = getCurrentBvid();
  document.querySelectorAll(".rank-video-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.bvid === current);
  });
}

function renderSelectionViews() {
  renderVideoInfo();
  renderTimeChart();
  renderSendTimeChart();
  renderLengthChart();
  renderWordChart();
  renderUserRanking();
  if (typeof renderPlaybackPanel === "function") renderPlaybackPanel();
  filterDanmakus();
  renderSearchHistory();
  renderCompareSection();
  applyIdentity(currentRole);
}

function renderVideoInfo() {
  const bar = byId("videoInfoBar");
  const coverLink = byId("videoCoverLink");
  const link = byId("videoTitleLink");
  const owner = byId("videoOwner");
  const ps = byId("partSelect");

  const video = currentVideo();
  if (!video) {
    bar.style.display = "grid";
    setVideoCover(null);
    link.textContent = "没有选择视频";
    link.removeAttribute("href");
    coverLink.removeAttribute("href");
    owner.textContent = "请选择榜单或历史中的视频";
    ps.style.display = "none";
    renderCurrentVideoStats(null);
    renderFetchDiagnostics(null);
    renderVideoDescription(null);
    byId("addToCompareBtn").disabled = true;
    byId("addToCustomBtn").disabled = true;
    return;
  }

  bar.style.display = "grid";
  byId("addToCompareBtn").disabled = false;
  byId("addToCustomBtn").disabled = false;
  setVideoCover(video);
  link.textContent = video.title || video.bvid;
  link.href = getVideoPageUrl(video);
  coverLink.href = link.href;
  owner.textContent = video.owner ? `UP主：${video.owner}` : "";

  const cache = pageCache[video.bvid];
  if (cache && cache.pages.length > 1) {
    ps.innerHTML = cache.pages.map((p) => `<option value="${p.cid}">${escapeHtml(p.part)}</option>`).join("");
    ps.value = String(cache.currentCid);
    ps.style.display = "";
  } else {
    ps.style.display = "none";
  }
  const shouldHydrate = needsVideoInfoHydration(video);
  renderCurrentVideoStats(video);
  renderFetchDiagnostics(video);
  renderVideoDescription(video, shouldHydrate && !getVideoDescription(video) && !videoInfoHydrationTried.has(video.bvid));
  hydrateVideoInfo(video);
}

function renderCurrentVideoStats(video) {
  const box = byId("currentVideoStats");
  if (!box) return;
  const rows = [
    ["播放", formatNumber(metricValue(video, "view"))],
    ["点赞", formatNumber(metricValue(video, "like"))],
    ["收藏", formatNumber(metricValue(video, "favorite"))],
    ["弹幕", formatNumber(metricValue(video, "danmaku"))],
    ["硬币", formatNumber(metricValue(video, "coin"))],
    ["总长度", formatTime(metricValue(video, "duration"))],
  ];
  box.innerHTML = rows.map(([label, value]) => `
    <div class="metric-item"><span>${label}</span><strong>${value}</strong></div>
  `).join("");
}

function getCurrentFetchMeta(video) {
  if (!video?.bvid) return null;
  const cache = pageCache[video.bvid];
  if (cache?.fetchMetaByCid && cache.currentCid) {
    return cache.fetchMetaByCid[cache.currentCid] || null;
  }
  return video.danmaku_fetch || null;
}

function fetchSourceLabel(source) {
  if (source === "segment") return "分段接口";
  if (source === "history") return "分段+历史快照";
  if (source === "xml") return "XML 回退";
  return source || "-";
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${Math.round(number * 1000) / 10}%`;
}

function renderFetchDiagnostics(video) {
  const box = byId("danmakuFetchDiagnostics");
  if (!box) return;
  if (!canViewDebugPanels()) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const meta = getCurrentFetchMeta(video);
  if (!meta) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const rows = [
    ["B站统计", formatNumber(meta.reported_count || 0)],
    ["实际获取", formatNumber(meta.fetched_count || 0)],
    ["覆盖比例", formatPercent(meta.coverage_ratio)],
    ["采集来源", fetchSourceLabel(meta.source)],
  ];
  if (meta.segment_count) rows.push(["分段数", formatNumber(meta.segment_count)]);
  if (meta.history_enabled) {
    rows.push(["历史日期", formatNumber(meta.history_date_count || 0)]);
    rows.push(["历史新增", formatNumber(meta.history_rows_count || 0)]);
  }
  box.hidden = false;
  box.classList.toggle("has-warning", Boolean(meta.warning));
  box.innerHTML = `
    <div class="fetch-diagnostics-title">弹幕采集诊断</div>
    <div class="fetch-diagnostics-grid">
      ${rows.map(([label, value]) => `
        <div class="fetch-diagnostic-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
      `).join("")}
    </div>
    ${meta.warning ? `<p class="fetch-diagnostics-warning">${escapeHtml(meta.warning)}</p>` : ""}
  `;
}

function renderVideoDescription(video, loading = false) {
  const box = byId("videoDescription");
  if (!box) return;
  const desc = getVideoDescription(video);
  const text = desc || (loading ? "正在获取视频简介..." : (video ? "暂无简介" : "选择视频后显示简介"));
  box.classList.toggle("is-empty", !desc);
  box.innerHTML = `
    <span>视频简介</span>
    <p>${escapeHtml(text)}</p>
  `;
}

function renderFilterBar() {
  const filter = dashboardData.filter;
  const bar = byId("filterBar");
  const hasAccountWords = activeBlockWords.length > 0;
  if ((!filter || !filter.enabled) && !hasAccountWords) {
    bar.style.display = "none";
    return;
  }
  bar.style.display = "flex";
  const parts = [`模式：${filter?.mode === "mask" ? "打码替换" : "整条删除"}`];
  if (filter?.enabled) {
    parts.push(`全局屏蔽词：${(filter.block_words || []).join("、") || "无"}`);
    if (filter.removed_count) parts.push(`删除 ${filter.removed_count} 条`);
    if (filter.masked_count) parts.push(`打码 ${filter.masked_count} 条`);
  }
  if (hasAccountWords) {
    parts.push(`当前账号生效屏蔽词：${activeBlockWords.join("、")}`);
  }
  byId("filterSummary").textContent = parts.join(" ｜ ");
}

function renderRankChart() {
  const box = byId("rankChart");
  const videos = getVideoRank(activeVideos());
  const maxValue = Math.max(...videos.map((v) => metricValue(v, sortMode === "official" ? "danmaku" : sortMode)), 1);
  const currentBvid = getCurrentBvid();
  box.innerHTML = videos.map((video, index) => {
    const value = metricValue(video, sortMode === "official" ? "danmaku" : sortMode);
    const percent = Math.max(4, Math.round((value / maxValue) * 100));
    const displayRank = sortMode === "official" && video.rank
      ? `#${String(video.rank).padStart(2, "0")}`
      : `#${String(index + 1).padStart(2, "0")}`;
    const active = currentBvid === video.bvid ? " active" : "";
    return `
      <button class="rank-video-item${active}" type="button" data-bvid="${escapeHtml(video.bvid)}">
        <span class="rank-number">${displayRank}</span>
        <span class="rank-body">
          <span class="rank-video-title">${escapeHtml(video.title || video.bvid)}</span>
          <span class="rank-video-meta">弹幕 ${formatNumber(metricValue(video, "danmaku"))} ｜ 播放 ${formatNumber(metricValue(video, "view"))}</span>
          <span class="rank-value-bar"><span style="width:${percent}%"></span></span>
        </span>
        <strong class="rank-value">${formatNumber(value)}</strong>
      </button>
    `;
  }).join("");
  requestAnimationFrame(() => {
    box.scrollTo({ top: rankScrollTop, behavior: "auto" });
  });
}

function colorToHex(v) {
  return `#${Number(v || 0).toString(16).padStart(6, "0").slice(-6)}`;
}

function setSearchPage(page) {
  const totalPages = Math.max(1, Math.ceil(currentQueryRows.length / searchResultPageSize));
  searchResultPage = Math.max(1, Math.min(page, totalPages));
  renderSearchResults();
}

function sortRows(rows, by) {
  if (by === "send_time_asc") {
    return [...rows].sort((a, b) =>
      Number(a.send_timestamp || 0) - Number(b.send_timestamp || 0)
      || Number(a.time_in_video || 0) - Number(b.time_in_video || 0)
    );
  }
  if (by === "send_time_desc") {
    return [...rows].sort((a, b) =>
      Number(b.send_timestamp || 0) - Number(a.send_timestamp || 0)
      || Number(a.time_in_video || 0) - Number(b.time_in_video || 0)
    );
  }
  return [...rows].sort((a, b) => Number(a.time_in_video || 0) - Number(b.time_in_video || 0));
}

function renderSearchPager(total, start, end, totalPages) {
  const pager = byId("searchPager");
  const info = byId("searchPageInfo");
  const prev = byId("prevSearchPage");
  const next = byId("nextSearchPage");
  if (!pager || !info || !prev || !next) return;
  if (total === 0) {
    pager.hidden = true;
    return;
  }
  pager.hidden = totalPages <= 1;
  info.textContent = `第 ${searchResultPage} / ${totalPages} 页 ｜ ${formatNumber(start + 1)}-${formatNumber(end)} 条`;
  prev.disabled = searchResultPage <= 1;
  next.disabled = searchResultPage >= totalPages;
}

function renderSearchResults() {
  const showTime = byId("showSendTime").checked;
  const showColor = byId("showColor").checked;
  document.querySelectorAll(".send-time-column").forEach((e) => { e.style.display = showTime ? "" : "none"; });
  document.querySelectorAll(".color-column").forEach((e) => { e.style.display = showColor ? "" : "none"; });
  const tbody = document.querySelector("#searchResultTable tbody");
  const summary = byId("searchSummary");
  if (currentQueryRows.length === 0) {
    summary.textContent = "共找到 0 条弹幕";
    renderSearchPager(0, 0, 0, 1);
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">无匹配结果</td></tr>';
    return;
  }
  const total = currentQueryRows.length;
  const totalPages = Math.max(1, Math.ceil(total / searchResultPageSize));
  searchResultPage = Math.max(1, Math.min(searchResultPage, totalPages));
  const start = (searchResultPage - 1) * searchResultPageSize;
  const end = Math.min(start + searchResultPageSize, total);
  const pageRows = currentQueryRows.slice(start, end);
  summary.textContent = `共找到 ${formatNumber(total)} 条弹幕，当前显示 ${formatNumber(pageRows.length)} 条`;
  renderSearchPager(total, start, end, totalPages);
  tbody.innerHTML = pageRows.map((r) => {
    const hex = colorToHex(r.color);
    return `<tr>
      <td>${escapeHtml(r.title)}</td>
      <td>${formatTime(r.time_in_video || 0)}</td>
      <td>${escapeHtml(r.user_hash)}</td>
      <td class="send-time-column" style="display:${showTime ? "" : "none"}">${escapeHtml(r.send_time_text)}</td>
      <td class="color-column" style="display:${showColor ? "" : "none"}"><span class="color-swatch" style="background-color:${hex}"></span>${hex}</td>
      <td>${escapeHtml(r.content)}</td>
    </tr>`;
  }).join("");
}

function canFetchBvid() {
  if (isAdmin()) return { allowed: true, waitSeconds: 0 };
  const now = Date.now();
  const interval = getBvidFetchIntervalMs();
  if (!lastBvidFetchAt || now - lastBvidFetchAt >= interval) {
    lastBvidFetchAt = now;
    return { allowed: true, waitSeconds: 0 };
  }
  return { allowed: false, waitSeconds: Math.ceil((interval - (now - lastBvidFetchAt)) / 1000) };
}

function getBvidFetchIntervalMs() {
  const seconds = Number(accountSession?.user?.search_interval_seconds);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return seconds * 1000;
  }
  return BVID_FETCH_INTERVAL_MS;
}

function canSearchLocal() {
  if (isAdmin()) return { allowed: true, waitSeconds: 0 };
  const now = Date.now();
  if (!lastLocalSearchAt || now - lastLocalSearchAt >= LOCAL_SEARCH_INTERVAL_MS) {
    lastLocalSearchAt = now;
    return { allowed: true, waitSeconds: 0 };
  }
  return { allowed: false, waitSeconds: Math.ceil((LOCAL_SEARCH_INTERVAL_MS - (now - lastLocalSearchAt)) / 1000) };
}

function danmakuFetchMessage(result, successText) {
  const meta = result?.danmaku_fetch;
  if (!meta?.warning) return successText;
  if (!canViewDebugPanels()) return successText;
  return `${successText}。已生成采集诊断，可能不是历史累计全量。`;
}

function applyBvidSearchResult(result) {
  if (!result?.ok) throw new Error(result?.error || "获取失败");
  const danmakuRows = result.danmakus || [];
  if (danmakuRows.length > MAX_LOCAL_DANMAKU_ROWS) {
    throw new Error(`该视频弹幕 ${formatNumber(danmakuRows.length)} 条，超过本地上限 ${formatNumber(MAX_LOCAL_DANMAKU_ROWS)} 条。`);
  }
  const v = result.video;
  const pages = result.pages || [];
  v.danmaku_fetch = result.danmaku_fetch || null;
  v.stats = result.stats || null;
  pageCache[v.bvid] = {
    pages,
    currentCid: result.current_cid,
    danmakusByCid: { [result.current_cid]: danmakuRows },
    fetchMetaByCid: { [result.current_cid]: result.danmaku_fetch || null },
    statsByCid: { [result.current_cid]: result.stats || null },
  };
  searchedVideos = searchedVideos.filter((x) => x.bvid !== v.bvid);
  searchedVideos.unshift(v);
  searchedDanmakus = searchedDanmakus.filter((r) => String(r.title || "") !== v.title);
  danmakuRows.forEach((row) => searchedDanmakus.push(row));
  invalidateDanmakuPoolIndex();
  addSearchHistory(v.bvid, v.title);
  pruneSearchedData();
  focusBvid = null;
  selectedBvid = v.bvid;
  renderAll();
  renderVideoInfo();
  filterDanmakus();
  return danmakuFetchMessage(
    result,
    `成功，${formatNumber(v.danmaku)} 条弹幕${pages.length > 1 ? `（${pages.length}P）` : ""}`
  );
}

function stopBvidJobPolling() {
  if (bvidJobPollTimer) {
    clearInterval(bvidJobPollTimer);
    bvidJobPollTimer = null;
  }
}

function setBvidFetchBusy(isBusy) {
  const fetchButton = byId("fetchBvidBtn");
  const refreshButton = byId("refreshCurrentVideoBtn");
  if (fetchButton) fetchButton.disabled = Boolean(isBusy);
  if (refreshButton) refreshButton.disabled = Boolean(isBusy);
}

async function finishBvidJob(job) {
  stopBvidJobPolling();
  const status = byId("fetchStatus");
  setBvidFetchBusy(false);
  if (job.status === "success") {
    const result = await requestJson(`${API_ENDPOINTS.jobResult}?job_id=${encodeURIComponent(job.job_id)}`);
    const message = applyBvidSearchResult(result);
    if (status) status.textContent = message;
    renderJobTask("bvid", { ...job, message, progress: 100 }, "BV 获取完成");
    return;
  }
  const message = job.error || job.message || "BV 获取失败";
  if (status) status.textContent = message;
  renderJobTask("bvid", job, "BV 获取失败");
}

async function pollBvidJobStatus(jobId) {
  const data = await requestJson(`${API_ENDPOINTS.jobStatus}?job_id=${encodeURIComponent(jobId)}`);
  const job = data.job;
  renderJobTask("bvid", job, "BV 获取进度");
  if (TERMINAL_JOB_STATUSES.has(job.status)) {
    await finishBvidJob(job);
  }
}

function startBvidJobPolling(jobId) {
  stopBvidJobPolling();
  pollBvidJobStatus(jobId).catch((err) => {
    stopBvidJobPolling();
    byId("fetchStatus").textContent = `任务状态读取失败：${err.message}`;
    setBvidFetchBusy(false);
    renderTaskState("bvid", {
      title: "BV 获取失败",
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [],
      events: [taskEvent(err.message, "error")],
    });
  });
  bvidJobPollTimer = setInterval(() => {
    pollBvidJobStatus(jobId).catch((err) => {
      stopBvidJobPolling();
      byId("fetchStatus").textContent = `任务状态读取失败：${err.message}`;
      setBvidFetchBusy(false);
      renderTaskState("bvid", {
        title: "BV 获取失败",
        status: "failed",
        progress: 100,
        message: err.message,
        metrics: [],
        events: [taskEvent(err.message, "error")],
      });
    });
  }, 900);
}

async function submitBvidFetch(input, { includeHistory = false, cid = "", sourceLabel = "BV 获取", initialMessage = "" } = {}) {
  const perm = canFetchBvid();
  if (!perm.allowed) {
    byId("fetchStatus").textContent = `过于频繁，请等待 ${perm.waitSeconds} 秒。`;
    return;
  }
  if (!input) {
    byId("fetchStatus").textContent = "请输入 BV 号。";
    return;
  }
  const status = byId("fetchStatus");
  status.textContent = initialMessage || "正在提交获取任务...";
  setBvidFetchBusy(true);
  renderTaskState("bvid", {
    title: `${sourceLabel}进度`,
    status: "running",
    progress: 6,
    message: includeHistory ? "任务正在提交到本地服务器，已请求历史补抓" : "任务正在提交到本地服务器",
    metrics: [["输入", input], ["模式", sourceLabel], ["分P", cid || "默认"], ["历史补抓", includeHistory ? "开启" : "关闭"]],
    events: [taskEvent(includeHistory ? `准备提交${sourceLabel}任务，并尝试历史弹幕补抓` : `准备提交${sourceLabel}任务`)],
  });
  try {
    const data = await requestJson(API_ENDPOINTS.searchJob, {
      method: "POST",
      body: JSON.stringify({ bvid: input, cid, include_history: includeHistory }),
    });
    status.textContent = canViewDebugPanels() ? "任务已开始，正在读取进度..." : "任务已开始，完成后会自动显示结果...";
    renderJobTask("bvid", data.job, "BV 获取进度");
    startBvidJobPolling(data.job.job_id);
  } catch (err) {
    status.textContent = `请求失败：${err.message}`;
    setBvidFetchBusy(false);
    renderTaskState("bvid", {
      title: "BV 获取失败",
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["输入", input], ["分P", cid || "默认"], ["历史补抓", includeHistory ? "开启" : "关闭"]],
      events: [taskEvent(err.message, "error")],
    });
  }
}

async function fetchBvid() {
  const input = byId("bvidSearchInput").value.trim();
  const includeHistory = Boolean(byId("historyDanmakuFetch")?.checked);
  await submitBvidFetch(input, { includeHistory, sourceLabel: "BV 获取" });
}

async function refreshCurrentVideoData() {
  const video = currentVideo();
  if (!video?.bvid) {
    byId("fetchStatus").textContent = "请先从热门榜单、历史记录或搜索结果中选择一个视频。";
    return;
  }
  byId("bvidSearchInput").value = video.bvid;
  const includeHistory = Boolean(byId("historyDanmakuFetch")?.checked);
  await submitBvidFetch(video.bvid, {
    includeHistory,
    sourceLabel: "当前视频数据更新",
    initialMessage: `正在更新当前视频：${video.title || video.bvid}`,
  });
}

async function switchPart(bvid, cid) {
  const cache = pageCache[bvid];
  if (!cache) return;
  if (cache.danmakusByCid[cid]) {
    cache.currentCid = cid;
    const video = findVideo(bvid);
    if (video) {
      video.danmaku = cache.danmakusByCid[cid].length;
      video.danmaku_fetch = cache.fetchMetaByCid?.[cid] || null;
      video.stats = cache.statsByCid?.[cid] || null;
    }
    replaceSearchedDanmakus(bvid, cache.danmakusByCid[cid]);
    renderVideoInfo();
    filterDanmakus();
    return;
  }
  const status = byId("fetchStatus");
  const page = (cache.pages || []).find((item) => Number(item.cid) === Number(cid));
  status.textContent = "正在提交分P弹幕获取任务...";
  await submitBvidFetch(bvid, {
    cid,
    includeHistory: false,
    sourceLabel: "分P切换",
    initialMessage: `正在获取分P：${page?.part || cid}`,
  });
}

function replaceSearchedDanmakus(bvid, newDanmakus) {
  const v = findVideo(bvid);
  if (!v) return;
  searchedDanmakus = searchedDanmakus.filter((r) => String(r.title || "") !== v.title);
  newDanmakus.forEach((row) => searchedDanmakus.push(row));
  invalidateDanmakuPoolIndex();
}

function filterDanmakus(options = {}) {
  if (options.enforceInterval) {
    const perm = canSearchLocal();
    if (!perm.allowed) {
      byId("searchSummary").textContent = `筛选过快，请等待 ${perm.waitSeconds} 秒。`;
      return;
    }
  }
  const content = byId("contentInput").value.trim().toLowerCase();
  const userHash = byId("userHashInput").value.trim();
  const sortBy = byId("sortSelect").value;
  currentQueryRows = currentVideoDanmakus().filter((r) => {
    const mc = !content || String(r.content || "").toLowerCase().includes(content);
    const mu = !userHash || String(r.user_hash || "") === userHash;
    return mc && mu;
  });
  currentQueryRows = sortRows(currentQueryRows, sortBy);
  searchResultPage = 1;
  renderSearchResults();
}

function resetSearch() {
  byId("contentInput").value = "";
  byId("userHashInput").value = "";
  byId("sortSelect").value = "time_in_video";
  filterDanmakus();
}

async function addToCompare(bvid) {
  if (!bvid || bvid === "all") return;
  const active = currentVideo();
  const video = active?.bvid === bvid ? active : findVideo(bvid);
  if (!video) return;
  try {
    await ensureVideoDanmakusLoaded(video);
  } catch (err) {
    alert(`弹幕加载失败：${err.message}`);
    return;
  }
  rememberVideo(video, getDanmakusForVideo(video));
  const alreadyCompared = compareVideos.some((v) => v.bvid === video.bvid);
  if (!alreadyCompared && compareVideos.length >= 2) {
    const oldest = compareVideos[compareVideos.length - 1];
    const ok = await confirmReplaceCompare(oldest);
    if (!ok) return;
  }
  compareVideos = compareVideos.filter((v) => v.bvid !== video.bvid);
  compareVideos.unshift(video);
  compareVideos = compareVideos.slice(0, 2);
  pruneSearchedData();
  renderCompareSection();
  scrollToSection("compareSection");
}

function removeFromCompare(bvid) {
  compareVideos = compareVideos.filter((v) => v.bvid !== bvid);
  pruneSearchedData();
  renderCompareSection();
}

function ensureCompareLayout(container) {
  if (container.querySelector("#compareTimeChart") && container.querySelector(".compare-video-grid")) return;
  disposeCompareCharts();
  const metricCards = COMPARE_METRICS.map(({ key }) => `
    <article class="compare-metric-card">
      <div class="compare-metric-text" data-compare-metric-text="${escapeHtml(key)}"></div>
      <div id="compareMetricChart_${escapeHtml(key)}" class="compare-mini-chart"></div>
    </article>
  `).join("");
  container.innerHTML = `
    <div class="compare-video-grid"></div>
    <div class="compare-metric-grid">${metricCards}</div>
    <div class="compare-chart-grid">
      <article class="compare-chart-panel compare-wide-card"><h3>弹幕时间分布</h3><div id="compareTimeChart" class="compare-chart-surface"></div></article>
      <article class="compare-chart-panel compare-wide-card"><h3>弹幕长度分布</h3><div id="compareLengthChart" class="compare-chart-surface"></div></article>
    </div>
  `;
}

function compareMetricTextHtml(label, key, a, b) {
  const av = a ? metricValue(a, key) : 0;
  const bv = b ? metricValue(b, key) : 0;
  const diff = a && b ? av - bv : null;
  const displayA = key === "duration" ? formatTime(av) : formatNumber(av);
  const displayB = key === "duration" ? formatTime(bv) : formatNumber(bv);
  const absDiff = key === "duration" ? formatTime(Math.abs(diff || 0)) : formatNumber(Math.abs(diff || 0));
  const diffClass = diff > 0 ? "diff-up" : diff < 0 ? "diff-down" : "";
  const winner = diff === null ? "等待对比" : diff === 0 ? "持平" : diff > 0 ? "A 更高" : "B 更高";
  const diffText = diff === null ? "加入第二个视频后显示差值" : diff === 0 ? "两侧一致" : `差值 ${absDiff}`;
  return `
    <div class="compare-metric-head">
      <h3>${escapeHtml(label)}</h3>
      <span class="compare-metric-state ${diffClass}">${winner}</span>
    </div>
    <div class="compare-value-row">
      <span><b>A</b>${a ? displayA : "-"}</span>
      <span><b>B</b>${b ? displayB : "-"}</span>
    </div>
    <p class="${diffClass}">${diffText}</p>
  `;
}

function renderCompareSection() {
  const container = byId("compareContent");
  const [a, b] = compareVideos;
  if (!a && !b) {
    disposeCompareCharts();
    container.innerHTML = '<div class="compare-full-row">请先从当前视频中添加对比视频</div>';
    return;
  }
  const slot = (video, label) => {
    if (!video) {
      return `<article class="compare-video-card is-empty"><img class="compare-cover" src="${VIDEO_PLACEHOLDER_URL}" alt="${label} 视频占位封面"><h3><span class="compare-badge">${label}</span>等待添加</h3><p>请选择一个视频加入对比</p><button class="btn btn-ghost compare-remove-btn" disabled>移出对比</button></article>`;
    }
    const href = getVideoPageUrl(video);
    const coverUrl = getVideoCoverUrl(video) || VIDEO_PLACEHOLDER_URL;
    const cover = `<img class="compare-cover" src="${escapeHtml(coverUrl)}" alt="${label} 视频封面" referrerpolicy="no-referrer">`;
    return `
      <article class="compare-video-card">
        <a href="${escapeHtml(href)}" target="_blank" rel="noopener">${cover}</a>
        <h3><span class="compare-badge">${label}</span>${escapeHtml(videoLabel(video, `${label} 视频`))}</h3>
        <p>${escapeHtml(video.owner ? `UP主：${video.owner}` : video.bvid)}</p>
        <button class="btn btn-ghost compare-remove-btn" data-compare-remove data-bvid="${escapeHtml(video.bvid)}">移出对比</button>
      </article>
    `;
  };
  ensureCompareLayout(container);
  container.querySelector(".compare-video-grid").innerHTML = `${slot(a, "A")}${slot(b, "B")}`;
  COMPARE_METRICS.forEach(({ label, key }) => {
    const text = container.querySelector(`[data-compare-metric-text="${key}"]`);
    if (text) text.innerHTML = compareMetricTextHtml(label, key, a, b);
  });
  requestAnimationFrame(() => renderCompareCharts(a, b));
}

function renderAll() {
  syncSortOptions();
  renderFilterBar();
  renderRankChart();
  renderTimeChart();
  renderSendTimeChart();
  renderLengthChart();
  renderWordChart();
  renderUserRanking();
  if (typeof renderPlaybackPanel === "function") renderPlaybackPanel();
  renderCrossVideoPanel();
  renderCustomManage();
  updateCustomCount();
  applyIdentity(currentRole);
}

async function bootstrap() {
  try {
    searchedVideos = [];
    searchedDanmakus = [];
    pageCache = {};
    invalidateDanmakuPoolIndex();
    await Promise.all([loadAllData(), loadIdentity(), loadAccountSession()]);
    await loadPopularDates();
    selectedBvid = "all";
    focusBvid = null;
    activeList = "hot";
    byId("hotTab").classList.add("active");
    byId("customTab").classList.remove("active");
    renderAll();
    renderVideoInfo();
    filterDanmakus();
    renderSearchHistory();
    renderCompareSection();
  } catch (error) {
    document.querySelector("main").innerHTML =
      `<section class="panel" style="text-align:center;padding:48px;"><h2>数据加载失败</h2><p style="color:var(--muted);">${escapeHtml(error.message)}</p></section>`;
  }
}

initCharts();
setupEvents();
bootstrap();
