# Innovation Plan Execution Findings

## Source Plan

- Plan file: `docs/inno_plan/selected_innovation_landing_plan.md`.
- Selected innovations:
  - 弹幕真实回放 + 情绪心电图双轨道.
  - 跨视频关键词桑基迁移图 + 主题河流.
  - 轻量弹幕情感分类器.

## Repository State

- Repository root: `D:/Codes/Python/FinalWork`.
- Branch: `main`.
- Worktree status before execution: clean.
- Existing tests are present under `tests/`.
- Implementation worktree: `C:\Users\Bolight\.config\superpowers\worktrees\FinalWork\innovation-plan-execution`.
- Implementation branch: `feature/innovation-plan-execution`.

## Architecture Notes

- Backend analyzer code lives in `src/analyzer.py`.
- Existing API routing is in `server.py`.
- Frontend chart code lives in `web/js/app-charts.js`.
- Main frontend app state and rendering live in `web/js/app.js` and `web/js/app-core.js`.
- `src/analyzer.py` already exposes time, length, word cloud, user-rank, and frontend single-video stats builders.
- `tests/test_analyzer.py` already covers analyzer payload shape and is the best place to add first backend TDD tests.
- `server.py` already has `_handle_video_danmakus`, which resolves `date=current|archive`, validates `bvid`, loads the current/archive dashboard, finds the video, and reads split danmaku store rows.
- `/api/playback/track` can reuse the same data lookup pattern and return a transformed playback payload instead of raw danmakus.

## Open Constraints

- No heavy ML dependencies should be added for the first implementation pass.

## Baseline Test Finding

- Running tests with system Python fails before collection because `jieba` is not installed. This is an environment mismatch; use the project venv or install `requirements.txt`.
- `venv\Scripts\python.exe -m pytest tests\test_analyzer.py -q` passes: 5 passed.
- `venv\Scripts\python.exe -m pytest tests\test_server_http_smoke.py::test_archive_date_refresh_job_is_disabled_to_keep_archives_read_only -q` passes when run alone.
- The grouped run of analyzer + server smoke had one connection-aborted failure in the archive-date refresh disabled test; treat as a baseline flake unless it recurs.

## Playback API Finding

- `/api/playback/track` reuses current/archive video danmaku loading and returns `track`, `sentiment_timeline`, `store`, and `meta` without exposing new dependencies.
- Test BV IDs must satisfy the existing `extract_bvid` rule: `BV` plus 10 alphanumeric characters.

## Cross-Video Finding

- `src/cross_video_analyzer.py` builds Sankey nodes/links, themeRiver rows, and keyword samples from archive snapshots.
- `/api/cross-video/keywords` reads archive dashboards and split danmaku stores through existing archive helpers.
- Full archive reads were too slow for browser demos; `row_limit` keeps the endpoint responsive while preserving a representative sample.

## Browser Verification Finding

- Playback panel and cross-video panel both render with non-zero dimensions.
- Selecting a rank video loaded playback data and enabled the playback button after the final fix.
- Cross-video panel loaded real archive data and showed keyword samples with no browser console errors.
