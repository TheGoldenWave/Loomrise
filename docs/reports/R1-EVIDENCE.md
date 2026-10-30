# R1 证据摘要 v0.13（进行中）

> 2026-10-29 更新 TaskItem 最小持久化、SQLite Online Backup、可运行的十项发布预检、故障注入及显式安全恢复拒绝路径证据；另复跑配置工作台单测与桌面/手机侧栏浏览器回归。**规则同 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) §0**：原始件留本地 `runs/R1/`，本文件只记结论、样本量与环境；矩阵"证据位置"列指向本文锚点。
>
> **本文件在 R1 未完成时就已经存在，这是故意的**——先把已验证部分与未验证部分分开写清，比事后一次性补写更不容易把"想做的"写成"做过的"。
>
> R1 证据与决定状态（2026-10-30）：**WP1 已落；WP2/WP5/WP7 部分；WP3/WP4/WP6/WP8 后端实现与单测已落；WP9 配置页面已接入 loopback HTTP 并完成本机 fixture 浏览器联调。** 用户已明确确认 R1 Gate 通过，并授权跳过产研/策略运营复核与签核流程；矩阵 M-A-01/02/03/06/17/18 已按本报告中的既有可复现工件及本轮 M-A-20 恢复补充证据更新为通过。该记录是用户的流程与版本验收决定，不伪造责任角色签字；不扩大技术证据边界。仍不覆盖断电/介质损坏、多进程 worker 所有权、生产身份和真实外部 exactly-once。R2 实施与最终快速验收见 [R2 证据摘要](R2-EVIDENCE.md)。

## 环境

| 项 | 值 |
|---|---|
| 机器 / 系统 | Apple M4 / macOS 15.6.1 |
| Python | 3.13.12（仓库根 `.venv`） |
| 存储 | 标准库 `sqlite3`（**零新依赖**），WAL + `synchronous=FULL` + 进程内单写者锁 |
| 测试 | `unittest`，全部本地、不触网、不调模型 |

## WP1 持久化底座 — 已落

`loomrise/durable_store.py`：请求/运行/事件/幂等/outbox、事件接纳回执与冲突诊断、配置草稿/稳定快照/候选及 TaskItem 等表由 schema v5 管理；请求含可选 `trigger_event_id`。空库和既有请求迁移可重复执行。v4 只落 mapped `subject_id`，并在旧库迁移时清理 ephemeral、空 scope 或未知 scope 的主体 ID。`backup_to(path)` 使用 SQLite Online Backup API，在存储锁内创建一致性数据库副本，并拒绝覆盖活动数据库本身或任何已存在目标文件。

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 不是"仅事件文件落盘"（`M-A-16`） | `test_migration_from_empty` 断言结构化表存在；`test_online_backup_reopens_with_records_and_valid_event_chain` 在线备份后重开数据库，核对请求/运行/事件和哈希链；`test_backup_rejects_live_database_path` 与 `test_backup_does_not_overwrite_existing_file` 验证不覆盖源库或现存文件 | 通过；不覆盖云端备份、异机灾备或介质损坏 |
| 提交点原子：请求/运行/事件要么一起可见要么都不可见（`M-A-19`） | `test_partial_commit_is_rolled_back` 在 COMMIT 前注入异常，断言三张表都为空 | 通过 |
| 事件哈希链可验证（`M-A-19`） | `test_event_hash_chain_verifies`、`test_tampered_event_fails_verification`（改 `event_json` 后校验必须失败） | 通过 |
| 落库链按**运行**封链 | `test_store_owns_the_persisted_chain`：故意传错 `prev_hash`，存储层重封 | 通过 |

**一个实现决定（不是文档承诺）**：内存账本的哈希链是"进程内一条链"，落库链是"每个 run 一条链"。进程重启后账本从 GENESIS 重开，若照抄账本的 `prev_hash`，库里的链必然断。**链尾归存储层持有**，`_append` 用同一 run 的上一条事件重封。

