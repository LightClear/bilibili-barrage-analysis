# MySQL 数据库迁移计划

这份文档用于规划 MySQL 接入，但当前不会改变稳定的文件模式运行。也就是说，1.1 版本仍然可以继续使用 `data/*.json`、`data/accounts.txt` 和 `web/data/*.json`；MySQL 先作为独立能力准备和测试。

## 目标

先建立一套 MySQL 数据层，为后续逐步替换文件存储做准备。第一阶段只新增：

- MySQL 建表脚本；
- MySQL 配置示例；
- 数据库迁移说明；
- 后续 Python 仓储层设计。

当前阶段不会让 `server.py` 读取或写入 MySQL。

## 当前文件存储现状

当前项目实际运行时主要依赖这些文件：

- `data/accounts.txt`：DEMO 账号、角色、PBKDF2 密码哈希、API 开关、本地访问令牌摘要、个人资料。
- `data/user_block_words/<账号>.txt`：每个账号独立的屏蔽词。
- `config/block_words.txt`：全局屏蔽词。
- `data/secure/api_providers.json`：加密后的用户模型 API 配置。
- `data/secure/server_secret.key`：用于解密模型 API 配置的本机密钥。
- `web/data/dashboard.json`：导出的仪表盘汇总和热门视频列表。
- `web/data/danmakus.json`：导出的弹幕明细。
- `data/archive/YYYY-MM-DD/today_hot_videos.json`：每日热门视频归档。
- `data/archive/YYYY-MM-DD/today_danmakus.json`：每日热门弹幕归档。
- `data/ai_analysis/*.txt` 和 `*.json`：最新 AI 报告和词云文件。
- `data/ai_analysis/cache/`：AI 报告缓存。

这些文件模式适合课程展示和本地 DEMO，但不适合长期多人使用。

## 为什么选择 MySQL

MySQL 适合作为下一阶段数据库，主要原因是：

- 支持多人并发访问；
- 支持索引，可以更好地查询大量弹幕；
- 有 MySQL Workbench 等可视化工具，便于查看数据；
- 部署方式更接近真实 Web 应用；
- 后续可以配合任务表、审计表和权限表做更完整的后台系统。

Workbench 不是必须的。项目应优先保留 SQL 文件和 Python 脚本，这样建库、迁移和检查都可以复现。Workbench 可以用来辅助查看表结构和调试查询。

## 当前新增的 MySQL 文件

当前阶段已经准备：

- `database/mysql/001_schema.sql`
- `database/mysql/README.md`
- `config/mysql.example.json`
- `src/db/mysql_config.py`
- `src/db/mysql_health.py`
- `src/db/mysql_connection.py`
- `src/db/mysql_apply_schema.py`
- `src/db/mysql_migration.py`
- `src/db/mysql_migrate_from_files.py`
- `src/db/mysql_export_to_files.py`
- `src/db/mysql_bootstrap_owner.py`
- `.gitignore` 中忽略 `config/mysql.local.json`

真实本地连接配置应保存为：

```text
config/mysql.local.json
```

该文件不能提交。

## 表结构概览

账号、安全和权限相关：

- `users`：账号、用户名、邮箱、PBKDF2 密码哈希、角色、API 开关、本地访问令牌摘要、搜索间隔、禁用状态。角色预留 `owner`，用于项目级高危操作。
- `sessions`：后续用于持久化登录会话和 CSRF Token 哈希；当前代码已抽出 `SessionStore`，默认仍使用内存实现。
- `login_attempts`：记录登录失败次数、验证码门槛和短时锁定状态。
- `audit_logs`：记录管理员操作和敏感数据修改。

用户设置：

- `user_block_words`：账号级屏蔽词。
- `global_block_words`：管理员维护的全局屏蔽词。
- `api_provider_configs`：用户自带模型服务配置，API Key 只保存加密 JSON。

视频和弹幕数据：

- `videos`：以 BVID 为核心的视频元数据和互动指标。
- `video_pages`：多 P 视频的 cid、分 P 标题和时长。
- `danmakus`：弹幕明细，按 `bvid`、`cid`、视频内时间、发送时间、用户哈希和内容前缀建立索引。
- `popular_snapshots`：每日热门榜单快照。
- `custom_lists` / `custom_list_videos`：账号级自定义榜单。

