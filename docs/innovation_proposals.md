# B站弹幕可视化项目 - 创新点方案建议

> 本文档由多智能体工作流（48 agent / 4 阶段：Explore → Ideate → Verify → Synthesize）生成，对当前项目实现做了全面扫描，从 10 个角度生成创新点，并经 3 视角（feasibility / novelty / value）对抗性验证后综合排序得出。
>
> 生成日期：2026-06-09

---

## 一、项目当前优势与缺口速览

### 已做得不错的方面
- **数据采集链路完整可用**：`collector.py` / `parser.py` / `filter.py` / `analyzer.py` / `pipeline.py` 形成清晰的离线流水线，按 BV 拆分存储 + 14 天归档为后续纵向分析打下基础。
- **账号与安全工程扎实**：PBKDF2-SHA256、CSRF Token、Session、撞库防护、AI 验证码、三级角色 + SSRF 防护 + 安全响应头，课程级别属于"过度工程"褒义。
- **AI 接入架构有诚意**：用户自带 OpenAI-compatible API + 本机加密存储 + 三档分析模式（省钱 / 深度摘要 / 全量原文），规避"作者掏钱"可持续性问题。
- **依赖极轻**：requests + jieba + ECharts + 标准库 HTTP Server，便于答辩零依赖启动。
- **后台任务可视化已就位**：`job_manager.py` 已能承载长任务事件流，是后续实时化天然底座。

### 最值得突破的缺口
- **缺少"弹幕该有的样子"——沿视频时间轴的回放**：当前所有图表都是静态聚合，未利用 `time_in_video` 这个项目最核心字段。
- **AI 分析停留在"看文本说氛围"**：封面、字幕、评论三大高价值通道完全未送入 LLM，错失多模态画像。
- **跨视频 / 纵向分析空白**：14 天归档数据未被任何图表消费，词云仅"单视频快照"，无法回答"梗在哪个视频起源"。
- **弹幕字段采集不完整**：`mode / fontsize / pool / dmid / weight` 全部丢弃，未来想做高级分析需回溯重采。
- **MySQL 已写 schema 但主流程不接入**：答辩中会被追问的"为什么做了一半"尴尬点。
- **零预测能力**：项目纯被动展示，无"预测下一个热门""识别新梗"等主动洞察。

---

## 二、推荐创新点（按"投入产出比 + 演示价值"排序）

### Top 1：弹幕真实回放 + 情绪心电图双轨道  ★★★★★

- **问题与价值**：项目最稀缺的"弹幕本体感"功能。数据 100% 已就绪（`time_in_video` + `send_timestamp`），却从未被时间轴消费。拖动游标看弹幕飞过 + 情绪曲线起伏，比任何静态图表都有冲击力。
- **技术方案**：
  - 上层 Canvas 2D 渲染 12 条 lane 滚动弹幕（贪心 lane 分配避免重叠 + 仅渲染 ±30s 可见窗口）。
  - 下层 ECharts line + visualMap 红绿渐变绘制情绪心电图。
  - 时间游标 requestAnimationFrame 节流。
  - 弹幕量 >5 万时 LTTB 降采样。
- **与现有架构的集成点**：
  - `src/analyzer.py` 新增 `build_playback_track(danmakus, lane_count=12)` 和 `build_sentiment_timeline()`。
  - `server.py` 新增 `/api/playback/track?bvid=` 端点复用 access_control。
  - 前端新建 `web/js/app-playback.js`。
- **新增依赖与成本**：零；情绪打分用本地词典（POSITIVE / INTENSE / 反讽词典扩展）做基线，仅高峰段调用 LLM 校准，sentiment 缓存进 danmaku_store 避免重复计费。
- **工程量评估**：中（约 1 周）。
- **答辩亮点**："我们让弹幕回到它该在的位置"——单句 slogan + 现场拖动 demo 形成视觉记忆点。
- **风险与降级方案**：LLM 不可用时纯词典心电图依旧可跑；弹幕量过大时自动扩 lane 或合并相邻同文；准备 2-3 个"情绪起伏明显"的预选视频做种子 demo。

---

### Top 2：封面-弹幕-评论三模态视频内容画像  ★★★★★