**局限**：`test_durable_transaction_crashes.py` 以子进程 `os._exit` 覆盖当前已识别的 SQLite 写事务点，包括运行/事件/outbox、配置草稿/版本/revision/候选、TaskItem 创建/取消、事件冲突诊断、schema 首建及 v2/v3/v4 迁移；`test_durable_outbox.py` 另覆盖 `commit_write` 提交前/后退出。系统信号/断电、介质故障、多进程 worker 所有权和真实外部副作用 exactly-once 仍未测。

## WP2 恢复与故障 — 部分

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 本地 `running` 旧尝试记失败、保留中断事实（`M-A-02` 的裁决部分，Task §7.1） | `test_local_running_is_interrupted_not_resumed`：owner 从 p1 换 p2 打开同一库 → `status=failed`、`finish_reason=restart_interrupted`、末尾事件 `run.interrupted`、链仍可验 | 通过 |
| 恢复可重复执行，不重复判中断 | `test_recover_is_idempotent` | 通过 |
| 旧代迟到写入被拒（`M-A-21` 的 R1 部分） | `test_old_run_rejects_late_write`：恢复后 `commit_write` 抛 `RuntimeError` | 通过 |
| 新尝试是新 Run，有自己的链并指向旧运行（lineage） | `test_new_attempt_keeps_lineage_and_own_chain`：`run_id` 不同、`lineage_parent` 指向旧 run、`occupancy_generation=2`、新链从 seq 0 开始 | 通过 |
| 显式安全恢复仅接受兼容版本、可恢复状态且无确认事实/已提交写入的中断请求 | `tests/test_durable_recovery.py`：成功恢复后重问确认；拒绝已有 `permission.confirm_answered`、已提交写入、配置版本变化和取消状态 | 通过（R1 受限新尝试） |
| 两次恢复竞争只允许一次接管 | `test_recovery_fences_a_second_attempt_after_first_claim`：第一次原子创建新 Run 后，第二次以旧状态/旧 Run 申请被拒；运行总数仍为 2 | 通过（单 SQLite 写者） |
| 同进程内运行被"接管"而非判中断 | `test_adopted_run_keeps_running` | 通过 |

**未做（不冒充）**：
1. `waiting_confirm` 在恢复后仍持久、可枚举，旧 Run 会失败并留中断事实；不自动唤醒、不沿旧 Run 续执行。实际 suspend/wake 与确认上下文重验属 R2 `M-A-20`。
2. R1 的最小 `TaskItem` 持久化只覆盖已采用事项的身份、主体、服务周期、目的、来源版本、状态与 revision；未实现完整 Proposal/Attempt、调度、触达授权或执行生命周期。M-A-04 的取消×恢复用例见下文。
3. 多进程/多 worker 所有权不安全，这是 R5a 的 Gate；本层只承诺单写者。

## WP7 幂等键语义 — 部分

`action_key(action, key) = f"{action}::{key}"`，**键绑定具体业务操作**而不是绑请求（`M-A-06`）。

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 同一 `(action, key)` 只产生一次写入，第二次返回原 `result_id` | `test_same_action_key_writes_once` | 通过 |
| 同一个键用在两个动作上是两件事 | `test_same_bare_key_on_different_action_is_distinct` | 通过 |
| 幂等记录与 outbox 意图同事务 | `test_write_emits_outbox_intent` | 通过 |
| 跨渠道/跨重启幂等 | `test_idempotent_key_survives_restart`：先从文字入口写入，关闭并重开 SQLite 后从语音入口用同一操作键重试；新 Run 复用原 `result_id`，无新增写入或 outbox 行 | 通过 |

**局限**：业务动作并发重复（`M-A-05`）与未知结果对账（`M-A-07`）属 R2，未做；上述业务写入测试证明串行、跨渠道与跨重启重试不重复。下面的入站事件接纳并发证据不替代这些业务副作用 Gate。

