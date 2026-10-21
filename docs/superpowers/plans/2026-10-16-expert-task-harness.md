# 专家内任务与 Harness 基础首片 Implementation Plan v0.1

> **For agentic workers:** REQUIRED: 使用 `subagent-driven-development`（有子 Agent 时）或 `executing-plans` 执行本计划；按复选框记录实际进展。本文是待执行计划，不是运行证据，也不自动授权真实触达、外部写入或发布。

**Goal:** 在本地确定性沙盒验证专家版本内任务蓝图、服务周期幂等初始化、内部事项受限管理、有界工作集与最小语义工具合同，不执行对外动作。

**Architecture:** 蓝图属于专家配置并冻结进 AgentVersion；可信主体/服务周期驱动 Task 应用服务，SQLite 事务保存事项、幂等与同一业务事件 envelope。系统装配工作集，假 Adapter 仅披露获准的读取/任务意图入口；模型、调度器、真实渠道和外部 Harness 之后分别接入。

**Tech Stack:** 既有 Python 3.13 核心；首片新增模块仅用标准库 `dataclasses/sqlite3/datetime/unittest`。保留 AgentScope 既有 commit 与 requirements，不引入 pytest、队列、记忆 Provider 或 MCP SDK。

---

日期：2026-10-16。状态：**方案已确定、实现未开始**。主规格为[Task 设计](../../TASK-SYSTEM-DESIGN.md) §2–5、§9–10；整体依赖为[TM 联合计划](../../TASK-MEMORY-INTEGRATION-PLAN.md) TM-01/02 及 TM-03/04 的 Task 子集；真实 host/Worker 披露继续由[AGI-02/03/08](../../AGENT-INTEGRATION-PLAN.md)验收。本计划不替代 S1 音频/SSE Gate，不要求先完成全部用户记忆。

## 范围、前提与交付边界

- 首片支持版本化蓝图、两名虚构用户/两个专家的隔离、可信服务周期、内部任务与触达候选、人工采用内部候选、受限改期/取消意图、恢复和工作集。触达候选本片不采用为可执行任务。
- 首片不启动调度/实际执行，不创建伪 ServiceRequest/Run，不调用真实模型、发送消息或电话，不新增 Web/MCP/生产接口，不实现 TaskAttempt 领取、在途迁移执行或完整用户身份合并。
- 本地使用标准库 SQLite 是首片验证手段，不代表选定生产调度/持久化 Provider。只恢复 Task 子集；不能据此宣称既有 ServiceRequest、幂等写入或完整应用已持久恢复。
- 可信调用上下文携带角色、租户、专家、主体/用途和已批准版本，不能接受模型在工具参数中自报权限。测试中的授权事实由显式假授权器提供，不从画像或 Prompt 推断。
- 当前没有独立 AgentSpec 合同；本片只建立任务配置值对象与 AgentVersion 的导入/冻结校验，不借此补齐整个控制面或发布服务。现有 AgentVersion 是可变 dataclass，`frozen_at` 不证明不可变。
- 所有代码步骤先写失败测试再实现；短步骤以一次测试/一个边界为单位。当前脏工作区内容属于其他工作，写入前重读，禁止覆盖、整包暂存或重置。

### 文件责任图（拟建路径，当前未实现）

| 文件 | 单一责任 |
|---|---|
| `loomrise/tasks/__init__.py` | 无副作用的有限导出，不启动 Worker 或连接 |
| `loomrise/tasks/blueprints.py` | 专家内蓝图值对象、严格解析、规范化指纹与深拷贝冻结 |
| `loomrise/tasks/contracts.py` | 主体/周期、候选、事项、类型化意图与结果合同；不含 SQL/SDK |
| `loomrise/tasks/store.py` | SQLite 事务、唯一键、revision 比较交换、幂等响应与同 envelope 事件存储 |
| `loomrise/tasks/service.py` | 初始化/采用/意图用例及权限、蓝图边界和人工锁定校验 |
| `loomrise/tasks/workset.py` | 已鉴权范围内的有界工作集、摘要和引用展开，不调度任务 |
| `loomrise/tasks/tools.py` | `inspect_context/manage_tasks` 的严格输入/输出及披露快照；只映射至 Task 用例 |
| `loomrise/time_policy.py` | 带时区时间解析、有效期判断和可注入时钟 |
| `loomrise/contracts.py`、`loomrise/ledger.py` | AgentVersion 嵌套解析；运行前事件扩展及旧事件兼容/非变异校验 |
| `loomrise/context.py` | 将已有无效/无时区有效期改为拒载并留原因，不扩展长期记忆 |
| `tests/task_fixtures.py` | 原创虚构蓝图、主体、时钟/授权器和临时数据库构造；无模型/网络 |
| `tests/test_task_contracts.py`、`test_task_store.py`、`test_task_service.py` | 配置/事件/时间、事务恢复、初始化/管理回归 |
| `tests/test_task_workset.py`、`test_task_disclosure.py` | 工作集覆盖、跨范围拒绝、Schema/预算/假 Adapter 降级 |
| `tests/test_s1.py` | 仅追加旧合同/事件/上下文兼容断言，保留原有自定义 runner |

