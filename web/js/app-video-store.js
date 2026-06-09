function normalizeMediaUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw.startsWith("//")) return `https:${raw}`;
  if (raw.startsWith("http://")) return raw.replace(/^http:\/\//, "https://");
  return raw;
}

function getVideoCoverUrl(video) {
  if (!video) return "";
  return normalizeMediaUrl(video.cover_url || video.pic || video.cover || video.thumbnail);
}

function getVideoDescription(video) {
  if (!video) return "";
  if (video.desc_v2 && Array.isArray(video.desc_v2)) {
    const parts = video.desc_v2
      .map((item) => String(item.raw_text || "").trim())
      .filter(Boolean);
    if (parts.length) return parts.join("\n");
  }
  return String(video.desc || video.description || video.introduction || "").trim();
}

function getVideoPageUrl(video) {
  const bvid = String(video?.bvid || "").trim();
  return bvid ? `https://www.bilibili.com/video/${encodeURIComponent(bvid)}` : "#";
}

function setVideoCover(video) {
  const img = byId("videoCover");
  const frame = img ? img.closest(".cover-frame") : null;
  if (!img || !frame) return;

  const url = getVideoCoverUrl(video) || VIDEO_PLACEHOLDER_URL;
  img.onerror = null;
  if (!url) {
    img.hidden = true;
    img.removeAttribute("src");
    frame.classList.remove("has-cover");
    return;
  }

  img.hidden = false;
  img.alt = `${video?.title || video?.bvid || "未选择视频"}封面`;
  frame.classList.add("has-cover");
  img.onerror = () => {
    img.hidden = true;
    img.removeAttribute("src");
    frame.classList.remove("has-cover");
  };
  img.src = url;
}

function needsVideoInfoHydration(video) {
  if (!video || !video.bvid) return false;
  return !getVideoCoverUrl(video)
    || !getVideoDescription(video)
    || video.like === undefined
    || video.favorite === undefined
    || video.coin === undefined;
}

function updateVideoEverywhere(info) {
  if (!info || !info.bvid) return;
  const lists = [
    dashboardData ? dashboardData.raw_videos : [],
    searchedVideos,
    customVideos,
    compareVideos,
  ];
  lists.forEach((list) => {
    (list || []).forEach((video) => {
      if (video.bvid === info.bvid) Object.assign(video, info);
    });
  });
}

async function hydrateVideoInfo(video) {
  if (!needsVideoInfoHydration(video) || videoInfoHydrationTried.has(video.bvid)) return;
  videoInfoHydrationTried.add(video.bvid);
  try {
    const resp = await fetch(`${API_ENDPOINTS.videoInfo}?bvid=${encodeURIComponent(video.bvid)}`, { cache: "no-store" });
    const result = await resp.json();
    if (!result.ok) {
      videoInfoHydrationTried.delete(video.bvid);
      return;
    }
    updateVideoEverywhere(result.video);
    renderVideoInfo();
    markActiveRankItem();
    renderCompareSection();
  } catch {
    videoInfoHydrationTried.delete(video.bvid);
    // 静态打开页面或网络不可用时保留已有数据。
  }
}

function activeVideos() {
  return activeList === "custom" ? customVideos : (dashboardData.raw_videos || []);
}

function findDashboardVideo(bvid) {
  return (dashboardData.raw_videos || []).find((v) => v.bvid === bvid);
}

function findVideo(bvid) {
  return searchedVideos.find((v) => v.bvid === bvid)
    || customVideos.find((v) => v.bvid === bvid)
    || (dashboardData.raw_videos || []).find((v) => v.bvid === bvid)
    || compareVideos.find((v) => v.bvid === bvid);
}