## 事件级 Run 接纳 — 已验证的 WP1 / WP2 / WP7 子集

2026-10-26，本机 Python 3.13.12 / SQLite 3.50.4，标准库实现、零新增依赖。来源事件唯一身份为 `(tenant_id, scenario_pack_id, trigger_kind, trigger_event_id)`；版本与渠道保存首次接纳值，不加入唯一身份。正文与主体语义按稳定 JSON 计算 SHA-256，用于识别身份复用冲突，不用于猜造来源事件 ID。

| 验证 | 证据与结论 |
|---|---|
| 原子接纳与回滚 | `test_atomic_first_duplicate_and_conflict`、`test_failed_commit_rolls_back_all_four_records`：receipt/request/Run/首事件同事务；重复引用原运行，冲突只追加哈希诊断，不覆盖首次输入 |
| 独立连接并发 | `test_independent_connections_compete_for_one_receipt`：两个线程、两个 SQLite 连接，同事件恰有一个 `created` 和一个 `duplicate`，四类记录各一条 |
| 提交后响应丢失及恢复 | `test_process_exit_after_commit_preserves_receipt`：子进程提交后 `os._exit(17)`，父进程重投命中原 receipt；`test_committed_but_unanswered_admission_survives_reopen` 同时覆盖恢复判失败后仍不另建运行 |
| 运行中与业务写入终态重投 | `test_inflight_duplicate_does_not_execute_or_take_ownership`、`test_duplicate_and_conflict_never_reenter_execution`：重复/冲突不进入模型、上下文或沙盒，不增加执行事件与 outbox |
| 版本、渠道、请求 ID 与主体 | 原身份不随版本、渠道、请求 ID 改变；更换主体产生内容冲突；不同租户/专家/事件类型/事件 ID 独立接纳 |
| 合法续接与无 ID | 同 request、新事件可建新 Run；省略 ID 不继承上一轮事件身份，首事件标 `event_deduplication=false`；声明 ID 却不提供 store 时显式拒绝 |
| v1 迁移与两类哈希链 | 旧请求列原值保留、迁移可重复；有 ID/无 ID 交错运行后，内存全局链、JSONL 重载链与 SQLite 每 Run 链均可验证。sink 接收副本，避免持久层重封污染内存链 |

入口示例：`await service.handle_text(text, trigger_event_id=source_id, trigger_kind="inbound_message")`，须配置 `store`。来源 ID 由受信调用方按每轮传入。`RunResult.admission_status` 区分 `created/duplicate/conflict`；重复/冲突只返回原请求/运行引用与 `run_status`，不重放文本、不把原结果计为新增写入。请求可以跨轮次变化，查询该次运行应读取 `run_status`，不能从请求当前状态推断原 Run 终态。直接使用 `DurableRunAdapter.begin()` 的调用方改取 `admission.run`，并只在 `created` 分支执行。

验证：新增测试 **16/16**；`unittest discover` **37/37**（存储 15 + 恢复 6 + 新增 16）；S1、合同语义、语音通道、语音配置的脚本自检分别通过；固定案例回放 **11/11**，原始回放件 `runs/R1/event-idempotency-replay.json` 与同目录 `events/`。`unittest discover` 不收集四个脚本式自检，因此分别运行，不能把 37 项称为全项目覆盖。

边界：本轮只验证同库事件接纳与提交后子进程退出；没有提交中 SIGKILL、断电、多主机、并发 Worker 所有权或供应商 Webhook 实测。事件源的 ID 稳定性、认证及保留期仍由后续入口接入验收；不因本子集通过宣称 R1 整体完成。

## WP2 Outbox 与配置后台后端 — 已落代码，Gate 仍在跑

`loomrise/outbox.py` 提供最小 at-least-once 投递函数：处理器收到持久 outbox 记录和稳定 `outbox_id`；只有处理器正常返回后才标记 `delivered`。失败保留 `pending`，`attempts` 在调用前递增。ack 重放不会二次改写已投递记录。消费端必须用稳定 ID 去重，外部副作用不承诺 exactly-once。