- **问题与价值**：当前 `build_ai_analysis` 只读文本，对鬼畜 / 反差封面 / 暗语弹幕完全失真。封面 URL 已采集但仅用于显示，是巨大资产浪费。三模态画像 + "标题党分 / 反差分 / 一致性 %"诊断条是真正差异化的学术亮点。
- **技术方案**：
  - `src/ai_analysis.py` 新增 `build_multimodal_profile(payload, provider_config)`。
  - `ai_provider.py` 新增 vision-capable 适配层 `_post_chat_completion_vision`（OpenAI Vision messages 协议，GPT-4o / GLM-4V / Qwen-VL / Gemini-1.5 均兼容）。
  - 输出结构化 JSON 含 `cover_semantic / comment_summary / danmaku_summary / cross_modal_diagnosis / final_profile`，每字段强制 `evidence_anchor` 防幻觉。
- **与现有架构的集成点**：
  - 复用 `secure_provider_store`（新增 `vision_capable` 字段）、`ai_usage` 记账、`ai_analysis` cache。
  - 前端 `web/js/app-ai.js` 新增 ECharts graphic 在封面上叠加语义热区。
- **新增依赖与成本**：零；封面图后端代理下载并缩放到 512px 再 base64 内联（规避 `i*.hdslb.com` 防盗链 + 压缩 token）；不支持视觉的模型自动降级为二模态。
- **工程量评估**：中（约 1.5 周）。
- **答辩亮点**：封面 X 光透视 + 三栏对照"封面在卖什么 / 弹幕在玩什么 / 评论在争什么" + 一致性诊断条。
- **风险与降级方案**：评论接口 `x/v2/reply/wbi/main` 需 WBI 签名——MVP 阶段可先用免签的旧 reply 接口或省略评论降级为二模态；vision 调用不可用时走纯文本兜底。

---

### Top 3：B 站梗知识库 + RAG 弹幕梗百科  ★★★★★

- **问题与价值**：B 站弹幕的"典孝急乐绷麻"在通用 LLM 眼里全是误判。这是项目独有数据 + 独有领域知识结合的最佳点，真正的"学术贡献"，填补 ai_analysis 中明确列出的"梗 / 迷因识别与传播追踪"空白。
- **技术方案**：
  - `data/knowledge/memes.jsonl` 维护结构化梗库（schema = `{slug, surface_forms[], category, era, origin, plain_explanation, in_video_meaning, sentiment, examples[], related_memes[]}`）。
  - MVP 阶段 50-80 条高频核心梗。
  - `src/meme_kb.py` 提供 trie 前缀 + 模糊匹配。
  - LLM 输出新增 `memes_decoded` 字段，强制 `confidence > 0.5 必须 cite kb_slug` 杜绝幻觉。
- **与现有架构的集成点**：
  - `build_ai_analysis` 流水线新增 meme_recall 阶段，召回 Top-5 候选作为 grounded 上下文塞入 prompt。
  - 前端在词云 / 关键词区每个梗加 (?) 图标悬浮显示卡片（类 Genius 歌词注解）。
  - admin 后台开放"梗提议"入口复用 access_control 审核流。
- **新增依赖与成本**：零（不引入 bge / sentence-transformers，避免 500MB 依赖膨胀）；MVP 仅用 surface trie + 模糊匹配，embedding RAG 列为可选 P2 走用户自带 API。
- **工程量评估**：中（约 1 周，主要在数据冷启动）。
- **答辩亮点**：演示鼠标悬浮 "典" → 弹出 "源自贴吧'典中典'缩写，表达对套路化言论的反讽。在本视频 02:14 针对 UP 主重复老梗的情节" 这种 Genius 级注解。
- **风险与降级方案**：梗库覆盖不到时显示"未收录，欢迎补充"并入审核队列；reference_urls 注意萌娘百科 CC-BY-NC 不可直接商用，需重写而非直引。

---

### Top 4：视频"破圈预测器"（Early Virality Predictor）  ★★★★☆

- **问题与价值**：项目同源数据天然自带标签（今天 Top50 出现明天进 Top10 = 正样本），无需外部标注。把"被动展示"升级为"主动预测"，论文张力极强。
- **技术方案**：
  - 特征工程纯 numpy（弹幕到达率二阶导、Poisson 过散度、`user_hash` 基尼系数、文本情感词占比、与同分区基线 z-score）。
  - 模型用纯 Python Logistic + L2 兜底（200 行 numpy）或 LightGBM。
  - 导出 `model.json`，推理纯 Python。
  - time-series CV 评估 AUC / lift@10。
- **与现有架构的集成点**：
  - 新增 `src/predictor/virality.py` 离线消费 `data/archive/`。
  - `pipeline.refresh_popular_payload` 完成后给 Top50 每项打 `virality_score`。
  - 前端排行榜每项加破圈概率徽章（ECharts gauge）。
  - SHAP / permutation importance 联动 bar 图实现可解释 ML。
