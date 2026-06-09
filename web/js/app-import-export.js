function exportData() {
  const payload = {
    exported_at: new Date().toISOString(),
    popular_videos: dashboardData.raw_videos || [],
    popular_danmakus: danmakus,
    searched_videos: searchedVideos,
    searched_danmakus: searchedDanmakus,
    custom_videos: customVideos,
    custom_danmakus: customDanmakus,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `danmaku_export_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function mergeArray(arr, items, keyFn) {
  const keys = new Set(arr.map(keyFn));
  for (const item of items || []) {
    const key = keyFn(item);
    if (!key) continue;
    if (!keys.has(key)) {
      arr.push(item);
      keys.add(key);
    }
  }
}

const IMPORT_ROOT_KEYS = new Set([
  "exported_at",
  "popular_videos",
  "popular_danmakus",
  "searched_videos",
  "searched_danmakus",
  "custom_videos",
  "custom_danmakus",
  "compare_videos",
]);

const IMPORT_VIDEO_KEYS = new Set([
  "bvid", "aid", "cid", "title", "owner", "cover_url", "pic", "cover", "thumbnail",
  "desc", "description", "introduction", "desc_v2", "view", "views", "like", "likes",
  "favorite", "favorites", "fav", "coin", "coins", "danmaku", "danmaku_count",
  "duration", "length", "rank", "part",
]);

const IMPORT_DANMAKU_KEYS = new Set([
  "bvid", "cid", "title", "time_in_video", "send_timestamp", "send_time_text",
  "user_hash", "content", "color",
]);

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function createImportReport() {
  return { issueCount: 0, issues: [] };
}

function addImportIssue(report, message) {
  report.issueCount += 1;
  if (report.issues.length < 20) report.issues.push(message);
}

function reportUnknownImportFields(raw, allowedKeys, context, report) {
  Object.keys(raw).forEach((key) => {
    if (!allowedKeys.has(key)) addImportIssue(report, `${context} 的未知字段 ${key} 已忽略`);
  });
}

function truncateImportText(value, maxLength, context, field, report, trim = true) {
  if (value === undefined || value === null) return "";
  let text = String(value);
  if (trim) text = text.trim();
  if (text.length > maxLength) {
    addImportIssue(report, `${context}.${field} 超过 ${maxLength} 字符，已截断`);
    text = text.slice(0, maxLength);
  }
  return text;
}

function sanitizeImportBvid(value, context, report, required = false) {
  const bvid = truncateImportText(value, 32, context, "bvid", report);
  if (!bvid) {
    if (required) addImportIssue(report, `${context} 缺少 bvid，已忽略`);
    return "";
  }
  if (!/^BV[0-9A-Za-z]{8,20}$/.test(bvid)) {
    addImportIssue(report, `${context}.bvid 格式异常，已忽略`);
    return "";
  }
  return bvid;
}

function sanitizeImportNumber(value, context, field, report) {
  if (value === undefined || value === null || value === "") return undefined;
  const number = Number(value);
  if (!Number.isFinite(number)) {
    addImportIssue(report, `${context}.${field} 不是有效数字，已忽略`);
    return undefined;
  }
  return Math.max(0, number);
}

function firstDefined(raw, fields) {
  return fields.map((field) => raw[field]).find((value) => value !== undefined && value !== null && value !== "");
}

function sanitizeImportMediaUrl(raw, context, report) {
  const value = firstDefined(raw, ["cover_url", "pic", "cover", "thumbnail"]);
  const url = normalizeMediaUrl(truncateImportText(value, MAX_IMPORT_TEXT_CHARS, context, "cover_url", report));
  if (!url) return "";
  if (/^(https:\/\/|\.\/|\/)/.test(url)) return url;
  addImportIssue(report, `${context}.cover_url 使用了不允许的地址，已忽略`);
  return "";
}

function sanitizeImportDescV2(value, context, report) {
  if (!Array.isArray(value)) return [];
  if (value.length > 20) addImportIssue(report, `${context}.desc_v2 超过 20 段，已截断`);
  return value.slice(0, 20)
    .map((item, index) => {
      if (!isPlainObject(item)) {
        addImportIssue(report, `${context}.desc_v2[${index}] 不是对象，已忽略`);
        return null;
      }
      const rawText = truncateImportText(item.raw_text, MAX_IMPORT_DESC_CHARS, `${context}.desc_v2[${index}]`, "raw_text", report);
      return rawText ? { raw_text: rawText } : null;
    })
    .filter(Boolean);
}

function sanitizeImportVideo(raw, context, report) {
  if (!isPlainObject(raw)) {
    addImportIssue(report, `${context} 不是对象，已忽略`);
    return null;
  }
  reportUnknownImportFields(raw, IMPORT_VIDEO_KEYS, context, report);
  const bvid = sanitizeImportBvid(raw.bvid, context, report, true);
  if (!bvid) return null;
  const video = { bvid };
  const title = truncateImportText(raw.title || bvid, MAX_IMPORT_TEXT_CHARS, context, "title", report);
  video.title = title || bvid;
  const owner = truncateImportText(raw.owner, MAX_IMPORT_TEXT_CHARS, context, "owner", report);
  if (owner) video.owner = owner;
  const coverUrl = sanitizeImportMediaUrl(raw, context, report);
  if (coverUrl) video.cover_url = coverUrl;
  const desc = truncateImportText(firstDefined(raw, ["desc", "description", "introduction"]), MAX_IMPORT_DESC_CHARS, context, "desc", report);
  if (desc) video.desc = desc;
  const descV2 = sanitizeImportDescV2(raw.desc_v2, context, report);
  if (descV2.length) video.desc_v2 = descV2;
  const part = truncateImportText(raw.part, MAX_IMPORT_TEXT_CHARS, context, "part", report);
  if (part) video.part = part;
  const aid = sanitizeImportNumber(raw.aid, context, "aid", report);
  if (aid !== undefined) video.aid = aid;
  const cid = sanitizeImportNumber(raw.cid, context, "cid", report);
  if (cid !== undefined) video.cid = cid;
  const metricFields = {
    view: ["view", "views"],
    like: ["like", "likes"],
    favorite: ["favorite", "favorites", "fav"],
    coin: ["coin", "coins"],
    danmaku: ["danmaku", "danmaku_count"],
    duration: ["duration", "length"],
    rank: ["rank"],
  };
  Object.entries(metricFields).forEach(([target, fields]) => {
    const value = sanitizeImportNumber(firstDefined(raw, fields), context, target, report);
    if (value !== undefined) video[target] = value;
  });
  return video;
}

function sanitizeImportDanmaku(raw, context, report) {
  if (!isPlainObject(raw)) {
    addImportIssue(report, `${context} 不是对象，已忽略`);
    return null;
  }
  reportUnknownImportFields(raw, IMPORT_DANMAKU_KEYS, context, report);
  const row = {};
  const bvid = sanitizeImportBvid(raw.bvid, context, report, false);
  if (bvid) row.bvid = bvid;
  const title = truncateImportText(raw.title, MAX_IMPORT_TEXT_CHARS, context, "title", report);
  if (title) row.title = title;
  if (!row.bvid && !row.title) {
    addImportIssue(report, `${context} 缺少 bvid 或 title，无法关联视频，已忽略`);
    return null;
  }
  const content = truncateImportText(raw.content, MAX_IMPORT_DANMAKU_CHARS, context, "content", report);
  if (!content) {
    addImportIssue(report, `${context} 缺少弹幕内容，已忽略`);
    return null;
  }
  row.content = content;
  const cid = truncateImportText(raw.cid, 64, context, "cid", report);
  if (cid) row.cid = cid;
  const time = sanitizeImportNumber(raw.time_in_video, context, "time_in_video", report);
  row.time_in_video = time === undefined ? 0 : time;
  const sendTimestamp = sanitizeImportNumber(raw.send_timestamp, context, "send_timestamp", report);
  if (sendTimestamp !== undefined) row.send_timestamp = sendTimestamp;
  const sendTimeText = truncateImportText(raw.send_time_text, 64, context, "send_time_text", report);
  if (sendTimeText) row.send_time_text = sendTimeText;
  const userHash = truncateImportText(raw.user_hash, 128, context, "user_hash", report);
  if (userHash) row.user_hash = userHash;
  const color = sanitizeImportNumber(raw.color, context, "color", report);
  if (color !== undefined) row.color = color;
  return row;
}

function importArray(data, key) {
  return Array.isArray(data?.[key]) ? data[key] : [];
}

function sanitizeImportArray(data, key, sanitizer, maxItems, report) {
  const raw = data[key];
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) {
    addImportIssue(report, `${key} 不是数组，已忽略`);
    return [];
  }
  const items = raw.length > maxItems ? raw.slice(0, maxItems) : raw;
  if (raw.length > maxItems) addImportIssue(report, `${key} 超过 ${formatNumber(maxItems)} 条，已截断`);
  return items
    .map((item, index) => sanitizer(item, `${key}[${index}]`, report))
    .filter(Boolean);
}

function sanitizeImportData(data) {
  const report = createImportReport();
  Object.keys(data).forEach((key) => {
    if (!IMPORT_ROOT_KEYS.has(key)) addImportIssue(report, `顶层未知字段 ${key} 已忽略`);
  });
  if (data.compare_videos !== undefined) {
    addImportIssue(report, "compare_videos 已忽略；对比视频请从单视频查看处重新加入");
  }
  return {
    data: {
      popular_videos: sanitizeImportArray(data, "popular_videos", sanitizeImportVideo, MAX_IMPORT_VIDEO_ROWS, report),
      popular_danmakus: sanitizeImportArray(data, "popular_danmakus", sanitizeImportDanmaku, MAX_LOCAL_DANMAKU_ROWS, report),
      searched_videos: sanitizeImportArray(data, "searched_videos", sanitizeImportVideo, MAX_IMPORT_VIDEO_ROWS, report),
      searched_danmakus: sanitizeImportArray(data, "searched_danmakus", sanitizeImportDanmaku, MAX_LOCAL_DANMAKU_ROWS, report),
      custom_videos: sanitizeImportArray(data, "custom_videos", sanitizeImportVideo, MAX_IMPORT_VIDEO_ROWS, report),
      custom_danmakus: sanitizeImportArray(data, "custom_danmakus", sanitizeImportDanmaku, MAX_LOCAL_DANMAKU_ROWS, report),
    },
    report,
  };
}

function countImportedDanmakus(data) {
  return importArray(data, "popular_danmakus").length
    + importArray(data, "searched_danmakus").length
    + importArray(data, "custom_danmakus").length;
}

function confirmImportData(file, data) {
  const count = countImportedDanmakus(data);
  if (count > MAX_LOCAL_DANMAKU_ROWS) {
    alert(`导入失败：弹幕总量 ${formatNumber(count)} 条，超过当前本地处理上限 ${formatNumber(MAX_LOCAL_DANMAKU_ROWS)} 条。`);
    return false;
  }
  const warnings = [];
  if (file.size > LARGE_IMPORT_FILE_BYTES) {
    warnings.push(`文件大小为 ${formatBytes(file.size)}`);
  }
  if (count >= HUGE_IMPORT_DANMAKU_ROWS) {
    warnings.push(`弹幕总量为 ${formatNumber(count)} 条，页面可能明显卡顿`);
  } else if (count >= LARGE_IMPORT_DANMAKU_ROWS) {
    warnings.push(`弹幕总量为 ${formatNumber(count)} 条，筛选和图表可能变慢`);
  }
  if (warnings.length === 0) return true;
  return window.confirm(`${warnings.join("；")}。\n是否继续导入？`);
}

function reportImportIssues(report) {
  if (!report.issueCount) return;
  const hiddenCount = report.issueCount - report.issues.length;
  const lines = report.issues.map((item) => `- ${item}`);
  if (hiddenCount > 0) lines.push(`- 另有 ${formatNumber(hiddenCount)} 个问题未展开显示`);
  alert(`导入完成，但已处理 ${formatNumber(report.issueCount)} 个数据问题：\n${lines.join("\n")}`);
}

function importData(file) {
  if (!file) return;
  if (file.size > LARGE_IMPORT_FILE_BYTES) {
    const ok = window.confirm(`导入文件较大（${formatBytes(file.size)}），浏览器解析可能需要较长时间。\n是否继续读取？`);
    if (!ok) {
      byId("importFile").value = "";
      return;
    }
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (!isPlainObject(data)) {
        alert("导入失败：JSON 顶层必须是对象。");
        return;
      }
      if (!confirmImportData(file, data)) return;
      const sanitized = sanitizeImportData(data);
      mergeArray(dashboardData.raw_videos || [], sanitized.data.popular_videos, (v) => v.bvid);
      mergeArray(danmakus, sanitized.data.popular_danmakus, (r) => `${r.bvid || ""}|${r.title || ""}|${r.time_in_video}|${r.content}`);
      mergeArray(searchedVideos, sanitized.data.searched_videos, (v) => v.bvid);
      mergeArray(searchedDanmakus, sanitized.data.searched_danmakus, (r) => `${r.bvid || ""}|${r.title || ""}|${r.time_in_video}|${r.content}`);
      mergeArray(customVideos, sanitized.data.custom_videos, (v) => v.bvid);
      mergeArray(customDanmakus, sanitized.data.custom_danmakus, (r) => `${r.bvid || ""}|${r.title || ""}|${r.time_in_video}|${r.content}`);
      invalidateDanmakuPoolIndex();
      updateCustomCount();
      renderCustomManage();
      renderAll();
      renderVideoInfo();
      filterDanmakus();
      reportImportIssues(sanitized.report);
    } catch {
      alert("导入失败：文件格式错误");
    }
  };
  reader.readAsText(file);
  byId("importFile").value = "";
}
