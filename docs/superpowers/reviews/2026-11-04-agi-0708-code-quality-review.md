# AGI-07/08 代码质量审查（2026-11-04）

## 元信息

- 审查依据：`docs/superpowers/plans/2026-10-30-r3-development.md:45` 九类必测场景，及「先独立规格审查，再代码质量审查」。
- 前序工件：`docs/superpowers/specs/2026-11-04-agi-0708-spec-review.md`（独立规格审查，已完成）。
- 审查方式：本机确定性 fixture + unittest；不伪造真实联调证据。
- 结论口径：下文「通过」仅指本机 fixture 下的 Python 回归通过；**真实 harness Provider、真实 host Skill 激活、质量对照均未联调，不记为通过**（见「明确未联调」一节）。

## 本轮改动与修复质量

改动均为局部 `Edit` 增量，未整文件重写、未执行任何 `git add / commit / checkout / restore / stash / reset`，未改禁改文件（`durable_store.py / contracts.py / contact_pages.py / customer_widget.html / service_cycles.py / graph_runtime.py / graph_validation.py / config_validation.py / prototypes/` 及只读 docs 清单）。

| 缺口 | 修复文件 | 负向/回归测试落点 |
|---|---|---|
| 1 替身冒充真实 Provider | `loomrise/diagnostics.py`（服务端 Provider 合同常量）、`loomrise/adapters/harness.py`（禁止自报 + 按注入判定 kind + descriptor 带 `provider_kind/version/contract_hash`）、`loomrise/governance_jobs.py`（create 校验 kind/version/contract_hash + 冻结 `evidence_class`） | `test_governance_jobs.py::TestGovernanceProviderRegistration`（5）、`test_harness_provider.py`（2）、`test_governance_harness_integration.py`（证据分类断言） |
| 2 作业入口未复用应用服务 | `loomrise/configuration.py`（`_GOVERNANCE_JOB_ACTIONS` 显式拒绝） | `test_diagnostics_interfaces.py::test_governance_jobs_are_cli_only_not_exposed_via_http_or_mcp` |
| 3 external_agent 绕过白名单 | `loomrise/configuration.py`（`_EXTERNAL_AGENT_DIAGNOSTICS_ACTIONS` 显式允许/拒绝） | `test_diagnostics_interfaces.py::test_external_agent_diagnostics_whitelist_is_explicit` |
| 4 撤权路径不独立 | `loomrise/diagnostics.py::revoke`（去掉 `_permission_tx` 合同/来源/时效校验，只留 owner 归属） | `test_diagnostics.py::test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry`；并更新 `test_permission_persists_contract_version_and_hash_and_rejects_stale_contract` 的旧断言（旧断言期望 revoke 失败，与新规格冲突） |
| 5 cancel 静默无效果 | `loomrise/governance_jobs.py::cancel`（两处 UPDATE 补 `rowcount != 1` 竞争检查） | `test_governance_jobs.py::test_cancel_reports_race_when_update_affects_no_row`、`test_concurrent_cancel_is_never_a_silent_no_op` |

测试桩适配（非新功能，仅为符合新 Provider 登记合同）：`tests/test_governance_jobs.py`、`tests/test_config_cli.py` 的 `Provider` stub descriptor 补齐 `provider_kind / version / contract_hash`。

## plan :45 九类场景逐条

### 1. 撤权 / 到期

- 覆盖测试：
  - `tests/test_diagnostics.py::TestDiagnosticPermission::test_expiry_and_revocation_prevent_evidence_report_submit_and_report_read`
  - `tests/test_diagnostics.py::TestDiagnosticPermission::test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry`（新增）
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_revoke_allows_status_and_cancel_but_blocks_retry_and_evidence`
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_revoked_permission_blocks_later_evidence_and_report_commit`
  - `tests/test_diagnostics_interfaces.py::DiagnosisInterfaceTests::test_cli_mcp_and_http_reuse_exact_snapshot_and_revoke`（撤销后 HTTP 403 / MCP `forbidden`）