- **新增依赖与成本**：仅 numpy；LightGBM 可选。
- **工程量评估**：中（约 1.5 周）。
- **答辩亮点**："比 B 站官方榜单多了一层可信度维度——抗操纵热度评估" + 特征重要度可解释 ML。
- **风险与降级方案**：14 天数据样本量偏少时退化为 baseline + 规则；与水军检测模块联动，水军比率 > 阈值时给 `virality_score` 打折。

---

### Top 5：弹幕峰值驱动的剧情时间线 + 快剪推荐  ★★★★☆

- **问题与价值**：当前 `peak_minute` 是个孤零零的数字，长视频用户痛点是"我想知道哪段最精彩"。B 站二创生态对"高能时间戳"是刚需，从弹幕峰值反推切片建议是项目天然且独有能力。
- **技术方案**：
  - `src/narrative_timeline.py` 用滑动窗口 z-score（不引入 ruptures）做变点检测，把视频切成 3-12 段 chapters。
  - 每段抽样 30-50 条代表弹幕。
  - 调用字幕接口 `x/player/v2` 拿台词附在弹幕样本前。
  - LLM 为每段输出 `{chapter_title, plot_summary, why_burst, highlight_score, suggested_clip_start/end, suggested_clip_caption}`。
  - 输出 Top-3 高能段作为快剪推荐卡片，带 B 站时间戳锚链接 `?t={s}s`。
- **与现有架构的集成点**：
  - 复用 `ai_analysis` cache（按 chapter_signature_hash 分段缓存）。
  - 前端 `app-charts.js` 时间分布折线图加 markArea 高亮各 chapter + markPoint 打 chapter_title。
- **新增依赖与成本**：零；字幕接口需 SESSDATA Cookie，无 Cookie 时仅用弹幕兜底。
- **工程量评估**：中（约 1.5 周）。
- **答辩亮点**：点击"Ch3 名场面 高能分 92"卡片 → 一键复制时间戳 → 现场跳转 B 站验证，制造"真的能用"体感。
- **风险与降级方案**：字幕缺失时纯弹幕峰值兜底；`_merge_provider_result` 必须加 chapter 时间区间合法性校验防 LLM 越界。

---

### Top 6：跨视频关键词桑基迁移图 + 主题河流  ★★★★☆

- **问题与价值**：14 天归档数据未被任何图表消费是巨大浪费。回答"破防这个梗从哪个视频起源、传播到了哪些视频"是 B 站文化研究的标志性问题。
- **技术方案**：
  - `src/cross_video_analyzer.py` 新增 `build_keyword_sankey(date_range, top_k=30)` 和 `build_meme_river(date_range)`。
  - ECharts 原生 sankey + themeRiver 组件。
  - 节点 = 高频梗，边 = 该梗在该视频频次。
  - 点击节点联动右侧弹出样本弹幕。
  - 可选量化"梗的 R0 值"（一个视频出现后平均扩散到几个视频）。
- **与现有架构的集成点**：复用 archive 14 天数据 + analyzer.py 现有分词链；与 Top 3 梗知识库的 slug 互联——桑基图节点优先用规范化梗名而非裸高频词。
- **新增依赖与成本**：零（ECharts 原生 sankey / themeRiver）。
- **工程量评估**：**小（约 3-4 天）**。
- **答辩亮点**：演示梗的诞生 → 扩散 → 衰减全生命周期，B 站文化研究独特视角。
- **风险与降级方案**：数据稀疏时降级显示 Top-5 梗即可；若梗知识库未先行落地，节点用"裸词聚类"兜底但视觉效果略逊。

---

### Top 7：弹幕情感分类器（中文轻量双轨）  ★★★☆☆

- **问题与价值**：当前字典式四档氛围精度差且无概率，无法支撑 Top 1 心电图的精细情绪曲线。是其他多个模块的"地基"。
- **技术方案**：
  - 双轨发布——
    - 路径 A：SnowNLP 纯 Python ~3MB 兜底（70% 精度）。
    - 路径 B：`uer/roberta-tiny-finetuned-dianping` INT8 量化 ONNX ~6-10MB + onnxruntime（85%+ 精度，CPU <5ms / 条）。
  - 三级降级链：onnx → SnowNLP → 词典。
