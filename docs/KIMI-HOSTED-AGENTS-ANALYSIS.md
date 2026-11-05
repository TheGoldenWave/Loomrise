# Kimi Hosted Agents：执行底座商品化与采用边界 v0.1

日期：2026-11-05。类型：**研究参照**（[REFERENCE-PROJECTS](REFERENCE-PROJECTS.md) **P0-12**）。证据等级：**文档级 A-**——官方文档 14 页逐页核对，字段名、枚举值与端点路径原文保留；**未调用 API、未配置控制台、未安装、未实测长程任务与触发器真实行为、未测中文客服效果**。本文件不改 [PRODUCT](PRODUCT.md) 定位、不改 [ROADMAP](ROADMAP.md) 阶段与退出 Gate、不改六层合同；§4 的借鉴项均为**设计输入**，落地需在对应版本按既有 Gate 验收。

---

## 0. 结论

Kimi Hosted Agents（下称 KHA）卖的**不是 Agent 产品，是 Harness**：云沙箱、会话、事件流、工具执行、记忆库、定时触发器、多智能体委派。它对应 Loomrise 架构图里的「统一执行内核」，不对应「交付工作台」。

三条判断：

1. **它不是同交付面的竞品。** 它没有 `AgentVersion` 的 `tested → approved → released → rolled_back` 状态机、没有评测集与配对回放、没有 `ChangeProposal`、没有 `Outcome` 与外部结果 ID、没有 Widget/Inbox/联系页、没有业务义务账本。这些正是 Loomrise 要立住的地方。
2. **它是中间层的替代品，因此是间接竞品。** 当客户能用几十行 cURL 跑起一个 7×24 长程 Agent 时，Loomrise 必须先回答「为什么还要你的工作台」。答案只能是可验收（D1）、可拥有（D2）、义务账本（D3）——不能是「我们也做了沙箱和 SSE」。
3. **它给出一条必须写进架构的切分线。** 执行内核不能整体外包（否则 `RunEvent`、模型外硬规则、`Outcome` 失守），但也不必整体自建（沙箱、镜像、长程会话持久化、SSE 分发、时钟都可以外包）。详见 §3.2。

一句话：**它把 Loomrise 架构的中间层商品化了，同时把两端（交付治理 / 客户接触面）留了出来。**

---

## 1. 证据与来源

| 页面 | 关键内容 | 等级 |
|---|---|---|
| `quickstart` | 七步跑通：agents → environments → sessions → events/stream → events → artifacts → filesystem | A- |
| `agents` | Agent 字段、不可变版本、版本历史、归档、并发校验 | A- |
| `sessions` | 会话创建、版本冻结、`agent_overrides`、资源绑定 | A- |
| `event-stream` | 事件类型全集、双 ID、游标、断线续读、增量 | A- |
| `tools` | 三类工具、内置工具集清单、自定义工具协议、`load_mode` | A- |
| `permissions` | `enabled` / `permission_policy` 两级配置、确认流程 | A- |
| `environments` | `packages` / `networking` / `setup_script`、`build_status` | A- |
| `skills` | `SKILL.md` 文件包、不可变版本、只读挂载 | A- |
| `memory` | 记忆库、文件版本、挂载路径、无向量检索 | A- |
| `dreams` | 梦境策略、触发条件、失败不回滚 | A- |
| `triggers` | cron、`session_mode`、运行记录、Webhook 通知 | A- |
| `self-hosted-environments` | Worker 拉取模式、能力差异、边界声明 | A- |
| `multiagent-orchestration` | coordinator / child thread、委派与消息 | A- |
| `pricing/hosted-agents` | 三部分计费与单价 | A- |

官方文档站结构与产品页一致，未发现与公众号文章冲突之处；文章中的「8 个金融模板」「140+ Skills」「30+ 插件」属于控制台目录内容，文档未逐项列出，**未核**。

---

## 2. 对象模型（事实层）

