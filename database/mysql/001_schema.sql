-- Bilibili Danmaku Dashboard 的 MySQL 第一版表结构。
-- 当前文件只负责准备数据库结构，尚未接入 server.py。
-- 执行该脚本不会改变当前项目的文件模式运行方式。

CREATE DATABASE IF NOT EXISTS danmaku_dashboard
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE danmaku_dashboard;

-- 一、账号、会话与安全
-- users：保存账号基础信息、密码哈希、账号角色、API 开关、本地访问令牌摘要和搜索间隔。
-- role 说明：
--   normal：普通用户；
--   admin：管理员，负责日常用户管理、榜单更新、屏蔽词等；
--   owner：项目负责人，位于管理员之上，只用于存储后端切换、迁移、回档和权限提升等高危操作。
-- API 能力不是角色：必须同时满足 api_enabled=true 且 ai_provider_configs 中存在当前账号自己的启用配置。
-- owner 不允许通过网页或普通接口提升，只能由服务器本地初始化脚本或人工建库创建。
-- 注意：password_hash 保存当前 PBKDF2 字符串，不保存明文密码。
CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account VARCHAR(32) NOT NULL,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL,
  role ENUM('normal', 'admin', 'owner') NOT NULL DEFAULT 'normal',
  gender VARCHAR(16) NOT NULL DEFAULT '未设置',
  birthday DATE NULL,
  api_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  app_api_key_hash CHAR(64) NULL,
  app_api_key_last4 VARCHAR(8) NULL,
  search_interval_seconds INT UNSIGNED NOT NULL DEFAULT 10,
  disabled BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at DATETIME NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_account (account),
  UNIQUE KEY uk_users_email (email),
  KEY idx_users_role (role),
  KEY idx_users_disabled (disabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- sessions：为后续持久化登录态预留。
-- 当前代码已抽出 SessionStore，默认仍使用内存实现；接入 MySQL 后只保存 Session Token 和 CSRF Token 的哈希。
-- identity_role 是 DEMO 身份切换状态，可临时为 api/admin/owner；它不等同于 users.role。
CREATE TABLE IF NOT EXISTS sessions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  session_token_hash CHAR(64) NOT NULL,
  account_id BIGINT UNSIGNED NOT NULL,
  csrf_token_hash CHAR(64) NOT NULL,
  identity_role ENUM('normal', 'api', 'admin', 'owner') NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_sessions_token (session_token_hash),
  KEY idx_sessions_account (account_id),
  KEY idx_sessions_expires (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- login_attempts：记录账号/IP 维度的登录失败状态，用于撞库防护。
-- ip_hash 用于避免直接保存原始 IP。
CREATE TABLE IF NOT EXISTS login_attempts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account VARCHAR(32) NOT NULL,
  ip_hash CHAR(64) NOT NULL,
  failed_count INT UNSIGNED NOT NULL DEFAULT 0,
  captcha_required BOOLEAN NOT NULL DEFAULT FALSE,
  lock_level TINYINT UNSIGNED NOT NULL DEFAULT 0,
  locked_until DATETIME NULL,
  first_failed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_failed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_login_attempts_account_ip (account, ip_hash),
  KEY idx_login_attempts_locked_until (locked_until)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 二、屏蔽词与用户配置
-- user_block_words：账号级屏蔽词，只影响对应用户的数据查看和 AI 分析。
CREATE TABLE IF NOT EXISTS user_block_words (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  word VARCHAR(128) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_block_words (account_id, word),
  KEY idx_user_block_words_word (word),
  CONSTRAINT fk_user_block_words_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- global_block_words：管理员维护的全局屏蔽词，会叠加到所有用户的个人屏蔽词上。
CREATE TABLE IF NOT EXISTS global_block_words (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  word VARCHAR(128) NOT NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_global_block_words_word (word),
  CONSTRAINT fk_global_block_words_creator FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ai_provider_configs：用户自带模型服务配置。
-- api_key_cipher_json 只保存加密后的 Key，不保存明文 API Key。
CREATE TABLE IF NOT EXISTS ai_provider_configs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  provider VARCHAR(32) NOT NULL,
  base_url VARCHAR(512) NOT NULL,
  model VARCHAR(128) NOT NULL,
  api_key_cipher_json JSON NOT NULL,
  api_key_fingerprint CHAR(64) NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ai_provider_account (account_id),
  KEY idx_ai_provider_provider_model (provider, model),
  CONSTRAINT fk_ai_provider_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 三、视频与弹幕数据
-- videos：按 BVID 保存视频元数据和互动指标，是视频相关表的主入口。
CREATE TABLE IF NOT EXISTS videos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bvid VARCHAR(32) NOT NULL,
  aid BIGINT UNSIGNED NULL,
  title VARCHAR(512) NOT NULL,
  owner VARCHAR(128) NULL,
  cover_url VARCHAR(1024) NULL,
  description MEDIUMTEXT NULL,
  view_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  like_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  favorite_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  coin_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  danmaku_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  pubdate DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_videos_bvid (bvid),
  KEY idx_videos_aid (aid),
  KEY idx_videos_owner (owner),
  KEY idx_videos_danmaku_count (danmaku_count),
  KEY idx_videos_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- video_pages：多 P 视频的分 P 信息。
-- bvid + cid 唯一，后续切换分 P 时可直接按 cid 查询弹幕池。
CREATE TABLE IF NOT EXISTS video_pages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bvid VARCHAR(32) NOT NULL,
  cid BIGINT UNSIGNED NOT NULL,
  page_index INT UNSIGNED NOT NULL DEFAULT 1,
  part_title VARCHAR(512) NOT NULL DEFAULT '',
  duration_seconds INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_video_pages_bvid_cid (bvid, cid),
  KEY idx_video_pages_bvid_index (bvid, page_index),
  KEY idx_video_pages_cid (cid),
  CONSTRAINT fk_video_pages_video FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- danmakus：弹幕明细表，后续数据量最大。
-- content_hash 用于去重，content 前缀索引用于辅助内容查询。
-- cid 和 user_hash 使用默认值而不是 NULL，避免唯一键在 NULL 上失效。
CREATE TABLE IF NOT EXISTS danmakus (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bvid VARCHAR(32) NOT NULL,
  cid BIGINT UNSIGNED NOT NULL DEFAULT 0,
  time_in_video DECIMAL(10, 3) NOT NULL DEFAULT 0,
  send_timestamp BIGINT UNSIGNED NULL,
  user_hash VARCHAR(128) NOT NULL DEFAULT '',
  content VARCHAR(1000) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  color INT UNSIGNED NULL,
  source VARCHAR(32) NOT NULL DEFAULT 'bilibili',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_danmakus_identity (bvid, cid, time_in_video, user_hash, content_hash),
  KEY idx_danmakus_bvid_cid (bvid, cid),
  KEY idx_danmakus_bvid_time (bvid, time_in_video),
  KEY idx_danmakus_bvid_send (bvid, send_timestamp),
  KEY idx_danmakus_user_hash (user_hash),
  KEY idx_danmakus_content_prefix (content(64)),
  CONSTRAINT fk_danmakus_video FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 四、榜单和用户自定义列表
-- popular_snapshots：每日热门榜单快照，保留日期、排名和对应视频。
CREATE TABLE IF NOT EXISTS popular_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  snapshot_date DATE NOT NULL,
  rank_position INT UNSIGNED NOT NULL,
  bvid VARCHAR(32) NOT NULL,
  score BIGINT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_popular_snapshot_rank (snapshot_date, rank_position),
  UNIQUE KEY uk_popular_snapshot_video (snapshot_date, bvid),
  KEY idx_popular_snapshots_bvid (bvid),
  CONSTRAINT fk_popular_snapshots_video FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- custom_lists：用户自定义榜单主表。
CREATE TABLE IF NOT EXISTS custom_lists (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(64) NOT NULL DEFAULT '默认榜单',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_custom_lists_account_name (account_id, name),
  CONSTRAINT fk_custom_lists_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- custom_list_videos：自定义榜单中的视频条目和排序位置。
CREATE TABLE IF NOT EXISTS custom_list_videos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  list_id BIGINT UNSIGNED NOT NULL,
  bvid VARCHAR(32) NOT NULL,
  position INT UNSIGNED NOT NULL DEFAULT 0,
  added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_custom_list_video (list_id, bvid),
  KEY idx_custom_list_position (list_id, position),
  KEY idx_custom_list_bvid (bvid),
  CONSTRAINT fk_custom_list_videos_list FOREIGN KEY (list_id) REFERENCES custom_lists(id) ON DELETE CASCADE,
  CONSTRAINT fk_custom_list_videos_video FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 五、AI 报告与后台任务
-- ai_reports：保存 AI 评价结果、词云 JSON 和缓存 hash。
CREATE TABLE IF NOT EXISTS ai_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NULL,
  report_scope ENUM('current', 'compare') NOT NULL DEFAULT 'current',
  bvid VARCHAR(32) NULL,
  cid BIGINT UNSIGNED NULL,
  compare_bvid VARCHAR(32) NULL,
  provider VARCHAR(32) NOT NULL DEFAULT 'local-demo',
  model VARCHAR(128) NOT NULL DEFAULT '',
  analysis_mode VARCHAR(32) NOT NULL DEFAULT 'summary',
  analysis_hash CHAR(64) NOT NULL,
  report_text MEDIUMTEXT NOT NULL,
  words_json JSON NULL,
  cached BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ai_reports_hash (analysis_hash),
  KEY idx_ai_reports_account (account_id),
  KEY idx_ai_reports_video (bvid, cid),
  KEY idx_ai_reports_created (created_at),
  CONSTRAINT fk_ai_reports_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_ai_reports_video FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- jobs：后台任务主表，例如热门榜单更新。
-- 后续管理员页可以通过该表显示任务状态、进度和结果。
CREATE TABLE IF NOT EXISTS jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id CHAR(36) NOT NULL,
  account_id BIGINT UNSIGNED NULL,
  job_type VARCHAR(64) NOT NULL,
  status ENUM('pending', 'running', 'success', 'failed', 'cancelled') NOT NULL DEFAULT 'pending',
  progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
  message VARCHAR(512) NOT NULL DEFAULT '',
  result_json JSON NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_jobs_job_id (job_id),
  KEY idx_jobs_account_created (account_id, created_at),
  KEY idx_jobs_status_created (status, created_at),
  KEY idx_jobs_type_created (job_type, created_at),
  CONSTRAINT fk_jobs_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- job_events：后台任务的步骤日志。
-- 适合记录“获取热门列表”“采集第 12/50 个视频”“写入归档”等可视化事件。
CREATE TABLE IF NOT EXISTS job_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id CHAR(36) NOT NULL,
  level ENUM('info', 'warning', 'error') NOT NULL DEFAULT 'info',
  step_name VARCHAR(128) NOT NULL DEFAULT '',
  progress TINYINT UNSIGNED NULL,
  message VARCHAR(512) NOT NULL,
  detail_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_job_events_job_created (job_id, created_at),
  CONSTRAINT fk_job_events_job FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 六、项目级数据治理
-- system_settings：项目级配置表。
-- 这里用于保存 STORAGE_BACKEND=file|mysql 等配置。该表的修改权应只开放给 owner。
-- setting_key 使用稳定字符串，例如：
--   storage.backend
--   storage.file_mysql_sync_mode
--   storage.last_successful_snapshot_id
CREATE TABLE IF NOT EXISTS system_settings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  setting_key VARCHAR(128) NOT NULL,
  setting_value_json JSON NOT NULL,
  description VARCHAR(512) NOT NULL DEFAULT '',
  updated_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_system_settings_key (setting_key),
  CONSTRAINT fk_system_settings_user FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- storage_backend_changes：记录存储后端切换请求和结果。
-- 只记录状态和摘要，具体任务步骤仍写入 jobs / job_events。
CREATE TABLE IF NOT EXISTS storage_backend_changes (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id CHAR(36) NULL,
  from_backend ENUM('file', 'mysql') NOT NULL,
  to_backend ENUM('file', 'mysql') NOT NULL,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  status ENUM('pending', 'running', 'success', 'failed', 'cancelled') NOT NULL DEFAULT 'pending',
  requested_by BIGINT UNSIGNED NULL,
  result_json JSON NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_storage_backend_changes_status (status, created_at),
  KEY idx_storage_backend_changes_job (job_id),
  CONSTRAINT fk_storage_backend_changes_job FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_storage_backend_changes_user FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- data_snapshots：文件模式或 MySQL 模式的数据快照登记表。
-- 文件模式可记录压缩包路径；MySQL 模式可记录 dump 文件或备份批次标识。
-- 注意：这里不保存备份文件本体，只保存可追踪的路径、校验值和摘要。
CREATE TABLE IF NOT EXISTS data_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  backend ENUM('file', 'mysql') NOT NULL,
  snapshot_type ENUM('manual', 'pre_migration', 'pre_switch', 'pre_rollback', 'scheduled') NOT NULL DEFAULT 'manual',
  scope ENUM('accounts', 'settings', 'videos', 'danmakus', 'popular_snapshots', 'ai_reports', 'all') NOT NULL DEFAULT 'all',
  snapshot_path VARCHAR(1024) NOT NULL,
  checksum_sha256 CHAR(64) NULL,
  size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  summary_json JSON NULL,
  created_by BIGINT UNSIGNED NULL,
  notes VARCHAR(512) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_data_snapshots_backend_created (backend, created_at),
  KEY idx_data_snapshots_type_created (snapshot_type, created_at),
  CONSTRAINT fk_data_snapshots_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- storage_sync_runs：记录文件与 MySQL 的互通同步。
-- 例如 file_to_mysql 用于从 data/*.json 导入数据库，mysql_to_file 用于导出回文件模式。
CREATE TABLE IF NOT EXISTS storage_sync_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id CHAR(36) NULL,
  direction ENUM('file_to_mysql', 'mysql_to_file', 'bidirectional_check') NOT NULL,
  scope ENUM('accounts', 'block_words', 'api_providers', 'videos', 'danmakus', 'popular_snapshots', 'ai_reports', 'all') NOT NULL DEFAULT 'all',
  source_snapshot_id BIGINT UNSIGNED NULL,
  target_snapshot_id BIGINT UNSIGNED NULL,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  status ENUM('pending', 'running', 'success', 'failed', 'cancelled') NOT NULL DEFAULT 'pending',
  requested_by BIGINT UNSIGNED NULL,
  inserted_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  skipped_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  failed_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  result_json JSON NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_storage_sync_runs_direction_created (direction, created_at),
  KEY idx_storage_sync_runs_status_created (status, created_at),
  KEY idx_storage_sync_runs_job (job_id),
  CONSTRAINT fk_storage_sync_runs_job FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_storage_sync_runs_source_snapshot FOREIGN KEY (source_snapshot_id) REFERENCES data_snapshots(id) ON DELETE SET NULL,
  CONSTRAINT fk_storage_sync_runs_target_snapshot FOREIGN KEY (target_snapshot_id) REFERENCES data_snapshots(id) ON DELETE SET NULL,
  CONSTRAINT fk_storage_sync_runs_user FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- rollback_runs：记录用户数据或项目数据回档操作。
-- 回档属于高危操作，应用层必须限制为 owner 才能执行，并且默认先 dry_run。
CREATE TABLE IF NOT EXISTS rollback_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_id CHAR(36) NULL,
  snapshot_id BIGINT UNSIGNED NOT NULL,
  target_backend ENUM('file', 'mysql') NOT NULL,
  target_scope ENUM('user', 'accounts', 'settings', 'videos', 'danmakus', 'popular_snapshots', 'ai_reports', 'all') NOT NULL,
  target_account_id BIGINT UNSIGNED NULL,
  dry_run BOOLEAN NOT NULL DEFAULT TRUE,
  status ENUM('pending', 'running', 'success', 'failed', 'cancelled') NOT NULL DEFAULT 'pending',
  requested_by BIGINT UNSIGNED NULL,
  affected_counts_json JSON NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_rollback_runs_status_created (status, created_at),
  KEY idx_rollback_runs_target_account (target_account_id, created_at),
  KEY idx_rollback_runs_job (job_id),
  CONSTRAINT fk_rollback_runs_job FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_rollback_runs_snapshot FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(id) ON DELETE RESTRICT,
  CONSTRAINT fk_rollback_runs_target_user FOREIGN KEY (target_account_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_rollback_runs_requester FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 默认仍使用文件模式。真正切换到 mysql 前，必须先完成迁移校验和备份。
INSERT INTO system_settings (setting_key, setting_value_json, description)
VALUES (
  'storage.backend',
  JSON_OBJECT('backend', 'file', 'mysql_ready', false),
  '当前启用的数据存储后端。只能由 owner 修改。'
)
ON DUPLICATE KEY UPDATE setting_key = setting_key;

-- 七、审计日志
-- audit_logs：记录管理员和 owner 操作，尤其是敏感数据修改、权限提升、迁移、回档。
CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  account_id BIGINT UNSIGNED NULL,
  action VARCHAR(128) NOT NULL,
  target_type VARCHAR(64) NOT NULL DEFAULT '',
  target_id VARCHAR(128) NOT NULL DEFAULT '',
  ip_hash CHAR(64) NULL,
  detail_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_logs_account_created (account_id, created_at),
  KEY idx_audit_logs_action_created (action, created_at),
  CONSTRAINT fk_audit_logs_user FOREIGN KEY (account_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