- **与现有架构的集成点**：`src/analyzer.py` 新增 `classify_sentiment(text) -> {label, prob}`；被 `build_dashboard_payload` 调用；情感分布灌入 AI 报告 prompt 让 LLM 不再瞎猜氛围。
- **新增依赖与成本**：SnowNLP 可选 3MB；ONNX 路径需 onnxruntime（~20MB），需 README 明示 Python 3.8-3.12 兼容。
- **工程量评估**：小（约 3-5 天）。
- **答辩亮点**：三级降级架构展现工程思维 + 量化精度对比表。
- **风险与降级方案**：onnxruntime Windows wheel 兼容性差时退到 SnowNLP；ChnSentiCorp + 500 条人工标注 B 站梗弹幕做 LoRA 微调可作为论文附加实验。

---

### Top 8：AI 投稿评分卡 + 多文体内容工坊  ★★★☆☆

- **问题与价值**：当前 AI 输出是"看了就没了"的报告，对 UP 主 / 营销 / 创作者零执行价值。把分析结果转化为可生产产物，留存率从一次性查询升级为高频回访。
- **技术方案**：
  - `src/ai_scoring.py` 输出 5 维评分（内容质量 / 互动健康度 / 标封契合度 / 破圈潜力 / 商业可持续）+ 同分区 baseline 分位（兜底用全量历史）。
  - `src/content_studio.py` 提供 6 种文体生成（投稿简介 250 字限 / 解说稿 / 复盘报告 markdown / 小红书种草文 / 动态文案 / 封面文字建议），每种独立 prompt 模板 + jsonschema 强校验。
- **与现有架构的集成点**：评分基于现有统计指标 + archive 历史，算法层零幻觉；多文体仅 prompt 差异，全部复用 ai_provider 单次调用；前端"AI 内容工坊"抽屉 + html2canvas 导出 PDF / PNG 分享卡（CSP 已放行 jsdelivr）。
- **新增依赖与成本**：零新后端依赖；前端可选 html2canvas。
- **工程量评估**：中（约 1 周，主要在 6 套 prompt 调优）。
- **答辩亮点**：雷达图 + "一键生成下期内容"按钮，从"看分析"升级为"做创作"。
- **风险与降级方案**：archive 不足 30 天时改为"相对自身历史"趋势评分；UI 显著标注"非 B 站官方算法"避免误导。

---

## 三、按主题分类的备选方案库

### 实时与直播
- **B 站直播 WSS 弹幕粒子风暴**：Canvas 粒子可视化 + SSE 桥接，演示冲击力强但需处理 WBI / buvid3 风控 + brotli 依赖（中风险）。
- **滑动窗口增量词云 + 梗爆发热力时间轴**：服务端 deque 60s / 300s / 600s 三档窗口 + z-score 突增检测，可独立于直播单独落地。
- **实时情绪温度计 + 6 维氛围雷达**：与 Top 1 心电图共用情感分类器，可作为直播扩展。

### 多模态 AI
- **官方 AI 视频总结对接**：直接调 `x/web-interface/view/conclusion/get` 拿官方 LLM 章节摘要，零成本补全章节维度。
- **弹幕-字幕跨模态语义锚定**：提出 `callback_rate / off_topic_rate` 原创指标，"UP 主埋梗命中率"独特视角。
- **AI 报告 Evidence-grounded 词云 Agent**：让 LLM 通过 tool-use 调用 `query_danmakus_at(minute)` 二次取证。

### 社交协作
- **AI 报告 ShareCard 公共空间**：仅做精简版（slug 16 位 + admin 审核队列 + 举报表），不做排行榜。
- **单视频协作标注 MVP**：短轮询替代 SSE，brush 联动 + 标注气泡持久化，规避多人并发冲突。

### 高级可视化
- **14 天热力日历 + Bar Chart Race**：ECharts 原生支持，1 天工作量补完时序叙事。
- **Scrollytelling 年度回顾**：IntersectionObserver + 懒加载图表，章节模板自动生成。
- **UP 主向量 UMAP 二维地图**：借助 Top 3 embedding 复用，可视化"内容生态地图"。

### 预测与 ML
- **弹幕异常 / 水军检测（无监督，零依赖）**：时间间隔规整度 + n-gram 自重复率 + 协同刷屏，是其他 ML 模块的地基。
- **梗生命周期 ARIMA / Holt-Winters 预测**：配合 Top 6 桑基图，标"上升 / 平稳 / 衰退"。

### 游戏化与教育
- **AI 素养徽章体系（轻量版）**：仅做积分事件审计表 + 5 个核心徽章，不做完整勋章墙。
- **新手引导式弹幕分析教程**：在 dashboard 加 onboarding tour，演示给评委时降低理解门槛。