AI 和任务：

- `ai_reports`：AI 报告、词云 JSON、模型、分析模式和缓存 hash。
- `jobs`：后台任务主表，例如热门榜单更新任务。
- `job_events`：任务执行过程中的事件，用于进度可视化。

项目级数据治理：

- `system_settings`：保存项目级配置，例如 `storage.backend=file|mysql`。
- `storage_backend_changes`：记录存储后端切换请求和结果。
- `data_snapshots`：记录文件快照或 MySQL 备份。
- `storage_sync_runs`：记录文件与 MySQL 互通同步任务。
- `rollback_runs`：记录用户数据或项目数据回档任务。

## 账号角色与 owner 权限级别

MySQL 模式建议把账号角色分为三级；当前文件模式也已经按同一规则启用运行时判断：

```text
normal < admin < owner
```

`owner` 是项目负责人权限，位于管理员之上。它解决的问题是：管理员需要能维护用户和日常数据，但不应该能随意切换存储后端、回档数据、提升别人为最高权限。否则管理员误操作或账号泄露时，影响范围太大。

建议权限边界：

- `normal`：查看仪表盘、筛选弹幕、维护自己的个人资料和个人屏蔽词。
- `admin`：包含日常后台能力，例如普通用户禁用、普通用户搜索间隔调整、全局屏蔽词、当前热门榜单更新、AI 缓存清理。
- `owner`：继承 `admin` 的全部能力，并包含项目级高危能力，例如文件/MySQL 切换、迁移、备份、回档、管理员权限管理、查看完整审计日志。

API 能力不是账号角色。账号必须同时满足 `api_enabled=true` 且存在当前账号自己的 `api_provider_configs` 启用配置，才能执行 AI 分析。管理员和 owner 也不能使用其他账号的模型 API 配置。

后续代码接口建议分成两类检查：

```text
require_admin()：日常管理接口。
require_owner()：存储切换、迁移、备份、回档、权限提升等高危接口。
require_same_account()：账号自己的 API 开关、模型配置和个人设置。
```

文件模式当前已经加入 `owner_demo / Owner12345` 默认账号，用来演示最高权限。普通管理员不能修改管理员或 owner 账号，也不能把普通账号提升为管理员；owner 不能在页面上撤销或禁用自己的 owner 权限，避免误操作导致最高权限丢失。owner 账号不允许通过网页或普通接口提升，只能由服务器本地初始化脚本或人工建库创建。

会话层当前已经拆出 `src/session_store.py`，`MemorySessionStore` 的字段与 `sessions` 表保持接近：账号、CSRF Token、演示身份、创建时间、最近访问时间和过期时间。真正切换 MySQL 时建议新增 `MySQLSessionStore`，并只保存 Session Token 与 CSRF Token 的哈希，避免数据库泄露后可直接伪造登录态。

## 文件与 MySQL 互通

你的目标不是“接入 MySQL 后彻底抛弃文件”，而是让两边尽量可互通。这是合理的，原因是：

- 文件模式适合课程演示，启动简单。
- MySQL 模式适合长期保存、多用户和大规模弹幕查询。
- 互通能力可以让你在测试 MySQL 失败时回到文件模式，不影响展示。

建议互通方向：

- `file_to_mysql`：从 `data/accounts.txt`、`data/archive/`、`web/data/*.json` 等文件导入 MySQL。
- `mysql_to_file`：把 MySQL 中的数据导出回文件模式，生成新的 JSON 文件或压缩包。
- `bidirectional_check`：只做校验，不写入，用于比较账号数、视频数、弹幕数、热门日期、hash 等是否一致。

切换后端时应遵守：

- 切换前自动创建 `pre_switch` 快照。
- 第一次迁移默认 `dry_run=true`。
- 数据校验通过后才允许真正切换。
- 切换记录写入 `storage_backend_changes`。
- 同步任务写入 `storage_sync_runs`，详细步骤写入 `jobs` 和 `job_events`。
- 修改 `system_settings.storage.backend` 的权限只开放给 `owner`。

## 用户数据回档

回档是比普通编辑更危险的操作，因为它可能覆盖现有数据。建议按两个粒度处理：