- 实际结果：专项 105 项、全量 714 项中通过。撤权后 `read_evidence / submit_report / read_report / retry` 全部拒绝；报告同事务提交被 `authority_revoked` 拦下；非 owner 撤销仍 `PermissionError`（身份校验未放宽）。

### 2. 旧 Schema / hash

- 覆盖测试：
  - `tests/test_diagnostics.py::TestDiagnosticPermission::test_permission_persists_contract_version_and_hash_and_rejects_stale_contract`（本轮强化为三段显式断言：读拒绝旧 hash / 撤权成功并落库 / 撤权后读取仍拒绝；未删除旧断言绕过）
  - `tests/test_diagnostics.py::TestDiagnosticPermission::test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry`（新增：旧 `schema_hash` + 过期 + 来源失效三者叠加仍可撤销）
  - `tests/test_governance_jobs.py::TestGovernanceProviderRegistration::test_stale_or_wrong_contract_hash_is_rejected`（新增）
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_explicit_restart_migration_preserves_job_and_attempt_rows`（旧 `schema_version` 重开迁移）
- 实际结果：通过。旧证据合同下证据读取拒绝、撤销可用；旧/错 `contract_hash` 的 Provider descriptor 被 `create` 拒绝且不落作业行。

### 3. 重复提交 / 回调

- 覆盖测试：
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_idempotency_freezes_provider_descriptor_and_input`
  - `tests/test_governance_jobs.py::TestGovernanceJobsConcurrency::test_two_sqlite_stores_compare_and_swap_only_one_attempt`
  - `tests/test_governance_jobs.py::TestGovernanceJobsConcurrency::test_report_insert_and_success_cas_rollback_as_one_transaction`
  - `tests/test_governance_jobs.py::TestGovernanceProviderRegistration` 负向用例均断言 `governance_jobs` 表 0 行
- 实际结果：通过。同一 `idempotency_key` 复用同一作业，输入变化即拒绝；双 store 并发只有一个领取成功；报告插入与成功 CAS 同事务回滚。

### 4. 取消竞争

- 覆盖测试：
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_same_loop_cancel_signals_provider_task_and_fences_swallowed_late_result`
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_cross_thread_cancel_signals_task_running_on_event_loop`
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_cancel_reports_race_when_update_affects_no_row`（新增：`rowcount=0` 抛「取消竞争」，真实状态不被覆盖回 queued/cancelled）
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_concurrent_cancel_is_never_a_silent_no_op`（新增：双 store 并发，结果为 `cancelled` 或 `race_rejected`，最终状态 `cancelled`）
- 实际结果：通过。本轮补的 rowcount 检查把「读取后状态被并发改变」的静默无效果显式化为失败。

### 5. 重开

- 覆盖测试：
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_explicit_job_persists_valid_report_usage_and_reopens`
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_explicit_restart_migration_preserves_job_and_attempt_rows`
- 实际结果：通过。SQLite 重开后状态/历史保留；旧 owner 的 running 作业只能经 `recover` 进入 `interrupted / provider_state=unknown`，且 `provider.calls == 0`（不自动恢复）。

### 6. 预算耗尽