| 验证 | 证据与结论 |
|---|---|
| 写事务内进程退出 | `tests/test_durable_outbox.py`：子进程在幂等记录、事件、outbox 各自插入后分别 `os._exit`，另测提交前退出；每次重开后幂等/outbox/工具结果均无半记录，恢复只追加中断事实，哈希链有效 |
| 提交后进程退出 | 同文件：提交后 `os._exit`，重开可见一条 pending outbox；新 Run 用原业务幂等键重试复用 `result_id`，不新增幂等、outbox 或工具事件 |
| 消费者副作用后、ack 前退出 | `tests/test_outbox_dispatch.py`：模拟消费者以独立 SQLite inbox 按 `outbox_id` 去重；首次效果写入后模拟 ack 崩溃，重投再次收到同一 ID，最终效果仍一条 |
| Handler 失败与重试 | 同文件：失败后仍 pending、尝试计数增加；重试 ID 不变，成功后只记一次 delivered |

该证据覆盖 `commit_write` 内的三个记录插入点、提交前/后的进程退出，以及一个遵守幂等合同的模拟消费者在副作用后/ack 前退出。独立 `set_request_state` 的硬退出回滚、重试和恢复不复活也在下方矩阵测试中覆盖。dispatcher 没有 claim lease，多 dispatcher 可并发重复调用 handler；断电、多主机和真实外部服务仍未验。

配置后端实现位于 `configuration.py`、`config_validation.py`、`config_http.py`、`config_cli.py` 与 `adapters/mcp.py`，统一调用 `ConfigurationApplication`：

- SQLite 持久化稳定快照、单专家草稿与 revision、冻结候选及字段级 diff；稳定版本只读，revision 使用 compare-and-swap，候选冻结要求校验通过和幂等键。
- HTTP API 只绑定 `127.0.0.1` 并校验 loopback Host；浏览器 Origin 使用精确 allowlist，默认只允许 `http://127.0.0.1:8765` 与 `http://localhost:8765`，其他本地预览源须通过 `LOOMRISE_CONFIG_ALLOWED_ORIGINS` 或 fixture 的 `--allowed-origin` 显式配置。CLI 与 stdio MCP 使用同一 schema envelope。身份来自权限为 `0600` 的本机 principal 文件；HTTP/MCP 工具参数不能覆盖租户、角色或专家授权范围。
- 外部 Agent 只可读、建受限草稿/候选和 patch 允许的人设字段；没有稳定版本写、审批、发布或生产业务写权限。MCP 可由 `loomrise config mcp` 启动；CLI 也支持配置 API 和仅本机 HTTP 服务。
- R1 配置校验覆盖 Unit 清单字段与接口、G0、HardRule v0.2、确定性条件/字段路径、G1 隔离、严格时区时间及 `task_blueprints` 的专家内唯一 `blueprint_key`；`Unit.body` 仍为空，不解析或执行 route graph。
- `AgentVersion.task_blueprints` 字段已加入。Task blueprint 的主体/用途对象形状尚未定版；`ContextFragment` 现支持可选 `subject_id/subject_scope`，主体或作用域不匹配会 fail-closed 并记录跳过原因。`ServiceRequest.persistent_subject` 确保只有 mapped 主体落库，ephemeral/未知 scope 不写主体 ID；v4 迁移同步清理旧版非 mapped/未知 scope 值。schema v5 新增 M-A-04 所需最小 TaskItem 身份/来源/状态/revision；用途隔离与完整任务合同仍未实现，WP5 仍部分。

新增 `tests/test_config_cross_entry.py`：以同一 SQLite 文件分别打开 HTTP app、CLI 入口和 MCP tool adapter，验证跨入口读写相同 revision/config；包括数组索引与带点字段名的 JSON path patch、字段 diff 往返、相同字段路径校验错误、非法草稿冻结被拒、过期 revision CAS 冲突，以及关闭并重建 HTTP app 后草稿/稳定快照保持不变。该测试使用 MCP 内存 client session，不是 stdio 进程验收。