function uniqueRows(rows) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = `${row.bvid || ""}|${row.cid || ""}|${row.time_in_video}|${row.user_hash}|${row.content}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function normalizePoolKey(value) {
  return String(value || "").trim();
}

function collectVideoPoolKeys(video) {
  if (!video) return [];
  const keys = [];
  const bvid = normalizePoolKey(video.bvid);
  const title = normalizePoolKey(video.title);
  if (bvid) keys.push(`bvid:${bvid}`);
  if (title) keys.push(`title:${title}`);
  return keys;
}

function collectRowPoolKeys(row) {
  if (!row) return [];
  const keys = [];
  const bvid = normalizePoolKey(row.bvid);
  const title = normalizePoolKey(row.title);
  if (bvid) keys.push(`bvid:${bvid}`);
  if (title) keys.push(`title:${title}`);
  return keys;
}

function invalidateDanmakuPoolIndex() {
  danmakuPoolIndex = null;
  invalidateStatsCache();
}

function appendRowsToDanmakuPoolIndex(index, rows) {
  (rows || []).forEach((row) => {
    collectRowPoolKeys(row).forEach((key) => {
      if (!index.has(key)) index.set(key, []);
      index.get(key).push(row);
    });
  });
}

function getDanmakuPoolIndex() {
  if (danmakuPoolIndex) return danmakuPoolIndex;
  const index = new Map();
  appendRowsToDanmakuPoolIndex(index, danmakus);
  appendRowsToDanmakuPoolIndex(index, customDanmakus);
  appendRowsToDanmakuPoolIndex(index, searchedDanmakus);
  danmakuPoolIndex = index;
  return danmakuPoolIndex;
}

function getDanmakusForVideoFromRows(video, rows) {
  if (!video) return [];
  const bvid = normalizePoolKey(video.bvid);
  const title = normalizePoolKey(video.title);
  return uniqueRows((rows || []).filter((row) => {
    const rowBvid = normalizePoolKey(row.bvid);
    const rowTitle = normalizePoolKey(row.title);
    return (bvid && rowBvid === bvid) || (title && rowTitle === title);
  }));
}

function isCurrentDashboardVideo(video) {
  return Boolean(video && (dashboardData.raw_videos || []).includes(video));
}

function hotDanmakuLoadKey(video) {
  return `${hotDate || "current"}|${String(video?.bvid || "")}`;
}

function getDanmakusForVideo(video) {
  if (!video) return [];
  if (isCurrentDashboardVideo(video)) {
    const hotRows = getDanmakusForVideoFromRows(video, danmakus);
    if (hotRows.length || loadedHotDanmakuKeys.has(hotDanmakuLoadKey(video))) return hotRows;
  }
  const matches = [];
  const seenKeys = new Set();
  const index = getDanmakuPoolIndex();
  collectVideoPoolKeys(video).forEach((key) => {
    if (seenKeys.has(key)) return;
    seenKeys.add(key);
    const rows = index.get(key);
    if (rows) matches.push(...rows);
  });
  return uniqueRows(matches);
}

function videoLabel(video, fallback = "未选择") {
  if (!video) return fallback;
  return video.title || video.bvid || fallback;
}

function getVideoRows(video) {
  return applyActiveBlockWords(getDanmakusForVideo(video));
}

function getCurrentBvid() {
  return focusBvid || (selectedBvid !== "all" ? selectedBvid : null);
}

function currentVideo() {
  const bvid = getCurrentBvid();
  if (!bvid) return null;
  if (focusBvid) return findDashboardVideo(bvid) || findVideo(bvid);
  return findVideo(bvid);
}

function replaceHotDanmakus(video, rows) {
  if (!video?.bvid) return;
  danmakus = danmakus.filter((row) => {
    const rowBvid = String(row.bvid || "");
    const rowTitle = String(row.title || "");
    return rowBvid !== video.bvid && rowTitle !== String(video.title || "");
  });
  (rows || []).forEach((row) => danmakus.push(row));
  loadedHotDanmakuKeys.add(hotDanmakuLoadKey(video));
  invalidateDanmakuPoolIndex();
}

function applyLoadedVideoDanmakus(video, rows, stats = null) {
  if (!video?.bvid) return;
  if (stats) {
    video.stats = stats;
    updateVideoEverywhere({ bvid: video.bvid, stats });
  }
  if (isCurrentDashboardVideo(video)) {
    replaceHotDanmakus(video, rows);
    return;
  }
  replaceSearchedDanmakus(video.bvid, rows || []);
}

function hasLoadedVideoDanmakus(video) {
  if (!video) return true;
  if (isCurrentDashboardVideo(video)) {
    return loadedHotDanmakuKeys.has(hotDanmakuLoadKey(video));
  }
  return getDanmakusForVideo(video).length > 0;
}

async function loadStaticCurrentVideoDanmakus(video) {
  if (!video?.bvid || hotDate !== "current") return null;
  const meta = hotDanmakuIndex?.videos?.[video.bvid] || video.danmaku_store || null;
  const file = String(meta?.file || `danmakus/${video.bvid}.json`);
  const rows = await loadJSON(`./data/${file}`);
  return { ok: true, date: "current", source: "static", video, danmakus: rows, stats: video.stats || null };
}

async function ensureVideoDanmakusLoaded(video) {
  if (!video || hasLoadedVideoDanmakus(video)) return getDanmakusForVideo(video);
  if (!isCurrentDashboardVideo(video)) return getDanmakusForVideo(video);
  const query = `date=${encodeURIComponent(hotDate || "current")}&bvid=${encodeURIComponent(video.bvid)}`;
  let result = null;
  try {
    result = await requestJson(`${API_ENDPOINTS.videoDanmakus}?${query}`);
  } catch (err) {
    if (hotDate !== "current") throw err;
    result = await loadStaticCurrentVideoDanmakus(video);
  }
  if (!result?.ok) throw new Error(result?.error || "弹幕加载失败");
  const rows = result.danmakus || [];
  applyLoadedVideoDanmakus(video, rows, result.stats || result.video?.stats || null);
  return getDanmakusForVideo(video);
}

async function ensureCurrentVideoDanmakusLoaded() {
  return ensureVideoDanmakusLoaded(currentVideo());
}

async function addToCustom(bvid) {
  if (!bvid || bvid === "all") return;
  if (customVideos.some((v) => v.bvid === bvid)) return;
  if (customVideos.length >= 30) {
    alert("自定义榜单已满 30 个，请先释放部分视频后再添加。");
    return;
  }
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
  customVideos.push({ ...video });
  getDanmakusForVideo(video).forEach((row) => customDanmakus.push(row));
  invalidateDanmakuPoolIndex();
  renderCustomManage();
  updateCustomCount();
  pruneSearchedData();
  if (activeList === "custom") {
    renderAll();
    renderVideoInfo();
    filterDanmakus();
  }
}

function removeFromCustom(bvid) {
  const video = customVideos.find((v) => v.bvid === bvid);
  if (!video) return;
  customVideos = customVideos.filter((v) => v.bvid !== bvid);
  customDanmakus = customDanmakus.filter((r) => String(r.title || "") !== video.title);
  invalidateDanmakuPoolIndex();
  if (selectedBvid === bvid) selectedBvid = "all";
  if (focusBvid === bvid) focusBvid = null;
  renderCustomManage();
  updateCustomCount();
  pruneSearchedData();
  renderAll();
  renderVideoInfo();
  filterDanmakus();
}

function renderCustomManage() {
  const section = byId("customManageSection");
  const list = byId("customVideoList");
  if (activeList !== "custom") {
    section.style.display = "none";
    return;
  }
  section.style.display = "";
  if (customVideos.length === 0) {
    list.innerHTML = '<p style="color:var(--muted);">自定义榜单为空，从热门榜单或 BV 搜索中添加视频。</p>';
    return;
  }
  list.innerHTML = customVideos.map((v) => `
    <div class="custom-video-item">
      <span>${escapeHtml(v.title || v.bvid)}</span>
      <button class="remove-custom-btn" data-remove-custom data-bvid="${escapeHtml(v.bvid)}">移除</button>
    </div>
  `).join("");
}

function updateCustomCount() {
  byId("customCount").textContent = `${customVideos.length}/30`;
}

function addSearchHistory(bvid, title) {
  searchHistory = searchHistory.filter((h) => h.bvid !== bvid);
  searchHistory.unshift({ bvid, title: title || bvid });
  searchHistory = searchHistory.slice(0, SEARCH_CACHE_LIMIT);
  renderSearchHistory();
}

function rememberVideo(video, rows = null) {
  if (!video || !video.bvid) return;
  searchedVideos = searchedVideos.filter((item) => item.bvid !== video.bvid);
  searchedVideos.unshift({ ...video });
  const sourceRows = rows || getDanmakusForVideo(video);
  searchedDanmakus = searchedDanmakus.filter((row) => {
    const sameBvid = String(row.bvid || "") === String(video.bvid);
    const sameTitle = String(row.title || "") === String(video.title || "");
    return !sameBvid && !sameTitle;
  });
  sourceRows.forEach((row) => searchedDanmakus.push(row));
  invalidateDanmakuPoolIndex();
  addSearchHistory(video.bvid, video.title || video.bvid);
  pruneSearchedData();
}

function isSearchedVideoPinned(bvid) {
  return customVideos.some((v) => v.bvid === bvid) || compareVideos.some((v) => v.bvid === bvid);
}

function removeSearchedVideo(video) {
  if (!video) return;
  searchedVideos = searchedVideos.filter((v) => v.bvid !== video.bvid);
  searchedDanmakus = searchedDanmakus.filter((row) => {
    const rowBvid = String(row.bvid || "");
    const rowTitle = String(row.title || "");
    return rowBvid !== video.bvid && rowTitle !== String(video.title || "");
  });
  invalidateDanmakuPoolIndex();
  delete pageCache[video.bvid];
  searchHistory = searchHistory.filter((item) => item.bvid !== video.bvid);
  if (selectedBvid === video.bvid) selectedBvid = searchedVideos[0]?.bvid || "all";
  if (focusBvid === video.bvid) focusBvid = null;
}

function pruneSearchedData() {
  let unpinned = searchedVideos.filter((v) => !isSearchedVideoPinned(v.bvid));
  while (unpinned.length > SEARCH_CACHE_LIMIT) {
    removeSearchedVideo(unpinned[unpinned.length - 1]);
    unpinned = searchedVideos.filter((v) => !isSearchedVideoPinned(v.bvid));
  }
  renderSearchHistory();
}

function renderSearchHistory() {
  const container = byId("searchHistory");
  const tags = byId("historyTags");
  if (searchHistory.length === 0) {
    container.style.display = "none";
    return;
  }
  container.style.display = "flex";
  tags.innerHTML = searchHistory.map((h) => {
    const cls = selectedBvid === h.bvid && !focusBvid ? "history-tag current" : "history-tag";
    return `<span class="${cls}" title="${escapeHtml(h.title)}" data-history-bvid="${escapeHtml(h.bvid)}">${escapeHtml((h.title || h.bvid).slice(0, 16))}</span>`;
  }).join("");
}

function selectHistory(bvid) {
  const item = searchHistory.find((h) => h.bvid === bvid);
  if (item) {
    searchHistory = searchHistory.filter((h) => h.bvid !== bvid);
    searchHistory.unshift(item);
    renderSearchHistory();
  }
  focusBvid = null;
  selectedBvid = bvid;
  renderSelectionViews();
}

function currentVideoDanmakus() {
  return getVideoRows(currentVideo());
}

function applyActiveBlockWords(rows) {
  if (!activeBlockWords.length) return rows;
  const words = activeBlockWords.map((word) => String(word || "").trim().toLowerCase()).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter((row) => {
    const content = String(row.content || "").toLowerCase();
    return !words.some((word) => content.includes(word));
  });
}

function setActiveBlockWords(words) {
  activeBlockWords = Array.isArray(words)
    ? words.map((word) => String(word || "").trim()).filter(Boolean)
    : [];
  invalidateStatsCache();
}
