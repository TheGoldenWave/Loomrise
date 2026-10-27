# 竞争格局与差异化定位 v0.1

状态：2026-10-24，研究结论。**不改 [PRODUCT](PRODUCT.md) 定位、不改 [ROADMAP](ROADMAP.md) 阶段、不构成对外营销文案授权**（§7 为内部话术候选，对外使用需另行批准）。
范围：ElevenLabs ElevenAgents、Delight.ai、Knocket（腾讯云 TRTC）三家与本项目的同轴对比。
事实来源：[ElevenLabs 专题卷](competitive/elevenlabs/00-INDEX.md)（A-/B/B+）、[Delight 专题卷](competitive/delight/00-INDEX.md)（B/B-/C）、Knocket 官方教程与产品页（B，2026-10-24 抓取，核验日同）。三家证据等级不同，**跨列比较只比「形态是否存在」，不比「实现质量」**。

---

## 0. 结论先行

三家不是同一类产品，所以「谁更强」是伪问题。真实问题是：**它们在配置链的哪一段止步，而我们打算在哪一段立住。**

| 厂商 | 一句话 | 止步于 |
|---|---|---|
| **Knocket** | 网页/移动/联系页的**轻量接触层**，免费 + BYOK，五步上线 | 止步于「答得像」——单 prompt + 每类 10 条知识 + 转人工短语，无版本、无评测、无记忆 |
| **Delight.ai** | 企业**营收 Agent**，把 SOP 做成一等资产（Actionbook），卖治理叙事（Trust OS） | 止步于「改得动」——规则是自然语言，靠模型解释，门禁是软的 |
| **ElevenLabs** | **语音 Agent 基础设施**，配置全参数暴露，四通道等价 | 止步于「跑得稳」——管道与控制面极强，业务结果与审批不归它管 |
| **Loomrise** | 开源 + 自有云，**可验收的业务 Agent 交付台** | 要立住的是「查得清」——六层冻结、模型外裁决、结果留证 |

一句话差异化：**它们都在优化「配置得多快、多好改」；我们要优化「出了问题能不能定位到哪一层、并由谁负责」。**

---

## 1. 定位光谱：不是一个市场

| | Knocket | Delight.ai | ElevenLabs | Loomrise |
|---|---|---|---|---|
| 买家 | 独立开发者 / 小团队 / 小 SaaS | 企业 CX 与营收负责人 | 开发者 / 产品团队 | 搭建者 + 策略运营（AI PM、解决方案、小团队） |
| 售卖方式 | 免费起步，自助注册 | 销售驱动，无公开定价 | 订阅 + 用量，自助 + API | 开源（Apache-2.0），自部署 |
| 核心承诺 | 一个 script 标签就有客服 | 每条对话都长营收 | 最好的语音管道 | 每个结果都可验收 |
| 主入口 | Widget / Contact Page / Inbox | 全渠道 + 语音 + 自有工单 Desk | API / SDK / CLI / MCP | 工作台 + 网页客服应用 |
| 护城河 | 零门槛 + 免费 | 通信基础设施（7B 对话/月）+ 治理叙事 | 语音模型与低延迟工程 | 待建立：证据链 + 可拥有 |

**关键判断**：Knocket 与我们是**同一交付面**的竞争（网页客服应用），Delight 与我们**同一购买场景**的竞争（企业客服/销售 Agent），ElevenLabs 与我们**不同交付面但会撞在语音需求上**。三者不能合并成一张「功能打勾表」，否则会得出「我们处处不如人」的错误结论。

---

## 2. ElevenLabs 与 Delight：五点相似

两家的产品形状差很远，但**叙事结构几乎同构**。这五点是行业共识区，不是任何一家的独有优势：

1. **把配置做成产品，而不是 YAML。** 都有网页后台、内置试用、可视化发布。
2. **自然语言是编排的默认形态。** ElevenLabs 的 Procedures 触发条件默认 `LLM Condition`；Delight 的 Actionbook 条件直接是自然语言 if/else。**确定性表达在两家都不是默认**（ElevenLabs 有 `Expression` AST 但为可选；Delight 无）。
3. **版本 + 环境 + 灰度是标配。** EL：分支 / 流量切分 / 字段级 diff；Delight：资产级版本 / Dev-Staging-Prod / 选择性部署 / 10% 灰度 / A/B。
4. **可观测被产品化。** EL：activity log + 25 个客户端事件；Delight：Openbook + 每次 tool call 的 Thinking Messages。都主张「每个决定可见」。
5. **评测被产品化，但都不是发布必要条件。** EL 有三类测试与参数断言三法，但官方把「测试通过才能合并」列为**未来能力**；Delight 有 Test set + outcome testing，公开资料中未见「不通过则禁止发布」。