HTTP 错误 envelope 与 CLI/MCP 共用；HTTP 状态码按错误类别区分：`invalid_request=400`、`forbidden=403`、`not_found=404`、`revision_conflict=409`、`validation_failed=422`。

2026-10-29 回归：`PYTHONTRACEMALLOC=5 PYTHONWARNINGS=error::ResourceWarning` 下 `unittest discover` **123/123**；其中 `test_durable_recovery.py` **14/14**（含确认/副作用/版本/状态拒绝及重复恢复 fencing），`test_durable_transaction_crashes.py` **18/18**（含 TaskItem 创建/取消、真实 v4→v5 DDL 回滚），`test_durable_store.py` **18/18**（含 SQLite Online Backup 往返及拒绝覆盖），配置清单服务与 CLI 测试均通过。`tests/test_s1.py`、`tests/test_contract_semantics.py`、`tests/test_voice_ws.py`、`tests/test_voice_config.py` 均通过；固定案例回放 **11/11**（输出到 `/tmp/loomrise-r1-validation-20261029.json`，事件输出到 `/tmp/events/`）。`prototypes/console-next` 前端 `npm test` **218/218**；`npm run test:sidebar` 桌面展开/收起、刷新持久、390px 手机抽屉、焦点与无横向溢出回归通过（6 张本地截图，`.playwright-cli` 浏览器记录）。配置相关与上下文测试的历史子集统计不代表当前全量回归。

<a id="ma-04-task-item-cancel-recovery"></a>

## M-A-04 TaskItem 撤销与恢复 — 通过

2026-10-29，SQLite schema v5 新增最小 `task_items` 持久表，记录事项 ID、租户/专家/主体/服务周期、目的、来源 AgentVersion、状态与 revision。尚未领取的 `waiting_condition/scheduled/ready` 事项可取消；取消状态与 revision 在同一事务中提交，重复取消不增加 revision。运行中或需先裁决执行停止的状态不能被直接标成已取消。恢复查询只返回待检查/排期/就绪事项，已取消事项不会复活。

| 验证 | 工件 | 结论 |
|---|---|---|
| 取消后重开数据库并执行恢复，状态仍为 `cancelled`、revision 保持 2，恢复查询为空 | `tests/test_task_items.py::test_cancelled_task_is_not_reactivated_or_recoverable_after_restart` | 通过 |
| 重复取消保持同一 revision | `tests/test_task_items.py::test_repeated_cancel_is_idempotent` | 通过 |
| v4 数据库升级后创建 TaskItem 表 | `tests/test_task_items.py::test_v4_database_migrates_task_items` | 通过 |
| 取消事务中硬退出回滚；重试后状态与 revision 一致且不进入恢复列表 | `tests/test_durable_transaction_crashes.py::test_task_item_cancel_crash_rolls_back_and_can_be_retried` | 通过 |

边界：这关闭的是 M-A-04 的已采用、未领取事项撤销恢复切片；不代表完整 TaskItem/TaskAttempt 合同、初始化去重、用途授权、人工确认的执行中取消、调度或主动触达已经实现。完整产品合同仍按 Task 设计后续评审和验收。

<a id="ma-03-crash-matrix"></a>

## M-A-03 SQLite 写事务崩溃矩阵 — 覆盖当前已识别写点

`tests/test_durable_transaction_crashes.py` **18/18 个测试方法**：覆盖运行创建各插入点、事件接纳记录与冲突诊断、事件批量追加、运行收尾各更新点、恢复写入、独立 `set_request_state`、outbox attempt/ack、稳定配置登记、草稿创建与 CAS 保存、候选冻结幂等重放、TaskItem 创建/取消、空库 schema 首建、旧列 ALTER、v3→v5 与 v4→v5 schema 迁移。各点均在子进程硬退出后重开，断言事务原子性、状态不前移、重试可行及不重复。与 `test_durable_outbox.py` **3/3**、`test_outbox_dispatch.py` **4/4** 合计另有 outbox 提交/消费者副作用后 ack 前重放证据。

