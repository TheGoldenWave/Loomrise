# Durable Run Adapter Implementation Plan

> **For agentic workers:** REQUIRED: Use `subagent-driven-development` (if subagents are available) or `executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Loomrise 建立可替换的 `DurableRunAdapter`，把 checkpoint、挂起/唤醒、崩溃恢复和 worker 接管纳入 S2-a 的运行可信建设，同时保持 `ServiceRequest`、`RunEvent`、`Outcome`、权限、幂等键和外部结果仍由 Loomrise 掌握。

**Architecture:** Adapter 只负责一次 `Run` 的耐久执行状态与恢复句柄；`TaskAttempt` 负责 TaskItem 的派发、lease/generation，并通过关联引用 `Run`，两者不形成第二套公共状态机。`runtime_execution_id` 不对外暴露，也不成为业务幂等键或结果 ID。R1 先用无副作用步骤验证原子提交线、重启恢复、旧 generation 拒绝和事件投影，R2 再接人工确认、取消确认、未知结果对账和最小沙盒副作用。`pi durable` 只作为机制参照，不加入默认运行依赖。

**Tech Stack:** 现有 Python `loomrise/` 运行时、`RunEvent` 哈希链、结构化持久化候选（SQLite 或等价实现由 R1 选型 Gate 决定）、故障注入测试；JSONL 仅作夹具/导出/短时回放。

---

## Chunk 1: Contract And Storage Ports

### Task 1: Define the durable execution contract

**Files:**
- Modify: `loomrise/contracts.py`（新增 `Run`、`TaskAttempt`、checkpoint/lineage 引用的最小字段；保持现有 `ServiceRequest` 与 `RunEvent` 兼容）
- Create: `loomrise/durable_adapter.py`（`DurableRunAdapter` 协议、状态/恢复结果类型和内部句柄）
- Test: `tests/test_durable_contracts.py`

- [ ] **Step 1: Write failing contract tests**

  覆盖 `ServiceRequest → Run → runtime_execution_id` 与 `TaskItem → TaskAttempt → Run` 的关联、跨渠道继续使用同一 `request_id`、Adapter 句柄不能作为业务幂等键，以及 `RunEvent` 能引用 checkpoint 但不把它当业务终态。

- [ ] **Step 2: Run the focused tests**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_contracts.py -q`

  Expected: FAIL because the new contract and adapter types do not exist.

- [ ] **Step 3: Implement the smallest contract**

  只添加稳定 ID、AgentVersion/上下文快照引用、lease/generation、lineage、内部句柄引用和生命周期字段；不把上游 durable task/phase 类型暴露到公共合同，不增加通用 `execute` 工具。

- [ ] **Step 4: Run the focused tests again**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_contracts.py -q`

  Expected: PASS.

### Task 2: Add a persistence boundary without committing to pi durable

**Files:**
- Create: `loomrise/durable_store.py`（checkpoint、运行快照、幂等索引、outbox 和恢复查询的 repository port；具体后端通过实现注入）
- Test: `tests/test_durable_store.py`
- Modify: `docs/ARCHITECTURE.md`（实现完成后回填实际选型和限制，不能预先宣称生产支持）

- [ ] **Step 1: Write failing store tests**

  覆盖原子提交的可见性：checkpoint、对应运行事实引用和 outbox 意图要么一起可读，要么都不可读；JSONL 夹具不能被测试误当长期业务账本。

- [ ] **Step 2: Run the focused tests**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_store.py -q`

  Expected: FAIL because no repository implementation exists.

- [ ] **Step 3: Implement a test repository and one selected durable backend**

  先完成可注入的内存/测试实现，再实现 R1 选定的结构化后端。后端必须显式声明单写者、锁、同步级别、迁移和备份语义；不得直接复制 `pi durable` 的 storage 实现或默认假定跨进程安全。

- [ ] **Step 4: Verify atomic commit and migration behavior**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_store.py -q`

  Expected: PASS, including schema migration from an empty store and rejection of an incomplete commit.

## Chunk 2: Recovery And Event Projection

### Task 3: Implement no-side-effect checkpoint and crash recovery

**Files:**
- Modify: `loomrise/service.py`（通过 Adapter 启动/恢复 `Run`，保留现有业务规则）
- Modify: `loomrise/ledger.py`（恢复时验证事件链并关联 durable lineage；不把事件文件当完整状态存储）
- Test: `tests/test_durable_recovery.py`

- [ ] **Step 1: Write crash-injection tests**

  在纯计算/上下文装配步骤前后注入进程退出，验证重启后从最后一个已提交 checkpoint 继续；已提交步骤不重复产生业务事件，未提交步骤不被伪造为完成。

- [ ] **Step 2: Run the tests to verify failure**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_recovery.py -q`

  Expected: FAIL on restart because S1 state is currently process-local.

- [ ] **Step 3: Implement rehydration and projection**

  恢复时先加载 `Run`/`TaskAttempt`/幂等/outbox，再验证 `RunEvent` 哈希链和 AgentVersion/上下文快照；Adapter 内部 phase/checkpoint 只投影为执行证据，业务终态仍由 `Outcome` 和外部结果决定。