### 数据开放
- **结构化数据集 CC-BY 发布**：14 天 Top50 弹幕 + 聚合指标导出为 `parquet / jsonl`，附数据集 README。
- **REST API 文档化（OpenAPI）**：用 swagger-ui 静态文件展示，规避引入 FastAPI 重构。

### 可访问性
- **键盘导航 + ARIA 标签全覆盖**：配合时间轴回放的快捷键控制（空格暂停、左右步进）。
- **色弱友好模式切换**：情感心电图提供 ColorBrewer 色板替代红绿。

### 运维质量
- **MySQL 主流程接入开关**：环境变量 `STORE_BACKEND=file|mysql` 双轨并存，回答"为什么写了 schema 不接入"。
- **Playwright 前端 E2E 测试**：至少覆盖登录 + 切换视频 + AI 报告生成三条主路径。

### 跨平台对比
- **同名作品跨 B 站 / 抖音弹幕对比**：数据采集成本高，仅作为答辩"未来工作"提及。

---

## 四、不推荐 / 慎选的方向及原因

| 方案 | 不推荐原因 |
|---|---|
| **B 站直播 WSS 实时风暴整体方案（5 子方案打包）** | 工程量被严重低估（25-40 人天），WBI / buvid3 风控未处理，ThreadingHTTPServer + SSE 在 N 路直播 × M 订阅者下线程必然耗尽，演示当天主播冷场即翻车 |
| **多直播间并排 PK 监控墙** | 5 秒 Jaccard 检测"话题迁移"假阳性极高（头部梗本就同时全平台流行），价值叙事偏 MCN 运营而非毕设受众，伪需求嫌疑大 |
| **社交化整体方案（5 个 social_collaboration 创新打包）** | 全部依赖 MySQL 主流程接入（项目自承认未完成），5 张新表 + 6 个新页 + SSE 全栈改造工程量爆炸；与"弹幕可视化"主题偏离，评委会质疑主线漂移；演示现场无真实 UGC，排行榜 / 徽章空转暴露 |
| **WebGL 百万级弹幕点云（X=视频时间 / Y=日期 / Z=长度）** | 三轴语义信息密度低，"为炫而炫"易被追问"回答了什么真实问题"；建议改为"弹幕语义嵌入 UMAP 3D 投影"才有洞察价值 |
| **本地 bge-small-zh 兜底嵌入** | 引入 sentence-transformers + torch 超过 500MB，与项目"依赖很轻"定位严重冲突；embedding 改为强制走用户自带 API，无 Key 用户直接禁用 RAG 而非引入重型依赖 |
| **UP 主追更轮询 + WBI 签名维护** | 30 分钟轮询会快速触发 B 站 -352 / -412 风控，WBI 签名是长期维护负担；改为"用户手动触发刷新该 UP 主"按需采集即可 |
| **多人协作 SSE 实时标注** | 并发冲突 / 乐观锁 / 消息去重在同步阻塞架构难以稳定实现；降级为单用户 brush 联动 + 标注持久化即可拿到 80% 价值 |
| **ruptures PELT 变点检测** | Windows wheel 偶有缺失 + O(n²) 性能问题，改为滑动窗口 z-score 同样可用 |

---

## 五、6 周冲刺路线图（如果只能选 3 个落地）

**核心三选**：Top 1（回放心电图）+ Top 2（三模态画像）+ Top 6（跨视频桑基）。

理由：一个抓眼球，一个有学术深度，一个用足 14 天归档数据。

### Week 1：情绪分类器 + 回放轨道骨架
- 落地 Top 7 简化版（仅 SnowNLP + 词典双级降级，跳过 ONNX）。
- `src/analyzer.py` 新增 `build_playback_track / build_sentiment_timeline`。
- `web/js/app-playback.js` Canvas 双层骨架 + 时间游标 + 贪心 lane 分配。
- **里程碑**：单视频可拖动回放，心电图静态可见。

### Week 2：回放完善 + AI provider Vision 适配
- 回放性能优化（LTTB 降采样 + ±30s 窗口渲染 + RAF 节流）。
- `src/ai_provider.py` 新增 `_post_chat_completion_vision` + 7 种 provider 适配单测。
- 封面后端代理下载 + 512px 缩放 + base64 内联。
- **里程碑**：回放可对外 demo；vision API 单测全绿。