> 第 5 点是两家**共同的结构性缺口**，也是我们唯一能同时对两家成立差异化的地方。

---

## 3. ElevenLabs 与 Delight：六点差别

| # | 维度 | ElevenLabs | Delight.ai |
|---|---|---|---|
| 1 | **编排形态** | 双形态：Procedures（自然语言触发 + 8 类步骤）+ Workflow（节点/边/表达式 AST）；**确定性可选存在** | 单形态：Actionbook（behavioral rules / global actions / conditional blocks），**无确定性形态** |
| 2 | **版本粒度** | Agent **整包不可变快照**（`AgentVersion`），分支即工作副本 | **资产级**版本（actionbook / profile 各自版本号），Agent 组合靠部署记录还原 |
| 3 | **语音深度** | 语音是一等基础设施：ASR / TTS / VAD / 话轮 / 软超时 / 打断忽略词全参数暴露 | 语音是业务流程：自有号码、IVR 按键导航、智能转接、按键输入敏感数字；**不暴露声学参数** |
| 4 | **自改进** | 未见 | 有，且明确 L0–L3 四级，L3 允许无人上线 |
| 5 | **配置通道** | 四通道等价（Dashboard / CLI / API / MCP），同一份 JSON | Dashboard + **反向 MCP**（外部 AI 客户端写生产配置）；无公开 API/CLI |
| 6 | **客户形态** | 开发者自助（免费层 + 文档 368 篇） | 企业交付（文档私有、需销售开权限、无自助注册） |

一句话：**ElevenLabs 把「管道」做深，Delight 把「运营面」做深。** 两者的交集是「自然语言编排 + 版本发布 + 可观测」，但各自往不同方向延伸。

---

## 4. 把 Knocket 拉进来：三层光谱

Knocket 的配置面小到可以全部列完（官方教程 B 级，字段上限为原文）：

| 配置面 | 内容 | 上限 |
|---|---|---|
| AI Agent | 总开关、覆盖渠道（Web Widget / Mobile Widget / Contact Page）、接待时段（Always / When offline） | 3 渠道 |
| Bot | 头像、名称、Greeting、System Prompt | 400 / 2000 字符 |
| LLM | Provider 预设或 Custom、API Key、API URL、Model ID、Test Connection | 仅 OpenAI Chat Completions 兼容；embedding 平台托管 |
| Handoff | 转人工短语库（默认 47 语言）+ 自定义；通知走 Browser Push / Telegram | — |
| Knowledge | FAQ / URL / File 三 tab，Indexed 状态 + Last Synced | **每 tab 10 条**；文件 10 MB；8 种格式 |
| Usage | AI Requests / Handoffs / Avg Response Time / token by model / 渠道分布 | — |

**它没有**（公开教程未见，不等于绝对没有）：版本、回滚、环境、测试集、评测、guardrail 分类、记忆、任务、SOP、工具调用、权限模型。

三个值得记住的点：

1. **它的转人工是模型外确定性匹配。** 短语命中在**模型跑之前**，官方原文 `deterministic, instant, no model call`。这是全场唯一一个「模型外裁决」的正例——虽然窄到只有一句话。它证明：**确定性优先不是我们的洁癖，是连免费产品都在用的省事做法**（因为便宜且不会错）。
2. **它的天花板写在配额里。** 每 tab 10 条知识、prompt 2000 字符。这不是疏忽，是产品定位：它服务「问题不超过 20 个」的站点。
3. **它没有治理叙事，也不需要。** 它的买家不问「怎么审计」，只问「今天能不能上线」。

---

## 5. 四家同轴对比

