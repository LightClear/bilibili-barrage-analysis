# 数据储存与接口文档

## 储存设计目标

项目早期的问题是榜单切换时会同时加载整份弹幕明细。弹幕文件一旦达到几十 MB 或更大，浏览器解析 JSON、前端重建索引和重新统计都会造成明显卡顿。

当前储存设计目标是：

- 榜单切换只加载轻量数据。
- 弹幕明细按模块、日期和视频拆分。
- 单视频弹幕只在需要时进入前端内存。
- 搜索历史和临时数据可释放。
- 本地运行时可以自动清理旧文件、孤儿分库和过期缓存。
- 保持 JSON 文件可读，方便课程展示和调试。

## 当前目录结构

```text
大/
  web/
    data/
      dashboard.json              # 当前热门榜单轻量展示数据
      danmaku_index.json          # 当前热门榜单弹幕文件索引
      video_stats.json            # 当前热门榜单单视频统计缓存
      danmakus/
        <BVID>.json               # 当前榜单单个视频弹幕明细
  data/
    archive/
      YYYY-MM-DD/
        today_hot_videos.json     # 指定日期热门榜单原始快照
        danmaku_index.json        # 指定日期弹幕文件索引
        video_stats.json          # 指定日期单视频统计缓存
        danmakus/
          <BVID>.json             # 指定日期单个视频弹幕明细
        today_danmakus.json       # 旧归档兼容读取，不再作为新写入格式
    ai_analysis/
      cache/                      # AI 分析缓存
      usage_stats.json            # AI 使用统计
      current_*_report.txt        # 当前视频最新报告 artifact
      compare_*_report.txt        # 对比分析最新报告 artifact
    secure/
      api_providers.json          # 账号级模型 Provider 加密储存
      bili_cookies.json           # 账号级 B 站 Cookie 加密储存
    user_block_words/
      <account>.txt               # 账号级个人屏蔽词
    accounts.txt                  # DEMO 账号 JSON 文本
  config/
    block_words.txt               # 全局屏蔽词
```

## 热门榜单数据结构

### dashboard.json

`dashboard.json` 面向首屏和榜单展示，包含视频列表、汇总指标、榜单元信息和部分图表所需的轻量字段。它不再承载整份弹幕明细。

典型用途：

- 首屏热门视频列表。
- 榜单排序和视频卡片信息。
- 当前日期、采集时间、视频数量等元信息。
- 不依赖弹幕明细的汇总展示。

### danmaku_index.json

`danmaku_index.json` 记录每个 BV 号对应的弹幕文件位置和基础状态。前端使用它判断某个视频是否可以按需加载弹幕。

示例结构：

```json
{
  "version": 1,
  "scope": "popular",
  "date": "2026-06-03",
  "videos": {
    "BVxxxx": {
      "file": "danmakus/BVxxxx.json",
      "count": 3600
    }
  }
}
```

### video_stats.json

`video_stats.json` 是单视频统计缓存，主要用于避免榜单切换后再扫描弹幕明细。

典型字段：

```json
{
  "BVxxxx": {
    "danmaku_count": 3600,
    "time_series": {},
    "send_time_series": {},
    "length_buckets": {},
    "word_cloud": [],
    "user_rank": []
  }
}
```

页面可以先用这些统计渲染图表。只有用户需要查看弹幕列表、做筛选、加入对比或 AI 分析时，才加载对应的弹幕明细文件。

### danmakus/<BVID>.json

单视频弹幕文件保存该视频的弹幕明细。热门榜单按日期拆分，因此同一个 BV 号在不同日期归档下可以有独立弹幕文件。

设计价值：

- 日期切换不会解析全部弹幕。
- 单个视频释放、补抓、清理更容易。
- 存储损坏或采集失败时影响范围更小。
- 更接近后续数据库中的 `danmakus` 按 `bvid/cid/date` 查询方式。

## 前端内存结构

前端不再把 `danmakus` 当作当前榜单全部弹幕，而是只保存已经加载过的视频弹幕。

主要状态：

| 状态 | 说明 |
| --- | --- |
| `dashboardData` | 当前榜单轻量数据 |
| `hotDanmakuIndex` | 当前日期的热门弹幕索引 |
| `loadedHotDanmakuKeys` | 当前日期已加载弹幕的视频集合 |
| `danmakus` | 已按需加载到前端的热门视频弹幕 |
| `searchedVideos` / `searchedDanmakus` | BV 搜索历史视频和弹幕 |
| `customVideos` / `customDanmakus` | 自定义榜单视频和弹幕 |
| `statsCache` | 当前视频和对比视频统计缓存 |

搜索历史释放由 `pruneSearchedData()` 控制。当前策略是最多保留 15 个未固定视频。如果视频已加入自定义榜单或对比，则视为固定，不会被自动释放。

## 数据调用方式

### 首屏启动

```text
前端 bootstrap()
  -> 读取 web/data/dashboard.json
  -> 读取 web/data/video_stats.json
  -> 读取 web/data/danmaku_index.json
  -> 请求 /api/identity 或 /api/account/session
  -> 渲染榜单和空的当前视频面板
```

首屏不会加载所有 `danmakus/<BVID>.json`。

### 切换热门日期

```text
GET /api/popular-date?date=YYYY-MM-DD
```

返回：

- 轻量 dashboard。
- 该日期 `danmaku_index`。
- 该日期 `video_stats`。
- 兼容字段 `danmakus: []`。

