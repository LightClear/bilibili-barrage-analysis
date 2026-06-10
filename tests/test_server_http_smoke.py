from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import timedelta
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import server
from src.account_demo import AccountStore
from src.danmaku_store import read_video_danmakus
from src.job_manager import JobManager
from src.secure_bili_cookie_store import SecureBiliCookieStore
from src.secure_provider_store import SecureProviderStore
from src.storage import read_json, write_json


@contextmanager
def run_test_server(tmp_path, monkeypatch):
    store = AccountStore(tmp_path / "accounts.txt")
    store.ensure_defaults()
    monkeypatch.setattr(server, "ACCOUNT_STORE", store)
    monkeypatch.setattr(server, "AI_PROVIDER_STORE", SecureProviderStore(tmp_path / "secure"))
    monkeypatch.setattr(server, "BILI_COOKIE_STORE", SecureBiliCookieStore(tmp_path / "secure"))
    with server.STATE_LOCK:
        server.SESSIONS.clear()
        server.SESSION_CSRF_TOKENS.clear()
        server.SESSION_IDENTITY_ROLES.clear()
        server.SESSION_EXPIRES_AT.clear()
        server.SESSION_CREATED_AT.clear()
        server.SESSION_LAST_SEEN_AT.clear()
        server.RATE_LIMITS.clear()
        server.RATE_WINDOWS.clear()
        server.LOGIN_FAILURES.clear()

    httpd = server.LocalThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def request_json(opener, base_url: str, path: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
    data = None
    active_headers = {"Content-Type": "application/json"}
    if headers:
        active_headers.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = Request(f"{base_url}{path}", data=data, headers=active_headers, method=method)
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read().decode("utf-8"))


