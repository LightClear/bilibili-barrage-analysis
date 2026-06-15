const playbackState = {
  cache: new Map(),
  key: "",
  data: null,
  time: 0,
  playing: false,
  lastFrameAt: 0,
  rafId: null,
  chart: null,
  requestToken: 0,
};

function setupPlaybackEvents() {
  on("playbackToggleBtn", "click", togglePlayback);
  on("playbackScrubber", "input", (event) => {
    playbackState.time = Number(event.target.value || 0);
    playbackState.playing = false;
    updatePlaybackToggle();
    renderPlaybackFrame();
  });
  window.addEventListener("resize", () => {
    resizePlaybackCanvas();
    renderPlaybackFrame();
    playbackState.chart?.resize();
  });
}

function renderPlaybackPanel() {
  const video = currentVideo();
  const status = byId("playbackStatus");
  if (!video?.bvid) {
    playbackState.key = "";
    playbackState.data = null;
    playbackState.playing = false;
    updatePlaybackToggle();
    setPlaybackStatus("选择榜单或历史中的视频后查看弹幕回放");
    setPlaybackDuration(0);
    drawPlaybackEmpty("等待选择视频");
    renderPlaybackSentiment([]);
    return;
  }

  const key = `${hotDate || "current"}|${video.bvid}`;
  if (playbackState.key === key && playbackState.data) {
    renderPlaybackFrame();
    return;
  }
  playbackState.key = key;
  playbackState.data = null;
  playbackState.time = 0;
  playbackState.playing = false;
  updatePlaybackToggle();
  setPlaybackStatus(`正在加载「${videoLabel(video)}」的回放轨道`);
  drawPlaybackEmpty("加载弹幕轨道中");
  renderPlaybackSentiment([]);
  loadPlaybackTrack(video, key);
  if (status) status.title = videoLabel(video);
}

async function loadPlaybackTrack(video, key) {
  const token = ++playbackState.requestToken;
  const query = `date=${encodeURIComponent(hotDate || "current")}&bvid=${encodeURIComponent(video.bvid)}`;
  try {
    let payload = playbackState.cache.get(key);
    if (!payload) {
      payload = await requestJson(`${API_ENDPOINTS.playbackTrack}?${query}`);
      if (!payload?.ok) throw new Error(payload?.error || "回放数据加载失败");
      playbackState.cache.set(key, payload);
    }
    if (token !== playbackState.requestToken || playbackState.key !== key) return;
    playbackState.data = payload;
    const duration = playbackDurationSeconds(payload, video);
    setPlaybackDuration(duration);
    setPlaybackStatus(`已加载 ${formatNumber(payload.meta?.track_count)} 条轨道弹幕`);
    updatePlaybackToggle();
    renderPlaybackSentiment(payload.sentiment_timeline || []);
    renderPlaybackFrame();
  } catch (error) {
    if (token !== playbackState.requestToken) return;
    setPlaybackStatus(`回放加载失败：${error.message}`);
    drawPlaybackEmpty("回放数据不可用");
  }
}

function playbackDurationSeconds(payload, video) {
  const videoDuration = metricValue(video, "duration");
  const trackMax = Math.max(0, ...(payload?.track || []).map((item) => Number(item.time || 0) + Number(item.duration || 0)));
  return Math.max(videoDuration, Math.ceil(trackMax));
}

function setPlaybackDuration(duration) {
  const scrubber = byId("playbackScrubber");
  if (!scrubber) return;
  scrubber.max = String(Math.max(0, Number(duration || 0)));
  scrubber.value = String(Math.min(Number(scrubber.max), playbackState.time));
  byId("playbackTimeLabel").textContent = formatTime(playbackState.time);
}

function setPlaybackStatus(text) {
  const status = byId("playbackStatus");
  if (status) status.textContent = text;
}

function togglePlayback() {
  if (!playbackState.data) return;
  playbackState.playing = !playbackState.playing;
  playbackState.lastFrameAt = 0;
  updatePlaybackToggle();
  if (playbackState.playing) playbackState.rafId = requestAnimationFrame(stepPlayback);
}