| 对象 | 语义 | 版本/生命周期 | 与 Loomrise 的对应 |
|---|---|---|---|
| **Agent** | 持久化、版本化的配置对象 | 每次 `PATCH` 生成**不可变新版本**；旧版本保留可读；`version` 可作并发校验（冲突 409）；归档后只读、不可再建会话，**归档不可逆** | `AgentSpec` + `AgentVersion`（它没有 `tested/approved/released` 状态机） |
| **Skill** | `SKILL.md` + 资源文件，打包为 `.zip`/`.skill` | 创建即不可变；修订 = **归档旧技能 + 建新技能（新 ID、新版本线）**；项目内注入名称/描述/路径，模型自行决定何时打开 | 外部 `SKILL.md`（≠ 内部 `SkillManifest`） |
| **Plugin** | 可复用能力组合（MCP 服务 + 技能） | 官方只给 `plugin_id`；自定义可钉版本或 `latest` | 无对应（Loomrise 明确不做插件市场） |
| **Session** | 一次运行实例，对应一项任务 | 创建时冻结 agent 版本、环境版本、凭据库与记忆库绑定；`idle/running/terminated`；`idle` ≠ 资源结束 | `ServiceRequest` + `Run`（它没有业务终态） |
| **Environment** | 云沙箱配置 | `build_status: building/ready/failed`；会话绑定后不可更换；构建失败时新会话**回退到最近一个 ready 版本** | 沙箱 Adapter 边界（Loomrise 未把镜像版本列为冻结项，见 KHA-07） |
| **Vault** | 凭据库 | 值只写不回显；创建会话时绑定；经平台出口代理注入 | 连接引用 / 后端受控保管 |
| **Memory Store** | 项目级文件集合 | 文件级版本（`created/modified/renamed/deleted`）；`source` 为 `api` 或 `session`，另有 `source_id` 归因 | 用户上下文 / 专家记忆的存储层候选 |
| **Trigger** | 按 cron 或手动运行 Agent | `active/paused/archived`；`upcoming_runs_at` 预览未来 5 次；每触发器保留 500 条运行记录、90 天 | `TaskAttempt` 调度 + `OutreachPolicy`（它没有授权与义务概念） |
| **Thread** | 会话内的执行轨迹 | coordinator + child；子线程不能再生子线程；子线程间不直接通信 | `Unit` 执行轨迹（它是运行时对象，不是配置对象） |

**关键机制**：

- **版本冻结链**：Agent 版本 → Session 冻结 → 运行中不可变。「会话创建后更新 Agent 不影响已有会话」，中断恢复继续用同一版本。
- **事件协议**：三类事件（user / agent / session）。`session.status` 的 `data.stop_reason.type` 为 `end_turn`（本轮结束）或 `requires_action`（等待客户端），后者带 `event_ids` 待办清单。
- **权限**：仅两字段 `enabled` + `permission_policy`（`always_allow` / `always_ask`），支持工具集级默认 + 单工具覆盖；每次调用以 `evaluated_permission` 下发裁决结果；确认走 `user.tool_confirmation`（`event_id` + `allow`/`deny` + `deny_message`）。
- **计费**：沙箱时长（¥0.072/小时，按秒）+ 模型 token + 插件按次（¥0.001–0.45/次）。**工具调用本身有单价**，成本账本必须能记这一层。

---

## 3. 与 Loomrise 的关系

### 3.1 三层映射

| 层 | KHA | Loomrise | 判断 |
|---|---|---|---|
| 运行底座：沙箱 / 会话 / SSE / 工具循环 / 记忆存储 / 触发器 | 完整且比 S1 成熟（多智能体、定时、自托管 Worker） | S1 最小切片 + R1–R3 部分 | **被商品化，正面挤压** |
| 业务配置与裁决：六层、`HardRule` 模型外、`ToolPolicy` | 只有 `system` + `tools` + 两档权限 | 六层冻结 | 它不做 |
| 验收与发布：评测 / 审批 / 回滚 | 无；只有「成功率」「可观测性」 | S2-c 规划 | **它的空档** |
| 业务结果证据 | 无 `Outcome`、无外部结果 ID | 执行合同核心 | **它的空档** |
| 客户接触面：Widget / Inbox / 联系页 | 无 | S2-a/b | 它不做 |
| 交付形态 | 纯 SaaS；自托管仅限**工具执行位置**，推理仍在平台 | 开源 + 单租户自有云 | 结构性差异 |

一处值得记下的诚实表述：KHA 自托管环境页明确写「**自托管环境不严格等于私有化部署，工具的输入和执行结果仍会经过平台模型推理接口**」。这与 [ARCHITECTURE](ARCHITECTURE.md) 已写的「服务部署在用户云不代表所有数据处理均在该云」是同一条纪律，Loomrise 在自有云叙事里应保持同等精度。

