# 持久可恢复执行设计评审 v0.1

日期：2026-10-29。状态：**评审意见**（记录现状对照、判定与建议），不是产品/架构决策，不是实现证据，**不新增 Gate、不改阶段范围**。逐条建议的落点只引用既有父 Gate 与 R2 工作包；是否采纳由产品与架构负责人裁决。

参照文章：刘军《Durable Agent 详解：如何让 Agent 在云端长期稳定运行》（阿里云云原生，2026-10-29，[原文](https://mp.weixin.qq.com/s/z8JHkCyOVVKrXpKH-vy6tw)）。该文以 AgentScope `HarnessAgent` 与阿里云 AgentCore 为样本，提出 Durable 的四项能力（输入不消失、已确认工作可复用、未完成工作有明确去向、执行过程可重新观察），以及三条实现要点：恢复边界是已提交的**逻辑边界**、一次 Commit 原子提交记录/文档/任务阶段、外部副作用必须先记意图并按重放策略决定是否重做。

评审对象：[架构](../ARCHITECTURE.md) §执行耐久层与恢复适配边界、[Task 设计](../TASK-SYSTEM-DESIGN.md) §7/§7.1/§7.2、[DurableRunAdapter 实施计划](../superpowers/plans/2026-10-23-durable-run-adapter.md)、[R1 证据摘要](R1-EVIDENCE.md)、代码 `loomrise/durable_store.py`、`durable_adapter.py`、`outbox.py`、`service.py`、`adapters/agentscope_runtime.py`。

## 0. 结论

1. **有设计、有规划、有部分实现**。耐久层不是空白，而是已经落到 `Run`/`RunEvent`/幂等/outbox/哈希链/中断裁决这一层，并有故障注入证据（`R1-EVIDENCE` WP1/WP2/WP7）。
2. **方向正确**，正确在文章最容易做错的三处：业务权威与执行证据分离、拒绝把 durable 当 exactly-once、不假装跨进程安全。
3. **主要短板是一个定位问题**：当前持久化的是**运行记录**，还不是**任务进度**。四项能力中第 ① 项达标、第 ④ 项部分，**第 ②③ 项只做了一半**——没有"意图先于执行"，没有驱动 resume 的调度者，也没有阶段级重入语义。
4. 差距集中在 R2 之前就会变成真实风险的三项（DC-01/02/03），建议在 R2 开工前并入既有 Gate 证据要求，**不需要新增 Gate，也不需要引入 `pi-durable` 依赖**。

## 1. 四项能力对照

| 文章能力 | 现状 | 判定 | 证据 |
|---|---|---|---|
| ① 输入不因进程退出而消失 | 稳定 `request_id` + `event_receipts` 四元唯一键 + `payload_hash` 区分 `duplicate`/`conflict` + 冲突诊断表 | **达标，强于文章示例**（文章只讲 requestId 关联，未区分同 ID 不同载荷） | `durable_store.py:296-335`；`tests/test_event_run_idempotency.py` |
| ② 已确认工作可复用 | 仅业务写入的 `result_id` 可跨渠道/重启复用（`action::key`）；模型响应、检索结果、上下文快照零复用 | **部分** | `durable_adapter.py:29-35`、`durable_store.py:410-455`；`R1-EVIDENCE` WP7 |
| ③ 未完成工作有明确去向 | 旧本地 `running` 一律 `failed/restart_interrupted` + lineage + 三层次裁决表（尝试/事项/副作用） | **部分**：裁决表比文章更严谨，但 `recoverable_requests`/`recoverable_task_items` 只被测试调用，无 resume 驱动者 | `durable_store.py:493-550,583,662`；`TASK-SYSTEM-DESIGN` §7.1 |
| ④ 执行过程可重新观察 | 每 run 一条哈希链 + `verify_chain` + outbox 至少一次投递 | **部分**：观测面向审计成立，面向"断线重连看进度"的业务只读视图未建 | `durable_store.py:381-401`、`outbox.py:19-35` |

## 2. 方向裁定：四条判断是对的

- **D1 权威分离正确。** `ARCHITECTURE:148` 明确 checkpoint/phase 只是执行证据，业务终态归 `RunEvent` + `Outcome`。这正对应文章 §04 把"平台执行事实"与"Harness 原生状态"分成两层，Loomrise 还多写了一条文章没有明说的边界：Adapter 提交成功 ≠ 请求成功 ≠ 外部写入完成。
- **D2 拒绝 exactly-once 幻觉正确。** `ARCHITECTURE:160` 与 `TASK-SYSTEM-DESIGN` §7 第 5 条要求无幂等键/结果 ID/对账证据即禁止重放写。文章用整节论证"框架不会自动让发邮件变幂等"，这里已经变成硬规则。
- **D3 不假装跨进程安全正确。** `ARCHITECTURE:166` 具体指出 `pi durable` 的 storage 单进程拥有、WAL + `synchronous=NORMAL` 是取舍、JSONL 会全量驻留内存，并把多进程/备份/迁移推到 R5a。比"接上就有耐久"的说法诚实得多。
- **D4 分层落位（R1→R2→R3/R4→R5a）正确。** 把「事务提交 → 挂起/对账 → Worker 接管 → 云端」拆开验收，避免了"引入 Adapter 就顺带获得云端恢复"这类越级声明。

因此本评审的立场是**补强，不是改方向**。下列建议全部限定在既有分层内。

## 3. 差距清单

优先级定义：P0 = R2 开工前必须补，否则风险会落在真实副作用上；P1 = R2 期间需明确表述；P2 = 记录在案、可后置。

### DC-01 · 缺"意图先于执行"的持久记录（P0）

**现状**：`service.py:313-328` 的 `_book` 先 `await sandbox.create_booking(...)`，返回后才 `emit("tool.outcome", ...)`；`durable_adapter.py:120-139` 只有带 `result_id` 的 `tool.outcome` 才走 `commit_write`。因此"外部已写、事件未提交"这段窗口在库里**没有任何记录**——恢复侧只能说"这个 run 中断了"，无法判断某次调用是否发生过。

**文章做法**：工具 Task 分 `call`/`execute` 两阶段，`call` 阶段先原子提交「最终参数 + 重放策略 + 执行意图」，提交成功才执行；恢复进 `execute` 阶段时按策略决定重放还是标记 `interrupted`（§03「普通工具」）。

**风险**：`M-A-07`（工具已受理但超时 / 迟到回执 / 未知状态可区分并进入对账）当前没有实现落点。R2 一旦接真实沙盒工具，这个窗口就是重复写入路径；`recover()` 也不会把它送进对账，只是判失败。

**建议**：新增持久 `tool_attempt`（或等价事件）记录，状态 `intent → executed → unknown`，`intent` 与幂等键同键、与 outbox 同事务；恢复时"有 intent 无 outcome"直接判 `UNKNOWN`/`reconciling` 并禁止自动重试。属于执行层内部状态，不改 `ServiceRequest`/`RunEvent`/`Outcome` 合同。

**落点**：`M-A-07`（父 Gate），R2-WP5。

### DC-02 · `recoverable_*` 有查询无驱动（P0）

**现状**：`durable_store.py:583`、`662`、`676` 三个恢复查询只被测试调用；仓库内无 `resume()`、无 sleeping/until、无 wake 契约。`service.py:119-123` 的启动恢复只做两件事：判中断、回填幂等索引。

**文章做法**：`resume()` 启动调度器，宿主通过 `onWake` 接收"现在有工作可运行"和"下次何时继续"；恢复时按 pending/running/waiting/sleeping/completing/terminal 分别进入（§03 末段）。

**风险**：`M-A-02`「重启后未完成请求可续」实际只做到"记录可查"，续不续取决于人工；`M-A-20` 的"确认唤醒"目前**没有落点**——等待态在库里，但没有代码会把它接回去。

**建议**：R2 落一个最小 resume 契约即可：启动扫描 `recoverable_requests` + `recoverable_task_items` → 按 §7.1 表产出待办（显式"不自动重跑"）→ 由应用层触发。把"谁触发继续"写进 Gate 证据要求，而不是默认调度器存在。

**落点**：`M-A-02`（父）、`M-A-20`（细化），R2-WP5。

### DC-03 · 人工确认事实不持久（P0）

**现状**：`adapters/agentscope_runtime.py:224-232` 的 `ConfirmLedger` 是内存 `set`，每个 Run 新建；`service.py:369-383` 只把 `request.state` 写成 `waiting_confirm`，**没有持久化"在等什么"**——哪些调用、什么参数、哪个 `AgentVersion`、谁在什么渠道确认。

**文章做法**：`waiting` 状态必须保存"依赖对象 + 汇合策略"；恢复后按原等待条件继续，不重复询问。

**风险**：`M-A-20` 要求"重启后重验确认上下文""不重复询问或写入"，当前无法证明——重启后既不能复用确认，也无法证明曾经确认过。这是合规面的问题，不只是技术债。

**建议**：持久化 `confirm_request`（调用摘要、参数哈希、`AgentVersion`、确认人/渠道/时间、确认结果），与 tool intent 同事务提交；恢复时重验后复用或重新征询，二者都要留证。

**落点**：`M-A-20`，R2-WP5。

### DC-04 · 恢复边界停在 Run 级，未到阶段级（P1）

**现状**：`request.routed`、上下文装配、`reply.text`、`tool.outcome` 都是事件，但没有"这里可重入"的语义；恢复 = 新建 `Run` 整轮重跑（`durable_adapter.py:60-105` + `service.py:226-241`），只有写入幂等挡住重复副作用。

**文章做法**：恢复从已保存阶段的入口重新执行，不跳回崩溃前某一行；一个阶段含多个不可重复动作时应继续拆分阶段。

**建议**：**不引入 task graph**（见 §4），但补一张「run phase → 重入语义」表（可复用 / 可重算 / 必须对账 / 禁止重放），并把 phase 持久化。这张表是 DC-01 与 DC-05 的共同前提。

**落点**：`M-A-19` 证据细化（不新增 Gate）。

### DC-05 · 模型调用与检索的复用策略是空的（P1）

**现状**：`ARCHITECTURE:147` 要求"必须登记结果复用、重新调用、时效重验及预算策略"，但没有字段或表承接；`Run.snapshot` 只有 `skill_routing` 与 `context_budget`（`service.py:229-236`）。R2 接真模型后，一次崩溃 = 整轮 token 重付。

**文章做法**：模型生成任务自身有 prepare/request/retry/poll/tools 阶段，重试次数、退避、下一阶段都进任务状态；已保存的部分文本只作中断记录，不驱动工具执行。

**建议**：最小可用形态即可——在 `Run.snapshot` 里给每类步骤登记 `replay_policy`（`pure` / `replayable` / `verify_required` / `no_replay`），先覆盖「模型生成」与「只读检索」两类，并顺带补齐成本账本的归因口径。

**落点**：R2-WP5；成本口径对应 `RunEvent` 已有字段。

### DC-06 · 上下文重建未对接（P1）

**现状**：`service.py:107-108,365-367` 的 `_states` 是内存态，重启后新一轮从零装配上下文，跨轮前文丢失。

**文章做法**：从持久记录重建上下文（消息、模型响应、工具结果），再应用已保存的压缩调整。

**建议**：先明确一个判断——`resume` 是否需要"接着推理"，还是只要求"业务不重复"。若需要前者，走既有 `ContextCompactionService` 账本重建，不新增第二套上下文事实源；与 S1 关闭原生自动压缩不冲突。

**落点**：`M-A-02`；涉及 §上下文账本表述时同步 ARCHITECTURE。

### DC-07 · `before_commit` 是生产路径上的测试后门（P2）

`durable_store.py:201,243` 以实例属性注入故障钩子，任何调用方都能设置。建议改为显式测试子类或构造参数，避免 R5a 前被误用为"提交后钩子"。

### DC-08 · 多步业务任务的归属需一句裁决（P2）

文章的自定义任务示例把五封邮件做成父子任务树。Loomrise 的对应物是 `TaskItem`（业务义务），Adapter 不应再建嵌套 task。建议在 `TASK-SYSTEM-DESIGN` §7.2 补一句明确取舍：**批量/多步业务由 TaskItem 子项承载，Adapter 不建嵌套 task graph**。否则 R3/R4 容易两条路都建。

## 4. 不建议照搬的部分

| 不照搬 | 理由 |
|---|---|
| 嵌套 task graph / 父子任务树进公共合同 | Loomrise 已有 `TaskItem` 承载业务义务；两套任务模型会形成第二状态权威（`ARCHITECTURE:131` 已禁止） |
| 通用 replay 机制 | 外部写入/消息发送禁止通 replay 重发（`ARCHITECTURE:147`）；只允许在明确策略下重放 |
| `pi-durable` 作为运行依赖 | 其 storage 语义与许可证状态未复核，且已明确只作机制参照（`ROADMAP:25`） |
| exactly-once 语义承诺 | 无幂等键/结果 ID/对账能力时做不到；文章本身也不承诺 |
| AgentCore 的 Session Store / Environment 抽象 | 现阶段等价物是 SQLite + 发行物清单；R5a 验完云端恢复前不引入平台层抽象 |

## 5. 文档状态不一致（本次一并校正）

三处仍写"Adapter 未实现"，与代码和 `ARCHITECTURE:172` 的"部分实现（2026-10-29）"矛盾。本次按 `ARCHITECTURE:172` 与 `R1-EVIDENCE` WP1 为准**只改状态表述，不改范围、Gate 或结论**：

| 位置 | 原文 | 校正为 |
|---|---|---|
| `ARCHITECTURE:3` | 未引入依赖或实现 Adapter | 已落最小 `DurableRunAdapter` + SQLite 存储（无新依赖）；R2 的挂起/唤醒与未知对账未实现 |
| `ARCHITECTURE:129` 节标题 | 方向已确认，规划未实现 | 方向已确认，部分实现 |
| `ROADMAP:37` | Adapter 未实现 | 部分实现（R1 最小切片） |

## 6. 建议的 R2 调整（不新增 Gate）

| R2-WP5 增项 | 对应父 Gate | 说明 |
|---|---|---|
| DC-01 工具意图持久化 + 无结果即对账 | `M-A-07` | 恢复路径从"判失败"改为"判未知→对账" |
| DC-03 确认请求持久化 | `M-A-20` | 使"不重复询问"可被证明 |
| DC-02 最小 resume 契约 | `M-A-02`、`M-A-20` | 只要求"可被触发"，不要求自动调度器 |
| DC-05 replay policy 字段 | 无（成本与复用登记） | 支撑 R2 的未知对账与逐条成本 |

三项均已属于 R2 现有"运行时可信"范围的实现细节，**不构成新 Gate、不改变 R2 退出判据**；`M-A-19…21` 仍只作父 Gate 证据细化。

## 7. 未决问题

1. phase 持久化落在 `Run` 字段还是独立事件流（影响 `RunEvent` 合同的稳定性）。
2. 上下文重建是否纳入 R2，还是留到 S2-b。
3. 跨渠道确认的身份合同：语音确认与文字确认能否互相复用（涉及身份而非执行层）。

## 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v0.1 | 2026-10-29 | 首次评审：四项能力对照、四条方向裁定、DC-01–08、三处文档状态校正、R2 增项建议 |
