# AGI-07/08 最小合同独立规格审查（2026-11-04）

## 元信息

- 审查对象：`docs/superpowers/plans/2026-10-30-r3-development.md:29-36` 的「最小合同」六条，及 :45「先独立规格审查，再代码质量审查」。
- 审查方式：逐条对照源码与本机可跑的 unittest，不依赖真实 Provider、真实 host 或公网。
- 审查顺序：本件为**第一步独立规格审查**；第二步代码质量审查见 `docs/superpowers/reviews/2026-11-04-agi-0708-code-quality-review.md`。
- 本轮修复：5 个确凿缺口（替身冒充真实 Provider、作业入口未复用应用服务、external_agent 绕过动作白名单、撤权路径不独立、cancel 静默无效果），新增 12 项测试。
- 工件性质：本机确定性 fixture 证据；**真实 harness Provider / 真实 host Skill 激活 / 质量对照均未联调**（见文末）。
- 基线：专项 93 项 OK、全量 Python 702 项 OK（只读审计记录）；本轮专项 105 项、全量 714 项。

## 逐条核查

### 合同 1（plan :31）许可字段、到期与撤销

**要求**：许可绑定 tenant、Agent、recipient actor、选定 run/case、证据合同版本/hash、用途、到期时间与撤销状态；调用方不能自报角色、审定身份或生产权限；缺少有效许可时外部 Agent 仍不能调用原运行查询。

**实现位置**：
- `loomrise/diagnostics.py::DiagnosticsService.issue`：写入 `tenant_id / agent_id / recipient_actor_id / issued_by / purpose / issued_at / expires_at / selection(runs,cases,evidence_contract) / permission_hash`，`_principal(owner=True)` 限定签发者。
- `loomrise/diagnostics.py::DiagnosticsService._permission_tx`：每次读/提交复验身份、`permission_hash`、`evidence_contract == {schema_version, schema_hash}`、`purpose`、时间窗、撤销状态，并调用 `_verify_sources_tx` 复核来源。
- `loomrise/diagnostics.py::DiagnosticsService.revoke`（本轮修复）：撤销只做 owner 身份 + tenant/agent 归属校验，不再经 `_permission_tx` 的合同/来源/时效校验，旧 Schema/hash、来源失效、过期下始终可执行。
- `loomrise/configuration.py::_execute`（本轮修复）：`diagnostics.*` early return 之前先做 external_agent 显式白名单 `_EXTERNAL_AGENT_DIAGNOSTICS_ACTIONS`；`run.diagnostics` 等非白名单动作对 external_agent 显式拒绝。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics.TestDiagnosticPermission tests.test_diagnostics_interfaces -q`

**结论**：符合。字段齐全、逐次复验、撤权/到期有拒绝路径；本轮补齐「撤销在旧记录下不被锁死」与「外部 Agent 白名单显式化」，白名单不再被 early return 绕过。

### 合同 2（plan :32）证据边界、脱敏、gaps、blind 与来源复核

**要求**：最多 10 run、每 run 最多 100 条白名单事件、总快照 ≤128 KiB；只保留已登记结构字段和原因码，不返回客户文本/完整配置/工具参数与结果/来源原文/自由错误/凭据；超限显式返回 gaps，不把裁剪后证据当完整轨迹；案例仅服务端受信登记，保存不可变 source id/hash、审定/消费状态与用途并由来源复核；状态未知、未消费 blind、未知分类拒绝；不接受调用方自报 `reviewed=true/blind=false`；不改真值/Case/盲测消费状态。

**实现位置**：
- `loomrise/diagnostics.py` 常量 `MAX_RUNS=10 / MAX_CASES=10 / MAX_EVENTS_PER_RUN=100 / MAX_SNAPSHOT_BYTES=128*1024 / MAX_REPORT_BYTES`，以及 `_EVENT_TYPES / _EVENT_FIELDS / _ENUM_VALUES / _NUMERIC_MAX / _BOOL_FIELDS` 白名单、`REPORT_LIMITATIONS / _BASE_LIMITATIONS`。
- `DiagnosticsService._snapshot_tx` / `_project_event`：按白名单投影、字节预算裁剪并写 `gaps`（`total_event_count / whitelisted_event_count / included_event_count / omitted_event_count / truncated / reasons`）。
- `DiagnosticsService._case` / `ORIGINAL_CASE_REGISTRY` / `TrustedDiagnosticCase`：只读服务端登记，校验 `content_hash`、`case_id`、`status=reviewed_original / purpose=diagnosis / blind_status=not_blind`；文件级自报不授信。
- `EVIDENCE_CONTRACT_DESCRIPTOR` / `EVIDENCE_SCHEMA_HASH`：投影结构变更即使既有许可失效而非含糊放行。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics.TestDiagnosticEvidence tests.test_diagnostics.TestDiagnosticReportsAndStorage -q`

