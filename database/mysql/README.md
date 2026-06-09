# MySQL 数据库准备说明

这个目录用于保存项目第一版 MySQL 数据模型。当前 MySQL 还没有接入 `server.py`，所以即使你执行了建表脚本，现有项目仍然会继续使用 `data/accounts.txt`、`web/data/*.json` 等文件模式运行。

换句话说：这里是“先准备数据库结构”，不是“立刻切换数据库”。

## 文件说明

- `001_schema.sql`：创建 `danmaku_dashboard` 数据库和第一版数据表。
- `config/mysql.example.json`：MySQL 连接配置示例。后续本地真实配置应复制为 `config/mysql.local.json`。

`config/mysql.local.json` 已加入 `.gitignore`，因为里面会保存本地数据库密码，不能提交。

## 推荐本地配置方式

建议为本项目单独创建 MySQL 用户，不要在应用代码里使用 `root`。为了更安全，建议分成两个账号：

- `danmaku_app`：项目运行时使用，只负责读写业务数据。
- `danmaku_migrator`：建表、迁移和结构调整时临时使用，不放进正式运行配置。

```sql
CREATE USER IF NOT EXISTS 'danmaku_app'@'localhost' IDENTIFIED BY 'change-this-password';
GRANT SELECT, INSERT, UPDATE, DELETE
ON danmaku_dashboard.* TO 'danmaku_app'@'localhost';

CREATE USER IF NOT EXISTS 'danmaku_migrator'@'localhost' IDENTIFIED BY 'change-this-migration-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
ON danmaku_dashboard.* TO 'danmaku_migrator'@'localhost';

FLUSH PRIVILEGES;
```

执行建表脚本：

```bash
mysql -u root -p < database/mysql/001_schema.sql
```

也可以在 MySQL Workbench 中打开 `001_schema.sql` 手动执行。Workbench 只是可视化工具，不是必须；命令行同样可以完成建库和建表。

## 连接健康检查

当前已经新增 MySQL 工具模块：

```text
src/db/mysql_config.py
src/db/mysql_health.py
src/db/mysql_apply_schema.py
src/db/mysql_migrate_from_files.py
src/db/mysql_export_to_files.py
src/db/mysql_bootstrap_owner.py
```

使用步骤：

1. 复制 `config/mysql.example.json` 为 `config/mysql.local.json`。
2. 修改 `mysql.local.json` 中的 `user`、`password`、`database` 等本地配置。
3. 如本机还没有 Python MySQL 驱动，安装：

```bash
python -m pip install mysql-connector-python
```

4. 在项目根目录执行：

```bash
python -m src.db.mysql_health
```

也可以输出 JSON，方便后续接入管理员页或脚本：

```bash
python -m src.db.mysql_health --json
```

这个健康检查只执行 `SELECT 1`，不会建表、不会写入数据，也不会让 `server.py` 切换到 MySQL。

## 建表、导入与导出命令

如果希望直接用 Python 执行建库建表脚本，可以使用：

```bash
python -m src.db.mysql_apply_schema
```

注意：建表需要使用有 `CREATE`、`ALTER` 等权限的迁移账号。正式运行账号 `danmaku_app` 不建议拥有这些结构变更权限。

文件模式导入 MySQL 先做 dry-run：

```bash
python -m src.db.mysql_migrate_from_files
```

检查报告确认无误后，再正式写入：

```bash
python -m src.db.mysql_migrate_from_files --apply
```

如需连同 `data/archive/` 历史归档一起导入：

```bash
python -m src.db.mysql_migrate_from_files --include-archives
python -m src.db.mysql_migrate_from_files --include-archives --apply
```

默认弹幕上限为 200 万条，超过会拒绝正式导入并要求先分批或调整：

```bash
python -m src.db.mysql_migrate_from_files --max-danmakus 2000000
```

从 MySQL 导出回文件模式会写入新目录，不覆盖当前运行数据：

```bash
python -m src.db.mysql_export_to_files
```

默认输出目录形如：

```text
data/mysql_export/YYYYMMDD_HHMMSS/
```

导出的 `accounts.txt` 会保留密码哈希和 API 开关，但不会导出本地访问令牌或模型 API Key 明文。

创建 MySQL owner 账号必须在服务器本地命令行执行：

```bash
python -m src.db.mysql_bootstrap_owner --account owner_main --username 项目负责人 --email owner@example.com --password Owner12345
```

如果账号已存在且确认要更新为 owner，才添加 `--replace`。这个能力不应该做成网页按钮。

## 账号角色与 API 能力

MySQL 规划中保留三个账号角色：

```text
normal < admin < owner
```

其中：

- `normal`：普通账号，查看和搜索弹幕数据。
- `admin`：管理员，负责日常管理，例如普通用户状态、搜索间隔、全局屏蔽词、当前热门榜单更新、AI 缓存清理。
- `owner`：项目负责人，继承管理员权限，并负责项目级高危操作，例如文件/MySQL 存储后端切换、数据迁移、备份、回档、管理员权限管理。

API 能力不是独立角色，而是账号能力状态：`users.api_enabled=true`，并且 `ai_provider_configs` 中存在当前账号自己的启用配置时，该账号才能调用 AI 分析。管理员和 owner 也必须配置自己的模型接口后才能调用 AI，不能借用或查看普通用户的 API Key。