| 维度 | Knocket | Delight.ai | ElevenLabs | **Loomrise** |
|---|---|---|---|---|
| 配置对象 | 单 Agent（prompt + 知识 + 转人工） | 共享资产（Knowledge/Actionbook/Tools/Profile/Safeguards）+ Agent 引用 | Agent 配置树（7 子块 + 16 字段 + workflow） | 六层：ContextSnapshot / RequestRouting / Skill-SOP / HardRule / ToolPolicy / Outcome |
| 编排形态 | 无（单 prompt） | Actionbook（自然语言 SOP，三视图） | Procedures + Workflow（含表达式 AST） | Unit：契约层 + 内容层，可嵌套图；条件深度 ≤2、闭集选择 |
| 条件求值 | 短语精确匹配（模型外） | 自然语言 if/else（模型内） | 默认 LLM Condition；可选 Expression（模型外） | **HardRule 模型外 + 只引用已声明字段** |
| 知识与作用域 | 3 tab × 10 条，无作用域 | Global / country 标签 + locale 路由 RAG | KB 三页签 + usage_mode + RAG 参数 | 带 `source_ref`、权利范围、有效期、撤销入口；缺任一项不得进快照 |
| 上下文 / 记忆 | 无 | context objects + AMP（可溯源、可删） | 会话级 + 未文档化 per-agent 开关 | 记忆 / 画像 / 上下文三层分离，各持权威 |
| 工具与权限 | 无（只有 LLM 连接） | 29 集成 + MCP；权限靠 RBAC 与集成侧 | 5 类工具（client/webhook/code/MCP/system）+ 工具级中断 | ToolPolicy：输入输出约束、确认、预算、超时、幂等、结果证据 |
| 业务结果 | 无（只记答复与转人工） | outcome 断言用于**评测**；写回 CRM/工单 | 无业务终态概念 | **Outcome 是执行合同**：持久副作用 + 外部结果 ID，「模型说完成」不算完成 |
| 版本 | 无 | 资产级 + change log + 一键回滚 | 整包快照 + 分支 + 流量切分 | 整包 `AgentVersion` 冻结，评测四元组可复现 |
| 测试 / 评测 | 无 | 真实对话建测试集 + outcome testing + scorecard | 三类测试 + 参数断言 + 成功三值 | 冻结集回放 + 独立评测 + ChangeProposal |
| 发布门禁 | 无（保存即生效） | 有装置，未见强制 | 有装置，合并不要求测试通过 | **独立评测 + 人工批准为必要条件** |
| 改进闭环 | 无 | ZTI L0–L3（L3 无人） | 未见 | Case → 提案 → 评测 → 批准 → 发布 → 回滚（S2-c） |
| 任务 / 服务义务 | 无 | 无（只有事件触发式主动触达） | 无 | **TaskItem 账本：跨会话服务义务** |
| 交付形态 | SaaS，免费 + BYOK | SaaS，销售驱动 | SaaS / API，不可自托管 | **开源 + 单租户自有云** |
| 证据等级 | B（教程） | B / B- / C | A- / B / B+ | 自身实现，S1 有验收 |

---

## 6. 我们靠什么差异化

### 6.1 四个能守住的差异（有结构性理由，不是功能堆）

**D1 · 可验收性：从「装置链」到「证据链」。**
三家都有「能看」，只有我们要求「能判」。具体是三条不可让的规则：① 整包 `AgentVersion` 冻结（回放可复现）；② 硬规则在模型外执行（价格/权限/金额不由模型解释）；③ 发布需要独立评测 + 人工批准。
对客户的说法不是「我们功能更多」，而是：**「出了问题，我能告诉你是哪一层、哪个版本、哪条规则、哪个结果没落地。」** 这是三家都答不了的问题——Delight 只能给 actionbook diff，ElevenLabs 只能给 trace。

**D2 · 可拥有：开源 + 单租户自有云。**
Delight 与 Knocket 的配置权威在厂商租户内，ElevenLabs 明确不可自托管。我们交付的是**客户自己云上的一套**：数据不出域、配置可导出、供应商可替换。这一条在受监管行业（医疗、金融、教育）是硬需求，不是偏好。

**D3 · 业务义务：Task 账本。**
三家都只管「这一轮对话」。真实的客服/销售有跨会话义务：三天后回访、材料未交、预约待确认。Delight 有事件触发的主动触达（补货、续费、弃单），但**没有义务账本**——它不知道「我答应过什么还没做」。这是我们的结构性差异点，也是最难被抄的一点（需要业务用户身份 + 事件 envelope + 幂等）。

**D4 · 记忆治理：记忆不授予触达权。**
Delight 的 AMP 方向相反——记忆直接驱动主动触达（"记忆 → 该联系他了"）。我们的规则是：记忆保存陈述，画像派生视图，上下文是本次快照，**触达权只来自授权与 Task**。差异不在「有没有记忆」，在「记忆能不能自己决定去打扰用户」。

### 6.2 三个必须补的短板（不补，上面四条讲不响）

