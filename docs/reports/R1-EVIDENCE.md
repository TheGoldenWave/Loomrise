# R1 证据摘要 v0.2（进行中）

> 2026-10-26 更新事件接纳证据，其余记录为 2026-10-23。**规则同 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) §0**：原始件留本地 `runs/R1/`，本文件只记结论、样本量与环境；矩阵"证据位置"列指向本文锚点。
>
> **本文件在 R1 未完成时就已经存在，这是故意的**——先把已验证部分与未验证部分分开写清，比事后一次性补写更不容易把"想做的"写成"做过的"。
>
> R1 进度：**WP1 持久化底座 · WP2 恢复与故障 · WP7 幂等键语义** 已落代码并自检；WP3–WP6、WP8 未开始。

## 环境

| 项 | 值 |
|---|---|
| 机器 / 系统 | Apple M4 / macOS 15.6.1 |
| Python | 3.13.12（仓库根 `.venv`） |
| 存储 | 标准库 `sqlite3`（**零新依赖**），WAL + `synchronous=FULL` + 进程内单写者锁 |
| 测试 | `unittest`，全部本地、不触网、不调模型 |

## WP1 持久化底座 — 已落

`loomrise/durable_store.py`：原五张表（`requests` / `runs` / `events` / `idempotency` / `outbox`）+ `meta` 版本号；2026-10-26 schema v2 增加 `event_receipts`、`event_admission_conflicts` 与请求的可选 `trigger_event_id` 列，迁移可重复执行。

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 不是"仅事件文件落盘"（`M-A-16`） | `test_migration_from_empty` 断言五张表都在、路径是 `.db` | 通过 |
| 提交点原子：请求/运行/事件要么一起可见要么都不可见（`M-A-19`） | `test_partial_commit_is_rolled_back` 在 COMMIT 前注入异常，断言三张表都为空 | 通过 |
| 事件哈希链可验证（`M-A-19`） | `test_event_hash_chain_verifies`、`test_tampered_event_fails_verification`（改 `event_json` 后校验必须失败） | 通过 |
| 落库链按**运行**封链 | `test_store_owns_the_persisted_chain`：故意传错 `prev_hash`，存储层重封 | 通过 |

**一个实现决定（不是文档承诺）**：内存账本的哈希链是"进程内一条链"，落库链是"每个 run 一条链"。进程重启后账本从 GENESIS 重开，若照抄账本的 `prev_hash`，库里的链必然断。**链尾归存储层持有**，`_append` 用同一 run 的上一条事件重封。

**局限**：没有做进程级 `kill -9` 注入，崩溃是用"提交前抛异常 + 不调 `finish`"模拟的。真实信号中断下的 WAL 行为未测。

## WP2 恢复与故障 — 部分

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 本地 `running` 旧尝试记失败、保留中断事实（`M-A-02` 的裁决部分，Task §7.1） | `test_local_running_is_interrupted_not_resumed`：owner 从 p1 换 p2 打开同一库 → `status=failed`、`finish_reason=restart_interrupted`、末尾事件 `run.interrupted`、链仍可验 | 通过 |
| 恢复可重复执行，不重复判中断 | `test_recover_is_idempotent` | 通过 |
| 旧代迟到写入被拒（`M-A-21` 的 R1 部分） | `test_old_run_rejects_late_write`：恢复后 `commit_write` 抛 `RuntimeError` | 通过 |
| 新尝试是新 Run，有自己的链并指向旧运行（lineage） | `test_new_attempt_keeps_lineage_and_own_chain`：`run_id` 不同、`lineage_parent` 指向旧 run、`occupancy_generation=2`、新链从 seq 0 开始 | 通过 |
| 同进程内运行被"接管"而非判中断 | `test_adopted_run_keeps_running` | 通过 |

**未做（不冒充）**：
1. **"未完成请求可续"没做**。现在只做"判中断 + 留证"，没有把等待态沿原关联唤醒——那是 R2 的 `M-A-20`。
2. **没有真实进程重启**。测试是同进程换 `owner_id` 打开同一库，语义等价于"另一个执行者接管"，但不等于操作系统的进程重启（含 WAL 恢复、文件锁释放）。
3. **多进程/多 worker 不安全**，这是 R5a 的 Gate，本层只承诺单写者。

## WP7 幂等键语义 — 部分

`action_key(action, key) = f"{action}::{key}"`，**键绑定具体业务操作**而不是绑请求（`M-A-06`）。

| 承诺 | 怎么验的 | 结论 |
|---|---|---|
| 同一 `(action, key)` 只产生一次写入，第二次返回原 `result_id` | `test_same_action_key_writes_once` | 通过 |
| 同一个键用在两个动作上是两件事 | `test_same_bare_key_on_different_action_is_distinct` | 通过 |
| 幂等记录与 outbox 意图同事务 | `test_write_emits_outbox_intent` | 通过 |
| 跨重启幂等索引恢复，内存索引按裸键 | `test_idempotent_index_survives_restart`：服务重启后 `_writes["idem-c2"]` 命中，重跑同一案例 `write_count=0` | 通过 |

**局限**：业务动作并发重复（`M-A-05`）与未知结果对账（`M-A-07`）属 R2，未做；上述业务写入测试只证明"串行 + 跨重启"不重复。下面的入站事件接纳并发证据不替代这些业务副作用 Gate。

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

边界：本轮只验证同库事件接纳与提交后子进程退出；没有提交中 SIGKILL、断电、多主机、并发 Worker 所有权或供应商 Webhook 实测。事件源的 ID 稳定性、认证及保留期仍由后续入口接入验收；不因本子集通过宣称 R1 整体完成。下一步仍按原 R1 工作包补配置持久化与实际入口集成；R2 处理业务动作并发与未知对账。

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
