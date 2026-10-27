# 01 · 配置模型与实现

> 证据等级：**B**（官方产品发布/博客的机制叙述）+ **B-**（多篇交叉一致后的推断）+ **C**（产品页宣称）。无 A-，无 B+。
> 语料：见 [索引](./00-INDEX.md) §1。抓取日 2026-10-24。
> 结构：§1–§7 为事实（不掺判断），§8–§9 为判断（明确标注），§10 为存疑。**引用时请连同等级一起引。**

---

## 1. 一句话

Delight 的配置不是「一个 Agent 一份配置」，而是**一套工作区共享资产 + 每个 Agent 的引用组合 + 两层环境（Dev/Prod）+ 资产级版本**；其中 `Actionbook` 是唯一被做成独立一等资产的业务逻辑载体，也是它全部产品叙事的轴心。

---

## 2. 层级结构：资产、实例、环境

### 2.1 工作区共享资产（B）

| 资产 | 内容 | 出处 |
|---|---|---|
| Knowledge | 知识源、snippet、embedding；后续扩为自建 KB（分类/章节/文章，draft/published/internal 三态） | `delight-knowledge`、`selective-deployment-2.0` |
| **Actionbook** | 自然语言 SOP，可被多个 Agent 复用 | `action-books-management` |
| Tools / Integrations | 29 个集成（handoff、知识源、业务动作三类） | `integrations` |
| Message Templates | 固定话术 | `deployment-and-production-mode` |
| Profile | 品牌语气、风格、身份（**与 actionbook 一起做版本控制**） | `version-control-for-actionbooks-profile` |
| CSAT / Safeguards / Workspace General | 后续纳入选择性部署范围 | `selective-deployment-2.0` |

### 2.2 Agent 实例（B/C）

- 每个 Agent 有自己的 identity、instructions、knowledge 选择、actionbook 选择、tools、safeguards、CSAT、handoff 设置（`delight-agent-mcp` 列举了 MCP 可写的字段组，见 §6）。
- **多 Agent 团队**：每个 Agent 独立拥有 knowledge 与 conversation history，销售/客服/留存数据不混，可各自套不同合规策略（`product-release/team`，B）。
- Agent 之间无「共享记忆」表述；共享的是工作区资产。

### 2.3 环境（B）

| 环境 | 语义 |
|---|---|
| Development | 建、测、调全部内容：知识、actionbook、话术、集成 |
| Production | **稳定、只读**，不接受未经部署的改动 |
| Staging | 生产镜像，含真实集成与策略（`trust-os` 页，C） |

部署是**选择性**的：逐资产勾选从 Dev 提升到 Prod，带 side-by-side/inline diff、自动变更检测、只读预览；设置类（Profile、CSAT、Safeguards、Workspace General）也可 diff 与回滚（`selective-deployment-2.0`，B）。灰度先 10%、A/B 对比 resolution 与 CSAT（`trust-os`，C）。

### 2.4 版本粒度：资产级，不是整包（B）

- Actionbook 与 Profile 各自有版本号、change log、一键回滚（`version-control-for-actionbooks-profile`，2025-03）。
- 已发布 actionbook 的版本号旁会挂运行数据，官方举例：`returns actionbook v3.2 / 96.4% resolution / 45,200 conversations`（`actionbook-editor`，C，数字为营销示例）。
- **未见**「一个 Agent 的整包不可变快照」这一概念。当前生产由哪些资产版本组合而成，需从部署记录还原（B-，推断）。

---

## 3. 四个配置面（官方叙事，C）

`delight.ai/builder` 只给四步，无第五步：

| # | 面 | 官方表述要点 |
|---|---|---|
| 1 | **Persona** | 人格、品牌价值、语气、风格 |
| 2 | **Knowledge** | 用与人工坐席相同的资料训练，保证一致准确 |
| 3 | **Actionbooks** | 「No code, no chart, just words」——不画流程图，写自然语言指令 |
| 4 | **Boundaries** | 内置 safeguard，防有害/偏见输出 |

