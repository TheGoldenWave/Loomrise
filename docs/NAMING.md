# Loomrise 命名决策 v0.3

状态：已确认，2026-09-27。本版新增「对象命名裁决」：与上游 AgentScope 同名对象的冲突按"谁更准确"裁决，不因为项目刚立项就沿用初建命名。

项目名采用 **Loomrise**，本地目录与公开仓库使用同一名称。

- `loom`：把资料、业务规则、渠道运行和反馈编织成可追踪的交付证据；
- `rise`：让每次运行成为下一次受控改进的基础。
- 对外副标题：`Build agents. Learn from every run.`

## 1. 对象命名裁决（S1）

裁决原则：**看语义，不看资历**。同名对象谁的名字更能让读者一眼判断"它是什么"，就用谁的；另一个加限定词并退到适配器内部。上游是库、Loomrise 是产品合同，但这不构成命名特权——两边都不准的，两边都改。

### 1.1 `Task`

| 对象 | 实际语义 | 判定 |
|---|---|---|
| 上游 `agentscope.state.Task` | 计划/待办条目：`subject`、`description`、`pending/in_progress/completed` | 名字**基本准确**：它就是"一件待办工作"。但在 Loomrise 代码里只出现在适配器内部，故内部别名为 `RuntimeTask`/`PlanTask`，不进入领域合同 |
| Loomrise 原 `Task` | 跨多轮、跨端、带副作用与结果证据、可含多次执行尝试的业务对象 | 名字**不准确**。它跨多轮、有状态机、有业务终态，语义上是"用户提出、需要被满足并结案的一项业务诉求"，而不是"一件工作单元" |

**裁决：Loomrise 改名为 `ServiceRequest`（业务请求），ID 为 `request_id`。**

理由：

1. `Task` 在业界几乎专指"执行单元"（Celery/Airflow/AgentScope 皆是）。Loomrise 的对象可以包含多次 `Run`、多轮对话、多次工具调用，把执行单元和业务请求混用一个词，会让"这轮跑了几次""这个请求完了没有"永远说不清。
2. `ServiceRequest` 是 CRM/ITIL 的既有词汇，目标用户（**AI 产品 / 产研**、解决方案、**策略运营**）无需学习；它天然带"提出—确认—履约—结案"的状态机，与 S1 的 `queued/running/waiting_confirm/cancelling/success/failed/cancelled` 对齐。
3. 改名后词表不再含糊：`ServiceRequest`（业务请求）／`Run`（执行尝试）／`RunEvent`（执行事实）／`EvalCase`（评测样本）／`Task`（执行单元，只在上游适配器内）。
4. 被否决的备选：`Case`（与评测样本撞名，且中文"案例"歧义）、`Ticket`/`WorkOrder`（偏人工工单，与 Agent 履约语义不符）、`Engagement`（行业黑话）。

配套影响：`TaskRouting` → `RequestRouting`（六层配置之一，语义不变）；`task_id` → `request_id`；AG-UI 的 `threadId` 承载 `request_id`，`runId` 承载 `run_id`。

### 1.2 `Skill`

| 对象 | 实际语义 | 判定 |
|---|---|---|
| 上游 `agentscope.skill.Skill` | 一个 Markdown 目录形态的能力包（`SKILL.md` + 资源） | 名字**错层**：它描述的是 Skill 的**载体/格式**，不是能力本身。准确名是 `MarkdownSkill` 或 `SkillDirectory` |
| Loomrise `SkillManifest` | 能力的**声明/合同**：适用条件、目标、退出、依赖、失败策略、来源证据 | 名字**准确**。与 `ToolManifest` 同构，明确表达"这是合同，不是权限，也不是可执行代码" |

**裁决：维持现有结论，两边都不用裸 `Skill` 作为权威名。** Loomrise 权威对象是 `SkillManifest`（UI 可简称 Skill）；上游 Markdown 目录对象在适配器内部称 `MarkdownSkill`/`SkillDirectory`。

理由：上游那个类一旦叫 `Skill`，"加载一个 Skill"就说不清是加载目录还是加载合同；而 Loomrise 侧必须强调它是**策略配置**，不是权限入口、不是任意代码执行入口，候选版本必须先评测后审批。

### 1.3 `app/`（AgentScope 服务层）

**裁决：明确不采用。** `src/agentscope/app/` 把 FastAPI 服务、路由、会话/用户/模型管理和飞书/钉钉/Discord channel 绑成一个控制面，并自带 `ag-ui-protocol` 中间件。这与 Loomrise「单一工作台 + 可替换适配器」冲突三条：

1. 引入 IM 渠道 → S1 不做 IM，S4 才做且需独立授权；
2. 引入第二套会话/用户状态 → 与 `ServiceRequest`/`RunEvent` 权威冲突；
3. 自带 `AGUIProtocolMiddleware` 源码自述"per-instance state，不支持并发流"，且绑定上游私有事件模型。

**但"不采用实现"不等于"不参考映射"**：AG-UI 事件映射可参照上游 `app/middleware/_protocol/_agui.py` 的 1:1 对照关系，实现放在 Loomrise 自己的投影层（`loomrise/adapters/projection.py`），投影输入是 `RunEvent`，不是上游事件。

## 2. 命名边界速查

| Loomrise 权威名 | 上游对应物 | 上游在 Loomrise 内的称呼 | 是否进入领域合同 |
|---|---|---|---|
| `ServiceRequest` | `agentscope.state.Task` | `RuntimeTask` / `PlanTask` | 否，仅适配器内部 |
| `Run` / `RunEvent` | reply / AgentEvent | 供应商事件（投影来源） | 否，仅投影输入 |
| `SkillManifest` | `agentscope.skill.Skill` | `MarkdownSkill` / `SkillDirectory` | 否，仅适配器内部 |
| `ToolManifest` / 硬规则 | `agentscope.permission.*` | 供应商权限规则 | 否，裁决权在 Loomrise |
| `ToolOutcome`（含自建 `unknown`） | `ToolResultState` | 供应商结果态 | 否，未知态由 Loomrise 补 |
| `PlaybackState`（含自建 `confirmed`） | `BotStoppedSpeakingFrame` | 服务端口径播放边界 | 否，设备级回执由 Loomrise 补 |

尚待确认：

- Python／TypeScript 包名；
- 域名与组织名；
- 商标和同名项目尽调。

在完成上述尽调前，不宣称名称已经可注册。完整候选比较和个人命名语境保留在本地私有工作区，不属于公开项目事实。
