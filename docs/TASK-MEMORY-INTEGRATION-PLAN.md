# Task 与用户上下文联合研究及建设计划 v0.4

更新日期：2026-10-23；研究截止：2026-10-23。状态：**统一任务体系与独立用户上下文模块方向已确认；专家内蓝图、版本绑定、初始化、受限决策与首片安排已登记；本版新增执行耐久层参照与 `DurableRunAdapter` 分期，但具体合同/参数、UI 和服务仍待实现验证**。没有改参考业务项目、S1 代码或正在开发的前端，也没有运行触达、后台周期作业或 Provider 服务。

## 1. 归并结论

Loomrise 在完整网页客服、业务执行、验收与持续改进之外，增加两项相连的产品能力：

1. **Task 体系**：统一专家内预设策略和会话 TODO，对具体服务义务进行计划、协同、执行、停止及结果核验。默认任务/触达约束属于 `AgentSpec.task_blueprints`，随专家 AgentVersion 冻结、评测和发布，不建跨专家共享策略库。事项暂称 `TaskItem`，不覆盖 `ServiceRequest` 或 SDK 的 `RuntimeTask/PlanTask`。
2. **用户上下文模块**：统一治理记忆、画像和本次上下文，共用主体、来源、用途、时间与撤销。画像派生自有效记录，任务账本掌握待办和执行事实，动态记忆不授予权限或改写配置。

两者连接成“当前事实与需求 → 任务候选 → 采用与计划 → 执行前重验 → 实际结果 → 经历与改进证据”。它们仍使用现有执行内核、六层、Case/Eval/ChangeProposal/Release 及身份权限合同。

职责、拟定字段与状态分别由[Task 设计](TASK-SYSTEM-DESIGN.md)和[用户上下文设计](USER-CONTEXT-DESIGN.md)管理。本文件只负责研究证据范围、联动、建设顺序、Gate 与交接，不再形成第三份独立对象定义。

**2026-10-16 补充**：记忆方向的**具名候选由一个增至两个并列**——新增 [Tencent Hy Memory 2.0](HY-MEMORY-LAYERED-ANALYSIS.md)（Apache-2.0，工作/代码记忆与冲突消解更强，但无鉴权多租户、发布仅 1 天、未联调），与原 [TencentDB Agent Memory](MEMORY-FOUNDATION-DESIGN.md) 并列。**本计划「先合同与故障集、再选一个 Provider 实测、不叠加多内核」的纪律不变**，Provider 对照不再重复做第二轮。跨用户经验已独立为**专家记忆**轴，见[专家-用户记忆体系](EXPERT-USER-MEMORY-SYSTEM.md)；该轴与本计划 TM 工作包**共用身份合同冻结（I1–I5）**，且 TM 首片**不依赖**专家记忆任何一期。

**2026-10-23 补充**：`@earendil-works/pi-durable@1.4.0`（MIT，实验性）作为**执行机制参照**纳入本计划，但不加入默认依赖，也不成为 Task、ServiceRequest、RunEvent 或业务结果的权威。只借鉴原子提交、checkpoint、sleep/wake、有限 retry、abort、crash-loop parking 和只读检查；`runtime_execution_id` 只在 Adapter 内部使用。R1/R2 先验证无副作用恢复、确认等待、旧 generation、未知结果对账，R3/R4 再接 Worker/parking，S3 才验证云端多进程与迁移。文件级步骤见[DurableRunAdapter 实施计划](superpowers/plans/2026-10-23-durable-run-adapter.md)。

## 2. 研究范围与证据等级

两条研究线分别核对了获授权的业务项目当前工作区、Loomrise 文档与对应源码，以及任务耐久执行/开源 Agent 记忆的官方资料。未提交的新方案也进入研究；提交日期不能代表工作区最新产品进展。业务原始材料、私有代码和话术不进入公开工件，公开设计只保留重构后的通用方法。

| 证据 | 本轮可支持的结论 | 不可据此宣称 |
|---|---|---|
| Loomrise 实际代码审读 | 已有请求/取消/上下文的最小实现及合同缺口 | 完整持久化、任务调度、跨会话记忆或前端对应后台已实现 |
| 本地业务源码与源码对照记录 | 分辨已有摘要/画像加载方法、已有来源描述与新事项协同计划 | 对记录未重新核验的跨仓代码或线上版本，不能作直接实测结论 |
| 当前业务 PRD 与过程记录 | 双来源事项协同、字段证据与冲突治理已提出；部分有本地原型/契约检查记录 | 原型、测试登记或 PRD 升级不能证明真实服务已上线 |
| 开源官方文档与历史研究 | 确认相邻机制、接口语义和需独立验证的边界 | 兼容性、许可适配、生产就绪或性能收益已在 Loomrise 验证 |