实现模块分别归属同一任务的 Worker；合同/Store 先合并，依赖未稳定前不要并行编辑 `contracts.py/ledger.py`。工作集与工具模块可在应用接口固定后并行，其他人改动不得回退。

## Chunk 1: 配置、时间与运行前事件

### Task 1: 固定蓝图与最小事项合同

**Files:** Create `loomrise/tasks/__init__.py`、`blueprints.py`、`contracts.py`、`tests/task_fixtures.py`、`tests/test_task_contracts.py`；Modify `loomrise/contracts.py` 的 `AgentVersion.from_dict` 及场景包导入/导出。

- [ ] 写 `TaskContractsTest.test_version_blueprints_roundtrip_and_hash`：同一专家局部键可跨普通修订稳定，另一专家同名键互不引用；旧 pack 缺蓝图仍加载为空，含蓝图必须嵌套解析，不能被现有 `from_dict` 静默丢掉。
- [ ] 运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_contracts.TaskContractsTest.test_version_blueprints_roundtrip_and_hash -v`，预期先因新模块/合同不存在失败；保存真实失败，不把导入失败当功能验收。
- [ ] 实现显式蓝图结构：目的/类型、受限触发、采用规则、Skill/工具引用、时间窗、完成判据、调整白名单和触达约束。采用可验证结构字段，不接受 `eval`、任意表达式/cron/代码。重复局部键、未知类型、未知可调字段或缺引用拒绝。
- [ ] 把蓝图与有效依赖版本/指纹、所属租户/专家纳入任务配置快照；由可信版本登记/假授权器确认批准与归属，不能仅凭调用者自报 version_id 绑定别的专家。旧无归属版本只保留 S1 用途，不能直接初始化 Task。使用深拷贝/不可变容器及规范化 JSON 哈希，初始化、管理和披露边界重验；测试外部原 dict/list 改动不影响已绑定快照，直接篡改绑定数据被拒。此项不宣称整个旧 AgentVersion 已实现不可变。
- [ ] 定义 TaskItem 必填 `tenant/agent/subject/service_cycle/blueprint_key`、来源/执行版本、revision、计划、阻断和证据引用。会话/人工事项也绑定专家已批准的适用蓝图/临时事项类型；无匹配类型只保留 Proposal，不能推断完成/执行包络。未确定身份的候选只能留在授权会话/草稿作用域，不成为可领取 TaskItem；任务状态不覆盖 ServiceRequest。
- [ ] 增加 `test_unknown_blueprint_field_rejected`、`test_snapshot_tamper_rejected`、`test_old_pack_without_blueprints_loads`，运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_contracts -v`；预期全部 PASS，序列化保留原字段和新增指纹。
- [ ] 复核本任务 diff；若实施会话执行提交，只暂存本任务明确拥有的文件/hunk，禁止 `git add .`，不得纳入现有无关改动。

### Task 2: 严格时间与兼容事件

**Files:** Create `loomrise/time_policy.py`；Modify `loomrise/contracts.py`、`loomrise/ledger.py`、`loomrise/context.py`、`tests/test_task_contracts.py`、`tests/test_s1.py`。