不返回整份弹幕明细。

### 加载单视频弹幕

```text
GET /api/video-danmakus?date=YYYY-MM-DD&bvid=BVxxxx
GET /api/video-danmakus?date=current&bvid=BVxxxx
```

返回指定日期、指定视频的弹幕明细。前端在以下场景触发：

- 点击榜单视频并查看详情。
- 对当前视频进行弹幕筛选。
- 加入自定义榜单。
- 加入视频对比。
- 触发当前视频或对比 AI 分析。

### BV 搜索任务

```text
POST /api/jobs/search
GET /api/jobs/status?job_id=...
GET /api/jobs/result?job_id=...
```

BV 搜索结果不写入热门归档。它进入当前浏览器页面的搜索历史库，前端根据上限自动释放未固定视频。

### 热门榜单刷新任务

```text
POST /api/jobs/refresh-popular
GET /api/jobs/status?job_id=...
GET /api/jobs/result?job_id=...
```

管理员或 owner 可创建刷新任务。任务完成后：

- 写入当天 `data/archive/YYYY-MM-DD/`。
- 导出当前 `web/data/`。
- 前端可重新读取当前热门榜单。

### 储存占用和清理

```text
GET /api/admin/storage-usage
POST /api/admin/storage-cleanup
```

管理员页支持先查看占用，再预览清理候选，最后执行清理。历史归档目录删除需要额外确认。

## 释放与清理机制

项目存在两类释放：前端内存释放和本地文件清理。

### 前端内存释放

前端释放主要针对 BV 搜索历史：

- 默认最多保留 15 个未固定视频。
- 加入自定义榜单或对比的视频视为固定。
- 超出上限后删除较旧的未固定视频和对应弹幕。
- 弹幕池变化后调用索引失效逻辑，下一次读取时重新建立索引。

这解决的是网页运行过程中内存和渲染压力不断增加的问题。

### 本地文件自动清理

服务启动时会自动执行保守清理，默认只处理可以安全判断的文件：

- 已有拆分库替代的旧全量弹幕文件。
- 运行时原始/处理弹幕副本。
- 未被索引引用的孤儿弹幕分库。
- 过期 AI 缓存。
- 超出保留数量的 AI 报告 artifact。

可以通过环境变量 `STORAGE_AUTO_CLEANUP=0` 临时关闭启动自动清理。

### 管理员手动清理

管理员页提供储存占用查看和手动清理。手动清理支持 dry-run 预览，避免直接删除。归档目录按保留天数删除时需要管理员明确确认。

## 接口设计清单

| 接口 | 方法 | 权限 | 用途 |
| --- | --- | --- | --- |
| `/api/popular-dates` | GET | 登录或游客可读 | 返回当前日期和归档日期 |
| `/api/popular-date` | GET | 登录或游客可读 | 返回轻量热门榜单、索引和统计 |
| `/api/video-danmakus` | GET | 登录或游客可读 | 返回单视频弹幕明细 |
| `/api/jobs/search` | POST | 按账号限制搜索间隔 | 创建 BV 搜索任务 |
| `/api/jobs/refresh-popular` | POST | admin / owner | 创建热门榜单刷新任务 |
| `/api/jobs/status` | GET | 任务可见范围 | 查询任务进度 |
| `/api/jobs/result` | GET | 任务可见范围 | 获取任务结果 |
| `/api/ai/analyze` | POST | API 开关和 Provider 状态控制 | 当前视频或对比 AI 评价 |
| `/api/account/block-words` | GET/POST | 当前账号 | 读取和保存个人屏蔽词 |
| `/api/account/provider` | GET/POST | 当前账号 | 读取和保存模型 Provider |
| `/api/account/bili-cookie` | GET/POST | 当前账号 | 读取和保存 B 站历史补抓凭证 |
| `/api/admin/storage-usage` | GET | admin / owner | 查看本地储存占用 |
| `/api/admin/storage-cleanup` | POST | admin / owner | 预览或执行本地储存清理 |

## MySQL 迁移对应关系

当前 JSON 文件模式可以自然映射到 MySQL：

| 文件模式 | MySQL 方向 |
| --- | --- |
| `today_hot_videos.json` | `popular_snapshots`、`popular_snapshot_items` |
| `dashboard.json` | 由视频表和统计表实时拼装或缓存 |
| `video_stats.json` | `video_stats` |
| `danmaku_index.json` | 可由 `danmakus` 表索引或对象储存索引替代 |
| `danmakus/<BVID>.json` | `danmakus` 按 `bvid/cid/date` 查询 |
| `accounts.txt` | `accounts` |
| 内存 Session | `sessions` |
| 内存任务表 | `jobs`、`job_events` |
| `ai_analysis/cache` | `ai_analysis_cache` |
| `usage_stats.json` | `ai_usage_events` |

建议迁移时不要一次性把所有弹幕明细强行塞进主流程。优先迁移账号、榜单、统计和任务状态，弹幕明细可以继续保留拆分文件，等查询需求稳定后再决定是否进入数据库。

## PPT 展示重点

- 用“旧结构：榜单切换读取整份弹幕”对比“新结构：轻量榜单加单视频按需加载”。
- 展示 `dashboard.json`、`video_stats.json`、`danmaku_index.json`、`danmakus/<BVID>.json` 四类文件的职责。
- 说明释放分为前端内存释放和本地文件清理。
- 说明该结构既适合本地课程项目，也为数据库迁移预留了表结构方向。
