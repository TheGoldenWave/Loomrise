# Durable Run Adapter Implementation Plan

> **For agentic workers:** REQUIRED: Use `subagent-driven-development` (if subagents are available) or `executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Loomrise 建立可替换的 `DurableRunAdapter`，把请求/事件持久化、恢复裁决、挂起/唤醒与外部副作用对账纳入 S2-a 的运行可信建设，同时保持 `ServiceRequest`、`RunEvent`、`Outcome`、权限、幂等键和外部结果仍由 Loomrise 掌握。

**Architecture:** Adapter 只负责 `Run` 的耐久执行状态与内部句柄；Task 调度是独立的可选关联，R1 不建设完整 `TaskAttempt` 派发器，也不要求入站请求先经过 Task。旧本地 `running` 执行重启后按 Task 裁决记为 `failed/restart_interrupted`；获准新尝试才可在新占用/代次下引用输入与版本兼容的已提交纯计算结果，旧 Attempt/worker 不复活。已持久等待态可恢复；只有执行端能完整查询的委派才重挂。未提交纯计算可重算，模型调用和实时检索须分别定义结果复用、重新调用、时效重验及预算策略。R1 先验存储事务、恢复裁决与旧代拒绝，R2 再接确认等待、取消确认及未知副作用对账。`pi durable` 只作为机制参照，不加入默认运行依赖。

**Tech Stack:** 现有 Python `loomrise/` 运行时、`RunEvent` 哈希链、**标准库 `sqlite3`**（2026-10-23 选定：WAL + `synchronous=FULL` + 进程内单写者锁，零新依赖）、标准库 `unittest` 故障注入测试；JSONL 仅作夹具/导出/短时回放。

---

## Chunk 1: 合同与存储端口

### Task 1: 定义耐久执行合同

**Files:**
- Modify: `loomrise/contracts.py`（新增 `Run` 与 checkpoint/lineage 引用的最小字段；保持现有 `ServiceRequest` 与 `RunEvent` 兼容；TaskAttempt 仅在 Task 合同就绪时通过可选关联进入）
- Create: `loomrise/durable_adapter.py`（`DurableRunAdapter` 协议、状态/恢复结果类型和内部句柄）
- Test: `tests/test_durable_contracts.py`

- [ ] **Step 1: Write failing contract tests**

  覆盖 `ServiceRequest → Run → runtime_execution_id`、可选 `TaskItem/TaskAttempt` 或后台作业关联、无 Task 的入站 Run、跨渠道沿用同一 `request_id`；断言 Adapter 句柄不是业务幂等键，`RunEvent` 可引用 checkpoint 但不把它当业务终态。

- [ ] **Step 2: Run the focused tests**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_contracts.py`

  Expected: FAIL because the new contract and adapter types do not exist.

- [ ] **Step 3: Implement the smallest contract**

  只添加稳定 `run_id`、请求/AgentVersion/上下文快照引用、占用代次、lineage、内部句柄引用和生命周期字段；TaskAttempt 维持可选关联，不新增 Task 调度状态机。不把上游 durable task/phase 暴露到公共合同，不增加通用 `execute` 工具。

- [ ] **Step 4: Run the focused tests again**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_contracts.py`

  Expected: PASS.

### Task 2: 建立可替换持久化边界，不绑定 pi durable

**Files:**
- Create: `loomrise/durable_store.py`（checkpoint、运行快照、幂等索引、outbox 和恢复查询的 repository port；具体后端通过实现注入）
- Test: `tests/test_durable_store.py`
- Modify: `docs/ARCHITECTURE.md`（实现完成后回填实际选型和限制，不能预先宣称生产支持）

- [ ] **Step 1: Write failing store tests**

  覆盖同一结构化存储事务的可见性：请求/Run 状态、幂等记录、`RunEvent` 序号与哈希链、checkpoint 校验引用及 outbox 意图要么一起可读，要么都不可读。若 checkpoint 内容在另一存储，先持久化不可变内容，再提交哈希引用；允许留下未引用内容，不允许暴露悬空引用。模拟 outbox 重投并用稳定 ID 去重。JSONL 仅作夹具/导出，不能误当业务账本。

- [ ] **Step 2: Run the focused tests**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_store.py`

  Expected: FAIL because no repository implementation exists.

- [ ] **Step 3: Implement a test repository and one selected durable backend**

  先完成可注入的内存/测试实现，再实现 R1 选定的结构化后端。后端必须显式声明单写者、锁、同步级别、迁移和备份语义；不得直接复制 `pi durable` 的 storage 实现或默认假定跨进程安全。TaskItem 采用/派发不在本工作包内；若未来接入，必须按 Task 设计将其与对应事件/outbox 建立事务关系。

