const charts = {};
let statsCache = new Map();
let statsDataVersion = 0;
let compareChartInstances = new Map();
let chartResizeTimer = null;
let crossVideoPayload = null;
let crossVideoLoading = false;

function buildTimeSeries(rows, duration = 0) {
  const counts = {};
  let maxMinute = Math.max(0, Math.ceil(Number(duration || 0) / 60));
  rows.forEach((row) => {
    const minute = Math.floor(Number(row.time_in_video || 0) / 60);
    maxMinute = Math.max(maxMinute, minute);
    counts[minute] = (counts[minute] || 0) + 1;
  });
  const minutes = Array.from({ length: maxMinute + 1 }, (_, index) => index);
  return {
    labels: minutes.map((minute) => `${minute}分`),
    values: minutes.map((minute) => counts[minute] || 0),
  };
}

function buildLengthBuckets(rows) {
  const buckets = { "1-5": 0, "6-10": 0, "11-20": 0, "20+": 0 };
  rows.forEach((row) => {
    const len = String(row.content || "").length;
    if (len <= 5) buckets["1-5"] += 1;
    else if (len <= 10) buckets["6-10"] += 1;
    else if (len <= 20) buckets["11-20"] += 1;
    else buckets["20+"] += 1;
  });
  return buckets;
}

const STOP_WORDS = new Set([
  "这个", "那个", "就是", "不是", "什么", "怎么", "还是", "可以", "没有", "真的",
  "感觉", "因为", "所以", "但是", "视频", "一个", "大家", "自己", "现在", "已经",
]);

function tokenizeDanmaku(text) {
  const matches = String(text || "").match(/[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}/g) || [];
  const tokens = [];
  matches.forEach((part) => {
    if (/^[A-Za-z0-9]+$/.test(part)) {
      if (part.length >= 2) tokens.push(part.toLowerCase());
      return;
    }
    if (part.length <= 4) {
      tokens.push(part);
      return;
    }
    for (let i = 0; i <= part.length - 2; i += 1) {
      tokens.push(part.slice(i, i + 2));
    }
  });
  return tokens.filter((token) => token.length >= 2 && !STOP_WORDS.has(token));
}

function buildWordStats(rows, limit = 30) {
  const counter = {};
  rows.forEach((row) => {
    tokenizeDanmaku(row.content).forEach((token) => {
      counter[token] = (counter[token] || 0) + 1;
    });
  });
  return Object.entries(counter)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([name, value]) => ({ name, value }));
}

function buildUserStats(rows, limit = 20) {
  const counter = {};
  rows.forEach((row) => {
    const userHash = String(row.user_hash || "");
    if (userHash) counter[userHash] = (counter[userHash] || 0) + 1;
  });
  return Object.entries(counter)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([userHash, count]) => ({ userHash, count }));
}

function blockWordsSignature(words) {
  return (Array.isArray(words) ? words : [])
    .map((word) => String(word || "").trim().toLowerCase())
    .filter(Boolean)
    .join("\n");
}

function activeBlockWordsSignature() {
  return blockWordsSignature(typeof activeBlockWords !== "undefined" ? activeBlockWords : []);
}

function normalizeServerTimeSeries(value) {
  if (!value || !Array.isArray(value.labels) || !Array.isArray(value.values)) return null;
  const labels = value.labels.map((label) => String(label));
  const values = value.values.map((item) => Number(item || 0));
  if (labels.length !== values.length) return null;
  return { labels, values };
}

function normalizeServerLengthBuckets(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entries = Object.entries(value)
    .map(([name, count]) => [String(name), Number(count || 0)])
    .filter(([name]) => Boolean(name));
  if (!entries.length) return null;
  return Object.fromEntries(entries);
}

function normalizeServerWords(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => ({ name: String(item?.name || "").trim(), value: Number(item?.value || 0) }))
    .filter((item) => item.name && item.value > 0);
}

function normalizeServerUserRows(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => ({
      userHash: String(item?.userHash || item?.user_hash || ""),
      count: Number(item?.count || 0),
    }))
    .filter((item) => item.userHash && item.count > 0);
}