| # | 短板 | 对手的做法 | 我们要到什么程度 |
|---|---|---|---|
| S1 | **SOP 的可维护性** | Delight 三视图（Source/Tree/Flow）+ 同屏 Tester；运营自己改 | SOP 必须是结构化文档 + 结构视图 + 页内测试；否则「运营可改」是空话，客户仍会回到工程排期 |
| S2 | **测试语料从哪来** | Delight 用真实 conversation ID 建用例、跨环境复用 | 冻结集要有真实来源（脱敏 + 授权 + 版本固定）；否则「评测」只是一组手写样例 |
| S3 | **首次上线速度** | Knocket 五步、分钟级；Delight 天级 | 初始化助手必须把「授权资料 → 可试用客服」压到同量级，否则 D1 的价值客户看不到就先流失 |

### 6.3 一个不追的方向

**不追「配置面数量」。** 三家加起来有 200+ 个配置项，堆配置项不会带来差异，只会带来维护成本与「看起来像但验不了」。我们的配置面按六层收敛，新增一项必须回答「它属于哪一层、谁改、怎么验」。

---

## 7. 对外话术候选（内部，需批准后使用）

| 对手 | 一句话 | 前提 |
|---|---|---|
| vs Knocket | 「它让你五分钟上线；我们多花一小时，换来每一次回答都能回放、每一个结果都能对账。」 | 需先补齐 S3，否则这句话站不住 |
| vs Delight | 「它的 actionbook 是写得更好、更好改的提示；我们的硬规则是模型改不了的那部分。」 | 需先补齐 S1，否则被反问「那你们运营怎么改」 |
| vs ElevenLabs | 「它给你最好的语音管道；我们给你业务结果的账本——两个可以一起用。」 | 定位为互补而非替代，避免在语音指标上正面比 |

> 三条都不是已批准文案。按 [OPEN-SOURCE-BOUNDARY](OPEN-SOURCE-BOUNDARY.md) 与 AGENTS §5，对外发布前需单独确认，且不得引用未经实测的性能或效果数字。

---

## 8. 明确不学

| # | 不学 | 出自 |
|---|---|---|
| 1 | 用自然语言 if/else 承载价格、退款阈值、升级判定 | Delight |
| 2 | 自治发布（ZTI L2/L3） | Delight |
| 3 | 外部 AI 客户端直接写生产配置 | Delight MCP |
| 4 | 记忆直接驱动主动触达 | Delight AMP |
| 5 | 资产级版本替代整包快照 | Delight |
| 6 | 合并/发布不要求测试通过 | ElevenLabs + Delight |
| 7 | 把配置项数量当竞争力 | 三家共有倾向 |
| 8 | 用配额当护城河（10 条知识、2000 字符 prompt） | Knocket |

---

## 9. 存疑与待验证

| # | 项 | 状态 |
|---|---|---|
| 1 | Knocket 是否有教程未展示的隐藏配置（版本、评测） | 公开教程只覆盖 Setting/Knowledge/Usage 三页；未见文档站全量索引 |
| 2 | Knocket 的数据留存、地区、是否能导出 | 未见说明 |
| 3 | Delight 发布是否强制测试通过 | 未见，D |
| 4 | Delight 定价与是否支持私有化 | 无 pricing 页，D |
| 5 | ElevenLabs 是否有自改进闭环（本轮语料未见） | D |
| 6 | 三家在中文客服场景的实测效果 | 全部未验；Knocket 的转人工短语库含中文（47 语言含 `转人工`），是唯一有中文痕迹的证据 |
| 7 | 我们的 S3 上线速度目标值 | 未定；需与 Knocket 五步流程做一次对照走查后再写数字 |

---

## 10. 事实 → 文件指针

| 本文件节 | 事实出处 |
|---|---|
| §2 / §3 ElevenLabs | [专题卷 01 配置对象模型](competitive/elevenlabs/01-CONFIG-MODEL.md)、[总纲](ELEVENLABS-AGENTS-ANALYSIS.md) |
| §3 / §4 Delight | [Delight 01 配置模型](competitive/delight/01-CONFIG-MODEL.md) |
| §4 Knocket 配置面 | `knocket.trtc.io/tutorials/ai-agent/`（2026-10-24）、[客服交付计划 §1](CUSTOMER-SERVICE-DELIVERY-PLAN.md) 覆盖矩阵 |
| §6.1 D1–D4 | [六层配置合同](CONFIGURATION-LAYERS.md)、[硬规则模型](HARD-RULE-MODEL.md)、[Task 设计](TASK-SYSTEM-DESIGN.md)、[用户上下文设计](USER-CONTEXT-DESIGN.md) |
| §6.2 S1–S3 | [S2 评测门禁提案](S2-EVAL-GATE-PROPOSAL.md)、[配置体验优化](CONFIGURATION-UX-OPTIMIZATION.md) |