- [ ] **Step 4: Verify atomic commit and migration behavior**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_store.py`

  Expected: PASS, including schema migration from an empty store and rejection of an incomplete commit.

## Chunk 2: 恢复裁决与事件投影

### Task 3: 实现无副作用步骤的故障恢复与旧代拒绝

**Files:**
- Modify: `loomrise/service.py`（通过 Adapter 启动/恢复 `Run`，保留现有业务规则）
- Modify: `loomrise/ledger.py`（恢复时验证事件链并关联 durable lineage；不把事件文件当完整状态存储）
- Test: `tests/test_durable_recovery.py`

- [ ] **Step 1: Write crash-injection tests**

  在纯计算/上下文装配步骤前后注入进程退出，按 Task §7.1 逐格验证：本地 running 的旧尝试变为 `failed/restart_interrupted`，不会复活；获准重试时新建占用代次和 `Run`，可引用输入/版本兼容的已提交纯计算结果；提交前崩溃的计算允许重算。已提交业务事实不重复入账，未提交步骤不能伪造为完成；另注入旧 generation 写入，验证拒绝。

- [ ] **Step 2: Run the tests to verify failure**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_recovery.py`

  Expected: FAIL on restart because S1 state is currently process-local.

- [ ] **Step 3: Implement rehydration and projection**

  启动时加载并裁决 `Run`/可选 TaskAttempt/幂等/outbox：持久等待态依原状态恢复，可完整查询的委派才重挂，本地 running 旧尝试关闭为失败并拒绝其 worker；只有获准的新尝试可引用兼容 checkpoint。随后验证 `RunEvent` 哈希链及 AgentVersion/上下文快照。Adapter phase/checkpoint 只投影为执行证据，业务终态仍由 `Outcome` 和外部结果决定。

- [ ] **Step 4: Run recovery tests and the existing regression suite**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_recovery.py`\
  `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_s1.py`

  Expected: PASS; existing S1 behavior remains unchanged.

### Task 4: 增加等待/唤醒、确认、取消与旧执行者检查

**Files:**
- Modify: `loomrise/service.py`（人工确认等待、取消请求/确认、lease/generation 重验）
- Modify: `loomrise/rules.py`（执行前最终授权与幂等检查保持模型外）
- Test: `tests/test_durable_lifecycle.py`

- [ ] **Step 1: Write failing lifecycle tests**

  覆盖确认等待期间崩溃（等待态保持，不重复询问）、确认后新动作前崩溃（running 旧尝试失败；新尝试前重验确认有效性）、取消竞争、旧 worker 迟到输出、lease 失效和新 generation。外部调用结果未知必须进入对账。旧 worker 任何迟到输出都不得产生新副作用。

- [ ] **Step 2: Run focused tests**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_lifecycle.py`

  Expected: FAIL until suspend/wake and generation checks are persisted.

- [ ] **Step 3: Implement lifecycle transitions**

  `cancel_requested`、`cancel_confirmed`、`business_action_revoked` 必须分别记录；Adapter abort 只能表示运行停止。等待态恢复及建立新尝试前重验租户、AgentVersion、权限、确认上下文、预算和占用代次，不复用过期内存快照。R2 的代次 fencing 只阻断旧执行者，真实跨进程 Worker 接管另排 R3/R4。

- [ ] **Step 4: Run focused tests and inspect event projections**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_lifecycle.py`

  Expected: PASS with distinct `RunEvent` records for request, confirmation, cancellation, stale generation rejection, and execution confirmation. `tests/test_durable_lifecycle.py` also asserts that read-only status inspection does not mutate the run.

## Chunk 3: 外部副作用与未知结果（**R2**，不是 R1）

> 本 Chunk 的幂等键与会话事实要等 WP7 的键语义落地；副作用重试/对账属 R2 的 `M-A-05/07`。R1 只做 Chunk 1–2 与 Task 1–4 的 R1 部分，不要把这里的测试写进 R1 证据。

### Task 5: 接入幂等副作用步骤与未知结果对账

**Files:**
- Modify: `loomrise/tools.py`（模拟工具增加稳定业务幂等键、外部结果 ID 和查询/对账接口）
- Modify: `loomrise/service.py`（把副作用边界封装为 Adapter step，但不把 Adapter 成功当业务成功）
- Test: `tests/test_durable_side_effects.py`

- [ ] **Step 1: Write failing side-effect tests**

  覆盖工具已写入但最终事件未提交、调用超时、回执迟到、重启后未知结果和同幂等键并发重复。预期只产生一个业务副作用，未知结果进入 `reconciling`，不会因为 durable retry 自动再次写入。

- [ ] **Step 2: Run focused tests**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_side_effects.py`

  Expected: FAIL until result IDs and reconciliation are persisted.