这个设计是为了避免“管理员”权限过大。管理员可以管理普通功能，但不能随意切换数据库、回滚用户数据、查看普通用户 API 使用情况，或把别人提升为最高权限。

当前文件模式已经启用运行时 `owner` 规则：`owner` 继承管理员接口权限，普通 `admin` 不能修改管理员或 owner 账号，也不能把任何账号切换成 owner。历史归档榜单保持只读，不允许任何角色写回当天快照。后续接入 MySQL 时继续保持同一套接口边界：

```text
日常管理接口：require_admin()
项目级高危接口：require_owner()
高权限账号管理：require_owner()
账号自己的 API 开关和模型配置：require_same_account()
```

owner 账号不允许通过页面或普通 HTTP 接口创建、提升或复制，只能由服务器本地初始化脚本或人工建库创建。这样可以降低 owner 账号被盗后批量制造更多 owner 账号的风险。

## 文件与 MySQL 互通设计

后续数据管理会支持两种后端：

- `file`：当前稳定模式，继续使用 `data/*.json`、`data/accounts.txt` 和 `web/data/*.json`。
- `mysql`：后续正式数据库模式。

两种模式之间要尽量互通，因此表结构新增了：

- `system_settings`：保存项目级配置，例如当前 `storage.backend` 是 `file` 还是 `mysql`。
- `storage_backend_changes`：记录文件模式与 MySQL 模式的切换请求、执行状态和结果。
- `data_snapshots`：记录文件快照或 MySQL 备份的位置、校验值和摘要。
- `storage_sync_runs`：记录 `file_to_mysql`、`mysql_to_file`、`bidirectional_check` 等同步任务。
- `rollback_runs`：记录用户数据或项目数据回档操作。

重要边界：

- 切换存储后端前必须先生成快照。
- 第一次迁移建议先做 `dry_run=true`，只检查不写入。
- 从文件导入 MySQL 后，应做数量、BVID、账号、弹幕 hash 等校验。
- 从 MySQL 导出回文件时，应生成新的文件目录或压缩包，不直接覆盖当前可运行数据。
- 真正覆盖或回档前，必须由 `owner` 确认。

## 回档设计

回档分两类：

- 用户级回档：例如恢复某个用户的个人资料、个人屏蔽词、自定义榜单、AI Provider 配置。
- 项目级回档：例如恢复全部账号、热门榜单归档、弹幕库、AI 报告缓存。

建议规则：

- 用户自己不能直接回档服务器数据。
- `admin` 可以查看部分历史记录，但不能执行回档。
- `owner` 可以执行回档，但默认先执行 dry-run。
- 每次回档必须写入 `rollback_runs` 和 `audit_logs`。
- 回档前自动创建 `pre_rollback` 快照，避免回档失败后无法恢复。

## 安全要求

- 不要在 SQL 文件中写入真实 API Key。
- 不要提交 `config/mysql.local.json`。
- 用户密码继续保存哈希值；迁移时直接保留当前 PBKDF2 字符串，不要还原或保存明文密码。
- 用户自带模型 API Key 只能保存为加密 JSON，思路与当前 `data/secure/` 一致。
- 本地访问令牌只用于本项目登录/接口访问，不等同于第三方模型 API Key；数据库中只保存哈希和尾号。
- 每个账号的模型 API 配置必须按 `account_id` 绑定查询，不能出现不同账号之间配置互窜。
- 后续写 Python 数据库访问代码时，所有 SQL 都必须使用参数化查询，不要拼接用户输入。
- `owner` 账号数量应尽量少，建议只保留 1 个主账号和 1 个备用账号。
- `owner` 的权限提升、后端切换、数据回档必须写入审计日志。
- 项目运行配置中只使用 `danmaku_app`，不要把 `danmaku_migrator` 写入正式配置。

## 热门榜单更新进度可视化

表结构中已经预留 `jobs` 和 `job_events` 两张表。它们用于记录后台任务，例如“刷新热门榜单”。后续管理员页面可以据此显示：

- 当前步骤；
- 进度百分比；
- 警告或错误事件；
- 最终结果摘要；
- 耗时和失败原因。

这部分是为了解决当前热门榜单更新时页面看起来“卡住”的问题。实际情况可能是服务器仍在抓取数据，但同步接口没有任何进度反馈。

## 当前状态

当前 MySQL 已完成独立工具链，但默认仍未切换 `server.py` 的运行后端：

- 可以先阅读表结构和迁移计划；
- 可以在本地 MySQL 中手动建库建表，或使用 `python -m src.db.mysql_apply_schema`；
- 可以用 `python -m src.db.mysql_health` 检查本地连接；
- 可以用 `python -m src.db.mysql_migrate_from_files` 做文件导入 dry-run；
- 可以用 `python -m src.db.mysql_migrate_from_files --apply` 正式导入；
- 可以用 `python -m src.db.mysql_export_to_files` 导出回新文件目录；
- 可以用 `python -m src.db.mysql_bootstrap_owner` 在服务器本地创建 owner；
- 不会影响当前页面运行；
- 不会自动替换 `AccountStore` 或 `web/data/*.json`。

后续若要让主服务直接读写 MySQL，再通过 `STORAGE_BACKEND=file|mysql` 开关逐步替换 `AccountStore`、SessionStore、视频仓储和弹幕查询仓储。