def test_static_page_has_security_headers_and_keeps_data_private(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener()

        with opener.open(f"{base_url}/index.html", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            headers = dict(resp.headers)

        assert resp.status == 200
        assert "app-core.js" in body
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]

        try:
            opener.open(f"{base_url}/data/accounts.txt", timeout=5)
        except HTTPError as exc:
            assert exc.code == 404


def test_login_csrf_and_admin_permission_flow(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))

        status, headers, session = request_json(opener, base_url, "/api/account/session")
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert session["logged_in"] is False

        status, headers, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        assert login["logged_in"] is True
        assert login["user"]["account"] == "admin_demo"
        assert login["csrf_token"]
        assert "HttpOnly" in headers["Set-Cookie"]
        assert "SameSite=Lax" in headers["Set-Cookie"]

        status, _, csrf_blocked = request_json(
            opener,
            base_url,
            "/api/identity",
            method="POST",
            payload={"role": "api"},
        )
        assert status == 403
        assert "CSRF" in csrf_blocked["error"]

        status, _, identity = request_json(
            opener,
            base_url,
            "/api/identity",
            method="POST",
            payload={"role": "api"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        assert identity["role"] == "api"

        status, _, owner_blocked = request_json(
            opener,
            base_url,
            "/api/identity",
            method="POST",
            payload={"role": "owner"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 403
        assert "owner" in owner_blocked["error"]


def test_normal_user_cannot_open_admin_user_list(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "normal"

        status, _, payload = request_json(opener, base_url, "/api/admin/users")
        assert status == 403
        assert "管理员" in payload["error"]


def test_job_debug_payload_is_hidden_from_normal_user(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "JOB_MANAGER", JobManager(max_jobs=5, max_events_per_job=5))
    with server.STATE_LOCK:
        server.JOB_RESULTS.clear()

    with run_test_server(tmp_path, monkeypatch) as base_url:
        job = server.JOB_MANAGER.create(server.BVID_SEARCH_JOB_TYPE, account="user_demo", message="任务已创建")
        server.JOB_MANAGER.add_event(
            job["job_id"],
            "分段采集完成",
            progress=80,
            step_name="segment_done",
            detail={"segment_count": 12, "reported_count": 3000},
        )
        server.JOB_MANAGER.succeed(job["job_id"], "任务完成", {"danmaku_count": 120})
        server.store_job_full_result(job["job_id"], {
            "ok": True,
            "video": {"bvid": "BVDEBUG001", "danmaku_fetch": {"warning": "调试警告"}},
            "danmakus": [],
            "danmaku_fetch": {"warning": "调试警告", "segment_count": 12},
        })

        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "normal"

        status, _, payload = request_json(opener, base_url, f"/api/jobs/status?job_id={job['job_id']}")
        assert status == 200
        assert payload["job"]["events"] == []
        assert payload["job"]["result"] == {}
        assert payload["job"]["account"] == ""

        status, _, result = request_json(opener, base_url, f"/api/jobs/result?job_id={job['job_id']}&consume=0")
        assert status == 200
        assert "danmaku_fetch" not in result
        assert "danmaku_fetch" not in result["video"]


def test_job_debug_payload_is_visible_to_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "JOB_MANAGER", JobManager(max_jobs=5, max_events_per_job=5))
    with server.STATE_LOCK:
        server.JOB_RESULTS.clear()

    with run_test_server(tmp_path, monkeypatch) as base_url:
        job = server.JOB_MANAGER.create(server.BVID_SEARCH_JOB_TYPE, account="user_demo", message="任务已创建")
        server.JOB_MANAGER.add_event(
            job["job_id"],
            "分段采集完成",
            progress=80,
            step_name="segment_done",
            detail={"segment_count": 12, "reported_count": 3000},
        )
        server.JOB_MANAGER.succeed(job["job_id"], "任务完成", {"danmaku_count": 120})

        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "admin"

        status, _, payload = request_json(opener, base_url, f"/api/jobs/status?job_id={job['job_id']}")
        assert status == 200
        assert payload["job"]["events"]
        assert payload["job"]["events"][-2]["detail"]["segment_count"] == 12
        assert payload["job"]["result"]["danmaku_count"] == 120


def test_disabled_account_login_returns_ban_message(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        admin_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, admin_login = request_json(
            admin_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200

        status, _, updated = request_json(
            admin_opener,
            base_url,
            "/api/admin/users/update",
            method="POST",
            payload={"account": "user_demo", "disabled": True},
            headers={"X-CSRF-Token": admin_login["csrf_token"]},
        )
        assert status == 200
        assert updated["user"]["disabled"] is True

        user_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(
            user_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 403
        assert payload["disabled"] is True
        assert "封禁" in payload["error"]


def test_legacy_refresh_popular_endpoint_is_disabled(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        anonymous = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(anonymous, base_url, "/api/refresh-popular?limit=1")
        assert status == 410
        assert "已停用" in payload["error"]

        user_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            user_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "normal"

        status, _, payload = request_json(user_opener, base_url, "/api/refresh-popular?limit=1")
        assert status == 410
        assert "已停用" in payload["error"]

        status, _, payload = request_json(
            user_opener,
            base_url,
            "/api/refresh-popular",
            method="POST",
            payload={},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 410
        assert "已停用" in payload["error"]


def test_admin_ai_usage_is_owner_only(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        admin_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, admin_login = request_json(
            admin_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        assert admin_login["user"]["role"] == "admin"

        status, _, admin_payload = request_json(admin_opener, base_url, "/api/admin/ai-usage")
        assert status == 403
        assert "owner" in admin_payload["error"]

        owner_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, owner_login = request_json(
            owner_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "owner_demo", "password": "Owner12345"},
        )
        assert status == 200
        assert owner_login["user"]["role"] == "owner"

        status, _, owner_payload = request_json(owner_opener, base_url, "/api/admin/ai-usage")
        assert status == 200
        assert "summary" in owner_payload


def test_admin_storage_cleanup_endpoint_previews_and_removes_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    web_data = tmp_path / "web" / "data"
    write_json(web_data / "danmaku_index.json", {
        "videos": {
            "BVKEEPHTTP": {"file": "danmakus/BVKEEPHTTP.json", "count": 1},
        },
    })
    write_json(web_data / "danmakus" / "BVKEEPHTTP.json", [{"content": "保留"}])
    write_json(web_data / "danmakus" / "BVORPHANHTTP.json", [{"content": "删除"}])
    write_json(web_data / "danmakus.json", [{"content": "旧全量"}])

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200

        status, _, usage = request_json(opener, base_url, "/api/admin/storage-usage")
        assert status == 200
        assert usage["categories"]["legacy_frontend_danmakus"]["exists"] is True

        options = {
            "dry_run": True,
            "legacy_frontend_danmakus": True,
            "current_orphan_danmakus": True,
            "archive_orphan_danmakus": False,
            "ai_cache_expired": False,
        }
        status, _, preview = request_json(
            opener,
            base_url,
            "/api/admin/storage-cleanup",
            method="POST",
            payload=options,
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        paths = {item["path"] for item in preview["candidates"]}
        assert "web/data/danmakus.json" in paths
        assert "web/data/danmakus/BVORPHANHTTP.json" in paths
        assert (web_data / "danmakus.json").exists()

        status, _, cleaned = request_json(
            opener,
            base_url,
            "/api/admin/storage-cleanup",
            method="POST",
            payload={**options, "dry_run": False},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        assert cleaned["removed"] == 2

    assert not (web_data / "danmakus.json").exists()
    assert not (web_data / "danmakus" / "BVORPHANHTTP.json").exists()
    assert (web_data / "danmakus" / "BVKEEPHTTP.json").exists()


def test_owner_can_switch_to_owner_demo_identity(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "owner_demo", "password": "Owner12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "owner"

        status, _, identity = request_json(
            opener,
            base_url,
            "/api/identity",
            method="POST",
            payload={"role": "owner"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        assert identity["role"] == "owner"
        assert identity["is_admin"] is True


def test_archive_date_refresh_job_is_disabled_to_keep_archives_read_only(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        admin_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, admin_login = request_json(
            admin_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        assert admin_login["user"]["role"] == "admin"

        status, _, admin_payload = request_json(
            admin_opener,
            base_url,
            "/api/jobs/refresh-archive-date",
            method="POST",
            payload={"date": "2026-05-01"},
            headers={"X-CSRF-Token": admin_login["csrf_token"]},
        )
        assert status == 410
        assert "只读" in admin_payload["error"]

        owner_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, owner_login = request_json(
            owner_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "owner_demo", "password": "Owner12345"},
        )
        assert status == 200
        assert owner_login["user"]["role"] == "owner"

        status, _, owner_payload = request_json(
            owner_opener,
            base_url,
            "/api/jobs/refresh-archive-date",
            method="POST",
            payload={"date": "2026-05-01"},
            headers={"X-CSRF-Token": owner_login["csrf_token"]},
        )
        assert status == 410
        assert "只读" in owner_payload["error"]


def test_refresh_popular_exports_only_today_data(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    today = server.now_beijing()
    yesterday = today - timedelta(days=1)
    write_json(
        tmp_path / "data" / "archive" / yesterday.strftime("%Y-%m-%d") / "today_hot_videos.json",
        [
            {
                "rank": 1,
                "bvid": "BVYESTERDAY",
                "title": "昨日归档视频",
                "owner": "历史UP",
                "view": 100,
                "danmaku": 1,
                "like": 2,
                "favorite": 3,
                "coin": 4,
                "duration": 60,
            }
        ],
    )
    write_json(
        tmp_path / "data" / "archive" / yesterday.strftime("%Y-%m-%d") / "today_danmakus.json",
        [{"bvid": "BVYESTERDAY", "title": "昨日归档视频", "content": "历史弹幕", "time_in_video": 1}],
    )

    today_video = {
        "rank": 1,
        "bvid": "BVTODAY001",
        "title": "今日热门视频",
        "owner": "今日UP",
        "view": 200,
        "danmaku": 1,
        "like": 3,
        "favorite": 4,
        "coin": 5,
        "duration": 90,
    }
    today_row = {"bvid": "BVTODAY001", "title": "今日热门视频", "content": "今日弹幕", "time_in_video": 2}
    monkeypatch.setattr(
        server,
        "collect_popular_dataset",
        lambda collector, limit, progress_callback=None: ([today_video], [today_row]),
    )

    payload = server.refresh_popular_payload(limit=50)
    dashboard = read_json(tmp_path / "web" / "data" / "dashboard.json")
    exported_danmakus, _ = read_video_danmakus(tmp_path / "web" / "data", "BVTODAY001")
    video_stats = read_json(tmp_path / "web" / "data" / "video_stats.json")

    assert payload["exported_video_count"] == 1
    assert payload["exported_danmaku_count"] == 1
    assert [video["bvid"] for video in dashboard["raw_videos"]] == ["BVTODAY001"]
    assert [row["bvid"] for row in exported_danmakus] == ["BVTODAY001"]
    assert (tmp_path / "data" / "archive" / today.strftime("%Y-%m-%d") / "today_hot_videos.json").exists()
    assert (tmp_path / "data" / "archive" / today.strftime("%Y-%m-%d") / "danmaku_index.json").exists()
    assert video_stats["BVTODAY001"]["danmaku_count"] == 1


def test_popular_date_reads_archived_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    archive_dir = tmp_path / "data" / "archive" / "2026-05-01"
    write_json(
        archive_dir / "today_hot_videos.json",
        [
            {
                "rank": 1,
                "bvid": "BVARCHIVE001",
                "title": "归档当天的视频标题",
                "owner": "归档UP",
                "view": 100,
                "danmaku": 1,
                "like": 2,
                "favorite": 3,
                "coin": 4,
                "duration": 60,
            }
        ],
    )
    write_json(
        archive_dir / "today_danmakus.json",
        [
            {
                "bvid": "BVARCHIVE001",
                "title": "归档当天的视频标题",
                "cid": 1,
                "time_in_video": 1.2,
                "send_timestamp": 0,
                "user_hash": "u1",
                "content": "归档弹幕",
            }
        ],
    )
    write_json(tmp_path / "web" / "data" / "dashboard.json", {"raw_videos": []})

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/popular-date?date=2026-05-01")
        detail_status, _, detail = request_json(opener, base_url, "/api/video-danmakus?date=2026-05-01&bvid=BVARCHIVE001")

    assert status == 200
    assert payload["source"] == "archive"
    assert payload["dashboard"]["archive_source"]["read_only"] is True
    assert payload["dashboard"]["raw_videos"][0]["title"] == "归档当天的视频标题"
    assert "stats" not in payload["dashboard"]["raw_videos"][0]
    assert payload["video_stats"]["BVARCHIVE001"]["danmaku_count"] == 1
    assert payload["danmakus"] == []
    assert payload["danmaku_index"]["videos"]["BVARCHIVE001"]["file"] == "danmakus/BVARCHIVE001.json"
    assert (archive_dir / "danmakus" / "BVARCHIVE001.json").exists()
    assert detail_status == 200
    assert detail["danmakus"][0]["content"] == "归档弹幕"
    assert detail["stats"]["danmaku_count"] == 1


def test_cross_video_keywords_endpoint_reads_archive_data(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    for date, bvid, title, rows in [
        (
            "2026-05-01",
            "BVCROSS0001",
            "跨视频甲",
            [
                {"bvid": "BVCROSS0001", "title": "跨视频甲", "content": "破防 破防 高能", "time_in_video": 1},
            ],
        ),
        (
            "2026-05-02",
            "BVCROSS0002",
            "跨视频乙",
            [
                {"bvid": "BVCROSS0002", "title": "跨视频乙", "content": "破防 名场面", "time_in_video": 2},
            ],
        ),
    ]:
        archive_dir = tmp_path / "data" / "archive" / date
        write_json(archive_dir / "today_hot_videos.json", [{"bvid": bvid, "title": title, "danmaku": len(rows)}])
        write_json(archive_dir / "today_danmakus.json", rows)
    write_json(tmp_path / "web" / "data" / "dashboard.json", {"raw_videos": []})

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/cross-video/keywords?days=14&top_k=2")

    assert status == 200
    assert payload["ok"] is True
    assert payload["meta"]["archive_days"] == 2
    assert {"name": "破防", "category": "keyword"} in payload["sankey"]["nodes"]
    assert {"source": "破防", "target": "跨视频甲", "value": 2} in payload["sankey"]["links"]
    assert ["2026-05-02", 1, "破防"] in payload["theme_river"]
    assert "破防 破防 高能" in [item["content"] for item in payload["samples"]["破防"]]


def test_cross_video_keywords_endpoint_supports_row_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    archive_dir = tmp_path / "data" / "archive" / "2026-05-01"
    write_json(archive_dir / "today_hot_videos.json", [{"bvid": "BVCROSSLIM1", "title": "采样视频", "danmaku": 2}])
    write_json(
        archive_dir / "today_danmakus.json",
        [
            {"bvid": "BVCROSSLIM1", "title": "采样视频", "content": "破防", "time_in_video": 1},
            {"bvid": "BVCROSSLIM1", "title": "采样视频", "content": "高能", "time_in_video": 2},
        ],
    )
    write_json(tmp_path / "web" / "data" / "dashboard.json", {"raw_videos": []})

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/cross-video/keywords?days=14&top_k=5&row_limit=1")

    assert status == 200
    assert payload["meta"]["row_limit"] == 1
    assert payload["meta"]["danmaku_rows"] == 1
    assert {"name": "破防", "category": "keyword"} in payload["sankey"]["nodes"]
    assert {"name": "高能", "category": "keyword"} not in payload["sankey"]["nodes"]


def test_popular_date_current_returns_lightweight_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    video = {
        "rank": 1,
        "bvid": "BVCURRENT001",
        "title": "当前热门视频",
        "owner": "当前UP",
        "view": 100,
        "danmaku": 1,
        "like": 2,
        "favorite": 3,
        "coin": 4,
        "duration": 60,
    }
    row = {
        "bvid": "BVCURRENT001",
        "title": "当前热门视频",
        "cid": 1,
        "time_in_video": 1.2,
        "send_timestamp": 0,
        "user_hash": "u1",
        "content": "当前弹幕",
    }
    write_json(
        tmp_path / "web" / "data" / "dashboard.json",
        {
            "summary": {"danmaku_count": 999, "total_view": 999, "total_like": 999},
            "word_cloud": [{"name": "旧全局词云", "value": 999}],
            "user_hash_rank": [{"user_hash": "旧用户", "count": 999}],
            "raw_videos": [video],
        },
    )
    write_json(tmp_path / "web" / "data" / "danmakus.json", [row])

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/popular-date?date=current")
        detail_status, _, detail = request_json(opener, base_url, "/api/video-danmakus?date=current&bvid=BVCURRENT001")

    assert status == 200
    assert payload["source"] == "current"
    assert payload["danmakus"] == []
    assert payload["dashboard"]["summary"]["danmaku_count"] == 1
    assert payload["dashboard"]["word_cloud"] == []
    assert payload["dashboard"]["user_hash_rank"] == []
    assert "stats" not in payload["dashboard"]["raw_videos"][0]
    assert payload["video_stats"]["BVCURRENT001"]["danmaku_count"] == 1
    assert payload["danmaku_index"]["videos"]["BVCURRENT001"]["file"] == "danmakus/BVCURRENT001.json"
    assert detail_status == 200
    assert detail["danmakus"][0]["content"] == "当前弹幕"


def test_playback_track_endpoint_returns_timeline_and_track(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    video = {
        "bvid": "BVPLAY000001",
        "title": "回放测试视频",
        "view": 100,
        "danmaku": 3,
        "like": 10,
        "coin": 1,
        "duration": 120,
    }
    rows = [
        {
            "bvid": "BVPLAY000001",
            "title": "回放测试视频",
            "cid": 1,
            "time_in_video": 12,
            "send_timestamp": 0,
            "user_hash": "u3",
            "content": "无聊",
        },
        {
            "bvid": "BVPLAY000001",
            "title": "回放测试视频",
            "cid": 1,
            "time_in_video": 1,
            "send_timestamp": 0,
            "user_hash": "u1",
            "content": "好看",
            "color": 16777215,
        },
        {
            "bvid": "BVPLAY000001",
            "title": "回放测试视频",
            "cid": 1,
            "time_in_video": 3,
            "send_timestamp": 0,
            "user_hash": "u2",
            "content": "燃爆",
        },
    ]
    write_json(tmp_path / "web" / "data" / "dashboard.json", {"raw_videos": [video]})
    write_json(tmp_path / "web" / "data" / "danmakus.json", rows)

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/playback/track?date=current&bvid=BVPLAY000001")

    assert status == 200
    assert payload["ok"] is True
    assert payload["date"] == "current"
    assert payload["video"]["bvid"] == "BVPLAY000001"
    assert [item["text"] for item in payload["track"]] == ["好看", "燃爆", "无聊"]
    assert payload["track"][0]["color"] == "#ffffff"
    assert payload["sentiment_timeline"] == [
        {"time": 0, "count": 2, "score": 1.0, "positive": 2, "neutral": 0, "negative": 0},
        {"time": 10, "count": 1, "score": -1.0, "positive": 0, "neutral": 0, "negative": 1},
    ]
    assert payload["meta"]["track_count"] == 3


def test_popular_dates_hide_today_archive_to_avoid_current_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path)
    today = server.now_beijing().strftime("%Y-%m-%d")
    past = "2026-05-01"
    for day in [today, past]:
        archive_dir = tmp_path / "data" / "archive" / day
        write_json(archive_dir / "today_hot_videos.json", [])
        write_json(archive_dir / "today_danmakus.json", [])

    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, payload = request_json(opener, base_url, "/api/popular-dates")

    values = [item["value"] for item in payload["dates"]]
    labels = [item["label"] for item in payload["dates"]]
    assert status == 200
    assert values[0] == "current"
    assert labels[0] == "今日榜单"
    assert today not in values
    assert past in values


def test_owner_cannot_promote_account_to_owner(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "owner_demo", "password": "Owner12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "owner"

        status, _, payload = request_json(
            opener,
            base_url,
            "/api/admin/users/update",
            method="POST",
            payload={"account": "user_demo", "role": "owner"},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 400
        assert "owner 账号只能在服务器端创建" in payload["error"]


def test_admin_cannot_toggle_user_api_switch(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        assert login["user"]["role"] == "admin"

        status, _, payload = request_json(
            opener,
            base_url,
            "/api/admin/users/update",
            method="POST",
            payload={"account": "user_demo", "role": "normal", "api_enabled": True},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 400
        assert "API 开关只能由账号本人" in payload["error"]


def test_ai_provider_is_bound_to_current_account(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        user_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, user_login = request_json(
            user_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200

        status, _, toggled = request_json(
            user_opener,
            base_url,
            "/api/account/api-toggle",
            method="POST",
            payload={"enabled": True},
            headers={"X-CSRF-Token": user_login["csrf_token"]},
        )
        assert status == 200
        assert toggled["identity"]["api_switch_enabled"] is True
        assert toggled["identity"]["api_configured"] is False
        assert toggled["identity"]["ai_available"] is False

        status, _, blocked = request_json(
            user_opener,
            base_url,
            "/api/ai/analyze",
            method="POST",
            payload={},
            headers={"X-CSRF-Token": user_login["csrf_token"]},
        )
        assert status == 403
        assert "模型 API 配置" in blocked["error"]

        status, _, provider = request_json(
            user_opener,
            base_url,
            "/api/account/ai-provider",
            method="POST",
            payload={
                "provider": "deepseek",
                "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            },
            headers={"X-CSRF-Token": user_login["csrf_token"]},
        )
        assert status == 200
        assert provider["configured"] is True
        assert "abcdefghijklmnopqrstuvwxyz" not in provider["masked_key"]

        status, _, ready_session = request_json(user_opener, base_url, "/api/account/session")
        assert status == 200
        assert ready_session["identity"]["role"] == "api"
        assert ready_session["identity"]["api_configured"] is True
        assert ready_session["identity"]["ai_available"] is True

        admin_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, admin_login = request_json(
            admin_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200

        status, _, admin_provider = request_json(admin_opener, base_url, "/api/account/ai-provider")
        assert status == 200
        assert admin_provider["configured"] is False

        status, _, admin_toggled = request_json(
            admin_opener,
            base_url,
            "/api/account/api-toggle",
            method="POST",
            payload={"enabled": True},
            headers={"X-CSRF-Token": admin_login["csrf_token"]},
        )
        assert status == 200
        assert admin_toggled["identity"]["role"] == "admin"
        assert admin_toggled["identity"]["api_switch_enabled"] is True
        assert admin_toggled["identity"]["api_configured"] is False
        assert admin_toggled["identity"]["ai_available"] is False


def test_ai_analyze_endpoint_returns_evidence_and_highlights(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "call_deepseek_analysis", lambda provider, data, result: result)
    with run_test_server(tmp_path, monkeypatch) as base_url:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, login = request_json(
            opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200

        status, _, toggled = request_json(
            opener,
            base_url,
            "/api/account/api-toggle",
            method="POST",
            payload={"enabled": True},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        assert toggled["identity"]["api_switch_enabled"] is True

        status, _, provider = request_json(
            opener,
            base_url,
            "/api/account/ai-provider",
            method="POST",
            payload={
                "provider": "deepseek",
                "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
            },
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert status == 200
        assert provider["configured"] is True

        status, _, result = request_json(
            opener,
            base_url,
            "/api/ai/analyze",
            method="POST",
            payload={
                "scope": "current",
                "analysis_mode": "economy",
                "video": {"title": "Evidence HTTP demo", "duration": 120},
                "danmakus": [
                    {"content": "boom scene", "time_in_video": 10, "user_hash": "u1"},
                    {"content": "boom again", "time_in_video": 12, "user_hash": "u2"},
                    {"content": "quiet part", "time_in_video": 80, "user_hash": "u3"},
                ],
                "words": [{"name": "boom", "value": 2}],
            },
            headers={"X-CSRF-Token": login["csrf_token"]},
        )

    assert status == 200
    assert result["ok"] is True
    assert result["evidence_report"]["claims"][0]["keyword"] == "boom"
    assert result["highlight_timeline"][0]["danmaku_count"] >= 2


def test_bili_cookie_is_bound_to_current_account_and_never_echoed(tmp_path, monkeypatch):
    with run_test_server(tmp_path, monkeypatch) as base_url:
        user_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, user_login = request_json(
            user_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "user_demo", "password": "User12345"},
        )
        assert status == 200

        status, _, empty = request_json(user_opener, base_url, "/api/account/bili-cookie")
        assert status == 200
        assert empty["configured"] is False

        secret = "abcdef1234567890"
        status, _, saved = request_json(
            user_opener,
            base_url,
            "/api/account/bili-cookie",
            method="POST",
            payload={"credential_type": "sessdata", "value": secret},
            headers={"X-CSRF-Token": user_login["csrf_token"]},
        )
        assert status == 200
        assert saved["configured"] is True
        assert secret not in json.dumps(saved, ensure_ascii=False)
        assert "SESSDATA=" in saved["masked_value"]

        admin_opener = build_opener(HTTPCookieProcessor(CookieJar()))
        status, _, _ = request_json(
            admin_opener,
            base_url,
            "/api/account/login",
            method="POST",
            payload={"account": "admin_demo", "password": "Admin12345"},
        )
        assert status == 200
        status, _, admin_status = request_json(admin_opener, base_url, "/api/account/bili-cookie")
        assert status == 200
        assert admin_status["configured"] is False

        loaded = server.BILI_COOKIE_STORE.get("user_demo")
        assert loaded["cookie_header"] == f"SESSDATA={secret}"

        status, _, cleared = request_json(
            user_opener,
            base_url,
            "/api/account/bili-cookie",
            method="POST",
            payload={"clear": True},
            headers={"X-CSRF-Token": user_login["csrf_token"]},
        )
        assert status == 200
        assert cleared["configured"] is False
