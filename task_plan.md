# Innovation Plan Execution

Goal: Implement the selected easy-to-land innovation plan from `docs/inno_plan/selected_innovation_landing_plan.md`.

Status: in_progress

## Phases

### Phase 1: Planning Setup
Status: complete

- Read the selected innovation plan.
- Check repository and branch state.
- Create persistent planning files for this execution.

### Phase 2: Baseline Review
Status: in_progress

- Inspect existing analyzer, server, frontend, and tests.
- Run baseline tests.
- Record findings and any existing failures.

### Phase 3: Week 1 Backend TDD
Status: pending

- Add sentiment dictionary support.
- Add `classify_sentiment`.
- Add `build_sentiment_timeline`.
- Add `build_playback_track`.
- Add playback API tests and endpoint.

### Phase 4: Week 2 Frontend and Cross-Video Backend
Status: pending

- Add playback frontend surface.
- Add cross-video analyzer with Sankey and theme river payload builders.
- Add cross-video API endpoint.

### Phase 5: Week 3 Frontend Charts and Verification
Status: pending

- Add ECharts Sankey and themeRiver rendering.
- Add keyword sample interaction.
- Run automated and manual verification.
- Update docs with implemented behavior and demo notes.

### Phase 6: AI Evaluation Reply Display Optimization
Status: complete

- Add markdown-to-HTML renderer for AI text responses (bold, lists, headers, blockquotes, separators).
- Redesign `ai-report-body` CSS with refined typography and visual hierarchy.
- Enhance evidence report cards with glow effects and improved visual design.
- Polish highlight timeline with better node styling and transitions.
- Add staggered reveal animations when AI results load.
- Verify end-to-end with different AI response formats.

### Phase 7: Web UI Popular Data Refresh with Configurable Limit
Status: complete

- Add `limit` parameter support to `POST /api/jobs/refresh-popular` (clamped 1-100, default 50).
- Add `<select id="popularLimitSelect">` with 5/10/25/50/100 options in the main dashboard hot tab.
- Update `canRefreshHotDateData()` to show the refresh button to all logged-in users.
- Wire `refreshHotDateData()` to read limit from the select and pass in the POST body.
- Add `.date-limit-select` CSS styles matching the existing amber theme.
- Update `setHotDateRefreshBusy()` to disable the limit select during job execution.
- Add `test_refresh_popular_job_accepts_limit_parameter` covering custom limit, default, and non-admin rejection.
- 158/158 tests pass.

## Decisions

- Work should be test-first for production code.
- Current implementation worktree: `C:\Users\Bolight\.config\superpowers\worktrees\FinalWork\innovation-plan-execution`.
- Current implementation branch: `feature/innovation-plan-execution`.
- Keep dependencies light and avoid adding heavy ML libraries.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| None yet |  |  |