- [ ] **Step 4: Run recovery tests and the existing regression suite**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_recovery.py tests/test_s1.py -q`

  Expected: PASS; existing S1 behavior remains unchanged.

### Task 4: Add suspend/wake, confirmation, cancellation, and stale-worker checks

**Files:**
- Modify: `loomrise/service.py`（人工确认等待、取消请求/确认、lease/generation 重验）
- Modify: `loomrise/rules.py`（执行前最终授权与幂等检查保持模型外）
- Test: `tests/test_durable_lifecycle.py`

- [ ] **Step 1: Write failing lifecycle tests**

  覆盖确认前崩溃、确认后工具执行前崩溃、取消竞争、旧 worker 迟到输出、lease 到期和新 generation 接管。旧 worker 任何迟到输出都不得产生新副作用。

- [ ] **Step 2: Run focused tests**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_lifecycle.py -q`

  Expected: FAIL until suspend/wake and generation checks are persisted.

- [ ] **Step 3: Implement lifecycle transitions**

  `cancel_requested`、`cancel_confirmed`、`business_action_revoked` 必须分别记录；Adapter abort 只能表示运行停止。恢复人工确认时重新校验租户、AgentVersion、权限、确认上下文、预算和 generation，不复用过期内存快照。

- [ ] **Step 4: Run focused tests and inspect event projections**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_lifecycle.py -q`

  Expected: PASS with distinct `RunEvent` records for request, confirmation, cancellation, stale worker rejection, and execution confirmation.

## Chunk 3: Side Effects And Unknown Results

### Task 5: Integrate idempotent side-effect steps and reconciliation

**Files:**
- Modify: `loomrise/tools.py`（模拟工具增加稳定业务幂等键、外部结果 ID 和查询/对账接口）
- Modify: `loomrise/service.py`（把副作用边界封装为 Adapter step，但不把 Adapter 成功当业务成功）
- Test: `tests/test_durable_side_effects.py`

- [ ] **Step 1: Write failing side-effect tests**

  覆盖工具已写入但最终事件未提交、调用超时、回执迟到、重启后未知结果和同幂等键并发重复。预期只产生一个业务副作用，未知结果进入 `reconciling`，不会因为 durable retry 自动再次写入。

- [ ] **Step 2: Run focused tests**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_side_effects.py -q`

  Expected: FAIL until result IDs and reconciliation are persisted.

- [ ] **Step 3: Implement the minimal adapter/tool boundary**

  执行前重验权限、确认版本、预算、AgentVersion、TaskAttempt lease/generation，并生成绑定具体业务操作的幂等键；执行后持久化外部 `result_id`/响应证据。无可靠对账能力时停止自动重试并转人工。

- [ ] **Step 4: Run focused tests and S1 regression**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_side_effects.py tests/test_s1.py -q`

  Expected: PASS; existing simulated booking semantics remain intact.

## Chunk 4: Inspection, Parking, And Release Gates

### Task 6: Add read-only inspection and crash-loop parking evidence

**Files:**
- Create: `loomrise/durable_inspection.py`（只读运行摘要、checkpoint/phase/lineage 查询；不提供写状态接口）
- Modify: `loomrise/durable_adapter.py`（连续恢复失败进入 `parked`，需要人工/运维显式恢复）
- Test: `tests/test_durable_inspection.py`
- Create: `docs/reports/R1-DURABLE-RUN-EVIDENCE.md`（按 Gate 追溯矩阵登记实测证据）

- [ ] **Step 1: Write failing inspection/parking tests**

  覆盖只读查看不改变状态、连续 crash-loop 不无限重试、parked 运行可查询原因/最后 checkpoint/lineage，并能在人工批准后恢复或终止。

- [ ] **Step 2: Run focused tests**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_inspection.py -q`

  Expected: FAIL until inspection and parking are implemented.

- [ ] **Step 3: Implement bounded recovery and evidence export**

  重试/退避/parking 的预算与阈值由 Loomrise 记录；导出证据必须同时包含环境、schema/Adapter 版本、故障点、事件哈希链、未覆盖项和是否发生外部副作用。

- [ ] **Step 4: Verify evidence can be read without mutating the run**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_inspection.py -q`

  Expected: PASS; evidence export is deterministic and inspection is read-only.

### Task 7: Close R1/R2 gates and defer cloud claims

**Files:**
- Modify: `docs/RELEASE-PLAN.md`（R1/R2 work packages and dependencies）
- Modify: `docs/RELEASE-GATE-MATRIX.md`（M-A durable evidence rows and evidence anchors）
- Modify: `docs/ROADMAP.md`（current status and no-production-support wording）
- Modify: `docs/context/INDEX.md`（plan and reference links）

- [ ] **Step 1: Map each test to a Gate row**

  R1 must cover atomic persistence, no-side-effect recovery, stale generation rejection, and event lineage. R2 must cover suspend/wake, cancellation confirmation, idempotent side effects, unknown reconciliation and read-only inspection.

- [ ] **Step 2: Run the complete focused verification**

  Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_durable_contracts.py tests/test_durable_store.py tests/test_durable_recovery.py tests/test_durable_lifecycle.py tests/test_durable_side_effects.py tests/test_durable_inspection.py tests/test_s1.py -q`

  Expected: PASS, with no new test claiming real external business writes or cloud recovery.

- [ ] **Step 3: Record evidence and limits**

  Write the raw artifacts under `runs/R1/` or `runs/R2/`, the checked-in summary under `docs/reports/<version>-EVIDENCE.md`, and leave cloud backup/migration/upgrade as R5a work. Do not add `pi-durable` to `requirements.txt` or `VERSION-PINS.md` unless a later selection decision explicitly approves it.

- [ ] **Step 4: Run repository checks**

  Run: `rtk git diff --check`

  Expected: no whitespace errors; all links, statuses, and index entries resolve.

---

Plan status: planning only. No adapter, storage backend, dependency, or production-support claim is implemented by creating this file.