可公开迁移的方法包括：具体主体的事项实例、先判断再派发、原事项可靠阻断后再激活替代、来源/业务结果分层、用户陈述/系统事实/推断分开、字段定义与用户值分开、按当前任务读取相关事项。业务人群、周期、私有字段与消息通道实现由未来场景包/Adapter 表达。

## 3. 当前实现的真实起点

| 领域 | 当前事实 | 接入前缺口 |
|---|---|---|
| 执行服务 | [`service.py`](../loomrise/service.py)有请求、活动执行、幂等和取消，已有写入前权限/幂等/取消检查；账本主要在进程内 | 持久化、重启恢复、事项领取/调度，以及面向新增主体、触达许可、Task revision与占用代次的最终检查 |
| 执行耐久层 | `pi durable` 已完成机制级源码核对，尚无 Loomrise Adapter 或运行依赖 | `Run`/`TaskAttempt`/checkpoint/lineage、原子提交、挂起/唤醒、旧 worker/generation、parking 与 Adapter→`RunEvent` 投影；不得让内部 task/phase 变成第二套业务状态 |
| 事件合同 | [`contracts.py`](../loomrise/contracts.py)的 RunEvent 需 request/run关联 | 运行前的事项/记忆事件需扩展同一 event envelope，不能虚构运行或创建平行业务真值 |
| 上下文 | [`context.py`](../loomrise/context.py)有三段式选择、来源/版本、过期/预算记录 | 严格时间、主体/用途/撤销、动态压缩与跨会话模块 |
| 用户身份 | 请求有租户与版本，缺稳定业务用户合同 | 匿名范围、受信跨渠道身份、主体关系、合并/拆分和权限重算 |
| 记忆候选 | TencentDB Agent Memory 与 Hindsight 已有提案/历史源码研究 | Provider、存储映射、候选采用、检索/删除和效果尚未联调 |
| 外部 Agent | [AGI-01–11](AGENT-INTEGRATION-PLAN.md)已排为高优先级方向 | API/MCP/Skills/Worker 未实现；新增事项和记忆用例不得绕过原权限 |

本轮代码审读及纯内存核对确认：带时区合法 `valid_until` 已接入过期过滤；格式错误在现有 `_expired` 中返回未过期，无时区日期还可能导致比较异常。这属于记忆接入的前置修正项，不宣称本轮已修复或新增回归测试文件。因此旧记忆提案“未接线”不能作为当前状态描述。

S1 的历史 11/11 继续按[S1 报告](S1-BUILD-REPORT.md)解释，未重跑，不能作为以上新增模块验收。正在建设的第二轮本地前端按其实施报告判断，不因为本轮增加产品概念而改变原型完成度。

## 4. 主源对照与选型结论

