from src.job_manager import JobManager


def test_job_manager_tracks_lifecycle_and_events():
    manager = JobManager(max_jobs=5, max_events_per_job=3)
    job = manager.create("refresh_popular", account="admin_demo", message="创建")

    manager.start(job["job_id"], "开始")
    manager.add_event(job["job_id"], "步骤一", progress=20)
    manager.add_event(job["job_id"], "步骤二", level="warning", progress=50)
    manager.succeed(job["job_id"], "完成", {"video_count": 50})

    saved = manager.get(job["job_id"])
    assert saved["status"] == "success"
    assert saved["progress"] == 100
    assert saved["result"]["video_count"] == 50
    assert saved["events"][-1]["step_name"] == "success"


def test_job_manager_prunes_old_jobs_and_finds_running_job():
    manager = JobManager(max_jobs=2)
    first = manager.create("refresh_popular", account="admin")
    second = manager.create("refresh_popular", account="admin")
    third = manager.create("ai_analysis", account="admin")

    assert manager.get(first["job_id"]) is None
    assert manager.get(second["job_id"]) is not None
    assert manager.get(third["job_id"]) is not None
    assert manager.latest_running("refresh_popular")["job_id"] == second["job_id"]

    manager.fail(second["job_id"], "失败")
    assert manager.latest_running("refresh_popular") is None
