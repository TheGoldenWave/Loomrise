# 架构与对象权威 v0.17

状态：2026-10-29，**路由与能力单元 `Unit` 已采纳为正式合同（v1.0），R1 落最小实现、R3 落画布与嵌套**；官方网页客服应用、统一业务执行与治理、自有云快捷交付，以及专家内版本化任务蓝图和 Harness 渐进披露的架构方案已确认，新增模块和合同仍为规划。S1 最小合同、执行内核及渐进式上下文加载已有代码；R1 SQLite 配置服务、HTTP/MCP/CLI 共用应用服务、TaskItem 撤销恢复最小切片及配置工作面的本机 fixture 浏览器联调已有实现与验证证据，但 R1 Gate 未通过。六层职责见[配置合同](CONFIGURATION-LAYERS.md)；`Unit` 契约见[路由与能力单元](ROUTE-GRAPH-AND-UNITS.md)，版本落点见[版本切分](RELEASE-PLAN.md)。本版补充 [pi durable](https://github.com/earendil-works/pi/tree/main/packages/durable) 的执行耐久机制参照，并按 Task §7.1 明确恢复裁决；**已落最小 `DurableRunAdapter` + SQLite 存储（零新依赖），未引入上游依赖**。截至 2026-10-29，R2-WP5 新增持久工具意图和未知操作阻断首片；外部结果对账收敛、挂起/唤醒仍未实现。完整 TaskItem/TaskAttempt、用途隔离及生产身份仍待验证。以下架构图和对象表同时包含 S1 切片与目标规范；真实证据见[S1 交付与验收](S1-BUILD-REPORT.md)、[R1 证据摘要](reports/R1-EVIDENCE.md)、[R2 证据摘要](reports/R2-EVIDENCE.md)和[版本钉](../VERSION-PINS.md)，建设顺序见[客服与自有云交付方案](CUSTOMER-SERVICE-DELIVERY-PLAN.md)。

项目采用**交付工作台 + 官方客服应用 + 统一执行内核 + 分类适配器**，区分**产品控制面**、**客服会话与一线操作**、**业务执行**、**媒体与渠道**、**知识摄入与检索**、**业务工具**、**观测与评测**、**部署交付**。首个云交付以单 Agent、单租户实例为目标；决策 Provider 只给建议，硬规则和发布权仍在 Loomrise。

```text
获授权 FAQ/URL/文件/CLI → 摄入与版本化知识 → ScenarioPack
                                                ↓
交付工作台（搭建/策略运营） → AgentSpec/AgentVersion → 发布绑定
                                                ↓
官方客服应用：Widget / Contact Page / Inbox / 移动 WebView
已有业务应用：经相同公开接口接入          │
                           Conversation / 接管事实 / 访客权限
                                                ↓
Web 文字 → 渠道适配 ───┐                  ExecutionService
Web 语音 → 媒体适配 ───┼──→ ServiceRequest / 权限 / 确认 / 幂等 / 取消 / 预算
Telegram/邮箱 → 渠道适配 ┤                       │
其他 IM/电话 → 后续适配 ┘                       │
                         ├── Agent 运行适配（AgentScope 候选）
                         ├── DecisionPolicy（可选 Provider 只给建议）
                         ├── 信息源 / 知识检索只读适配
                         └── 业务工具合同 → 供应商/模拟适配 → 结果 ID
                                    ↓
                               ServiceRequest / RunEvent
                                    ↓
                        Case → EvalSet → EvalResult
                                    ↓
                  ChangeProposal → 人工审批 → Release / Rollback
```

## 候选组合与责任边界

| 层 | 候选复用 | Loomrise 必须掌握 |
|---|---|---|
| 交付工作台 | 基础 UI、AG-UI 客户端 | 场景配置、业务组件、就绪检查、验收与发布 |
| 官方客服应用 | Web 组件、消息与表单基础设施 | Widget/联系页/Inbox、访客身份、会话记录、人工接管、消息送达与发布版本绑定 |
| 控制面 | Web 框架、身份库、按需复用服务组件 | 租户、`AgentVersion`、密钥引用、配额、业务数据与发布权限 |
| 业务执行 | AgentScope main 快照 `a388212`（源码版本字符串 2.0.8） | `ExecutionService`、任务生命周期、恢复、幂等、取消确认与真实结果 |
| 执行耐久层（规划） | [pi durable](https://github.com/earendil-works/pi/tree/main/packages/durable) 作为机制参照；不作为默认运行依赖 | `DurableRunAdapter` 的提交线、checkpoint、挂起/唤醒、恢复、重放、重试与 crash-loop parking；业务合同、外部副作用和结果判定仍由 Loomrise 掌握 |
| 决策策略 | 工程规则、可选分类／评分 Provider | 候选过滤、拒选、阈值、回退、审计与评测 |
| 网页语音 | Pipecat 最小工程链路 | 媒体会话到业务请求的桥接、播放状态、用量与超限停止 |
| 交互协议 | AG-UI 最小事件映射 | 业务事件、权限投影、脱敏与可靠状态 |
| 观测 | OpenTelemetry；Langfuse 可选 | `RunEvent` 权威、业务终态、成本账本与证据保留 |
| 外部接入 | API / 文件 / 事件流与外部检索 SDK | 来源授权、身份/字段映射、检索权限和引用、撤销、接入状态 |
| 知识摄入 | 文件解析、网页抓取与索引实现 | FAQ/URL/文件/CLI 统一来源条目、版本、有效期、候选审阅、索引就绪和撤回影响 |
| 物料资产（规划） | 对象存储、媒体处理、内容理解与检索 Adapter | 原件/派生版本、授权/有效期/可用范围、已审简介索引、撤回失效；发送通过既有工具和消息合同留证 |
| 业务工具 | 供应商 API / 用户自定义适配 | `ToolManifest`、执行授权、沙盒/模拟、确认、幂等和结果证据 |
| 改进 | SkillOpt / skill-up / SkillHone 作为方法或离线适配参照 | `Case`、`EvalSet`、`EvalResult`、`ChangeProposal`、审批、发布与回滚 |
| Task 协调（规划） | 持久队列/耐久执行候选 | TaskItem 的来源、计划、采用、占用/代次、停止、仲裁和执行关联；实际结果由原有执行内核掌握 |
| 用户上下文（规划） | 记忆存储/提炼/检索 Adapter | 稳定主体、来源/用途/时间/撤销、记忆候选、画像投影、实际加载与受治理压缩 |
| 自有云交付 | 容器工具及云资源模板 | 固定发行物、资源映射、凭据引用、初始化与检查、升级/恢复/迁移记录；云私有类型不进入业务合同 |

AgentScope `RealtimeAgent` 与 Qwen Audio Agent 仅作为限时语音对照，不同时维护三条生产链路。Octop、Dify、Langflow 作为应用体验参照，不作为默认底座。框架状态通过 Adapter 关联，前端不绑定上游私有数据类型。

渠道/媒体适配、Agent 运行适配、信息源适配、知识检索适配、业务工具适配和事件导出是不同边界。网页语音的媒体交互可以异步进行，但业务请求仍进入同一 `ExecutionService`；AgentScope 是运行 SDK 候选，不是“文字专属业务内核”。新供应商优先实现现有适配合同，不增加平行任务状态或另一套发布流程。

## 官方客服应用、会话与接管（规划未实现）

完整网页客服覆盖落在可部署的官方应用模块，工作台仍承担配置和治理。一线客服在 Inbox 回复、承接和释放会话；策略运营在工作台复核提名、标注真值、评测和审批。应用可与工作台同一发行，也可接入已有业务前端；其操作仍通过相同业务接口留证。页面计数和现有 S2 原型不是客服应用完成证据。

| 规划合同 | 归属与必要语义 |
|---|---|
| `Conversation` / 访客资料 | 客服应用管理会话、消息序号、渠道身份与最小访客字段；一段会话可关联多个 `ServiceRequest`。访客、坐席和工作台用户的访问权限分别校验 |
| 人工交接记录 | 关联会话及受影响请求，区分请求交接、执行暂停确认、人工承接、人工回复、释放和恢复；事件写入关联的 `RunEvent`，通知回执另记 |
| 入口/渠道绑定 | Widget、联系页与渠道绑定已发布版本及环境；入口只获得必要客户端权限，长期模型/云密钥由服务端引用 |
| 答疑结果 | 关联资料引用、生成与送达证据、问题解决确认或未知、升级结果；有业务写入时另保存外部结果 ID |

以上均为目标合同，尚未加入 S1 代码。现有 `ServiceRequest` 状态不直接增加“人工接管＝取消”这一推断。交接时停止受影响的后台执行，取得暂停或取消执行确认后才允许人工/AI 单一执行者继续；恢复必须检查最新资料、权限、预算、任务代次和确认有效性。超时只触发占用与恢复检查，满足已登记条件后才能切换接待所有权并使旧占用失效；人工与 AI 发送或写入前均核验当前占用代次。静默不能证明人工已完成或取消已确认，也不自动重启有副作用请求。

Widget 与 Contact Page 的外观、语言、访客表单、预约及社交外链由应用 Schema 管理；AI 生成页面只产出可审阅的受约束组件草稿。页面发布与 `AgentVersion/Release` 分别编号，发布入口必须绑定可用的业务版本。预约跳转、通知送达、人工承接与业务完成分别留证。

S2-a/b 先实现最小沙盒发布绑定：冻结配置，通过来源、权限和固定样例检查，经人工批准后绑定指定测试版本；入口标明沙盒环境，不读取可变草稿，业务写入工具仍使用模拟实现。完整配对评测、提案审批、发布回滚在 S2-c 验收，真实用户公网发行在 S3 验收。授权渠道沙盒可使用必要的测试地址、回调或测试域名，不能据其可达性宣称生产交付已通过。

FAQ、URL、文件与 CLI 进入同一摄入服务：登记来源及使用范围 → 解析 → 审阅候选 → 形成版本化知识 → 建索引 → 供检索。解析/索引失败不得标成可用知识；删除或授权撤销使后续检索停止，并使受影响的评测和发布就绪状态待重验。摄入写入是配置管理操作，不赋予 Agent 修改来源或业务系统的权限。

### 物料资产、处理与发送（目标规范，后端未实现）

物料与知识事实分别管理，知识域下提供独立物料库。`MaterialAsset/MaterialVersion` 为拟建应用资产合同，管理原件、派生文件、来源/授权、有效期、专家/环节范围及简介审阅版本；具体字段须另行登记，尚未加入 S1。对象存储管理实际文件，数据库管理资产和权限，压缩、OCR/转写/理解和检索分别留作业/产物证据；媒体处理服务不等同于平台内创作 Agent Worker。原件、派生文件可读、简介已审、索引可用、发送与送达均为独立状态。

Agent 检索经审阅、有效且范围匹配的简介/标签，返回资产与版本引用，再按需进入 `ContextSnapshot`；摘要只是选择依据，不自动成为业务答疑事实，也不授予发送权。人工和 Agent 文件发送经既有 `ToolManifest/ToolPolicy`、会话占用与 `ServiceRequest/RunEvent` 留证。自动发送默认关闭，使用批准的 AgentVersion 和策略，校验物料允许自动发送、请求/适用条件、数量及渠道限制；人工接管立即使 AI 旧选择失效。执行前及异步读取后重验资产/策略版本、授权、有效期、范围、原件/派生可用、会话与任务代次，拒绝迟到或撤回选择。

消息冻结名称、文件/派生版本和简介快照，回执绑定具体发送尝试；历史内容不因资产改名或撤回被重写。撤回阻止新检索/发送，不承诺收回客户已下载的文件。发送记录不是送达、已读或业务完成，超时未知先对账再决定重试。当前前端只以 IndexedDB 保存原件、localStorage 保存元数据，压缩/理解与 Agent 自动发为明确仿真，不能作为对象存储、向量检索或真实渠道验收。详见[物料专题](MATERIAL-LIBRARY-AND-DELIVERY.md)。

Telegram、邮箱桥接与浏览器/Telegram 通知通过各自 Adapter 接入；消息、回复关联与去重、身份、授权撤销和回执乱序独立验证。Telegram 通知不等同于消息渠道打通；移动 WebView 不等同于原生媒体 SDK。使用统计从消息与 `RunEvent` 等权威记录派生，AI 已回复、问题已解决、业务成功、人工承接及延迟指标必须有各自口径。

## 可选配置助手与编辑权威（规划未实现）

[第二轮前端交付与评审](S2-FRONTEND-ROUND2.md)实现了同一草稿与冻结快照的本地前端投影，目录为 `prototypes/console-next/`。其 state/action 只用于界面验证，不是新增领域权威或正式应用 API；真实来源、身份、幂等、执行、评测与发布仍由后端负责。本轮不建设平台内 Worker，外部 Agent 桥接也未接入。

手动编辑与初始化助手共用 `AgentSpec` 草稿、结构校验、来源、权限和版本合同；概览与详细配置是同一对象的 UI 投影。手动创建不依赖生成助手；助手只提出带基准版本、依据和影响范围的候选差异，经用户采用后写入草稿，不能直接授权、执行生产动作或发布。人工修改与助手建议必须处理过期和并发冲突，已发布版本不原地覆盖。创作助手与客服执行 Agent 的身份、权限和预算分别管理，既有六层及 `ExecutionService/RunEvent/Release` 权威不变。具体体验见[配置后台体验优化](CONFIGURATION-UX-OPTIMIZATION.md)；第三方创作与后台 harness 接入已进入[高优先级开发计划](AGENT-INTEGRATION-PLAN.md)，具体 Provider 与支持矩阵仍待实测，不改变运行 SDK 选型。

### 统一 API、MCP／Skills／CLI 与后台 Worker（方向已确认，规划未实现）

网页、MCP 和 CLI 通过同一应用服务操作来源、草稿、候选、沙盒试用与评测资源，服务端重验身份、作用域、基准 revision、幂等和预算。MCP 是第三方 host 的工具与资源入口，外部 `SKILL.md` 指导工具组合；内部 `SkillManifest` 定义客服策略，两者分别版本化。MCP Skills 的发现、内容读取与宿主加载分开，兼容与降级逐客户端验收。外部创作 Agent 仅获受限草稿／候选操作，不开放生产业务写入、未消费 blind、验收真值修改或直接发布。

Loomrise 调用通用 harness 则通过独立后台 Worker／Provider Adapter，先验证一个供应商。作业冻结授权输入、可改范围与预算，返回结构化产物及证据；供应商线程、工具循环和内部状态留在 Adapter，作业成功不等于候选采用、业务成功或发布完成。取消、恢复、并发冲突、子作业预算和迟到产物分别留证；故障时手动编辑与已发布在线服务独立可用。治理报告与改动建议由 Agent 辅助生成，裁决和审批由 Loomrise 规则、独立评测及获授权的人掌握。S2-a 创建接入、S2-b 诊断／Worker 首链、S2-c 受控改进、S3 可选 Worker 云交付按[开发计划](AGENT-INTEGRATION-PLAN.md)验收。

## Task 协调与用户上下文模块（方向已确认，合同提案未实现）

专家的默认任务与主动服务定义置于拟建 `AgentSpec.task_blueprints`，包含局部 `TaskPolicy/TaskTemplate/OutreachPolicy` 职责，随 `AgentVersion` 冻结、评测、发布与回滚；不建设跨专家共享策略对象或独立策略发布链。运营配置、会话 TODO、业务事件与人工安排通过同一用例形成 `TaskProposal/TaskItem`。确定主体的服务周期只幂等初始化适用默认事项：低风险内部事项可按批准规则登记，触达先候选再经采用判定，不因初始化或 Agent 决策获得联系权。

持久计划与调度层协调事项，执行创建或唤醒 `ServiceRequest`，或交受限后台 Worker 生成治理产物。`TaskAttempt` 关联租约/代次、版本与结果，不替代 `RunEvent/Outcome`。Agent 仅可在蓝图声明范围内提交实例 revision/取消意图，不能写发送/完成终态；原事项可靠阻断后才能激活替代，未知结果先对账。保留来源与执行 AgentVersion，版本发布不重建事项或中途换请求版本；在途迁移显式预览、重验，删除蓝图不抹除义务，回滚不重置频次或复活退订。对象与完整合同见[Task 设计](TASK-SYSTEM-DESIGN.md)与[命名](NAMING.md)。

`UserContextService` 是拟建的独立职责模块：身份/作用域、受控记忆候选与记录、派生画像、按任务精确读取、上下文装配/压缩与保留失效。记忆和画像仅提供依据；Task 账本、业务系统、权限与配置仍各有权威。输出进入既有 `ContextSnapshot/ContextFragment`，不新增第七层，不允许 Provider/Proxy 私自注入。主体跨会话连续性、AgentVersion 的读取快照、字段/策略兼容性分别管理，详见[用户上下文设计](USER-CONTEXT-DESIGN.md)。

前置合同包括稳定业务 `subject_id`、用途/关系授权、严格有效期/撤销以及可记录执行前事项/记忆变更的同一事件 envelope。当前 S1 RunEvent 强制 request/run关联，不能为记录新事项伪造一次运行；正式扩展及兼容性验证在[联合计划](TASK-MEMORY-INTEGRATION-PLAN.md)中安排。两类模块均未加入 S1 代码，调度器与记忆底座仍待同条件验证。

### 最小语义工具与渐进披露（方案已确认，未实现）

当前事项摘要由系统装配，不把每个内部 CRUD 都做成模型工具。拟以有界 `inspect_context` 读取/展开和 `manage_tasks` 类型化提出/调整/请求取消覆盖任务决策；真正发送和业务写入仍各有语义明确的 ToolManifest、权限和结果合同，不提供万能 `execute/invoke`。基于角色、已发布版本、任务/Skill、当前授权及预算形成最小可见工具集合，在线客服、外部创作 Agent 与后台 Worker 分别限权。

Harness 按“身份/安全摘要与工作集 → 当前任务蓝图/Skill、必要事实及 Tool Schema → 按需证据/结果”披露，冻结实际可见集合的 ID、版本/哈希与输入快照，加载/跳过和预算消耗留证。隐藏工具猜名仍拒绝，发现不等于授权；不支持轮内增量工具的 Adapter 固定每次运行的最小子集，扩展须新快照/运行边界。全局频次、占用、撤销与业务终态始终由服务端账本判定，不从提示词子集推断。S1 工具目前固定装配，不具备此处完整披露能力；接入 Gate 见[Agent 计划](AGENT-INTEGRATION-PLAN.md)。

## S1 配置与执行边界

S1 将复杂业务 Agent 配置压缩为可审计的六层：`ContextSnapshot` 提供带来源和有效期的事实；`RequestRouting` 选择当前唯一主请求；`Skill/SOP` 描述适用条件、下一步和退出；`HardRule` 在模型外裁决权限、确认、停止和去重；`ToolPolicy` 描述工具副作用、幂等和结果证据；`Outcome` 保存业务状态和结果 ID。模型可以提出解释和下一步，但不能绕过 `HardRule`、`ToolPolicy` 或 `Outcome`。

渐进式上下文加载是横切的执行策略，不新增第七个领域层。运行时按“常驻基线 → 当前任务/Skill → 按需知识或工具结果”选择上下文，并对每个片段保留作用域、触发条件、优先级、来源版本、敏感级别和 token 估算。全局/任务/Skill 三级 `HardRule` 可以被独立追踪和模型外评估，但不要求把全部规则原文注入上下文；执行内核只向模型提供当前有效约束摘要，完整规则证据留在 `RunEvent`。这样既保留约束边界，也避免为了修复一个 badcase 无限堆叠 Prompt。

上下文压缩不是 S1 之后要永久放弃的能力，冲突点在于“未留证的隐式改写”。S1 关闭 AgentScope 运行时注入，并由压缩适配器拦截原生自动压缩/截断；长期由 Loomrise 的 `ContextCompactionService` 读取不可变上下文账本，产出带输入快照、摘要或截断算法、来源覆盖、输入/输出哈希、token 变化和成功/失败事件的压缩结果。上游 SDK 只能作为执行器，不能成为上下文事实源。压缩前后的业务 `RunEvent` 与来源引用均保留，审计回答的是“原始加载了什么、压缩保留了什么、哪些内容被移出模型窗口以及为什么”。

S1 的最小加载合同包含 `context_scope`（global/task/skill/evidence）、`activation_reason`、`source_ref`、`source_version`、`token_estimate` 和 `load_status`（loaded/skipped/expired/budget_capped）。加载与跳过都记录事件，便于区分“规则未命中”“上下文未加载”“检索无结果”和“模型误判”。S1 不实现自动摘要、长期记忆优化或基于评测结果的动态调参。

长期记忆拟接入外部内核，继续作为受治理的数据来源，不新增第七层。[用户上下文设计](USER-CONTEXT-DESIGN.md)管理业务用户记忆/画像/上下文模块职责；**专家记忆**（跨用户经验，归属 `expert_id` 而非 `agent_version`）的分工、五个身份合同与阶段路线见[专家-用户记忆体系](EXPERT-USER-MEMORY-SYSTEM.md)；记忆内核具名候选现有**两个并列**（[TencentDB Agent Memory](MEMORY-FOUNDATION-DESIGN.md) 与 [Tencent Hy Memory 2.0](HY-MEMORY-LAYERED-ANALYSIS.md)），均未选定底座、均只用只读 Adapter。有效记录按主体、用途、来源/版本/有效期和撤销检查后进入 `evidence` 并留证；记忆、画像、专家经验和模型推断均不授予权限，不由外部系统私自注入提示词。

这六层是对实际 Agent 配置中阶段、路由、规则、工具和结果结构的公开抽象，不包含任何真实业务配置、内部标识或私有提示词。S1 只实现入站消息触发；`ServiceRequest` 保留可关联触发来源的字段，暂不实现定时器、条件触达或主动发送队列。

## 执行耐久层与恢复适配边界（方向已确认，部分实现）

[pi durable](https://github.com/earendil-works/pi/tree/main/packages/durable) 的价值在于提供一组可验证的执行机制参照：原子提交线、task/phase/checkpoint、重启恢复、sleep/wake、有限重试、abort、crash-loop parking、嵌套任务/任务图、replay policy 以及只读查看和遥测。本次参考版本为 `@earendil-works/pi-durable@1.4.0`（提交 `936e5f40aede9327b9142b63506ed2b68bc6b4ac`）；它是 MIT、实验性项目，后续选型仍需重新核对版本、许可证和存储语义。Loomrise **只借鉴机制，不引入其领域模型、私有状态或默认依赖**。这些机制由拟建的 `DurableRunAdapter` 封装，不能在公共 API、客服会话、Task 合同或发布合同中形成第二套状态权威。

目标映射如下；`runtime_execution_id` 是 Adapter 内部句柄，不能被客户端当作业务幂等键、结果 ID 或权限凭据。`TaskAttempt` 与 `Run` 是两个维度：前者负责事项派发/租约，后者负责一次业务执行；两者通过内部关联连接，不把其中一方嵌入另一方的公共状态机：

```text
ServiceRequest (request_id，跨多轮/多端的业务聚合)
  └─ Run (run_id，一次 Loomrise 执行尝试，冻结 AgentVersion/上下文/策略快照)
      └─ runtime_execution_id (Adapter 私有的 task/phase/checkpoint 线)

TaskItem (一项业务义务)
  └─ TaskAttempt (attempt_id，一次派发，带 lease/generation)
       -- 可选关联 --> ServiceRequest/Run 或后台 Worker 作业
```

- 一个 `ServiceRequest` 可有多个 `Run`；一个 `TaskItem` 可有多个 `TaskAttempt`。`TaskAttempt` 负责调度占用、代次和恢复关联，不能写入业务完成或发送终态。入站请求可以没有 `TaskItem/TaskAttempt`，不为接入耐久层强制引入调度器；此时由执行服务持有运行占用代次。
- 恢复先服从 [Task 重启裁决表 §7.1](TASK-SYSTEM-DESIGN.md#71-重启恢复裁决表2026-10-21-定)：本地 `running` 的旧 `TaskAttempt` 记为 `failed/restart_interrupted`，关联 `Run` 保留中断事实；只有 Loomrise 重验并允许事项重试后，才新建尝试和 `Run`，保留原 lineage、逻辑动作幂等键及已提交结果。已持久化的等待态可沿原关联唤醒；已委派执行只有执行端可完整查询时才重新挂接。旧 worker 的占用失效后必须拒绝其新动作；无 Task 的本地 `Run` 使用相同裁决，不自动复活。
- checkpoint 复用不等于旧尝试复活：已提交且输入/版本兼容的纯计算结果可以复用；提交前崩溃的计算允许重算，不重复追加同一业务事实。模型调用、实时检索和外部读取不是纯函数，必须登记结果复用、重新调用、时效重验及预算策略；外部写入或消息发送禁止通过通用 replay 重发。
- `RunEvent` 仍是业务事实源；Adapter 的 checkpoint、内部 phase、重放和遥测只是执行证据或派生视图。Adapter 的“提交成功”只能表示其内部状态已持久化，不能直接表示 `ServiceRequest` 成功、外部写入完成或发布完成。

### Adapter 内部机制与业务边界

`DurableRunAdapter` 可以把 task/phase 状态与 checkpoint 原子提交后再对外暴露内部状态；可以挂起等待确认或外部回调、sleep/wake、在纯函数或可重放步骤上 replay、在有界预算内 retry，连续崩溃时 parking 并请求人工处理。这些状态必须通过 `RunEvent` 映射为可审计的运行事实，但不能把上游 durable task、phase、runtime task 或 task graph 直接暴露为 Loomrise 合同。

提交后可见必须覆盖 Loomrise 的事务边界，而非只覆盖 Adapter 自己的存储：请求/运行状态、幂等记录、`RunEvent` 序号与哈希链、outbox 意图及 checkpoint 引用由同一结构化存储事务关联。若 checkpoint 内容置于另一存储，先持久化不可变内容，再在上述事务中提交其校验引用；崩溃可留下未引用内容，但不能暴露无效引用或先发布未提交事件。outbox 允许重复投递，消费者按稳定事件/动作 ID 去重；不能凭 checkpoint 推断跨数据库、外部系统或文件写入具有原子性。

所有外部副作用仍走 Loomrise 的 `ToolManifest`/`HardRule`/`Outcome`：

1. **执行前**重验权限、确认版本、预算、AgentVersion 和运行占用代次；有关联 `TaskAttempt` 时另验其 revision/lease/generation。幂等键绑定具体业务操作，在同一动作跨渠道、重启与获准新尝试时保持稳定。
2. **执行后**持久化外部 `result_id` 和响应证据；超时、断连或供应商状态不明一律记为 `UNKNOWN`，先对账再决定是否重试。
3. durable retry/replay 不能提供外部副作用 exactly-once；没有幂等键、结果 ID 和对账证据时，不得因为 Adapter 恢复或重试而再次写入。
4. Adapter 的 abort/cancel 只表示内部执行停止或已确认停止；`ServiceRequest` 的业务取消、授权撤销和已发生外部动作的撤销分别留证，`cancel_requested`、`cancel_confirmed` 与 `business_action_revoked` 不得互相推断。
5. **代次只有一个生效来源**：有 `TaskAttempt` 时以它的 `lease/generation` 为准，无 Task 时以 `Run` 的运行占用代次为准；两者不会同时裁决，也不会出现"谁都能续命"的双栅栏。存在 `TaskAttempt` 时 `Run.occupancy_generation` 只作审计记录、不参与放行。新建尝试与新建 `Run` 的裁决权在 Loomrise（不是 Adapter，也不是旧执行者）。

### 选型约束与采用顺序

pi durable 的存储实现不能直接当作 Loomrise 的生产持久化承诺：其 storage 由单进程拥有且不提供跨进程锁，SQLite 默认 WAL + `synchronous=NORMAL` 是取舍而非强持久性保证，JSONL 长期运行仍可能把完整历史留在内存；IndexedDB 与 Cloudflare Durable Object 具有平台绑定。若进入多 worker 或自有云，必须由 Loomrise 提供明确的单写者/lease/generation、数据库锁、备份恢复和迁移校验，不能假定 Adapter 自带跨进程一致性。JSONL 只可作导出、夹具或短时回放格式，不是长期业务账本。

采用顺序和当前状态如下：

| 阶段 | 采用范围 | 当前状态与硬边界 |
|---|---|---|
| S2-a / R1 | 先落 `Run`、可选 `TaskAttempt` 关联及请求/事件/幂等/outbox 存储合同；定义 `DurableRunAdapter` 接口，以无副作用步骤验证事务提交可见性、重启裁决、重复提交和旧 generation，不建设完整 Task 调度。Checkpoint 可作为实现机制，是否采用由 R1 选型/设计 Gate 决定 | **部分实现（2026-10-29）**。SQLite 耐久层、loopback 配置 HTTP、共用配置服务、CLI/MCP、版本/diff/校验及恢复/outbox 测试已落；配置工作面的本机 fixture 浏览器联调已验。schema v5 增加最小 TaskItem 身份/来源/状态/revision 持久化，M-A-04 撤销恢复切片有测试证据；完整 TaskItem/TaskAttempt、主体/用途隔离、M-A-03/17/18 签核与 R1 父 Gate 仍未关闭。逐项证据见 [R1-EVIDENCE](reports/R1-EVIDENCE.md) |
| S2-a / R2 | 将 Adapter 接入最小沙盒发布、暂停/唤醒、取消确认、超时未知与对账；继续使用模拟或可回收副作用 | **部分实现（2026-10-29）**。schema v10 已持久化工具意图与物料逐版本元数据；未决操作转为 `reconciling` 并阻止自动重放。另有沙盒候选批准/入口绑定、知识摄入/撤回、物料原件版本、loopback Widget/Inbox 服务端切片。尚无结果查询/回执收敛、确认 suspend/wake 与只读运行状态服务；固定样例检查未接入，R2 Gate 未关闭。证据见 [R2-EVIDENCE](reports/R2-EVIDENCE.md)。不能把 durable task 成功当作业务成功 |
| S2-b / R3 → S2-c / R4 | 在前两批验证后再接嵌套 task/phase、后台 worker、查看/重放/parking 和真实业务工具沙盒；真实写入仍由 Loomrise 幂等与结果合同保护 | **规划**。不因引入 Adapter 改变 `ServiceRequest`、`RunEvent`、`Outcome`、权限或发布权威 |
| S3 / R5a | 首云部署时再验多进程/多 worker、备份恢复、升级迁移、存储替换和云端故障；可按需实现 SQLite/其他存储 Adapter | **未实现**。没有通过真实云恢复、迁移和升级 Gate 前，不宣称云端耐久执行或生产级恢复 |

该层的最低验收顺序是：持久提交点 crash/restart → duplicate submission → pending confirmation recovery → R1 stale-generation rejection → R2 cancellation race/late output → `UNKNOWN` 结果对账。跨进程 Worker handoff 属 R3/R4 后续验证。任何适用项未有可复现证据，均不能把 Adapter 标为已支持。

## 权威对象

| 对象 | 单一权威 | 必要状态/权限 | 删除/撤销 |
|---|---|---|---|
| `ScenarioPack` / 原始素材 | 上传者或材料权利人；本项目只托管获授权副本 | 来源、使用许可或模拟标记、有效期 | 用户删除，停止后续检索；已发版本标记失效并重验 |
| MaterialAsset / MaterialVersion（目标合同） | Loomrise 应用资产治理；文件权利归来源方 | 来源/授权/有效期/范围、原件与派生、已审简介和版本；可检索不等于可发送 | 撤回阻止新使用并使关联版本待重验；历史附件按保留策略处理，不承诺收回已下载文件 |
| `AgentSpec` / `AgentVersion` / `Release` | Loomrise | `draft → tested → approved → released → rolled_back`；发布版本不可覆盖，含专家内任务/触达蓝图及依赖快照 | 用户停用；在途事项显式迁移/暂停，审计元数据依保留策略处理 |
| `Unit`（路由与能力单元，已采纳合同） | Loomrise；随 `AgentVersion` 冻结 | 契约层：`entry_ports`（带 `requires`）、`reads`/`writes`、`exit_ports`（每个出口自带 `completion`）、`fallback`、`on_event`（作用域 `self`/`subtree`/`global`）、`max_rounds`、`load_mode`（`routed` 或 `concurrent`）；内容层：子图或原子（`tool`/`judge`/`speak`/`say`）。R1 的 `body` 为空字段 | 随版本冻结，不单独删除；被引用版本必须已冻结才可用于路由；组合环禁用、执行环须有 `max_rounds` |
| `ServiceRequest` / `Run` / `RunEvent` | Loomrise | 绑定租户、业务请求、运行尝试、渠道、版本、成本与敏感级别；`Run` 可引用 Adapter 的 `runtime_execution_id`，但不以其作为业务权威 | 租户可删除或脱敏；禁止跨租户可见 |
| TaskProposal / TaskItem / TaskAttempt（合同提案） | Loomrise 应用与调度用例 | 稳定主体、来源、策略/实例revision、权限与代次，关联实际请求/作业/结果 | 停止/取消需区分未派发、执行确认和外部撤销；回滚不复活授权 |
| 用户记忆 / 派生画像 / ContextPlan（合同提案） | Loomrise 治理与加载合同；Provider 只提供存储/提炼/检索 | 主体/用途/来源/时间/版本、候选与有效值、冲突和加载快照 | 更正/forget传播到派生视图、缓存与迟到作业；任务义务不自动删除 |
| 客服会话 / 交接记录 / 入口绑定（规划） | Loomrise 官方客服应用；外部渠道只提供收发证据 | 会话可关联多个请求；接管所有权、消息可见范围、已发布版本与环境 | 依保留策略删除/脱敏；停用入口或渠道后立即阻止新收发，保留必要审计摘要 |
| 应用发行物 / 云部署清单（规划） | Loomrise 版本规范；资源与授权由用户云账号管理 | 发行版本、资源与数据流清单、最小授权、部署验收及升级兼容 | 用户停用或卸载；持久数据保留/删除独立确认，恢复须通过校验 |
| 连接引用 / `ToolManifest` / `SkillManifest` | Loomrise 管理配置和许可；外部数据权利仍归来源方 | 分类、合同版本、授权范围、风险、工具/Skill 可用版本 | 授权撤销即禁用连接；相关版本和评测标记待重验 |
| `DecisionRequest` / `DecisionResult` | Loomrise 协议，Provider 只给建议 | 候选集版本、分数类型、绝对适配度、回退与 deadline | 可删除业务内容；保留必要的审计摘要 |
| `Case` / `EvalSet` / `EvalResult` | Loomrise（人工真值与硬规则为评测权威） | 题目版本、环境快照、期望副作用与证据 | 证据删除后，相关“已验证”结论失效 |
| `ChangeProposal` | Loomrise | `proposed → evaluated → accepted/rejected`；权限和硬规则不可自改 | 可撤回、拒绝、审计 |
| API key / IM / 线路授权 | 用户或供应商 | 后端受控保管或短期令牌，不进入前端包与 Trace | 随时撤销或删除；对应运行停止 |

## 领域合同目标与 S1 实现边界

`loomrise/contracts.py` 已实现 `ServiceRequest`、`RunEvent`、`AgentVersion`、`ScenarioPack`、`ToolManifest`、`SkillManifest` 与 `Case` 的最小合同。下列完整字段与生命周期仍是目标规范，不能从状态枚举推断对应流程已完成；独立 `AgentSpec`、`EvalSet/EvalResult`、`DecisionResult` 和领域 `ChangeProposal` 合同尚未实现。未注入 store 的 S1 执行仍使用进程内请求/幂等状态并可导出 JSONL；R1 已新增 SQLite 耐久入口与配置候选存储，配置工作面也已完成本机 fixture HTTP 联调；完整 TaskItem、恢复 Gate、真实写入撤销和生产身份仍待补齐。

- `AgentSpec@v1`：稳定 ID、场景目标、授权资料及连接引用、SOP／安全锁定段、可改段、线索字段、Skill/工具及权限引用、专家内 `task_blueprints`、模型、预算、审批策略和评测集引用。`AgentVersion` 冻结这些配置、依赖引用和合同版本，不携带凭据；任务蓝图不引用共享可变策略，动态事实/授权须保留每次重验的来源/版本证据。当前 S1 的可变 AgentVersion dataclass 尚未实现完整冻结和蓝图校验。
- `Unit@v1`（**已采纳合同；R1 落最小实现，R3 落嵌套与画布**）：契约层九字段 + 内容层（子图或原子）。路由三层：G0 确定性闸门 → G1 在**闭集**内选 → G2 兜底；连接五类：同层边、端口边、边界事件可用，组合环与裸跨层边不可；条件引用只允许已声明字段，深度 ≤2 层。它是 `RequestRouting` 与 `Skill/SOP` 的组织形态，**不是第七层**。R1 只实现清单投影所需字段与九条校验函数，嵌套/端口/边界事件的能力实现见 [RELEASE-PLAN](RELEASE-PLAN.md) §3 R3。
- `ServiceRequest@v1`：业务请求可跨多轮与多端；状态至少包含排队、运行、等待确认、取消中、成功、失败和已取消；可记录 `trigger_kind` 与 `trigger_ref`，S1 仅使用入站消息来源。AgentScope 的 `state.Task` 是运行时子任务清单，适配器内部只以 `RuntimeTask`/`PlanTask` 称呼，不进入本合同。
- `Run@v1`（目标合同）：一次 Loomrise 执行尝试，绑定 `ServiceRequest`、`AgentVersion`、上下文/工具/策略快照、预算、占用代次和生命周期；可关联 `TaskAttempt`，Adapter 句柄仅存内部映射。已持久等待可沿原 `Run` 唤醒，本地 `running` 崩溃须保留中断事实，获准重试时新建 `Run` 并保留 lineage；安全 checkpoint 的复用不能抹去旧尝试失败。外部结果未知先对账，不自动重写。
- `RunEvent@v1`：租户、Agent 版本、任务、运行、媒体会话、渠道、序号、时间、事件类型、来源引用、耗时／成本和幂等键；文字与语音至少区分生成、发送、已确认播出和未知；上下文事件还需记录作用域、选择/跳过原因、来源版本和 token 估算；Adapter checkpoint/phase 可作为执行证据引用，但业务终态仍以该账本及 `Outcome` 为准。
- `ToolManifest@v1`：稳定 ID/版本、业务语义、输入/输出 Schema、副作用级别、权限、确认、超时/预算、幂等、错误与未知结果、模拟实现、外部结果 ID 与审计字段。平台内部任务状态操作不必全部成为模型工具。
- `SkillManifest@v1`：稳定 ID/版本/状态、适用条件、目标、退出条件、可引用知识/工具 ID、失败或转人工策略、依赖 Skill、来源证据和验收案例。`SkillManifest` 是 Loomrise 的公开规范对象，UI 可简称 Skill；AgentScope 的 Markdown 目录对象只在适配器内部以 `MarkdownSkill`/`SkillDirectory` 称呼。SkillManifest 是策略配置，不是权限或任意代码执行入口；候选版本必须先经过评测和审批才能进入已发布版本。
- `Case/EvalSet/EvalResult@v1`：人工审定输入和预期状态/动作/副作用，冻结资料与模拟环境；按开发、验证、盲测分集，旧版/候选版配对批量回放，保存逐例判定与汇总。确定性硬规则独立于机评，缺证据、关键退步或违规时阻断候选发布。
- `DecisionResult@v1`：Provider／模型版本、候选集哈希、选中项或拒选、原始分数及类型、校准版本、延迟、用量与错误。
- `ChangeProposal@v1`：原版本、证据 Run／Case、结构化 diff、允许修改范围、固定评测集、实验结果、提出者与审批人；验证成功不等于上线成功。

S1 纯咨询可以无副作用返回 `success`，这只说明该轮执行结束；完整客服答疑要另外持久化生成、送达和问题解决证据。FAQ 验收关注事实、引用、范围和未解升级，不要求每个答疑生成工单或预约。

工具在执行前再次校验权限、预算、参数、确认版本与任务代次。判别器超时不得自动放行高风险动作；语音打断使待播片段和过期后台任务失效，但不能误把“未播出”记成用户已经听见。

真实外部写入不得用于离线回放。信息源与知识检索连接要分别处理业务事实和可引用材料；都须记录来源、授权、有效期和撤销，知识撤回会使关联评测与发布就绪状态待重验。外呼供应商的拨打/接通/结束/转写等回执要与业务结果分别记账，线路授权、合规和人工接管在真实接入前单独验证。

## 事件与部署路线

Loomrise 业务事件是事实源，AG-UI 只用于前端映射，OpenTelemetry 用于跨服务追踪，Langfuse 是可选观测后端。`request_id`、`run_id`、`media_session_id` 和 `trace_id` 分别编号；计费、审批、发布和副作用审计不依赖抽样 Trace。

后续主动触达由[Task 体系](TASK-SYSTEM-DESIGN.md)统一形成与协调具体事项，不作为渠道适配器里的隐藏定时任务；对外约束作为专家蓝图内 `OutreachPolicy` 随 AgentVersion 版本化，触达先候选/采用判定，再于执行前重验最新许可、去重、频次、占用和停止条件，最终创建或唤醒既有 `ServiceRequest`、写入同一事件账本。规则引擎可生成候选，Agent 可在批准范围内决策，但都不能绕过授权和确认；S1 不实现该策略、调度器或发送队列。

## 用户自有云部署与发行边界（规划未实现）

统一 Linux/容器发行提供工作台、官方客服应用、执行服务和必要 Worker；数据库、知识文件、物料原件/派生与索引保存在持久存储中，Voice Worker 和完整观测为可选组件。各云使用同一产品版本与业务合同，部署模板只映射计算、持久存储、网络、密钥服务、入口和运维资源。首轮以单租户实例验收，完整多租户隔离不是首云交付前置能力，也不能据单租户验证宣称已支持多租户。

用户在自己的云账号创建资源并管理凭据，日常配置、运行和升级不强制依赖 Loomrise 托管控制面。模板使用受限授权，长期凭据不进入浏览器、公开包、Trace 或示例文件。模型、语音、通知与检索的外部访问明确列在数据流清单中；选择用户云不自动证明数据处理完全本地化。

部署交付须覆盖：

1. **预检与创建**：展示固定发行版本、资源/权限清单及云控制台费用预览，检查地域、网络、模型连接和渠道回调；部署失败可重试收敛，清理临时资源与删除业务数据分开。
2. **就绪与安装**：完成认证、HTTPS、访问隔离、存储与 Worker 检查；在真实测试网页验证 Widget 加载、请求到达、消息返回、人工回复及业务结果，不仅检查进程存活。
3. **持久化与恢复**：会话、请求、接管占用、幂等键、结果、版本及事件跨重启保留；备份包含必要数据与版本清单，恢复后校验关联、去重与授权状态。
4. **升级与回退**：分别管理应用发行版本和 `AgentVersion`，记录数据库/索引迁移与兼容性；应用回退、数据恢复和业务配置回滚分别验收。回滚不撤销已发生的外部写入。
5. **迁移与退出**：对授权资产导出、导入并校验，凭据在目标环境重新授权；停止服务与删除持久数据分开执行，旧回调和后台任务不得继续写入。

腾讯云、阿里云是优先候选，AWS、Azure 为后续候选；入口选型、SSE/WebSocket 连接时长、后台任务、存储与 Voice Worker 兼容性必须逐云验证。S3 验收一个云的完整链路，S4 扩展多云模板；只有通过该版本真实部署、恢复和升级 Gate 的配置才能标为“已支持”。目前没有统一 Linux/容器发行或云快捷部署的运行证据。

## 自进化与技能编排边界

后续自进化采用“不可变运行证据 → 轨迹归一化 → 独立失败归因 → Candidate Skill/`ChangeProposal` → 沙箱与评测 → 审批发布”的链路。`Trajectory` 是从 `RunEvent` 派生的分析视图，不取代业务事实；经验和被拒绝提案可以长期保留，但生产 Agent 只加载已发布版本。

作者/提议者、执行 Agent 与评估/审计者应逻辑隔离。候选必须携带来源 Run/Case、父版本、结构化 diff、依赖图、评测环境、成本变化和接受/拒绝/回滚理由，并通过开发、验证、保留集、回归和迁移样本门禁。Skill 自进化不得直接修改 `HardRule`、`ToolPolicy` 的权限/副作用、`Outcome` 语义、发布权限或数据保留策略；这些只能形成待审提案。

Skill 数量增长后，Meta Skill 可以在已发布 Skill 集合中做选择、排序、并行与停止决策，但必须受预算、权限、依赖和回退约束。S1 不实现 Meta Skill 或自动发布；S2 只建立候选和评测闭环。

部署目标保留 Lite 本地试用、可选 Voice Worker、Server 用户自有云服务端版和观测扩展。S1 的本机入口与 macOS 离线恢复证据不代表 Linux 容器、公开网络或云交付已完成。完整发行与快捷部署按[验证路线](ROADMAP.md)验收；从 SQLite 迁移到 PostgreSQL 必须提供导出导入与校验。权限、工具授权、幂等、审计、备份恢复及适用的租户隔离未通过验证前，不宣称生产级或企业级能力。

## 失败与撤回

工具超时与重复提交必须幂等；语音打断和用户改需求要使相关旧结果失效；知识撤回使引用与缓存失效；物料撤回阻断新检索和发送，异步处理/索引迟到产物不得复活授权；评测证据删除后不得继续展示无来源的“已验证提升”；用户停用 IM 授权时立即停止收发。渠道可故障降级，但不得悄悄改为更高权限操作。