**结论**：符合（既有实现 + 既有专项覆盖）。边界常量、脱敏投影、显式 gaps、案例登记与来源复核均在位；报告不接受自报审定/blind 字段。

### 合同 3（plan :33）proposal 报告、六类与精确证据引用

**要求**：报告为 `proposal`，类别仅 `knowledge/routing/loading/policy/tool/rule`，每个候选至少引用一个已披露的精确证据 ID；未知/不足明确为不足；只提名，不升级为事实或业务终态。

**实现位置**：`loomrise/diagnostics.py::REPORT_JSON_SCHEMA`（`status` const `proposal`、`REPORT_CATEGORIES` 六类、`evidence_ids` 正则 + `uniqueItems`）、`DiagnosticsService.validate_report`（逐类发现或 `insufficient_categories`、`limitations` 必须继承快照缺口、`evidence_ids` 必须来自当前快照）、`_submit_report_tx`（同事务内重验许可/快照 hash 后落 `diagnosis_reports`）。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics.TestDiagnosticReportsAndStorage -q`

**结论**：符合。报告只写 `diagnosis_reports`，不触达业务表。

### 合同 4（plan :34）Worker 与业务 Run/TaskItem 分离、冻结与显式控制

**要求**：独立作业，冻结发起身份、目的、许可、输入哈希、精确工具 Schema/hash、Provider 标识、总时限/尝试数/输出上限；固定最小只读工具子集；显式启动/取消/安全重试；不装定时任务、不自动恢复运行。

**实现位置**：`loomrise/governance_jobs.py::GovernanceJobs.create`（冻结 `purpose / principal_actor_id / permission_id / snapshot_id / input_hash / provider / tools / tool_hash / report_schema_hash / max_attempts / total_seconds / total_tokens / attempt_tokens / max_output_bytes`，本轮新增 `evidence_class`）、`DIAGNOSIS_TOOL`（单只读工具）、`run / cancel / retry / recover`；`loomrise/durable_store.py` 的 `governance_jobs / governance_attempts` 独立表。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_governance_jobs tests.test_diagnostics_interfaces -q`

**结论**：符合。作业表与业务 `runs / requests / service_requests / task_items` 分离；本轮把 `provider_kind / version / contract_hash` 纳入冻结并登记 `evidence_class`。

### 合同 5（plan :35）8 状态机、CAS/预算/重启裁决

**要求**：`queued / running / cancel_requested / cancelled / interrupted / failed / exhausted / succeeded` 与 Provider 停止/结果 `unknown` 分开留证；本地 interrupted 不证明远端停止；Provider 完成与报告原子落库分开；产物 CAS、许可有效性与冻结输入 hash 重验在同一事务；CAS generation 防重复领取/迟到输出；取消未确认保持待确认；未知用量保守占预算；重启旧运行只经明确恢复检查进入 interrupted，再由获权人显式安全重试，预算不重置。

