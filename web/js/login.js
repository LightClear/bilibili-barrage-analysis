let sessionState = null;
let aiCaptchaToken = "";
let loginCaptchaToken = "";
let serverClockBaseMs = null;
let serverClockClientMs = null;
let serverClockTimer = null;
let blockWordsLoadedForAccount = "";
let providerLoadedForAccount = "";
let biliCookieLoadedForAccount = "";
let aiProviderTemplates = [];
let aiProviderConfigured = false;
let csrfToken = "";
let refreshJobPollTimer = null;
let activeRefreshJobId = "";

const API = {
  session: "/api/account/session",
  login: "/api/account/login",
  logout: "/api/account/logout",
  register: "/api/account/register",
  emailCode: "/api/account/email-code",
  aiCaptcha: "/api/account/ai-captcha",
  profile: "/api/account/profile",
  apiToggle: "/api/account/api-toggle",
  apiReset: "/api/account/api-reset",
  blockWords: "/api/account/block-words",
  aiProvider: "/api/account/ai-provider",
  aiProviderTest: "/api/account/ai-provider/test",
  biliCookie: "/api/account/bili-cookie",
  accountAiUsage: "/api/account/ai-usage",
  identity: "/api/identity",
  adminStatus: "/api/admin/status",
  adminUsers: "/api/admin/users",
  adminUserUpdate: "/api/admin/users/update",
  adminBlockWords: "/api/admin/block-words",
  adminAiCache: "/api/admin/ai-cache",
  adminAiCacheClear: "/api/admin/ai-cache/clear",
  adminStorageUsage: "/api/admin/storage-usage",
  adminStorageCleanup: "/api/admin/storage-cleanup",
  adminAiUsage: "/api/admin/ai-usage",
  refreshPopularJob: "/api/jobs/refresh-popular",
  jobStatus: "/api/jobs/status",
  recentJobs: "/api/jobs/recent",
};

const TERMINAL_JOB_STATUSES = new Set(["success", "failed", "cancelled"]);
const ROLE_LABELS = {
  normal: "普通用户",
  admin: "管理员",
  owner: "项目负责人",
};

const byId = (id) => document.getElementById(id);

function isAdminRole(role) {
  return role === "admin" || role === "owner";
}

function isOwnerRole(role) {
  return role === "owner";
}

function roleLabel(role) {
  return ROLE_LABELS[role] || ROLE_LABELS.normal;
}

function roleSelectOptions(currentRole, canManagePrivileged) {
  const roles = ["normal"];
  if (canManagePrivileged || currentRole === "admin") {
    roles.push("admin");
  }
  if (currentRole === "owner") {
    roles.push("owner");
  }
  return roles.map((role) => `
    <option value="${role}"${currentRole === role ? " selected" : ""}>${ROLE_LABELS[role]}</option>
  `).join("");
}

function setStatus(id, text, isError = false) {
  const el = byId(id);
  if (!el) return;
  el.textContent = text || "";
  el.style.color = isError ? "#fb7185" : "#68f5ff";
}

