# E2E Test Report

**Date:** 2026-07-09 13:29:05
**Result:** 24/25 passed (0 soft-warnings)

```
[13:20:04] ============================================================
[13:20:04] E2E TEST — Chat UI Backend
[13:20:04] Start: 2026-07-09 13:20:04
[13:20:04] ============================================================
[13:20:04] ── Starting FastAPI ──
[13:20:08]   FastAPI ready
[13:20:08] 
── Test 01: First chat message ──
[13:20:34]   ✅ reply has content
[13:20:34]   ✅ used fetch tool
[13:20:34]   ✅ DB has user+assistant
[13:20:34] 
── Test 02: Multi-turn chat ──
[13:21:08]   ✅ round 1 ok
[13:22:11]   ✅ round 2 ok
[13:22:11]   ❌ round 2 longer  — r1=1627 r2=1239
[13:22:11]   ✅ DB has 4+ msgs
[13:22:11] 
── Test 03: Free-form input ──
[13:22:35]   ✅ reply ok
[13:22:35]   ✅ fetch called
[13:22:35] 
── Test 04: Reasoning ──
[13:25:07]   ✅ reply ok
[13:25:07]   reasoning: 350 chars
[13:25:07] 
── Test 05: Add subscription ──
[13:25:20]   ✅ add called
[13:25:20]   ✅ reply confirms
[13:25:20]   ✅ DB has sub
[13:25:20] 
── Test 06: English prompt ──
[13:26:26]   ✅ reply ok
[13:26:26]   ✅ english reply
[13:26:26] 
── Test 07: 3-user concurrent ──
[13:27:20]   3 users done in 53.7s
[13:27:20]   ✅ user zhang: ok=True
[13:27:20]   ✅ user li: ok=True
[13:27:20]   ✅ user wang: ok=True
[13:27:20]   ✅ user zhang msgs isolated
[13:27:20]   ✅ user wang msgs isolated
[13:27:20]   ✅ user li msgs isolated
[13:27:20] 
── Test 08: Persist reliability ──
[13:28:30]   ✅ round 1 ok
[13:29:05]   ✅ round 2 ok
[13:29:05]   ✅ DB correct
[13:29:05]   ✅ tool_calls in DB
[13:29:05] 
============================================================
[13:29:05] FINAL: 24/25 passed, 0 soft-warnings
[13:29:05] ============================================================
```