- 覆盖测试：
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_retry_exhausts_token_budget_without_refunding_reserved_attempt`
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_retry_reserves_another_attempt_before_provider_and_honors_total_budget`
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_unknown_execution_keeps_full_reservation_and_cannot_retry`
  - `tests/test_governance_jobs.py::TestGovernanceJobsLifecycle::test_invalid_usage_is_not_persisted_and_reservation_is_not_refunded`
- 实际结果：通过。超预算重试进入 `exhausted` 且保留预留 token；`unknown` 执行保守占满预留且不可直接重试；非法用量不落库、不退款。

### 7. 迟到结果

- 覆盖测试：
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_same_loop_cancel_signals_provider_task_and_fences_swallowed_late_result`
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_timeout_that_provider_swallows_does_not_publish_late_success`
  - `tests/test_governance_jobs.py::TestGovernanceJobsCancellation::test_caller_task_cancellation_that_provider_swallows_still_fences_result`
- 实际结果：通过。Provider 吞掉取消/超时后迟到成功结果被围栏拦下，`diagnosis_reports` 表 0 行、`report_id` 为 None。

### 8. 全业务表零写入

- 覆盖测试：
  - `tests/test_diagnostics_interfaces.py::DiagnosisInterfaceTests::test_report_submission_has_no_business_dml_and_cannot_expand_authority`（`set_trace_callback` 断言所有 `INSERT/UPDATE/DELETE` 均含 `diagnosis_`）
  - `tests/test_diagnostics_interfaces.py::DiagnosisInterfaceTests::test_governance_jobs_are_cli_only_not_exposed_via_http_or_mcp`（新增：application/HTTP/MCP 拒绝作业时 `governance_jobs` 表 0 行）
  - `tests/test_governance_jobs.py::TestGovernanceProviderRegistration` 负向用例（新增：descriptor 被拒时 `governance_jobs` 表 0 行）
- 实际结果：通过。诊断/报告/作业写入均隔离在 `diagnosis_* / governance_*` 表，未写业务表。

### 9. 故障下手动 / 在线服务独立可用

- 覆盖测试：
  - `tests/test_diagnostics_interfaces.py::DiagnosisInterfaceTests::test_cli_mcp_and_http_reuse_exact_snapshot_and_revoke`（CLI/MCP/HTTP 读同一快照、独立可用，不依赖作业或 Provider）
  - `tests/test_config_cli.py::test_governance_job_cli_requires_provider_and_supports_cancel`（`_diagnostics_provider` 不可用 → `provider_unavailable`，作业故障不扩散到普通诊断动作）
  - `tests/test_diagnostics.py::TestDiagnosticPermission::test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry`（证据合同/来源故障下撤销仍可用）
- 实际结果：通过（**边界**：此处「在线服务」仅指本机 loopback HTTP/MCP fixture）。证据读取、提案提交、许可撤销不依赖真实 Provider 或作业系统；作业/Provider 故障不影响手动与在线诊断链路。
- 未覆盖：真实公网/真实渠道下的在线服务独立性未验收。

## Provider 登记质量专项（本轮缺口 1）

| 场景 | 测试 | 结果 |
|---|---|---|
| 缺 `provider_kind` 被拒 | `test_missing_provider_kind_is_rejected` | 通过（`类别` + 表 0 行） |
| 自报 `real` 但注入替身被拒 | governance 层 `test_self_reported_real_kind_is_rejected` + harness 层 `test_config_cannot_self_report_provider_kind` | 通过 |
| 旧/错 `contract_hash` 被拒 | `test_stale_or_wrong_contract_hash_is_rejected` | 通过（`合同`） |
| 替身贴真实 version 被拒 | `test_version_must_match_declared_kind` | 通过（`版本`） |
| 替身成功登记为 offline 证据 | `test_offline_scripted_success_is_registered_as_offline_evidence`、`test_injected_scripted_model_is_registered_as_offline_evidence`、集成测试断言 | 通过（`evidence_class=offline_scripted`，非 real） |

## 明确未联调（不得写成通过）

- **真实 harness Provider 未联调**：本机仅 `ScriptedChatModel` 替身 + `https://provider.example.invalid/v1` + `test-only-credential`；未核真实官方合同、未接真实模型凭据与网络、未验工具/文件/网络/凭据隔离的真实性。服务端 `ALLOWED_PROVIDER_KINDS` 不含 `real_harness`，本机无真实联调条件时明确「不可运行」，不把替身结果计入真实 Provider 证据分类。
- **真实 host Skill 激活未联调**：读取 MCP `DIAGNOSIS_SKILL_URI` resource 不等于真实 host 已完成 Skill 激活。
- **质量对照未联调**：多样本模型质量、真实 Provider 质量矩阵、目标角色任务基线均未跑，继续按未通过记录。
- **最终复核（主 agent，2026-11-04 18:25）**：本工件自身改动纯 Python、不宣称前端通过；主 agent 已独立复跑前端 340/340、Canvas 构建 Exit 0、Python 全量 739 项 OK、S1 自检与合同语义自检全部通过。工件内 714 / 733 项为各工作包落盘时点快照；AGI 5 模块专项收口后 61 项、8 模块 105 项。
- 真实渠道/公网/生产身份隔离、R2/R3 Gate 保持未通过。