- 用户级回档：个人资料、个人屏蔽词、自定义榜单、用户模型 API 配置、用户 AI 报告。
- 项目级回档：全部账号、全局屏蔽词、热门榜单归档、视频库、弹幕库、AI 缓存。

推荐安全流程：

1. `owner` 选择快照和回档范围。
2. 系统先执行 dry-run，展示将新增、覆盖、删除、跳过的数量。
3. `owner` 二次确认。
4. 系统创建 `pre_rollback` 快照。
5. 执行回档任务。
6. 写入 `rollback_runs`、`jobs`、`job_events` 和 `audit_logs`。

`admin` 可以查看部分回档记录和任务状态，但不建议允许 `admin` 执行回档。

## 热门榜单更新进度可视化

热门榜单更新可能耗时较长，因为它要访问 B 站接口，获取热门视频、视频信息和弹幕数据。同步按钮会让页面看起来像卡住，即使服务器其实仍在工作。

后续任务系统应使用：

- `jobs.status`：任务状态，取值包括 `pending`、`running`、`success`、`failed`、`cancelled`。
- `jobs.progress`：0 到 100 的进度百分比。
- `jobs.message`：当前对用户可见的步骤说明。
- `job_events`：详细事件，例如“获取热门列表”“采集第 12/50 个视频”“写入归档”“导出前端数据”。

管理员页面可以展示：

- 顶部进度条；
- 当前步骤文字；
- 最近事件列表；
- 警告和错误标签；
- 总耗时和最终结果摘要。

这部分已经先在文件模式下用 `src/job_manager.py` 的内存任务表实现，不必等 MySQL 真正接入。等 MySQL 接入后，再把任务状态落盘到 `jobs` 和 `job_events`。

## 历史归档只读与当前视频数据更新

热门榜单的日期选择分为两类：

- `当前榜单`：代表今天重新从 B 站热门接口获取的榜单。更新时可以重新获取热门列表、弹幕，并重新导出 `web/data/dashboard.json` 和 `web/data/danmakus.json`。
- `YYYY-MM-DD` 历史日期：代表当日已经保存下来的热门榜单快照。这个快照的意义是“那一天榜单上有哪些视频、排名是什么”，所以不应该用今天的热门榜单覆盖它。

因此历史归档日期保持只读：

- `data/archive/YYYY-MM-DD/today_hot_videos.json` 不再由页面或 HTTP 接口写回；
- `data/archive/YYYY-MM-DD/today_danmakus.json` 不再由页面或 HTTP 接口写回；
- `POST /api/jobs/refresh-archive-date` 已停用并返回 410；
- 从历史日期中选择视频时，页面读取的是当天归档文件中的视频和弹幕；
- 如果需要获取该视频的最新数据，使用“更新当前视频数据”按钮重新发起 BV 获取任务；
- 新获取的数据只进入页面搜索历史/缓存库，不修改原归档快照。

当前视频数据更新复用 BV 搜索后台任务：

```text
POST /api/jobs/search
请求体：{"bvid":"BV...", "include_history": false}
频率：与当前账号的搜索时间间隔一致。
效果：重新获取当前视频的新元数据和弹幕，写入页面历史缓存，不写回归档文件。
```

后续接入 MySQL 时，这个功能建议映射到：

- `popular_snapshots`：保存某天榜单快照，包含日期、BVID、rank、来源和创建时间；
- `videos`：保存视频元数据，允许按 BVID 更新；
- `danmakus`：保存弹幕明细，建议按 BVID/CID 分批替换或按采集批次标记；
- `jobs` / `job_events`：保存更新任务和进度事件。

数据库模式下也应保留这个边界：历史快照表 `popular_snapshots` 表示当天榜单事实，不应被“获取最新视频数据”改写；最新视频数据应写入 `videos`、`video_pages`、`danmakus` 或新的采集批次表。

## 推荐迁移顺序

建议在稳定的 1.1 文件版本之后按顺序处理：

