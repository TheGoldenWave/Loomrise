# 用户记忆模块基石：TencentDB Agent Memory 接入设计 v0.1

状态：**提案，待确认**。2026-10-09。本文给出把 [TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)（下称 **TDAI**）作为 Loomrise「用户记忆」模块基石的选型结论、边界裁决、分期路径与验收判据。**不代表已实现，也未运行任何 TDAI 服务或做过端到端联调。** 已确认的产品边界仍以[产品定义](PRODUCT.md)和[六层配置合同](CONFIGURATION-LAYERS.md)为准；阶段与 Gate 见[验证路线](ROADMAP.md)。

## 0. 本文要解决的问题

Loomrise 至今没有用户记忆能力。现状是 S1 明确划出的空白：

- [ARCHITECTURE.md](ARCHITECTURE.md) §S1 配置与执行边界：「**S1 不实现自动摘要、长期记忆优化或基于评测结果的动态调参**」。
- [CONFIGURATION-LAYERS.md](CONFIGURATION-LAYERS.md) §6：`ContextSnapshot`「只读虚构资料、用户已确认字段、当前任务摘要；**不实现长期记忆**」。
- [PRODUCT-FORM-AND-INTEGRATION.md](PRODUCT-FORM-AND-INTEGRATION.md) §知识检索行：「不将检索结果**自动升级**为业务事实或长期记忆」。
- [PRODUCT.md](PRODUCT.md) §ScenarioPack：「知识库是可审阅事实，会话记忆是带来源、有效期和删除入口的上下文，**两者不能互相自动升级**」。

也就是说：**记忆需求已被识别，但被刻意留空，且留空时已经写下了约束。** 本文的任务是判断 TDAI 能否满足这些约束，而不是引入一个现成系统了事。

## 1. 上游事实核对（2026-10-09 实测）

以下均为对 `_reference/tencentdb-agent-memory`（commit `8b86874`，浅克隆）与 GitHub API 的实测，不是转述 README 宣传语。

| 项 | 实测值 |
|---|---|
| 仓库 | `TencentCloud/TencentDB-Agent-Memory`，MIT License（`LICENSE` 第 3 行明示 "licensed under the MIT"） |
| Star / Fork | 27,839 / 2,701 |
| 最近推送 | 2026-09-29 |
| 声明版本 | README 称当前 `v2.0.0`；`sdk/memory-core/python/pyproject.toml` 为 `1.0.1-beta.1`（**版本口径不一致，取用时须自行钉定**） |
| 部署形态 | 三个服务：`memory-core`(8420) + `memory-hub`(8125) + `proxy`(8096)，Docker 公开镜像 `agentmemory/*` |
| 语言 | 主 TypeScript；**官方 Python SDK 存在**，`sdk/memory-core/python` |
| Python SDK 依赖 | `httpx>=0.24.0`，`requires-python>=3.9` |
| SDK 是否已发 PyPI | **否**。`tencentdb-agent-memory-sdk-python` 与 `tencentdb-agent-memory-sdk-python-v2` 两个包名在 PyPI 均返回 404 |
| 接口规模 | MemoryCore v3 共 **108 个接口**（数据面 18 / Skill 17 / Knowledge 5 / Chat-Memory 1 / Memory-Prompt 7 / 记忆生成日志 2 / Meta 55 / Internal Meta 2 / 实例销毁 1） |

### 1.1 记忆分层（与 Loomrise 直接相关）

| 层 | 上游语义 | 上游存储形态 |
|---|---|---|
| **L0 Conversation** | 原始对话，全上下文 | `POST /v3/conversation/add` |
| **L1 Atom** | 从对话提炼的事实、偏好、约束、事件（`episodic`/`persona`/`instruction` 三类） | `atomic/update`、`atomic/query`、`atomic/search` |
| **L2 Scenario** | 按项目或场景组织的知识块 | `scenario/ls`、`scenario/read`、`scenario/write` |
| **L3 Core / Persona** | 长期画像、稳定模式、高层认知 | `core/read`、`core/write`（单文件 `persona.md`） |