完整性复核：`SqliteStore` 的每个事务写入口均已映射到故障测试：`migrate`、`begin_run`、`admit_event`（首次接纳与冲突诊断）、`append_events`、`commit_write`、`finish_run`、`set_request_state`、`recover`、TaskItem 创建/取消、outbox attempt/ack、稳定配置登记、草稿创建/保存、候选冻结；`backup_to` 是在线一致性快照，不修改源库。硬退出矩阵与遵守稳定 outbox ID 去重的模拟消费者证据可复现。剩余不覆盖：系统断电/介质损坏、多进程所有权及真实外部副作用 exactly-once；用户已确认 R1 Gate 通过并授权跳过责任角色签核。

<a id="ma-12-release-checklist"></a>

## M-A-12 发布前检查清单 — R1 前半可运行，完整 Gate 进行中

`ConfigurationService.release_checklist` 与 `loomrise config release checklist --agent-id … --candidate-id …` 对冻结候选运行十项预检。当前自动检查“候选已冻结”和“配置结构/规则有效”；来源登记、来源授权、知识摄入、固定样例准备/通过、沙盒选择、入口版本绑定和人工批准共八项明确为 `pending`，不会被客户端勾选伪装成通过。

结果提供逐项 `passed/failed/pending`、计数进度与 `ready`。当前 R1 只提供只读预检，`publish_enabled` 始终为 `false`；清单本身可运行不等于发布可用，也不替代 R2 的状态持久化、检查阻断、批准和沙盒入口绑定。

| 验证 | 工件 | 结果 |
|---|---|---|
| 十项清单结构及 2 通过/8 待验证；缺少后续服务证据时 `ready=false` 且发布关闭 | `tests/test_configuration_service.py::test_release_checklist_runs_and_keeps_unimplemented_evidence_pending` | 通过 |
| 越权外部 Agent 无法读取发布清单 | `tests/test_configuration_service.py::test_release_checklist_requires_authorized_candidate_scope` | 通过 |
| 配置 CLI 对冻结候选输出同一 JSON envelope 与 10 项进度，不启用发布 | `tests/test_config_cli.py::test_read_create_patch_validate_and_freeze_use_common_envelope` | 通过 |

样本为合成的 `expert-a` 配置候选，本机 Python 3.13.12、SQLite；未连接知识摄入、样例执行、沙盒、入口绑定或审批服务。M-A-12 完整通过仍需 R2 将每项检查接到权威状态并证明任一阻断项未通过时不能发布。

### 配置工作台清单呈现 — 已验本机浏览器，Gate 待签核

2026-10-29 使用本机 Python 3.13.12、SQLite fixture，页面 `127.0.0.1:8765`、配置服务 `127.0.0.1:8766`，合成专家 `course-demo`。真实浏览器从 R1 配置页冻结候选，随即读取同一 `release.checklist` 服务结果：候选状态 `frozen`，清单显示 2/10 通过、0 未通过、8 待验证；页面明确当前不能批准或发布。该序列未创建 stable 版本或发布入口，也未接入来源/摄入/样例/审批服务。前端单测另验证清单渲染与关闭发布状态。浏览器结果补强 WP9 页面证据，但 M-A-12 完整 Gate 仍由 R2 阻断发布测试关闭，R1 状态不因本次呈现而转为通过。

<a id="wp9-console-browser-acceptance"></a>

## WP9 配置工作台浏览器联调 — 本机 fixture 已验

2026-10-27 使用隔离的合成专家 `course-demo`、loopback 页面 `127.0.0.1:8768`、配置服务 `127.0.0.1:8766` 和同一 SQLite 目录 `/tmp/loomrise-r1-wp9-20261027` 完成浏览器交互。该验收证明当前原型真实调用服务，不是生产身份、多人或外部业务验收。

