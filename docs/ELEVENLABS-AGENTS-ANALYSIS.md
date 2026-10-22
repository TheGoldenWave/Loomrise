# ElevenLabs ElevenAgents：配置方案设计与能力边界 v0.5

> 2026-10-21。调研对象：[ElevenLabs AI 客服方案产品页](https://elevenlabs.io/zh/agents/ai-customer-support)（原文入口）、ElevenAgents 官方文档站（`elevenlabs.io/docs`，部分路径已从 `agents-platform` 迁至 `eleven-agents`，两套路径并存且互为重定向），以及**同日登录免费账户后的后台逐页实见**（§12）。
>
> **证据等级**：本文件**没有源码级证据**——ElevenLabs 是闭源托管服务，无法像 AgentScope／Pipecat／Qwen Audio Agent 那样逐行核对实现。全文按五级标注：
>
> | 等级 | 含义 | 本文件对应 |
> |---|---|---|
> | **A** | 源码／本地安装级 | **无源码**（闭源）；但 **API schema 达契约级**，标 **A-**（字段名、枚举、AST 类型取自官方 API 响应示例与请求体，见 §13） |
> | **B+** | **登录后台、界面逐页实见**字段、开关、空状态文案与路由（2026-10-21） | 配置页、测试编辑器、护栏表单、版本控制、渠道、设置、**Workflow 画布与检查器（§13）** |
> | **B** | 官方文档明确写出字段、默认值或范围 | 多数配置结论 |
> | **C** | 官方博客／产品页宣称，无字段级细节 | 时延、语言数、合规认证、成本 |
> | **D** | 未核／口径冲突 | 见 §6、§7 与 §12.5 标注 |
>
> **已做**：注册免费账户、从官方 Customer Support 模板建了一个真实 agent（`agent_8801m5…`，分支 `agtbrch_3201m5…`）、两轮走查 Overview／Configure／Monitor／Deploy 共 **18 个二级页**（第一轮见 §12.1–12.6，第二轮补齐 Spotlight／Dashboards／Architect／Triage／Workflow／Knowledge Base 三页签／Settings·Architect／Test Runs，见 §12.9），并查阅 branches 与 merge proposals 两份文档。**逐页核验状态表见 §12.8**——哪些看了字段、哪些只见结构、哪些没进，都在那张表里。
>
> **仍未做**：未调用 API、未跑真实会话（**被自身校验错误阻断，见 §12.8-C**）、未测时延／并发／中文识别质量、未购买电话号、未验证企业版能力（留存/脱敏/ZRM）。所有"可借"结论只表示**机制值得对照**，不表示已验证在本项目可行。本文件不修改任何既有文档的结论，只提出待确认项（§9）。

## 0. 结论先行

1. **ElevenLabs 已经不是"TTS 供应商 + 语音 demo"，而是与 Loomrise 定位重叠最深的托管式 Agent 交付平台。** 它的三段式（Configure → Deploy → Monitor）与 Loomrise 的"配置 → 试用 → 验收 → 发布"是同一根轴；差别在**裁决装置**：它把版本、分支、灰度、评测、实验都做成平台内自助功能，**有评审对象但没有强制门**（v0.2 修正：合并提案存在但非必选，且"测试必须通过才能合并"官方列为未来能力——见 §0.1-1、§12.5）。
2. **最值得对标的是它的配置对象模型**：`version` 是不可变快照，明确切成"随版本冻结"（prompt / LLM / voice / tools / KB / workflow / evaluation / data_collection / safety / widget）与"随实例固定"（auth / call_limits / queueing / privacy / analysis_llm / alerting）两组。这正好补上 Loomrise 六层里"实例级设置"当前表达偏薄的地方——**但不新增第七层**（§8 第 2 项）。
3. **它的"验收"是事后 LLM 判官 + 模拟用户测试，不是门禁。** 没有留出集、没有作者隔离、判据是自然语言（后台实测：**三类测试都没有"期望值精确匹配/参数断言"入口**）、判官模型可用低延迟模型。Loomrise 的 `golden/blind` 分离与"评测体系自身迭代"仍是实质差异，不应放弃。
4. **它的"硬约束"是语义级护栏，不是确定性裁决。** Custom Guardrail = 自然语言策略 + 轻量模型逐条判回复；官方明说护栏是 Alpha，且**对工具调用与参数没有校验机制**。因此它不能充当 `HARD-RULE-MODEL` 的合规底线——能借的是**退出策略枚举**与**streaming/blocking 的延迟—漏出权衡**这两个产品化取舍。
5. **能力边界集中在六处**：无内置跨通话记忆（官方博客明确）· 配置权威在平台账户且客户端可覆盖 prompt（overrides）· Widget 必须公开且关闭鉴权 · ZRM 下 LLM 只允许 Gemini/Claude · 批量外呼不能开 ZRM · 不可自托管（VPC 仅企业版）。

## 0.1 v0.2 修订：后台实见后的四处更正

**这四条是"照文档写会写错"的地方，阅读后文时以本节为准。**

| # | v0.1 的表述 | 实见事实 | 性质 |
|---|---|---|---|
| **1** | "**没有审批门**：合并分支或改流量百分比就是上线" | 有**提案对象**（Merge proposals）：合并前可要求"无 changes-requested + 至少一个非作者批准"。但**它是可选路径**——有目标分支写权限即可直接 merge，不必开提案。所以准确说法是：**有评审装置，没有强制门** | 表述过强 → 收窄 |
| **2** | "分支 ≠ 门禁"（结论正确） | **仍成立，且被官方文档原句确认**："To have a branch's changes reviewed before they're merged, or to reach a branch you don't have write access to, **open a merge proposal instead of merging directly**." 更关键的是官方把"**提案必须通过测试才能合并**"列为**未来数周才做**——**评测当门禁目前不在产品里** | 结论成立 → 补强证据 |
| **3** | 测试"工具调用参数校验：exact / regex / LLM 语义判定" | 后台**未见**参数级断言入口：Tool invocation test 只有"选工具 + Pass if any tool matches"（留空＝断言未调用工具）。是否只能走 API 尚未核 | 降级为 **D**，不当依据 |
| **4** | §7-1"无内置跨通话记忆" | 有 **Users 实体**（可按 user ID 搜、按 Agent／**Branch**／日期过滤），说明"用户"是平台一等对象。博客"voice agents 无跨通话记忆"仍成立，但**不能表述成"没有用户概念"**。**v0.3 补充：记忆入口已找到**——`Knowledge Base → Memory (Alpha)`，agent 级、可搜索、可按日期过滤、空状态为 `No memory entries found`（§12.9-1） | 需分拆：用户实体 ≠ 记忆；且"没有记忆"应改为"有记忆对象、但无 per-user 维度可见" |

**同时新增两个 v0.1 完全没有的对象**：**Procedures**（可复用的流程对象，含结构化步骤与变量表达式条件）与 **Architect**（Alpha 的 AI 迭代助手，能开提案但不能审批）。这两个是本轮最有参考价值的发现，见 §12.2、§12.3。

## 0.2 v0.3 修订：第二轮走查后的四处补充

**这一轮是"补页"，不是"改结论"。四条都是 v0.2 没看到的面。**

| # | v0.2 的说法 | 实见补充 | 性质 |
|---|---|---|---|
| **5** | "记忆机制本体未在 UI 找到入口" | **有入口**：`Knowledge Base` 三个页签之一是 **`Memory (Alpha)`**，agent 级、可搜索、只有日期过滤。→ 不能再写"没有记忆"，准确说法是**有 agent 级记忆对象集，但看不到 per-user 维度**，`Users` 与 `Memory` 两张表未打通 | 从"无"改为"有但粗" |
| **6** | 知识库能力按"文档 + RAG"记 | **`Retrieval mode` 有三档**：`On demand` / `Every turn` / `Prompt only`。后者官方原句是"知识库永不被检索，只把足够小的文档全文塞进提示"。→ **"不检索"是产品里的一等模式**，这会让 `source_ref`／引用溯源退化（EL-12） | 新增约束 |
| **7** | Workflow 只记"节点 + 自然语言条件边" | 节点检查器可**逐节点覆盖** Voice／LLM／Eagerness／Spelling patience／Speculative turn／Interruptible，未覆盖处显示 **`Using default`**。→ 存在"**版本 → 节点**"两级覆盖与**显式继承标记**，这是我们完全没有的粒度（EL-10） | 新增粒度 |
| **8** | "它的校验只到语义层" | **它有确定性结构校验**，且阻断发布：错误定位到 JSON 路径（`steps[0].branch.branches[0].steps`）+ 人话提示，有错时 `Preview`/`Publish` 双禁用。→ **结构校验（必填/引用/枚举）与语义判定在它那里是分开的两层**，这个分层值得照抄（EL-11） | 修正"只有语义校验"的印象 |


## 0.3 v0.4 修订：Workflow 深挖后的两处更正

**这一轮只动 Workflow，不碰其它章节的结论。两处都是"前两轮把它们看简单了"。**

| # | 前两轮的说法 | 实见 + API schema | 性质 |
|---|---|---|---|
| **9** | 「**边条件是自由文本自然语言**」（§8.2-10、§12.9-3） | **条件类型是枚举三选一**：`None`（无条件）/ `LLM Condition`（自然语言）/ `Expression`（变量 + 运算符 + 字面量的 AST）。模板与默认都走 `LLM Condition`，但**确定性分支有完整构造器**，且 `Expression` 里的操作数可以是 `Dynamic Variable`、`String`/`Number`/`True`/`False`/`Null`，也可以是 **`LLM Evaluation`** | 表述过强 → **改为"默认交给模型，但提供了确定性分支"** |
| **10** | 「评估顺序未提及」/「Procedures 与 Workflow 是两个并列功能」 | ① **边有 `edge_order`**，Start 节点检查器原句：`Edges higher in the list will be evaluated first.`（拖拽即排序）；② **每条边有 forward / backward 两个条件**；③ 官方 API 说清：**保存草稿/发布时 Procedures 被编译成 workflow 的 nodes + edges**，两者是"编辑态表达 → 执行态产物"的关系 | 关系修正 |

**本轮最有参考价值的单点**：它没有把"这条边由模型判还是由表达式判"做成二选一，而是**把模型判定降级成表达式 AST 里的一个叶子节点**（`{"type":"llm","value_schema":{"type":"boolean"}}`）。→ 一条规则可以混合确定性与概率成分，**且哪部分是概率的、在结构上一眼可辨**（§13.4、EL-14）。

详细见新增的 **§13 Workflow 深挖**（约 130 行，含节点类型枚举、四种条件类型、Expression AST、校验与阻断实测、Procedures→Workflow 编译关系、本轮可借 6 项 / 不借 3 项、EL-14…EL-16）。

## 0.4 v0.5 修订：扒完 368 篇官方文档后的三处更正

**这一轮没有新的界面实见，全部来自官方文档原文（B / A-）。三处都是"上一轮把'我没看到'写成了'它没有'"。**

| # | 上一轮的说法 | 文档原文 | 性质 |
|---|---|---|---|
| **11** | 「工具参数级断言**仅 API 侧存在**，后台只有『选工具 + Pass if any tool matches』」→ **降为 D 级**（§11 未核项） | `customization/agent-testing` 明列**三种参数断言**并各给示例：**Exact Match**（转接号码逐字）、**Regex Pattern**（`^ORD-[0-9]{8}$`）、**LLM Evaluation**（"应是一条礼貌的、提到已接通的留言"） | **恢复 B 级**。后台走查未走到该编辑面板 ≠ 该面板不存在。**这是方法错误，不是观察错误** |
| **12** | 「**无跨通话记忆**（官方博客）」「任何 per-user 记忆设置都没有」 | ① KB 有 `Memory (Alpha)` 页签（**agent 级**、可搜索、仅日期过滤、无 per-user 维度）；② `operate/versioning` 的**实例级设置表**里 `privacy` 一行写着 *Retention settings, zero-retention mode, and **user memories***——**全语料 368 篇中该词只出现这 1 次，无独立文档页、无字段 schema、无生命周期说明** | 表述过强 → **改为"有一个名为 user memories 的 per-agent 设置，但语义未文档化"**。可引用的结论只剩："它没有把记忆做成独立对象，也没有候选/裁决环节" |
| **13** | 「RAG 容量与检索参数**未核**」（§11） | 参数四项：`embedding_model`（如 `e5_mistral_7b_instruct`）、`max_vector_distance`（0.6）、`max_documents_length`（50000）、`max_retrieved_rag_chunks_count`（20）；延迟约 **250ms**；配额按档 **1MB / 2MB / 20MB / 100MB / 500MB / 1GB**；**<500 字节的文档无法索引**，自动改为塞进提示 | 已核，**升 B/A-**。同时拿到一条更重要的边界：**知识库文档内容不进版本快照，只有"挂载关系"进**（§8.1-1 的"版本=不可变快照"须带这个例外） |

### 0.4.1 本轮的净增事实（不改变 §8 的取舍）

1. **合并不要求测试通过是官方原句**，且"测试必须过才能合并"被官方列在 *Planned additions over the coming weeks* 里——**这是"方向被对手公开承认、位置还空着"的唯一一处**（详见专题卷 07 §3.3）。
2. **Architect 能开提案、不能批**（官方原句：*Architect can't review, approve, merge, or close a proposal*）——在一个不追求可审计的商业产品里也划同一条线，是我们"模型只提交候选、不得裁决"的**强外部佐证**。
3. **告警把"评估分下滑"做成了 monitor**（六类 monitor 之一）——质量被接进运维告警，而不是只放报表。
4. **排队只对"会释放的资源"有意义**（官方明确日限额不排队）——一条可直接搬的容量判断。
5. **`source_attribution` 默认 `false`**：引用出处在整个产品里是**双重可选**（检索可选、归属可选），不是默认义务。

### 0.4.2 专题卷

本轮把 368 篇文档拆成 9 卷，**结论仍只在本文件**，专题卷只承载事实与原文位置：

| 卷 | 主题 |
|---|---|
| [00 索引](competitive/elevenlabs/00-INDEX.md) | 证据分级、语料地图、三条贯穿性结构差异、六处官方自相矛盾 |
| [01 配置对象模型](competitive/elevenlabs/01-CONFIG-MODEL.md) | 三层结构、版本级 vs 实例级、关键默认值、草稿语义 |
| [02 编排](competitive/elevenlabs/02-ORCHESTRATION.md) | 提示/Procedures/Workflow 三档取舍、8 种步骤类型、节点/边/AST、编译契约 |
| [03 运行时与语音](competitive/elevenlabs/03-RUNTIME-VOICE.md) | 四计时器、三层打断、工具时序、9 个系统工具 |
| [04 知识与"记忆"](competitive/elevenlabs/04-KNOWLEDGE-AND-MEMORY.md) | KB 三页签、usage_mode、RAG 参数与配额、用户实体≠用户记忆 |
| [05 质量体系](competitive/elevenlabs/05-QUALITY-AND-EVAL.md) | 测试三类、参数断言三法、概率化分桶、三值评估、四类护栏、六 monitor |
| [06 渠道与电话](competitive/elevenlabs/06-CHANNELS-TELEPHONY.md) | Widget 鉴权硬边界、排队、批量外呼、WhatsApp 三条制度约束 |
| [07 治理与合规](competitive/elevenlabs/07-GOVERNANCE-COMPLIANCE.md) | 版本/分支/流量/提案、实验、Architect、工单、留存/ZRM/披露 |
| [08 能力对照矩阵](competitive/elevenlabs/08-CAPABILITY-MATRIX.md) | 88 项逐维查漏：他有我无 51 / 我有他无 11 / 形态不同 23 / 双方都缺 3 |
| [09 接入面：CLI 与 MCP](competitive/elevenlabs/09-CLI-AND-MCP.md) | 三条通道的分工（官方原句）、配置落盘形态、托管 MCP 的"直发"裂缝、入向 MCP 三档审批与合规互斥；对我方 6 条可落点 |

## 1. 产品形态：三层产品与四件套

| 产品 | 是什么 | 面向谁 |
|---|---|---|
| **ElevenAgents** | 全渠道 Agents 平台。跑在 Realtime 模型上，或跑在"完全级联且可配"的 pipeline 上（自定义 TTS／LLM／STT、workflows、evals、monitoring） | 做生产级 Agent 的开发者与企业 |
| **Realtime models** | 独立的 speech-to-speech 模型 API（低复杂度加语音） | 想最小改动加语音、或从别家实时 API 迁过来 |
| **Speech Engine** | 只把语音编排层拿出来，给已有文字 Agent 加语音 | 已有文字 Agent |

官方架构描述的四件套（B）：微调的 ASR 模型 · 自选 LLM（支持 custom LLM 接入）· 低时延 TTS（10,000+ 音色、70+ 语言）· **专有 turn-taking 模型**。

产品页宣称（C）：亚秒级延迟、90+ 语言、10,000+ 音色、SOC 2 Type II / GDPR / HIPAA、零留存模式、VPC 部署、端到端加密、400+ 预设集成（Salesforce／Zendesk／Twilio 等）。

> **口径冲突（D）**：文档写 **70+ languages**，产品页写 **90+ 语言**。采购或对比时不能引用任一数字作承诺，须以实测语言清单为准。同类问题见 §7 第 11 条。

## 2. 配置方案设计

### 2.1 配置对象的分层（本节是全文重点）

ElevenLabs 的 Agent 配置分成三块（B）：

```text
agent
├─ conversation_config            ← 随版本冻结
│   ├─ agent      : prompt(含内置工具)、first_message、language、llm、tools、knowledge_base、dynamic_variables
│   ├─ turn       : turn_timeout、turn_eagerness、soft_timeout、interruptions
│   ├─ tts        : voice_id、model、stability、speed、similarity_boost
│   ├─ asr        : keywords、质量参数
│   ├─ conversation: max_duration_seconds、text_only
│   └─ language   : 支持语言集与预设
├─ platform_settings（版本化子集） ← 随版本冻结
│   └─ evaluation / widget / data_collection / overrides / workspace_overrides / testing / safety(guardrails)
├─ workflow                        ← 随版本冻结（完整节点与边定义）
└─ per-agent settings              ← 不随版本（全部分支共享，只能在 main 改）
    └─ name / tags / auth / call_limits / queueing_config / privacy(retention、ZRM、user memories)
       / analysis_llm / topic_discovery / sentiment_analysis / simulation_library / alerting / ban
```

这个切分对 Loomrise 的价值不在字段，而在**"哪一组设置应该随版本走"这个判断本身**。对照六层：

| ElevenLabs 配置域 | 典型字段 | 随版本？ | Loomrise 对应 |
|---|---|---|---|
| `agent.prompt` / `first_message` / `language` | 系统提示、开场白、语言 | 是 | `AgentSpec` 内容层（`locked`/`mutable` 段落） |
| `agent.llm` | 模型、温度、max tokens | 是 | ②a 工程参数 / 模型档（`locked` 段列了"模型档"） |
| `agent.tools` + `dynamic_variables` | 工具集与参数 | 是 | `ToolPolicy` + 权限（`locked`） |
| `agent.knowledge_base` | 挂哪些文档、usage_mode | 是 | 知识**引用权**（`locked`）+ 条目内容（`mutable`） |
| `turn` / `tts` / `asr` | 话轮、音色、ASR 关键词 | 是 | ②a（产研）/ ②b（策略运营）——**切分不同，见 §2.2** |
| `evaluation` / `data_collection` | 判据与抽取字段 | 是 | 评测域（`Case` / `EvalSet` 的判据部分） |
| `safety`（guardrails） | 护栏策略与退出动作 | 是 | `HardRule` 的**语义近似物**，但不等价（§5） |
| `auth` / `call_limits` / `queueing_config` / `privacy` / `alerting` | 鉴权、并发、排队、留存、告警、分析用 LLM | **否** | 实例/平台级 → 当前散落，缺显式归属 |

**结论**：Loomrise 六层没有"实例级设置"这一格。ElevenLabs 的做法是**显式声明"这些不随版本走，且只能在 main 改"**，而不是让它隐式散落在部署配置里。这是一条可直接吸收的表达，不需要新增层（§8 第 2 项）。

### 2.2 会话流（话轮、打断、静音、超时）

字段与默认值（B，均在 `conversation_config`）：

| 设置 | 字段 | 默认 | 范围 | 说明 |
|---|---|---|---|---|
| 最大会话时长 | `conversation.max_duration_seconds` | **600s（10 分钟）** | 60–7,200s | 从会话开始计，独立于话轮超时 |
| 静音后接管 | `turn.turn_timeout` | 未给默认值 | 1–30s | 官方案例：客服 5–10s、信息收集 10–15s、免责声明 15–30s |
| 软超时填充语 | `soft_timeout` | **-1（关闭）** | 0.5–8.0s，推荐 3.0s | 每轮只触发一次；默认文案 `"Hhmmmm...yeah."`；支持按语言覆盖、客户端覆盖、LLM 生成（用最近 4 条消息 / 1000 字符） |
| 打断 | `interruptions`（Client Events 里的开关） | 启用 | 开/关 | 关闭用于"法律免责、安全说明必须完整听完" |
| 话轮急切度 | `turn_eagerness` | Normal | Eager / Normal / Patient | 官方推荐：客服 Eager、信息收集 Patient |

两个可迁移的机制点：

- **软超时是"填充语"而非"等待音"**：只解决"LLM 慢"这一段，且**禁止用带时间承诺的填充语**（官方明确不建议 "One second…"，因为真实耗时不可预测）。Loomrise 的 `VOICE-ARCHITECTURE-DECISIONS` D-03 只有"停—判—续"，没有"LLM 计算慢"这一支；这是缺口。
- **打断是"客户端事件"而不是纯服务端行为**：开关落在 client events 上，意味着打断能力取决于接入端（widget/SDK）是否订阅该事件。Loomrise 把打断当平台契约（①），更接近"不可协商"，两者取向不同。

**与 `§4.3-Q2` 的冲突（需裁决，见 §9 EL-1）**：ElevenLabs 把 `turn_eagerness`、`turn_timeout`、`interruptions` 当**业务可配的体验参数**；Loomrise 的 Q2 四档把"话轮/打断/静默窗"分别放进 ① 平台契约与 ②a 工程参数。三种处理都能自圆其说，差别在于**指标绑定**：Loomrise 的 Q8 已把"误停恢复时延 p95 / 复读率 / 漏判抢话"写成门禁指标，一旦话轮档位交给策略运营，指标阈值就必须跟着档位走，否则横向不可比。**建议**：话轮三档可进 ②b（体验开关），但**判定窗与首响预算仍留 ②a**，且阈值表按档位分列。

### 2.3 语音与语言

- 10,000+ 音色、70+ 语言（B）；支持 instant / professional voice cloning（产品页 C，且本项目排除音色克隆）。
- `language_detection` 系统工具：检测到用户换语言后可切换（参数 `reason` + `language`）。
- overrides 可换 voice_id、stability（0.0–1.0）、speed（0.7–1.2）、similarity_boost。
- **text-only 模式**：`conversation.text_only = true` 可开启纯文字会话；widget 侧三档 `Voice only（默认）/ Voice + text / Chat Mode（由文本发起）`。→ 与 Loomrise"文字与语音并列一等入口"同构，但它是**同一 agent 配置下的模态开关**，不是两套入口。

### 2.4 知识（知识库 / RAG）

| 项 | 值 | 等级 |
|---|---|---|
| 文件格式 | pdf / docx / txt / md / html / epub | B |
| 单文件大小 | ≤ 20MB | B |
| 来源 | 文件、URL、纯文本 | B |
| 使用模式 `usage_mode` | `auto`（默认：有索引则 RAG，否则全文）/ `prompt`（强制全文进系统提示） | B |
| 全文进提示的上限 | 约 **300,000 字符**，超过必须走 RAG | B |
| 文件夹 | **只能走 RAG**（永远不进提示） | B |
| 索引容量 | 按订阅档位 | B（具体数字未取得，D） |
| 共享 | 一份文档可挂多个 agent | B |

**与 Loomrise 的关键差异**：ElevenLabs 只有"整份文档挂不挂 + 用哪种方式用"，**没有"条目内容可变 / 引用权不可变"的分离**。Loomrise 的 `§4.3-Q2` 明确"知识必须分两件事：条目＝内容（可变），引用权＝事故面（locked）"，这条在本项目里是**独有设计**，不能被"文档级挂载"替代——文档级挂载无法表达"这段内容可以改措辞，但不能被这个版本的 Agent 引用"。

### 2.5 工具（含执行模式，本节最值得借）

五类工具（B）：**client tools**（客户端执行）· **webhook tools**（外部 API）· **code tools**（平台侧 JS 沙箱）· **MCP tools** · **system tools**（内置）。

系统工具八个（B）：

| 工具 | 关键参数 | 说明 |
|---|---|---|
| `end_call` | `reason`（必填）、`message` | 满足条件时结束会话 |
| `language_detection` | `reason`、`language` | 切换语言与音色 |
| `transfer_to_agent` | `agent_number`（0 基索引）、`reason` | 转给另一个 AI agent |
| `transfer_to_number` | `transfer_number`、`client_message`、`agent_message` | 转人工；分别给客户与坐席各一句 |
| `skip_turn` | `reason` | 不说话，等用户 |
| `play_keypad_touch_tone` | `dtmf_tones`（0-9 * # w W） | 走自动语音菜单 |
| `voicemail_detection` | `reason` | 检测语音信箱，可选留言 |
| `update_state` | 按配置生成的字段 | 按表达式更新 dynamic variables，不发外部请求 |

**执行模式（B，官方博客原文口径）**：

| 模式 | 行为 | 适用 |
|---|---|---|
| **immediate** | LLM 请求后立即执行 | 快速查询（订单状态） |
| **pre-tool speech** | 先说"我帮你查一下"，工具并行跑 | 减少静默等待；工具慢时平台自动延长填充语 |
| **post-tool speech** | **等 agent 说完再执行** | **有现实后果的动作：转接电话、结束会话、提交付款** |
| **async** | 后台跑，不暂停对话 | 发邮件、触发外部工作流、记数据（即发即忘） |

这三／四档解决的正是 Loomrise 目前只有原则、没有枚举的地方：

- `post-tool speech` = **"有副作用的动作必须在播报完成之后才执行"**。它把"用户听到'我现在为你转接'"与"真的挂断/转接"这两件事**排序**了，而不是并行。Loomrise 的 D-04 四件必证里有"失效结果不播"，但缺"副作用不得先于播报"这一条显式约束。
- `async` = 旁路执行、不占交互槽。与 D-04"不占交互槽"同义，但 ElevenLabs 把它做成**工具级属性**（同一个 agent 里不同工具不同模式），而不是全局开关。这个粒度更对：`lookup_order` 该 immediate，`send_email` 该 async，`transfer_to_number` 该 post-tool。
- 工具输出可按预定义映射写回 **dynamic variables**，成为"随对话演变的工作记忆"（B/C）。→ 可借为工作集的事实来源，但只能是**候选事实**，仍须过四道结构校验（`EXPERT-USER-MEMORY-SYSTEM` §4.2.1）。
- **没有平台级确认机制**：工具调用的时机与条件写在系统提示里（"验证身份后调用 lookup_order"），是否"先问用户再执行"完全靠提示词。→ **不借**：Loomrise 的人工确认是硬约束，不是提示词约定。

### 2.6 工作流（多子 agent 图）

节点类型（B）：**subagent**（在基础配置上追加或完全覆盖 prompt / LLM / voice / knowledge / tools）· **say**（`literal` 逐字说，可带按语言翻译；或 `prompt` 由 LLM 生成）· **dispatch tool**（强制调用，**唯一带成功/失败双边的节点**）· **update state**（经过即赋值）· **agent transfer** · **transfer to number** · **end**。

边条件（B；**v0.4 起以 §13.3 为准**）：`forward_condition.type` 是枚举 —— `unconditional`（None）/ `llm`（自然语言）/ `expression`（AST）/ `result`（工具节点的成功失败）。**每条边另有 `backward_condition`（回退），默认 None**；节点出边有 `edge_order`，列表顺序即判定优先级。**LLM 条件在系统提示之外并行求值，不进入生成**——官方明确这是为了"不污染提示、不影响回复生成方式"。

三个可注意的设计取舍：

1. **子 agent 切换时重建编排器对象**，上下文保留但知识/工具**选择性暴露**，防"知识孤岛"与跨职责信息泄漏。这是"角色隔离"的工程实现，比只写"不要越界"强。
2. **say 节点用 literal 兜住"不能说错的话"**（问候、法律告知、复述确认）——把不确定性从模型手里拿走。Loomrise 的 `locked` 段落协议本质上要的是同一件事，但 Loomrise 是"内容锁 + 人审"，ElevenLabs 是"节点锁 + 逐字播报"，后者更硬、更不可协商。
3. **官方自己承认工作流的代价**：需要严格步骤顺序或有确定性要求时才用，"否则优先单 agent"；并警告子 agent 会形成知识孤岛。→ 与 Loomrise"单 Agent 为主"判断一致，可作为外部佐证。

### 2.7 个性化：动态变量与 overrides（含一条硬边界）

- **dynamic variables**：会话级键值，可注入 prompt / first message / tools，可被工具输出与 `update_state` 节点/工具更新。官方推荐用它做个性化（可维护性、结构化）。
- **overrides**：**默认关闭**，须在 Security 里**逐字段**开启。可覆盖字段：system prompt、first message、language、voice_id、LLM、tools、knowledge_base、text-only、stability、speed、similarity_boost、ASR keywords（≤50 个/会话）。
- **硬边界**：一旦开启 `prompt.prompt` 覆盖，**客户端可以在建立会话时整段替换 system prompt**，也可替换工具集与知识库。

> 这与 Loomrise "稳定版本只读 + `locked`/`mutable` 段落 + 配置权威在版本"是**相反取向**。ElevenLabs 的 overrides 服务的是"一个 agent 服务多租户/多品牌"的 SaaS 场景，代价是**配置权威外泄到调用方**。可借的只有**窄粒度、非语义**的注入：ASR keywords（专有名词纠错）、first_message 里的人数与账户名。**不借** prompt / tools / knowledge_base 三类的运行时覆盖。

## 3. 版本、发布与实验

### 3.1 版本化（B）

| 概念 | 事实 |
|---|---|
| 开关 | **opt-in，一旦开启不可关闭**（永久变更） |
| version | **不可变快照**，ID `agtvrsn_*`；创建于保存时，创建后不可修改 |
| version 内容 | `conversation_config`（prompt/LLM/voice/tools/KB/first_message/language/turn/interruption）+ **部分** `platform_settings`（evaluation / widget / data_collection / overrides / workspace_overrides / testing / safety）+ 完整 `workflow` |
| branch | `agtbrch_*`；有不可删的 **Main**；可从任意分支的任意版本拉分支；可合并到任意分支；非 main 可 rebase 到 main；名字 ≤140 字符 |
| draft | **按人按分支**；提交新版本时丢弃；合并进分支时丢弃 |
| 流量 | 按百分比切分，**必须和为 100%**；按 `conversation_id` **确定性路由**（同一用户稳定到同一分支） |
| 冲突 | 默认取"最近修改"的一方；`force=True` 取源分支；`preview_merge` 可先看 `overridden_fields` 与 `conflicts` |
| per-agent 设置 | 只能在 main 改；在其他分支只读，且向非 main 发布时**丢弃**这些改动，之后合并也不带回 |

### 3.2 实验（B）

分支 + 流量 + 指标：CSAT、containment rate、转化、平均处理时长（AHT）、响应时延中位数、每次解决成本。**前置条件：必须先开版本化**。

### 3.3 与 Loomrise 的差别（这是最重要的一条边界）

| 维度 | ElevenLabs | Loomrise |
|---|---|---|
| 版本不可变 | 是 | 是（`AgentVersion`） |
| 分支 | 是（git-like，含 merge/rebase） | 否（草稿 → 冻结 → 新版本） |
| 上线方式 | **改流量百分比即上线**；合并即生效 | **评测 → 审批 → 发布** |
| 审批门 | **非强制**：可直接 merge；也可开 merge proposal 要求"无 changes-requested + 一个非作者批准"，但提案是 alpha 且可选（§12.5） | 强制（`ChangeProposal` + 人工批准） |
| 评测与合并的关系 | **互不绑定**：提案页有 `Test runs` 页签供人看，"测试不通过不许合并"被官方列为**未来能力** | 绑定：门禁不过不许发布 |
| 回滚 | branch/version 回切 + 流量归零 | 版本回退（且**不回滚记忆与决策史**） |
| 实验 | 平台内自助 A/B | 配对评估 + 留出集，不做生产流量实验 |

**必须说清的一句**：**分支不等于门禁。** ElevenLabs 的分支与灰度做得很完整（字段级 diff、确定性路由、preview_merge），但它把"谁来批准"留给组织，不留给系统。Loomrise 的差异点不在版本机制，而在**谁能改、改完凭什么算过**。可借的是前者的**机制**（不可变快照 + 字段级 diff + 确定性切分），不能借它的**放行方式**。

## 4. 测试与验收

### 4.1 三类测试（B）

| 类型 | 检什么 | 结构 | 限制 |
|---|---|---|---|
| **Simulation** | 整段多轮对话是否达成目标 | 场景描述（自然语言）+ success condition（自然语言）+ max turns **1–50，默认 5** | 判官是 LLM |
| **Next Reply（Scenario）** | 下一句回复质量/语气/合规 | chat history + success criteria + **正例与反例** 各给一条 | 只看一轮 |
| **Tool Call** | 是否调用正确工具、参数是否正确 | 选工具 + 参数校验：**exact / regex / LLM 语义判定**（**D**：后台 UI 未见参数级入口，仅"选工具 + Pass if any tool matches"，留空即断言未调用——见 §12.4） | 覆盖系统工具与自定义工具；**是否仅 API 侧支持参数断言，未核** |

配套机制：

- **从真实对话一键建用例**："Create test from this conversation"，从 call history 直接转成测试并加入 suite。
- **工具 mock**：`mock none / all / selected`；**系统工具与工作流工具永不被 mock**；fallback 可选"调真实工具"或"直接报错"。
- **概率化**：`repeat_count` 2–20（API）或 3×/5×/15×（UI）；输出 **pass rate**（绿 100%、琥珀 ≥80%、红 <80%）+ **失败分桶**（按失败原因聚类，可展开到具体 transcript 与判定理由）。
- **环境 / 历史 / 变量**：可选 environment、可从半段对话起跑（测恢复）、注入测试专用动态变量。

### 4.2 事后分析（B）

| 能力 | 结构 | 输出 |
|---|---|---|
| **Success evaluation** | 每条 = `identifier` + `description`（自然语言 prompt）；**≤30 条/agent** | `success` / `failure` / **`unknown`** + rationale |
| **Data collection** | 结构化字段（bool / string / integer…，建议用 enum 约束） | 每条会话的结构化抽取结果 |
| **Sentiment** | 逐用户轮次打分轨迹 | 正/中/负，可按主题聚合 |
| **Smart search** | 关键词 + 语义 | 跨会话检索 |

**评测与抽取用的 LLM 目前固定为低延迟模型**（官方博客，C），并称"近期会提供更多选项"。这解释了它为什么判据必须短、必须单目标——**不是设计偏好，是延迟约束下的妥协**。

### 4.3 Post-call webhook（B）

三种事件：`post_call_transcription`（转录 + 分析 + 元数据）· `post_call_audio`（仅 base64 音频）· `call_initiation_failure`（`busy` / `no-answer` / `unknown` + 供应商原始 `metadata.body`）。

`post_call_transcription.data` 关键字段：`conversation_id`、`agent_id`、`status`、`user_id`、`branch_id`、`version_id`、`environment`、`transcript[]`（含 `role` / `message` / **`tool_calls`** / **`tool_results`** / `time_in_call_secs` / `conversation_turn_metrics`）、`metadata`（`call_duration_secs` / `cost` / `termination_reason` / `feedback` / `authorization_method` / `deletion_settings`）、`analysis`（`evaluation_criteria_results` / `data_collection_results` / `call_successful` / `transcript_summary`）。

投递与安全：HMAC 签名头 `ElevenLabs-Signature`（SDK `construct_event` / `constructEvent`）；非 200 视为失败；**连续失败 ≥10 次且最近成功超过 7 天则自动停用**；音频走 chunked 流式，单请求 5 分钟超时，按 `conversation_id` 去重。

> 对本项目的直接价值：它给出了一份"一通会话应该落哪些事实"的**外部参考字段集**（版本 ID、分支、环境、每轮工具调用与结果、轮次级时延指标、终止原因、成本）。Loomrise 的 `RunEvent` 已覆盖大部分，缺的是**轮次级时延指标**与**终止原因枚举**的显式字段。

### 4.4 与 Loomrise 评测门禁的差距（不可让渡的四条）

| Loomrise 要求 | ElevenLabs 现状 | 结论 |
|---|---|---|
| `golden` 只判不退步、`blind` 按批次消费一次 | 无留出集概念；测试与生产同一 suite | 差异点，保留 |
| `blind` 不得由搭建者编写 | 无作者隔离；任何人可建测试 | 差异点，保留 |
| 判据须版本化（Rubric 版本）、跨版本分数不比较 | 判据是可随时改的自然语言 `description`，**无判据版本** | 差异点，保留 |
| 变更时不得有在途候选（禁止赛后改规则） | 无此约束，分支存活即可改判据 | 差异点，保留 |
| "判不了"要显式 | **有 `unknown` 三值** | **可借**（§8 第 7 项） |
| 重复采样不能过滤"引用真、推断假" | 有 `repeat_count` + 失败分桶，但**未声称解决该问题** | 可借机制，不可当结论 |

## 5. 安全与合规

### 5.1 Guardrails 2.0（B，文档自身标注 Alpha）

四类护栏，三层防护：

| 护栏 | 层级 | 延迟 | 成本 | 退出策略 |
|---|---|---|---|---|
| **Focus** | 系统提示强化（贯穿全程，防长对话漂移） | 极小 | 含在套餐 | 无 |
| **Manipulation** | **用户输入验证**（检测 prompt injection / 指令覆盖） | 无 | 含在套餐 | **终止会话** |
| **Content** | agent 回复验证（色情/暴力/政治敏感等分类 + 阈值） | 取决于模式 | 含在套餐 | 可配 |
| **Custom** | agent 回复验证（自然语言策略 + 轻量模型**逐条回复**判 block/allow） | 取决于模式 | **按量计费** | 可配 |

执行模式与退出：

- `streaming`（默认）：与回复并发生成，**几乎零延迟，但可能已播出不足 500ms 音频后才被拦截**。
- `blocking`：等校验通过再发，**+200–500ms**；官方建议"语音用 streaming、文字用 blocking"。
- 退出动作两个值：`end_call`（默认，会话立即结束，**不封禁用户**）· `retry`（**仅 blocking 可用**，移除违规轮次 → 注入反馈 → 重新生成，**最多 3 次**，仍违规则结束）。
- retry 反馈可注入 4 类策略：通用拒绝 / 带纠正指令重试 / 调 `transfer_to_agent` / 调 `transfer_to_number`；占位符 `{{trigger_reason}}`、`{{agent_message}}`。
- 所有触发都进对话分析（哪个护栏、做了什么动作）。

**三条必须写明的边界**：

1. **Custom Guardrail 是"模型判模型"**，概率性、逐条、按量计费、状态 Alpha。它不是确定性裁决，**不能替代 `HARD-RULE-MODEL`**（后者要求条件只能引用已声明字段、在模型外执行、可复现）。
2. **官方文档未提供对工具调用与参数的校验机制**。护栏只管"说的话"，不管"做的事"。→ 转接错号、下单错参数这类风险，ElevenLabs 靠提示词与 Tool Call 测试，不靠运行时强校验。
3. **streaming 模式的代价被写得很诚实**："a fraction of a second of audio may play before interception"。这条与 Loomrise D-02 的"不播过期内容 0 容忍"直接冲突——本项目不能接受"已播出再拦"。**可借的是它的坦诚口径，不是它的默认值。**

### 5.2 认证与入口（B）

| 方式 | 事实 |
|---|---|
| **Signed URL**（推荐） | 服务端用 API key 换临时签名 URL，**15 分钟过期**；会话可长于 15 分钟，但必须在窗口内发起；**不限制生成数量** |
| **Allowlist** | 最多 **10 个 hostname**，**精确匹配**（子域要逐条加） |
| 互斥 | **二选一**，不能同时配 |
| 已知局限（官方 FAQ） | 签名 URL 只证明"来源被授权"，**不能限制到具体用户**；要限人须在自己的应用里先认证 |

### 5.3 一条硬冲突（B）

> **Widget 目前要求 agent 是公开的、且关闭鉴权**（"Widgets currently require public agents with authentication disabled"）。

这意味着**网页嵌入与访客鉴权在它的产品结构里不可兼得**（要么公开挂 widget，要么用 SDK + signed URL 自建前端）。Loomrise 的网页客服是"访客入口 + 权限 + 版本"三者同时要，**这条不能借，但要记住它是托管平台的固有取舍**。

### 5.4 隐私与留存（B）

- **retention**：可设 0 天（即时删除）；HIPAA 场景官方建议 ≥6 年；GDPR 按处理目的对齐。
- **audio saving**：可关闭。
- **conversation history redaction**：**企业版**；文本替换占位符、音频替换哔声；可按实体类型细分（全部姓名 / 只脱敏姓；全部金融标识 / 只脱敏卡号）。
- **ZRM（Zero Retention Mode）**：企业版；数据只在内存、处理完不落盘、控制台也看不到转录与录音；**但 LLM 被限制为承诺不训练不保留的供应商——当前只有 Google Gemini 与 Anthropic Claude**；想用其他模型须自签协议 + 自定义 LLM + **安全团队人工审核**。
- **批量外呼不能开 ZRM**（须逐通发起）。

> **ZRM 的真实含义**：这不是"合规开关"，是**"合规模式与模型选型的耦合"**。开了它，你就不能再用别家模型；这恰好说明"合规不是一层配置，而是会反向约束模型选择"——Loomrise 在 `CONFIGURATION-LAYERS` 里把模型档放 `locked` 段是对的，但还缺"合规模式反向约束模型可选集"这条依赖。

## 6. 渠道与部署

| 渠道 | 能力 | 边界 |
|---|---|---|
| 网页 Widget | 多模态三档：voice only（默认）/ voice+text / chat mode；`<elevenlabs-convai>` 一行嵌入；支持 dynamic variables、overrides、client tools | **必须公开且关闭鉴权**；markdown 链接默认纯文本（防钓鱼），需按 host 白名单开放 |
| SDK | React / Next.js / Swift / Kotlin / React Native / Python | 复杂定制走 SDK |
| WebSocket API | 底层协议，自定义实现 | — |
| 电话（Twilio 原生 / SIP trunk） | 号码导入或购买；SIP 支持 TCP / **TLS 1.2+（生产推荐）** / UDP（实验）；编解码 **G.711（PCMU/PCMA, 8kHz）或 G.722（16kHz）**；支持自定义 SIP 头；NAPTR/SRV 发现 | 并发按订阅档；达上限默认**拒接**，可开 **queueing** 排队 + 等待音 |
| 批量外呼 | CSV/XLS 名单、动态变量列、立即或定时、单通试呼、进度与逐条状态；可指定 `target_concurrency_limit`（≥1） | 自动只用 **min(工作区并发 50%, agent 并发 70%)**；**不能开 ZRM**；名单可覆盖 `language / first_message / system_prompt / voice_id`（须先在安全设置里允许） |
| 其他 | Microsoft Teams（Graph media bot，含暖转接）· WhatsApp（**默认 15 分钟不活跃超时**，企业可申请调整） | — |

**部署形态**：托管 SaaS。VPC 仅企业版（产品页 C）。**没有自托管、没有私有化部署**——这条直接排除它作为 Loomrise 的交付底座。

## 7. 能力边界清单

| # | 能力 | 官方证据 | 边界 / 代价 | 对 Loomrise 的含义 |
|---|---|---|---|---|
| 1 | **跨通话记忆** | 官方博客明确："Voice agents do not have built-in memory across calls"。但后台有 **Users 实体**（按 user ID 检索、可按 Agent／Branch 过滤） | **用户实体 ≠ 记忆**：实体解决"认得这个人"，记忆解决"记得上次说过什么"；前者有，后者靠动态变量 + webhook 自己在外部拼 | 我们的记忆体系仍是真差异；**但别对外说"它没有用户概念"** |
| 2 | 配置审批 / 双人复核 | 有 merge proposal（alpha）：合并需"无 changes-requested + 至少一个非作者批准"；但**不强制走提案**，有写权限可直接 merge | 单人工作区下形同自批（未实测） | 门禁是差异点，保留；**注意它有对象而无强制** |
| 3 | 硬约束确定性 | Custom Guardrail = 自然语言 + 轻量模型；Alpha | 概率性；**工具参数不校验** | 不能作为合规底线 |
| 4 | 验收证据可复现 | 判据是自然语言 `description`，无版本 | 改判据不留痕 | 保留 Rubric 版本要求 |
| 5 | 网页入口 + 访客鉴权 | Widget 要求公开 + 关闭鉴权 | 二选一 | 不可借 |
| 6 | 配置权威 | overrides 默认关闭但可开；开启后客户端可整段换 prompt / tools / KB | 权威外泄到调用方 | 只借窄粒度注入 |
| 7 | 自托管 / 可迁移 | 无；VPC 仅企业 | 数据与配置都在平台 | 排除作底座 |
| 8 | 合规模式与模型选择 | ZRM 下 LLM 仅 Gemini / Claude；其他须自签协议 + 人工审核 | 合规反向约束模型 | 补"合规→模型可选集"依赖 |
| 9 | 批量外呼 | 自动只用部分并发；不能开 ZRM | 大规模外呼需拆批 + 放弃 ZRM | 与"主动触达"轴相关，需另评 |
| 10 | 知识容量 | 单文件 ≤20MB；全文进提示 ≤~300k 字符；文件夹只能 RAG | 大资料必须切分 + 索引 | 与"知识条目 vs 引用权"分离不冲突 |
| 11 | 多语言口径 | 文档 70+，产品页 90+ | **口径不一致** | 不得引用任一数字作承诺 |
| 12 | 评测判官 | 目前固定低延迟模型 | 判据必须短、单目标 | 解释了它的判据风格，不必模仿 |
| 13 | 会话时长 | 默认 600s，上限 7,200s | 长任务须外部承接 | 与"旁路委派"配套 |
| 14 | 版本开关 | opt-in 且**一旦开启不可关闭** | 无法回退到"无版本"状态 | 反面教材：开关要可逆 |
| 15 | 实例级设置 | 只能在 main 改，其他分支只读且发布时丢弃 | 多分支并行时易踩坑 | 借其"显式归属"，不借其"只能在 main" |

## 8. 对 Loomrise 的采用边界

### 8.1 可借（30 项，均为机制，不含任何"已验证"含义）

| # | 机制 | 落点 | 借法 | 等级 |
|---|---|---|---|---|
| 1 | **版本＝不可变快照 + 字段级 diff**（`preview_merge` 给出 `overridden_fields` / `conflicts`） | `S2-IA-NAV` 版本详情·边界页 | 草稿版本与稳定版本对比时，**按字段列出将被覆盖的项**，而不是只给一句"共 7 处改动" | B |
| 2 | **显式区分"随版本冻结"与"随实例固定"** | `CONFIGURATION-LAYERS` | 补一格"实例级设置"（并发、排队、留存、告警、分析用模型、鉴权），**归 ②a，不新增第七层** | B |
| 3 | **工具执行模式枚举**：immediate / pre-tool speech / post-tool speech / async | `TASK-SYSTEM-DESIGN`、`VOICE-ARCHITECTURE-DECISIONS` D-04 | 作为**工具级属性**而非全局开关；`post-tool speech` 补上"副作用不得先于播报"这条约束 | B/C |
| 4 | **工具输出 → 动态变量（工作记忆）** | `USER-CONTEXT-DESIGN` 工作集 | 只作**事实候选**，仍过四道结构校验；不进 system prompt 直拼 | B/C |
| 5 | **LLM 条件在提示外并行求值** | `HARD-RULE-MODEL` 的反面对照 | 作为"允许自然语言条件会怎样"的对照案例；Loomrise 仍只允许已声明字段 | B |
| 6 | **子 agent 切换时重建编排器、选择性暴露知识与工具** | 路由与角色隔离 | "阶段隔离"的工程做法：每阶段只可见其职责相关知识/工具 | B |
| 7 | **评测结果三值 `success/failure/unknown` + rationale** | `S2-EVAL-GATE-PROPOSAL` | 案例判定必须有"判不了"状态，禁止二值化 | B |
| 8 | **测试三分类 + 工具 mock（系统工具与工作流工具不 mock）+ 概率化 pass rate + 失败分桶** | `S2-EVAL-GATE-PROPOSAL` 新增提案（§9 EL-3） | "从真实坏例一键成用例"对应提名→案例；`repeat_count` 与分桶补齐重复采样口径 | B |
| 9 | **失败处置动作枚举**：结束 / 纠正重试（≤3 次）/ 转其他 agent / 转人工 | 硬规则与失败处置 | 与护栏解耦，单独作为"违规或失败后做什么"的枚举 | B |
| 10 | **软超时填充语**（仅覆盖 LLM 慢这一段；禁止时间承诺式文案） | D-03 播报窗口 | 补 D-03 缺的一支：不是"用户在说话"，而是"模型还没算完" | B |
| **11** | **流程作为独立对象 + `Used by` / `Uses` 双向引用**（Procedures） | `HARD-RULE-MODEL`、`S2-IA-NAV` 配置域 | 流程/规则抽成有 ID 的对象，才能被测试与判据 `@` 引用、才能反查"谁在用"。**这是 v0.1 完全漏掉的一层** | **B+** |
| **12** | **条件只由"变量 + 运算符 + 值"结构化拼装**（Expression 构造器），同时**允许**另一支自然语言条件 | `HARD-RULE-MODEL` 的反面参照 | 证明"只允许已声明字段"**可产品化**，且 UI 形态就是表达式构造器；我们不采纳它的自然语言分支 | **B+** |
| **13** | **判据带正反例**（Success / Failure Examples） | `S2-EVAL-GATE-PROPOSAL` 判据结构 | 极低成本提升判官稳定性；与"判据须版本化"不冲突（例子也是判据的一部分，须一起冻结） | **B+** |
| **14** | **判据声明作用域**（`Analysis scope: Conversation / Agent`）与**评分形态**（`Binary / Numeric`） | 案例集数据模型 | 我们"确定性真值 vs 软质量人评"分治需要对偶的产品表达：**判据必须自己说明"判整通还是判行为"** | **B+** |
| **15** | **逐条护栏/判据显示预估成本**（`≈$0.000171/min`） | 评测域 UI、成本可见性 | 策略运营要能看见"这条判据每千通多少钱"，否则评测预算无法协商 | **B+** |
| **16** | **`Flag issue for review` 作为系统工具**（模型可主动打标进复核队列） | `CaseNomination` 通道 | 与我们"一线坏例 → 只作提名、不等于真值"同构，但它是**模型自己提名**；须保留"提名 ≠ 判据"的红线 | **B+** |
| **17** | **显式继承标记 `Using default`**（节点未覆盖的字段直接标出"继承自上层"） | 配置域 UI（`S2-IA-NAV`） | 现在我们的配置页看不出"这个值是本层定的还是从版本继承的"。**把继承关系做成可见事实**，比在文档里解释层级便宜得多 | **B+** |
| **18** | **保存前结构校验 + 字段路径级错误定位**（`steps[0].branch.branches[0].steps` + "Step 1: Branch requires at least one step"，有错则 Preview/Publish 双禁用） | `ChangeProposal` 提交前、配置编辑页 | 纯确定性、可离线做。**错误定位到字段而非页面**是它能用的关键；只报"保存失败"等于没报（§9 EL-11） | **B+** |
| **19** | **部署检查清单**（Deployment checklist 10 项、显示 2/10） | 发布前检查（S2 配置域） | 借清单内容（`agents.md` / 偏好 / KB 同步 / 流程 / 采集字段 / 判据 / 上渠道 / 打标），但**必须标明"勾选 ≠ 验收通过"**，否则多一个假绿（§9 EL-13） | **B+** |
| **20** | **评测看板两图**：`Pass rate over time` + `Worst performing tests`（可按 Test/Branch 分组） | 评测域看板 | "最差用例排行"是失败分桶的最低成本形态：先按用例排序，不急着做聚类 | **B+** |
| **21** | **成功率与满意度分列两个指标**（`Overall Success Rate` / `Average CSAT Rating`，CSAT 由 widget 1–5 收集） | 人评页（Q4 决定的外部佐证） | 佐证"共情与语气单独一栏、不与确定性判据合并计分"；差别是它的 CSAT 只有分数、我们要求"评 + 改" | **B+** |

> **22–27 项见 §13.7**（Workflow 深挖的增量：模型判定作表达式叶子节点 · backward 边 · `edge_order` 优先级可见化 · 增量/覆盖字段分声明 · 拓扑关停 · 两段式结构校验）。不在两处重复表格，计数以 §13.7 为准。

**28–30 项（2026-10-22 新增，接入面；详见[卷 09](competitive/elevenlabs/09-CLI-AND-MCP.md) §7.2）**

| # | 机制 | 落点 | 借法 | 等级 |
|---|---|---|---|---|
| **28** | **配置落盘＝"注册表 + 分文件"，且 `--dry-run` 是一等命令** | `AGENT-INTEGRATION-PLAN` AGI-05（CLI） | 落盘形态给了"可迁移"一个物证：客户能把自己的 Agent 带走成**一个目录**。但**不照抄它的 `pull` 默认**（本地已存在即跳过 → 静默分叉）；我们要求**带 revision 比较的显式冲突** | **A-/B** |
| **29** | **Skills 从工具合同生成**（`generate-skills`：读内嵌 API 定义、离线、免 key、随 CLI 版本） | AGI-03 的空白（"分发"已定，"谁生成"未定） | 生成式 Skills 天然满足"披露可还原"（Tool ID / Schema 版本 / hash 与真实合同同源）；代价是生成物只覆盖"怎么调"，**"何时不该调 / 失败怎么处理"必须分文件存放**，否则重生成会覆盖人的判断 | **B** |
| **30** | **入向 MCP 逐工具审批三档 + 默认全批**（`require_approval_all` 默认；逐工具三分：自动 / 需批 / **禁用**） | `ToolPolicy` 的默认值与档位 | 新增外部工具默认需批准；补一档"**显式禁用**"（≠ 未配置）。它自己写明 `destructiveHint`/`readOnlyHint` **不能单独作安全依据**，可原样引为"声明不授予权限"的外部佐证 | **A-** |

### 8.2 不借（16 项）

| # | 不借 | 理由 |
|---|---|---|
| 1 | 自然语言策略当硬规则（Custom Guardrail） | 概率性 + Alpha + **不校验工具参数**；与"模型外确定性裁决"冲突 |
| 2 | 分支合并／改流量即上线 | 无审批门；与"评测→审批→发布"冲突 |
| 3 | 客户端可覆盖 prompt / tools / KB（overrides） | 配置权威外泄；Loomrise 的 `AgentVersion` 只读不可退让 |
| 4 | 工作流图作默认形态 | 官方自己承认知识孤岛与"否则优先单 agent"；Loomrise 已是单 Agent 为主 |
| 5 | 判据全自然语言 + 固定低延迟判官 | 不可版本化、不可复现、不可跨版本比较 |
| 6 | 用动态变量拼接冒充"记忆" | 那是会话级注入；与四类记忆（业务用户/专家/个人/配置）严格分开 |
| 7 | 托管平台作交付底座 | 不可自托管、不可迁移，与"开源、可迁移、可回滚"定位直接冲突 |
| **8** | **"分支即工作副本"的编辑模型**（改一处即时生效，只有 `Publish` 把分支推到生产） | 与 Loomrise"**保存 ≠ 提交**、稳定版本只读"直接冲突。我们要求"改到一半可以放着不生效且不污染稳定版"，分支模型做不到——分支内的半成品对同分支所有人都是生效的 | **B+** |
| **9** | **评测放在 Monitor 组**（看结果，不在发布主路径上） | 这是"评测不进合并门禁"的结构性原因。我们要把评测放在发布路径**内部**，不能照它的分组 | **B+** |
| **10** | ~~条件边用自然语言自由文本~~ → **把 LLM 自然语言条件当默认、且当唯一形态**（模板两条边的 `LLM Condition` 就是自然语言） | 分支判定若交给模型理解自然语言 → 不可裁决、不可枚举、不可确定性复现。**但注意（v0.4 修正）**：它有完整的 `Expression` 构造器（变量 + 运算符 + 字面量），可以写成确定性条件——**不借的是"默认这么写"，不是"只能这么写"**（§13.4） | **B+** |
| **11** | **`Prompt only` 检索模式**（官方原句：知识库永不被检索，只把足够小的文档全文塞进提示） | 与"资料可获授权 + `source_ref` + 引用溯源"直接冲突：不检索就没有出处。若引入必须**禁止该档或显式标为"无引用能力"**（§9 EL-12） | **B+** |

| **15** | **同一能力在多入口有不同写入语义**（应用内 Architect 走草稿+提案；托管 MCP **直接发布**到目标分支或 main，官方自标 Warning） | 同一个模型改同一个字段，从两个入口进，一个有审一个没有——这不是简化，是分裂。**验收口径：任何入口对同一资源的写入语义必须一致**；某入口做不到草稿，就**不给写权限**，而不是"给写权限但不走草稿" | **B** |
| **16** | **工作区级安全开关下放给"有写权限即可"**（MCP 开关：任何成员或任何带 `convai_write` 的 key 都能开，不限管理员） | 安全开关的权限应与风险同级。我们工作区级设置（告警阈值等）是**仅管理员**，这条口径要一致地贯彻到 MCP／连接器开关，不能因为"只是个集成"就放松 | **B** |

### 8.3 一句话定位差异

> ElevenLabs 把**"做出来、发出去、看效果"**做成了自助闭环；Loomrise 要补的是同一闭环上**"凭什么算过"的那一段**——版本不可变它也有，但它把裁决权交给组织；Loomrise 把裁决做成装置（`Case` / `EvalSet` / 留出集 / `ChangeProposal` / 审批）。**它的强项是工程化的话轮与工具时序，我们的强项是证据与门禁。二者不是替代关系，是对照关系。**

## 9. 新增待确认项（EL-1…EL-18，均不阻塞出稿；EL-14…EL-16 见 §13.9，EL-17…EL-18 见本节末）

| 编号 | 待确认 | 影响 | 阻塞出稿 |
|---|---|---|---|
| **EL-1** | 话轮三档（eager/normal/patient）与 soft timeout 是否进 ②b 体验开关（`§4.3-Q2` 四档切分需修订） | 若进，Q8 的三个指标阈值须**按档位分列**，否则横向不可比 | 否 |
| **EL-2** | 工具执行模式（immediate/post-speech/async）是否写入 `AgentSpec` 作为工具属性 | 影响 `§4.3-Q2` 段落协议：工具执行时序属 `locked`（事故面）还是 ②b | 否 |
| **EL-3** | 概率化重复次数（2–20）与失败分桶是否进 S2 评测口径；与现有配对评估是叠加还是替代 | 影响 `S2-EVAL-GATE-PROPOSAL` §5 预算与判定 | 否 |
| **EL-4** | "判不了"（`unknown`）是否进案例判定状态机 | 影响 `S2-DESIGN` 状态与 `S2-IA-NAV` 案例标注页的筛选项 | 否 |
| **EL-5** | 是否把 ElevenLabs 列为"外部托管对照/兜底 Provider"（而非交付底座） | 若列，须在 `OPEN-SOURCE-BOUNDARY` 记一条"外部托管不作为交付底座" | 否 |
| **EL-6** | **流程/规则是否升为独立对象**（Procedures 式：有 ID、可复用、可 `Used by` 反查、可被判据 `@` 引用） | 若升，`S2-IA-NAV` 配置域需新增一个二级页（当前 17 页 → 18 页），且 `HARD-RULE-MODEL` 要区分"规则对象"与"规则内容" | 否（但影响 S2 之后） |
| **EL-7** | 判据是否支持**正反例**与**作用域字段**（整通 / 单轮） | 影响案例集数据模型与 `S2-IA-NAV` 案例标注页的编辑区；正反例须与 rubric 一同冻结，否则"赛后改例子"等于改规则 | 否 |
| **EL-8** | 评测/护栏是否展示**单条成本预估** | 影响评测域 UI 与 `S2-EVAL-GATE-PROPOSAL` 的预算口径；与"策略运营看成本"这条使用者定义直接相关 | 否 |
| **EL-9** | 是否引入**模型主动提名**（`Flag issue for review` 式）并入 `CaseNomination` | 若引入，必须写死"模型提名不得直接成为真值"，且提名来源要能区分"人工' / '模型'"（`origin` 字段扩一值） | 否 |
| **EL-10** | **节点级覆盖 + 显式继承标记**（`Using default`）是否引入 | 我们的配置只挂 `AgentVersion`、粒度到底；它是"版本 → 节点"两级。若引入，`CONFIGURATION-LAYERS` 要新增"覆盖粒度"一轴，且评测冻结必须记录**哪些字段被本地覆盖**，否则同一版本号下两种行为不可比 | 否（但影响 S2-c 语音） |
| **EL-11** | **保存前结构校验 + 字段路径级错误定位**是否进 S2 | 纯确定性、可离线做，且与我们"条件只能引用已声明字段"同源。若做，`ChangeProposal` 提交前应有一步"结构校验"（必填/引用完整/枚举合法），错误定位到字段而非页面 | 否（建议做，成本低） |
| **EL-12** | **检索模式三档**（`On demand` / `Every turn` / `Prompt only`）是否引入 | `Prompt only` 一旦等于"资料全塞提示"，`source_ref` 与引用溯源即退化。若引入，必须**禁止该档或显式标为"无引用能力"**，并与"资料可获授权"准入条件对齐 | 否（但涉及定位承诺） |
| **EL-13** | 是否复制**部署检查清单**（Deployment checklist 式） | 它是人肉 checklist 不是门禁；但"上线前该确认什么"我们有共识却没有落成清单。若做，须标明"勾选不等于验收通过"，避免变成新的假绿 | 否 |

> **EL-17／EL-18（2026-10-22 新增，接入面；详见[卷 09](competitive/elevenlabs/09-CLI-AND-MCP.md) §7）**

| 编号 | 待确认 | 影响 | 阻塞出稿 |
|---|---|---|---|
| **EL-17** | **CLI 的配置落盘目录是否成为"可迁移交付物"的一部分**（客户带走的是"一个可 git 的目录"还是"平台导出包"） | 若成为，`OPEN-SOURCE-BOUNDARY.md` 要写清"带走的是什么、缺什么"（至少：MCP server 与知识库文档**进不了**它的版本库，我们若照抄形态会继承同一缺口）；`AGENT-INTEGRATION-PLAN` AGI-05 验收要加"revision 冲突显式化" | 否 |
| **EL-18** | **零留存／类 HIPAA 要求下，入向 MCP 是否整块禁用并登记进准入清单**（官方原句：ZRM / HIPAA 工作区不能用 MCP，且工作区开关不能覆盖） | 若登记，`PRODUCT.md` 三条准入里的"资料可授权"要扩一句：**外部 MCP server 是一个新的数据出口**，须与 `source_ref` 同口径审批；这条应在**准入阶段**问，不是实施时发现 | 否（但涉及准入措辞） |

## 10. 与既有文档的关系（只补引注，不改结论）

| 文档 | 本次动作 |
|---|---|
| `REFERENCE-PROJECTS.md` | 新增 **P0-10** 行（重点参考：配置对象模型 + 工具时序 + 版本/测试机制）；Sources 补官方文档入口；引言补一条时点说明 |
| `AGENT-CONFIGURATION-COMPARISON.md` | 新增一行"有，产品型配置后台（**商业托管，非开源**）"，并注明不能与开源清单同等计入 |
| `README.md` | "选型、竞品、记忆与语音研究"行的"继续查什么"补本篇 |
| `docs/context/INDEX.md` | §3-D 研究参照补一行 |
| `CONFIGURATION-LAYERS` / `S2-*` / `VOICE-*` | **不改**。EL-1…EL-5 登记在本文件；若确认采纳，再按单一权威原则写回各自权威文件 |
| `VERSION-PINS.md` | **不改**（无可 pin 的源码；若将来接入 API，须记 API 版本与账单口径） |
| 本文件 §12 | **v0.2 新增**。台后实见只补本文件自身证据等级与借法，**未改任何其它文档结论**；`REFERENCE-PROJECTS.md` 的 P0-10 行仍准确，未改 |
| `docs/competitive/elevenlabs/`（9 卷） | **v0.5 新增**。只承载**事实与原文位置**，不产生新结论；与本文件冲突时以本文件为准。新增事实若需改变取舍，一律回写到 §8 / §9，不在专题卷里改 |

## 11. 核验边界

- **证据性质**：v0.1 全部来自公开文档与官方博客／产品页；v0.2 增补免费账户后台的界面级实见（B+，§12）；v0.3 做了第二轮补页（§12.8 逐页状态表、§12.9 追加实见）；v0.4 做了第三轮 Workflow 深挖（§13），并首次拿到契约级证据（A-：API schema 的节点枚举、条件类型枚举、表达式 AST）；**v0.5 抓齐官方文档全集（368 篇原文，本地镜像 `_reference/elevenlabs-docs/`），把事实层拆成 8 个专题卷（§0.4.2），并回改了上一轮三处"把'我没看到'写成'它没有'"的表述（§0.4）**。仍然**无源码、未调用 API、无真实会话、无实测时延/并发/中文识别**——**会话详情页从未打开**，原因是自身校验错误阻断了 Preview/Publish（§12.8-C）。
- **v0.4 的一处实作副作用（如实记录）**：为验证 `Transition type` 的枚举，我把模板 agent 中 `Identify Issue → Troubleshoot` 一条边从 `LLM Condition` 改成了 `Expression`；改回 `LLM Condition` 后**原条件文本未被自动还原**，该 agent 因此停在 `Condition cannot be empty` 的 Error 态（`Preview` / `Publish` 双禁用）。随后错误态下该边检查器**无法再次打开**（连续两次鼠标事件超时），画布也一度整体不渲染。→ **样本 agent 需人工修复**：把该边 `Transition type` 保持 `LLM Condition`，并在 `LLM condition` 里填回 `The caller has a technical issue, API error, integration problem, or performance concern`。**这个副作用本身即 §13.5 那条"错误态可持久化且缺回退入口"的实证。**
- **界面 ≠ 契约**：UI 上看到的开关只说明"平台允许你点"，不说明默认值、上限、企业版差异。凡涉及配额、留存、ZRM、并发，仍以合同与 API 文档为准（D）。
- **单账户、单人、单 agent 样本**：无法验证多人协作相关能力（提案审批、reviewer 指定、protected branch），这些仍按官方文档（B）记录。
- **文档路径变动**：调研期间 `agents-platform` 与 `eleven-agents` 两套路径并存（后者为新路径，前者多可重定向）。同页可能出现两种口径（如护栏是否 Alpha），本文件已标注，未做仲裁。
- **产品页宣称不进入结论**：亚秒级延迟、90+ 语言、SOC 2 / HIPAA、400+ 集成均按 C 级处理，**不作为本项目承诺或对比基准**。
- **未核项（v0.5 已结清三项，余下如下）**：~~RAG 检索参数~~（已核，卷 04 §3）· ~~测试参数级断言是否仅 API 侧~~（已核，卷 05 §3）· ~~Users 是否含 per-user memory~~（已核，结论是"有设置名、无语义"，卷 04 §5.2）· `analysis_llm` 的实际可替换范围（枚举逾百项，但可用集是否受套餐限制未写）· Teams/CCAAS 之外的企业电话细节 · Enterprise 合同条款（留存/ZRM/并发/合规认证全在此）· **`vad` 类型的字段定义（API 文档该类型正文为空）** · **`trust_context` 三值的语义** · **`protection_status` 的实际拦截效果** · **中文与方言的打断/话轮表现（无任何第三方数据，且我们未实测）** · **工作区级 8 个页面（KB 库 / Tools / Integrations / Voices / Conversations / Users / Tests / Channels / Settings / Developers）未进**（§12.8-B）。
- **一条方法教训（写入文件以免重复犯）**：v0.4 曾因"后台没看到参数断言面板"把 B 级降为 D 级；v0.5 读到文档后恢复 B 级。**"未观察到"只能记为"未观察到"，不能记为"不存在"**。凡降级必须写明"在哪个界面、用哪种操作没看到"。

## 12. 后台实见（2026-10-21，登录后逐页核验，B+）

> 账户类型：免费层，个人工作区（`My Workspace`）。入口路径：`elevenlabs.io/app` → 左上平台切换器 → **ElevenAgents**（三个并列平台：ElevenCreative / ElevenAgents / ElevenAPI），首次进入需同意 ElevenAgents Terms。
> 样本 agent 由官方 **Customer Support** 模板生成，未填任何第三方凭据（Zendesk / Salesforce 均跳过），因此工具与渠道处于"未接通"状态——**这正是观察空状态与失败态的好机会**。

### 12.1 导航即产品模型（18 个二级页，四组）

```text
agent 侧栏（分支选择器常驻顶部：agent 名 → [Main ▾]）
├─ Overview   : Spotlight · Dashboards · Architect(Alpha) · Triage
├─ Configure  : Agent · Procedures · Workflow · Version Control · Knowledge Base
│               · Analysis · Tools · Guardrails · Settings
├─ Monitor    : Conversations · Tests · Users
└─ Deploy     : Channels · Outbound
```

三个结构性观察：

1. **配置页是"分支视角"，不是"版本视角"。** 所有路由都带 `?branchId=agtbrch_…`，连 `Tests`、`Users`、`Channels` 都带。分支是**贯穿全站的坐标**，版本只是分支上的提交点。对照 Loomrise：我们的 IA 是"专家 → 版本 → 配置"，**版本是坐标、没有分支**——这是根本形态差异，不是字段差异。
2. **`Tests` 在 Monitor 组，不在 Configure 组。** 它的定位是"看结果"而不是"配约束"；`Analysis` 反而在 Configure 组（因为它就是配置判据）。这个分组透出一个取向：**评测是监控的一部分，不是发布流程的一部分**。这正是 §0.1-2 的结构性原因——不进门禁，因为它不在 Configure 主路径上。
3. **`Settings` 只有三个子页：Advanced / Security / Architect。** v0.1 依据文档列的那些"实例级设置"（留存、并发、排队、告警、分析模型）在 UI 里被拆散了：分析模型进 `Analysis`，留存与 ZRM 不在 agent 级（应在工作区级），并发不在 agent 页。**"随实例固定"这组在 UI 上是散落的，文档里的分层比实现更整齐。**

### 12.2 Procedures：v0.1 漏掉的核心对象（最值得对标）

`Procedures` 是一个**独立、可复用、可被引用**的流程对象，官方一句话定义写在空状态里：**"Teach your agent to handle a specific task in natural language."**

创建入口五种：**Freetext / Structured / Folder / Import / Draft with Architect**。Structured 编辑器实测字段：

| 区块 | 内容 |
|---|---|
| 头部 | Procedure name · **Used by**（反向引用：哪些 agent 在用）· **Uses**（依赖：引用了哪些其它 procedure）· **Trigger** 开关 + "When should the agent use this procedure?" |
| Steps | **Ask**（向用户索取信息）· **Tell**（引导回复）· **Say**（**逐字播报**）· **If**（**Text** 自然语言 / **Expression** 表达式）· **Tool**（调外部工具）· **System tool**（调内置工具）· **Sub-procedure**（调另一个结构化流程） |
| Expression | 结构化构造器：**变量选择器 + 运算符（EQUALS…）+ 值**，另有 `Wrap in` 组合器——**不是自由文本框** |

这条对我们有直接价值，而且**比 Workflow 更贴近我们的场景**：

- **"流程从 prompt 里抽出来变成对象"**，才可能被测试引用、被判据引用、被反向查询"谁在用"。Loomrise 的硬规则与流程目前仍是版本内的一段文字 + 页面上的结构化编辑，**没有独立对象 ID**。这是 `HARD-RULE-MODEL` 之外一个值得讨论的形态（§9 EL-6）。
- **`Say` 节点 = 逐字播报**，与 v0.1 记录的 Workflow `say(literal)` 同源，但下沉到了流程对象层。对应我们的段落级 `locked`。
- **`If` 双形态（Text / Expression）正是我们争论过的那条线**：他们**两种都允许**，且把"表达式"做成变量+运算符的结构化构造器。我们 `HARD-RULE-MODEL` 只允许"引用已声明字段"，本质是**只保留 Expression 一支、并禁止自由文本**。他们的实现反而证明了这条约束**可产品化**——表达式构造器就是它的 UI 形态。
- **判定窗内的 `@` 引用**：测试判据与分析判据都能 "Type @ to select procedures to reference"，即**判据可以指着一个流程对象说"你按它做了吗"**。我们目前判据只能指向案例与 rubric 文本。

> 待核实：`Used by` 是**跨 agent** 还是仅当前 agent 内；procedure 是否随分支走（侧栏显示在 agent 内，推测随分支）。不影响借法。

### 12.3 Agent 配置页实测字段（`/agent`）

| 分组 | 实测字段与默认值 |
|---|---|
| 提示与开场 | System prompt（可 `{{` 插动态变量；右下角有 **Set timezone** 警告，未设时提示）；**First message**（含 **Disclosure Requirements** 外链、"**Interruptible**" 开关＝开场白可被打断，默认开） |
| 语音模式 | **Voice mode：Realtime（标 `New` `GA`）／ Custom** 二选一 —— 即"模型内全双工"与"可配置级联"是同一 agent 的两种运行模式 |
| 音色与语言 | Voices（1 个 Primary + 可加多个，标注"recommended for expressive models"）· Language（English Default + 可加语言） |
| 模型 | **LLM：默认 `Gemini 3.5 Flash`**（可换 provider/model）· **Agent behavior：`Default behavior`**（说明为"人格与按渠道的回复行为"） |
| 话轮模型 | 页内以**升级卡片**形式出现：**"Turn V3 — latest turn taking model, uses state-of-the-art contextual turn detection"**，按钮 `Switch to Turn V3` / `Dismiss` |

**两条对我们有用的**：

- **`Turn V3` 是一个可切换的、有版本的组件**，而且**平台主动推送升级**。这坐实 `VOICE-ARCHITECTURE-DECISIONS` D-01 的分层：**语义断句/话轮判定确实在 provider 侧、且会独立演进**，harness 不能假设它不变。→ 我们的"评测冻结四元组"里，**话轮模型版本必须进冻结项**，否则跨版本分数不可比。
- **`Interruptible` 是开场白级开关**（不是全局打断开关），这比 v0.1 记录的"client events 级开关"更细：**"这一句能不能被打断"是逐条消息属性**。对应我们 D-03 的"硬打断路径"——他们把它做成了内容级标注。

### 12.4 测试：结构比文档更"轻"，但有一个我们缺的设计

`/tests` 两个页签：**Attached Tests / Past Test Runs**。测试是**独立对象**（可建文件夹、可 `Detach from agent`、可被多个 agent 复用），右侧行操作为"从 agent 上摘除"而不是删除。

三类测试的实测表单（B+）：

| 类型 | 实测字段 | 判据形态 |
|---|---|---|
| **Simulation test** | Test name · **Describe simulated user scenario**（"we will use your instructions to generate a realistic conversation scenario"）· **Success criteria**（可多条，**支持 @ 引用 procedures**）· **Maximum conversation turns（默认 5，占位提示 20）** · **Mock all tools** + 选择具体 mock 哪些工具 · **Model configuration**（模拟用哪些 LLM，"更强模型可能更好但更贵"）· 动态变量 · **Simulated channel（默认 Default）** · 右侧逐条编辑对话 · **Edit as JSON** · **Attach to the agent automatically**（默认勾选） | 自然语言 |
| **Next reply test** | Test name · **Describe expected next message**（判"下一句"是否达标）· **Success Examples（可选）/ Failure Examples（可选）** · 动态变量 · Simulated channel · 左侧可编辑历史对话 | 自然语言 + **正反例** |
| **Tool invocation test** | Test name · **Tool to test**（**留空＝断言"一个工具都没调"**）· **Pass test if any tool matches** · 可选 Workflow **Node transition** 与系统工具 | 断言"调了/没调" |

**四个可直接借的设计**：

1. **判据带正反例**（Success / Failure Examples）。给 LLM 判官喂 1 条正例 1 条反例，比只写一段描述稳定得多，成本几乎为零。→ 我们 `S2-EVAL-GATE-PROPOSAL` 的判据目前只有 rubric 文本（§9 EL-7）。
2. **`Simulated channel` 是测试的必填维度**。同一句回复在语音与文字里判据不同（长度、复述、打断）。→ 我们的案例集目前没有"渠道"字段，这与"文字/语音并列一等入口"不匹配。
3. **Mock 是逐工具的**，不是全局开关。→ 可借为"副作用工具默认 mock、只读工具走真实"。
4. **"留空即断言未调用"**：把"不该发生的事"变成一等用例，而不是靠人工看 transcript。→ 我们的 golden 集应该有一整类"负向案例"（不该调用/不该承诺/不该外发）。

**必须写明的缺口**：UI 里**没有任何"期望值精确匹配"的入口**——没有期望回复文本、没有参数断言、没有阈值。三类测试的判定**全部落在自然语言判据或"是否调用"上**。这与我们"确定性判据 vs 软质量人评"的分治直接冲突：**它的"确定性"只到工具调用这一层，回答内容一律靠模型判**。

### 12.5 版本与提案：官方原句与路线图（关键更正）

`Version Control` 三页签：**Branches / Proposals / Contributors**。

- Branches 表列：Name · **Traffic Split** · **Conversations (7d)** · Status（`100% Live`）· Created by · Updated。按钮：**Graph** · **Traffic split** · **Create branch**。
- Proposals 空状态原句：**"No open proposals — Open one from a branch to have its changes reviewed before they reach the target branch."** 筛选器：Status / Created by / **Awaiting review from** / **Reviewed by**。
- 官方 versioning 文档原句：**"When you're satisfied with changes on a branch, merge them into another branch… To have a branch's changes reviewed before they're merged, or to reach a branch you don't have write access to, open a merge proposal instead of merging directly."** → **直接合并是默认路径**。
- Merge proposals **标注 alpha**，合并前置三条：① 对源与目标分支都有写权限（protected branch 需 workspace admin）② **没有任何 reviewer 的最新裁定是 "changes requested"** ③ **至少一个非作者的批准**（workspace admin 可越过）。
- 提案页四页签：**Overview / Changes / Test runs / Conversations** —— 也就是说测试结果**给人看**，供人做判断。
- **官方明确列为"未来数周"、当前没有的能力**（原文列举）：**Required tests that must pass before a proposal can be merged** · Requesting approvals from specific reviewers · Configuring owners for different parts of an agent。
- Architect 的行为边界（官方原句）：能**开提案**（"Because Architect acts as you, the proposal lists you as its author"），但**不能 review / approve / merge / close**——"Those steps are always done by people."

> **这三条合起来是一个强结论**：ElevenLabs 自己也认为"**评测不通过就不许合并**"是正确方向，而且**还没做**。这是 Loomrise 唯一一处**方向被对手公开承认、位置却还空着**的地方。它比"我们多了留出集"这种功能级差异重要得多。

### 12.6 其余实见（补 v0.1 的空缺）

| 位置 | 实测 |
|---|---|
| **Guardrails** | 四类：**Focus / Manipulation（默认 `Active`）· Content / Custom（默认 `Not enabled`）**。Custom 表单：Name · Prompt · **Estimated cost ≈ `$0.000171/min`**（逐条护栏显示预估成本）· Model（`Gemini 3.1 Flash Lite`）· Execution mode（`Streaming`）· **Evaluate full response only**（"仅适用于文本回复，不适用于语音会话"）· **Action on guardrail violation**（`End conversation` / `Retry`——**标注"仅 blocking 模式可用"**）· **Conversation history（Alpha）**（纳入多少条历史，默认 0） |
| **Tools** | 两个子页 **Tools / MCP**（MCP 是**逐 agent** 连）。System tools 实测 **9 个**开关：End conversation · Detect language · Skip turn · Update state · Transfer to agent · Transfer to number · Play keypad touch tone · Voicemail detection · **Flag issue for review**。★ v0.1 只记了 8 个，漏了最后一个 |
| **Analysis** | Default analysis model **`Gemini 2.5 Flash`**（可被单条判据覆盖）· Topic discovery · **Sentiment analysis（明示"只分析文本，不分析音频"）** · Analysis Language（Auto）· Auto-translate transcript · **Source Attribution**（"记录每次回复引用了哪些知识库来源，用于事后分析"）；判据编辑器：Name · **Evaluation instructions（@ 引用 procedures）** · **Scoring：Binary / Numeric** · **Analysis scope：Conversation / Agent** · Analysis model（默认继承） |
| **Settings · Advanced** | **Enable chat mode**（"创建纯文字对话 agent，不处理音频"——同一 agent 的模态开关，印证 v0.1 §2.3）· Allow file attachments · 内存中保留文件数 10 · 每会话最大文件数 10 · **Enable DTMF input**（"仅支持通过 Telephony / Twilio / Genesys 的带外 DTMF"）· **ASR 模型 `Scribe v2 Realtime`** · **Filter background speech**（"启用背景人声检测，过滤远处的人声"）· 输入音频 `PCM 16000 Hz` |
| **Settings · Security** | **Enable authentication**（默认关）· **Allowlist**（空时红字："No allowlist specified: Any host will be able to connect to this agent. We strongly recommend…"）· **Overrides 逐字段开关，默认全关**：Agent language / First message / **Workflow start node** / System prompt / LLM / Voice / Additional voices / Voice speed / Voice stability / Voice similarity |
| **Channels** | Telephony · WhatsApp · Widget · **Zendesk · Genesys · Intercom(Alpha) · Slack(Alpha) · Freshdesk(Alpha) · Telegram(Alpha) · Custom Channel(Alpha，入站 webhook 的通用异步文本)** |
| **Users** | 按 user ID 搜索，按 **Date / Agent / Branch** 过滤 |
| **Outbound** | 批量外呼列表 + `Create a batch call` |
| **模板** | 四个官方模板：Customer Support（2 integrations：zendesk_search / zendesk_add_comment + salesforce_search / salesforce_get_contact）· Language Practice Tutor · Front Desk Receptionist · Inbound Lead Qualifier。模板自带 **3 条测试**（未接凭据时全部显示 "Failed to load test / Tool not found"）、**1 条开场白 + 结构化工作流图**（Start → Identify Issue → 双分支 → Troubleshoot / Account & Billing → Resolve or Escalate → End） |

**由此得到两条对定位的判断**：

1. **它走"渠道寄生"，不是"交付工作台"。** Channels 里一半是别人的客服系统（Zendesk / Genesys / Freshdesk / Intercom）——它的产品假设是"你已经有工单系统，我把对话能力插进去"。Loomrise 的假设是"把资料做成可验收的版本"，**不依附任何既有客服台**。这条差异比任何单点功能都更能解释两者的用户不同。
2. **`Filter background speech` 就是 D-03 的 P1（说话人级归属）的产品化尝试**，但官方表述是"过滤远处人声"，是**声学/距离维度**，不是"这句话是不是说给助手的"。→ 我们的三级归属判定（P0 声学 / P1 说话人 / P2 语义）里，**行业目前公开能做到的是 P0 到 P1 之间**，P2 仍是空白。这条可作为 D-03 的外部佐证，也提醒不要对外宣称 P2 已满足。

### 12.7 仍未验证的部分（保持 D 级）

- 模板自带的 3 条测试**全部加载失败**（`Tool not found`），因此**未能看到测试库里一条真实测试的字段实例**，也**未能跑一次 Run All Tests**。
- **会话详情页从未打开过**——见 §12.8 的阻断原因。
- **未验证**：Tool invocation test 是否支持参数级断言（API 侧可能支持，UI 侧未见）；`Users` 里是否有 per-user memory；Merge proposal 的审批在**单人工作区**是否形同自批（缺第二人无法实测）。
- 副作用：工作区多了一个 `Customer Support` agent 与一个空的 `Untitled Procedure`，**未删除**（保留作后续复测样本）。**注意：这个空 procedure 现在使整个 agent 处于校验失败状态**（§12.9-4），Preview 与 Publish 均被禁用——它既是有用的样本，也是当前的最大障碍。

### 12.8 页面清单与核验状态（回答"是不是每页都看了"）

**先说结论：不是每页都看到了字段级，有一部分只看到结构、有一部分被阻断、工作区级有一半根本没进。** 下表逐项交代，状态只有三种：**实见字段**（看过字段名与默认值）／ **只见结构**（看过页面骨架与空状态，字段未展开）／ **未达**（打不开或没有数据）。

**A. agent 级 18 个二级页**

| # | 页面 | 状态 | 备注 |
|---|---|---|---|
| 1 | Spotlight | **实见字段** | per-agent 首页：`Ready to chat` + 三条入口（开始对话／配 agent／读文档）+ `View Dashboards` |
| 2 | Dashboards | **实见字段** | 13 个指标页签，见 §12.9-9；只逐页看了 General／Evaluation／Data Collection／Queue／Audio |
| 3 | Architect (Alpha) | **实见字段** | Home/Inbox 双页签、7 类可触达对象、Deployment checklist 10 项、alpha 免费到 2026-10 |
| 4 | Triage | **实见字段** | 工单板四状态，见 §12.9-2 |
| 5 | Agent | **实见字段** | 见 §12.3 |
| 6 | Procedures | **实见字段** | 见 §12.2（后被自己的空实例污染成错误态） |
| 7 | Workflow | **实见字段** | 画布 + 节点检查器，见 §12.9-3 |
| 8 | Version Control | **实见字段** | 三页签 Branches/Proposals/Contributors，见 §12.5 |
| 9 | Knowledge Base | **实见字段** | 三页签 Sources／**Memory (Alpha)**／**Retrieval**，见 §12.9-1 |
| 10 | Analysis | **实见字段** | 见 §12.6 |
| 11 | Tools | **实见字段** | Tools + MCP 两子页，system tools 9 个 |
| 12 | Guardrails | **实见字段** | 四类 + 逐条成本，见 §12.6 |
| 13 | Settings | **实见字段** | 三子页 Advanced／Security／Architect，见 §12.6 与 §12.9-5 |
| 14 | Conversations | **只见结构** | 只有空列表（`No results`）；**会话详情页未打开** |
| 15 | Tests | **实见字段** | 三页签 Attached Tests／Past Test Runs；测试实例全部加载失败 |
| 16 | Users | **只见结构** | 只有搜索框与过滤维度，无数据 |
| 17 | Channels | **实见字段** | 见 §12.6 |
| 18 | Outbound | **只见结构** | 只有列表与 `Create a batch call` 按钮 |

**B. 工作区级（同一平台内，不属于任何单个 agent）**

| 页面 | 状态 | 备注 |
|---|---|---|
| Home | **实见字段** | 与 agent Dashboards 同构；另有 `Overall Success Rate` 与 `Average CSAT Rating` 两块独立卡片（§12.9-7） |
| Agents（列表） | **只见结构** | 只有我自建的一个 agent |
| Knowledge Base（工作区库） | **未达** | 未进 |
| Tools（工作区） | **未达** | 未进 |
| Integrations | **未达** | 未进 |
| Voices | **未达** | 未进 |
| Conversations（工作区） | **未达** | 未进 |
| Users（工作区） | **未达** | 未进 |
| Tests（工作区） | **未达** | 未进 |
| Channels（工作区） | **未达** | 未进 |
| Phone Numbers | **只见结构** | 只有 `Import number`，无购买入口；docs 指向 Twilio 原生集成 |
| WhatsApp | **未达** | 未进 |
| Settings（工作区） | **未达** | 未进（留存/ZRM/并发/账单预计在此，未核） |
| Developers | **未达** | 未进（API key、webhook 预计在此） |

**C. 为什么会话详情页打不开（唯一硬阻断）**

Preview 与 Publish 都被置灰，顶栏 `Publish` 变成红色 `Error`，点开是 **Validation details**：`Procedures → Untitled Procedure → steps[0].branch.branches[0].steps → "Step 1: Branch requires at least one step"`。即**我建 agent 时留下的那个空 procedure 让整个 agent 不合法**，于是无法对话、无法发布、无法产出任何一条会话记录，`Conversations` 与 `Triage` 只能看到空板。

→ **要看会话详情，必须先处理掉那个空 procedure（补一步或删除）。这一步我没有替你做**，它是你账户里的对象，等你一句话。

### 12.9 第二次走查的追加实见（2026-10-21 晚，补 §12.1–12.6 的空缺）

1. **Knowledge Base 有三个页签，v0.2 只记了"资料"一个面**：`Sources` / **`Memory (Alpha)`** / **`Retrieval`**。
   - `Memory (Alpha)`：空状态 `No memory entries found`，检索框 `Search memory entries...`，过滤维度只有 `Date After` / `Date Before`。→ **记忆是 agent 级的一个可浏览对象集**，不是黑盒；但**没有 per-user 维度可见**（`Users` 页有 user ID，两者未打通）。
   - `Retrieval`：**`Retrieval mode` 三档 —— `On demand` / `Every turn` / `Prompt only`**（当前 `Prompt only`）。官方说明原句：**"Your knowledge base is never searched. The agent only sees the documents small enough to be included in its prompt in full."** → **"不检索"是产品里的一等模式**。这对我们是个警告：`Prompt only` 一旦等价于"资料全塞提示"，`source_ref` 与引用溯源就退化为空；我们若要引用溯源，**必须禁止这一档或显式标为"无引用能力"**（EL-12）。
2. **Triage 是工单板，不是列表**：四状态 `Pending / In progress / Resolved / Cancelled`，列 `Creator / Assignee / Created`，按钮 `New ticket`、`Status`、`Filter`、`Sort`。顶栏**没有** `Publish`（不随发布走）。
   → 这是"一线坏例 → 待调查"最接近的行业形态；与我们 `CaseNomination` 的差别是**它带 assignee 与状态流转**（有人认领）。四条状态可直接对照 Q6 五值投影：`Pending→已提交`、`In progress→处理中`、`Resolved→已结束`、`Cancelled→已结束(取消)`，**它没有"需补充信息/需授权"两支**。
3. **Workflow 是画布 + 节点检查器，且语音参数可逐节点覆盖**：节点检查器五页签 `General / Knowledge Base / Tools / Tests / Edges`；`General` 里除 `Conversation goal`、`Override prompt` 开关外，还有 **Voice / LLM / Entry behavior / Eagerness / Spelling patience / Speculative turn / Interruptible**，未覆盖的字段右上角标 **`Using default`**。
   → 两点：**① 显式继承标记**（`Using default`）是我们完全没有的 UI 语言，它把"这个值是从上层继承的还是本地覆盖的"变成可见事实；**② 语音行为参数是节点级、不是 agent 级**——这比我们 Q2 的四档切分更细，多出一根"覆盖粒度"的轴（EL-10）。
   → 另一面：模板里**两条边都用 `LLM Condition`（自然语言自由文本）**。**v0.4 修正**：这只说明"默认交模型判"，不代表它没有确定性方案——边检查器的 `Transition type` 是 `None / LLM Condition / Expression` 三选一，`Expression` 是"变量 + 运算符 + 字面量"的完整构造器（§13.3、§13.4）。**不借的是"默认把判定交给模型"，可借的是它把概率判定降级为 AST 叶子节点的做法。**
4. **存在确定性的结构校验，且阻断发布**：`Validation details` 弹窗把错误定位到 **JSON 路径**（`steps[0].branch.branches[0].steps`）+ 人话（`Step 1: Branch requires at least one step`），并给 `Discard changes`。有错时 `Preview` 与 `Publish` 双禁用。
   → 这坐实一件事：**"保存前必须通过结构校验"是能产品化的**，而且**错误要定位到字段而非页面**。与我们的关系：这类校验（必填、引用完整、枚举合法）**正好属于确定性可裁决的那一半**，应当与"内容对不对"彻底分开——他们也正是这么分的（结构校验在前，语义判定交给测试与人）。
5. **Settings·Architect 划出了一条我们也在划的边界，而且用原句说清了**：四个子项 `Agent context (agents.md)` / `Organization` / `Your preferences (user.md)` / `Prompt library`。原句：**"Stored as agents.md and sent to Architect at the start of every conversation… This only guides how Architect helps you build the agent; it does not change the agent's own behavior or runtime prompt."**
   → 这就是我们的**第 ③ 类记忆（搭建者个人记忆，明确排除在产品运行时外）**，他们做了同一刀，并且**写在界面上**。可直接引为外部佐证：`EXPERT-USER-MEMORY-SYSTEM.md` 的 ①②③ 分治不是我们的洁癖。
6. **`Past Test Runs` 是真正的评测看板**：两张图 **`Pass rate over time`** 与 **`Worst performing tests`**（可 `Group` 按 Tests 分组），过滤维度 `Branch` / `Test` / `Granularity` / `Group by`，主按钮 `Run All Tests`。
   → **"最差测试排行"是失败聚类的最低成本形态**，我们 `S2-EVAL-GATE-PROPOSAL` 里"失败分桶"可以直接借这个入口形态（按用例排序，不做聚类算法）。
7. **成功率与满意度是两个指标，不合成一个分**：工作区 Home 除会话数/时长/成本外，单独两块卡片 `Overall Success Rate` 与 `Average CSAT Rating`；CSAT 说明原句 **"Enable feedback collection in an agent's widget to let callers rate conversations from 1 to 5."**
   → 对应我们 Q4 的决定（共情与语气单独一栏、不与确定性判据合并计分）：**行业里也是分开摆的**。差别是它的 CSAT 只有 1–5 一个数（用户打分），我们的 `人评与修正` 是**评 + 改**（评完还能给出修正内容）。
8. **`Testing` 页签直接跳 `tests/runs`**：Dashboard 的 13 个页签里，`Testing` 是唯一一个**离开看板跳去另一个页面**的，其余都是同构指标页。
9. **Dashboards 13 个页签**：`General / Evaluation / Data Collection / Workflow / Audio / Queue / Tools / LLMs / Topics / Knowledge Base / Guardrails / Advanced / Testing`。
   - `Queue` 页签实为指标（`Queued` / `Average Queue Time`），**不是排队配置** → 坐实 §12.1-3 的"排队不在 agent 页"。
   - `Audio` 页签是**独立的时延看板**（`Agent Response Time`、`Response Generation L…` 等）。
   - `Evaluation` / `Data Collection` 两个空状态都写"去 analysis settings 里加判据" → **指标是判据的投影**，先有判据才有图。
10. **Architect 页的实际内容比文档描述的更像一个"建造者控制台"**：输入框占位 `Ask Architect to build a tool, fix a behavior, or investigate an alert. Type @ to reference, / for commands...`；下方一排七个图标直达 `Agent / Procedures / Tools / Knowledge Base / Tests / Analysis / Guardrails`；右侧 `Deployment checklist` 10 项勾选（`agents.md` / `user.md` / KB auto-sync / procedures / 采集字段 / eval 判据 / 上渠道 / flag issues…），当前 2/10（20%）。页内提示 **"Architect is now available and free to use during the alpha, through October 2026."**
    → **"部署检查清单"是它的上线前置**，本质是一份**人肉 checklist**（不是门禁），但它的存在说明"上线前该确认什么"在产品里是有共识清单的。我们 S2 的"发布前检查"缺这份清单的等价物。

## 13. Workflow 深挖（2026-10-21 第三轮，界面 B+ + API schema A-）

> 触发：Jason 指出 Workflow 值得重点看。前两轮对 Workflow 的记录只到"画布 + 节点检查器五页签"，既没看边的条件类型枚举，也没看变量与表达式的结构。本节补齐，并**修正前两轮两处过强的判断**（§13.8）。
>
> 证据：① 后台实见（B+，节点检查器、边检查器、全局设置、画布工具栏、autosave 行为）；② 官方 API schema（**A-**：字段名、枚举值、AST 类型来自 `GET /v1/convai/agents/:id` 响应示例与 `POST .../drafts`，是契约级而非界面级，但仍未自行调用）。

### 13.1 作用域是三层，不是两层

```
Agent（system prompt / voice / LLM / language / tools / KB / analysis）
  └─ Workflow 全局（Global settings：prevent_subagent_loops）
       └─ 节点 Node（conversation_config 覆盖 + additional_prompt / additional_KB / additional_tool_ids）
```

- 节点检查器 `General` 页签里，**未覆盖的字段右侧标 `Using default`**，且该标记是**可点的入口**（点开即"覆盖"）。
- **`Entry behavior` 是唯一没有 `Using default` 的字段** —— 它是节点级专有概念，不属于 agent 继承链。
- 节点的知识库与工具是**增量语义**（API 字段名 `additional_knowledge_base` / `additional_tool_ids` / `additional_prompt`），不是"替换"。但 `conversation_config` 是**覆盖**语义。**同一层里两套语义并存**（增量 vs 覆盖），这是它自己也容易踩的地方——做对照时不要假设"节点 = 全量快照"。

> 对我们的意义：EL-10 里"覆盖粒度"这根轴现在有具体形状了——**增量字段与覆盖字段必须分开声明**，否则"这个节点用了哪些工具"永远说不清。

### 13.2 节点类型（API 枚举 + 界面可见）

| `node.type` | 界面名 | 关键字段 | 说明 |
|---|---|---|---|
| `start` | Start | `edge_order` | 入口。**没有出边即工作流被禁用**（Global settings 原句：`To disable a workflow, disconnect the start node.`）——用拓扑而不是开关来关停 |
| `override_agent` | 子 agent 节点 | `conversation_config`、`additional_prompt`、`additional_knowledge_base`、`additional_tool_ids`、`entry_behavior`、`label` | 最常用。`entry_behavior` 默认 `auto` |
| `standalone_agent` | Agent transfer | `agent_id`、`delay_ms`、`drop_history`、`isolate_history`、`preserve_voice_settings`、`preserve_client_tts_overrides`、`enable_transferred_agent_first_message` | 跨 agent 交接，**历史可丢弃/隔离/保留**是显式字段 |
| `tool` | Dispatch tool | `tools[{tool_id}]` | **保证调用**。唯一带"结果边"的节点 |
| `phone_number` | Transfer to number | `transfer_type`（`conference`）、`require_acceptance`、`sip_refer_play_dialtone`、`custom_sip_headers`、`transfer_destination` | 转人工 |
| `end` | End | `outcome`（`success`）、`return_when_nested` | 结束；`return_when_nested` 决定是否只退出子图 |
| （文档另有） | Say | 模式 `literal`（逐字，可按语言给翻译）/ `prompt` | 见 §2.6-2 |
| （文档另有） | Update state | 赋值表达式 | 经过即赋值，与 LLM 自主调 `update_state` 工具分开 |
| （schema 另有） | `subgraphs` | — | **支持嵌套子图**，顶层 `workflow.subgraphs` 字段 |

**`say` 与 `update state` 的出现说明它把"确定性动作"从模型手里拿走了两类**：说什么（逐字）与记什么（赋值）。这两类恰好是我们 `locked` 段落协议与"配置不能被模型改"的交集。

### 13.3 边：四种条件类型、双向、有顺序

**条件类型是枚举，不是自由文本**（API：`forward_condition.type`）：

| `type` | 界面名 | 字段 | 判定性质 |
|---|---|---|---|
| `unconditional` | None | —（无条件通过） | 确定性 |
| `llm` | LLM Condition | `condition`（自然语言）+ `label`（**不送模型**，仅展示） | **概率性** |
| `expression` | Expression | `expression`（AST，见 §13.4） | **确定性**（除非 AST 里含 `llm` 节点） |
| `result` | （工具节点专有） | `successful: true/false` | 确定性，来自工具结果 |

**每条边有两个方向的条件**：`forward_condition`（前进）与 `backward_condition`（回退）。界面是两个页签 `Forward | Backward`，回退页签打开时标题会**反向显示**（`Troubleshoot → Identify Issue`），默认 `None`。

→ **"回到上一个节点"是边的一等属性，不是 hack**。对话里用户改主意（"算了，我问的是另一件事"）就走 backward 回到分类节点。对照我们：Loomrise 的对话流没有回退语义，只有任务态回退（`reconciling` / 重试），**这是真实缺口**。

**顺序即优先级**（Start 节点检查器原句）：`Configure the order in which outgoing edges are evaluated. Edges higher in the list will be evaluated first.` 拖拽排序，列表顺序即 `edge_order`。

→ 这一条比"边有优先级"更重要：**它把"先判什么后判什么"变成了可见、可拖动的列表**。我们的硬规则优先级链（`HARD-RULE-MODEL`）在文档里是文字，在 UI 上没有等价物。

### 13.4 Expression AST：概率判定被降级成操作数（本节最值得借）

界面形态是一个三层构造器：`[操作数] [运算符▾] [值]`，加 `Wrap in`（把整条表达式包进新的外层）与逻辑分组。

**操作数类型**（界面枚举）：`String` / `Number` / `True` / `False` / `Null` / `Dynamic Variable` / **`LLM Evaluation`**。
**运算符三组**：`Comparison`（`Equals` / `Not Equals` / `Greater Than` / `Greater Than or Equals` / `Less Than` / `Less Than or Equals`）· `Logical`（`And` / `Or` / **`Conditional`** = 三元）· `Arithmetic`。

API 侧的 AST 与界面一一对应：

```json
{"type":"or_operator","children":[
  {"type":"dynamic_variable","name":"force_phone_transfer"},
  {"type":"llm","prompt":"Phone condition","value_schema":{"type":"boolean","description":"Phone condition"}},
  {"type":"eq_operator","left":{"type":"dynamic_variable","name":"mode"},
                        "right":{"type":"string_literal","value":"dev"}}
]}
```

**这一条是全文最有参考价值的单点**：

> 它没有把"这条边由模型判定还是由表达式判定"做成二选一，而是**把模型判定降级成 AST 里的一个操作数**（`type:"llm"`，带 `value_schema` 声明返回类型）。于是一条边可以写成"字段比对 **OR** 模型判定"，且在结构上**能一眼看出哪部分是概率的、哪部分是确定的**。

对照我们：`HARD-RULE-MODEL` 现在的隐含假设是"硬规则全部确定性、模型判定在规则之外"。ElevenLabs 证明了第三种形态——**混合表达式，但概率部分被显式标记为操作数**。这不推翻我们的原则（规则始终在模型外执行），反而是它的**工程实现方式**：模型判定不再"穿透"整条规则，只占一个叶子节点。

配套的还有一条官方建议：轮次计数这类判断**不要写进提示**，而是走 `workflow edge expression condition` 或 procedure 的 `If` 表达式（原句举例 `system__agent_turns >= 5`）。→ 与"条件只能引用已声明字段"完全同向，可直接引为外部佐证。

### 13.5 校验、阻断与"坏数据能让画布不渲染"（实测）

- **结构校验实时跑且阻断发布**：把一条 `LLM Condition` 改成 `Expression` 后变量留空，立刻出现三处反馈——① 画布上该边显示 `== ""` 并带红色错误点；② 左侧菜单 `Workflow` 出现红点；③ **右上角 `Preview` 变灰禁用、`Publish` 变成红色的 `Error` 按钮**。
- **错误态会持久化，且没有"保存"动作**：刷新页面后错误仍在，且 `Undo` / `Redo` 均 disabled（刷新即清栈）。→ **草稿是 autosave 的，错误数据可以存在草稿里，但发布被门挡住**。这一点与我们"保存 ≠ 提交"不冲突，但**我们的草稿是否需要"可保存但不合法的中间态"**是个真问题：他们允许，我们没定义。
- **实测到的坏行为**：错误态的边无法再打开检查器完成修复（连续两次 `dispatchMouseEvent` 超时），且修复过程中**画布一度整块不渲染**（节点元素从 DOM 消失，只剩顶栏与右栏 `Global settings`）。→ 记录为**已知缺陷**：**字段级校验能通过、但组合起来会让图不可渲染**。对我们的启发不是"别学它"，而是**校验要有两段：字段合法性 + 图可渲染性**，且**任何一段失败都必须保留"退回上一步"的入口**（它的 undo 刷新即失效）。
- `Global settings` 里只有两项：`To disable a workflow, disconnect the start node.`（说明文案）与 **`Prevent infinite loops`** 开关（API：`prevent_subagent_loops`，默认 `false`），说明原句 `Prevents the workflow from continuously transitioning in a loop when all conditions are true.`
  → **默认不防环**。这是它的取舍：允许环（回退/重试），环的风险交给使用者。我们若做图，必须反过来——**默认防环，显式开环**。

### 13.6 Procedures 与 Workflow 是同一层的两种表达（关键关系澄清）

官方 API（`procedures/compile`，已标记 deprecated 但把关系说透了）：**保存草稿 / 发布 agent 时，结构化 Procedures 会被编译成 workflow 的 nodes 与 edges，编译结果随草稿或版本一起保存，并返回校验错误。**

→ 所以三者关系是：

```
Procedures（结构化步骤，编辑态、可复用、有 Used by 反查）
        ↓ 保存/发布时编译
Workflow（nodes + edges + edge_order，执行态、可视化）
        ↓ 存进
草稿 / 版本（平台自动跑，不再需要单独 compile 调用）
```

这解释了为什么 Procedures 的步骤里有 `If（Text | Expression）`、`Tool`、`Sub-procedure`——**它们与 Workflow 的边、工具节点、子图是同一批语义的两种写法**。前两轮把 Procedures 与 Workflow 当两个并列功能记，是不准确的。

> 对我们的意义（EL-6 要加强）：如果将来引入"流程对象"，**必须一开始就定清楚"编辑态表达"与"执行态产物"是不是同一份数据**。ElevenLabs 的做法（编辑态可编译 → 执行态只读产物 → 存进版本）与我们的 `ChangeProposal → 评测 → 审批 → 新版本` 是兼容的：**编译产物天然就是"要冻结的东西"**。

### 13.7 可借 / 不借（本轮增量）

| # | 借 | 落到哪 | 为什么 |
|---|---|---|---|
| **22** | **模型判定作为表达式的一个操作数**（`type:"llm"` + `value_schema`），而非"整条边由模型判" | `HARD-RULE-MODEL` 的条件表达 | 第三条路：混合表达式，**概率叶子节点显式可见**。比"硬规则全确定性 + 模型判定在规则外"更接近工程可落地形态 |
| **23** | **边的 forward / backward 双条件** | 对话流设计（S2 之后） | 回退是一等语义；我们没有 |
| **24** | **`edge_order` 拖拽排序 = 判定优先级可见化** | 硬规则优先级链 | 文字规则 → 可拖动列表。顺序错了能被看见 |
| **25** | **增量字段与覆盖字段分开声明**（`additional_*` vs `conversation_config`） | EL-10 的"覆盖粒度"轴 | 不做这个区分，"节点用了什么"永远说不清 |
| **26** | **用拓扑关停而非开关**（断开 start 即停用） | 配置域 | 少一个状态位，少一种"开关忘了关"的事故 |
| **27** | **结构校验必须两段：字段合法 + 图可渲染** | EL-11 加强 | 实测它会通过字段校验却渲染不出图 |

| # | 不借 | 理由 |
|---|---|---|
| **12** | **默认不防环**（`prevent_subagent_loops` 默认 `false`） | 环的风险交给使用者＝事故面交给使用者。我们要默认防环、显式开环 |
| **13** | **错误态可持久化且无"退回上一版"**（刷新即失去 undo） | 坏数据能停在草稿里且修不回来（本轮实测）。我们的草稿必须能"丢弃"回到最近可用态 |
| **14** | **同一层内混用增量与覆盖语义却不显式标注** | 借它的字段设计（#25），但不借它把两套语义放在同一个检查器里不作区分 |

### 13.8 对前两轮的两处修正

| 位置 | 原表述 | 修正后 |
|---|---|---|
| §8.2 #10 | 「不借：**条件边用自然语言自由文本**」 | **过强**。真相是**条件类型三选一（None / LLM Condition / Expression）**，模板与默认都用 `LLM Condition`。**不借的应改为"把 LLM 自然语言条件当默认且当唯一形态"**；`Expression`（变量+运算符+字面量 AST）恰恰是我们要的那种"只能引用已声明字段"，可以借（§13.4） |
| §12.9-3 第二段 | 「**边条件是自由文本自然语言**……他们的分支判定交给模型理解自然语言」 | 同上。准确说法：**默认交给模型，但提供了确定性分支的完整构造器**；画布上看到的自然语言标签只是 `label`/`condition`，不代表它没有第二种类型 |

### 13.9 新增待确认项

| 编号 | 待确认 | 影响 | 阻塞出稿 |
|---|---|---|---|
| **EL-14** | 条件表达式是否引入**"模型判定作为叶子节点"**的混合形态（`type:"llm"` + 返回类型声明） | 若引入，`HARD-RULE-MODEL` 需新增一节"混合条件"：**概率叶子必须声明返回类型与判定问题，且整条规则仍标记为"含概率成分"**，评测时该条不得计入确定性判据 | 否（但这是本轮最重要的一条） |
| **EL-15** | 对话流是否引入**backward 条件（回退边）** | 若引入，`TASK-SYSTEM-DESIGN` 的状态机与对话流要分开：任务态回退已有（`reconciling`），**对话流回退没有**。S2-c 语音必须先验"回退后是否复读"（与 D-03 的复读率 0 容忍同一条指标） | 否（S2 之后） |
| **EL-16** | 草稿是否允许**"可保存但不合法"的中间态** | 他们允许（autosave + 发布阻断），我们没定义。若不允许，编辑体验会变重；若允许，必须配"丢弃回最近可用态"的入口 | 否（影响 S2 配置域交互细节） |

> **EL-14 的一条替代路线**（2026-10-22，v0.2 已定案）：若采用[路由与能力单元](ROUTE-GRAPH-AND-UNITS.md) §4 的"**闭集选择**"——模型只在工程给出的候选单元里选、不发明选项——则**不必引入"混合条件"**：概率只用于"选"，确定性用在哪里"些"和"能不能"。两者不并存，取其一。同一份文档还给出了"分形单元"（收起是节点、展开是图），用来答它扁平结构的第 ⑨ 条缺点。

## Sources（访问日 2026-10-21）

- 产品页（中文）：https://elevenlabs.io/zh/agents/ai-customer-support
- 平台总览：https://elevenlabs.io/docs/eleven-agents/overview
- 会话流：https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow
- 工具：https://elevenlabs.io/docs/eleven-agents/customization/tools · 系统工具：`.../tools/system-tools`
- 知识库：https://elevenlabs.io/docs/eleven-agents/customization/knowledge-base
- 工作流：https://elevenlabs.io/docs/eleven-agents/customization/agent-workflows
- 个性化 overrides：https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides
- 版本化：https://elevenlabs.io/docs/eleven-agents/operate/versioning · 实验：`.../operate/experiments`
- **合并提案（alpha）+ 路线图原文**：https://elevenlabs.io/docs/eleven-agents/operate/merge-proposals
- **Procedures**：https://elevenlabs.io/docs/eleven-agents/customization/procedures
- **Architect（Alpha）**：https://elevenlabs.io/docs/eleven-agents/operate/architect · 与提案的关系：`.../operate/architect/proposals`
- **Triage**：https://elevenlabs.io/docs/eleven-agents/operate/triage
- 后台实见（需登录，2026-10-21 免费账户）：`https://elevenlabs.io/app/agents/agents/<agent_id>/…`，二级页 `agent` / `procedures` / `workflow` / `branches`(`/proposals`) / `knowledge-base` / `analysis` / `tools`(`/mcp`) / `guardrails` / `settings`(`subtab=security`) / `tests` / `history` / `users` / `channels` / `batch-calling`
- 测试：https://elevenlabs.io/docs/eleven-agents/customization/agent-testing
- 对话分析：https://elevenlabs.io/docs/eleven-agents/customization/agent-analysis · 成功评估：`.../agent-analysis/success-evaluation`
- 护栏：https://elevenlabs.io/docs/agents-platform/best-practices/guardrails · 博客：https://elevenlabs.io/blog/guardrails
- 鉴权：https://elevenlabs.io/docs/eleven-agents/customization/authentication
- 隐私：https://elevenlabs.io/docs/eleven-agents/customization/privacy
- Widget：https://elevenlabs.io/docs/eleven-agents/customization/widget
- SIP 中继：https://elevenlabs.io/docs/eleven-agents/phone-numbers/sip-trunking · 批量外呼：`.../phone-numbers/batch-calls`
- Post-call webhook：https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks
- 编排引擎（博客，2026-02-27 / 更新 2026-09-14）：https://elevenlabs.io/zh/blog/unpacking-elevenagents-orchestration-engine
- 语音 Agent 能力（含"无内置跨通话记忆"）：https://elevenlabs.io/blog/voice-agent-capabilities
- 定价与并发档位：https://elevenlabs.io/pricing
- **v0.4 新增（Workflow 深挖）**：
  - 工作流文档（节点类型全集）：https://elevenlabs.io/docs/eleven-agents/customization/agent-workflows
  - **动态变量与内置 `system__*` 清单**：https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables
  - **API：创建草稿（`workflow` 请求体 + `forward_condition` / `edge_order` / `prevent_subagent_loops` / `subgraphs`）**：https://elevenlabs.io/docs/api-reference/agents/drafts/create
  - **API：读取 agent（`node.type` 与 `condition.type` 枚举、表达式 AST 完整形状）**：https://elevenlabs.io/docs/api-reference/agents/get
  - **API：Procedures 编译（"保存/发布时把 procedures 编译为 workflow 并返回校验错误"的原句）**：https://elevenlabs.io/docs/eleven-agents/api-reference/agents/procedures/compile