生成是异步管线（`pipeline.everyNConversations`、`l1IdleTimeoutSeconds` 等参数）；检索是分层降级（正常用 L2/L3 快速bootstrap，需要具体事实时 BM25 + 向量 + RRF 回落到 L1/L0），并按条数、字符预算、超时三重截断。

### 1.2 四类记忆资产

除分层外，上游把资产分为 `Chat Memory` / `Skill` / `LLM-Wiki` / `CodeGraph` 四类，**统一注册为 Memory Asset**，通过「Fixed Binding + ACL」决定某 Agent 能用哪些。可见性语义为 `private`（仅 Owner，连团队管理员都看不到）/ `team` / `restricted`（User/Role/Agent ACL）/ `agent`。

### 1.3 已核实的上游已知问题（文档自陈或代码可见）

这几条直接影响取用方式，必须写进设计约束而不是当噪音忽略：

1. **L1 版本字段类型不一致**：`atomic/update` 返回字符串 `"v2"`，`query`/`search` 返回数字。上游文档明确承认「根源在代码…文档无法同时满足，前端需按接口分别处理」。
2. **删除接口不做用户级鉴权**：`conversation/delete`、`atomic/delete` 信任 Bearer + `x-tdai-service-id`，不做归属校验。上游注明「与面板转发前校验一致」——**意味着绕过面板直连 MemoryCore 时，删除权限须由 Loomrise 侧自行保证**。
3. **CodeGraph 优先公开 HTTPS 仓库**，私有仓库与 SSH 凭据支持仍在完善；README 明确「Hub 支持手动资产绑定；全自动记忆路由仍在迭代」。
4. **MongoDB 存储后端是实验特性**，默认关闭，且要求 MongoDB 7.0+ 带 mongot，无 mongot 直接 init 报错、不静默降级。
5. **Proxy 已知限制**：`x-task-id` 缺失时 Hermes/OpenClaw 这类 header 预选客户端会退化成交互式 form，客户端无法响应即导致**会话绕过（无记忆注入、无对话记录）**；部分客户端工具调用后续请求不带扩展 header，会导致该轮跳过注入与记录。

## 2. 选型结论

**结论：采用 TDAI 作为 Loomrise 用户记忆模块的存储与提炼内核，但通过「适配器 + 只读取用」的方式接入，不采用 Proxy 注入，不 fork 代码，不让上游成为任何权威。**

### 2.1 三个候选方案与裁决

| 方案 | 做法 | 裁决 |
|---|---|---|
| **A. Proxy 注入** | Loomrise 客户端改 base URL 指向 TDAI Proxy，由 Proxy 把 L2/L3 blend 进 system prompt | **否决**。见 §2.2 |
| **B. fork / 改上游源码** | 把 TDAI 代码搬进 `loomrise/`，按需裁剪 | **否决**。与[参考项目四条规则](REFERENCE-PROJECTS.md) §3 第 1、2 条冲突：违反「供应商依赖只在 Adapter」，且上游 TypeScript 与 Loomrise Python 不同栈，fork 后无法跟版 |
| **C. 适配器 + 只读取用**（**推荐**） | Loomrise 通过 `MemorySourceAdapter` 合同调用 TDAI L1/L2/L3；读取结果进 `ContextFragment` 并留证；写入仅走受控通道 | **采用** |

### 2.2 为什么否决 Proxy 注入（这是本方案最关键的一条）

TDAI Proxy 的工作方式是把记忆 blend 进 system prompt。INSTALLED.md 对代理管线的描述是：`auth` → `sessionInit` → `injection`（L2/L3 memory + skill + knowledge blended into the system prompt）→ forward。

这与 Loomrise 两条已生效的架构承诺**直接冲突**：