- [ ] 写 `test_time_requires_timezone`、`test_invalid_context_time_is_not_loaded`、`test_task_event_without_fake_run`、`test_legacy_event_hash_roundtrip`、`test_single_and_tail_event_tampering`。无时区/非法时间拒绝；合法时间按注入时钟比较；未传有效期与非法有效期不混同。
- [ ] 运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_contracts -v`；预期新增边界先失败，尤其覆盖当前 `_expired` 非法时间放行和 `EventLedger.verify()` 调用 `seal` 改写待比较对象的缺口。
- [ ] 实现严格解析与拒载原因。任务计划可明确等待缺时间，但不猜默认时区；ContextFragment 的无效有效期使用跳过及原因事件，不伪记为有效。
- [ ] 扩展同一事件 envelope 的版本、任务/主体/专家关联和可选 request/run：运行事件仍要求合法请求/运行对，运行前事件必须有明确 Task/候选及可信作用域。不造 `request_id=task_id` 等假执行。
- [ ] 旧事件按其原 envelope/schema 计算和验证哈希；不能给旧记录补新空字段后重新 seal 伪造兼容。验证函数独立计算预期哈希、不修改原记录；旧 JSONL 可原样读取/导出，新增格式有显式版本。
- [ ] 再跑 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_contracts -v`，预期全部 PASS；S1 旧事件/片段断言必须保留。事件仅保证完整性检查，不宣称抵抗有权限的全链重写。

## Chunk 2: 持久初始化与受限任务意图

### Task 3: 事务、幂等和恢复

**Files:** Create `loomrise/tasks/store.py`、`tests/test_task_store.py`；扩充 `tests/task_fixtures.py`。

- [ ] 写 `TaskStoreTest`：唯一初始化键、事务中断、两连接竞争、同键不同参数、revision 冲突、关闭/重开数据库、重复事件投影。运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_store -v`，预期先失败。
- [ ] 实现 Task/Proposal、初始化 occurrence、意图结果、当前 revision 和事件的事务存储。来源唯一键使用 `tenant+agent+subject+cycle+blueprint+occurrence`，不含 AgentVersion；另保存来源版本/指纹。初始化 occurrence 是周期内固定发生项，不随本次消息/重连 ID 改变。跨事项语义去重依据主体/目标/业务对象/有效期，不能仅以文本相似度去重。
- [ ] 事件表保存 Task 事务内的同一 RunEvent envelope，是该沙盒的事件权威；JSONL/内存展示为幂等投影，不能在提交前另写“成功”事件或靠双写回调保证一致。Task 当前状态与该事件同事务提交。旧 S1 运行账本仍按原证据范围，不宣称已全量接入数据库。
- [ ] 同幂等键同输入返回已持久化结果；同键不同输入返回冲突。版本、环境和授权信息记录为证据，不因新 attempt/run/version 产生新事项或重置幂等。拒绝事件可留证，但不能半提交事项修改。
- [ ] 运行上述测试，预期两个连接只创建一份事项、事务故障无半成品、重开后返回同 ID/revision/响应；使用临时目录数据库，不提交数据库或用户数据。

### Task 4: 服务初始化、人工路径与最小决策

**Files:** Create `loomrise/tasks/service.py`、`tests/test_task_service.py`；Modify `tasks/contracts.py`。

- [ ] 先写 `test_initialization_is_idempotent_across_versions`、`test_outreach_stays_proposal`、`test_missing_identity_does_not_create_item`、`test_agent_and_subject_isolation`、`test_conversation_todo_reuses_existing_obligation`，运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_service -v`，预期先失败；相同义务兼容则复用并补来源，冲突则留候选，不合并权限。
- [ ] 实现 `initialize_service(scope, approved_version, source_event)`：可信服务周期绑定首次生效版本；重复/换版本初始化返回原事项与保留版本原因，不自动补新蓝图或默迁旧任务。新周期需可信业务事件，不能由工具参数开周期重置计数。未来新增/迁移由独立显式用例处理。
- [ ] 低风险内部蓝图仅在身份、记录权限和条件齐备时自动采用；条件未知保持候选/等待原因。触达无论模型怎样建议都只建 TaskProposal，本片没有采用触达或执行通道。会话提出和人工创建均保留来源引用、目标及缺口，人工可独立采用/拒绝获准内部候选；增加无匹配批准类型不得采用的断言。
- [ ] 写 `test_adjustment_envelope_and_human_lock`、`test_stale_revision_and_revocation_rejected`、`test_coupled_batch_is_atomic`、`test_no_status_or_policy_override`。将允许窗口内改期与越界、改渠道/频次/承诺/完成状态分别断言。
- [ ] 实现类型化 `propose/adjust/request_cancel`：scope 来自可信上下文；修订含 base revision、幂等和证据；只接受蓝图白名单。人工锁定默认仅能提出建议；本片不实现人工应急解锁。批量只在同主体/周期，任一项失败则全批不修改；禁止跨主体整批操作。
- [ ] 未执行事项的取消由服务端核验取消权限、批准停止条件/明确用户撤销/有权人员决定，再确认不存在活动尝试后裁决并留证；无条件的模型建议保留待人审，不自动丢弃服务承诺。含运行/未知外部尝试的输入返回 `execution_not_supported` 或保持取消待协调，不能假装停止。`set_status/mark_completed/mark_sent`、硬删除、任意代码与蓝图修改一律拒绝。
- [ ] 明确变化失效规则：计划/必要事实变化增加 revision 并使旧决策/确认失效；拒绝的变更不增加事项 revision。同键重试返回同结果；改期不更换来源 occurrence 或新建义务。
- [ ] 再跑 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_service test_task_store -v`，预期全部 PASS。保留版本升级、删蓝图、模拟回滚后事项/取消事实不丢失的断言；真实在途迁移/频次发送由 TM-07/08 后验。

最低端到端断言以如下真实可执行测试为目标；`make_task_sandbox` 在 fixtures 内构造时钟、授权器、临时 SQLite、两个已批准专家版本和服务，不连接 SDK：

```python
def test_initialization_is_idempotent_across_versions(self):
    with make_task_sandbox() as box:
        first = box.service.initialize_service(box.scope, box.v1, "init-1")
        again = box.service.initialize_service(box.scope, box.v2, "init-2")
        self.assertEqual(first.item_ids, again.item_ids)
        self.assertEqual(first.proposal_ids, again.proposal_ids)
        self.assertEqual(1, len(first.item_ids))
        self.assertEqual(1, len(first.proposal_ids))
        item = box.store.get_item(box.scope, first.item_ids[0])
        self.assertEqual(box.v1.version_id, item.source_agent_version)
        self.assertEqual(box.v1.version_id, item.execution_agent_version)
        self.assertEqual([], box.external_calls)