function getUsableServerStats(video) {
  const stats = video?.stats;
  if (!stats || stats.source !== "server") return null;
  if (String(stats.filter_signature || "") !== activeBlockWordsSignature()) return null;
  const timeSeries = normalizeServerTimeSeries(stats.time_series);
  const lengthBuckets = normalizeServerLengthBuckets(stats.length_buckets);
  if (!timeSeries || !lengthBuckets) return null;
  return {
    timeSeries,
    lengthBuckets,
    words: normalizeServerWords(stats.word_cloud),
    userRows: normalizeServerUserRows(stats.user_rank),
  };
}

function videoStatsCacheKey(video) {
  const bvid = String(video?.bvid || "");
  const cid = String(video?.cid || "");
  const title = String(video?.title || "");
  const duration = metricValue(video, "duration");
  const statsSignature = String(video?.stats?.filter_signature || "");
  return `${statsDataVersion}|${bvid}|${cid}|${title}|${duration}|${statsSignature}`;
}

function invalidateStatsCache() {
  statsDataVersion += 1;
  statsCache.clear();
}

function getVideoStats(video) {
  const key = videoStatsCacheKey(video);
  if (statsCache.has(key)) return statsCache.get(key);
  const rows = getVideoRows(video);
  const serverStats = getUsableServerStats(video);
  const stats = {
    rows,
    timeSeries: serverStats?.timeSeries || buildTimeSeries(rows, metricValue(video, "duration")),
    lengthBuckets: serverStats?.lengthBuckets || buildLengthBuckets(rows),
    userRows: serverStats?.userRows?.length ? serverStats.userRows : buildUserStats(rows, 20),
    serverWords: serverStats?.words || [],
    wordsByLimit: new Map(),
    sendTimeByMode: new Map(),
  };
  statsCache.set(key, stats);
  return stats;
}

function getCachedWordStats(video, limit = 30) {
  const stats = getVideoStats(video);
  if (stats.serverWords.length) return stats.serverWords.slice(0, limit);
  if (!stats.wordsByLimit.has(limit)) {
    stats.wordsByLimit.set(limit, buildWordStats(stats.rows, limit));
  }
  return stats.wordsByLimit.get(limit);
}

function getCachedSendTimeDistribution(video, mode = "auto") {
  const stats = getVideoStats(video);
  if (!stats.sendTimeByMode.has(mode)) {
    stats.sendTimeByMode.set(mode, buildSendTimeDistribution(stats.rows, mode));
  }
  return stats.sendTimeByMode.get(mode);
}

function disposeCompareCharts() {
  compareChartInstances.forEach((chart) => chart.dispose());
  compareChartInstances.clear();
}

function createCompareChart(id) {
  const el = byId(id);
  if (!el) return null;
  const cached = compareChartInstances.get(id);
  if (cached && cached.getDom && cached.getDom() === el && !(cached.isDisposed && cached.isDisposed())) return cached;
  if (cached) cached.dispose();
  const chart = echarts.getInstanceByDom(el) || echarts.init(el);
  compareChartInstances.set(id, chart);
  return chart;
}

function initCharts() {
  charts.time = echarts.init(byId("timeChart"));
  charts.sendTime = echarts.init(byId("sendTimeChart"));
  charts.length = echarts.init(byId("lengthChart"));
  charts.word = echarts.init(byId("wordChart"));
  if (byId("keywordSankeyChart")) charts.keywordSankey = echarts.init(byId("keywordSankeyChart"));
  if (byId("themeRiverChart")) charts.themeRiver = echarts.init(byId("themeRiverChart"));

  const rankBox = byId("rankChart");
  rankBox.addEventListener("scroll", () => {
    rankScrollTop = rankBox.scrollTop;
  });
  rankBox.addEventListener("click", (event) => {
    const item = event.target.closest(".rank-video-item");
    if (!item) return;
    rankScrollTop = rankBox.scrollTop;
    const video = findDashboardVideo(item.dataset.bvid) || findVideo(item.dataset.bvid);
    if (!video) return;
    focusBvid = video.bvid;
    selectedBvid = video.bvid;
    markActiveRankItem();
    renderSelectionViews();
    ensureVideoDanmakusLoaded(video).then(() => {
      if (getCurrentBvid() === video.bvid) renderSelectionViews();
    }).catch((err) => {
      const summary = byId("searchSummary");
      if (summary && getCurrentBvid() === video.bvid) summary.textContent = `弹幕加载失败：${err.message}`;
    });
  });

  window.addEventListener("resize", () => {
    clearTimeout(chartResizeTimer);
    chartResizeTimer = setTimeout(() => {
      chartResizeTimer = null;
      resizeAllCharts();
    }, 160);
  });
}