### 3.2 自持 / 可外包切分线（本次调研的核心增量）

Harness 被商品化，意味着继续把工程量压在「沙箱、镜像依赖、SSE 分发、长程会话持久化」上，是在跟云厂商比成本。但整体外包会直接毁掉验收能力。可行的切分：

| 必须自持 | 理由 |
|---|---|
| `AgentVersion` 冻结（含依赖快照） | 回放可复现的前提 |
| `HardRule` 模型外裁决 | 价格/权限/金额不能由模型解释 |
| `ToolPolicy`：确认、幂等键、预算、执行前重验 | 外部副作用只能写一次 |
| `Outcome` + 外部结果 ID | 「模型说完成」不是完成 |
| `RunEvent` 账本 | 业务事实源，不可被 Adapter 状态替代 |
| `TaskItem` 义务与触达许可 | 跨会话义务，它完全不做 |
| 发布审批与回滚 | 它的归档不可逆，与回滚冲突 |

| 可以外包 | 理由 |
|---|---|
| 沙箱镜像、依赖安装、`shell`/`ipython` 执行 | 纯算力，无业务语义 |
| 长程会话持久化与断线续读 | 协议成熟，可替换 |
| SSE/流分发 | 同上 |
| 记忆文件的物理存储 | 只要读取路径经我方装配 |
| **时钟**（cron 触发信号） | 但「该不该触发」必须自己判 |

这条线正好落在 KHA 的 API 形状上：`custom tool` 让业务工具留在自己侧执行（**写权不外包**）、`user.tool_confirmation` 让确认权留在自己侧、`trigger` 只能当**时钟信号源**。

> **硬边界**：不得让外部 `trigger` 直接「到点创建会话并执行」。那会绕过「触达先候选、执行前重许可」，等价于把 `OutreachPolicy` 的执行权外包给一个不认识授权与义务的系统。外部触发器只能产生一个待判定的时间信号，是否创建 `TaskAttempt`、是否取得许可，仍由 Loomrise 裁决。

### 3.3 它没有的，正好是我们必须有的

- 没有「候选版本 vs 已发布版本」的区分：Agent 一改就生成新版本，**没有 `tested`/`approved` 门槛**，也没有灰度。
- 没有评测：只有会话成功率与 Token 统计，没有冻结集、没有配对回放、没有 `blind`/`golden` 分集。
- 没有业务终态：`Outcome` 概念缺失，工具执行成功即结束。
- 没有义务：触发器只管「按时跑一次」，不管「答应过的事有没有做完」。
- 没有客户接触面：它是 API/控制台，不是客服应用。

---

## 4. 可借鉴（KHA-01…KHA-10）

每条给「上游怎么做 / 我方落点 / 差异与限制」。**借鉴 ≠ 照抄**，冲突处以 Loomrise 既有合同为准。

### KHA-01 · 触发器把「计划触发」与「任务成功」切开

**上游**：`completed` 只表示「会话已创建、初始事件已被接受」，**不代表任务完成**；确认结果要拿 `session_id` 另查。重叠运行记为 `skipped` + `error.type = overlap_in_flight`；暂停后恢复**从当前时间重算，不补跑**错过的时点；`upcoming_runs_at` 给未来 5 次计划时间供人核对。

**落点**：[TASK-SYSTEM-DESIGN](TASK-SYSTEM-DESIGN.md) §7 调度语义；[RELEASE-PLAN](RELEASE-PLAN.md) R4 主动服务。<br>
**差异**：Loomrise 已有 `TaskAttempt` 的 lease/generation 与 §7.1 重启裁决，比它严格；但「计划触发成功 ≠ 义务完成」这一条要在状态投影里显式体现，不能只有一个 `completed`。

### KHA-02 · 梦境：把「记忆整理」降级成一次普通受治理运行

**上游**：记忆库是纯文件；Dreaming 由**平台托管触发器**在「变更会话数达阈值（1–100）」或「每日定时」任一满足时创建一次**普通会话**，Agent 直接改写原库；每个文件变更留版本，`source = session` + `source_id` = 会话 ID，可反查「这次整理改了哪些文件」；`.dream/log.md` 连 no-op 也记。