```

## Chunk 3: 有界工作集、语义工具与交接

### Task 5: 工作集与精确展开

**Files:** Create `loomrise/tasks/workset.py`、`tests/test_task_workset.py`；Modify fixtures。

- [ ] 写当前相关/将到期/逾期/待对账/阻断义务并集、近期完成摘要、跨租户/专家/主体拒绝、过期引用、极小预算测试。运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_workset -v`，预期先失败。
- [ ] `build_workset(scope, route, clock, limits)` 从已授权账本集合查询，稳定排序/去重、分页并保存选择/跳过原因。测试显式登记前瞻窗口/条数/token 上限，这些是沙盒参数而非产品固定阈值。
- [ ] 未决项给 ID、目标、计划摘要、缺口、来源/执行版本和允许调整；完成项给实际结果事实/引用，不能把 sent 当 succeeded。fixture 可表达将来的对账/执行状态，但不得开放写这些状态的模型操作。
- [ ] `expand_context` 仅接受白名单对象引用和必要范围，再查最新角色/主体/用途/版本；先鉴权后读取，不把无权对象内容带入错误。结果有条数/字节/token 界限及来源版本，截断保留受限继续读取引用。
- [ ] 安全/停止必要摘要不可被裁剪；预算不足返回明确阻断及缺项，不输出可执行动作。工作集外事项仍通过 Store 的全局去重/冲突查询参与服务端检查，提示词不是调度状态源。
- [ ] 再跑 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_workset test_task_service -v`，预期覆盖并集和负例全部 PASS，不泄露其他范围或加载全历史。

### Task 6: 两个语义工具与假 Adapter 披露

**Files:** Create `loomrise/tasks/tools.py`、`tests/test_task_disclosure.py`；不修改现有在线 `ExecutionService` 的工具注册循环。

- [ ] 写 `test_only_allowed_schema_is_visible`、`test_guessed_hidden_tool_rejected`、`test_stale_schema_and_revocation_rejected`、`test_external_author_cannot_adjust_production_task`、`test_static_adapter_requires_new_snapshot`。运行 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_disclosure -v`，预期先失败。
- [ ] 系统工作集无需 get-list Tool；Task 工具只提供 `inspect_context` 和 `manage_tasks`。解析器拒绝未知操作/额外权限字段，读和意图都走同一用例。实际业务工具不合并到这两个入口，也不提供万能调用器。
- [ ] 先做纯函数披露计划与假 Adapter：L0 安全/任务/能力摘要，L1 所选蓝图/Skill 和获准精确 Schema，L2 受限证据/结果。输入快照保存角色/用途/环境、专家版本、实际可见 ID/Schema hash、必要事实引用、加载/跳过、预算及授权版本。
- [ ] 服务端验证调用所属快照、可见工具、Schema 版本与最新授权；猜名、旧缓存、读后撤权仍拒。创作角色只可提出登记范围候选，不能复用在线角色的调整/取消权；无需给它展示 Task 生产工具。
- [ ] 假静态 Adapter 每次运行固定最小集合；需要额外 Schema 时返回需新快照/运行边界，旧快照不能直接扩权。假动态 Adapter 也必须更新已审计快照后使用，不以发现代替授权。
- [ ] 再跑 `rtk proxy env PYTHONPATH=.:tests python3 -m unittest test_task_disclosure test_task_workset -v`，预期全部 PASS。只报告假 Adapter 合同通过，不能称 Codex/Claude/MCP 已兼容，也不能把估算 token 当真实收益。

