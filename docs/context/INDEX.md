# Loomrise 文档总索引 v0.16

日期：2026-10-29（新增[持久可恢复执行设计评审](../reports/DURABLE-EXEC-REVIEW-2026-10-29.md)登记并同步耐久切片状态）。状态：文档导航与分类；**不新增产品决策或实现证据**。文件自身的状态、适用范围和验收记录优先于本索引摘要。新 Agent 先读 [协作指南](../../AGENTS.md)，人类入口见 [README](../../README.md)。

## 1. 先定位问题与权威文件

| 要回答的问题 | 现行依据 | 适用范围 |
|---|---|---|
| 产品做什么、为谁服务 | [PRODUCT](../PRODUCT.md) | 定位、角色、黄金路径与排除范围 |
| 产品如何组成、外部怎样接入 | [产品形态与开放接入](../PRODUCT-FORM-AND-INTEGRATION.md) | 工作台／客服应用、接入分类、前后端职责 |
| 哪个对象持有事实或权限 | [ARCHITECTURE](../ARCHITECTURE.md)、[六层配置合同](../CONFIGURATION-LAYERS.md) | 领域权威、Adapter、版本与模型外边界；包含目标规范 |
| 先做什么、何时算过关 | [ROADMAP](../ROADMAP.md) → [版本切分](../RELEASE-PLAN.md) → [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) | ROADMAP 给阶段依赖与退出 Gate；版本切分给**阶段内先做什么、每版 WP 与退出判据**；矩阵给**每条 Gate 由哪件工件证明、证据在哪** |
| 网页客服与云交付覆盖哪些能力 | [客服交付建设方案](../CUSTOMER-SERVICE-DELIVERY-PLAN.md) | 能力矩阵、S2-a/b/c 和云部署生命周期；新增能力规划未实现 |
| 图片/视频/文档如何录入、检索与发送 | [物料库与文件发送](../MATERIAL-LIBRARY-AND-DELIVERY.md) | 独立资产、后处理、简介审阅、人工/Agent 发送策略与分阶段 Gate；后端未实现 |
| 运营策略、会话 TODO 与主动服务怎样统一 | [Task 设计](../TASK-SYSTEM-DESIGN.md)、[联合计划](../TASK-MEMORY-INTEGRATION-PLAN.md) | 专家内蓝图/版本、周期初始化、受限决策/工作集、迁移与取消；方案已确定，合同/服务未实现 |
| Task/Harness 怎样影响当前配置后台 | [体验 §12](../CONFIGURATION-UX-OPTIMIZATION.md#12-专家任务与-harness-的后台增量设计)、[IA §8](../S2-IA-NAV.md#8-taskharness-后台增量落点)、[启动方案 §8](../S2-CONSOLE-KICKOFF.md#8-taskharness-后台增量工作包) | 版本内任务配置、服务事项/Inbox、能力/上下文披露、Diff/在途影响与 CT-00–06；设计已落，原型/服务未实现 |
| 策略运营如何配置专家与主动服务 | [运营人员后台配置说明](../OPERATOR-CONFIGURATION-GUIDE.md) | 按当前十个模块和 Task/Harness 新增设计组织；本地原型与规划状态明确区分 |
| 用户记忆、画像与上下文怎样治理 | [用户上下文设计](../USER-CONTEXT-DESIGN.md) | 主体、字段证据、派生视图、装配/压缩、撤销及Provider对照；模块方向确认，未实现 |
| 跨用户经验（专家记忆）怎样独立于用户记忆 | [专家-用户记忆体系](../EXPERT-USER-MEMORY-SYSTEM.md) | 三种记忆分工、五个身份合同、写入红线、版本兼容矩阵与 MEM-0–5 路线；方向与规划，未实现 |
| 语音交互架构怎么定的、全双工指标怎么进门禁 | [语音架构决策记录](../VOICE-ARCHITECTURE-DECISIONS.md) | D-01–D-05 五项已定判断与理由；指标操作表在验证计划，媒体通道协议在 `web.py:voice_ws` |
| Qwen Audio 这套 harness 能借什么、不能借什么 | [Qwen-Audio-Agent 源码研读](../QWEN-AUDIO-AGENT-HARNESS-STUDY.md) | 六组机制借鉴清单与证据分级（代码/文档/论文/演示）、不借五条、Q6–Q10；未安装未联调 |
| Hy Memory 三层能复用什么、不能用什么 | [Hy Memory 三层裁决](../HY-MEMORY-LAYERED-ANALYSIS.md) | 框架/模型/应用逐层实测与采用裁决；并列具名候选，未安装未联调 |
| 三方 Agent、MCP／Skills／CLI 怎么排期 | [Agent 接入开发计划](../AGENT-INTEGRATION-PLAN.md) | AGI-01–11 的优先级、依赖与验收；规划未实现 |
| 执行状态怎样持久化、重启如何恢复、durable 借什么 | [架构](../ARCHITECTURE.md) · [R1 证据摘要](../reports/R1-EVIDENCE.md) · [DurableRunAdapter 实施计划](../superpowers/plans/2026-10-23-durable-run-adapter.md) · [持久执行设计评审](../reports/DURABLE-EXEC-REVIEW-2026-10-29.md) | SQLite `DurableRunAdapter` 已部分实现；旧本地 running 尝试失败、待确认事实保留但不自动续跑；TaskItem 撤销与完整恢复 Gate 未通过；R3/R4 才做 Worker/parking，未引入默认依赖；评审列出 DC-01–08 缺口，属意见不构成 Gate |
| 到底已经跑通哪些功能 | [S1 交付与验收](../S1-BUILD-REPORT.md)、对应原型报告 | 运行证据与局限；不能用规划或原型代替服务验收 |
| 实际安装的是哪个构件 | [VERSION-PINS](../../VERSION-PINS.md) | 实测版本、commit、许可证与安装复现 |
| 什么材料可以公开 | [开源与私有边界](../OPEN-SOURCE-BOUNDARY.md) | 分类、脱敏、公开晋升、许可与提交红线 |

权威按主题和适用范围区分。研究结论、历史快照、实施计划和原型合同不能覆盖产品权限或阶段 Gate；文件内部只替代某一节时，不视为整份文档失效。发现冲突先核对状态与来源，未决细节登记在对应专题中。

## 2. 按任务选择阅读路径

| 当前要做的事 | 建议顺序 | 开工前确认 |
|---|---|---|
| 接手项目、确认下一步 | README → ROADMAP → S1 交付与验收 → 本索引相关专题 | S1 剩余 Gate 与 S2 本地原型分别处理 |
| 调整客服产品或部署范围 | PRODUCT → 客服交付建设方案 → ARCHITECTURE → ROADMAP | 当前范围与待实现能力；云支持需逐云实测 |
| 优化初始化、配置与 UI | [体验优化](../CONFIGURATION-UX-OPTIMIZATION.md) → [工作台 IA](../S2-IA-NAV.md) → [前端简报](../S2-FRONTEND-DESIGN-BRIEF.md) → 对应轮次的原型合同／报告 | 当前四组/三深度与旧 23 面分开；Task/Harness 增量按体验 §12、IA §8 和 CT 工作包，设计不等实现 |
| 设计或调整后台侧栏菜单 | [导航跟进验证](../CONFIG-UI-ROUND1-REPORT.md#6-两平面导航跟进2026-10-26) → [终态侧栏规范](../S2-SIDEBAR-SPEC.md) → [ElevenLabs 侧栏卷 10](../competitive/elevenlabs/10-SIDEBAR-NAV.md) → [工作台 IA](../S2-IA-NAV.md) → [线框用词表](../CONFIG-UI-PREVIEW.md) | 原型已区分工作区与专家导航；终态平台设置聚合、变更等仍属候选，不从两平面实现推断全部候选已确认 |
| 扩展客服物料与文件发送 | [物料专题](../MATERIAL-LIBRARY-AND-DELIVERY.md) → [原型物料合同](../../prototypes/console-next/MATERIALS-CONTRACT.md) → [第二轮报告](../S2-FRONTEND-ROUND2.md) → ARCHITECTURE/ROADMAP | 知识事实与文件资产分开；简介可检索不等于可发送；本地缓存/仿真与真实处理/渠道 Gate 分开 |
| 设计 Task、记忆与主动服务联动 | 联合计划 → Task 设计 → 用户上下文设计 → PRODUCT/ARCHITECTURE/ROADMAP | 蓝图随专家版本且不共享；TaskItem 不覆盖 ServiceRequest，记忆不授予触达权；首片不依赖完整记忆 |
| 实施专家内任务首片 | [首片实施计划](../superpowers/plans/2026-10-16-expert-task-harness.md) → Task 设计 → 联合计划 → S1 报告/版本钉 | 内部任务本地沙盒、幂等/恢复/越界与工作集验收；无定时执行、真实触达或已完成服务声明 |
| **实施 R0 合同对齐** | [R0 开工清单](../superpowers/plans/2026-10-23-r0-contract-alignment.md) → [版本切分](../RELEASE-PLAN.md) §3 R0 → [Gate 矩阵](../RELEASE-GATE-MATRIX.md) §1 → [硬规则](../HARD-RULE-MODEL.md) | 合同代码**可写不合主干**；先证据后合入；阈值先登记再采样；P1/P2 标"未覆盖" |
| **选 STT/TTS 与写语音通道** | [阿里云语音选型](../ALIYUN-VOICE-SELECTION.md) → R0 开工清单 WP1 | 云端阿里、北京地域；ASR 选带日期快照的，TTS 只能钉别名（风险须声明）；**音频上传通道目前不存在，要新建** |
| 实施配置后台 Task/Harness 前端增量 | [前端开发计划](../superpowers/plans/2026-10-19-console-task-harness-frontend.md) → Kickoff §8 → UX §12 → IA §8 | 仅 `console-next` 本地投影；CT-00–06、分工边界和前端验收；不替代 Task 服务、正式权限、调度、渠道或发布 Gate |
| 实现 MCP／CLI／Skills | Agent 接入开发计划 → [初始化与摄入](../INTAKE-AND-INITIALIZATION.md) → ARCHITECTURE → [参考项目](../REFERENCE-PROJECTS.md) | 同一应用服务、来源授权、revision／幂等、host 支持矩阵、无直接发布权 |
| 设计评测、候选改进与治理 | [S2 范围决策](../S2-SCOPE-DECISIONS.md) → [S2 治理设计](../S2-DESIGN.md) → [评测提案](../S2-EVAL-GATE-PROPOSAL.md) → AGI-07–10 | blind 与作者隔离；已定 Gate Reserve 和待定预算／状态机分别核对 |
| 修改执行合同、规则或依赖 | ARCHITECTURE → 六层合同 → S1 交付与验收 → VERSION-PINS → 对应代码／测试 | 先读 [硬规则提案](../HARD-RULE-MODEL.md) 的状态；目标合同不代表现有代码 |
| 研究记忆、语音或新的 Provider | 参考项目 → 对应研究／验证提案或[决策记录](../VOICE-ARCHITECTURE-DECISIONS.md) → 既有 Adapter 与阶段 Gate | 上游能力、源码核查、安装、真实联调是不同证据等级；记忆候选现为 TDAI 与 Hy Memory 两个并列，先合同后实测 |
| 查旧设计或复现旧结果 | [历史归档索引](../archive/README.md) → 原文及其后继 | 核对记录时点，不把旧阶段名或原型菜单当现行规范 |

## 3. 文档分类与职责

### A. 现行产品、架构与协作依据

| 文件 | 用途 | 状态与关联 |
|---|---|---|
| [README](../../README.md) | 产品介绍、快速运行和任务入口 | 摘要入口；详细状态回到权威文件 |
| [AGENTS](../../AGENTS.md) | 新会话启动、阅读路由、护栏与交接 | 协作规范，不保存私人会话全文 |
| [PRODUCT](../PRODUCT.md) | 用户、价值、黄金路径、产品边界 | 已确认方向；完整产品规划未实现 |
| [产品形态与开放接入](../PRODUCT-FORM-AND-INTEGRATION.md) | 交付物、接入分类、职责 | 关联 ARCHITECTURE 与客服交付计划 |
| [ARCHITECTURE](../ARCHITECTURE.md) | 领域权威、数据与适配边界 | 区分 S1 最小实现与目标合同 |
| [六层配置合同](../CONFIGURATION-LAYERS.md) | Context／Routing／Skill／Rule／Tool／Outcome | S1 部分实现，完整配置规划 |
| [ROADMAP](../ROADMAP.md) | 阶段总表、优先顺序、Gate | 不承诺日期；实现状态要有验收依据 |
| [版本切分与核心交付](../RELEASE-PLAN.md)（**v0.19**） | 阶段内的版本切分 R0 / R1 / R2 / R3 / R4 / R5a / R5b：每版入口条件、工作包（WP）、明确不做、退出判据；**三层视图**（产品能力／前端／后端）；**角色→任务→页面→证据**映射；EL 30 项、**AGI-01–11（MCP/CLI/Skills/Worker）**和执行耐久 Adapter 落版本；R2 开工授权例外与 WP5 首片状态 | **不改阶段范围与父 Gate**；用户授权只允许跳过 R1 未完成的角色签核以开工，R1 与 R2 Gate 状态仍以矩阵为准 |
| [R1 证据摘要](../reports/R1-EVIDENCE.md) | R1 后端代码、测试样本与限制：SQLite（含在线备份）、恢复/outbox、配置服务/HTTP/MCP/CLI、校验、可运行发布预检及 WP9 本机浏览器联调 | **进行中**；M-A-04 与 M-A-16 已通过；M-A-12 R1 前半可运行但完整检查仍缺 R2 证据；M-A-03/17/18 待签核，R1 父 Gate 未退出 |
| [R2 证据摘要](../reports/R2-EVIDENCE.md) | 本次 R2 开工授权例外、工作包实现状态、可复现验证与未完成项 | **实施中**；WP5 有工具意图/未知操作阻断首片，尚无对账收敛、发布、摄入、物料或 Widget/Inbox 服务；授权跳过 R1 角色复核不等于 R1 Gate 通过 |
| [版本 Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md)（**v0.7**） | 每条父 Gate → 归属版本 → 工件 → 正反例 → 通过条件 → 证据位置 → 状态；M-A-19…21 与 M-C-11…12 为耐久证据细化 | **追溯表，不是 Gate 权威**；子项不独立决定版本退出；M-A-04 与 M-A-16 已通过，M-A-12 部分证据已登记，R1 仍有父 Gate 未全绿 |
| [RELEASE-PLAN 与当前产品方向评审记录](../RELEASE-PLAN-REVIEW.md)（**v0.1**） | 产品、市场、架构、平台、交付管理与设计六个视角的综合评审；记录优势、风险优先级、知识库启发和待决事项 | 评审意见，不是产品/架构决策或实现证据；不替代 ROADMAP 与客服交付方案 Gate |
| [评审处置台账](../RELEASE-PLAN-REVIEW-RESPONSE.md)（**v0.1**） | 15 条评审意见的采纳/部分采纳/不采纳、改动落点、被修正的事实前提、5 项未关闭 | 只记处置，不重复原文；未关闭项是下轮评审入口 |
| [持久可恢复执行设计评审](../reports/DURABLE-EXEC-REVIEW-2026-10-29.md)（**v0.1**） | 对照 Durable Agent 四项能力的现状盘查、四条方向裁定、DC-01–08 缺口（意图先于执行/确认持久化/resume 驱动/阶段边界/replay 策略）、不照搬清单与 R2 增项建议 | **评审意见**；不改 Gate、阶段范围或实现状态；建议落点只引用既有 M-A-* 与 R2-WP5 |
| [开源与私有边界](../OPEN-SOURCE-BOUNDARY.md) | 分类、公开晋升、许可与红线 | 核心 Apache-2.0；[LICENSE](../../LICENSE)、[NOTICE](../../NOTICE)为许可工件 |
| [命名决策](../NAMING.md) | 项目名和与上游同名对象的裁决 | 已确认；合同名称不要按页面旧称改写 |
| [参考项目与采用边界](../REFERENCE-PROJECTS.md) | 各类上游的候选角色及采用条件 | 技术选择入口；参照不代表已支持 |

### B. 当前建设计划与专题设计

| 文件 | 负责内容 | 状态与下游 |
|---|---|---|
| [客服交付建设方案](../CUSTOMER-SERVICE-DELIVERY-PLAN.md) | Knocket 客服覆盖矩阵、增强能力、云部署生命周期 | 方向／范围已确认，新增能力规划；约束 S2 与 S3/S4 |
| [物料库与文件发送](../MATERIAL-LIBRARY-AND-DELIVERY.md) | 独立图片/视频/文档资产、真实后处理目标、已审简介检索、人工与 Agent 自动发送 | 方向已确认；本地前端扩展按第二轮报告验收，真实服务未实现；约束 S2-a/b/c 和 S3 恢复 |
| [Agent 接入开发计划](../AGENT-INTEGRATION-PLAN.md) | 共用 API、MCP／Skills、可选 CLI、后台 Worker 与最小工具/渐进披露 | 高优先级 AGI-01–11 已登记；任务/Skill/Schema 快照、角色隔离与 host 降级待验证 |
| [初始化与摄入](../INTAKE-AND-INITIALIZATION.md) | 来源、网页／本地摄入、受限外部创建 | 方向已确认；接口命名、参数与部分措辞待定 |
| [配置后台体验优化](../CONFIGURATION-UX-OPTIMIZATION.md) | 可选助手、完整手动路径、渐进式配置；§12 专家任务/Harness 后台设计与 UX-17–24 | UX-01–16 按原提案/逐轮采用核对；新增模块交互已落方案、未实现，不新建策略库 |
| [运营人员后台配置说明](../OPERATOR-CONFIGURATION-GUIDE.md) | 面向策略运营的专家模块、主动服务配置和运行治理概览 | 依据现行方案编写；新增 Task/Harness 工作面及正式后台服务仍未实现 |
| [运营视角配置需求清单](../OPERATOR-CONFIG-REQUIREMENTS.md) | 运营（Voice of Customer）视角的 22 条配置需求、优先级、逐条验收口径与 OAT-1 验收脚本；证据指向 `console-next` 实际工件 | **需求提案，待 PM 取舍**；不改 PRODUCT 定位、ROADMAP Gate 与六层合同；R-22 落地后 OPERATOR-CONFIGURATION-GUIDE 应改写为四步流水线说明 |
| [配置重构与编排画布产研需求](../PRODUCT-CONFIG-OPTIMIZATION.md) | 产品视角对 22 条运营需求与 8 条领域专家需求的逐条裁决（采纳/部分/改判）、专家配置项重梳为「四资产 + 一装配」、编排画布定为一等域（守卫层/证据层/运行叠加）、V1/V2 两版校准计划与否决条件 | **提案，待产品确认**；画布合同沿用 ROUTE-GRAPH v1.0 不改；不改 ROADMAP 阶段；R1/R2 细项替换前需确认 |
| [配置后台新结构线框预览](../CONFIG-UI-PREVIEW.md) | v0.2：易用性复盘（13 个问题与坚持项）、界面用词表（内部词 → 业务词）、扁平导航（首页/知识库/红线/业务办理/对话流程/测试/上线）、11 页 + 右侧面板（试一试/依据）+ 待处理队列的 ASCII 线框、上手度量 | **线框预览，非视觉定稿**；用词表只约束界面文案，不改合同术语；"专家"一词保持不变（2026-10-26 产品确认） |
| [配置化优化需求 · 新布局对现状差距](../CONFIG-GAP-REQUIREMENTS.md) | 对照 `prototypes/console-next/` 与线框 v0.2 逐页盘点差距；23 条需求（CG-01…CG-23）、验收口径、落版建议（V1-a…V1-d）、风险与明确不做 | **需求提案，待评审排期**；实施前按批次拆工作包；V1-a 不依赖后端，可先做；依赖后端的先在本地模式完成 |
| [配置化前端改版轮次 1 交付报告](../CONFIG-UI-ROUND1-REPORT.md) | 本地配置 UI 改版范围、测试/浏览器证据与后续阻塞；第 6 节单列两平面导航与展开收起跟进 | 本地原型已验证；首轮 200/200、导航 209/209、展开收起 212/212 分批记录，桌面/手机交互通过；不改变 S2 正式服务/Gate 状态 |
| [终态侧边栏菜单设计规范](../S2-SIDEBAR-SPEC.md) | 两平面（工作区 3 项 / 专家 8 项 + 底部设置）的菜单候选、出现条件、角标与队列、⌘K 边界、命名与分期；含**与 ElevenLabs 的四类裁决**及与 IA 的 8 处差异处置 | **设计规范候选稿 v0.1**；原型已有工作区资源直达与专家 7+专家设置两平面，平台设置聚合/变更/任务等仍未实现；本地事实见导航跟进报告 |
| [前后端进度对账与迭代计划](../FRONTEND-BACKEND-ITERATION-PLAN.md) | 当前配置原型与服务端状态对账；记录两平面/配置页面的数据边界、S2-a/b/c 与 R1/R2/R3/R4/R5a/R5b 的候选映射、I0–I5 后续迭代及跨文档差异 | **R1 实现/联调进度对账 + 迭代提案 v0.8**；不改 Gate/合同；R1 配置主链与 WP9 本机浏览器联调已验，M-A-04 与父 Gate 仍未通过；终态侧栏仍为候选 |
| [第二轮后台 UI 走查与优化计划](../CONSOLE-UI-WALKTHROUGH-PLAN.md) | `console-next` 全后台信息优先级、集合状态、四组导航确认与本轮交接 | 本轮取舍已确认、UI已实现；验证与剩余Gate见第二轮报告第11节，真实S2服务未实现 |
| [S2 范围决策](../S2-SCOPE-DECISIONS.md) | 人机协同、提名／真值、审批与改进范围 | 已确认方向，完整治理归 S2-c；不是执行完成报告 |
| [S2 治理设计](../S2-DESIGN.md) | Case、Eval、ChangeProposal、权限与流程 | 设计草案；已吸收 Gate Reserve，完整流程未实现 |
| [S2 工作台 IA](../S2-IA-NAV.md) | 对象归属/页面；§8 为当前四组/三深度上 Task/Harness 增量落点 | 当前原型与新增规划分开；旧六域/23 面、先版本列表/三 tab 不作为本轮实施命令 |
| [S2 界面约束](../S2-UI-DESIGN.md) | 证据分离、状态、内容维护；§9 补事项/披露/迁移约束 | 保留现行治理；新增规划未实现，原 §2 导航已归档 |
| [配置后台启动方案](../S2-CONSOLE-KICKOFF.md) | 旧 K0/D3/K1 缺口；§8 为 CT-00–06 投影/蓝图/事项/证据/Diff 与联调交接 | 新工作包全待实施，沿用原生模块；CT/B/T 编号均不是新产品阶段，前端不关闭 TM/AGI Gate |
| [前端设计启动简报](../S2-FRONTEND-DESIGN-BRIEF.md) | 当前基线、关系与 §11 Task/Harness 增量设计输入 | 旧 23 面仅职责对照；新工作面设计不等于页面或服务已交付 |
| [编排视图前端方案](../S2-ORCHESTRATION-UI.md)（**提案 v0.1**） | 「流程」tab 三投影（图/清单/规则）的画布实现：技术选型 `@xyflow/react` v12（含四条理由与不选 X6/LogicFlow 的原因）、四视图态、端口与边界事件的画法、**九条**校验的界面落点、视图模型与组件树、无障碍；**RG-F1–RG-F12 已全部定案** | **未实施**；不新增二级页（修正 RG-1 的「17→18」）；依赖须登记 `VERSION-PINS` |
| [硬规则表达模型](../HARD-RULE-MODEL.md) | 条件算子、裁决、冲突与字段形状；**v0.2 已裁决**：裁决/授权/路由去向/事项状态四层分开、条件深度 2 层（含边条件）、`state` 四窗口（`cycle` 默认） | 六问已闭合（§9），D3 与 K1 阻塞解除；**代码已同步**（2026-10-23，`contracts.py` 的 `Verdict` 四值、`AuthorizationResult`、`StateWindow`、`validation.py` 第九条） |
| [S2 评测门禁提案](../S2-EVAL-GATE-PROPOSAL.md) | Gate Reserve、配对评估、预算与状态机 | §2 已确认且并入治理设计；§3–§5 仍待确认 |
| [Task 体系设计](../TASK-SYSTEM-DESIGN.md) | 专家内版本蓝图、默认初始化、双来源事项、受限决策、迁移与工作集 | 方案已确定；§9 后台设计后继已登记，UI/服务未实现；ServiceRequest 不变，无共享策略库 |
| [用户上下文设计](../USER-CONTEXT-DESIGN.md) | 记忆/画像/上下文模块职责及治理、身份、检索/压缩、遗忘 | 模块方向已确认；接口/字段/Provider提案未实现，六层不变 |
| [Task 与上下文联合计划](../TASK-MEMORY-INTEGRATION-PLAN.md) | 两条研究归并、TM-01–14、DurableRunAdapter 分期、首片/AGI依赖，§7 后台 CT 采纳入口 | 方案/顺序与 UI 设计已登记；旧 running Attempt 失败/新尝试规则不变；服务/新增 UI 未实现，不改变原型和 S1 验收状态 |
| [专家任务与 Harness 首片实施计划](../superpowers/plans/2026-10-16-expert-task-harness.md) | 蓝图冻结、初始化、内部任务账本/意图、工作集与语义工具假 Adapter | 文件级待执行计划；只验内部沙盒，不承诺已支持调度/发送/生产持久化 |
| [R0 合同对齐开工清单](../superpowers/plans/2026-10-23-r0-contract-alignment.md) | 预检、证据两层约定、语音阈值登记表模板、WP0–WP6（媒体/指标/SSE/合同落地/合入回归/签核）与 DoD | 执行清单，未开工；合同代码不合主干；不建配置器、不动原型；不替代 Gate 权威 |
| [DurableRunAdapter 实施计划](../superpowers/plans/2026-10-23-durable-run-adapter.md) | R1/R2 的 `Run`、可选 Task 关联、事务持久化/恢复裁决/挂起/未知对账；Worker 接管/parking 留 R3/R4 | 实现部分持久化与恢复；完整故障矩阵、TaskItem 调度、R2 唤醒/对账、R3/R4 Worker 仍待做；矩阵细化项不新增 Gate，不引入 `pi-durable` 默认依赖，不宣称云端或外部 exactly-once |
| [阿里云端到端语音选型](../ALIYUN-VOICE-SELECTION.md) | 流式 ASR/TTS 候选、锁版本策略（日期快照 vs 别名）、接口形状、与现有链路的差距、待核项 | **调研与候选登记，未跑通**；key 未到位；SDK 兼容性待验；不替代 `M-S1-09` |
| [配置后台 Task/Harness 前端增量开发计划](../superpowers/plans/2026-10-19-console-task-harness-frontend.md) | `console-next` 的版本内蓝图、服务事项/Inbox、渐进披露、情景预览与 Diff | 仅前端执行计划，CT-00–06 全待开始；不连接正式 API/调度/渠道，不改变服务 Gate |
| [用户记忆内核提案](../MEMORY-FOUNDATION-DESIGN.md) | TDAI的历史核查与候选Adapter；模块职责转看用户上下文设计 | 供应商选型/映射待确认，未联调；“采用”是原推荐，不等于已批准或双内核选定 |
| [Hy Memory 三层裁决](../HY-MEMORY-LAYERED-ANALYSIS.md) | 腾讯 Hy Memory 2.0 框架/模型/应用三层的源码与论文实测、十个可抄机制、采用与排除裁决 | 与 TDAI 并列的第二个具名候选；发布 1 天、极新；不采用其权重与自动 reconcile；未安装未联调 |
| [专家-用户记忆体系](../EXPERT-USER-MEMORY-SYSTEM.md) | 业务用户记忆/专家记忆/个人记忆分工、`Experience`最小字段、写入红线W1–W3、**C6 证据样本不得自证**、版本兼容矩阵、MEM-0–5；**§10 已决**：`subject_id` 由业务映射提供 + `ephemeral` 兜底、不做身份合并 | 方向与规划；不改六层、不改§7.4无例外；字段与接口为提案，未实现；**I1 阻塞已解除** |
| [实时语音协同验证计划](../VOICE-COORDINATION-VALIDATION.md) | 媒体前台／业务后台的可选对照；全双工指标登记口径（2026-10-21） | 待锁版本、待实测；不新增业务内核或电话承诺 |
| [语音架构决策记录](../VOICE-ARCHITECTURE-DECISIONS.md) | **D-01–D-05**：全双工落点（harness 工程式）、指标按业务语义拆解与阈值纪律、播报窗口与播出回执、委派首次验收阶段、**媒体通道与业务通道分离（`final` 只是句尾）** | 五项已定；Q1–Q10 已结清；不复制指标表，操作细节在验证计划 |
| [Qwen-Audio-Agent 源码研读](../QWEN-AUDIO-AGENT-HARNESS-STUDY.md) | 技术报告 + 项目主页 + main `ca2e7e2` 源码：六组机制借鉴、不借五条、对 D-01/D-02/D1 的增量 | 研究提案；证据分四级；未安装、未联调、未核许可证兼容 |

### C. 实现证据与原型轮次

| 文件／工件 | 用途 | 证据边界 |
|---|---|---|
| [S1 交付与验收](../S1-BUILD-REPORT.md) | 代码交付物、逐项 Gate 与运行证据 | 真实模型与确定性回放分别留证；音频与真实模型 SSE 等仍缺 |
| [VERSION-PINS](../../VERSION-PINS.md) | 实际构件、依赖与安装恢复 | 安装／恢复证据不替代媒体或生产验收 |
| [S1 适配验证快照](../S1-VALIDATION-AND-ADAPTATION.md) | 源码／安装级检查、版本选择与适配理由 | 2026-09-27 的验证时点；后续真实模型证据读 S1 交付报告 |
| [首轮原型规范](../S2-PROTOTYPE-SPEC.md) · [页面索引](../../prototypes/s2-console/index.html) | 15 页本地工作台的规格与复现入口 | 旧轮次保留对照；不含真实 S2 后台 |
| [首轮 UI 走查报告](../UI-WALKTHROUGH-REPORT.md) | S1 页面与首轮原型的逐页检查 | 样本／视窗／断言限于原报告，不移用到第二轮 |
| [第二轮前端实施计划](../superpowers/plans/2026-10-14-console-round2.md) | 体验需求到实现任务和交付检查 | 本地前端任务；完成度读实际工件及对应验收报告，不靠本索引推断 |
| [访客物料试用实施计划](../superpowers/plans/2026-10-14-visitor-material-preview.md) | 试用台/Widget独立会话、实际原件与本地收件/查看、异步重验 | 本地前端扩展，完成证据见第二轮报告第8节；真实Agent/渠道未实现 |
| [知识工作区优化计划](../superpowers/plans/2026-10-14-knowledge-workspace-ux.md) | 知识/物料列表、详情、编辑互斥，内容密度与高级配置渐进展开 | 本地前端已实现；92项Node与9项新增浏览器流程证据见第二轮报告第10节，真实服务未接入 |
| [后台 UI 布局优化实施计划](../superpowers/plans/2026-10-15-console-ui-optimization.md) | 四组导航、专家列表下概览/配置二级归属、缺口聚焦、四集合工作面、知识计数与中文术语；并行分工与验收交接 | 仅本地原型；实际验证与未验辅助技术Gate见第二轮报告第11节 |
| [第二轮前端交付与评审](../S2-FRONTEND-ROUND2.md) | 人工配置、协助预留、物料库与访客试用/Widget扩展、后端交接 | 原基础批次已验证；物料扩展及测试以对应节为准，原始计数不能移作新增能力证据；仅本地前端，真实 S2 服务未实现 |
| [第二轮后台 UI 走查与优化计划](../CONSOLE-UI-WALKTHROUGH-PLAN.md) | 原走查依据、确认决策及本轮优化结果入口 | 原走查分数不外推为优化后测量；本轮重新执行的证据见报告第11节 |
| [第二轮前端合同](../../prototypes/console-next/FRONTEND-CONTRACT.md) | 本地状态、视图接口、actions 和边界 | 原型协作合同，不能直接充当正式服务 API |
| [物料前端合同](../../prototypes/console-next/MATERIALS-CONTRACT.md) | 独立本地资产状态、缓存/视图/发送接口与异步重验 | 原型协作合同；IndexedDB 原件与模拟处理/自动发送分别管理，不是正式服务 API |
| [第二轮视觉设计](../../prototypes/console-next/DESIGN.md) · [原型入口](../../prototypes/console-next/index.html) | 本地工作台的视觉、导航与操作面 | 真实模型、资料处理、渠道、权限、审批／部署服务仍待建设；集成验证看该轮报告 |

### D. 研究参照与历史材料

| 文件 | 可用于什么 | 不能推出什么 |
|---|---|---|
| [Agent 配置后台对比](../AGENT-CONFIGURATION-COMPARISON.md) | 指定上游快照的配置对象与产品体验参照 | 不保证最新商业版能力或已在本项目接入 |
| [ElevenLabs 配置方案与能力边界](../ELEVENLABS-AGENTS-ANALYSIS.md) | 托管式平台（ElevenAgents）的配置分层、工具执行时序、版本/分支/评测机制与能力边界；可借 30 项、不借 16 项、EL-1…EL-18 待确认；v0.3 含**后台逐页核验状态表**（§12.8），v0.4 §13 深挖 Workflow，**v0.5 扒齐 368 篇官方文档并回改三处过强表述（§0.4）** | 闭源托管，**无源码、未调用 API、无真实会话**；界面级（B+）与 API schema（A-）为主；不构成采用承诺或时延/并发/中文效果结论 |
| [路由与能力单元](../ROUTE-GRAPH-AND-UNITS.md)（**已采纳合同 v1.0**） | 融合形态：**单元＝契约层＋内容层，收起是节点、展开是图**（可分形嵌套）；**五类连接**——跨层只走端口（跳步）或边界事件（异常/挂断/超时），裸跨层边禁；模型在闭集内选（margin + 可校验依据）；**九条**保存前校验（接口诚实 + 连接合法 + 条件深度 ≤2）；L0 逐层路由表摘要 + 虾宝五类知识档位映射；三类测试粒度不对称 | **已采纳**（2026-10-22）：R1 落最小实现（清单投影九字段 + `body` 空字段），嵌套/端口/边界事件/画布在 R3；不新增第七层 |
| [ElevenLabs 专题卷](../competitive/elevenlabs/00-INDEX.md)（10 卷） | 上面那份总纲的**事实层**：配置对象、编排、运行时与语音、知识与记忆、质量体系、渠道与电话、治理与合规、**88 项能力对照矩阵**、**CLI 与 MCP 的定位与落点**、**两级侧栏与 ⌘K 面板排布** | 只承载事实与原文位置，**不产生结论**；判断一律回总纲 §8 / §9 与[终态侧栏规范 §2](../S2-SIDEBAR-SPEC.md#2-与-elevenlabs-的四类裁决) |
| [Delight.ai 专题卷](../competitive/delight/00-INDEX.md)（1 卷） | 企业客服/销售竞品的**配置模型与实现**：工作区共享资产 + 资产级版本 + Dev/Prod 选择性部署；`Actionbook` 作为一等 SOP 资产的形态、三视图与执行语义；测试集来源、outcome 断言、ZTI 四级自治；与六层逐层对照、可借 7 项 / 不借 5 项 | 官方文档站私有，**无 A-/B+**，上限 B+C；`Actionbook = 结构化提示` 为交叉推断（B-）非原文；不能据此推断其工具约束、发布门禁强度或中文效果 |
| [竞争格局与差异化定位](../COMPETITIVE-LANDSCAPE.md) | ElevenLabs / Delight / Knocket（腾讯云 TRTC）三家同轴对比：定位光谱、五点相似、六点差别、四家对比大表、**四个可守差异（可验收 / 可拥有 / 任务账本 / 记忆治理）+ 三个必须补的短板（SOP 可维护性 / 测试语料来源 / 上线速度）** | 跨列只比「形态是否存在」不比「实现质量」；§7 对外话术为**内部候选**，未经批准不得外发；不改 PRODUCT 定位与 ROADMAP 阶段 |
| [Hindsight 迭代机制分析](../HINDSIGHT-ITERATION-ANALYSIS.md) | 来源记忆、经验沉淀与改进假设的机制研究 | 已核源码不等于已联调、已选替代内核或效果提升 |
| [历史归档索引](../archive/README.md) | 被替代设计的原文、时点与后继关系 | 归档内容不得作为新实现默认规格 |

## 4. 方案之间如何关联

- **产品到交付**：PRODUCT 定义用户与价值 → 客服交付计划列能力 → ARCHITECTURE 定义事实与职责 → ROADMAP 安排阶段 Gate。
- **配置到初始化**：六层合同确定对象职责 → 初始化与摄入规定来源 → 体验优化规定低门槛与详细视图 → IA／前端合同展开页面。助手和手动路径都回到同一版本。
- **第三方 Agent 到改进**：Agent 接入计划的 AGI-01–06 先建立共用服务与受限创建 → AGI-07–08 诊断／Worker → AGI-09–10 候选与授权治理 → S2 设计／评测规则决定能否采用与发布。
- **任务到用户上下文**：Task 设计确定专家蓝图/版本、初始化、受限决策及义务/执行分权 → 首片先验内部账本/工作集 → 用户上下文设计提供有效事实/画像 → 联合计划对齐 TM/AGI 与阶段 Gate；Provider 不持业务权威，渐进披露不授予权限。
- **任务到配置后台**：Task/AGI 合同 → 体验 §12 的版本内规则/用户实例/证据分面 → IA §8 的归属/命名 → 简报 §11 与启动方案 CT-00–06 → 后续原型/正式服务分别验收；不把新增设计倒写为第二轮已实现。
- **证据到结论**：S1 交付报告与各轮 UI 报告记录实际测试 → ROADMAP 更新可公开进度 → Gate 追溯矩阵登记逐条工件与证据位置。上游研究与本地原型不能替代真实服务证据。
- **计划到验收**：RELEASE-PLAN 的每版 WP → 矩阵行号 → 工件与证据位置 → 处置台账的未关闭项。三者任一漂移，先改权威 Gate 再改下游。
- **部署到迁移**：客服交付计划的部署生命周期 → ARCHITECTURE 的发行物与场景包边界 → ROADMAP S3 首云、S4 扩云；AGI-11 仅增加可选 Worker 交付。

## 5. 已替代与容易混淆的内容

| 旧内容／误读 | 当前入口 | 保留与适用范围 |
|---|---|---|
| S2-UI-DESIGN 原 §2 的旅程分区导航 | S2-IA-NAV 的对象域导航 | 原文移入 [历史快照](../archive/design/s2-ui-navigation-v0.2.md)；原文件 §3–§7 的界面约束保留 |
| 旧工作台设计的 S2-a／S2-b 批次名 | ROADMAP、客服交付计划 | 旧表只用于还原设计批次，不覆盖现行 S2-a/b/c 产品阶段 |
| RELEASE-PLAN v0.1 的"五组工件齐全即 S2-a 退出" | [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) §2 | 该表述无法逐条核验，已由 18 行逐行签核替代；旧表述只作历史对照 |
| ROUTE-GRAPH 的"提案，未采纳"状态 | 同文件 v1.0 | 2026-10-22 已采纳为正式合同（R1 最小实现 / R3 嵌套与画布），旧状态不再适用 |
| 工作台 IA 的 6 域／23 面 = 完整产品全部 UI | 客服交付计划 + 对应原型合同／新增规格 | 第二轮原型有客服应用／知识等展示；该轮本地菜单不自动成为整体 IA 的已确认定稿 |
| 侧栏"交付与验证／治理／平台"三组 6 域 = 现行菜单形态 | [终态侧栏规范](../S2-SIDEBAR-SPEC.md) §3 | 6 域保留为对象归属，菜单改为两平面（工作区 3 项 / 专家 8 项 + 底部设置）；分组仅在主组 ≥10 项时启用；§13 的 8 处差异待确认 |
| 旧先版本列表/三 tab/独立频控仍是本轮命令，或全池可召回等于全量注入 | IA §8、体验 §12、简报 §5/11、启动方案 §8 | 当前选专家先概览、三深度同配置；频控在蓝图单点定义；候选可检索不等于本轮可见，能力按任务披露，旧计数只作对照 |
| 新 Task 设计 = 配置/原型已支持调度或一次发布迁移所有用户 | UX-17–24、CT-00–06、TM/AGI Gate | 设计已落、代码未改；保存不初始化，发布不默迁，模拟/真实与本地/服务验收分开 |
| 旧 IA 中“物料不进召回”或物料名称仍待定 | 物料专题 + IA 知识域/命名项 35 | 已更新为「物料库」；经审简介/标签可检索定位资产，发送仍重验，不自动把摘要升级为知识事实 |
| 首轮 15 页的走查结论 = 第二轮也通过 | 对应轮次的实施计划、测试与报告 | 两套目录并存；以报告范围区分，不合并计数 |
| 2026-09-27 适配快照的“真实模型未验” = 当前仍未跑过 | S1-BUILD-REPORT 的后续六路径记录 | 保留旧证据时点；网页音频和真实模型 SSE 仍分别未闭 Gate |
| 评测提案整篇已批准 | S2-DESIGN + 评测提案逐节状态 | §2 已吸收，其余建议仍有待确认细节 |
| TDAI旧提案写“采用”或SDK记忆模块 = 已决定/已实现用户记忆 | USER-CONTEXT-DESIGN + MEMORY-FOUNDATION-DESIGN逐节状态 | Provider仍候选；稳定主体、用途/时间/撤销和实际联调先过Gate |
| Task体系 = 原ServiceRequest改回裸Task或上游待办类 | NAMING + TASK-SYSTEM-DESIGN | 产品可称Task体系，事项合同暂称TaskItem；请求与RuntimeTask/PlanTask分离 |
| 高优先级接入／前端演示 = MCP、后台 Worker、云服务已支持 | AGI 计划 + 实际服务联调证据 | 当前为计划或本地原型，不增加兼容性声明 |
| ElevenLabs 有分支／灰度／测试／护栏 = 等价于 Loomrise 的评测与审批门禁 | [ElevenLabs 分析](../ELEVENLABS-AGENTS-ANALYSIS.md) §3.3 / §4.4 / §5.1 · [治理卷](../competitive/elevenlabs/07-GOVERNANCE-COMPLIANCE.md) §3 | 它有版本与灰度机制，**有提案评审装置但不是强制门**（管理员可绕过，且合并不要求测试通过）；护栏是自然语言 + 轻量模型的概率判定且不校验工具参数，不能替代模型外确定性裁决 |

## 6. 新资料落点、归档与会话接力

| 新增资料类型 | 放在哪里 | 同步什么 |
|---|---|---|
| 产品／架构／阶段决策 | 对应现行权威文件 | 受影响正文、README 摘要与本索引 |
| 单项专题设计或工作包 | 优先扩充既有专题；确需独立时用 `docs/` | 状态、依赖、验收、上游／下游链接与索引 |
| 某轮实施计划 | `docs/superpowers/plans/` 或既有任务计划 | 任务、已完成工件、剩余与阻塞、验证和下一步 |
| 实际测试或交付结果 | 对应建设报告／该轮验收报告 | 工件、环境、命令、证据、限制；必要时更新 ROADMAP |
| 原型视图／本地状态规范 | 对应 `prototypes/` 轮次 | 链回产品／体验需求；不得冒充服务合同 |
| 被明确替代的方案 | `docs/archive/`，按归档说明 | 原入口指针、时点、替代范围与后继；修复入链 |

维护时新增文件要登记用途和状态，替代文件要登记后继与范围，验证只写实际执行结果。会话结束将未完成工作写回其实施文件；新会话沿本索引找到计划，再检查工作区与真实工件。无需把完整聊天存成另一份产品方案。