**落点**：[USER-CONTEXT-DESIGN](USER-CONTEXT-DESIGN.md) §8 动态压缩与经验优化；[EXPERT-USER-MEMORY-SYSTEM](EXPERT-USER-MEMORY-SYSTEM.md) 的专家记忆整理。<br>
**借鉴点**：整理不是「偷偷改 prompt」，而是**一次可归因的运行 + 可回滚的文件版本**。这绕开了 REFERENCE-PROJECTS 已否决的 Proxy 注入形态。<br>
**必须改进的缺陷**：失败不回滚、只能逐文件恢复、会话挂载路径写入绕过 `content_sha256` 并发校验。Loomrise 应做成**批次级事务 + 整体撤销**，并把「整理前后差异」作为待审候选而非直接生效。

### KHA-03 · 工具 Schema 的两级加载模式

**上游**：`load_mode: eager | on_demand`，工具集级默认 + 单工具覆盖。`on_demand` 时先只播报工具名清单，模型用 `select_tools` 元工具按名加载 schema；`select_tools` 以普通 `agent.tool_use` 事件出现，客户端无需特殊处理。插件携带的 MCP 工具默认 `on_demand`。**不支持的模型静默回退为全量内联。**

**落点**：[AGENT-INTEGRATION-PLAN](AGENT-INTEGRATION-PLAN.md) AGI-02/03/08；[ARCHITECTURE](ARCHITECTURE.md)「最小语义工具与渐进披露」。<br>
**真实分歧（必须显式记录）**：KHA 回退到「全量内联」，Loomrise 选「固定每次运行的最小子集」。前者省事、兼容好；后者更安全、不泄露工具面。**保留 Loomrise 的选择**，但要在兼容矩阵里写明这条取舍，否则实现时会被更省事的路径带跑。

### KHA-04 · 权限裁决单值化、逐次留证

**上游**：两个字段搞定；每次调用的 `evaluated_permission` 直接挂在 `agent.tool_use` 事件上。不需要把完整规则原文塞进事件。

**落点**：`ToolPolicy` 的配置 schema 与 `RunEvent` 工具事件字段。<br>
**建议**：工具事件增一个 `evaluated_policy` 单值（哪条策略放行/拦截），完整规则证据以引用方式另存。这与 [ARCHITECTURE](ARCHITECTURE.md)「完整规则证据留在 `RunEvent`」不冲突，只是把「结论」和「依据」分层，避免每轮都灌全文。

### KHA-05 · `requires_action` 的结构化等待语义

**上游**：`session.status.idle` + `stop_reason.type`；`requires_action` 时 `event_ids` 列出待处理项（自定义工具结果、工具确认）。多智能体下等待是**线程级**的，其他线程继续跑，会话级状态仍为 `running`。

**落点**：`ServiceRequest` 的等待态投影与 AG-UI 事件映射。<br>
**价值**：Loomrise 有「等待确认」状态，但缺一个结构化终止原因。加上 `stop_reason` 后，前端能直接回答「在等谁、等什么」，而不是靠文案猜。线程级等待也正好对应 `Unit` 的并发加载语义。

### KHA-06 · 事件流的双 ID 与增量替换

**上游**：SSE 消息 `id` = **恢复游标**（不透明字符串）；`data` 内事件对象 `id` = **业务事件 ID**（用于去重）。两者不是一回事。连接先收 `control` 告知当前游标；30s 一次 `: hb`；断线用 `cursor` 或 `Last-Event-ID`，游标失效则重读历史取新 `stream_cursor`。`agent.delta` 只存在于实时流、不在历史，**完整事件到达后必须替换累积增量**。

**落点**：AG-UI 投影层与运行日志前端。<br>
**这是最容易做错的一组细节**：把游标当事件 ID、把增量当事实、断线后重放重复事件，都会直接污染「已回复/已送达」的计数。

### KHA-07 · 环境版本与会话绑定

**上游**：`build_status` 三值；构建失败时新会话**回退最近一个 ready 版本**；会话创建时冻结当时最新 ready 版本，之后更新环境不影响已有会话；`limited` 网络策略下 `allowed_hosts` 支持通配符/端口/IP-CIDR，另有 `allow_mcp_servers`、`allow_package_managers` 两个独立开关。

