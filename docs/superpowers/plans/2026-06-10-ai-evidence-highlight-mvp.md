# AI Evidence Highlight MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MVP evidence-backed AI report and high-energy segment timeline to the existing danmaku dashboard.

**Architecture:** Build deterministic local evidence and highlight structures from loaded danmaku rows, then include them in the AI request/response path. The frontend renders these structures as cards under the current-video AI report, while the provider prompt receives the same structures as grounding material.

**Tech Stack:** Python standard library, pytest, vanilla JavaScript, existing OpenAI-compatible provider adapter, existing dashboard CSS.

---

### Task 1: Local Evidence and Highlight Builders

**Files:**
- Create: `src/ai_evidence.py`
- Modify: `src/ai_analysis.py`
- Test: `tests/test_ai_evidence.py`
- Test: `tests/test_ai_analysis.py`

- [ ] Add failing tests for representative evidence claims and high-energy segment ranking.
- [ ] Implement `build_evidence_report(rows, words, metrics)` and `build_highlight_timeline(rows, words)`.
- [ ] Include both structures in local current-video AI results.

### Task 2: Provider Grounding

**Files:**
- Modify: `src/ai_provider.py`
- Test: `tests/test_ai_provider.py`

- [ ] Add failing tests that prompt payload includes `evidence_report` and `highlight_timeline`.
- [ ] Extend current-video output schema and prompt rules to require evidence-backed conclusions.
- [ ] Preserve local evidence/highlight structures when merging provider results.

### Task 3: Frontend MVP

**Files:**
- Modify: `web/index.html`
- Modify: `web/js/app-ai.js`
- Modify: `web/css/dashboard.css`
- Test: `tests/test_frontend_assets.py`

- [ ] Add placeholder containers below the current-video AI text.
- [ ] Build evidence and highlight payloads from currently loaded rows.
- [ ] Render returned cards after AI analysis completes.
- [ ] Add asset tests for the new DOM ids and functions.

### Task 4: Verification

**Files:**
- Test: focused pytest files

- [ ] Run AI, provider, frontend asset, and relevant HTTP smoke tests.
- [ ] Confirm the new UI is present in `index.html` and the response path remains compatible with cached/provider results.