## 验证记录（实际跑过的命令与真实输出）

命令 1（专项，8 个模块）：
```
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics tests.test_diagnostics_interfaces tests.test_governance_jobs tests.test_harness_provider tests.test_governance_harness_integration tests.test_config_cli tests.test_config_http tests.test_configuration_service -q
```
真实输出：
```
Ran 105 tests in 8.001s

OK
```
（基线 93 项 OK → 105 项，新增 12 项）

命令 2（全量 Python 回归）：
```
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
```
真实输出：
```
Ran 733 tests in 40.648s

OK
```
（基线 702 项 OK；本轮新增 12 项、其他 teammate 在本工作区并行新增 19 项，共 733 项全部 OK、无失败。全量总数随并行开发变化，关键口径为 OK/无失败）

命令 3（合同语义自检）：
```
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_contract_semantics.py
```
真实输出（末行）：
```
全部通过
```

命令 4（本轮 12 个新增测试逐项）：
```
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_governance_jobs.TestGovernanceProviderRegistration tests.test_governance_jobs.TestGovernanceJobsCancellation.test_cancel_reports_race_when_update_affects_no_row tests.test_governance_jobs.TestGovernanceJobsCancellation.test_concurrent_cancel_is_never_a_silent_no_op tests.test_harness_provider.HarnessProviderTests.test_config_cannot_self_report_provider_kind tests.test_harness_provider.HarnessProviderTests.test_injected_scripted_model_is_registered_as_offline_evidence tests.test_diagnostics_interfaces.DiagnosisInterfaceTests.test_external_agent_diagnostics_whitelist_is_explicit tests.test_diagnostics_interfaces.DiagnosisInterfaceTests.test_governance_jobs_are_cli_only_not_exposed_via_http_or_mcp tests.test_diagnostics.TestDiagnosticPermission.test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry -v
```
真实输出：
```
Ran 12 tests in 1.079s

OK
```

命令 5（收口后单条验证 team-lead 关注的 `tests/test_diagnostics.py:129` 断言）：
```
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics.TestDiagnosticPermission.test_permission_persists_contract_version_and_hash_and_rejects_stale_contract -v
```
真实输出：
```
test_permission_persists_contract_version_and_hash_and_rejects_stale_contract (tests.test_diagnostics.TestDiagnosticPermission.test_permission_persists_contract_version_and_hash_and_rejects_stale_contract) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.117s

OK
```

收口说明：该测试原有的 `assertRaises(DiagnosticIntegrityError)` 针对 `revoke`，与「撤权路径不独立」修复后的新合同冲突。收口时**未删除旧断言绕过**，而是改写为三段显式断言并补一条负向断言区分两条路径：(A) 普通读取仍拒绝旧证据合同 hash（`read_permission` → `DiagnosticIntegrityError`）；(B) 撤权不受证据合同/来源完整性影响，始终可执行且 `revoked_at` 落库；(C) 撤权后普通读取仍被拒（`read_evidence` → `DiagnosticIntegrityError`），证明撤权成功不意味着放行读取。读路径的完整校验（`_permission_tx` → `_verify_sources_tx`、`EVIDENCE_SCHEMA_HASH`）保持不变，只有撤权路径不再复用它。