| 主源 | 官方已描述机制 | 拟借鉴/验证范围 |
|---|---|---|
| [Temporal Workflow](https://docs.temporal.io/workflow-execution)、[Activity 幂等](https://docs.temporal.io/activity-definition)、[取消](https://docs.temporal.io/activity-execution)、[Schedule](https://docs.temporal.io/schedule) | 耐久历史、重试、取消通知及排程规则；外部副作用仍要求应用/供应商幂等 | 对照恢复、租约/旧执行者、取消确认、未知结果对账；不因采用耐久框架承诺不会双发 |
| [DBOS Workflows](https://docs.dbos.dev/python/tutorials/workflow-tutorial)、[Queues](https://docs.dbos.dev/python/tutorials/queue-tutorial)、[Steps](https://docs.dbos.dev/python/tutorials/step-tutorial) | 数据库耐久工作流、队列并发、Step 重试 | 与数据库事项服务比较；队列去重作用域/释放语义不代替长期业务去重，总期限/预算自行控制 |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Memory](https://docs.langchain.com/oss/python/concepts/memory)、[LangMem](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) | thread checkpoint、跨线程 Store、结构化 profile和collection、后台记忆处理 | 学习恢复/记忆分权、候选抽取和精确读取；不更换现有在线 runtime，不用namespace替代鉴权 |
| [Letta Memory](https://docs.letta.com/agent-sdk/memory) | 常驻与按需读取、版本化记忆 | 按当前接口有限评估；旧 V1 与现行 SDK 分开，不默认开启自编辑/自动整理 |
| [Hindsight](https://hindsight.vectorize.io/developer/api/retain)、[Recall](https://hindsight.vectorize.io/developer/api/recall) | 有来源的记录/归纳、检索与反思 | 与 TDAI 做同条件对照；反思只提出候选，权限/时间/token上限由我方二次检查 |
| [AgentScope 长期记忆](https://doc.agentscope.io/tutorial/task_long_term_memory.html)、[TencentDB Agent Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory)、[Tencent Hy Memory 2.0](https://github.com/Tencent-Hunyuan/Hy-Memory) | 记忆抽象/适配与分层资产治理；Hy Memory 另含冲突消解版本链、按 token 计的存储预算与三类记忆 | 保留邻近候选，先一个 Adapter；确认构件、许可、用户身份和数据删除，不开隐式 Proxy注入。Hy Memory 的**自动 reconcile 必须降级为候选生成器**，其适用条件须改造为可确定性求值，裁决见[Hy Memory 三层裁决](HY-MEMORY-LAYERED-ANALYSIS.md) |
| [pi durable](https://github.com/earendil-works/pi/tree/main/packages/durable) | 原子提交线、task/phase/checkpoint、sleep/wake、有限 retry、abort、crash-loop parking、任务图和只读检查 | 作为 `DurableRunAdapter` 的机制参照；单进程 storage、SQLite WAL/synchronous 取舍、JSONL 内存历史和外部副作用 exactly-once 均须独立验证；不采用其领域状态、默认依赖或跨进程安全假设 |

**本轮不选定新的调度或记忆底座。** 先冻结合同、原始事件及故障集，再比较“数据库事项服务 + Worker”与一个耐久 Provider；`pi durable` 先按无副作用 Adapter 试验，不因机制完整就直接采用。记忆比较一个初始 Adapter 与有限候选。正式构件、许可、运维与支持矩阵另验。不同时引入多个框架、多个自动记忆管线或平行事件源。

## 5. 最小联合验证切片

用原创虚构客服资料及两名明确区分的模拟用户完成：

1. 用户提出带时间/条件的服务需求，形成有源事件的 TaskProposal；同类运营策略命中时不会重复登记。
2. 明确自述可按字段规则记录，提取出的未来动作交任务服务；时间模糊、授权缺失或存在矛盾时等待澄清。
3. 有权的人或已批准规则采用 TaskItem；人工锁定安排可见，Agent 在白名单内改期/跳过并保留 revision和依据。
4. 到期只唤醒检查。读当前必要字段、Task状态、许可、占用和预算；恢复后不补发所有过期任务。
5. 在确定性沙盒执行模拟通知/只读核查，保存实际模拟结果；生成、提交、送达、解决和业务完成分别判定。
6. 用户更正或撤销后，相关画像、检索与任务进入重验；旧 Worker、旧建议及迟到抽取无法复活已失效内容。
7. 再次进入会话时只装配该主体/目的的必要事实、事项与结果，显示来源和未加载原因；另一个用户不可读取。

初次切片不接电话、不发真实客户消息，也不要求全部记忆算法已选定。随后增加真实模型和获授权渠道沙盒，按新增 Gate 逐项留下运行证据。

### 5.1 先做无需记忆 Provider 的 Task 基础子片

上面的联合切片由数个 Gate 组成，不一次性接通全部服务。先实现[专家任务首片](superpowers/plans/2026-10-16-expert-task-harness.md)：冻结专家内蓝图，以可信模拟主体/服务周期幂等初始化；内部事项按规则登记，触达只生成候选；支持受限提出/调整/请求取消、持久 revision 与有界工作集。只提供本地确定性验收，不调度实际执行、不发消息、不打开生产工具。

该子片可不等待完整记忆模块、调度器或 Harness Provider，但不能省略主体/记录权限、严格时间、版本指纹、事务幂等、运行前事件和恢复验证。Agent 所需工作集由系统装配；语义操作先在应用服务和假 Adapter 中验收，真实 host 的动态 Tool Schema 发现与权限由 AGI-02/03/08 分别联调。基础实例调整属于本片，不拖到 TM-09 才允许 Agent 合法改期。执行恢复先按 TM-14 的无副作用故障集验证，不把内存假 Adapter 的通过写成生产耐久支持。

## 6. 建设工作包与现行阶段的建议映射

下表优先级/阶段为本轮建议，不能据此把尚未完成的 S1 Gate 或真实渠道授权豁免。

| ID | 建议优先级/阶段 | 工作包与依赖 | 必要 Gate |
|---|---|---|---|
| TM-01 | P0 / S2-a 基础 | 冻结专家内 task_blueprints、TaskItem/Proposal、主体/服务周期、来源/执行 AgentVersion、字段权威与事件 envelope | 蓝图随专家版本且不共享可变策略；双来源同合同；不覆盖 ServiceRequest；无公共匿名桶或虚构 Run |
| TM-02 | P0 / S2-a 基础 | 严格时间、主体与撤销校验，原创正反例；改代码前读 S1 报告/版本钉 | 非法/无时区时间、过期、撤回、越权片段不可加载；既有回放兼容 |
| TM-03 | P0 / S2-a 基础 | 持久事项/记忆治理元数据、revision、服务周期/occurrence 幂等、事件/outbox 与撤销标记；先交付 Task 所需子集 | 重复初始化/事件/版本升级不重复造事项；重启/事务失败不丢义务或复活撤销；来源版本不变成新去重维度 |
| TM-14 | P0 / S2-a R1→R2，S2-b/c 扩展 | `DurableRunAdapter`：`ServiceRequest → Run → runtime_execution_id`，`TaskItem → TaskAttempt → Run` 关联；无副作用 checkpoint/原子提交；确认 suspend/wake；取消/旧 generation；未知结果对账；R3/R4 再加入 Worker 接管、有限 retry、crash-loop parking 与只读检查；依赖 TM-03、既有 `RunEvent`/Outcome 合同 | 崩溃恢复不重复纯步骤或副作用；确认、权限、版本、预算和 generation 恢复时重验；未知不自动重写；旧 worker 无法迟到写入；Adapter 事实可投影回 `RunEvent`，不产生第二业务真相 |
| TM-04 | P0 / S2-b 切片 | 内部 TODO、人工管理、默认蓝图初始化与候选预览、基础受限决策/工作集；依赖 TM-01/02 及 TM-03 的 Task 子集，不依赖完整记忆 | 完整人工路径；内部事项按规则采用、触达先候选；revision/人工锁定/越界/原子调整/取消留证，不产生发送或完成假象 |
| TM-05 | P0 / S2-b 切片 | 一个只读记忆 Adapter、精确字段与跨会话 ContextPlan；真实数据前须有最小撤销/删除回执与派生失效 | 主体/用途隔离、来源/版本、预算与故障降级；必需前提缺失时阻断动作；同一请求下一轮不从SDK/harness复用历史再次注入已撤销内容 |
| TM-06 | P1 / S2-b–c | 受控候选抽取与当前画像；先虚构/影子验证，真实授权数据前先具最小撤销/删除/派生失效及迟到防复活 | 用户陈述/系统事实/推断分权，更正、冲突、迟到与重复可复核 |
| TM-07 | P0 / S2-c 联合 | 持久调度、领取代次、跨事项额度/占用原子预留、原事项阻断后替代与显式版本迁移 | 两 Task 抢一次总额度、双 Worker、取消竞争和未知占额通过；版本/删蓝图不默迁义务；受理后崩溃先对账，不重复副作用 |
| TM-08 | P0 / S2-c 沙盒 | 专家版本内的受授权主动服务渠道试验；依赖渠道/会话与 TM-07 | 候选/采用/执行分离；最终许可、总频次、停止/撤销、回执及去重；无许可不能换渠道，回滚不重置计数 |
| TM-09 | P1 / S2-c | 在 TM-04 基础决策上扩展策略诊断、专家蓝图候选评测与审批 | 实例调整不改蓝图；蓝图/承诺/权限变更随 AgentVersion 经 Release，不另设共享策略发布链 |
| TM-10 | P0 / S2-c | 在TM-05/06最小遗忘Gate上扩展完整跨资产传播、身份更正、任务依赖与数据保留 | 检索/画像/缓存/复用历史/作业代次全部失效，仍有义务如实等待，不伪造取消完成 |
| TM-11 | P1 / S2-c | 受治理压缩、经验归纳与上下文优化 | 保护项保留、来源覆盖与真实输入可解释；候选改善通过独立评测，未消费blind隔离 |
| TM-12 | P0 / S3 | 用户自有云重启、备份、升级/迁移与旧Worker失效 | 不集中补发、不复活已删除记忆/已取消任务，配置回滚不撤销外部结果 |
| TM-13 | P1 / S4 独立 | 电话、其他渠道与多租户扩展 | 各渠道许可/身份/回执单验；电话与租户隔离不被前期单实例沙盒替代 |

MCP/CLI/网页的任务与记忆用例沿用 AGI 共用服务边界；后台抽取、复核和候选作业可以复用 Worker 骨架，但业务任务、治理任务和模型内计划各自保留身份、目标、预算与结果合同。扩展接口前先登记新作用域，不让外部 Agent 直接执行客户触达、写业务或发布。

AGI-02 负责最小领域工具面/按需读取合同，AGI-03 负责外部 Skill 的渐进披露，AGI-08 负责后台 Worker 的输入/能力快照与权限降级；它们复用 Task 首片的工作集/意图校验，不把在线客服的 `manage_tasks` 生产权限映射给创作角色。Adapter 不支持动态工具时使用每次运行固定最小授权集合；实际 host 兼容性未通过前不宣称已支持渐进工具发现。

## 7. 产品与 UI 采纳输入

统一事项清单命名“服务事项”，从当前专家/用户范围进入，按服务周期、来源、目的、状态、负责人、时限和阻断筛选；当前编辑版不隐式过滤其他版本未决义务。详情联结来源/执行版本、上下文依据、尝试与结果。专家版本内配置“任务与主动服务”：先看业务摘要，再展开条件/允许决策，最后查看合同/依赖；没有独立全局策略库。Inbox 投影同一义务，不能把实例改期保存成专家默认策略；发布预览展示在途影响，发布批准与迁移授权/确认分开。用户上下文从事项/Inbox/运行侧栏按需查看，不新造全量 CRM。

记忆、主动策略和 Provider 配置后置。首次手动或助手创建仍以授权资料答疑为第一成果；无需先完成画像字段库、调度器或触达设置。完整人工路径可管理获准 Task，助手故障不丢任务。真实角色和发布服务未接入时，原型必须标演示，不能用开关表现已取得权限。

后台模块设计与规划已落入[体验设计 §12](CONFIGURATION-UX-OPTIMIZATION.md#12-专家任务与-harness-的后台增量设计)、[IA §8](S2-IA-NAV.md#8-taskharness-后台增量落点)和[启动方案 CT-00–06](S2-CONSOLE-KICKOFF.md#8-taskharness-后台增量工作包)，对应 UX-17–24。保留当前四组导航、三深度和完整手动 FAQ 路径；能力注册/版本授权/实际披露三层分开，L0–L2 不增加权限。上述均为设计未实现，不修改当前 `prototypes/` 或原型计数；本地前端验收、正式 Task/记忆服务与真实 host/渠道分别过 Gate。

## 8. 联合验收指标

固定测试时钟、源事件、主体映射、字段/记忆/任务/策略版本、模型、工具/渠道模拟与预算。在候选前登记阈值，不根据结果回填。

- 任务：正确执行、正确避让/等待、错误放行、错误阻断；重复副作用、过期补发、取消未生效及未知对账。按具体任务与来源发生次数报告分母，发送量不代替服务完成。
- 记忆：精确读取、证据关联、更正/冲突/撤销、跨主体误读、迟到复活、动态字段新鲜度；抽取与当前画像分别评价。
- 上下文：保护信息保留、无效内容排除、来源覆盖、实际 token/等待时间和缓存失效；检索评分不代替使用权限。
- 任务/工具披露：当前、将到期和待对账工作集覆盖率，隐藏工具猜名/过期 Schema 的拒绝，动态工具不兼容时的最小集合降级。同样本/模型/预算对照全目录与渐进披露，纳入 Schema、结果、发现额外往返和失败成本，先测量再定收益。
- 执行耐久：checkpoint 提交可见性、恢复后的重复步骤数、确认等待恢复成功率、旧 generation 拒绝率、未知结果进入对账的比例、parking 后人工处置时延；必须按是否跨过外部副作用边界分层，不以 Adapter task 成功率替代业务成功率。
- 治理：实例调整不越界、策略候选可追溯、真值/blind不被作者污染、发布与回滚有独立证据。

未知不能按失败或成功随意合并；通知送达、人工承接、业务成功、配置采用和发布分别统计。无来源事实、权限越界、已撤销信息复活、重复外部写入为阻断问题。

## 9. 开放决定与交接

已确定：专家内配置/版本权威、无共享策略库、服务周期初始化与去重、候选/采用/执行分离、受限实例决策、显式在途迁移和渐进披露。待实施定版/验证：正式命名/合同版本、稳定用户关系模型、各场景采用与调整数值、调度优先级/前瞻窗口/补跑、保留期限、首个生产调度/记忆 Provider 及质量/时间/用量阈值。

已完成工件为本文、专题设计及产品/架构/路线/索引对应更新、首片文件级计划和本版后台增量设计。下一步后端按首片计划补 TM-01/02、TM-03/14 及 TM-04 的 Task 子集与原创故障集；前端从 CT-00 的合同投影/虚构故障集起步，后续才接正式服务。再推进 AGI host 联调、联合记忆切片和 TM-07/08，不依赖完成高级记忆引擎才开始基础合同。本轮没有代码实现或新增运行/服务验收，不改既有前端完成状态。