function resizeAllCharts() {
  Object.values(charts).forEach((chart) => chart.resize());
  compareChartInstances.forEach((chart) => chart.resize());
}

async function renderCrossVideoPanel(options = {}) {
  const status = byId("crossVideoStatus");
  if (!charts.keywordSankey || !charts.themeRiver) return;
  if (crossVideoPayload && !options.force) {
    drawCrossVideoCharts(crossVideoPayload);
    return;
  }
  if (crossVideoLoading) return;
  crossVideoLoading = true;
  if (status) status.textContent = "正在读取最近 14 天归档数据";
  try {
    const payload = await requestJson(`${API_ENDPOINTS.crossVideoKeywords}?days=14&top_k=30&row_limit=5000`);
    if (!payload?.ok) throw new Error(payload?.error || "跨视频数据加载失败");
    crossVideoPayload = payload;
    drawCrossVideoCharts(payload);
    if (status) status.textContent = `已读取 ${formatNumber(payload.meta?.archive_days)} 天归档数据`;
  } catch (error) {
    if (status) status.textContent = `跨视频数据不可用：${error.message}`;
    charts.keywordSankey.clear();
    charts.themeRiver.clear();
    renderKeywordSamples({});
  } finally {
    crossVideoLoading = false;
  }
}

function drawCrossVideoCharts(payload) {
  const sankey = payload.sankey || { nodes: [], links: [] };
  charts.keywordSankey.setOption({
    tooltip: { trigger: "item" },
    series: [{
      type: "sankey",
      data: sankey.nodes || [],
      links: sankey.links || [],
      nodeAlign: "justify",
      draggable: false,
      emphasis: { focus: "adjacency" },
      label: { color: "rgba(226,232,240,.86)" },
      lineStyle: { color: "gradient", opacity: 0.34 },
    }],
  });
  charts.themeRiver.setOption({
    tooltip: { trigger: "axis" },
    singleAxis: {
      type: "time",
      axisLabel: { color: "rgba(226,232,240,.68)" },
      axisLine: { lineStyle: { color: "rgba(148,163,184,.25)" } },
    },
    series: [{
      type: "themeRiver",
      data: payload.theme_river || [],
      label: { color: "rgba(226,232,240,.82)" },
      emphasis: { itemStyle: { shadowBlur: 12, shadowColor: "rgba(104,245,255,.28)" } },
    }],
  });
  charts.keywordSankey.off("click");
  charts.keywordSankey.on("click", (params) => {
    if (params?.data?.category === "keyword") renderKeywordSamples(payload.samples || {}, params.data.name);
  });
  const firstKeyword = (sankey.nodes || []).find((node) => node.category === "keyword")?.name;
  renderKeywordSamples(payload.samples || {}, firstKeyword);
}