1. **与「渐进式上下文加载可解释」冲突**。[ARCHITECTURE.md](ARCHITECTURE.md) 要求运行时「对每个片段保留作用域、触发条件、优先级、来源版本、敏感级别和 token 估算」，[CONFIGURATION-LAYERS.md](CONFIGURATION-LAYERS.md) §5 要求每次选择可解释且记录 `context_scope`/`activation_reason`/`source_ref`/`source_version`/`token_estimate`/`load_status`。Proxy 把记忆混进 system prompt 意味着**模型看到的内容与 Loomrise 记录的加载事实不一致**——这正是 `loomrise/context.py` 顶部注释所批判的那类「未留证的隐式改写」，Loomrise 已在 AgentScope 侧 fail-closed 拦截过一次。
2. **与「模型只接收约束摘要、不承载全部原文」冲突**。Loomrise 刻意让 `HardRule` 完整定义留在 `RunEvent`，只向模型送当前有效约束摘要。记忆全文注入会把这个边界推倒。
3. **Proxy 会话绕过风险**（§1.3 第 5 条）。Loomrise 的 `RunEvent` 是业务事实源，一旦某些轮次静默跳过注入与记录，审计链就断了，且这种断裂**不会报错**，只表现为「某轮没记忆」。

因此：**Loomrise 自己决定加载什么、加载多少、如何留证；TDAI 只提供「存了什么」和「能检索到什么」。**

### 2.3 为什么 C 仍然值得做

| 需求 | Loomrise 现状 | TDAI 能补什么 |
|---|---|---|
| 跨会话记住用户偏好/约束 | 无（`ContextSnapshot` 仅当前任务摘要） | L3 persona + L1 `instruction`/`persona` 类型 |
| 对话自动提炼事实 | 无 | L1 atom 异步提炼管线 |
| 按场景恢复工作上下文 | 仅 `context_scope=task` 局部 | L2 scenario 文件树 |
| 检索式回退 | 无 | BM25 + 向量 + RRF |
| 记忆可见性与所有权 | 无 | `private`/`team`/`restricted`/`agent` + Owner |
| 删除/撤销入口 | 无（`ContextFragment.valid_until` 未接线） | 上游 `*/delete`、`chat-memory/clear` |

**结论：方向正确，能补真实空白，且不侵入 Loomrise 权威。**

### 2.4 必须承认的三处不匹配

1. **提炼时机 vs 发布纪律冲突**。TDAI 的 L1→L2→L3 是**自动异步**的；而 [CONFIGURATION-LAYERS.md](CONFIGURATION-LAYERS.md) §7.4 与 [INTAKE-AND-INITIALIZATION.md](INTAKE-AND-INITIALIZATION.md) §6.2 要求「CLI 的产物一律是 `candidate`，不是 `published`」。**裁决：TDAI 自动提炼的记忆一律视为 `candidate`，进 `ContextFragment` 时 `sensitivity` 默认 `internal`、`activation_reason` 必填来源，永不自动进入已发布 `AgentVersion`。** 需要进配置的，必须经人工确认写成 `fragments`。
2. **三元组隔离 vs Loomrise 的 tenant + 版本模型**。上游强制 `team_id + agent_id + user_id` 三元组（缺省回落 `default` 桶）。Loomrise 的隔离维度是 `tenant_id` + `agent_version`，且强调「禁止跨租户可见」。**裁决：映射 `team_id ← tenant_id`、`agent_id ← agent_version`、`user_id ← 业务用户标识`，且三元组必须显式传齐，禁止依赖 `default` 回落**（回落等于把不同租户的 L0 混进同一桶）。
3. **Python SDK 未发 PyPI**。两个候选包名均 404。**裁决：按 `LICENSE` 与 `_reference/README.md` 的既有规则，采用「链接或按文档重实现」路径——优先直接调用 MemoryCore v3 HTTP 接口（Loomrise 依赖里 `httpx==0.28.1` 已存在，满足上游 `httpx>=0.24.0`），暂不把未发布 SDK 引入 `requirements.txt`。** 若后续要引入，必须先在 [VERSION-PINS.md](../VERSION-PINS.md) 钉定来源 revision。

## 3. 边界红线（不可越界）

这七条是本文档存在的意义，任何实现方案不得违反。