| 场景 | 验证结果 |
|---|---|
| CLI 注入非法字段类型，页面运行服务端校验 | CLI 与页面均返回 `$.units` / `invalid_units` / `units must be an array` |
| 同 revision 两入口编辑 | CLI 将草稿从 r2 更新到 r3；网页旧 r2 保存收到 HTTP 409。页面保留本地未保存输入，分别展示服务端 r3 与本地版本，并提供显式“载入服务端版本”；点击后读到 CLI 值 |
| 服务重启与刷新 | 停止 HTTP 进程，以相同 principal/SQLite 路径重启；CLI 与页面刷新均读到 r3 和相同 `persona.goal` |
| 校验与冻结 | CLI 修复 `$.units` 后页面在 r4 校验通过并冻结候选 `cp_fffa8d56f0ff11287850`；CLI 读取的 diff 为 `$.persona.goal`，候选状态 `frozen` |
| 稳定版本边界 | 候选 UI 显示“未批准”，明确冻结不是审批、stable 或发布；稳定列表只有 `r1-fixture-v1`，stable 未被候选冻结改写 |

原始件在本机忽略目录 `runs/R1/console/`：`wp9-acceptance-log.txt`、`wp9-revision-conflict-confirmed.png`、`wp9-candidate-history-confirmed.png`。SHA-256：`wp9-acceptance-log.txt`=`79b7c89efa971ed9e52bd32458a8a4703529c6cd2ecb2b26f5f412ff4d526077`；`wp9-revision-conflict-confirmed.png`=`140e12305b5b470beb5f5ccee1ace930cc4ce3446d7c7c23e4f0b5b6fea82196`；`wp9-candidate-history-confirmed.png`=`32f7834d37aad2f80a43a38a8db8389645c97a27b6f80921de3668b56eae51a7`。该浏览器序列和 MCP/CLI 同合同测试支持 M-A-17/18；用户确认 R1 Gate 通过并授权跳过责任角色签核，决定记录见本报告顶部。

### Origin allowlist 浏览器复验

2026-10-27 在新隔离 fixture 上复验跨端口浏览器读取。页面 `http://127.0.0.1:8768`，配置服务 `http://127.0.0.1:8766`，SQLite 目录 `/tmp/loomrise-r1-origin-recheck-20261027`；fixture 启动参数为 `tests/r1_configuration_http_fixture.py --port 8766 --data-dir /tmp/loomrise-r1-origin-recheck-20261027 --allowed-origin http://127.0.0.1:8768`。页面读取到草稿 r1；健康检查 GET 和 3 个配置 POST 均为 200，响应只回显 `Access-Control-Allow-Origin: http://127.0.0.1:8768`，浏览器 console error 为 0。本次仅读取，没有写入或冻结。

原始件在 `runs/R1/console/`：`wp9-origin-allowlist-recheck.txt`、`wp9-origin-allowlist-recheck.png`。截图 SHA-256：`4af475ae4ad1755709b95329ec694770719ff812b59803dd981647647620bc2e`。本复验只证明显式配置的本机预览源可访问；默认仍仅允许 `http://127.0.0.1:8765` 与 `http://localhost:8765`。

## 怎么跑

```bash
rtk proxy env PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_s1.py
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_contract_semantics.py
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_voice_ws.py
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_voice_config.py
rtk proxy env PYTHONPATH=. .venv/bin/python -m loomrise.cli replay --out runs/R1/event-idempotency-replay.json
```

回归不受影响：`tests/test_s1.py` 81 项、`test_contract_semantics.py` 47 项、`test_voice_ws.py` 33 项、`test_voice_config.py` 9 项、`cli replay` 11/11——**不传 `store` 时耐久层完全空转**，S1 行为零变化（`test_no_store_means_no_behavior_change`）。