第四步之外还有一层没进叙事但确实存在：**Tools/Integrations**（29 个）与 **context objects**（§5）。官方分工是「CX 团队写 actionbook，技术团队负责把 Agent 接到数字服务与数据上」（`sendbird.com/blog/ai-sop`，B）。

---

## 4. Actionbook：本卷重点

### 4.1 它是什么（B）

- 位置：`Workspace Settings` 内，**不是一个 textarea 里的 prompt**，而是结构化文档。
- 固定结构，每本一致：**behavioral rules（行为规则）/ global actions（全局动作）/ conditional blocks（条件块）**。
- conditional block 即 if/else：条件在上、结果在下，渲染为可视块；运营在 UI 里改条件，**不接触底层 template syntax**。
- 一本 actionbook 可以有几十节、嵌套条件、跨意图锚点链接；官方给的规模是「35 节、2847 字符嵌套 markup」。
- 一个 Agent 可挂**多本** actionbook（`sendbird.com/blog/ai-sop`：CX teams create multiple Actionbooks for their AI agents）；选择依据可含 country / language / user context（`localized-ai-agent`，B）。
- 明确反决策树：理由是真实对话无法穷举，硬编码路径会死锁（`ai-sop`，B）。

### 4.2 三视图（B）

| 视图 | 用途 | 关键句 |
|---|---|---|
| Source | 直接编辑结构文本 | — |
| Tree | 右侧层级大纲，点击跳转对应节 | 「navigate by name, land exactly there」 |
| Flow（Openbook） | 全本渲染成结构图 | 「**not to trace decisions — to navigate the document**」 |

第三条要特别注意：**Flow 是导航用的文档视图，不是执行图**。它没有节点/边/表达式的执行语义，也不承担分支求值。

### 4.3 编辑回路（B）

左侧写 → 右侧实时 Preview → 同屏内置 Tester 对真实 Agent 跑一遍 → 保存。Version history 在同一屏顶部。

### 4.4 执行语义：这是本卷最关键的一条（B-，推断）

官方营销语：`AI executes the playbook, not freeform generation. No improvised responses. No off-script risk.`（`ai-customer-service`，**C**）

但四篇机制叙述互相印证的是另一件事：

| 证据 | 指向 |
|---|---|
| Actionbook 的定义是「natural language control without rigid coding」 | 内容是可读文本，不是可解释执行的形式化规范 |
| 条件是自然语言 if/else，运营在 UI 改条件即可改变行为 | 条件求值发生在模型侧 |
| Dynamic Safeguards 中，绑定的 actionbook 接收 `flagged type` 与 `reason` 作为**输入**，再由它「生成回应」 | actionbook 是**提示上下文**，不是函数 |
| ZTI 的缺陷形态是「某个 actionbook 分支跳过了 eligibility check」，靠重跑真实对话把通过率从 85% 提到 100% | 缺陷是**概率性遗漏**，不是抛错；只能靠统计修复 |
| 用 LLM 抽取 intent、用 LLM 判 outcome | 判定链本身是概率的 |

**推断（B-）**：`Actionbook = 结构化提示（structured prompt），不是可执行规范（executable spec）`。它的「确定性」来自写得更细、约束更多、测试更密，而不是来自模型外的裁决器。因此「no off-script risk」是营销表述，不能作为实现证据。

> 这条推断决定了它能不能被我们照抄：能抄形态（结构化 SOP + 三视图 + 内嵌测试），不能抄「把价格/退款阈值/升级判定写进去」这个用法。

---

## 5. 知识、本地化与上下文

### 5.1 知识源（B）

- 类型：URL、文件、CSV/JSON、snippet、embedding；集成式来源含 Salesforce（Knowledge）、Zendesk、Freshworks、ServiceNow、Confluence、Notion、Google Drive、Amazon S3。
- **Delight Knowledge**（2026-07）：自建 KB，分类/章节/文章、多语言、draft/published/internal 三态；同一份内容同时供给 AI 回答、公共帮助中心（自定义域名）、坐席工单内检索；Zendesk Guide 可迁入并保留 SEO。
- 答案可带 citations（`citations` 发布，B）。

### 5.2 本地化与标签路由（B）

