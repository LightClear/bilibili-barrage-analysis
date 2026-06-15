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

function aiRowTime(row) {
  const value = Number(row?.time_in_video || 0);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function aiAnchor(row) {
  return {
    time: Number(aiRowTime(row).toFixed(3)),
    text: String(row?.content || "").trim().slice(0, 160),
  };
}

function buildEvidenceReportForAi(rows, words = [], metrics = {}) {
  const cleaned = (rows || [])
    .filter((row) => String(row?.content || "").trim())
    .sort((left, right) => aiRowTime(left) - aiRowTime(right));
  const claims = [];
  const uniqueUsers = new Set(cleaned.map((row) => String(row.user_hash || "")).filter(Boolean));

  (words || []).slice(0, 4).forEach((word) => {
    const keyword = String(word?.name || "").trim();
    if (!keyword) return;
    const lowerKeyword = keyword.toLowerCase();
    const anchors = cleaned
      .filter((row) => String(row.content || "").toLowerCase().includes(lowerKeyword))
      .slice(0, 5)
      .map(aiAnchor);
    if (!anchors.length) return;
    claims.push({
      type: "keyword",
      title: `关键词证据：${keyword}`,
      keyword,
      evidence_count: anchors.length,
      confidence: Math.min(0.95, 0.35 + anchors.length / Math.max(cleaned.length, 1)),
      anchors,
    });
  });

  const peakMinute = Number(metrics?.peak_minute || 0);
  const peakStart = Math.max(0, Math.floor(peakMinute) * 60);
  const peakAnchors = cleaned
    .filter((row) => aiRowTime(row) >= peakStart && aiRowTime(row) < peakStart + 60)
    .slice(0, 5)
    .map(aiAnchor);
  if (peakAnchors.length) {
    claims.push({
      type: "peak",
      title: `峰值证据：${formatTime(peakStart)}-${formatTime(peakStart + 60)}`,
      start: peakStart,
      end: peakStart + 60,
      evidence_count: peakAnchors.length,
      confidence: Math.min(0.95, 0.35 + peakAnchors.length / Math.max(cleaned.length, 1)),
      anchors: peakAnchors,
    });
  }

  return {
    summary: {
      sample_count: cleaned.length,
      unique_users: uniqueUsers.size,
      keyword_count: (words || []).length,
    },
    claims: claims.slice(0, 6),
  };
}

function buildHighlightTimelineForAi(rows, words = [], segmentSeconds = 60, maxSegments = 5) {
  const cleaned = (rows || [])
    .filter((row) => String(row?.content || "").trim())
    .sort((left, right) => aiRowTime(left) - aiRowTime(right));
  const keywords = (words || []).slice(0, 10).map((word) => String(word?.name || "").trim()).filter(Boolean);
  const bucketSize = Math.max(10, Number(segmentSeconds || 60));
  const buckets = new Map();
  cleaned.forEach((row) => {
    const start = Math.floor(aiRowTime(row) / bucketSize) * bucketSize;
    if (!buckets.has(start)) buckets.set(start, []);
    buckets.get(start).push(row);
  });

  return Array.from(buckets.entries())
    .map(([start, bucketRows]) => {
      const keywordHits = keywords
        .map((keyword) => ({
          keyword,
          count: bucketRows.filter((row) => String(row.content || "").toLowerCase().includes(keyword.toLowerCase())).length,
        }))
        .filter((item) => item.count > 0)
        .sort((left, right) => right.count - left.count)
        .slice(0, 3);
      const uniqueUsers = new Set(bucketRows.map((row) => String(row.user_hash || "")).filter(Boolean)).size;
      const score = bucketRows.length * 10 + keywordHits.reduce((sum, item) => sum + item.count * 6, 0) + uniqueUsers * 2;
      const topKeywords = keywordHits.map((item) => item.keyword);
      return {
        start,
        end: start + bucketSize,
        title: topKeywords.length ? `${formatTime(start)} ${topKeywords[0]} 高能段` : `${formatTime(start)} 弹幕集中段`,
        score,
        danmaku_count: bucketRows.length,
        unique_users: uniqueUsers,
        keywords: topKeywords,
        reason: topKeywords.length
          ? `${formatNumber(bucketRows.length)} 条弹幕集中出现，关键词 ${topKeywords.slice(0, 2).join("、")} 较突出。`
          : `${formatNumber(bucketRows.length)} 条弹幕集中出现，适合回看画面内容。`,
        samples: bucketRows.slice(0, 4).map(aiAnchor),
      };
    })
    .sort((left, right) => right.score - left.score || left.start - right.start)
    .slice(0, maxSegments);
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
    evidence_report: buildEvidenceReportForAi(rows, words, buildAiMetrics(rows, video, words, timeSeries)),
    highlight_timeline: buildHighlightTimelineForAi(rows, words),
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

function renderAiMarkdown(text) {
  if (!text) return "";

  const lines = String(text).split("\n");
  const out = [];
  const context = { list: null, index: 0 };

  function closeList() {
    if (context.list === "ul") { out.push("</ul>"); context.list = null; }
    if (context.list === "ol") { out.push("</ol>"); context.list = null; }
  }

  function pushBlock(tag, content, extraClass = "") {
    closeList();
    const cls = extraClass ? ` class="${extraClass}"` : "";
    out.push(`<${tag}${cls}>${content}</${tag}>`);
  }

  for (let i = context.index; i < lines.length; i += 1) {
    context.index = i;
    let raw = lines[i];
    // Detect indent for nested content
    const indent = raw.match(/^(\s*)/)[1].length;

    // Trim trailing spaces but preserve structure
    const trimmed = raw.trim();
    if (!trimmed) {
      closeList();
      continue;
    }

    // Inline formatting helper
    const fmt = (s) =>
      escapeHtml(s)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Horizontal rule
    if (/^[-*_]{3,}$/.test(trimmed)) {
      closeList();
      out.push('<hr class="ai-hr">');
      continue;
    }

    // Heading
    const hMatch = trimmed.match(/^(#{1,3})\s+(.+)/);
    if (hMatch) {
      const level = Math.min(hMatch[1].length, 3);
      closeList();
      out.push(`<h${level + 1} class="ai-h">${fmt(hMatch[2])}</h${level + 1}>`);
      continue;
    }

    // Blockquote
    if (trimmed.startsWith("> ")) {
      closeList();
      const quoteLines = [];
      let j = i;
      while (j < lines.length) {
        const qLine = lines[j].trim();
        if (qLine.startsWith("> ")) {
          quoteLines.push(fmt(qLine.slice(2)));
          j += 1;
        } else if (!qLine && j + 1 < lines.length && lines[j + 1].trim().startsWith("> ")) {
          j += 1;
        } else {
          break;
        }
      }
      out.push(`<blockquote class="ai-quote"><p>${quoteLines.join("<br>")}</p></blockquote>`);
      i = j - 1;
      continue;
    }

    // Unordered list
    const ulMatch = trimmed.match(/^[-*]\s+(.+)/);
    if (ulMatch) {
      if (context.list !== "ul") { closeList(); out.push('<ul class="ai-ul">'); context.list = "ul"; }
      out.push(`<li>${fmt(ulMatch[1])}</li>`);
      continue;
    }

    // Ordered list
    const olMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
    if (olMatch) {
      if (context.list !== "ol") { closeList(); out.push('<ol class="ai-ol">'); context.list = "ol"; }
      out.push(`<li>${fmt(olMatch[2])}</li>`);
      continue;
    }

    // Regular paragraph — merge consecutive non-empty non-special lines
    closeList();
    const paraLines = [fmt(trimmed)];
    let k = i + 1;
    while (k < lines.length) {
      const nxt = lines[k].trim();
      if (!nxt) break;
      if (/^[-*_]{3,}$/.test(nxt) || /^#{1,3}\s/.test(nxt) || nxt.startsWith("> ")
        || /^[-*]\s/.test(nxt) || /^\d+\.\s/.test(nxt)) break;
      paraLines.push(fmt(nxt));
      k += 1;
    }
    out.push(`<p>${paraLines.join("<br>")}</p>`);
    i = k - 1;
  }

  closeList();
  return out.join("\n");
}

function setAiResultHtml(id, markdownText) {
  const el = byId(id);
  if (!el) return;
  const html = renderAiMarkdown(markdownText);
  el.innerHTML = html;
  el.classList.remove("is-error");
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

function renderAiEvidenceReport(report) {
  const box = byId("aiEvidenceReport");
  if (!box) return;
  const claims = Array.isArray(report?.claims) ? report.claims.slice(0, 6) : [];
  if (!claims.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = `
    <div class="ai-insight-head ai-reveal">
      <h3>证据链</h3>
      <span>${formatNumber(report?.summary?.sample_count || 0)} 条样本</span>
    </div>
    <div class="ai-evidence-grid">
      ${claims.map((claim, i) => `
        <article class="ai-evidence-card ai-reveal" style="animation-delay:${0.08 + i * 0.07}s">
          <span class="ai-evidence-kicker">${escapeHtml(claim.type || "evidence")}</span>
          <div class="ai-evidence-card-head">
            <strong>${escapeHtml(claim.title || claim.keyword || claim.type || "证据")}</strong>
            <span>${Math.round(Number(claim.confidence || 0) * 100)}%</span>
          </div>
          <div class="ai-anchor-list">
            ${(claim.anchors || []).slice(0, 4).map((anchor, j) => `
              <p style="animation-delay:${0.12 + i * 0.07 + j * 0.04}s"><span>${formatTime(anchor.time)}</span>${escapeHtml(anchor.text || "")}</p>
            `).join("")}
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderAiHighlightTimeline(timeline) {
  const box = byId("aiHighlightTimeline");
  if (!box) return;
  const segments = Array.isArray(timeline) ? timeline.slice(0, 5) : [];
  if (!segments.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = `
    <div class="ai-insight-head ai-reveal">
      <h3>高能片段时间线</h3>
      <span>${segments.length} 段</span>
    </div>
    <div class="ai-highlight-list">
      ${segments.map((segment, i) => `
        <article class="ai-highlight-item ai-reveal" style="animation-delay:${0.1 + i * 0.09}s">
          <div class="ai-highlight-time">
            <strong>${formatTime(segment.start)}-${formatTime(segment.end)}</strong>
            <span>${formatNumber(segment.score || 0)}</span>
          </div>
          <div class="ai-highlight-body">
            <div class="ai-highlight-meta">
              <span>${formatNumber(segment.danmaku_count || 0)} 条弹幕</span>
              <span>${formatNumber(segment.unique_users || 0)} 位用户</span>
            </div>
            <h4>${escapeHtml(segment.title || "高能片段")}</h4>
            <p>${escapeHtml(segment.reason || "")}</p>
            <div class="ai-highlight-tags">
              ${(segment.keywords || []).slice(0, 4).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("")}
            </div>
            <div class="ai-anchor-list">
              ${(segment.samples || []).slice(0, 3).map((sample, j) => `
                <p style="animation-delay:${0.14 + i * 0.09 + j * 0.04}s"><span>${formatTime(sample.time)}</span>${escapeHtml(sample.text || "")}</p>
              `).join("")}
            </div>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function clearCurrentAiInsights() {
  renderAiEvidenceReport(null);
  renderAiHighlightTimeline(null);
}

async function evaluateCurrentVideo(forceRefresh = false) {
  const video = currentVideo();
  scrollToSection("aiCurrentTextPanel");
  clearCurrentAiInsights();
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
    setAiResultHtml("aiCurrentText", aiResultText(result));
    renderAiEvidenceReport(result.evidence_report);
    renderAiHighlightTimeline(result.highlight_timeline);
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
    clearCurrentAiInsights();
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
    setAiResultHtml("aiCompareText", aiResultText(result));
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