1. **TDAI 不持有 Loomrise 权威**。它是记忆数据源，不运行、不编排 Loomrise Agent。这与 [REFERENCE-PROJECTS.md](REFERENCE-PROJECTS.md) §2「长期上下文系统（可选外部系统）：经治理的 Context Pack 来源，不承担 Loomrise 的运行、Agent 配置、渠道或发布权威」一致——本文把该行从泛指**落实为具名项目**。
2. **记忆不得自动升级为事实**。沿用 [PRODUCT.md](PRODUCT.md)「知识库与会话记忆不能互相自动升级」与 §6.1「本地 ≠ 有权」：记忆片段进上下文时必须带 `source_ref`、有效期与撤销入口。
3. **记忆不得授予权限**。TDAI 的 ACL 只决定「谁能看到这条记忆」，**不决定「这个 Agent 能做什么」**。工具权限、确认、停止、去重一律仍由 `HardRule` / `ToolPolicy` 在模型外裁决。
4. **`HardRule` 不可写入记忆层**。规则定义留在 `AgentVersion` 配置内；记忆可记录「曾出现过某约束」，但不得成为规则来源，否则违反 §7.4 不可自动修改清单。
5. **模型口头声称「已记住」不是证据**。沿用 AGENTS.md Product Truth；记忆写入是否成功以 `MemoryCore` 响应与 `RunEvent` 为准。
6. **Skill 资产不并入 Loomrise `SkillManifest`**。上游 `Skill` 有自己的版本、ACL 与提取机制，Loomrise 的 `SkillManifest` 有独立的 `candidate/validated/approved/released` 生命周期（§7.2）。二者语义不同，**本阶段不合并**；上游 Skill 仅作为 §7 自进化的机制参照。
7. **删除权限由 Loomrise 侧保证**。上游删除接口不做用户级鉴权（§1.3 第 2 条），绕过面板直连时，Loomrise 必须在调用前自行校验归属。

## 4. 分期路径

每一期都给出**可判定**的退出条件。未通过不进入下一期。

### M0 · 契约与决策（当前阶段，仅文档）

- 产出本文档，确认 §2 选型结论与 §3 七条红线。
- 明确隔离三元组映射、记忆写入是否进 `RunEvent`、TDAI 部署归属（谁运维、凭据谁管）。
- **退出条件**：Jason 确认本文档；§6 待决策项逐条有结论。

### M1 · 只读适配器（最小可验证切片）

目标：**只证明「能读、读得准、读得留痕」，不写任何记忆。**

- 新增 `loomrise/adapters/memory_source.py`，实现 `MemorySourceAdapter` 协议（读 L3 persona / L2 scenario 索引 / L1 atomic 检索），HTTP 直连 MemoryCore v3，显式传齐三元组。
- 读取结果转为 `ContextFragment`，必填 `source_ref`（指向 TDAI 记录 ID）、`source_version`、`valid_until`、`sensitivity`，`load_status` 用既有枚举。
- 接入 `context.py` 的三段式加载，走 `evidence` 段；`activation_reason` 记录命中的检索式与 TDAI 记录 ID。
- 失败即 `skip`（记 `RunEvent`），不阻塞主流程；**记忆不可用不得导致请求失败**。
- **退出条件**：干净环境可用确定性样例跑通「读 L2 → 转 fragment → 进 evidence 段 → 事件留证」全链；记忆服务不可用时回放仍 11/11 通过（与 S1 基线一致）；能证明三元组隔离生效（两个租户互不可见）。

### M2 · 受控写入

目标：**写入是候选，不是事实。**

- 运行结束后把 `RunEvent` 摘要按 §2.4 第 1 条规则提交 L0（`conversation/add`），提炼产物只作 `candidate`。
- 写 `RunEvent`：记忆写入请求 ID、结果、耗时、失败原因。
- **退出条件**：写入失败不影响业务终态（`Outcome` 不变）；写入内容不含凭据与未脱敏敏感字段（对齐 SOUL/隐私约束）；能撤回删除。

### M3 · Skill / Wiki / CodeGraph 复用评估

- 评估 TDAI Wiki ingest 是否可替代或补强 Loomrise 的知识摄入通道（对照 [INTAKE-AND-INITIALIZATION.md](INTAKE-AND-INITIALIZATION.md) §6.3「摄入产物复用既有对象」）。
- 评估 CodeGraph 对 S2 自进化「回归/迁移评测」的价值。
- **退出条件**：给出「采用 / 机制参照 / 不采用」三选一的书面结论与理由；不因「上游有」而默认采用。