- 每个知识源与每本 actionbook 可标 **Global** 或 **country-specific**。
- Client 传 `setCountry` 元数据 → Agent 自动选合适知识库与 actionbook，并用 country/language 过滤 RAG。
- 会话中语言切换会被实时检测，保留 memory、context、tone。

### 5.3 context object（B）

- 可在 actionbook 与 safeguard 回应中读取的会话期对象：membership tier、region、language 等。
- 这是它的「个性化注入」通道，等价于我们的 `ContextSnapshot` 的**输入侧**，但没有来源、有效期、敏感级别、撤销入口的合同表述（B-）。

---

## 6. 配置的读写通道

| 通道 | 能力 | 证据 |
|---|---|---|
| Dashboard | 全部配置面；Workspace Settings 统一入口 | B |
| **Delight Agent MCP** | 外部 AI 客户端（Claude Code / Claude.ai / ChatGPT / Cursor / Codex）直连 live agent 数据，**并创建/更新 actionbooks、tools、knowledge sources、agent 配置（identity、instructions、safeguards、CSAT、handoff）** | B（`delight-agent-mcp`，2026-08） |
| CLI | 未见 | D |
| 公开 REST API | 未见（文档私有） | D |

MCP 这条值得单记：方向与我们的 MCP 相反。我们是「Agent 通过 MCP 用外部工具」，它是「外部 AI 通过 MCP 改我的生产配置」。官方卖点是「诊断问题和修复问题在同一个对话里完成，不用切面板」。

---

## 7. 测试、评测与改进闭环

### 7.1 测试（B）

| 能力 | 机制 |
|---|---|
| Tester | 编辑器内直接对真实 Agent 跑 |
| Conversation Benchmark Testing | 多轮模拟对话 + 期望结果比对，可**定时后台跑**，用于抓回归 |
| Test Upgrade | 用**真实 conversation ID** 建用例；label 分组、bulk 操作；**同一套测试集跨 dev/staging/prod 复用**；失败给「做了什么、错在哪、下一步看哪」 |
| Outcome-based testing | 三层：intent recognition（手工或 LLM 抽取）→ outcome validation（结果对不对）→ **workflow verification（该触发的 actionbook 分支是否触发、该调的集成是否调用）** |

`workflow verification` 这一层最值得注意：它把「SOP 分支命中」和「工具调用命中」当成可断言的对象——这正是我们 `RunEvent` 能提供、而多数平台没有的东西。

### 7.2 人在环评测（B）

- **AI Agent Scorecards**：tone / clarity & readability / relevance / solution effectiveness 四维打分 + 预设原因标签 + coaching notes。
- Humans as AI evaluators、hallucination & unsafe content detection、**low CSAT analysis**（把 1–2 分对话自动分成五类失败）。
- **Thinking Messages**：把「正在调用哪个工具」外化为用户可见的具体状态，替代通用打字指示器。

### 7.3 改进闭环 ZTI（B，营销级叙述）

四级自治阶梯：

| 级 | 语义 | 解锁条件 |
|---|---|---|
| L0 | 全手动 | — |
| L1 | AI 提议，人批准 | — |
| L2 | 人掌舵，边界内自治 | **人机一致率 > 97%**（定义与测量方法未公开） |
| L3 | 零接触，全自动研究→假设→测试→上线 | 客户自行判断 |

L2 的管道（官方原文四步）：

1. **Research**：扫真实对话而非测试集。举例：847 条里 34 条失败，聚类根因 → 某 actionbook 分支漏了高价值退款的 eligibility check。
2. **Hypothesize**：不给「改提示」，给**具体 actionbook diff**（增/删/改逐条可见）。
3. **Human steer**：批准 / 限定范围（「别动第 3 步的升级逻辑」）/ 拒绝。每次决定被当作训练信号。
4. **Test & deploy**：对**同一批 34 条真实对话**迭代，85% → 94% → 100% 后上线。

L3 仍保留客户设定的 approval gates：财务阈值、合规要求、敏感话题。

