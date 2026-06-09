const BVID_FETCH_INTERVAL_MS = 10000;
const LOCAL_SEARCH_INTERVAL_MS = 2000;
const IDENTITY_STORAGE_KEY = "danmaku_identity_role";
const SEARCH_CACHE_LIMIT = 15;
const MAX_LOCAL_DANMAKU_ROWS = 2000000;
const LARGE_IMPORT_FILE_BYTES = 50 * 1024 * 1024;
const LARGE_IMPORT_DANMAKU_ROWS = 200000;
const HUGE_IMPORT_DANMAKU_ROWS = 1000000;
const MAX_IMPORT_VIDEO_ROWS = 500;
const MAX_IMPORT_TEXT_CHARS = 2000;
const MAX_IMPORT_DESC_CHARS = 5000;
const MAX_IMPORT_DANMAKU_CHARS = 500;
const AI_PHRASE_SCAN_LIMIT = 50000;
const AI_FULL_RAW_MAX_ROWS = 20000;
const AI_FULL_RAW_MAX_BYTES = 3.4 * 1024 * 1024;
const AI_USER_REQUIREMENT_MAX_CHARS = 300;
const SEARCH_RESULT_PAGE_SIZE = 300;
const VIDEO_PLACEHOLDER_URL = "./images/video_placeholder_16x9.png";
const API_ENDPOINTS = {
  search: "/api/search",
  videoInfo: "/api/video-info",
  identity: "/api/identity",
  compare: "/api/compare",
  aiAnalyze: "/api/ai/analyze",
  backgroundImage: "/api/background-image",
  accountSession: "/api/account/session",
  blockWords: "/api/account/block-words",
  popularDates: "/api/popular-dates",
  popularDate: "/api/popular-date",
  videoDanmakus: "/api/video-danmakus",
  refreshPopularJob: "/api/jobs/refresh-popular",
  searchJob: "/api/jobs/search",
  jobStatus: "/api/jobs/status",
  jobResult: "/api/jobs/result",
};
const TERMINAL_JOB_STATUSES = new Set(["success", "failed", "cancelled"]);
const TASK_UI = {
  bvid: {
    panel: "bvidTaskPanel",
    title: "bvidTaskTitle",
    progressText: "bvidTaskProgressText",
    progressBar: "bvidTaskProgressBar",
    message: "bvidTaskMessage",
    metrics: "bvidTaskMetrics",
    events: "bvidTaskEvents",
  },
  hotDate: {
    panel: "hotDateTaskPanel",
    title: "hotDateTaskTitle",
    progressText: "hotDateTaskProgressText",
    progressBar: "hotDateTaskProgressBar",
    message: "hotDateTaskMessage",
    metrics: "hotDateTaskMetrics",
    events: "hotDateTaskEvents",
  },
  currentAi: {
    panel: "currentAiTaskPanel",
    title: "currentAiTaskTitle",
    progressText: "currentAiTaskProgressText",
    progressBar: "currentAiTaskProgressBar",
    message: "currentAiTaskMessage",
    metrics: "currentAiTaskMetrics",
    events: "currentAiTaskEvents",
  },
  compareAi: {
    panel: "compareAiTaskPanel",
    title: "compareAiTaskTitle",
    progressText: "compareAiTaskProgressText",
    progressBar: "compareAiTaskProgressBar",
    message: "compareAiTaskMessage",
    metrics: "compareAiTaskMetrics",
    events: "compareAiTaskEvents",
  },
};
const COMPARE_METRICS = [
  { label: "播放", key: "view" },
  { label: "点赞", key: "like" },
  { label: "收藏", key: "favorite" },
  { label: "弹幕", key: "danmaku" },
  { label: "硬币", key: "coin" },
  { label: "长度", key: "duration" },
];

const byId = (id) => document.getElementById(id);
const formatNumber = (v) => Number(v || 0).toLocaleString("zh-CN");
const formatBytes = (bytes) => {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
};

function on(id, event, handler) {
  const el = byId(id);
  if (el) el.addEventListener(event, handler);
}

function csrfHeaders(headers = {}) {
  return csrfToken ? { ...headers, "X-CSRF-Token": csrfToken } : headers;
}