**落点**：[ARCHITECTURE](ARCHITECTURE.md) `AgentVersion` 依赖快照 + 沙箱 Adapter。<br>
**发现的缺口**：Loomrise 的 `AgentVersion` 目前冻结配置，**没有把「运行环境镜像版本」列为冻结项**。同一 `AgentVersion` 在两个镜像上跑，回放不可复现。建议补进依赖快照（不要求照抄 `build_status` 三值）。

### KHA-08 · Skill 的文件包形态与只读挂载

**上游**：一个 `SKILL.md` + 资源文件打成不可变包；运行时**只注入名称、描述与文件路径**，模型自行决定何时打开；挂载只读；包内 `SKILL.md` 必须恰好一个。

**落点**：AGI-03/04 的外部 `SKILL.md` 接入；与内部 `SkillManifest` 严格分开。<br>
**不借**：它的「修订 = 换 ID 换版本线」与 Loomrise 的回滚要求冲突。Loomrise 的 `SkillManifest` 版本应可在同一 ID 下演进并回滚。

### KHA-09 · 记忆的「索引常驻 + 内容按需」读取形态

**上游**：无自动向量检索；会话启动只注入根目录 `README.md` + `index.md` 各 ≤16 KiB，其余用文件工具按需读取；`read_only`/`read_write` + `instructions` 在会话创建时冻结。

**落点**：[USER-CONTEXT-DESIGN](USER-CONTEXT-DESIGN.md) §7 上下文装配。<br>
**旁证价值**：这与 Loomrise 的「常驻基线 → 当前任务 → 按需证据」三段式同构。一个成熟商业产品选择**不建向量库、用索引文件 + 按需读取**，说明渐进加载不是洁癖，是可运维的取舍。<br>
**不借**：客服知识必须可检索，不能只靠索引文件；`index.md` 的维护成本会随规模上升。索引常驻只适用于 baseline 摘要层。

### KHA-10 · 凭据注入的边界

**上游**：值只写不回显、创建后不可再查看、变更靠轮换；注入只覆盖经平台出口代理的 80/443 流量，按凭据自身的主机白名单匹配替换占位符；MCP 凭据按 MCP 服务地址匹配。

**落点**：连接引用与 `ToolManifest` 的凭据字段。<br>
**价值**：「只写不回显 + 创建时绑定 + 注入范围有限」三条，比「加密存储」更能防误用。Loomrise 的「长期凭据不进浏览器/公开包/Trace」应补上「注入范围」这一维。

---

## 5. 不借

| # | 不借 | 理由 |
|---|---|---|
| **KHA-X01** | 归档不可逆；技能修订必须换 ID 换版本线 | 与 `rolled_back` 要求直接冲突 |
| **KHA-X02** | 梦境失败不回滚、逐文件手工恢复 | 应做批次级事务 + 整体撤销（KHA-02 已注明改进方向） |
| **KHA-X03** | 模型自主 `spawn_subagent` 决定业务编排 | KHA 自己承认「需精确控制请自行编排多个会话」；Loomrise 的编排权必须在自持侧，且仅在可隔离/限权/验收/回退时才考虑子 Agent |
| **KHA-X04** | 用 `idle` 当轮次结束并当作业务终态 | 与「生成 ≠ 发送 ≠ 业务完成」分层冲突 |
| **KHA-X05** | 「完成」即结束、无 `Outcome` 与外部结果 ID | 这是它的结构性缺口，不能学 |
| **KHA-X06** | 插件市场 / 140+ Skills 目录作为能力指标 | Loomrise 明确不做插件市场；按六层收敛配置面 |
| **KHA-X07** | 自动触发直接创建执行会话 | 绕过「触达先候选、执行前重许可」（见 §3.2 硬边界） |

---

## 6. 对迭代计划的落点