## 5. 验收判据（M1 交付时逐条对照）

| # | 判据 | 判定方式 |
|---|---|---|
| 1 | 三元组隔离生效，不依赖 `default` 回落 | 两个租户交叉读取的隔离测试 |
| 2 | 每条记忆片段有 `source_ref` / `source_version` / `valid_until` | 片段结构断言 |
| 3 | 每次加载/跳过都有 `RunEvent` 留证 | 事件回放 |
| 4 | 记忆服务不可用时主流程不受影响 | 停服回放，对比 S1 基线 11/11 |
| 5 | 模型未因记忆获得任何权限 | 构造「记忆中含越权指令」的样例，硬规则仍拒绝 |
| 6 | L1 `version` 字段类型不一致已被处理 | 针对 `update`(str) 与 `query`(num) 各一条测试 |
| 7 | 未引入未发布依赖 | `requirements*.txt` 无 TDAI SDK |
| 8 | 未 fork 上游代码 | 无 TDAI 源码进入 `loomrise/` |

## 6. 待决策项

1. **TDAI 服务由谁部署与运维**：本机 Docker 三服务，还是团队共用实例？影响凭据管理与 §2.4 第 2 条的租户隔离前提。
2. **隔离三元组中 `user_id` 取什么**：Loomrise 当前 `ServiceRequest` 只有 `tenant_id`，**没有稳定的业务用户标识**。是新增字段，还是先用会话匿名桶？这是一个真实的合同缺口，不是配置项。
3. **记忆是否进 `RunEvent`**：进则可审计但体积增大；不进则需独立的记忆事件流。
4. **Prompt 模式**：`MEMORY_PROMPT_MODE` 有 `code`（默认，面向工程协作）与 `chat`（面向个人对话/persona 类记忆）。Loomrise 面向业务用户咨询，默认 `chat` 更合适，但需实测。
5. **存储后端**：sqlite（零依赖，上游推荐上手）还是 MongoDB（实验特性，需 7.0+ mongot）。
6. **是否与 Jason 个人知识库打通**：`/Users/goldenwave/KnowledgeBase/` 已有 L0–L3 分级体系。**默认不打通**（私人知识库与产品运行时数据边界必须显式），如需打通须单独立项并先过隐私分级。

## 7. 与既有文档的关系

| 文档 | 关系 |
|---|---|
| [PRODUCT.md](PRODUCT.md) §79「其他长期上下文或记忆系统只能作为经治理的数据来源」 | 本文是这条原则的**首个具名落地**；不改该原则 |
| [REFERENCE-PROJECTS.md](REFERENCE-PROJECTS.md) §2「长期上下文系统（可选外部系统）」 | 该行**具名化为 TDAI**，仍留在「平行参考」而非「首选集成」 |
| [ARCHITECTURE.md](ARCHITECTURE.md) §S1「不实现长期记忆优化」 | **不变**。M1–M2 只读与受控写入，仍不构成自动摘要或动态调参 |
| [CONFIGURATION-LAYERS.md](CONFIGURATION-LAYERS.md) §6 | 记忆进 `ContextFragment`，不新增第七层；加载策略仍是横切机制 |
| [INTAKE-AND-INITIALIZATION.md](INTAKE-AND-INITIALIZATION.md) §6 三条硬约束 | §3 红线 2/4/5 是其在记忆场景的具体化 |
| [VERSION-PINS.md](../VERSION-PINS.md) | 若引入 SDK，须先钉定 revision（当前未引入） |

## 8. Sources

- TencentCloud/TencentDB-Agent-Memory：<https://github.com/TencentCloud/TencentDB-Agent-Memory>
  - commit `8b86874`（2026-09-29），MIT，本地浅克隆于 `_reference/tencentdb-agent-memory`
  - 已读：`README.md`、`INSTALL.md`、`LICENSE`、`MemoryCore/v3-api-memorycore-doc.md`、`sdk/memory-core/python/{README_CN.md,pyproject.toml,tencentdb_agent_memory/v3/client.py}`、`agents/workbuddy/README.md`
  - 未做：启动任何服务、发任何 API 请求、端到端联调、性能与召回质量实测