### Task 7: 回归、证据与后继移交

**Files:** 更新本计划执行清单、Task/TM/AGI 对应状态；实际实施后再创建 `docs/TASK-SANDBOX-REPORT.md` 并登记总索引，不提前建成功报告。

- [ ] 新增测试均使用标准库 unittest，按单测试失败 → 最小实现 → 通过留证。全量新测试命令：`rtk proxy env PYTHONPATH=.:tests python3 -m unittest discover -s tests -p 'test_task_*.py' -v`，预期退出 0，无跳过安全用例。
- [ ] 使用实际可用核心虚拟环境跑 S1；不存在时可在被忽略目录新建：`rtk proxy python3 -m venv .build/task-core`，随后 `rtk proxy .build/task-core/bin/python -m pip install -r requirements.txt` 和 `rtk proxy .build/task-core/bin/python -m pip check`。仅实施时执行，当前文档轮未创建/安装。
- [ ] 用该环境重跑新测试，再执行 `rtk proxy env PYTHONPATH=. .build/task-core/bin/python tests/test_s1.py` 与 `rtk proxy env PYTHONPATH=. .build/task-core/bin/python -m loomrise.cli replay --out /tmp/loomrise-task-sandbox/replay-s1.json`。预期自检退出 0、既有确定性案例 11/11；使用脚本回放，不用可能读取本机真实凭据的普通 `cli run` 替代。
- [ ] 运行 `rtk git status --short`、`rtk git diff --check`、`rtk git check-ignore -v private/`、`rtk git diff --cached --name-only`；检查新增文件语法、链接和索引。暂存敏感/私有文件立即停止处理，不覆盖既有工作。
- [ ] 报告精确命令、环境/版本、正反例数量、事务故障与恢复证据、真实失败和未覆盖项。没有实际运行不勾选；若本机依赖/网络不满足，保留失败证据与未完成状态，不把历史 S1 结果充当本次结果。
- [ ] 交接 AGI-02/03/08 的真实工具/Schema 装配和 host 测试、TM-05 的只读上下文、TM-07 的调度/跨事项额度与占用原子预留/未知占额/对账/在途迁移，以及 TM-08 的获授权渠道沙盒。首片未测发送，不能宣称跨 Task 联系额度已通过。S1 剩余音频/SSE、完整发布服务、生产身份和持久化仍独立验收。

## 验收结论应如何记录

首片通过仅表示：专家局部任务配置可冻结/恢复，适用默认事项初始化不重复，受限管理不会伪造执行/完成，工作集与假 Adapter 的读取/披露/意图校验可复核。它不证明真实主动服务、完整 Agent 决策质量、云服务或生产级安全已完成。full/progressive 的真实模型质量/Schema/结果 token、往返和时延对照留在 AGI Gate；先登记同条件阈值，实测后再决定是否有收益。

当前交接：已完成主设计、整体分期和本文件；全部实现/测试复选框保持未勾选。下一步从 Chunk 1 的失败测试开始，不需要重复询问已经确定的归属/共享策略取舍，也不据本文启动定时任务或真实触达。