**实现位置**：`loomrise/governance_jobs.py::GovernanceJobs.run`（领取 CAS + generation + reserved_tokens）、`_finalize`（同事务提交报告 + CAS + 迟到结果围栏）、`_timeout_fence`、`_mark_provider_invoked`、`cancel`（本轮补 `cur.rowcount != 1` 竞争检查）、`recover`、`retry`（预算耗尽判定 + rowcount CAS）。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_governance_jobs.TestGovernanceJobsLifecycle tests.test_governance_jobs.TestGovernanceJobsCancellation tests.test_governance_jobs.TestGovernanceJobsConcurrency -q`

**结论**：符合。本轮补齐 cancel 两处 UPDATE 的 rowcount 检查及竞争/并发测试，消除跨连接并发下静默无效果。

### 合同 6（plan :36）Provider 隔离与分开登记

**要求**：首个真实 harness Provider 先核官方合同、锁版本并隔离工具/文件/网络/凭据；无可用 Provider 明确不可运行；直接结构化模型、脚本 Provider 与真实通用 harness 分开登记，不能互相替代验收。

**实现位置**：
- `loomrise/diagnostics.py`（本轮新增）`PROVIDER_KIND_OFFLINE_SCRIPTED / PROVIDER_KIND_STRUCTURED / PROVIDER_KIND_REAL_HARNESS`、`ALLOWED_PROVIDER_KINDS`、`PROVIDER_VERSIONS`、`PROVIDER_CONTRACT / PROVIDER_CONTRACT_HASH`。
- `loomrise/adapters/harness.py::AgentScopeDiagnosisProvider.__init__`：禁止 config 自报 `provider_kind`；按是否注入模型判定 kind（注入脚本/替身 → `offline_scripted`，未注入 → `real_harness`）；descriptor 带 `provider_kind`、按 kind 区分的 `version`、`contract_hash`。
- `loomrise/governance_jobs.py::GovernanceJobs.create`：校验 `provider_kind` 必须属服务端登记的非真实类别（禁止自报 real）、version 与 kind 一致、`contract_hash == PROVIDER_CONTRACT_HASH`；成功登记为 `evidence_class=offline_scripted / offline_structured`，绝不写入真实 Provider 证据分类。
- `loomrise/config_cli.py::_diagnostics_provider`：Provider 配置不可用返回 `provider_unavailable`，不静默降级为替身。

**验证命令**：
`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_harness_provider tests.test_governance_jobs.TestGovernanceProviderRegistration tests.test_governance_harness_integration -q`

**结论**：符合本轮修复范围。替身成功（`ScriptedChatModel + example.invalid + test-only-credential`）明确登记为 offline/scripted 证据；「缺 kind / 自报 real / 旧错 contract hash / 替身贴真实 version」均有负向拒绝。**真实 harness Provider 未联调**（见未覆盖项）。

## 作业入口决策（plan :43，本轮缺口 2）

经工程判断选择 **(b)「作业仅 CLI、HTTP/MCP 不暴露」并做实，而非 (a)**，理由：

1. job 的 `create / run` 需要注入 Provider **对象**（非 dict）且 `run` 为 async；`ConfigurationApplication.execute(action: str, payload: dict)` 的同合同契约无法承载对象注入，强行在同步 execute 内 `asyncio.run` 会与 HTTP 已有 event loop 冲突。
2. 把作业暴露到 HTTP/MCP 会把「触发外部 Provider 调用」能力从本地 CLI 扩展到网络可达接口，实质扩大权限面，违背 team-lead「以不扩大权限为前提」及 plan :43「诊断 MCP server 只披露该工作流所需工具，不借配置工具取得发布/在线业务能力」。
3. 因此不留半成品：在应用服务层用 `_GOVERNANCE_JOB_ACTIONS` **显式登记并拒绝**全部 `diagnostics.job.*`（`forbidden`），CLI 保留专用入口；CLI/MCP/HTTP「同合同」定义为三者经同一 `ConfigurationApplication.execute` 得到一致的拒绝结果，而非三者都能跑 job。

回归：`tests/test_diagnostics_interfaces.py::test_governance_jobs_are_cli_only_not_exposed_via_http_or_mcp` 断言 application 层对 owner/external_agent 均 forbidden、HTTP 403、诊断 MCP 工具集无 job 工具、全程 `governance_jobs` 表 0 行；`tests/test_config_cli.py::test_governance_job_cli_requires_provider_and_supports_cancel` 保留 CLI 作业 create/cancel 正向路径。

## 未覆盖项（明确标注，不记为通过）

- **真实 harness Provider 未联调**：本机只有 `ScriptedChatModel` 替身、`https://provider.example.invalid/v1`、`test-only-credential`；未核真实官方合同、未接真实模型凭据/网络、未验工具/文件/网络/凭据隔离的真实性。
- **真实 host Skill 激活未联调**：读取 MCP `DIAGNOSIS_SKILL_URI` resource 不等于真实 host 已完成 Skill 激活。
- **质量对照未联调**：多样本模型质量、真实 Provider 质量矩阵、目标角色任务基线均未跑。
- **最终复核（主 agent，2026-11-04 18:25）**：本工件自身改动纯 Python、不宣称前端通过；主 agent 已独立复跑前端 340/340、Canvas 构建 Exit 0、Python 全量 739 项 OK、S1 自检与合同语义自检全部通过。工件内 714 / 733 项为各工作包落盘时点快照；AGI 5 模块专项收口后 61 项、8 模块 105 项。
- 真实渠道/公网/生产身份隔离、R2/R3 Gate 继续按未通过记录。

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
真实输出（节选末行）：
```
  ok    平铺 when 不触发深度问题

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
