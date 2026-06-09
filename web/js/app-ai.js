function compactVideoForAi(video) {
  if (!video) return {};
  return {
    bvid: video.bvid || "",
    title: video.title || "",
    owner: video.owner || "",
    desc: getVideoDescription(video),
    view: metricValue(video, "view"),
    like: metricValue(video, "like"),
    favorite: metricValue(video, "favorite"),
    coin: metricValue(video, "coin"),
    danmaku: metricValue(video, "danmaku"),
    duration: metricValue(video, "duration"),
  };
}

function sampleRows(rows, limit) {
  if (!Array.isArray(rows) || rows.length <= limit) return rows || [];
  const picked = [];
  const step = rows.length / limit;
  for (let i = 0; i < limit; i += 1) {
    picked.push(rows[Math.floor(i * step)]);
  }
  return picked;
}

function normalizePhrase(content) {
  return String(content || "")
    .replace(/\s+/g, "")
    .replace(/[!！?？。,.，、~～；;:："'“”‘’（）()[\]{}<>《》]/g, "")
    .slice(0, 40);
}

function buildPhraseCandidates(rows, limit = 80, scanLimit = AI_PHRASE_SCAN_LIMIT) {
  const counter = {};
  const examples = {};
  sampleRows(rows, scanLimit).forEach((row) => {
    const original = String(row?.content || "").trim();
    const text = normalizePhrase(original);
    if (text.length < 3) return;
    counter[text] = (counter[text] || 0) + 1;
    if (!examples[text]) examples[text] = original;
  });
  return Object.entries(counter)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([text, value]) => ({ text, value, example: examples[text] || text }));
}

function buildAiSamples(rows, timeSeries, limit = 120) {
  const samples = [];
  const seen = new Set();
  const push = (text) => {
    const value = String(text || "").trim().slice(0, 120);
    if (!value || seen.has(value)) return;
    seen.add(value);
    samples.push(value);
  };

  const peakMinutes = (timeSeries?.values || [])
    .map((value, minute) => ({ value, minute }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 3)
    .map((item) => item.minute);
  const peakSet = new Set(peakMinutes);
  for (const row of rows || []) {
    if (samples.length >= Math.floor(limit / 2)) break;
    const minute = Math.floor(Number(row.time_in_video || 0) / 60);
    if (peakSet.has(minute)) push(row.content);
  }

  sampleRows(rows, Math.ceil(limit / 2)).forEach((row) => push(row?.content));
  return samples.slice(0, limit);
}

function buildAiMetrics(rows, video, words, timeSeries) {
  let totalLength = 0;
  let maxLength = 0;
  const users = new Set();
  (rows || []).forEach((row) => {
    const content = String(row.content || "");
    totalLength += content.length;
    maxLength = Math.max(maxLength, content.length);
    if (row.user_hash) users.add(String(row.user_hash));
  });
  const values = timeSeries?.values || [];
  let peakMinute = 0;
  let peakValue = 0;
  values.forEach((value, index) => {
    if (value > peakValue) {
      peakValue = value;
      peakMinute = index;
    }
  });
  const count = rows?.length || 0;
  return {
    danmaku_count: count,
    unique_users: users.size,
    avg_length: count ? Number((totalLength / count).toFixed(1)) : 0,
    max_length: maxLength,
    peak_minute: peakMinute,
    peak_count: peakValue,
    top_words: (words || []).slice(0, 10),
    duration: metricValue(video, "duration"),
    view: metricValue(video, "view"),
    like: metricValue(video, "like"),
    coin: metricValue(video, "coin"),
    favorite: metricValue(video, "favorite"),
  };
}

function aiModeConfig(mode) {
  if (mode === "deep") {
    return { sourceMode: "deep-summary", phraseLimit: 160, sampleLimit: 260, scanLimit: 120000 };
  }
  if (mode === "full_raw") {
    return { sourceMode: "full-raw", phraseLimit: 220, sampleLimit: 320, scanLimit: 200000 };
  }
  return { sourceMode: "summary-samples", phraseLimit: 80, sampleLimit: 120, scanLimit: AI_PHRASE_SCAN_LIMIT };
}

function getAiAnalysisMode() {
  const mode = byId("aiAnalysisMode")?.value || "economy";
  return ["economy", "deep", "full_raw"].includes(mode) ? mode : "economy";
}

function normalizeAiRequirementText(value) {
  return String(value || "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getAiRequirement(scope) {
  const id = scope === "compare" ? "aiCompareRequirement" : "aiCurrentRequirement";
  const text = normalizeAiRequirementText(byId(id)?.value || "");
  if (text.length > AI_USER_REQUIREMENT_MAX_CHARS) {
    throw new Error(`AI 分析要求最多 ${AI_USER_REQUIREMENT_MAX_CHARS} 个字符。`);
  }
  return text;
}

function updateAiRequirementCount(scope) {
  const inputId = scope === "compare" ? "aiCompareRequirement" : "aiCurrentRequirement";
  const countId = scope === "compare" ? "aiCompareRequirementCount" : "aiCurrentRequirementCount";
  const input = byId(inputId);
  const count = byId(countId);
  if (!input || !count) return;
  const length = normalizeAiRequirementText(input.value).length;
  count.textContent = `${Math.min(length, AI_USER_REQUIREMENT_MAX_CHARS)}/${AI_USER_REQUIREMENT_MAX_CHARS}`;
}

function aiModeLabel(mode) {
  return {
    economy: "省钱模式",
    deep: "深度摘要",
    full_raw: "全量原文",
  }[mode] || "省钱模式";
}

function compactDanmakusForAi(rows) {
  return (rows || []).map((row) => ({
    time_in_video: Number(row.time_in_video || 0),
    send_timestamp: Number(row.send_timestamp || 0),
    content: String(row.content || "").slice(0, 140),
  }));
}

function buildAiDataset(video, label = "当前", mode = getAiAnalysisMode()) {
  const stats = getVideoStats(video);
  const rows = stats.rows;
  const config = aiModeConfig(mode);
  const words = getCachedWordStats(video, 80);
  const timeSeries = stats.timeSeries;
  const lengthBuckets = stats.lengthBuckets;
  const dataset = {
    label,
    analysis_mode: mode,
    video: compactVideoForAi(video),
    metrics: buildAiMetrics(rows, video, words, timeSeries),
    words,
    length_buckets: lengthBuckets,
    time_series: timeSeries,
    phrase_candidates: buildPhraseCandidates(rows, config.phraseLimit, config.scanLimit),
    danmaku_samples: buildAiSamples(rows, timeSeries, config.sampleLimit),
    source: {
      mode: config.sourceMode,
      danmaku_count: rows.length,
      max_local_danmaku_rows: MAX_LOCAL_DANMAKU_ROWS,
    },
  };
  if (mode === "full_raw") {
    if (rows.length > AI_FULL_RAW_MAX_ROWS) {
      throw new Error(`全量原文模式最多支持 ${formatNumber(AI_FULL_RAW_MAX_ROWS)} 条弹幕。当前为 ${formatNumber(rows.length)} 条，请改用深度摘要模式。`);
    }
    dataset.danmakus = compactDanmakusForAi(rows);
  }
  return dataset;
}

function setAiText(id, text, isError = false) {
  const el = byId(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

async function requestAiAnalysis(payload) {
  if (payload.analysis_mode === "full_raw") {
    const bytes = new TextEncoder().encode(JSON.stringify(payload)).length;
    if (bytes > AI_FULL_RAW_MAX_BYTES) {
      throw new Error(`全量原文请求约 ${formatBytes(bytes)}，超过当前安全上限 ${formatBytes(AI_FULL_RAW_MAX_BYTES)}。请改用深度摘要模式。`);
    }
  }
  return requestJson(API_ENDPOINTS.aiAnalyze, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

function confirmFullRawMode(mode) {
  if (mode !== "full_raw") return true;
  return window.confirm("全量原文模式会把当前已加载弹幕原文提交给模型服务，可能明显增加等待时间和 API 费用。是否继续？");
}

function aiResultText(result) {
  const prefix = result.cached ? "本次使用缓存结果，未调用外部模型 API。\n\n" : "";
  return prefix + (result.text || "AI 分析完成，但没有返回文字内容。");
}

async function evaluateCurrentVideo(forceRefresh = false) {
  const video = currentVideo();
  scrollToSection("aiCurrentTextPanel");
  if (!video) {
    setAiText("aiCurrentText", "请先选择一个视频后再进行 AI 评价。", true);
    renderTaskState("currentAi", {
      title: "当前视频 AI 评价",
      status: "failed",
      progress: 100,
      message: "未选择视频",
      events: [taskEvent("请先选择一个视频", "error")],
    });
    return;
  }
  const mode = getAiAnalysisMode();
  let userRequirement = "";
  try {
    userRequirement = getAiRequirement("current");
  } catch (err) {
    setAiText("aiCurrentText", err.message, true);
    return;
  }
  if (!confirmFullRawMode(mode)) return;
  const events = [taskEvent(`准备使用${aiModeLabel(mode)}分析当前视频`)];
  if (userRequirement) events.push(taskEvent("已带入用户填写的分析关注点"));
  renderTaskState("currentAi", {
    title: "当前视频 AI 评价",
    status: "running",
    progress: 10,
    message: "正在整理弹幕摘要和视频指标",
    metrics: [["模式", aiModeLabel(mode)], ["视频", videoLabel(video)], ["要求", userRequirement ? "有" : "无"]],
    events,
  });
  setAiText("aiCurrentText", `正在使用${aiModeLabel(mode)}分析当前视频...`);
  try {
    await nextPaint();
    await ensureVideoDanmakusLoaded(video);
    const dataset = buildAiDataset(video, "当前", mode);
    events.push(taskEvent(`已整理 ${formatNumber(dataset.metrics.danmaku_count)} 条弹幕的摘要数据`));
    renderTaskState("currentAi", {
      title: "当前视频 AI 评价",
      status: "running",
      progress: 38,
      message: "摘要已生成，正在提交 AI 分析请求",
      metrics: [["模式", aiModeLabel(mode)], ["弹幕", formatNumber(dataset.metrics.danmaku_count)], ["唯一用户", formatNumber(dataset.metrics.unique_users)]],
      events,
    });
    await nextPaint();
    const result = await requestAiAnalysis({
      scope: "current",
      analysis_mode: mode,
      force_refresh: Boolean(forceRefresh),
      user_requirement: userRequirement,
      ...dataset,
    });
    events.push(taskEvent(result.cached ? "命中缓存，未调用外部模型" : "AI 分析结果已返回"));
    applyAiWordStats(video, result);
    renderTaskState("currentAi", {
      title: "当前视频 AI 评价",
      status: "success",
      progress: 100,
      message: result.cached ? "已使用缓存评价" : "AI 评价完成",
      metrics: [["模式", aiModeLabel(mode)], ["词云词数", formatNumber((result.words || []).length)], ["缓存", result.cached ? "是" : "否"]],
      events,
    });
    setAiText("aiCurrentText", aiResultText(result));
  } catch (err) {
    events.push(taskEvent(err.message, "error"));
    renderTaskState("currentAi", {
      title: "当前视频 AI 评价",
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["模式", aiModeLabel(mode)], ["视频", videoLabel(video)]],
      events,
    });
    setAiText("aiCurrentText", err.message, true);
  }
}

function applyAiWordStats(video, result) {
  if (!video?.bvid || !Array.isArray(result.words) || result.words.length === 0) return;
  aiWordStatsByBvid[video.bvid] = result.words
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item && item.name && Number(item.value) > 0)
    .sort((left, right) => Number(right.item.value) - Number(left.item.value) || left.index - right.index)
    .slice(0, 30)
    .map(({ item }) => ({ name: String(item.name), value: Number(item.value) }));
  renderWordChart();
}

async function evaluateCompareVideos(forceRefresh = false) {
  scrollToSection("aiCompareTextPanel");
  const mode = getAiAnalysisMode();
  let userRequirement = "";
  try {
    userRequirement = getAiRequirement("compare");
  } catch (err) {
    setAiText("aiCompareText", err.message, true);
    return;
  }
  if (compareVideos.length === 0) {
    setAiText("aiCompareText", "请先添加至少一个视频到对比列表。", true);
    renderTaskState("compareAi", {
      title: "对比视频 AI 评价",
      status: "failed",
      progress: 100,
      message: "对比列表为空",
      events: [taskEvent("请先添加至少一个视频到对比列表", "error")],
    });
    return;
  }
  if (!confirmFullRawMode(mode)) return;
  let datasets;
  const events = [taskEvent(`准备使用${aiModeLabel(mode)}分析对比视频`)];
  if (userRequirement) events.push(taskEvent("已带入用户填写的对比关注点"));
  renderTaskState("compareAi", {
    title: "对比视频 AI 评价",
    status: "running",
    progress: 10,
    message: "正在整理 A/B 视频的弹幕摘要",
    metrics: [["模式", aiModeLabel(mode)], ["视频数", formatNumber(compareVideos.length)], ["要求", userRequirement ? "有" : "无"]],
    events,
  });
  try {
    await nextPaint();
    await Promise.all(compareVideos.map((video) => ensureVideoDanmakusLoaded(video)));
    datasets = compareVideos.map((video, index) => buildAiDataset(video, index === 0 ? "A" : "B", mode));
  } catch (err) {
    events.push(taskEvent(err.message, "error"));
    renderTaskState("compareAi", {
      title: "对比视频 AI 评价",
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["模式", aiModeLabel(mode)], ["视频数", formatNumber(compareVideos.length)]],
      events,
    });
    setAiText("aiCompareText", err.message, true);
    return;
  }
  const totalRows = datasets.reduce((sum, item) => sum + Number(item.metrics?.danmaku_count || 0), 0);
  events.push(taskEvent(`已整理 ${formatNumber(totalRows)} 条弹幕的对比摘要`));
  renderTaskState("compareAi", {
    title: "对比视频 AI 评价",
    status: "running",
    progress: 40,
    message: "摘要已生成，正在提交 AI 对比请求",
    metrics: [["模式", aiModeLabel(mode)], ["视频数", formatNumber(datasets.length)], ["弹幕", formatNumber(totalRows)]],
    events,
  });
  setAiText("aiCompareText", `正在使用${aiModeLabel(mode)}分析 A/B 视频差异...`);
  try {
    await nextPaint();
    const result = await requestAiAnalysis({
      scope: "compare",
      analysis_mode: mode,
      force_refresh: Boolean(forceRefresh),
      user_requirement: userRequirement,
      datasets,
    });
    events.push(taskEvent(result.cached ? "命中缓存，未调用外部模型" : "AI 对比分析结果已返回"));
    renderTaskState("compareAi", {
      title: "对比视频 AI 评价",
      status: "success",
      progress: 100,
      message: result.cached ? "已使用缓存评价" : "AI 对比评价完成",
      metrics: [["模式", aiModeLabel(mode)], ["视频数", formatNumber(datasets.length)], ["缓存", result.cached ? "是" : "否"]],
      events,
    });
    setAiText("aiCompareText", aiResultText(result));
  } catch (err) {
    events.push(taskEvent(err.message, "error"));
    renderTaskState("compareAi", {
      title: "对比视频 AI 评价",
      status: "failed",
      progress: 100,
      message: err.message,
      metrics: [["模式", aiModeLabel(mode)], ["视频数", formatNumber(datasets.length)]],
      events,
    });
    setAiText("aiCompareText", err.message, true);
  }
}
