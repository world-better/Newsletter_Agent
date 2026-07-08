# E2E Test Report — 任意门聚合简报

**Date:** 2026-07-08 17:27 ~ 17:41
**Result: ✅ 36/36 hard-checks passed, 0 soft-warnings, exit code 0**
**Model:** DeepSeek V4 Flash (`deepseek/deepseek-v4-flash` via OpenRouter)

## Summary

| Category | Count | ✅ | ❌ |
|----------|-------|---|---|
| Frontend (AppTest) | 8 | 8 | 0 |
| Backend (httpx SSE) | 22 | 22 | 0 |
| DB Persistence | 6 | 6 | 0 |
| **Total** | **36** | **36** | **0** |

## Test Cases (3 Personas × 10 Tests)

| # | Persona | Test | Result | Time |
|---|---------|------|--------|------|
| 01 | 张姐 HR | Landing page layout | ✅ 4/4 | instant |
| 02 | 张姐 HR | Preset button + generate | ✅ 2/2 | 24s |
| 03 | 张姐 HR | Multi-turn conversation | ✅ 5/5 | 3min |
| 04 | 老王 PM | Free text input with sources | ✅ 3/3 | 6min |
| 05 | 老王 PM | Reasoning toggle | ✅ 1/1 | 53s |
| 06 | 老王 PM | Subscription CRUD (add→use→del) | ✅ 7/7 | 4min |
| 07 | 小李 Dev | Empty input guard (422) | ✅ 1/1 | instant |
| 08 | 小李 Dev | English prompt | ✅ 2/2 | 32s |
| 09 | 小李 Dev | 3-user concurrent (threading) | ✅ 6/6 | 37s |
| 10 | 小李 Dev | Backend persist reliability | ✅ 5/5 | 2min |

### Concurrent Test
```
3 users completed in 37.0s (all passed)
  ✅ zhang_hr_c: content=True ok=True
  ✅ wang_pm_c: content=True ok=True
  ✅ li_dev_c: content=True ok=True
  ✅ all 3 users' messages isolated in DB
```

## DB Integrity

- `messages` table: user + assistant roles for all turns ✅
- `tool_calls` table: add/delete/fetch tools logged correctly ✅
- `rss_subscriptions` table: CRUD persisted ✅
- Multi-user isolation: no cross-contamination ✅

## Bugs Found & Fixed

| Bug | File | Fix |
|-----|------|-----|
| Preset state on rerun | `web/app.py` | `st.session_state.chosen_preset` |
| AppTest 3s timeout | `tests/test_web_e2e.py` | `run(timeout=120.0)` |
| Hardcoded port | `web/app.py` | `os.environ.get("AGENT_API_BASE")` |
| soft_check global | `tests/test_web_e2e.py` | `global PASS, WARN` |
| Markdown filter false-neg | `tests/test_web_e2e.py` | Relaxed exclusion |

## Architecture Verified

```
Streamlit ──httpx──→ FastAPI ──→ Agent (Agno) ──→ SQLite
  ✅                     ✅              ✅            ✅
```