> 这条链的形态与我们 `ChangeProposal → 评测 → 人工批准 → Release` 高度同构。差别只在**终点**：他们把 L3 定义为「人可以退出」，我们把「批准权」定义为不可由模型静默接管。

---

## 8. 与 Loomrise 六层逐层对照

| 六层 | Delight 对应物 | 差异性质 |
|---|---|---|
| `ContextSnapshot` | context objects（tier/region/language）+ `setCountry` + AMP 记忆 | 有注入通道与跨渠道记忆；**无来源/有效期/敏感级别/撤销的快照合同**，记忆与上下文不分层 |
| `RequestRouting` | 无显式对象。路由隐含在 actionbook 意图块 + 多 actionbook/知识按 locale 选择 + 渠道入口 | 缺「主请求 + 任务代次 + 下一步候选」的账本；同会话多业务请求如何记账未见 |
| `Skill/SOP` | **Actionbook** | **形态同构且工程化更强**：独立版本化、跨 Agent 复用、三视图导航、内嵌测试、可被 AI 提议修改。我们目前 SOP 是配置的一部分，不是一等资产 |
| `HardRule` | Safeguards（4 类内置 + 自定义）+ actionbook 里的阈值/升级文本 + kill switch | **根本分歧**：阈值写在自然语言里由模型解释；safeguard 也是概率分类器。我们有模型外裁决，没有它的可读性与运营自助 |
| `ToolPolicy` | 29 个集成 + MCP；工具调用状态可见 | 未见输入/输出约束、确认、预算、幂等、结果证据的显式配置；「该不该调」由 actionbook 文本约束 |
| `Outcome` | outcome-based testing 的断言 + resolution rate + 转工单/下单结果 | 它把 outcome 当**评测断言**，不是**执行终态合同**；未见统一结果 ID 与「模型声称完成不算完成」的纪律 |
| （无对应） | 资产级版本 + 选择性部署 + 灰度 + A/B | 我们是整包快照 + Release/Gate（未实现）；优劣见 §9 |
| （无对应） | 多 Agent 团队（数据隔离） | 对应我们的 ScenarioPack 边界，但它的隔离粒度声明更明确 |

---

## 9. 判断：三条结构性差异，七项可借，五项不借

### 9.1 结构性差异（决定能不能照抄）

**① 版本粒度：资产级 vs 整包快照。**
它的收益是「改一本 actionbook 不用重建 Agent」，代价是「当前生产 = 哪套资产组合」不是一等对象，只能靠部署记录还原。我们不改成资产级（回放可复现是硬要求），但**它的部署 diff 视图值得抄**——把「这次发布改了哪几项」摊开给人看，是低成本高收益的。

**② 规则表达：自然语言 SOP vs 模型外硬规则。**
它用可读性换确定性。它整套 Openbook/Tree 是在**补偿**可读性与可维护性，不是在解决确定性——真出问题仍靠重跑真实对话做统计修复。我们相反：确定性有了，运营改不了。**两边都不完整，不要互相说服**。可借的中间态是：`Skill/SOP` 层做成结构化文档 + 三视图（降低运营门槛），`HardRule` 层保持模型外（不放宽）。

**③ 门禁位置：装置齐全，门是软的。**
它有版本、diff、staging、灰度、A/B、approval gate，但公开资料中**未见**「测试不通过不得发布」的强制；`selective deployment` 的 diff 是给人看的，不是断言；ZTI L3 允许无人上线。结论：**这是「可观测 + 可回滚」的工程形态，不是「可验收」的治理形态**。我们 S2 的独立评测与人工批准不能因头部厂商这么做而松动。

### 9.2 可借（建议，待决策）

