# R1 证据摘要 v0.8（进行中）

> 2026-10-27 更新 R1 配置后端、耐久故障、主体持久化边界与 WP9 浏览器联调证据。**规则同 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) §0**：原始件留本地 `runs/R1/`，本文件只记结论、样本量与环境；矩阵"证据位置"列指向本文锚点。
>
> **本文件在 R1 未完成时就已经存在，这是故意的**——先把已验证部分与未验证部分分开写清，比事后一次性补写更不容易把"想做的"写成"做过的"。
>
> R1 进度：**WP1 已落；WP2/WP5/WP7 部分；WP3/WP4/WP6/WP8 后端实现与单测已落；WP9 配置页面已接入 loopback HTTP 并完成本机 fixture 浏览器联调。** M-A-03 当前已识别 SQLite 写点均有硬退出证据，M-A-03/17/18 均待 Gate 签核；M-A-04 与 R1 父 Gate 未通过。

## 环境

| 项 | 值 |
|---|---|
| 机器 / 系统 | Apple M4 / macOS 15.6.1 |
| Python | 3.13.12（仓库根 `.venv`） |
| 存储 | 标准库 `sqlite3`（**零新依赖**），WAL + `synchronous=FULL` + 进程内单写者锁 |
| 测试 | `unittest`，全部本地、不触网、不调模型 |

## WP1 持久化底座 — 已落

`loomrise/durable_store.py`：请求/运行/事件/幂等/outbox、事件接纳回执与冲突诊断、配置草稿/稳定快照/候选等表由 schema v4 管理；请求含可选 `trigger_event_id`。空库和既有请求迁移可重复执行。v4 只落 mapped `subject_id`，并在旧库迁移时清理 ephemeral、空 scope 或未知 scope 的主体 ID。

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 不是"仅事件文件落盘"（`M-A-16`） | `test_migration_from_empty` 断言五张表都在、路径是 `.db` | 通过 |
| 提交点原子：请求/运行/事件要么一起可见要么都不可见（`M-A-19`） | `test_partial_commit_is_rolled_back` 在 COMMIT 前注入异常，断言三张表都为空 | 通过 |
| 事件哈希链可验证（`M-A-19`） | `test_event_hash_chain_verifies`、`test_tampered_event_fails_verification`（改 `event_json` 后校验必须失败） | 通过 |
| 落库链按**运行**封链 | `test_store_owns_the_persisted_chain`：故意传错 `prev_hash`，存储层重封 | 通过 |

**一个实现决定（不是文档承诺）**：内存账本的哈希链是"进程内一条链"，落库链是"每个 run 一条链"。进程重启后账本从 GENESIS 重开，若照抄账本的 `prev_hash`，库里的链必然断。**链尾归存储层持有**，`_append` 用同一 run 的上一条事件重封。

**局限**：`test_durable_transaction_crashes.py` 以子进程 `os._exit` 覆盖当前已识别的 SQLite 写事务点，包括运行/事件/outbox、配置快照/草稿/revision/候选、事件冲突诊断、schema 首建和 v2/v3 迁移；`test_durable_outbox.py` 另覆盖 `commit_write` 提交前/后退出。系统信号/断电、介质故障、多进程 worker 所有权和真实外部副作用 exactly-once 仍未测；M-A-03 等待矩阵签核。

## WP2 恢复与故障 — 部分

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 本地 `running` 旧尝试记失败、保留中断事实（`M-A-02` 的裁决部分，Task §7.1） | `test_local_running_is_interrupted_not_resumed`：owner 从 p1 换 p2 打开同一库 → `status=failed`、`finish_reason=restart_interrupted`、末尾事件 `run.interrupted`、链仍可验 | 通过 |
| 恢复可重复执行，不重复判中断 | `test_recover_is_idempotent` | 通过 |
| 旧代迟到写入被拒（`M-A-21` 的 R1 部分） | `test_old_run_rejects_late_write`：恢复后 `commit_write` 抛 `RuntimeError` | 通过 |
| 新尝试是新 Run，有自己的链并指向旧运行（lineage） | `test_new_attempt_keeps_lineage_and_own_chain`：`run_id` 不同、`lineage_parent` 指向旧 run、`occupancy_generation=2`、新链从 seq 0 开始 | 通过 |
| 同进程内运行被"接管"而非判中断 | `test_adopted_run_keeps_running` | 通过 |

**未做（不冒充）**：
1. `waiting_confirm` 在恢复后仍持久、可枚举，旧 Run 会失败并留中断事实；不自动唤醒、不沿旧 Run 续执行。实际 suspend/wake 与确认上下文重验属 R2 `M-A-20`。
2. 取消状态测试证明 `ServiceRequest` 不进入可恢复列表；没有 `TaskItem`/`TaskAttempt` 合同，不能据此关闭 M-A-04 的事项撤销恢复 Gate。
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
- `AgentVersion.task_blueprints` 字段已加入。Task blueprint 的主体/用途对象形状尚未定版；`ContextFragment` 现支持可选 `subject_id/subject_scope`，主体或作用域不匹配会 fail-closed 并记录跳过原因。`ServiceRequest.persistent_subject` 确保只有 mapped 主体落库，ephemeral/未知 scope 不写主体 ID；v4 迁移同步清理旧版非 mapped/未知 scope 值。用途隔离与 TaskItem 撤销恢复仍没有已定持久合同，WP5 仍部分。