### Week 3：三模态画像 MVP
- `src/ai_analysis.py` 新增 `build_multimodal_profile`，输出 JSON schema 含 evidence_anchor。
- 评论接口先用免签旧版兜底，标注"二模态降级路径已就绪"。
- 前端 `app-ai.js` 新增三栏对照卡片 + 封面 ECharts graphic 热区叠加。
- **里程碑**：5 个测试视频跑出完整三模态报告。

### Week 4：跨视频桑基 + 主题河流
- `src/cross_video_analyzer.py` 消费 archive 14 天数据。
- ECharts sankey + themeRiver 接入 `app-charts.js`。
- 节点点击 → 联动样本弹幕弹窗。
- **里程碑**：14 天梗迁移视图可演示。

### Week 5：梗知识库种子 + RAG 接入（Top 3 简化版）
- `data/knowledge/memes.jsonl` 手工整理 50-80 条核心梗。
- `src/meme_kb.py` trie 前缀 + 模糊匹配。
- AI prompt 中注入候选梗 + 强制 cite kb_slug。
- 前端词云 (?) 图标 + 悬浮卡片。
- **里程碑**：答辩用 3 个演示视频 100% 梗覆盖。

### Week 6：集成打磨 + 演示脚本 + 兜底缓存
- 所有 AI 产物预生成缓存到 5 个"黄金视频"，确保零外部依赖可演示。
- html2canvas 一键导出三模态画像分享卡。
- README 更新 + 答辩 PPT 录制 GIF。
- E2E 走查 + 性能压测 + 演示剧本秒级分配。
- **里程碑**：完整故事线可一镜到底跑通。

---

## 六、答辩演示的"故事线"建议

**主线一句话**：

> "我们让弹幕从屏幕上滚过的文字，变成可被回放、可被理解、可被预测的文化数据。"

### 5 句话叙事

1. **看清（Top 1）**：打开任意热门视频，拖动时间游标，弹幕沿轨道飞过 + 情绪心电图实时起伏——这是项目最朴素也最有力的"弹幕本体感"，证明我们用足了 `time_in_video` 这个核心字段。
2. **看懂（Top 2 + Top 3）**：封面被 AI X 光透视，标出"萌系封面 vs 恐怖内容 = 标题党分 72%"；弹幕里的"典孝绷"不再是乱码——鼠标悬浮即弹出 Genius 级注解。三模态画像 + 领域知识增强让 AI 第一次真正理解 B 站。
3. **看见（Top 6）**：切到跨视频视图，"破防"这个梗从 BV1xxx 起源、扩散到 8 个视频、3 天后衰减——14 天归档数据第一次产生纵向洞察。
4. **看未来（可选 Top 4 彩蛋）**：排行榜每个视频旁标着"破圈概率 78% ↑"，把项目从"展示型可视化"升级为"预测型分析平台"。
5. **收束**：整个项目零外部 API 强依赖（用户自带 Key + 本地词典兜底）、零重型框架（原生 JS + ECharts）、零脏数据进入分析（水军打标 + 字典预过滤）——是"小而美"的工程美学，也是可被复现的学术贡献。

### 关键防守话术

| 评委可能的提问 | 应答要点 |
|---|---|
| "为什么不接 MySQL？" | 已写 schema 是为了"演示文件 / 生产 MySQL 双轨并存"的工程考量，演示选文件后端确保答辩零环境依赖 |
| "AI 部分是不是套壳？" | `cross_modal_diagnosis` 量化指标、`evidence_anchor` 防幻觉约束、`meme_kb` RAG 召回评估三个原创设计，可独立验证 |
| "新颖性在哪？" | `callback_rate` / 标题党分 / 梗 R0 值 三个原创指标 + 三模态一致性诊断管线，不在任何已知 B 站第三方工具中出现 |

---

## 附录：方案选择决策原则

1. **优先"对该项目已有架构改动小但效果震撼"的方案**——保护已稳定的 1.1 文件模式。
2. **每个推荐方案都明确"工程量（小 / 中 / 大）"和"新颖度（标配 / 常见+ / 真创新）"**——避免被评委质疑"为做而做"。
3. **每个方案都保留兜底降级路径**——LLM 不可用、Cookie 失效、依赖缺失时仍可演示。
4. **零强外部依赖原则**——所有 AI 都走用户自带 API；本地模型走 SnowNLP / 词典；ML 走 numpy 而非 torch。
5. **演示资产预生成**——为 5 个"黄金视频"提前缓存所有 AI 产物，确保答辩现场零网络也能跑。