| 编号 | 落点版本 | 具体动作 | 是否改 Gate |
|---|---|---|---|
| KHA-01 | R4（S2-c 主动服务） | `TaskAttempt` 状态投影增「计划触发成功 ≠ 义务完成」；重叠记 `skipped`；恢复不补跑写入 §7 | 否，细化既有 Gate 证据 |
| KHA-02 | R4-WP6（受控抽取与遗忘） | 记忆整理定义为一次受治理 `Run`，产物为待审候选 + 批次可撤销 | 否 |
| KHA-03 | R0/R1（AGI-02/03） | `load_mode` 取舍写进兼容矩阵；保留「最小子集」而非全量回退 | 否 |
| KHA-04 | R1/R2（`ToolPolicy`） | 工具事件增 `evaluated_policy` 单值；规则依据另存引用 | 否 |
| KHA-05 | R2-WP5 / R3 | `stop_reason` 结构化终止原因进入 `ServiceRequest` 投影 | 否 |
| KHA-06 | R2-WP4 / R3（SSE） | 双 ID 分离；增量仅实时、完整事件替换增量；断线重放去重 | 否 |
| KHA-07 | R1（`AgentVersion` 快照） | 依赖快照补「运行环境镜像版本」 | 否，补合同字段 |
| KHA-08 | R3（AGI-03/04） | 外部 `SKILL.md` 只读挂载 + 元信息注入；内部 `SkillManifest` 保持可演进 | 否 |
| KHA-09 | R4（用户上下文） | baseline 层可用「索引常驻」；知识检索仍走索引服务 | 否 |
| KHA-10 | R2（连接引用） | 凭据补「注入范围」维度 | 否 |

**共同约束**：以上均为设计输入，不新增阶段、不新增平行业务状态、不引入 KHA 作为运行依赖。任一项落地时，证据位仍写回既有 `M-A-*` / `M-B-*` / `M-C-*` 行。

---

## 7. 待确认（KHA-Q1…Q6）

| # | 问题 | 影响 |
|---|---|---|
| **KHA-Q1** | 是否把 KHA 列为后台 Worker / 通用 harness 的**具名 Provider 候选** | 若列，需与 Codex SDK、Claude Agent SDK 同条件对照，并先验证 Adapter 边界（会话状态不能成为第二权威） |
| **KHA-Q2** | `AgentVersion` 是否必须冻结镜像版本，还是只冻 `environment_id` + 摘要 | 影响 R1 合同字段与回放可复现性证明强度 |
| **KHA-Q3** | 记忆整理的「批次可撤销」粒度：按次运行 / 按文件 / 按 diff 块 | 影响 R4-WP6 的存储与 UI |
| **KHA-Q4** | `load_mode` 与 Loomrise「最小子集」的兼容矩阵是否覆盖不支持轮内加载的 Adapter | 影响 AGI-08 验收范围 |
| **KHA-Q5** | 外部触发器作为「时钟信号源」是否需要单独的合同对象 | 影响 Task 调度接口是否新增类型 |
| **KHA-Q6** | 企业客服场景下「会话送第三方推理」的合规口径 | 采购障碍；与自有云叙事直接相关，需单独评估，不在本文裁决 |

---

## 8. Sources

- 快速开始：https://platform.kimi.com/docs/hosted-agents/quickstart
- 智能体：https://platform.kimi.com/docs/hosted-agents/agents
- 会话：https://platform.kimi.com/docs/hosted-agents/sessions
- 事件流：https://platform.kimi.com/docs/hosted-agents/event-stream
- 工具：https://platform.kimi.com/docs/hosted-agents/tools
- 权限策略：https://platform.kimi.com/docs/hosted-agents/permissions
- 执行环境：https://platform.kimi.com/docs/hosted-agents/environments
- 自托管环境：https://platform.kimi.com/docs/hosted-agents/self-hosted-environments
- 技能：https://platform.kimi.com/docs/hosted-agents/skills
- 记忆：https://platform.kimi.com/docs/hosted-agents/memory
- 梦境：https://platform.kimi.com/docs/hosted-agents/dreams
- 触发器：https://platform.kimi.com/docs/hosted-agents/triggers
- 多智能体编排：https://platform.kimi.com/docs/hosted-agents/multiagent-orchestration
- 控制台：https://platform.kimi.com/docs/hosted-agents/console
- 定价：https://platform.kimi.com/docs/pricing/hosted-agents
- 产品公告（公众号）：https://mp.weixin.qq.com/s/anUer3njbiUh4KOYfORncA（2026-11-05 12:16）

以上均为 2026-11-05 访问。**未调用 API、未开户、未走查控制台界面**（本会话浏览器插件不可用），故不产生界面级（B+）或运行级证据。
