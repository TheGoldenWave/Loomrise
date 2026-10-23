# R1 证据摘要 v0.1（进行中）

> 2026-10-23。**规则同 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) §0**：原始件留本地 `runs/R1/`，本文件只记结论、样本量与环境；矩阵"证据位置"列指向本文锚点。
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

`loomrise/durable_store.py`：五张表（`requests` / `runs` / `events` / `idempotency` / `outbox`）+ `meta` 版本号，迁移可重复执行。

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

**局限**：并发重复（`M-A-05`）与未知结果对账（`M-A-07`）属 R2，未做；这里只证明"串行 + 跨重启"不重复。

## 怎么跑

```bash
cd /Users/goldenwave/Documents/MyProject/Loomrise
PYTHONPATH=. .venv/bin/python tests/test_durable_store.py      # 15 项
PYTHONPATH=. .venv/bin/python tests/test_durable_recovery.py   # 6 项
```

回归不受影响：`tests/test_s1.py` 81 项、`test_contract_semantics.py` 47 项、`test_voice_ws.py` 33 项、`test_voice_config.py` 9 项、`cli replay` 11/11——**不传 `store` 时耐久层完全空转**，S1 行为零变化（`test_no_store_means_no_behavior_change`）。