function formatTime(seconds) {
  const total = Math.floor(Number(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function metricValue(video, key) {
  if (!video) return 0;
  const aliases = {
    view: ["view", "views"],
    like: ["like", "likes"],
    favorite: ["favorite", "favorites", "fav"],
    danmaku: ["danmaku", "danmaku_count"],
    coin: ["coin", "coins"],
    duration: ["duration", "length"],
  };
  for (const name of aliases[key] || [key]) {
    if (video[name] !== undefined && video[name] !== null) return Number(video[name] || 0);
  }
  return 0;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function requestJson(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = csrfHeaders({ ...(options.headers || {}) });
  if (method !== "GET" && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(url, {
    cache: "no-store",
    ...options,
    headers,
  });
  const result = await resp.json();
  if (!result.ok) throw new Error(result.error || "请求失败");
  return result;
}

function jobStatusLabel(status) {
  return {
    pending: "等待中",
    running: "进行中",
    success: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status] || "任务状态";
}

function shortTaskTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function taskEvent(message, level = "info") {
  return { message, level, created_at: new Date().toISOString() };
}

function nextPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
}

function renderTaskState(key, state = {}) {
  const ui = TASK_UI[key];
  if (!ui) return;
  const panel = byId(ui.panel);
  if (!panel) return;
  if ((key === "bvid" || key === "hotDate") && !canViewDebugPanels()) {
    panel.hidden = true;
    return;
  }
  if (state.hidden) {
    panel.hidden = true;
    return;
  }
  const status = state.status || "running";
  const progress = Math.max(0, Math.min(100, Number(state.progress || 0)));
  panel.hidden = false;
  panel.className = `task-panel task-${status}${state.compact ? " task-compact" : ""}`;
  byId(ui.title).textContent = state.title || "任务进度";
  byId(ui.progressText).textContent = `${Math.round(progress)}%`;
  byId(ui.progressBar).style.width = `${progress}%`;
  byId(ui.message).textContent = state.message || "任务状态更新中";

  const metrics = state.metrics || [];
  const metricBox = byId(ui.metrics);
  metricBox.innerHTML = metrics.length
    ? metrics.map(([label, value]) => `
      <div class="task-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
    `).join("")
    : "";

  const events = (state.events || []).slice(-7).reverse();
  const eventBox = byId(ui.events);
  eventBox.innerHTML = events.length
    ? events.map((item) => `
      <div class="task-event task-event-${escapeHtml(item.level || "info")}">
        <span>${escapeHtml(shortTaskTime(item.created_at))}</span>
        <p>${escapeHtml(item.message || "")}</p>
      </div>
    `).join("")
    : "";
}

function renderJobTask(key, job, title) {
  if (!job) {
    renderTaskState(key, { hidden: true });
    return;
  }
  const result = job.result || {};
  const lastEvent = (job.events || [])[job.events.length - 1] || {};
  const detail = lastEvent.detail || {};
  let metrics = [
    ["任务ID", String(job.job_id || "").slice(0, 8) || "-"],
    ["状态", jobStatusLabel(job.status)],
    ["弹幕", result.danmaku_count !== undefined ? formatNumber(result.danmaku_count) : (detail.rows_count !== undefined ? formatNumber(detail.rows_count) : "-")],
    ["分P", result.page_count !== undefined ? formatNumber(result.page_count) : (detail.page_count !== undefined ? formatNumber(detail.page_count) : "-")],
    ["B站统计", result.reported_count !== undefined ? formatNumber(result.reported_count) : "-"],
  ];
  if (key === "hotDate" && (result.archive_date !== undefined || detail.date !== undefined)) {
    metrics = [
      ["任务ID", String(job.job_id || "").slice(0, 8) || "-"],
      ["日期", result.archive_date || detail.date || "-"],
      ["视频", result.updated_video_count !== undefined ? formatNumber(result.updated_video_count) : (detail.video_count !== undefined ? formatNumber(detail.video_count) : (detail.total !== undefined ? formatNumber(detail.total) : "-"))],
      ["弹幕", result.updated_danmaku_count !== undefined ? formatNumber(result.updated_danmaku_count) : (detail.danmaku_count !== undefined ? formatNumber(detail.danmaku_count) : "-")],
      ["失败", result.failed_video_count !== undefined ? formatNumber(result.failed_video_count) : (detail.failed_video_count !== undefined ? formatNumber(detail.failed_video_count) : "0")],
    ];
  } else if (result.video_count !== undefined || result.exported_video_count !== undefined) {
    metrics = [
      ["任务ID", String(job.job_id || "").slice(0, 8) || "-"],
      ["状态", jobStatusLabel(job.status)],
      ["视频", result.video_count !== undefined ? formatNumber(result.video_count) : "-"],
      ["弹幕", result.danmaku_count !== undefined ? formatNumber(result.danmaku_count) : "-"],
      ["失败", result.failed_video_count !== undefined ? formatNumber(result.failed_video_count) : "0"],
    ];
  }
  if (result.history_enabled || detail.history_rows_count !== undefined) {
    metrics.push(["历史新增", formatNumber(result.history_rows_count ?? detail.history_rows_count ?? 0)]);
  }
  renderTaskState(key, {
    title,
    status: job.status || "running",
    progress: job.progress || 0,
    message: job.message || "任务状态更新中",
    metrics,
    events: job.events || [],
  });
}