1. 编写只读 MySQL 健康检查脚本。此步骤已完成，使用 `python -m src.db.mysql_health`。
2. 编写建表 CLI。此步骤已完成，使用 `python -m src.db.mysql_apply_schema`。
3. 编写 `owner` 初始化脚本，只允许本地命令行执行，避免普通页面直接创建最高权限账号。此步骤已完成，使用 `python -m src.db.mysql_bootstrap_owner`。
4. 编写文件到 MySQL 的 dry-run 校验脚本。此步骤已完成，使用 `python -m src.db.mysql_migrate_from_files`。
5. 将 `data/accounts.txt` 迁移到 `users`。导入脚本已支持，正式写入需添加 `--apply`。
6. 迁移全局屏蔽词和账号级屏蔽词。导入脚本已支持。
7. 迁移加密后的 AI Provider 配置。导入脚本已支持，仍保存加密 JSON，不解密输出。
8. 迁移视频和分 P 信息。导入脚本已支持当前数据；历史归档需添加 `--include-archives`。
9. 迁移热门榜单快照。导入脚本已支持当前日期和历史日期。
10. 分批迁移弹幕。导入脚本已支持，默认 200 万条上限，超过需分批或提高 `--max-danmakus`。
11. 增加 `mysql_to_file` 导出脚本，保证可以回退到文件模式。此步骤已完成，使用 `python -m src.db.mysql_export_to_files`，并且不会覆盖当前运行目录。
12. 迁移 AI 报告和缓存元数据。当前尚未接入，后续可根据 `ai_reports` 表补充。
13. 增加 `STORAGE_BACKEND=file|mysql`，默认仍为 `file`。
14. 增加 `system_settings.storage.backend` 的 owner-only 修改接口。
15. 一次只切换一个功能到仓储层，避免大范围故障。

## 后续 Python 代码结构

推荐后续新增：

```text
src/db/
  __init__.py
  mysql_config.py
  mysql_health.py
  mysql_connection.py
  mysql_apply_schema.py
  mysql_migration.py
  mysql_migrate_from_files.py
  mysql_export_to_files.py
  mysql_bootstrap_owner.py
  repositories.py
```

`mysql_config.py` 负责读取配置，优先级建议是：

1. 环境变量；
2. `config/mysql.local.json`；
3. `config/mysql.example.json` 只作为模板，不应作为真实密码来源。

当前健康检查支持 `DANMAKU_MYSQL_CONFIG` 和 `BILI_MYSQL_CONFIG` 两个环境变量；如果都没有设置，则读取 `config/mysql.local.json`。它不会把 `config/mysql.example.json` 当作真实连接配置，避免误用模板密码。

`mysql_connection.py` 应提供连接和事务上下文。

`repositories.py` 应封装 SQL，避免业务代码到处直接写 SQL。例如：

- `get_user_by_account(account)`
- `save_user(user)`
- `list_effective_block_words(account)`
- `upsert_video(video)`
- `insert_danmakus(rows)`
- `create_job(type, account)`
- `append_job_event(job_id, message, progress)`
- `get_system_setting(key)`
- `set_system_setting(key, value, actor)`
- `create_data_snapshot(scope, backend, actor)`
- `record_storage_sync_run(direction, scope, actor)`
- `record_rollback_run(snapshot_id, scope, actor)`

后续 `server.py` 和其他业务代码应调用仓储方法，而不是直接拼 SQL。

## 安全要求

- 不保存明文密码。
- 不保存明文模型 API Key。
- 模型 API Key 保存为加密 JSON，并且加密密钥不能和数据库备份放在一起泄露。
- 所有 SQL 必须使用参数化查询。
- 为项目创建单独的 MySQL 用户，不要在应用里使用 `root`。
- 数据库用户只授予必要权限。
- `config/mysql.local.json` 不提交。
- 日志中不能记录 API Key、Session Token、CSRF Token 或完整数据库连接串。
- 管理员操作应写入审计日志。
- `owner` 操作必须写入审计日志，尤其是权限提升、存储后端切换、迁移、备份和回档。
- 运行时数据库账号不使用 `CREATE`、`ALTER` 等结构变更权限；结构迁移使用单独的迁移账号。
- 回档和存储切换默认先 dry-run，再二次确认。

## 为什么不立即接入 MySQL

当前项目在文件模式下已经稳定。如果直接把账号、Session、弹幕、AI 报告全部切到 MySQL，会导致改动范围过大，排错成本也会变高。

更稳妥的路径是：

1. 先完成稳定的文件模式 1.1；
2. 独立准备和测试 MySQL；
3. 增加存储后端开关；
4. 一个功能一个功能地切换。

这样即使演示时 MySQL 没有启动，项目也可以继续用文件模式运行。
