# Agent Autoloop 的运行时闭环与 Loomrise 自迭代设计的对照 v0.1

> 状态：**上游源码与文档已核；应用建议为研究提案，未安装、未运行、未联调、未接入 Loomrise**。2026-11-04。
> 核对版本：[KKKKhazix/agent-autoloop `ae305ac`](https://github.com/KKKKhazix/agent-autoloop/tree/ae305acfb868f721e4e6885eb836a535dd62c3c4)（2026-11-04 18:20 +0800，`main` 浅克隆于本机临时目录，未入库），`LICENSE` 为 MIT。
> 本次只读代码与文档（`kernel/` 11 文件约 1 650 行、`protocol/`、`worker/`、`plugins/`、`docs/protocol.md`、`SECURITY.md` 相关章节、`AGENTS.md`、`skills/agent-autoloop/SKILL.md`、`examples/recipes/`、`sim/`），**未安装、未跑测试、未实测效果与性能**。文中所有上游结论标注到文件与常量；所有 Loomrise 结论标注到现有文档，均为设计或提案状态。

## 1. 结论与边界

**先纠正一个前提：这个项目里没有"自迭代算法"，也没有任何"让 Agent 自己变好"的机制。** 全仓没有自省、复盘、经验归纳、策略搜索这类实现；`kernel/evolve.ts` 的 `evolve` 是事件溯源的投影重建函数，与"进化"只共用了一个词。它真正做的事是：**让命令行 Agent 在无人值守时长周期接活、卡住会停下来问人、问完能接着干**。

它对 Loomrise 的借鉴价值因此不在"怎么生成改进候选"——那一段 Loomrise 的 [S2 治理设计](S2-DESIGN.md) 已经比它完整得多（真值、配对回放、Gate Reserve、审批矩阵、回滚）。价值在另一段：**改进闭环一旦真的长期跑起来，靠什么不失控、不丢证据、不重复花钱。** 这一段 Loomrise 目前是空的：

| 缺口 | 现状 |
|---|---|
| 改进流程跨天等待人的挂起与恢复 | `ImprovementRun` 只有 `running/proposed/exhausted/blocked/closed`，没有"等人"这个态（[评测提案 §4](S2-EVAL-GATE-PROPOSAL.md)） |
| 迭代自己触发自己的上限 | 只有轮数预算 `budget`，没有"链条深度"这一维 |
| 改进期间的配置变更与在途运行的关系 | 未定义；`AgentVersion` 有版本，但"改版本不换在途"没有写成合同 |
| 保存失败、评测配置损坏时的降级 | 未定义；`mutable` 段即时生效后才发现坏掉，只有"异步补回放 + 退步回滚"一条兜底 |
| 回放/诊断中断后的结果归属 | `unknown` 语义在 R2 待办里，尚未成为状态 |
| 一轮改进花了多少钱、归因到哪条规则/哪个 Agent | `EvalResult` 有成本对比，但运行侧没有逐轮记账与归因 |

结论分三级，避免夸大：

1. **直接借语义（推荐）**：挂起零消耗、跳数熔断、领取时冻结配置、写错继续跑、未知态、逐轮记账。六条都能落进 `ImprovementRun` 与 `GovernanceJob` 的字段与状态，不新增产品阶段、不改 Gate。
2. **借形态、不借实现**：回执合同、"决定账本"（`decisions`/`declined`）、事件溯源的 `why` 视图。语义有价值，存储形态（本机 `rules.json` + SQLite 单文件）不适用于多租户服务。
3. **不借**：把规则文件当发布权威、把"至少一次 + Skill 自查"当业务幂等、把"Agent 就是一个进程、最后一条消息即回执"当在线客服执行合同、卡片链接持有即授权。理由见 §5。

一句话：**它不是一个可以抄的"自进化内核"，而是一份把"长期自动运行"写成可验证纪律的工程样本；Loomrise 该抄的是纪律，不是形态。**

## 2. 它实际怎样转起来

### 2.1 六个词（`docs/protocol.md` §六个词）

| 词 | 含义 | 对 Loomrise 的近似对象 |
|---|---|---|
| 事件 | 发生了一件事：来源、编号、类型、对象、摘要、详情、回原处的链接；时间到了、人点了卡片也是事件 | `RunEvent` / 服务周期触发 / 人工决定 |
| 规则 | 什么事件、交给谁、在哪个目录、用什么 Skill、什么时候告诉你 | `AgentSpec` 的装配项 + `DecisionPolicy` 的路由部分 |
| 事项 | 同一规则下同一对象的事；卡片、到期复查、会话都挂在事项上 | `Case` 的线程 / `TaskItem` |
| 一轮 | 一次执行：领一批事件，交一份回执，然后结束 | 一次 `Run`（`ServiceRequest` 的执行） |
| 回执 | Agent 的最后一条消息，想让中台做的事全写在这里 | `ChangeProposal` + 副作用意图（弱化版） |
| 卡片 | 给人看的东西；带选项是提问，选了就是新事件；不带选项是通知 | 审批页的待办项 / `CaseNomination` 的确认 |

### 2.2 一轮的完整生命周期（`kernel/decide.ts`）

```text
事件进门（parseEvent：字段白名单 + 字符集 + 长度上限 + hops）
  → 按规则匹配（source + type 通配）
  → 入队（同规则同事项已有排队的一轮则并进去，不新开）
  → 接单程序领活（claim，签发这一轮的独立 token）
  → Agent 进程跑（脱离进程组，输出落文件）
  → 交回执（finish：整份在同一个事实里一次生效）
      ├─ ask    → 生成提问卡片，本轮结束，不占进程
      ├─ later  → 生成到期复查（继承 hops）
      ├─ notice → 通知卡片
      ├─ resolve→ 结掉本轮核对范围内的开源卡片
      └─ events → 只有规则写了 emits 才允许，hops + 1
  → 人回答卡片 = 新事件 → 唤醒原事项，接着原会话
```

关键点：**Agent 自己不能改变"交给谁、在哪、什么权限"，它只能提交回执申请。** 事件里的 `cwd`/`agent`/`access` 字段会被直接拒收（`protocol/validate.ts` 的 `FIELDS` 白名单；`docs/protocol.md` §六条原则第 6 条）。

### 2.3 四个内核机制（README §内核的四个机制）

| 机制 | 已核实实现 |
|---|---|
| 挂起零消耗 | 等人时进程退出，等待状态落库；回答到达后按 `resume` 接回原会话（`decide.ts` 的 `answer`/`enqueue`） |
| 事件溯源 | 判断、追加日志、更新投影在同一 WAL+FULL 事务内完成，提交后才应答；格式指纹变化时从日志重建，不写迁移（`kernel/evolve.ts`、`docs/protocol.md` §日志与确定性） |
| 指令数据分离 | 提示词里只有来源名、类型、对象、链接四个校验过的字段；正文写进 `context.json` 并标明"是资料"（`worker/contract.ts:19-69`） |
| 跳数熔断 | `MAX_HOPS = 8`，回执事件强制取本轮最大 hops + 1，超过只记录不派发并出一张通知（`decide.ts:30`、`:174-183`） |

其余硬常量（用于后面判断"抄多少"）：重试 5 分钟起、每次翻倍、封顶 1 小时，连续第 3 次通知、第 10 次不再重试（`decide.ts:32`、`:264`）；领活租约 5 分钟未报即转 `unknown`（`due.ts:10`）；接单程序 10 分钟不连即通知一次（`due.ts:12`）；卡片重发按 0/1/3/7/15/25/35/45/55 分钟（`decide.ts:26`）。

## 3. 逐条对照：哪些能落进 Loomrise 的自迭代

### 3.1 总表

| # | 上游机制 | 上游证据 | Loomrise 落点 | 借鉴等级 |
|---|---|---|---|---|
| U1 | 一轮不等人、挂起零消耗、回答唤醒原会话 | `protocol.md` §原则 5；`decide.ts` `answer`/`enqueue` | `ImprovementRun` 新增"等人"态，审批可跨天 | 直接借语义 |
| U2 | 跳数熔断（上限与业务结果无关，Agent 改不了） | `decide.ts:30`、`:174-183` | `ImprovementRun` 的迭代链深度上限 | 直接借语义 |
| U3 | 配置版本 = 产生它的那条事实序号；在途轮次保留领取时版本 | `decide.ts:469`、`query.ts:7-11`；`SKILL.md` §改规则 | `AgentVersion` 在途 `Run` 的版本钉 | 直接借语义 |
| U4 | 规则写错/读不到：旧规则继续跑 + 推一张卡片说错在哪 | `decide.ts:473`；`protocol.md` §失败时会怎样 | `mutable` 段即时生效失败时的降级路径 | 直接借语义 |
| U5 | 超时无回音 → `unknown`，通知人，放开同组，后到的结果照样收 | `decide.ts:212-219`；`protocol.md` §失败时会怎样 | R2 未完成的"未知结果对账" | 直接借语义 |
| U6 | 逐轮 `usage` 记账，按规则/Agent 汇总今日与 7 日 | `state.ts:13-19`、`:93-112` | `ImprovementRun` 预算可归因 | 直接借语义 |
| U7 | 回执合同：字段白名单、条数上限、越界整份拒收 | `protocol/validate.ts:143-175` | AGI-08 Worker 的作业回执 | 借形态 |
| U8 | 决定账本：`docs/decisions.md` 记人定过的、`docs/declined.md` 记拒绝过的，Agent 先读、定过的不再问 | `skills/agent-autoloop/SKILL.md` §写处理手册 | 减少诊断重复提问；经验沉淀为可评审文本 | 借形态 |
| U9 | 交付流水线：检查工作流 → 按 `review.points` 审查（`xhigh` 高风险路径加审）→ 白名单合并 → Ship → 健康接口校验提交号 | `plugins/delivery/`、`SKILL.md` §交付流水线 | 代码交付门，不是业务质量门；只借"发布后核实版本"这一条 | 仅参考 |
| U10 | 固定种子 20 万步模拟、8! 动作全序、1000 次 SIGKILL、25 处变异、独立重放 oracle | `sim/invariants.ts`、`protocol.md` §一致性和复现 | 评测体系自身的迭代闭环（[提案 §5.6](S2-EVAL-GATE-PROPOSAL.md)） | 借方法 |

### U1 挂起零消耗——`ImprovementRun` 缺的那个态

上游把"等人"做成一等状态：一轮结束时进程退出，等待落库，人回答后产生新事件并唤醒原事项，尽量接着原会话（`decide.ts` `answer` → `enqueue(..., card.lane, resume)`）。

Loomrise 的 `ImprovementRun` 状态机（[评测提案 §4](S2-EVAL-GATE-PROPOSAL.md)）是 `running → proposed → closed/exhausted/blocked`。它假设审批是"生成提案后立刻有人看"，但真实节奏是：提案生成 → 等审批人两三天 → 驳回 → 再来一轮。这三天里如果流程还挂在 `running`，既算不清预算，也说不清"到底在等谁"。

**建议落点**：在 `running` 与 `proposed` 之间加 `awaiting_human`（等待审批/等待真值确认），字段 `waiting_on`（审批人角色 / 案例编号 / 起始时间）、`resume_ref`（回答后接回哪一轮）。语义照抄三条：不占执行资源、不计新预算、回答到达时作为新输入继续而不是重跑。**这与 Loomrise 已有的 `RunEvent` 模型兼容**——人的决定本来就是事件，不需要新合同。

### U2 跳数熔断——"迭代自己触发自己"的上限

上游的熔断不在业务层，在内核层：`hops` 由内核累加，经过人工提问和定时复查都不清零，Agent 自己改不了；超过 8 层只记录、不派发，并发一张卡片告知（`decide.ts:348` 回执事件取 `hopsOf + 1`；`answer`/`timer` 继承原深度）。

这正是 Loomrise 的自迭代闭环最需要的阀门。流程 A→B→C→D 里，每一环都可能再产出提名：诊断发现新坏例 → 生成候选 → 回放失败 → 又是新坏例 → 再生成候选。**`budget` 只能限制"一个 run 里试几次"，限不住"run 生了 run"。**

**建议落点**：`ImprovementRun` 增加 `chain_depth`（由谁触发：人 / 阈值提醒 / 上一轮 run 的产物），上限建议 3 层；超过上限时**不静默丢弃**，而是转成一条待人工复核的提名（`CaseNomination`）。注意上游的边界也适用于我们：**熔断只停派发，不判失败**——所以熔断本身要留痕，否则会变成线索黑洞（见 §7 风险 2）。

### U3 领取时冻结配置——"改版本不换在途"

上游把规则也当成事实：`rules` 是一次输入，`version = draft.seq`（`decide.ts:469`），于是每条事实都记住自己当时的规则版本；运行记住 `rules_version`，`configuration(view, run.rules_version)` 取回它领取时那一版（`query.ts:7-11`）。规则变更时：排队中的任务领活时采用新配置，**已领取的保留原 Job 配置与接单程序**，换 Agent 则不带旧会话（`SKILL.md` §改规则、`protocol.md` §规则末段）。

Loomrise 已有 `AgentVersion` 与"版本钉"的方向，但**没有写成"在途 `Run` 用哪一版"的合同**。这在自迭代里是硬问题：一个 run 正在跑，人批准了候选版本并发布，在途的这一轮该算旧版还是新版？如果算混了，回放结论和线上事实就对不上，Gate 证据链断在这里。

**建议落点**：在 `Run` 上明确 `agent_version_ref` + `policy_profile_ref`，语义取"领取时冻结、发布不回溯在途"；同时在评测报告里把"在途轮次"排除出候选版本的样本。**这是本文件里最该先做的一条**——它不影响任何现有实现，只是一句合同 + 一个字段。

### U4 写错继续跑——降级路径要有出口，且要有告警

上游对"配置坏了"的处理是双轨：启动时读不到规则就不启动（没有旧规则可用）；运行中写错则**保留旧规则继续跑，并推一张卡片说明错在哪**（`decide.ts:473` `rulesError`；`protocol.md` §失败时会怎样末两行）。

Loomrise 的 `mutable` 段是"即时保存生效、完整回放异步补、退步自动回滚并通知"（[S2 设计 §5 第 14 条](S2-DESIGN.md)）。问题是：**如果保存进去的内容本身让评测跑不起来**（案例集引用失效、阈值非法、Skill 引用缺失），"异步补回放"就永远补不上，而线上已经在用这一版。

**建议落点**：候选保存时做一次"可评测性检查"（确定性、不需要模型），不过则拒绝保存而不是保存后告警；已经生效的版本若在下一次例行检查中不可评测，退回上一版并出一张 `CaseNomination` 级告警。上游给的是一个更弱的形态（继续用旧的 + 通知），但方向一致：**宁可跑旧版，不可跑坏版，且必须让 owner 知道。**

### U5 未知态——`failed` 与 `unknown` 不能混

上游把"不确定做没做完"单独设成 `unknown`：领活后 5 分钟没回音，标记 `unknown`、放开同组、通知人；**它后来交的结果照样收**（`decide.ts:212-219`）。这与 `failed` 的后果完全不同：`failed` 会触发重试（花真钱），`unknown` 不会。

Loomrise 的 [R2 证据](reports/R2-EVIDENCE.md) 里"未知结果对账"仍未完成，而自迭代场景比在线客服更容易撞上这个：回放批次跑到一半超时、诊断 Worker 被杀、Gate 预算耗尽中断——**如果这些都记成失败，重试会重复消耗 Reserve 批次，而 Reserve 是一次性的**（[S2 设计 §2.1](S2-DESIGN.md)：`gate_only` 只用一次）。

**建议落点**：`ImprovementRun` 与 `GovernanceJob` 都区分 `failed`（可判定未完成，可重试）与 `unknown`（不可判定，冻结预算、转人工对账，禁止自动重跑）。Gate Reserve 的消耗必须在 `unknown` 时也记账——**跑过就是跑过，不能因为结果丢了就当没花。**

### U6 逐轮记账——预算要能归因到"哪一轮改进"

上游每轮都记 `usage`（输入、输出、缓存、费用），`status` 按完成时间汇总今日与 7 日，并按规则、Agent 分行（`state.ts:13-19`、`:93-112`）。缺数时明确区分"没上报"和"报了 0"（`addUsage` 只加显式给出的字段）。

Loomrise 的 `ImprovementRun` 有 `budget`（候选轮数上限），但没有金额与 token 维度，也没有"这一轮改进花了多少"的归因。等真跑起来，"预算"会退化成"次数配额"，成本失控时说不清是谁花的。

**建议落点**：`ImprovementRun` 加 `spent`（轮数 / token / 金额 / 缺失计数四项并列，不合并成一项），`EvalResult` 的成本对比引用它。**缺失必须显式计数**，不能当 0——这一条比数字本身重要，否则预算永远看起来"没超"。

## 4. 一条可以直接抄的最小形态：决定账本

上游在 `SKILL.md` §写处理手册 里给了一条很低成本的约定：

> 项目里放两份文件：`docs/decisions.md` 记用户亲口定的事，`docs/declined.md` 记他拒绝过的，让 Agent 先读，定过的不再问。

这解决的是 Loomrise 自迭代里一个具体而烦人的问题：**诊断 Agent 反复提同一类被驳回的建议。** AGI-07 只读诊断、AGI-09 生成候选，如果每次诊断都从零开始，运营会第 N 次驳回同一个提案。

建议的形态（不改对象模型，先做文本）：

- `declined` 的来源是 `ChangeProposal` 的驳回记录，按"原因 + 目标字段"归并，不由模型自由生成；
- 诊断/候选生成时作为**只读输入**注入，附"哪一次驳回、谁驳的、理由是什么"；
- 它**不是**硬规则，挡不住人后来改主意——驳回记录过期或业务条件变化时可以被新提案覆盖，但要在提案里说明"为什么这次不一样"。

这条与 [S2 设计 §2.3](S2-DESIGN.md) 不冲突：驳回记录是证据，不是配置，不获得任何权限。

## 5. 明确不借

| 不借 | 理由 |
|---|---|
| **把规则文件当发布权威** | 上游改 `rules.json` 几秒生效，无审批、无回放、无真值核对。它敢这样是因为影响面是"一个人自己电脑上的自动化"；Loomrise 的候选影响的是客户会话与业务承诺，必须过 Gate 与人工批准（[S2 设计 §4 权限矩阵](S2-DESIGN.md)）。 |
| **"Agent 就是一个进程、最后一条消息即回执"当在线客服执行合同** | 这个模型假设"一轮不等人、不流式、不打断"。客服要流式首响、要取消、要人工接管、要 TTS 播出回执（[语音架构决策](VOICE-ARCHITECTURE-DECISIONS.md) D-03）。回执模型只适合后台迭代 Worker（AGI-08），不适合在线服务执行。 |
| **"至少一次 + Skill 自查"当业务幂等** | 上游明说"Agent 可能被叫两次，所以 Skill 里有副作用的动作要先核实当前状态"（`protocol.md` §失败时会怎样末段）——**这是把幂等责任推给提示词**。Loomrise 要求持久结果与外部结果 ID（[AGENTS.md](../AGENTS.md) §3），不能靠模型自觉。 |
| **卡片链接"持有即授权"** | 上游卡片链接 7 天有效、谁拿到谁答（`SECURITY.md` §边界）。审批权必须绑定身份与角色（[S2 设计 §4](S2-DESIGN.md)），不能靠"链接没外泄"。 |
| **单机中台形态与无界面设计** | `rules.json` + 单 SQLite + 本机 `master.key` 是刻意的单机取舍。Loomrise 是多用户工作台，只借语义不借存储。 |
| **用代码交付门替代业务质量门** | 上游交付流水线（检查 → 审查 → 合并 → Ship → 健康接口校验提交号）验的是"代码上线了没有"，不是"客服答得对不对"。方向可参考，不能替代 `EvalSet`。 |

## 6. 建议的研究工作包（编号为研究序号，不改阶段、不改 Gate）

| 编号 | 内容 | 依赖 | 可判定的完成条件 |
|---|---|---|---|
| AP-01 | `ImprovementRun` 增加 `awaiting_human` + `waiting_on` + `resume_ref` | 现有 `RunEvent`，无需新合同 | 提案生成后流程不占执行资源；跨天回答后从原轮次继续而非重跑；预算不因等待增加 |
| AP-02 | 在途 `Run` 冻结 `AgentVersion`；评测排除在途样本 | 现有 `AgentVersion` 字段 | 发布候选版本期间在途轮次仍按旧版留证；回放报告与线上事实不冲突 |
| AP-03 | `chain_depth` 上限 3 层，超限转提名而非静默丢弃 | AP-01 | 构造"提案→回放失败→新提名"三跳样例，第四跳不再派发且留痕可查 |
| AP-04 | `failed` / `unknown` 分离；Reserve 在 `unknown` 时仍记账 | AP-01 | 人为中断回放后，批次标 `consumed`、预算已扣、卡片告警，且不自动重跑 |
| AP-05 | `ImprovementRun.spent` 四项并列（轮/token/金额/缺失） | AP-04 | 缺数时显示"未上报 n 轮"，不显示 0 |
| AP-06 | 驳回账本作为诊断只读输入 | AGI-07 | 同一驳回原因重复提案时，提案里能看到上次驳回人与理由 |

**这些都不需要新阶段。** AP-01/02 是字段与合同，AP-03/04/05 是状态机补充，AP-06 是输入侧装配。它们服务于 S2-c 的 AGI-09/10，不改变 R4 的退出判据。

## 7. 必须守住的四个风险点

1. **"跑得久"不等于"变好了"。** 上游全仓没有一个质量指标，它优化的是"不打扰人、不丢活、不重复花钱"。把这套纪律接到 Loomrise 上，很容易产生"闭环转起来了，所以有提升"的错觉。**改善证据只能来自 Gate Reserve**（[S2 设计 §2.1](S2-DESIGN.md)），运行纪律只保证证据不丢。
2. **熔断会变成线索黑洞。** 上游的 `MAX_HOPS` 只"记录 + 通知"，不判断对错。Loomrise 若照抄，被熔断的迭代链会悄悄堆在日志里没人看。**熔断必须产出待复核提名，并进运营的待办队列。**
3. **`unknown` 会堆积成"没人知道做没做"。** 上游有 `resolve` 让人事后结卡片，Loomrise 的 `unknown` 若没有超期升级机制，会变成永久灰区。建议给 `unknown` 设强制对账期限（例如 24 小时），超期升级为阻塞项。
4. **本机文件型状态不能当服务实现。** `rules.json`、`context.json`、`entry.json` 三处文件承载了上游的配置、资料、恢复信息，这在单机成立，在多实例/多租户下是竞态源。**只借语义，不借这层。**

## 8. 最小验证与通过条件

下表**一条都未执行**，只是未来判定"能不能借"的入口：

| 验证 | 可判定的通过条件 |
|---|---|
| 挂起与恢复 | 构造"提案生成 → 等待 48 小时 → 批准"的样例：期间无执行资源占用、无新增预算消耗；批准后从原轮次继续，不重跑已通过的检查 |
| 版本冻结 | 发布候选版本时有一个在途 run：该 run 的留证仍指向旧版；回放报告里该样本被排除且有说明 |
| 迭代链熔断 | 三跳样例通过、第四跳被拦；被拦的那一跳在待办队列可见，并附完整链路 |
| 未知态记账 | 人为在回放中 kill 进程：批次标 `consumed`、预算已扣、状态为 `unknown` 而非 `failed`、无自动重跑 |
| 成本归因 | 缺 `usage` 的轮次显示为"未上报"，不显示 0；按规则/Agent 汇总与逐轮明细一致 |

只有这些条件实测通过，才可以把本文件从"研究参照"升级为可落地的实施项。

## 9. 来源与核查范围

- 上游仓库与许可：[`KKKKhazix/agent-autoloop` `ae305ac`](https://github.com/KKKKhazix/agent-autoloop/tree/ae305acfb868f721e4e6885eb836a535dd62c3c4)、`LICENSE`（MIT）。已读 `README.md`/`README.en.md`、`docs/protocol.md`、`docs/plugins.md`、`SECURITY.md`、`AGENTS.md`、`skills/agent-autoloop/SKILL.md`、`kernel/{decide,evolve,state,due,query,rules}.ts`、`protocol/{rules,validate}.ts`、`worker/{worker,contract}.ts`、`plugins/delivery/{project,review,run}.ts`、`sim/invariants.ts`、`examples/recipes/feedback/`。**未安装、未运行 `npm test`、未跑 `sim/*`、未接任何真实渠道或 Agent。**
- 上游自述的性能与模拟数据（20 万步、1000 次强杀、千连接内存）未独立复现，只作为"它有这套验证方法"的判断依据，不作为本项目选型证据。
- Loomrise 对照：[S2 治理设计](S2-DESIGN.md)、[S2 评测门禁提案](S2-EVAL-GATE-PROPOSAL.md)、[Agent 接入开发计划](AGENT-INTEGRATION-PLAN.md) AGI-07–10、[架构与对象权威](ARCHITECTURE.md)、[R2 证据摘要](reports/R2-EVIDENCE.md)、[语音架构决策](VOICE-ARCHITECTURE-DECISIONS.md)。
- 相关研究：[Hindsight 迭代机制分析](HINDSIGHT-ITERATION-ANALYSIS.md)（经验沉淀方向）、[Qwen-Audio-Agent 源码研读](QWEN-AUDIO-AGENT-HARNESS-STUDY.md)（harness 方向）。本文与两者互补，不替代。
- 下游使用：本文 §3 的六条运行纪律已被 [Agent 自迭代长效方案与分期规划](AGENT-SELF-ITERATION-ROADMAP.md) §5 引用为 `ImprovementRun` 的字段来源，不在此重复。