function renderKeywordSamples(samples, activeKeyword = "") {
  const box = byId("keywordSamples");
  if (!box) return;
  const keywords = Object.keys(samples || {});
  if (!keywords.length) {
    box.innerHTML = '<p class="desc">暂无可展示的关键词样本。</p>';
    return;
  }
  const keyword = activeKeyword && samples[activeKeyword] ? activeKeyword : keywords[0];
  const rows = (samples[keyword] || []).slice(0, 6);
  box.innerHTML = `
    <h3>样本弹幕：${escapeHtml(keyword)}</h3>
    <div class="keyword-sample-list">
      ${rows.map((row) => `
        <div class="keyword-sample-item">
          <span>${escapeHtml(row.date || "")}</span>
          <strong>${escapeHtml(row.title || row.bvid || "")}</strong>
          <p>${escapeHtml(row.content || "")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function renderTimeChart() {
  const video = currentVideo();
  const data = getVideoStats(video).timeSeries;
  const endValue = Math.min(data.labels.length - 1, 35);
  const timeDataZoom = data.labels.length > 36 ? [
    {
      type: "slider",
      xAxisIndex: 0,
      startValue: 0,
      endValue,
      height: 14,
      bottom: 8,
      borderColor: "rgba(148,163,184,0.22)",
      fillerColor: "rgba(56,189,248,0.20)",
      handleStyle: { color: "#68f5ff" },
      textStyle: { color: "#94a3b8" },
    },
    {
      type: "inside",
      xAxisIndex: 0,
      startValue: 0,
      endValue,
      zoomOnMouseWheel: false,
      moveOnMouseWheel: true,
    },
  ] : [];
  charts.time.setOption({
    animationDuration: 800,
    tooltip: { trigger: "axis" },
    grid: { left: 42, right: 20, top: 18, bottom: data.labels.length > 36 ? 52 : 32 },
    dataZoom: timeDataZoom,
    xAxis: {
      type: "category",
      data: data.labels,
      boundaryGap: false,
      axisLabel: { color: "#94a3b8", hideOverlap: true },
    },
    yAxis: { type: "value", axisLabel: { color: "#94a3b8" } },
    series: [{
      name: "弹幕数",
      type: "line",
      smooth: true,
      showSymbol: false,
      sampling: "lttb",
      areaStyle: { color: "rgba(56,189,248,0.16)" },
      lineStyle: { width: 3, color: "#38bdf8" },
      data: data.values,
    }],
  }, { replaceMerge: ["dataZoom"] });
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function sendTimeBucketLabel(date, mode) {
  const year = date.getFullYear();
  const month = pad2(date.getMonth() + 1);
  const day = pad2(date.getDate());
  if (mode === "year") return `${year}`;
  if (mode === "month") return `${year}-${month}`;
  if (mode === "day") return `${year}-${month}-${day}`;
  return `${year}-${month}-${day} ${pad2(date.getHours())}:00`;
}

function resolveSendTimeMode(timestamps, selectedMode) {
  if (selectedMode && selectedMode !== "auto") return selectedMode;
  if (timestamps.length <= 1) return "month";
  const spanDays = (timestamps[timestamps.length - 1] - timestamps[0]) / 86400;
  if (spanDays > 3650) return "year";
  if (spanDays > 730) return "month";
  if (spanDays > 3) return "day";
  return "hour";
}

function buildSendTimeDistribution(rows, selectedMode = "auto") {
  const timestamps = (rows || [])
    .map((row) => Number(row.send_timestamp || 0))
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  if (timestamps.length === 0) return { labels: [], values: [], mode: "month" };

  const mode = resolveSendTimeMode(timestamps, selectedMode);
  const counts = {};
  timestamps.forEach((timestamp) => {
    const label = sendTimeBucketLabel(new Date(timestamp * 1000), mode);
    counts[label] = (counts[label] || 0) + 1;
  });
  const labels = Object.keys(counts).sort();
  return {
    labels,
    values: labels.map((label) => counts[label]),
    mode,
  };
}

function syncSendTimeModeButtons() {
  document.querySelectorAll("[data-send-time-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.sendTimeMode === sendTimeMode);
  });
}

function formatSendTimeAxisLabel(value, mode) {
  const text = String(value || "");
  if (mode === "year") return text;
  if (mode === "month") {
    const [year, month] = text.split("-");
    return `${year}\n${month}月`;
  }
  if (mode === "day") {
    const [year, month, day] = text.split("-");
    return `${month}-${day}\n${year}`;
  }
  const [date, hour] = text.split(" ");
  const [, month, day] = String(date || "").split("-");
  return `${month}-${day}\n${hour || ""}`;
}

function renderSendTimeChart() {
  const chart = charts.sendTime;
  if (!chart) return;
  syncSendTimeModeButtons();
  const data = getCachedSendTimeDistribution(currentVideo(), sendTimeMode);
  const unitMap = { year: "年", month: "月", day: "日", hour: "小时" };
  const unit = unitMap[data.mode] || "月";
  const defaultWindowMap = { year: 19, month: 35, day: 45, hour: 47 };
  const defaultWindow = defaultWindowMap[data.mode] || 35;
  const endValue = Math.min(data.labels.length - 1, defaultWindow);
  const zoom = data.labels.length > defaultWindow + 1 ? [
    {
      type: "slider",
      xAxisIndex: 0,
      startValue: 0,
      endValue,
      height: 14,
      bottom: 8,
      borderColor: "rgba(148,163,184,0.22)",
      fillerColor: "rgba(251,191,36,0.22)",
      handleStyle: { color: "#fbbf24" },
      textStyle: { color: "#94a3b8" },
    },
    {
      type: "inside",
      xAxisIndex: 0,
      startValue: 0,
      endValue,
      zoomOnMouseWheel: false,
      moveOnMouseWheel: true,
    },
  ] : [];

  chart.setOption({
    animationDuration: 800,
    tooltip: {
      trigger: "axis",
      formatter(params) {
        const item = params[0];
        return `${item.axisValue}<br/>发送弹幕：${formatNumber(item.value)} 条`;
      },
    },
    grid: { left: 50, right: 22, top: 24, bottom: data.labels.length > 8 ? 78 : 48 },
    dataZoom: zoom,
    xAxis: {
      type: "category",
      data: data.labels,
      axisLabel: {
        color: "#cbd5e1",
        hideOverlap: true,
        interval: "auto",
        margin: 16,
        lineHeight: 15,
        formatter: (value) => formatSendTimeAxisLabel(value, data.mode),
      },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: "value",
      name: `条/${unit}`,
      nameTextStyle: { color: "#94a3b8" },
      axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,0.12)" } },
    },
    series: [{
      name: "发送弹幕",
      type: "bar",
      data: data.values,
      barMaxWidth: 28,
      itemStyle: {
        borderRadius: [8, 8, 0, 0],
        color: "#fbbf24",
      },
    }],
  }, { replaceMerge: ["dataZoom"] });
}

function renderLengthChart() {
  const buckets = getVideoStats(currentVideo()).lengthBuckets;
  charts.length.setOption({
    animationDuration: 800,
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { color: "#cbd5e1", textBorderWidth: 0 } },
    series: [{
      name: "弹幕长度",
      type: "pie",
      radius: ["42%", "70%"],
      center: ["50%", "45%"],
      label: {
        color: "#e2e8f0",
        fontFamily: "Microsoft YaHei",
        fontSize: 12,
        fontWeight: 700,
        formatter: "{b}\n{c}",
        textBorderWidth: 0,
      },
      labelLine: {
        lineStyle: { color: "rgba(226,232,240,0.55)" },
      },
      emphasis: {
        label: {
          color: "#ffffff",
          fontSize: 13,
          textBorderWidth: 0,
        },
      },
      data: Object.entries(buckets).map(([name, value]) => ({ name, value })),
    }],
  });
}