async function requestJSON(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (method !== "GET" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const resp = await fetch(url, {
    cache: "no-store",
    ...options,
    headers,
  });
  const data = await resp.json();
  if (typeof data.csrf_token === "string") {
    csrfToken = data.csrf_token;
  }
  if (data.ok && data.logged_in === false) {
    csrfToken = "";
  }
  if (!data.ok) {
    const error = new Error(data.error || "请求失败");
    error.data = data;
    throw error;
  }
  return data;
}

function formPayload(ids) {
  const payload = {};
  Object.entries(ids).forEach(([key, id]) => {
    payload[key] = byId(id).value.trim();
  });
  return payload;
}

function showAuthMode(mode) {
  const isLogin = mode === "login";
  byId("loginForm").hidden = !isLogin;
  byId("registerForm").hidden = isLogin;
  byId("loginTab").classList.toggle("active", isLogin);
  byId("registerTab").classList.toggle("active", !isLogin);
  if (!isLogin) refreshAiCaptcha();
}

function setLoginCaptchaVisible(visible) {
  const panel = byId("loginCaptchaPanel");
  if (!panel) return;
  panel.hidden = !visible;
  if (!visible) {
    loginCaptchaToken = "";
    byId("loginAiAnswer").value = "";
  }
}

async function loadSession() {
  try {
    sessionState = await requestJSON(API.session);
    renderSession();
  } catch (err) {
    setStatus("authStatus", err.message, true);
  }
}

function renderSession() {
  const loggedIn = Boolean(sessionState?.logged_in);
  document.body.classList.toggle("account-mode", loggedIn);
  byId("authPanel").hidden = loggedIn;
  byId("accountPanel").hidden = !loggedIn;
  if (!loggedIn) {
    csrfToken = "";
    blockWordsLoadedForAccount = "";
    providerLoadedForAccount = "";
    biliCookieLoadedForAccount = "";
    stopServerClock();
    stopRefreshJobPolling(true);
    showAuthMode("login");
    return;
  }

  const user = sessionState.user;
  renderProfile(user);
  renderApi(user);
  if (blockWordsLoadedForAccount !== user.account) {
    blockWordsLoadedForAccount = user.account;
    loadBlockWords();
  }
  if (providerLoadedForAccount !== user.account) {
    providerLoadedForAccount = user.account;
    loadAiProvider();
  }
  if (biliCookieLoadedForAccount !== user.account) {
    biliCookieLoadedForAccount = user.account;
    loadBiliCookie();
  }
  loadAccountAiUsage();
  byId("adminPanel").hidden = !isAdminRole(user.role);
  updateOwnerOnlySections(user);
  if (isAdminRole(user.role)) {
    loadAdminData();
  } else {
    stopServerClock();
    stopRefreshJobPolling(true);
  }
}

function renderProfile(user) {
  const rows = [
    ["用户名", user.username],
    ["账号", user.account_masked],
    ["权限", roleLabel(user.role)],
    ["性别", user.gender || "未设置"],
    ["生日", user.birthday || "未设置"],
    ["邮箱", user.email_masked],
    ["注册时间", user.created_at || "-"],
    ["最近登入", user.last_login_at || "-"],
    ["API 开关", user.api_enabled ? "已开启" : "未开启"],
    ["BV搜索间隔", `${user.search_interval_seconds ?? 10} 秒`],
  ];
  byId("profileSummary").innerHTML = rows.map(([label, value]) => `
    <div class="profile-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
  byId("profileUsername").value = user.username || "";
  byId("profileGender").value = user.gender || "未设置";
  byId("profileBirthday").value = user.birthday || "";
}

function renderApi(user) {
  byId("apiEnabled").checked = Boolean(user.api_enabled);
  byId("apiKeyInput").value = user.api_key || "";
}

async function loadBlockWords() {
  try {
    const data = await requestJSON(API.blockWords);
    byId("blockWordsInput").value = (data.words || []).join("\n");
    renderBlockWordStats(data);
    setStatus("blockWordsStatus", `已加载个人 ${data.count || 0} 个，全局 ${data.global_count || 0} 个，最终生效 ${data.effective_count || 0} 个`);
  } catch (err) {
    setStatus("blockWordsStatus", err.message, true);
  }
}

function renderBlockWordStats(data) {
  const el = byId("blockWordStats");
  if (!el) return;
  const items = [
    ["个人屏蔽词", data.count || 0],
    ["全局屏蔽词", data.global_count || 0],
    ["最终生效", data.effective_count || 0],
  ];
  el.innerHTML = items.map(([label, value]) => `
    <div class="block-stat"><span>${label}</span><strong>${formatNumber(value)}</strong></div>
  `).join("");
}

async function saveBlockWords() {
  try {
    const raw = byId("blockWordsInput").value;
    const data = await requestJSON(API.blockWords, {
      method: "POST",
      body: JSON.stringify({ words: raw }),
    });
    byId("blockWordsInput").value = (data.words || []).join("\n");
    renderBlockWordStats(data);
    setStatus("blockWordsStatus", data.message || `已保存 ${data.count || 0} 个屏蔽词`);
  } catch (err) {
    setStatus("blockWordsStatus", err.message, true);
  }
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function jobStatusLabel(status) {
  const labels = {
    pending: "等待中",
    running: "运行中",
    success: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status] || status || "未知";
}

function shortTime(value) {
  const text = String(value || "");
  return text.includes("T") ? text.slice(11, 19) : text || "-";
}

function stopRefreshJobPolling(clearActive = false) {
  if (refreshJobPollTimer) {
    clearInterval(refreshJobPollTimer);
    refreshJobPollTimer = null;
  }
  if (clearActive) activeRefreshJobId = "";
}

function aiProviderPayload(includeKey = true) {
  const payload = {
    provider: byId("aiProviderSelect").value,
    model: byId("aiProviderModel").value.trim(),
    base_url: byId("aiProviderBaseUrl").value.trim(),
  };
  if (includeKey) payload.api_key = byId("aiProviderKey").value.trim();
  return payload;
}

function providerTemplate(value) {
  return aiProviderTemplates.find((item) => item.value === value);
}

function renderAiProviderTemplates(templates, selectedProvider) {
  if (Array.isArray(templates) && templates.length) {
    aiProviderTemplates = templates;
    byId("aiProviderSelect").innerHTML = templates.map((item) => `
      <option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>
    `).join("");
  }
  byId("aiProviderSelect").value = selectedProvider || "deepseek";
  if (!byId("aiProviderSelect").value && aiProviderTemplates.length) {
    byId("aiProviderSelect").value = aiProviderTemplates[0].value;
  }
}

function applyAiProviderTemplate(provider) {
  const template = providerTemplate(provider);
  if (!template) return;
  byId("aiProviderModel").value = template.model || "";
  byId("aiProviderBaseUrl").value = template.base_url || "";
  byId("aiProviderKey").placeholder = template.key_hint || "API Key";
}

function renderAiProvider(data) {
  aiProviderConfigured = Boolean(data.configured);
  const provider = data.provider || "deepseek";
  renderAiProviderTemplates(data.templates, provider);
  const template = providerTemplate(provider) || {};
  byId("aiProviderModel").value = data.model || template.model || "deepseek-v4-flash";
  byId("aiProviderBaseUrl").value = data.base_url || template.base_url || "https://api.deepseek.com";
  byId("aiProviderKey").placeholder = template.key_hint || "API Key";
  byId("aiProviderKey").value = "";
  const storageLabel = data.storage === "local-encrypted" ? "本机加密存储" : data.storage;
  const text = data.configured
    ? `已配置：${data.provider} / ${data.model} / ${data.masked_key}（${storageLabel}）`
    : "未配置自带模型 API，开启 API 开关后仍需先保存本账号的模型配置";
  setStatus("aiProviderStatus", data.message || text);
}

async function loadAiProvider() {
  try {
    const data = await requestJSON(API.aiProvider);
    renderAiProvider(data);
  } catch (err) {
    setStatus("aiProviderStatus", err.message, true);
  }
}

async function saveAiProvider() {
  try {
    const data = await requestJSON(API.aiProvider, {
      method: "POST",
      body: JSON.stringify(aiProviderPayload(true)),
    });
    renderAiProvider(data);
    const enabled = Boolean(sessionState?.user?.api_enabled);
    setStatus("aiProviderStatus", enabled
      ? `${data.message} 当前账号 API 已开启，主页面可以使用 AI 评价。`
      : `${data.message} 还需要开启 API 开关后，主页面才会开放 AI 评价。`);
  } catch (err) {
    setStatus("aiProviderStatus", err.message, true);
  }
}

async function testAiProvider() {
  try {
    const payload = byId("aiProviderKey").value.trim()
      ? aiProviderPayload(true)
      : aiProviderPayload(false);
    const data = await requestJSON(API.aiProviderTest, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderAiProvider(data);
    setStatus("aiProviderStatus", data.message || "连接测试成功");
  } catch (err) {
    setStatus("aiProviderStatus", err.message, true);
  }
}

async function clearAiProvider() {
  try {
    const data = await requestJSON(API.aiProvider, {
      method: "POST",
      body: JSON.stringify({ clear: true }),
    });
    renderAiProvider(data);
  } catch (err) {
    setStatus("aiProviderStatus", err.message, true);
  }
}

function renderBiliCookie(data) {
  byId("biliCookieValue").value = "";
  const type = data.credential_type || "sessdata";
  byId("biliCredentialType").value = type === "cookie" ? "cookie" : "sessdata";
  const storageLabel = data.storage === "local-encrypted" ? "本机加密存储" : data.storage;
  const text = data.configured
    ? `已配置：${data.credential_type === "cookie" ? "BILI_COOKIE" : "BILI_SESSDATA"} / ${data.masked_value}（${storageLabel}，${data.updated_at || "-"}）`
    : "未配置。主页面勾选“历史补抓”时会回退到服务端环境变量；若也未配置环境变量，则只能使用公开接口。";
  setStatus("biliCookieStatus", data.message || text);
}

async function loadBiliCookie() {
  try {
    const data = await requestJSON(API.biliCookie);
    renderBiliCookie(data);
  } catch (err) {
    setStatus("biliCookieStatus", err.message, true);
  }
}

async function saveBiliCookie() {
  try {
    const data = await requestJSON(API.biliCookie, {
      method: "POST",
      body: JSON.stringify({
        credential_type: byId("biliCredentialType").value,
        value: byId("biliCookieValue").value.trim(),
      }),
    });
    renderBiliCookie(data);
  } catch (err) {
    setStatus("biliCookieStatus", err.message, true);
  }
}

async function clearBiliCookie() {
  try {
    const data = await requestJSON(API.biliCookie, {
      method: "POST",
      body: JSON.stringify({ clear: true }),
    });
    renderBiliCookie(data);
  } catch (err) {
    setStatus("biliCookieStatus", err.message, true);
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function refreshAiCaptcha() {
  try {
    const data = await requestJSON(API.aiCaptcha);
    aiCaptchaToken = data.token;
    byId("aiQuestion").textContent = data.question;
  } catch (err) {
    byId("aiQuestion").textContent = "加载失败";
    setStatus("authStatus", err.message, true);
  }
}

async function refreshLoginCaptcha() {
  try {
    const data = await requestJSON(API.aiCaptcha);
    loginCaptchaToken = data.token;
    byId("loginAiQuestion").textContent = data.question;
  } catch (err) {
    byId("loginAiQuestion").textContent = "加载失败";
    setStatus("authStatus", err.message, true);
  }
}

async function loadAdminData() {
  const tasks = [
    loadAdminStatus(),
    loadAdminUsers(),
    loadAdminBlockWords(),
    loadAiCacheStats(),
    loadRecentRefreshJobs(),
  ];
  resetStorageUsagePanel();
  if (isOwnerRole(sessionState?.user?.role)) {
    tasks.push(loadAdminAiUsage());
  } else {
    clearAdminAiUsage();
  }
  await Promise.all(tasks);
}

function updateOwnerOnlySections(user) {
  const showOwnerOnly = isOwnerRole(user?.role);
  const aiUsageCard = byId("ownerAiUsageCard");
  if (aiUsageCard) {
    aiUsageCard.hidden = !showOwnerOnly;
  }
  document.querySelectorAll(".owner-identity-only").forEach((el) => {
    el.hidden = !showOwnerOnly;
  });
  if (!showOwnerOnly) {
    clearAdminAiUsage();
  }
}

function stopServerClock() {
  if (serverClockTimer) {
    clearInterval(serverClockTimer);
    serverClockTimer = null;
  }
}

function setServerClock(serverTime) {
  const parsed = Date.parse(serverTime);
  if (!Number.isFinite(parsed)) return;
  serverClockBaseMs = parsed;
  serverClockClientMs = Date.now();
  updateServerClockDisplay();
  stopServerClock();
  serverClockTimer = setInterval(updateServerClockDisplay, 1000);
}

function updateServerClockDisplay() {
  const el = byId("serverTimeLive");
  if (!el || serverClockBaseMs === null || serverClockClientMs === null) return;
  const current = new Date(serverClockBaseMs + (Date.now() - serverClockClientMs));
  el.textContent = current.toLocaleString("zh-CN", { hour12: false });
}

async function loadAdminStatus() {
  try {
    const data = await requestJSON(API.adminStatus);
    const identity = data.current_identity?.role || "normal";
    document.querySelectorAll(".identity-admin-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.role === identity);
    });
    const rows = [
      ["服务器时间", data.server_time, "serverTimeLive"],
      ["当前演示身份", identity],
      ["当前账号", data.current_account || "-"],
      ["账号数量", data.account_count],
      ["归档日期数", (data.archive_dates || []).length],
      ["dashboard.json", data.files?.dashboard?.exists ? `${data.files.dashboard.size} bytes` : "缺失"],
      ["danmaku_index.json", data.files?.danmaku_index?.exists ? `${data.files.danmaku_index.size} bytes` : "缺失"],
      ["video_stats.json", data.files?.video_stats?.exists ? `${data.files.video_stats.size} bytes` : "缺失"],
      ["accounts.txt", data.files?.accounts?.exists ? `${data.files.accounts.size} bytes` : "缺失"],
    ];
    byId("serverStatus").innerHTML = rows.map(([label, value, id]) => `
      <div class="server-item"><span>${label}</span><strong${id ? ` id="${id}"` : ""}>${escapeHtml(value)}</strong></div>
    `).join("");
    setServerClock(data.server_time);
  } catch (err) {
    setStatus("accountStatus", err.message, true);
  }
}

function renderRefreshJob(job) {
  const panel = byId("refreshJobPanel");
  if (!panel) return;
  const state = byId("refreshJobState");
  const progressText = byId("refreshJobProgressText");
  const bar = byId("refreshJobProgressBar");
  const message = byId("refreshJobMessage");
  const metrics = byId("refreshJobMetrics");
  const events = byId("refreshJobEvents");
  const button = byId("refreshPopularBtn");

  if (!job) {
    panel.className = "job-panel";
    state.textContent = "等待更新";
    progressText.textContent = "0%";
    bar.style.width = "0%";
    message.textContent = "点击更新后会显示采集步骤。";
    metrics.innerHTML = "";
    events.innerHTML = "";
    if (button) button.disabled = false;
    return;
  }

  const status = job.status || "pending";
  const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  panel.className = `job-panel job-${status}`;
  state.textContent = jobStatusLabel(status);
  progressText.textContent = `${progress}%`;
  bar.style.width = `${progress}%`;
  message.textContent = job.message || "任务状态更新中";
  if (button) button.disabled = !TERMINAL_JOB_STATUSES.has(status);

  const result = job.result || {};
  const lastEvent = (job.events || [])[job.events.length - 1] || {};
  const detail = lastEvent.detail || {};
  const metricRows = [
    ["任务ID", String(job.job_id || "").slice(0, 8) || "-"],
    ["创建", shortTime(job.created_at)],
    ["视频", result.video_count !== undefined ? formatNumber(result.video_count) : (detail.total ? `${formatNumber(detail.done || 0)}/${formatNumber(detail.total)}` : "-")],
    ["弹幕", result.danmaku_count !== undefined ? formatNumber(result.danmaku_count) : (detail.rows_count !== undefined ? formatNumber(detail.rows_count) : "-")],
    ["警告", result.failed_video_count !== undefined ? formatNumber(result.failed_video_count) : "-"],
    ["导出", result.exported_video_count !== undefined ? `${formatNumber(result.exported_video_count)} 视频` : "-"],
  ];
  metrics.innerHTML = metricRows.map(([label, value]) => `
    <div class="job-metric"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");

  const shownEvents = (job.events || []).slice(-8).reverse();
  events.innerHTML = shownEvents.length
    ? shownEvents.map((item) => `
      <div class="job-event job-event-${escapeHtml(item.level || "info")}">
        <span>${escapeHtml(shortTime(item.created_at))}</span>
        <p>${escapeHtml(item.message || "")}</p>
      </div>
    `).join("")
    : '<p class="job-event-empty">暂无任务事件</p>';
}

async function refreshJobStatus(jobId) {
  const data = await requestJSON(`${API.jobStatus}?job_id=${encodeURIComponent(jobId)}`);
  const job = data.job;
  renderRefreshJob(job);
  if (TERMINAL_JOB_STATUSES.has(job.status)) {
    stopRefreshJobPolling(false);
    if (job.status === "success") {
      setStatus("accountStatus", job.message || "热门榜单更新完成");
      await loadAdminStatus();
    } else if (job.status === "failed") {
      setStatus("accountStatus", job.error || job.message || "热门榜单更新失败", true);
    }
  }
}

function startRefreshJobPolling(jobId) {
  activeRefreshJobId = jobId;
  stopRefreshJobPolling(false);
  refreshJobStatus(jobId).catch((err) => setStatus("accountStatus", err.message, true));
  refreshJobPollTimer = setInterval(() => {
    refreshJobStatus(jobId).catch((err) => {
      stopRefreshJobPolling(false);
      setStatus("accountStatus", err.message, true);
    });
  }, 1000);
}

async function loadRecentRefreshJobs() {
  try {
    const data = await requestJSON(`${API.recentJobs}?type=refresh_popular&limit=5`);
    const latest = (data.jobs || [])[0] || null;
    if (!latest) {
      renderRefreshJob(null);
      return;
    }
    renderRefreshJob(latest);
    if (!TERMINAL_JOB_STATUSES.has(latest.status)) {
      startRefreshJobPolling(latest.job_id);
    }
  } catch (err) {
    setStatus("accountStatus", err.message, true);
  }
}

async function loadAdminUsers() {
  try {
    const data = await requestJSON(API.adminUsers);
    const canManagePrivileged = isOwnerRole(sessionState?.user?.role);
    byId("userAdminList").innerHTML = data.users.map((user) => {
      const privileged = isAdminRole(user.role);
      const locked = privileged && !canManagePrivileged;
      const selfOwner = canManagePrivileged && isOwnerRole(user.role) && user.account === sessionState?.user?.account;
      const rowClass = locked ? " user-row-locked" : "";
      const roleDisabledAttr = locked || selfOwner ? " disabled" : "";
      const editDisabledAttr = locked ? " disabled" : "";
      const disableAccountAttr = locked || selfOwner ? " disabled" : "";
      return `
      <div class="user-row${rowClass}" data-account="${escapeHtml(user.account)}">
        <div class="user-main">
          <strong>${escapeHtml(user.username)}</strong>
          <span>${escapeHtml(user.account_masked)} ｜ ${escapeHtml(user.email_masked)} ｜ ${roleLabel(user.role)}</span>
          ${locked ? '<em class="role-lock-hint">仅 owner 可管理</em>' : ""}
          ${selfOwner ? '<em class="role-lock-hint">已保护最高权限</em>' : ""}
        </div>
        <select class="admin-role-select"${roleDisabledAttr}>
          ${roleSelectOptions(user.role, canManagePrivileged)}
        </select>
        <label>搜索间隔<input class="admin-search-interval" type="number" min="0" max="3600" value="${Number(user.search_interval_seconds ?? 10)}"${editDisabledAttr}></label>
        <span class="user-api-state">API：${user.api_enabled ? "已开启" : "未开启"}</span>
        <label><input class="admin-disabled-check" type="checkbox"${user.disabled ? " checked" : ""}${disableAccountAttr}>禁用</label>
        <button class="ghost-action save-user-btn" type="button"${editDisabledAttr}>保存</button>
      </div>
    `;
    }).join("");
  } catch (err) {
    setStatus("accountStatus", err.message, true);
  }
}

async function loadAdminBlockWords() {
  try {
    const data = await requestJSON(API.adminBlockWords);
    byId("globalBlockWordsInput").value = (data.words || []).join("\n");
    setStatus("globalBlockWordsStatus", `已加载 ${data.count || 0} 个全局屏蔽词`);
  } catch (err) {
    setStatus("globalBlockWordsStatus", err.message, true);
  }
}

async function saveAdminBlockWords() {
  try {
    const raw = byId("globalBlockWordsInput").value;
    const data = await requestJSON(API.adminBlockWords, {
      method: "POST",
      body: JSON.stringify({ words: raw }),
    });
    byId("globalBlockWordsInput").value = (data.words || []).join("\n");
    setStatus("globalBlockWordsStatus", data.message || `已保存 ${data.count || 0} 个全局屏蔽词`);
    await loadBlockWords();
  } catch (err) {
    setStatus("globalBlockWordsStatus", err.message, true);
  }
}

function renderAiCacheStats(data) {
  const rows = [
    ["缓存文件数", formatNumber(data.count || 0)],
    ["占用空间", formatBytes(data.total_bytes || 0)],
    ["最近缓存", data.newest_at || "-"],
    ["最早缓存", data.oldest_at || "-"],
  ];
  byId("aiCacheStatus").innerHTML = rows.map(([label, value]) => `
    <div class="server-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

async function loadAiCacheStats() {
  try {
    const data = await requestJSON(API.adminAiCache);
    renderAiCacheStats(data);
    setStatus("aiCacheMessage", `缓存目录：${data.path || "data/ai_analysis/cache"}`);
  } catch (err) {
    setStatus("aiCacheMessage", err.message, true);
  }
}

async function clearAiCache(mode) {
  try {
    if (mode === "all" && !window.confirm("确定清空全部 AI 缓存？这不会删除最新报告文件，但之后相同分析会重新调用模型。")) {
      return;
    }
    const data = await requestJSON(API.adminAiCacheClear, {
      method: "POST",
      body: JSON.stringify({
        mode,
        max_age_days: 7,
        confirm: mode === "all",
      }),
    });
    renderAiCacheStats(data);
    setStatus("aiCacheMessage", `已清理 ${formatNumber(data.removed || 0)} 个缓存文件，释放 ${formatBytes(data.removed_bytes || 0)}`);
  } catch (err) {
    setStatus("aiCacheMessage", err.message, true);
  }
}

function renderStorageUsage(data) {
  const categories = data.categories || {};
  const redundant = data.redundant || {};
  const item = (key) => categories[key] || {};
  const archiveLegacy = redundant.archive_legacy_danmakus || {};
  const rows = [
    ["总占用", formatBytes(data.total_bytes || 0)],
    ["当前榜单弹幕分库", `${formatBytes(item("current_split_danmakus").bytes || 0)} / ${formatNumber(item("current_split_danmakus").files || 0)} 文件`],
    ["旧前端 danmakus.json", item("legacy_frontend_danmakus").exists ? formatBytes(item("legacy_frontend_danmakus").bytes || 0) : "无"],
    ["运行时弹幕副本", `${formatBytes((item("runtime_raw_danmakus").bytes || 0) + (item("runtime_processed_danmakus").bytes || 0))} / ${formatNumber((item("runtime_raw_danmakus").files || 0) + (item("runtime_processed_danmakus").files || 0))} 文件`],
    ["历史归档", `${formatBytes(item("archives").bytes || 0)} / ${formatNumber((data.archive_dates || []).length)} 个日期`],
    ["归档旧全量弹幕", archiveLegacy.exists ? `${formatBytes(archiveLegacy.bytes || 0)} / ${formatNumber(archiveLegacy.files || 0)} 文件` : "无"],
    ["AI 缓存", `${formatBytes(item("ai_cache").bytes || 0)} / ${formatNumber(item("ai_cache").files || 0)} 文件`],
    ["AI 报告", `${formatBytes(item("ai_artifacts").bytes || 0)} / ${formatNumber(item("ai_artifacts").files || 0)} 文件`],
  ];
  byId("storageUsageStatus").innerHTML = rows.map(([label, value]) => `
    <div class="server-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

function storageCleanupPayload(dryRun) {
  return {
    dry_run: Boolean(dryRun),
    legacy_frontend_danmakus: byId("storageCleanupLegacy").checked,
    runtime_flat_danmakus: byId("storageCleanupRuntimeFlat").checked,
    current_orphan_danmakus: byId("storageCleanupCurrentOrphans").checked,
    archive_orphan_danmakus: byId("storageCleanupArchiveOrphans").checked,
    archive_legacy_danmakus: byId("storageCleanupArchiveLegacy").checked,
    ai_cache_expired: byId("storageCleanupAiCache").checked,
    ai_cache_max_age_days: Number(byId("storageAiCacheDays").value || 7),
    archive_retention_days: Number(byId("storageArchiveDays").value || 0),
    confirm_archive_cleanup: byId("storageArchiveConfirm").checked,
  };
}

function renderStorageCleanupCandidates(data) {
  const box = byId("storageCleanupCandidates");
  const candidates = data.candidates || [];
  if (!candidates.length) {
    box.innerHTML = '<p class="job-event-empty">没有可清理文件</p>';
    return;
  }
  box.innerHTML = candidates.slice(0, 12).map((item) => `
    <div class="job-event">
      <span>${escapeHtml(formatBytes(item.bytes || 0))}</span>
      <p>${escapeHtml(item.reason || "-")} ｜ ${escapeHtml(item.path || "")}</p>
    </div>
  `).join("") + (candidates.length > 12
    ? `<p class="job-event-empty">还有 ${formatNumber(candidates.length - 12)} 项未显示</p>`
    : "");
}

function resetStorageUsagePanel() {
  const box = byId("storageUsageStatus");
  if (box && !box.innerHTML.trim()) {
    box.innerHTML = '<div class="server-item"><span>本地储存占用</span><strong>点击刷新占用后扫描</strong></div>';
  }
  const msg = byId("storageCleanupMessage");
  if (msg && !msg.textContent.trim()) {
    setStatus("storageCleanupMessage", "点击刷新占用或预览清理时才会扫描本地归档目录");
  }
}

async function loadStorageUsage() {
  try {
    const data = await requestJSON(API.adminStorageUsage);
    renderStorageUsage(data);
    setStatus("storageCleanupMessage", "已加载本地储存占用");
  } catch (err) {
    setStatus("storageCleanupMessage", err.message, true);
  }
}

async function runStorageCleanup(dryRun) {
  try {
    const payload = storageCleanupPayload(dryRun);
    if (!dryRun) {
      const archiveDays = Number(payload.archive_retention_days || 0);
      const archiveText = archiveDays > 0 ? `，并删除 ${archiveDays} 天前的历史归档` : "";
      if (!window.confirm(`确定执行本地储存清理${archiveText}？该操作无法从页面撤销。`)) return;
    }
    const data = await requestJSON(API.adminStorageCleanup, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderStorageUsage(data.usage || {});
    renderStorageCleanupCandidates(data);
    const action = dryRun ? "预计可释放" : "已释放";
    const count = dryRun ? data.candidate_count : data.removed;
    const bytes = dryRun ? data.candidate_bytes : data.removed_bytes;
    setStatus("storageCleanupMessage", `${action} ${formatBytes(bytes || 0)}，涉及 ${formatNumber(count || 0)} 项`);
  } catch (err) {
    setStatus("storageCleanupMessage", err.message, true);
  }
}

function usageStatusLabel(status) {
  return {
    cache_hit: "缓存命中",
    local_success: "本地分析",
    provider_success: "模型成功",
    provider_fallback: "模型失败回退",
  }[status] || status || "-";
}

function renderAiUsageSummary(data, targetId) {
  const summary = data.summary || {};
  const today = data.today || {};
  const rows = [
    ["总请求", formatNumber(summary.total_requests || 0)],
    ["今日请求", formatNumber(today.total_requests || 0)],
    ["外部调用", formatNumber(summary.external_calls || 0)],
    ["缓存命中", formatNumber(summary.cache_hits || 0)],
    ["失败/回退", `${formatNumber(summary.failures || 0)} / ${formatNumber(summary.provider_fallbacks || 0)}`],
    ["估算输入", `${formatNumber(summary.estimated_input_tokens || 0)} tokens`],
    ["请求体量", formatBytes(summary.request_bytes || 0)],
    ["全量原文", formatNumber(summary.full_raw_requests || 0)],
  ];
  byId(targetId).innerHTML = rows.map(([label, value]) => `
    <div class="server-item"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
}

function renderAiUsageRecent(data) {
  const box = byId("adminAiUsageRecent");
  if (!box) return;
  const recent = data.recent || [];
  box.innerHTML = recent.length
    ? recent.slice(0, 8).map((item) => `
      <div class="job-event">
        <span>${escapeHtml(shortTime(item.created_at))}</span>
        <p>${escapeHtml(item.account || "-")} ｜ ${escapeHtml(item.provider || "local-demo")} ｜ ${escapeHtml(item.analysis_mode || "-")} ｜ ${escapeHtml(usageStatusLabel(item.status))}</p>
      </div>
    `).join("")
    : '<p class="job-event-empty">暂无 AI 调用记录</p>';
}

function clearAdminAiUsage() {
  const status = byId("adminAiUsageStatus");
  const recent = byId("adminAiUsageRecent");
  if (status) status.innerHTML = "";
  if (recent) recent.innerHTML = "";
  setStatus("adminAiUsageMessage", "");
}

async function loadAccountAiUsage() {
  try {
    const data = await requestJSON(API.accountAiUsage);
    renderAiUsageSummary(data, "accountAiUsageStatus");
    setStatus("accountAiUsageMessage", data.note || "费用请以模型平台控制台为准");
  } catch (err) {
    setStatus("accountAiUsageMessage", err.message, true);
  }
}

async function loadAdminAiUsage() {
  if (!isOwnerRole(sessionState?.user?.role)) {
    clearAdminAiUsage();
    return;
  }
  try {
    const data = await requestJSON(API.adminAiUsage);
    renderAiUsageSummary(data, "adminAiUsageStatus");
    renderAiUsageRecent(data);
    setStatus("adminAiUsageMessage", data.note || "费用请以模型平台控制台为准");
  } catch (err) {
    setStatus("adminAiUsageMessage", err.message, true);
  }
}

function bindEvents() {
  byId("loginTab").addEventListener("click", () => showAuthMode("login"));
  byId("registerTab").addEventListener("click", () => showAuthMode("register"));
  byId("refreshCaptchaBtn").addEventListener("click", refreshAiCaptcha);
  byId("refreshLoginCaptchaBtn").addEventListener("click", refreshLoginCaptcha);

  byId("emailCodeBtn").addEventListener("click", async () => {
    try {
      const email = byId("registerEmail").value.trim();
      const data = await requestJSON(API.emailCode, {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setStatus("authStatus", `${data.message} 验证码：${data.demo_code}`);
    } catch (err) {
      setStatus("authStatus", err.message, true);
    }
  });

  byId("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = formPayload({
        account: "loginAccount",
        password: "loginPassword",
      });
      if (!byId("loginCaptchaPanel").hidden) {
        payload.ai_token = loginCaptchaToken;
        payload.ai_answer = byId("loginAiAnswer").value.trim();
      }
      const data = await requestJSON(API.login, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionState = data;
      setStatus("authStatus", "");
      setLoginCaptchaVisible(false);
      renderSession();
    } catch (err) {
      if (err.data?.requires_captcha) {
        setLoginCaptchaVisible(true);
        byId("loginAiAnswer").value = "";
        await refreshLoginCaptcha();
      }
      setStatus("authStatus", err.message, true);
    }
  });

  byId("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = formPayload({
        username: "registerUsername",
        account: "registerAccount",
        password: "registerPassword",
        password_confirm: "registerPasswordConfirm",
        email: "registerEmail",
        email_code: "registerEmailCode",
        ai_answer: "registerAiAnswer",
      });
      payload.ai_token = aiCaptchaToken;
      const data = await requestJSON(API.register, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionState = data;
      setStatus("authStatus", "");
      renderSession();
    } catch (err) {
      setStatus("authStatus", err.message, true);
      refreshAiCaptcha();
    }
  });

  byId("logoutBtn").addEventListener("click", async () => {
    await requestJSON(API.logout, { method: "POST", body: "{}" });
    sessionState = { ok: true, logged_in: false, user: null };
    renderSession();
  });

  byId("profileForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await requestJSON(API.profile, {
        method: "POST",
        body: JSON.stringify({
          username: byId("profileUsername").value.trim(),
          gender: byId("profileGender").value,
          birthday: byId("profileBirthday").value,
        }),
      });
      sessionState = data;
      renderSession();
      setStatus("accountStatus", "资料已保存");
    } catch (err) {
      setStatus("accountStatus", err.message, true);
    }
  });

  byId("apiEnabled").addEventListener("change", async (event) => {
    try {
      const data = await requestJSON(API.apiToggle, {
        method: "POST",
        body: JSON.stringify({ enabled: event.target.checked }),
      });
      sessionState = data;
      renderSession();
      if (event.target.checked && !aiProviderConfigured) {
        setStatus("accountStatus", "API 开关已开启；请先保存本账号的模型 API 配置，主页面才会开放 AI 评价。");
      } else {
        setStatus("accountStatus", event.target.checked ? "API 已开启，主页面可使用已配置的模型 API" : "API 已关闭，主页面 AI 功能已停用");
      }
    } catch (err) {
      setStatus("accountStatus", err.message, true);
      event.target.checked = !event.target.checked;
    }
  });

  byId("resetApiKeyBtn").addEventListener("click", async () => {
    try {
      const data = await requestJSON(API.apiReset, { method: "POST", body: "{}" });
      sessionState = data;
      renderSession();
      setStatus("accountStatus", "本地访问令牌已重置；模型 API 仍以自带模型配置为准");
    } catch (err) {
      setStatus("accountStatus", err.message, true);
    }
  });

  byId("saveBlockWordsBtn").addEventListener("click", saveBlockWords);
  byId("refreshAiUsageBtn").addEventListener("click", loadAccountAiUsage);
  byId("saveGlobalBlockWordsBtn").addEventListener("click", saveAdminBlockWords);
  byId("pruneAiCacheBtn").addEventListener("click", () => clearAiCache("expired"));
  byId("clearAiCacheBtn").addEventListener("click", () => clearAiCache("all"));
  byId("refreshStorageUsageBtn").addEventListener("click", loadStorageUsage);
  byId("previewStorageCleanupBtn").addEventListener("click", () => runStorageCleanup(true));
  byId("runStorageCleanupBtn").addEventListener("click", () => runStorageCleanup(false));
  byId("refreshAdminAiUsageBtn").addEventListener("click", () => {
    if (!isOwnerRole(sessionState?.user?.role)) {
      clearAdminAiUsage();
      return;
    }
    loadAdminAiUsage();
  });
  byId("aiProviderSelect").addEventListener("change", (event) => applyAiProviderTemplate(event.target.value));
  byId("saveAiProviderBtn").addEventListener("click", saveAiProvider);
  byId("testAiProviderBtn").addEventListener("click", testAiProvider);
  byId("clearAiProviderBtn").addEventListener("click", clearAiProvider);
  byId("saveBiliCookieBtn").addEventListener("click", saveBiliCookie);
  byId("clearBiliCookieBtn").addEventListener("click", clearBiliCookie);

  byId("copyApiKeyBtn").addEventListener("click", async () => {
    const key = byId("apiKeyInput").value;
    if (!key) {
      setStatus("accountStatus", "请先开启 API");
      return;
    }
    await navigator.clipboard.writeText(key);
    setStatus("accountStatus", "本地访问令牌已复制");
  });

  document.querySelectorAll(".identity-admin-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await requestJSON(API.identity, {
          method: "POST",
          body: JSON.stringify({ role: btn.dataset.role }),
        });
        await loadAdminStatus();
        setStatus("accountStatus", "演示身份已切换");
      } catch (err) {
        setStatus("accountStatus", err.message, true);
      }
    });
  });

  byId("refreshPopularBtn").addEventListener("click", async () => {
    try {
      setStatus("accountStatus", "热门榜单更新任务已提交，正在创建进度面板...");
      byId("refreshPopularBtn").disabled = true;
      const data = await requestJSON(API.refreshPopularJob, {
        method: "POST",
        body: "{}",
      });
      renderRefreshJob(data.job);
      startRefreshJobPolling(data.job.job_id);
      setStatus("accountStatus", data.existing ? "已有热门榜单更新任务正在运行" : "热门榜单更新任务已开始");
    } catch (err) {
      byId("refreshPopularBtn").disabled = false;
      setStatus("accountStatus", err.message, true);
    }
  });

  byId("reloadAdminBtn").addEventListener("click", loadAdminData);

  byId("userAdminList").addEventListener("click", async (event) => {
    const button = event.target.closest(".save-user-btn");
    if (!button) return;
    if (button.disabled) return;
    const row = button.closest(".user-row");
    try {
      await requestJSON(API.adminUserUpdate, {
        method: "POST",
        body: JSON.stringify({
          account: row.dataset.account,
          role: row.querySelector(".admin-role-select").value,
          search_interval_seconds: row.querySelector(".admin-search-interval").value,
          disabled: row.querySelector(".admin-disabled-check").checked,
        }),
      });
      setStatus("accountStatus", "账号权限已更新");
      await loadAdminUsers();
      await loadAdminStatus();
    } catch (err) {
      setStatus("accountStatus", err.message, true);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  refreshAiCaptcha();
  loadSession();
});
