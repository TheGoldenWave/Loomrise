# R1 Stale Operation Safety Implementation Plan

状态：本地实现与回归验证完成，未提交；R1 Gate 状态不变。

> **For agentic workers:** REQUIRED: Use subagent-driven development to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** Prevent late R1 operations from reviving recovered Runs, leaking configuration across experts, or creating duplicate frozen candidates on retry.

**Architecture:** Keep durable Run status authoritative inside the SQLite transaction. Route changes must always invalidate older configuration loads through the existing generation guard. Candidate freeze retries must reuse the same idempotency key for the same expert draft revision.

**Tech Stack:** Python `sqlite3`, vanilla JavaScript modules, Node `node:test`, Playwright browser checks.

---

## Chunk 1: WP2 Old Run Completion Guard

**Files:** `loomrise/durable_store.py`, `tests/test_durable_recovery.py`

- [x] Add a regression test that recovers a running request through a second owner, then calls `finish()` on the still-open old adapter.
- [x] Add a reverse-order regression where old `finish()` wins before recovery's write transaction and verify no contradictory interruption event is appended.
- [x] Verify the test fails because the old adapter currently overwrites the recovered terminal state.
- [x] Update `finish_run()` to condition its terminal update on `status='running'` and raise before updating the request or appending an event when no row transitions.
- [x] Verify the regression, normal finish, recovery, durable store, and SQLite crash-matrix tests pass.
- [ ] Commit the implementation and regression test.

## Chunk 2: WP9 Expert Switch During Configuration Load

**Files:** `prototypes/console-next/app.js`, `prototypes/console-next/tests/config-ui-browser-check.js` or a focused browser check.

- [x] Add a failing browser regression that delays expert A's configuration response, switches to expert B, and verifies the visible draft and subsequent edits belong only to expert B.
- [x] Remove the global in-flight gate that suppresses B's load; let the workspace generation guard discard stale A responses.
- [x] Verify the focused browser check and `npm test` pass.
- [ ] Commit the app and test changes.

## Chunk 3: WP3/WP9 Candidate Freeze Retry Idempotency

**Files:** `prototypes/console-next/r1-configuration.js`, `prototypes/console-next/tests/r1-configuration.test.js`.

- [x] Add a failing test where the server creates a candidate but the client sees a transient error, then verify retry reuses the same operation key and yields only one candidate.
- [x] Retain the idempotency key for the same agent and draft revision across ambiguous retries; use a new key only for a new source revision.
- [x] Verify malformed rejection shapes preserve the key and only contract-complete server rejection clears it.
- [x] Verify the focused controller test and `npm test` pass.
- [ ] Commit the controller and test changes.

## Final Verification

- [x] Run full backend `unittest discover` with `ResourceWarning` treated as errors and tracemalloc enabled: **114/114**.
- [x] Run front-end `npm test`: **230/230**; focused `test:r1-switch` and `test:sidebar` browser checks passed on an isolated 127.0.0.1:8769 preview with separate Playwright sessions.
- [x] Expert-switch browser check waits for the page to parse the delayed draft response and settle two animation frames before asserting that expert B remains unchanged.
- [x] Review the complete diff, `git diff --check`, ignored `private/` status, and staged-file list.