function updatePlaybackToggle() {
  const button = byId("playbackToggleBtn");
  if (!button) return;
  button.textContent = playbackState.playing ? "暂停" : "播放";
  button.disabled = !playbackState.data;
}

function stepPlayback(timestamp) {
  if (!playbackState.playing) return;
  if (!playbackState.lastFrameAt) playbackState.lastFrameAt = timestamp;
  const delta = (timestamp - playbackState.lastFrameAt) / 1000;
  playbackState.lastFrameAt = timestamp;
  const scrubber = byId("playbackScrubber");
  const max = Number(scrubber?.max || 0);
  playbackState.time = Math.min(max, playbackState.time + delta);
  if (playbackState.time >= max) playbackState.playing = false;
  updatePlaybackToggle();
  renderPlaybackFrame();
  if (playbackState.playing) playbackState.rafId = requestAnimationFrame(stepPlayback);
}

function resizePlaybackCanvas() {
  const canvas = byId("playbackCanvas");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
}

function renderPlaybackFrame() {
  const scrubber = byId("playbackScrubber");
  if (scrubber) scrubber.value = String(playbackState.time);
  const label = byId("playbackTimeLabel");
  if (label) label.textContent = formatTime(playbackState.time);
  const data = playbackState.data;
  if (!data) {
    drawPlaybackEmpty("暂无回放数据");
    return;
  }
  drawPlaybackTrack(data.track || [], playbackState.time);
}

function drawPlaybackEmpty(text) {
  const canvas = byId("playbackCanvas");
  if (!canvas) return;
  resizePlaybackCanvas();
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(226, 232, 240, 0.68)";
  ctx.font = "14px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(text, width / 2, height / 2);
}

function drawPlaybackTrack(track, currentTime) {
  const canvas = byId("playbackCanvas");
  if (!canvas) return;
  resizePlaybackCanvas();
  const ctx = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(15, 23, 42, 0.32)";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(148, 163, 184, 0.12)";
  for (let y = 24; y < height; y += 28) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  const visible = track.filter((item) => {
    const start = Number(item.time || 0);
    const end = start + Number(item.duration || 6);
    return currentTime >= start - 1 && currentTime <= end + 1;
  });
  ctx.font = "15px sans-serif";
  ctx.textBaseline = "middle";
  visible.forEach((item) => {
    const start = Number(item.time || 0);
    const duration = Number(item.duration || 6);
    const progress = Math.max(0, Math.min(1, (currentTime - start) / duration));
    const text = String(item.text || "");
    const textWidth = ctx.measureText(text).width;
    const x = width - progress * (width + textWidth + 80);
    const y = 22 + (Number(item.lane || 0) % 12) * 20;
    ctx.fillStyle = "rgba(2, 6, 23, 0.58)";
    ctx.fillRect(x - 8, y - 12, textWidth + 16, 24);
    ctx.fillStyle = item.color || "#ffffff";
    ctx.fillText(text, x, y);
  });
}

function renderPlaybackSentiment(rows) {
  const el = byId("playbackSentimentChart");
  if (!el || !window.echarts) return;
  const chart = playbackState.chart || echarts.init(el);
  playbackState.chart = chart;
  chart.setOption({
    grid: { left: 36, right: 18, top: 20, bottom: 28 },
    xAxis: {
      type: "category",
      data: rows.map((item) => formatTime(item.time)),
      axisLabel: { color: "rgba(226,232,240,.68)" },
      axisLine: { lineStyle: { color: "rgba(148,163,184,.25)" } },
    },
    yAxis: {
      type: "value",
      min: -1,
      max: 1,
      axisLabel: { color: "rgba(226,232,240,.68)" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,.12)" } },
    },
    tooltip: { trigger: "axis" },
    visualMap: {
      show: false,
      min: -1,
      max: 1,
      inRange: { color: ["#fb7185", "#e2e8f0", "#22c55e"] },
    },
    series: [{
      type: "line",
      smooth: true,
      symbolSize: 6,
      data: rows.map((item) => Number(item.score || 0)),
      areaStyle: { opacity: 0.14 },
      lineStyle: { width: 3 },
    }],
  });
}