function renderWordChart() {
  const video = currentVideo();
  const words = (video?.bvid && aiWordStatsByBvid[video.bvid])
    ? aiWordStatsByBvid[video.bvid]
    : getCachedWordStats(video, 30);
  charts.word.setOption({
    animationDuration: 800,
    animationDurationUpdate: 900,
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 24, top: 24, bottom: 80 },
    xAxis: { type: "category", data: words.map((w) => w.name), axisLabel: { color: "#94a3b8", rotate: 35 } },
    yAxis: { type: "value", axisLabel: { color: "#94a3b8" } },
    series: [{ name: "出现次数", type: "bar", data: words.map((w) => w.value), itemStyle: { borderRadius: [10, 10, 0, 0], color: "#a78bfa" } }],
  });
}

function renderUserRanking() {
  const rows = getVideoStats(currentVideo()).userRows;
  const tbody = document.querySelector("#userRankTable tbody");
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty-cell">暂无数据</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row, i) =>
    `<tr><td class="rank-cell">${i + 1}</td><td>${escapeHtml(row.userHash)}</td><td>${formatNumber(row.count)}</td></tr>`
  ).join("");
}

function renderCompareCharts(a, b) {
  const statsA = getVideoStats(a);
  const statsB = getVideoStats(b);
  const activeLegend = [a ? "A" : null, b ? "B" : null].filter(Boolean);

  COMPARE_METRICS.forEach(({ key }) => {
    const chart = createCompareChart(`compareMetricChart_${key}`);
    if (!chart) return;
    chart.setOption({
      animationDuration: 700,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter(params) {
          return params.map((item) => {
            const value = key === "duration" ? formatTime(item.value) : formatNumber(item.value);
            return `${item.name}：${value}`;
          }).join("<br>");
        },
      },
      grid: { left: 34, right: 18, top: 10, bottom: 24 },
      xAxis: {
        type: "value",
        axisLabel: {
          color: "#94a3b8",
          formatter: key === "duration" ? (value) => formatTime(value) : undefined,
        },
        splitLine: { lineStyle: { color: "rgba(148,163,184,0.10)" } },
      },
      yAxis: { type: "category", inverse: true, data: ["A", "B"], axisLabel: { color: "#cbd5e1", fontWeight: 800 } },
      series: [{
        type: "bar",
        barWidth: 16,
        data: [
          { value: a ? metricValue(a, key) : 0, itemStyle: { color: "#38bdf8", borderRadius: [0, 8, 8, 0] } },
          { value: b ? metricValue(b, key) : 0, itemStyle: { color: "#a78bfa", borderRadius: [0, 8, 8, 0] } },
        ],
      }],
    });
  });

  const seriesA = statsA.timeSeries;
  const seriesB = statsB.timeSeries;
  const maxLen = Math.max(seriesA.labels.length, seriesB.labels.length);
  const timeLabels = Array.from({ length: maxLen }, (_, i) => `${i}分`);
  const timeChart = createCompareChart("compareTimeChart");
  if (timeChart) {
    timeChart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: activeLegend, textStyle: { color: "#cbd5e1" } },
      grid: { left: 46, right: 18, top: 42, bottom: maxLen > 30 ? 54 : 32 },
      dataZoom: maxLen > 30 ? [{ type: "slider", xAxisIndex: 0, height: 14, bottom: 8, startValue: 0, endValue: 29 }] : [],
      xAxis: { type: "category", data: timeLabels, axisLabel: { color: "#94a3b8", hideOverlap: true } },
      yAxis: { type: "value", axisLabel: { color: "#94a3b8" } },
      series: [
        a ? { name: "A", type: "line", smooth: true, showSymbol: false, data: timeLabels.map((_, i) => seriesA.values[i] || 0), lineStyle: { color: "#38bdf8", width: 3 }, areaStyle: { color: "rgba(56,189,248,0.12)" } } : null,
        b ? { name: "B", type: "line", smooth: true, showSymbol: false, data: timeLabels.map((_, i) => seriesB.values[i] || 0), lineStyle: { color: "#a78bfa", width: 3 }, areaStyle: { color: "rgba(167,139,250,0.12)" } } : null,
      ].filter(Boolean),
    }, { replaceMerge: ["dataZoom"] });
  }

  const lengthA = statsA.lengthBuckets;
  const lengthB = statsB.lengthBuckets;
  const lengthLabels = Object.keys(lengthA);
  const lengthChart = createCompareChart("compareLengthChart");
  if (lengthChart) {
    lengthChart.setOption({
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: activeLegend, textStyle: { color: "#cbd5e1" } },
      grid: { left: 46, right: 18, top: 42, bottom: 32 },
      xAxis: { type: "category", data: lengthLabels, axisLabel: { color: "#94a3b8" } },
      yAxis: { type: "value", axisLabel: { color: "#94a3b8" } },
      series: [
        a ? { name: "A", type: "bar", data: lengthLabels.map((label) => lengthA[label]), itemStyle: { color: "#38bdf8", borderRadius: [6, 6, 0, 0] } } : null,
        b ? { name: "B", type: "bar", data: lengthLabels.map((label) => lengthB[label]), itemStyle: { color: "#a78bfa", borderRadius: [6, 6, 0, 0] } } : null,
      ].filter(Boolean),
    });
  }
}