| # | 借什么 | 落点 | 需补的前置 |
|---|---|---|---|
| DL-1 | **真实对话 → 测试集**（conversation ID 建用例、label 分组、跨环境复用） | S2 评测集的语料来源 | 脱敏、授权、版本固定（它没提，我们必须有） |
| DL-2 | **outcome 断言三件套**：intent / outcome / workflow（SOP 分支命中 + 工具调用命中） | `S2-EVAL-GATE-PROPOSAL` 的断言类型 | 断言只能引用 `RunEvent` 已记录事实 |
| DL-3 | **结构化 SOP 三视图**（Source / Tree / Flow-导航）+ 点击跳转 + 同屏 Tester | `Skill/SOP` 编辑器（体验优化 §12） | Flow 只是导航，不得被读成执行图 |
| DL-4 | **部署 diff + 只读预览**（逐项变更可见，设置类也可回滚） | `Release` 的发布前确认页 | 与 `AgentVersion` 整包快照对齐语义 |
| DL-5 | **工具调用状态外化**（Thinking Messages） | ②b 体验开关的「进度播报」 | 与播报窗口、取消语义对齐 |
| DL-6 | **safeguard 触发后按类型分支回应 + 强制兜底文案** | `HardRule` 拒绝话术的结构 | 拒绝话术必须模型外可判定，不能靠生成 |
| DL-7 | **多 Agent 数据隔离声明**（knowledge / 会话历史不共享） | `ScenarioPack` 边界的对外表述 | 与多租户合同一致 |

### 9.3 不借

| # | 不借什么 | 理由 |
|---|---|---|
| N-1 | 用自然语言 if/else 承载价格、退款阈值、升级判定 | 与 `HardRule`「只引用已声明字段、模型外裁决」直接冲突 |
| N-2 | ZTI L2/L3 的自治发布 | 批准权不得由模型分数或优化作业静默接管 |
| N-3 | 外部 AI 客户端经 MCP 直接写生产配置 | 配置权威外流，绕开我们的评测与发布门 |
| N-4 | 记忆直接驱动主动触达 | 记忆不授予触达权（记忆 ≠ 授权 ≠ 任务） |
| N-5 | 资产级版本替代整包快照 | 破坏「同一版本冻结可回放」这一验收前提 |

---

## 10. 存疑与待确认

| # | 项 | 状态 |
|---|---|---|
| 1 | Actionbook 的完整 section 类型与 template syntax 语法 | D。仅知「behavioral rules / global actions / conditional blocks」三类，语法未公开 |
| 2 | 工具是否有 input/output schema、确认、幂等、预算、超时配置 | D。公开面只讲「连了哪些集成」，不讲调用约束 |
| 3 | 发布是否强制测试通过 | D。公开面只有「可测」「可 diff」「可回滚」，无「不通过则禁止发布」表述 |
| 4 | 是否记录业务结果 ID（订单号/工单号）并与对话绑定 | D。只知道会写回 Salesforce/Zendesk/ServiceNow |
| 5 | 定价、是否支持 self-host / VPC / 私有化 | D。sitemap 62 页无 pricing，仅 contact-sales；纯 SaaS 判断为 B- |
| 6 | 中文与中文语音的实测效果 | D。宣称多语言，中文客服场景未验 |
| 7 | 「人机一致率 97%」的定义与测量方法 | D。仅营销页出现一次 |
| 8 | `No improvised responses / no off-script risk`（C）与自然语言执行的机制关系 | 矛盾。判为营销表述，不采信为实现证据 |
| 9 | Openbook 的 Flow 视图是否被客户误读为 workflow 引擎 | 风险项。「not to trace decisions」写在博客正文，不在产品页 |
| 10 | Sendbird 与 delight.ai 的合同主体与产品边界 | D。官方称 delight.ai 是「Sendbird 的下一章」，文档仍托管在 `sendbird.com/docs`，采购时需确认 |

---

## 11. 事实 → 判断指针

| 本卷事实 | 指向 |
|---|---|
| §2.4 资产级版本 | §9.1-① |
| §4.1 一个 Agent 多本 actionbook + 按 locale 选择 | `RequestRouting` 的缺口补强思路 |
| §4.4 Actionbook = 结构化提示 | §9.1-②、N-1 |
| §5.3 context object 无治理字段 | `ContextSnapshot` 的差异化主张 |
| §6 MCP 写生产配置 | N-3 |
| §7.1 workflow verification | DL-2 |
| §7.2 Thinking Messages | DL-5 |
| §7.3 ZTI 四级 | N-2、§9.1-③ |