新增 `tests/test_config_cross_entry.py`：以同一 SQLite 文件分别打开 HTTP app、CLI 入口和 MCP tool adapter，验证跨入口读写相同 revision/config；包括数组索引与带点字段名的 JSON path patch、字段 diff 往返、相同字段路径校验错误、非法草稿冻结被拒、过期 revision CAS 冲突，以及关闭并重建 HTTP app 后草稿/稳定快照保持不变。该测试使用 MCP 内存 client session，不是 stdio 进程验收。

HTTP 错误 envelope 与 CLI/MCP 共用；HTTP 状态码按错误类别区分：`invalid_request=400`、`forbidden=403`、`not_found=404`、`revision_conflict=409`、`validation_failed=422`。

2026-10-27 最新验证：`unittest discover` **108/108**，全量测试在 `ResourceWarning` 视为错误及分配追踪下通过；前端 `npm test` **218/218**，`npm run test:sidebar` 桌面/手机浏览器回归通过；`tests/test_s1.py`、`tests/test_contract_semantics.py`、`tests/test_voice_ws.py`、`tests/test_voice_config.py`、固定案例回放 **11/11** 与 `compileall` 均通过。配置相关测试 **35/35**、主体/有效期上下文测试 **6/6** 是较早的子集统计；最新全量结果包含字段路径与 JSON 边界回归、Origin allowlist、mapped-only 主体持久化/迁移，以及配置写事务、schema DDL 与事件冲突诊断硬退出回滚测试。本轮仍未关闭 M-A-04、M-A-03 签核、M-A-17/18 签核及 R1 父 Gate。

<a id="ma-03-crash-matrix"></a>

## M-A-03 SQLite 写事务崩溃矩阵 — 覆盖当前已识别写点，Gate 待签核

`tests/test_durable_transaction_crashes.py` **15/15 个测试方法**：覆盖运行创建各插入点、事件接纳记录与冲突诊断、事件批量追加、运行收尾各更新点、恢复写入、独立 `set_request_state`、outbox attempt/ack、稳定配置登记、草稿创建与 CAS 保存、候选冻结幂等重放、空库 schema 首建、旧列 ALTER、v3→v4 主体清理与 schema 版本更新。各点均在子进程硬退出后重开，断言事务原子性、状态不前移、重试可行及不重复。与 `test_durable_outbox.py` **3/3**、`test_outbox_dispatch.py` **4/4** 合计另有 outbox 提交/消费者副作用后 ack 前重放证据。

当前已识别的 `SqliteStore` 写路径已逐类覆盖；这不证明系统断电/存储故障、多进程所有权或真实外部副作用 exactly-once。上述边界和 outbox 消费者去重前提留给对应 Gate；M-A-03 状态仍为“在跑”，等待 Gate 矩阵签核。TaskItem 义务没有定版持久合同，本测试的取消恢复结论仅适用于现有 `ServiceRequest` 状态。

<a id="wp9-console-browser-acceptance"></a>

## WP9 配置工作台浏览器联调 — 本机 fixture 已验，Gate 待签核

2026-10-27 使用隔离的合成专家 `course-demo`、loopback 页面 `127.0.0.1:8768`、配置服务 `127.0.0.1:8766` 和同一 SQLite 目录 `/tmp/loomrise-r1-wp9-20261027` 完成浏览器交互。该验收证明当前原型真实调用服务，不是生产身份、多人或外部业务验收。

| 场景 | 验证结果 |
|---|---|
| CLI 注入非法字段类型，页面运行服务端校验 | CLI 与页面均返回 `$.units` / `invalid_units` / `units must be an array` |
| 同 revision 两入口编辑 | CLI 将草稿从 r2 更新到 r3；网页旧 r2 保存收到 HTTP 409。页面保留本地未保存输入，分别展示服务端 r3 与本地版本，并提供显式“载入服务端版本”；点击后读到 CLI 值 |
| 服务重启与刷新 | 停止 HTTP 进程，以相同 principal/SQLite 路径重启；CLI 与页面刷新均读到 r3 和相同 `persona.goal` |
| 校验与冻结 | CLI 修复 `$.units` 后页面在 r4 校验通过并冻结候选 `cp_fffa8d56f0ff11287850`；CLI 读取的 diff 为 `$.persona.goal`，候选状态 `frozen` |
| 稳定版本边界 | 候选 UI 显示“未批准”，明确冻结不是审批、stable 或发布；稳定列表只有 `r1-fixture-v1`，stable 未被候选冻结改写 |

原始件在本机忽略目录 `runs/R1/console/`：`wp9-acceptance-log.txt`、`wp9-revision-conflict-confirmed.png`、`wp9-candidate-history-confirmed.png`。SHA-256：`wp9-acceptance-log.txt`=`79b7c89efa971ed9e52bd32458a8a4703529c6cd2ecb2b26f5f412ff4d526077`；`wp9-revision-conflict-confirmed.png`=`140e12305b5b470beb5f5ccee1ace930cc4ce3446d7c7c23e4f0b5b6fea82196`；`wp9-candidate-history-confirmed.png`=`32f7834d37aad2f80a43a38a8db8389645c97a27b6f80921de3668b56eae51a7`。该证据支持 M-A-17/18 进入签核评估，不替代矩阵签核，也不关闭 M-A-04 或 R1 父 Gate。

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