- [ ] **Step 3: Implement the minimal adapter/tool boundary**

  执行前重验权限、确认版本、预算、AgentVersion 和运行占用代次；有关联 TaskAttempt 时另验其 revision/lease/generation。生成跨渠道、重启及获准新尝试保持稳定且绑定具体业务操作的幂等键；执行后持久化外部 `result_id`/响应证据。无可靠对账能力时停止自动重试并转人工。

- [ ] **Step 4: Run focused tests and S1 regression**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_durable_side_effects.py`\
  `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_s1.py`

  Expected: PASS; existing simulated booking semantics remain intact.

## Chunk 4: 验收映射与交接

### Task 6: 将证据映射到既有 Gate 并划清后续范围

**Files:**
- Modify: `docs/RELEASE-PLAN.md`（R1/R2 work packages and exit criteria）
- Modify: `docs/RELEASE-GATE-MATRIX.md`（父 Gate 的 durable 故障证据映射）
- Modify: `docs/ROADMAP.md`（阶段范围与当前状态）
- Modify: `docs/context/INDEX.md`（计划、版本及矩阵入口）

- [ ] **Step 1: 建立父 Gate 与测试的映射**

  R1 测试映射到既有 `M-A-01…04`、`M-A-06`、`M-A-16…18`；M-A-19 是原子恢复/lineage 的证据细化，不独立阻断退出。R2 测试映射到既有 `M-A-05`、`M-A-07…15`；M-A-20/21 分别细化确认恢复与取消/旧代拒绝，同样不独立增加退出条件。R2 只在 `tests/test_durable_lifecycle.py` 覆盖生命周期所需的只读运行状态检查。

- [ ] **Step 2: 登记后续阶段的证据边界**

  跨进程 Worker 接管、crash-loop parking 和 phase/replay/telemetry 深度互查属于 R3/R4 的既有 Worker 治理门；M-C-11/12 只细化 M-C-07，不单独增加 R4 退出条件。若没有经验证的 Worker 需求，不要求照搬上游 task graph。其后续实现和证据按 R3/R4 开工时的独立工作包排期，不在本 R1/R2 计划虚列测试文件或证据报告。

- [ ] **Step 3: 检查计划链接与状态描述**

  确认架构、路线、版本工作包和矩阵都把 R1/R2 限定在本计划范围；没有将 Worker 接管、parking 或云端恢复写成已实现或新增 Gate。

- [ ] **Step 4: 校验本计划文档**

  Run: `rtk git diff --check`

  Expected: 无空白错误；相关本地链接、版本号和 Gate 引用一致。

### Task 7: 完成 R1/R2 计划级验证与证据登记

**Files:**
- Modify: `docs/reports/<version>-EVIDENCE.md`（实际实施后按版本登记证据；规划阶段不创建）

- [ ] **Step 1: Map each test to a Gate row**

  对照各父 Gate 检查工件覆盖。M-A-19…21 是父 Gate 的实现/证据细化，不形成额外独立退出条件。R1 证明事务持久化、重启裁决、lineage 和旧代拒绝；R2 证明等待/唤醒、取消确认、幂等副作用、未知对账及最小只读状态检查。parking、跨进程 Worker 接管和 phase/replay 深度检查留给 R3/R4 的既有 Worker 治理 Gate（M-C-07；M-C-11/12 仅作细化），云端声明留给 R5a。

- [ ] **Step 2: Run the complete focused verification**

  Run: `rtk proxy env PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_durable_*.py' -v`

  Also run: `rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_s1.py`

  Expected: PASS, with no new test claiming real external business writes or cloud recovery.

- [ ] **Step 3: Record evidence and limits**

  Write raw artifacts under `runs/R1/` or `runs/R2/`, the checked-in summary under `docs/reports/<version>-EVIDENCE.md`, and map each result to its parent Gate. Do not put parking or Worker handoff evidence in R1/R2. Leave cross-process Worker takeover/parking to R3/R4 and cloud backup/migration/upgrade to R5a. Do not add `pi-durable` to `requirements.txt` or `VERSION-PINS.md` unless a later selection decision explicitly approves it.

- [ ] **Step 4: Run repository checks**

  Run: `rtk git diff --check`

  Expected: no whitespace errors; all links, statuses, and index entries resolve.

---

Plan status: planning only. No Adapter, storage backend, dependency, or production-support claim is implemented by creating this file. Checkpoint mechanics remain an implementation candidate: the Gate requires durable recovery and atomic business-state visibility, not adoption of pi durable's API or storage implementation.
