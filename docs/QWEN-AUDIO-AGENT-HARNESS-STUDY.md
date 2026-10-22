# Qwen-Audio-Agent 源码与 Qwen-Audio-3.1-Realtime 报告研读 v1.0

状态：研究提案，2026-10-21。依据三份一手材料逐条核对：技术报告 [arXiv:2609.25176v2](https://arxiv.org/abs/2609.25176)（2026-09-24）、[项目主页](https://qwenaudio.github.io/qwen-audio-3.1-realtime/)、[QwenAudio/qwen-audio-agent](https://github.com/QwenAudio/qwen-audio-agent) 源码（本地 `_reference/qwen-audio-agent`，拉到 **main `ca2e7e2`**，2026-10-21 15:11，较此前参照的 `2b70ebc` 新增 31 个提交）。

**本文只做借鉴判定，不改任何既有文档结论。** 偏移诊断（D1–D3）见[架构对照](QWEN-AUDIO-3.1-REALTIME-ALIGNMENT.md)，已定决策见[语音架构决策记录](VOICE-ARCHITECTURE-DECISIONS.md)，指标操作表见[实时语音协同验证计划](VOICE-COORDINATION-VALIDATION.md)。三处不复制本文表格，本文也不复制它们。

## 0. 结论摘要

**总判定：这三份材料是 Loomrise 迄今最贴近的同形态参考——不是"另一个语音框架"，而是一套"实时前台 + 编排运行时 + 可替换后台执行器"的交付骨架，且已经在真实产品里跑起来。** 它的业务语义比我们粗（无版本、无审批、无租户），但**工程形态比我们细**，尤其在四处：任务交付语义、播报时序、记忆写入准入、确定性门禁。

| # | 可取 | 价值 | Loomrise 现状 |
|---|---|---|---|
| 1 | **双层状态投影**（内部 9 态 → 对外 5 值） | 运行页/服务事项有稳定投影，内部状态可自由演进 | 只有内部语义状态，未定义对外投影 |
| 2 | **重启恢复裁决矩阵**（5 动作，queued/running 一律 failed + 显式原因） | 把"重启后怎么办"从原则变成可测表 | §7.7 只有"一起恢复"的原则 |
| 3 | **播报窗口 + 打断/重投分流**（3 条件阻塞；打断→视为已送达，其他取消→重试） | D-02「打断→不播过期内容」的实现形态 | 有语义，无实现形状 |
| 4 | **客户端播出回执**（`playback.started`；服务端生成不算送达） | 正好补 Pipecat P0-2 的"无设备级回执"缺口 | 已知缺口，无参照形状 |
| 5 | **进度播报参数化**（60s 间隔 / 800ms 静默窗 / 单通道合并） | D1「何时说」第一次有了可配置落点 | 无落点 |
| 6 | **指令优先级链**（当前明确要求 > 长期偏好 > 默认人设；记忆只作事实不作指令） | 记忆与人格冲突有了可执行的裁决顺序 | 有"经验是倾向不是约束"的原则，无顺序 |
| 7 | **记忆学习四道结构校验**（逐字引用 / 字面锚定 / 非复述 / 关于交互） | 补上"引用真、推断假"这一类错误的准入防线 | 证据只引 ID，未要求结论可锚定 |
| 8 | **确定性契约门禁 5 维**（路由/引用/打断/重复播报/注入），直接驱动生产组件 | 与我们的"确定性 vs 软质量分离"同构，维度可直接映射 | 同构，缺"门禁必须打生产代码"的纪律 |
| 9 | **可执行环境 + 构造检查**（无模型回放参考解，导出允许写集） | 保证评测用例本身可判定 | 基准案例缺这一层自检 |
| 10 | **评测污染过滤**（工具名/对话片段/政策文本与评测集重叠要剔除） | 我们的配置文本会进评测集，是真风险 | 未见对应机制 |

**明确不借**：业务政策写成自然语言进系统提示、配置无版本无审批改完重启生效、模型内安全对齐当权限、GRPO 自动发布、个人助手形态的租户模型。理由见 §4。

**对已定结论的影响**：D-01 得到实证支持但要**修正一处表述**（语义断点并不全是 harness 自己做的，见 §5.1）；D-02 的"停止播报时延"必须拆成"harness 可控"与"provider 决定"两段（§5.2）；D1 的答案不是"做成可配置"，而是"平台固定 + 有限参数化"（§5.3）。

## 1. 证据等级与边界

本仓库的纪律是"上游能力、源码核查、安装、真实联调是不同证据等级"。本文逐条标注：

| 等级 | 含义 | 本文覆盖 |
|---|---|---|
| **A·代码级** | 本地检出源码逐行读过 | 任务状态机、恢复矩阵、播报窗口、打断分流、进度节流、记忆同步快照、核心工具白名单 |
| **B·文档级** | 仓库文档明述，未逐行核对实现 | 并发准入（全局 1 + 每 owner 1）、任务记录"是交付回执不是后端任务图镜像"、`playback.started` 协议字段 |
| **C·论文级** | 报告自述，Loomrise 未复现 | 可执行环境与三层奖励、系统级路由评测 91.04%、FDB 各表数字 |
| **D·演示级** | 仓库自带 example，非生产系统 | 客服示例（前端只读 MCP + 后台写入需确认 + 预览后提交） |

四条必须写在前面的边界：

1. **模型与 harness 是两件事**。报告 §7 的 Voice Harness 明确"informed by the open-source Qwen-Audio-Agent runtime"，且"evaluated separately from Qwen-Audio-3.1-Realtime"。它的路由评测用的是 **3.0 做前台**，不是 3.1。看到 91.04% 不要读成"3.1 模型能力"。
2. **报告自己声明结果不可统计比较**："descriptive"、"no repeated-seed significance test"、"缺失结果不视为 0"、"GPT-Realtime-2 用 low effort"。项目主页也主动写明"matched 3.1 duplex measurements are not yet reported"。这比我预期诚实。
3. **客服示例是 demo**："local, single-call demo, not a production customer service system"。可借的是分工形状，不是质量结论。
4. **许可证未核**。本轮未核 LICENSE 与本项目 Apache-2.0 的兼容性；本文所有"借"都指**机制与形状**，不含代码复制。

## 2. 先纠正三个容易看错的认知

**（1）它不是"Qwen 模型专属的壳"。** 仓库把后台做成了可替换执行器：ACP 协议接 OpenCode / Qoder / Qwen Code / MiniMax Code / Kimi Code / Codex，A2A 接远程 Agent，也可自定义 `BackendPort`；前台实时模型同样是可替换 Provider（Qwen、GPT-Live、Google Live、MiniCPM-o、StepFun、Doubao Seeduplex、本地 S2S）。**"一个前台 + 一个编排运行时 + 一个可换后台"这个形态，与 Loomrise 的 `ExecutionService + Adapter` 是同一类东西。** 这比"又一个语音 Agent demo"重要得多。

**（2）"harness 工程式"在它这里不是全部自己实现。** 语音前端文档写得很直白：轮次检测用 `smart_turn`（语义断句），"configured by the runtime; no manual VAD tuning is exposed"。也就是说**语义断点这一层它委托给了 provider 的可配置模式，自己只持话轮、打断、播报窗口、结果插入**。这对我们的 D-01 是一处必须修正的表述（§5.1）。

**（3）模型与 harness 可以同版本解耦演进。** 2026-10-20 的提交 `cf43ed7` 加入 `qwen-audio-3.1-realtime-plus`，方式是"reuse the `dashscope` provider and the existing WebSocket event protocol"——换模型是配置项，事件协议不动，默认仍留在 3.0 Plus。**这是 Jason 拍 D-01 时"为了更好兼容各家 LLM"的那个假设的直接证据。**

## 3. 可借机制清单

每条给：机制 → 出处 → Loomrise 落点 → 判定（**补**=我们没有 / **对齐**=已有且相当 / **更严**=我们更严，可反向引用作佐证）。

### 3.1 任务台账与交付语义

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| A1 | **双层状态**：内部 `scheduled/queued/running/delegated/finalizing/cancelling/completed/failed/cancelled` 九态，对外压成 `submitted / working / auth_required / input_required / 终态` 五值；`queued` 与 `running` 在 UI 上同为"处理中" | `task-state.mjs:5-15, 119-131`（A） | 运行页与服务事项列表需要稳定投影；内部状态机可继续演进而不破坏面板与文案 | **补** |
| A2 | **任务记录是交付回执，不是后端任务图镜像**："A Task record is a delivery receipt, not a mirror of the backend's internal task graph"；公开字段只留请求、时间、结果/错误、通用活动、有界权限摘要、通知状态 | `deep-dive.md` §5（B） | §2 对象权威可加一句边界：`TaskAttempt` 不镜像执行器内部 step，SDK 内部状态不作业务终态（与我们既有口径同向，缺的是明确的反向禁止） | **对齐** |
| A3 | **取消是确认制**：进入 `cancelling` 后由执行结果裁决，不由口头声明；"The Gateway updates the final state from the result, not from a spoken claim" | `deep-dive.md` §7（B）、`task-state.mjs:81-84`（A） | 我们已有 `cancel_requested → cancel_pending → 按停止确认与实际结果裁决`，且区分"执行已停止"与"事项已取消" | **更严** |
| A4 | **重启恢复五动作矩阵**：`RESTORE / RESCHEDULE / REATTACH / CANCEL / FAIL` 由 `(kind, status, scope, delegation 完整性)` 确定性决定；`queued/running` 重启一律 `failed` 并带显式原因；多目标任务 reattach **全或无**，不部分重挂、不回退旧顶层 ID | `task-recovery.mjs:8-54`（A） | 直接落成 `TaskItem` 的恢复裁决表；服务外呼场景需再加"已接通不可恢复为未呼"一条 | **补** |
| A5 | **并发准入**：默认全局 1 个活跃槽、每 owner 1 个；后续请求排队；等待用户输入/授权的任务**仍占槽**；委派出去后让出槽但任务不算完成 | `deep-dive.md` §2（B） | 我们有外呼频次/占用的原子预留，但没有"同一主体并行后台任务数"的定义 | **补**（小参数，防成本与体验互相抢占） |
| A6 | **播报策略与执行范围解耦**：`scope=user/system` 与 `notificationPolicy=announce/silent` 两个正交字段；UI 自有操作默认静默 | `task-state.mjs:22-28, 113-117`（A） | "这条结果要不要说"应是配置项，不是从状态推断 | **补** |

### 3.2 播报时序与结果交付（对 D-02 直接有用）

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| B1 | **播报窗口三条件**：`isBlocked = 用户正在说 ∨ 本轮未完成 ∨ 有音频待播`。插入时机是布尔判定，不是启发式 | `announcement-window.mjs:78-84`（A） | D-02「打断→不播过期内容」需要一个可判定的插入条件；这是现成形状 | **补** |
| B2 | **打断 ≠ 失败**：播报被用户打断 → `confirm`（视为已送达，不重播）；其他原因取消 → `retry`（重投）。且只有 `playbackStarted` 为真才发 `interrupted` 事件 | `realtime-presentation-runtime.mjs:735-748`（A） | 这是"打断播报≠取消任务"在**送达语义**上的精确版本；我们没有"播了一半算不算送达"的判定 | **补** |
| B3 | **客户端播出回执**：`playback.started` 回执确认"开始播出"，服务端生成完成不算；已开始播后打断不重复播放；上下文注入与回执各自有界重试 | `deep-dive.md` §7（B）、`response-context.mjs:54`（A） | 正对 P0-2 已核缺口"无客户端设备级播出回执"。**借形状，不借代码** | **补** |
| B4 | **进度播报参数化**：单任务最小间隔 60s、静默窗 800ms、失败重试 1s、单通道合并去重；进度以 `<background_work_progress>` 注入并只带 `task_id`，模型**不得因此调工具** | `progress-announcement-manager.mjs:6-8, 22-29`（A）、`PROMPT.md:69-72` | D1「何时说」的落点：不是一个开关，是一组可登记、可评测的节流参数 | **补** |
| B5 | **呈现时序单一职责**："This component owns presentation timing only… never polls a backend or derives narration from tool activity" | `progress-announcement-manager.mjs:36-40`（A） | 归因清晰：播报频率问题不该被误诊成执行问题 | **补**（纪律） |

### 3.3 交互策略与提示词归属

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| C1 | **工具面的提示词归属**：核心合同工具（`spawn_thinking/update_agent_task/get_agent_task_status/cancel_agent_task/respond_permission/get_current_time`）可被固定提示词点名；可选工具（记忆/检索/笔记/提醒…）各自携带说明、只在可用时加载，且互不点名；**白名单只存在于边界测试里**，不是运行时分类 | `deep-dive.md` §3（B）、`frontend-tool-registry.test.mjs:35-40`（A） | 这是"渐进披露 + 经验不授予权限"的落地形态：**能力面由装配决定，提示词有归属规则，测试锁死三者一致**。可直接搬成 Loomrise 的 Skill/工具面装配纪律 | **补** |
| C2 | **指令优先级链**：用户当前明确要求 > 长期偏好 > 助手默认人设；人设**不得**涉及工具、路由、权限、安全、记忆、任务与事实判断；`user_memory` 只作事实依据、不作行为指令；运行时上下文不具指令权限 | `PROMPT.md:7-22`（A） | 我们的"专家经验是行为倾向不是约束、永不直达配置"缺一个**运行期冲突裁决顺序**。这是现成可抄的五级顺序 | **补** |
| C3 | **语音输出规范**：避免空泛承接、重复用户要求、感谢等待、承诺耗时、承诺持续更新、用话语填补安静；**没有新信息时不要说话** | `PROMPT.md:90-96`（A） | 直接作为播报策略的验收条目；也是 D-02「附和」指标的语料来源（什么算废话是可列举的） | **补** |
| C4 | **工具调用前不口头回应**（提示词硬规定），进度改由独立通道注入 | `PROMPT.md:66-67`（A） | 与报告 §4.6"训练模型在工具调用前简短致谢"**正相反**。这不是矛盾，是分工差异，见 §5.3 | **辨析** |
| C5 | **委派合同措辞**：忠实保留目标与明确约束（**包括否定要求**），只消解有依据的指代，不扩写需求、不指定实现方案；缺关键信息才问 | `PROMPT.md:38-42`（A） | 与我们"禁止自由文本条件、不替业务方扩写"同向，可作为 `ServiceRequest` 转 `TaskItem` 的措辞基线 | **对齐** |

### 3.4 记忆写入与准入

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| D1 | **两文档按"行为权限"分域**：`user` 是指令权威（可覆盖实例默认、让位于当前话语），`memory` 只存事实永不作为指令；"scopes are separated by behavioral authority, not topic" | `deep-dive.md` §3（B） | 我们四种记忆按主体与生命周期分。这里补一条正交切法：**同一主体内部，按"能不能当指令"再切一刀** | **补** |
| D2 | **原子写 + 失败安全**：只有 `read/append/replace` 三个操作；`replace` 定位唯一片段，片段缺失或有歧义即安全失败；会话末抽取器不直接写文件、拒绝越界与敏感内容、留审计日志、无 key 时静默关闭 | `deep-dive.md` §3（B） | W1–W3 只说"模型只提交候选、不直写库"，未定义 replace 的失败语义与审计落点 | **补** |
| D3 | **首响路径禁止远程 IO**：provider 的 `list()` **必须同步返回**快照（异步直接抛错）；提示词路径读有界本地快照、不等远程；文档上限 8 篇 / 8000 字符；流式路径只做有界内存工作，索引/模型调用/持久化留到会话边界 | `runtime.mjs:23-25, 80-88`（A）、报告 §7.4（C） | 对"记忆 Provider 只读适配"是硬约束：**语义检索可以存在，但不能进首响关键路径**。这条比我们现有表述更可执行 | **补** |
| D4 | **学习准入四道结构校验**：`quote_not_from_user`（引用必须逐字出现在用户回合）/ `value_not_anchored`（结论字面部分必须能在引用里找到）/ `value_parrots_quote`（结论不得等于复述）/ `quote_not_about_interaction`（交互类偏好必须确实指向助手）；配合 `confirm ≥ 2` 且**来自 ≥2 个不同会话**、90 天无新确认则计数衰减、明确与推断**物理分区**、拒绝原因进 `memory-audit.jsonl` | `preference-learning.md`（B，机制描述完整） | 我们的专家经验走"提案 → 评测 → 审批"，比计数门槛严得多；但**准入时的字面锚定校验我们没有等价物**。证据只引 ID 还不够，还要保证结论能从被引证据里读出来 | **补** |
| D5 | 反直觉的一句："repeated sampling cannot filter this class out"——用户每次说同一句、模型每次错推同一结论，计数照样到阈值 | `preference-learning.md`（B） | **直接反驳"多轮运行累积证据≈可信"的直觉**。多轮只提高频次，不提高正确性；裁决仍要靠评测与审批 | **补**（认知） |

### 3.5 评测与门禁

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| E1 | **确定性契约门禁 5 维**：路由（能力门控的工具面）、引用（稳定 ID、去重、危险 URL 丢弃、只用一次）、打断（打断后的音频与转写必须抑制，事件只投影一次）、重复播报（重复完成信号合并、不重复呈现）、提示注入（检索内容是不可信数据、带显式告知、**不能改变已注册工具面**） | `frontend-evaluations.md`（B） | 与"确定性 vs 软质量分离"同构，且五个维度名可直接映射到我们的语音门禁与投影层 | **补**（维度命名与覆盖面） |
| E2 | **门禁必须打生产代码**："drives production Runtime components; it does not contain a second implementation"；不调模型、不发外部请求、可重复跑；**明确把语义质量排除在 release gate 外**（要凭据、成本、统计阈值） | `frontend-evaluations.md`（B） | "门禁测的是生产代码而不是测试替身"应成为纪律：否则门禁绿而线上坏。与我们既有"确定性真值"口径一致 | **补**（纪律） |
| E3 | **污染过滤**：训练/评测前过滤工具名、对话片段、政策文本中与评测数据重叠的部分 | 报告 §4.4（C） | 我们的配置文本、SOP 与 Skill 会与评测用例同源，**这是真实风险**，现有提案未见对应机制 | **补** |

### 3.6 可执行环境（对应 `EvalSet` 运营）

| # | 机制 | 出处 | Loomrise 落点 | 判定 |
|---|---|---|---|---|
| F1 | **domain = 工具池 + 有状态库 + 业务政策**；**task = 初始态 + 用户脚本 + 期望终态 + 行为断言 + 参考调用链**；每 episode 用私有状态副本，互不污染 | 报告 §4.1、附录 A（C） | 我们的基准案例可以照此补齐"参考调用链"与"私有一致初始态"，让用例可回放 | **补** |
| F2 | **构造检查**：训练前**无模型回放参考解**，验证工具确实能到达期望终态，并由实际状态变化**导出允许写集**；不一致的用例修复或丢弃 | 报告 §4.1（C） | "用例本身可判定"的自检层。我们若缺这一层，坏用例会把门禁本身污染 | **补** |
| F3 | **三类终态**：`write` / `justified refusal` / `unsupported`；"no change 是一等期望结果"，纯信息请求由行为断言判分而非状态变化 | 报告 §4.1（C） | 基准案例需区分"拒绝"与"不支持"——两者都与"没做"不同，混在一起就无法验收边界 | **补** |
| F4 | **判分顺序**：终态 → 写集否决 → 行为断言；"流利回复不能补偿状态失败或越权写入；反之状态正确也不豁免交互规则违规" | 报告 §4.2（C） | 与"两栏证据不合并 + 硬规则不因结果正确而豁免"完全同构，可作外部佐证引用 | **更严**/对齐 |
| F5 | **无效 rollout 重采样、不记 0**；难例台账；按"稳定通过/稳定失败/接近能力边界"打标签并据此加难度 | 报告 §4.3–4.4（C） | 与我们"坏例先归因再改"一致；"重采样不记 0"可借来防基础设施故障污染指标 | **对齐** |

## 4. 明确不借的五条

1. **业务政策写成自然语言进系统提示。** 报告的航班柜台示例（附录 A）把"每个客户最多 2 个有效 hold、到期日按 `expiry_date > today` 计"写成散文交给模型执行。这正是 Loomrise 禁止的形态——**条件只能引用已声明字段、禁止自由文本**。这个例子反过来是我们最好的反例教材：可判定的业务约束不能靠模型读散文。
2. **配置无版本、无审批、改完重启生效。** 它的口径是"changes to Realtime or backend behavior take effect on the next Gateway start"，没有草稿、评测、审批、回滚。与 `AgentVersion` / `ChangeProposal` / 发布 Gate 直接冲突。
3. **模型内安全对齐当权限。** 报告自己写："benchmark results do not measure authorization guarantees enforced by the runtime"，以及"能力边界评测不证明能力真的可用"、"spoken promise is neither proof of execution nor an authorization token"。**它把这条当成限制写出来，我们把它当成架构原则。** 方向一致，但它的默认仍靠模型合规，我们的硬规则在模型外——不退回模型内。
4. **GRPO 自演化与自动发布。** 多粒度奖励、自演化环境是好研究，但产出物直接进模型权重；Loomrise 的改进必须过评测与人工审批，保持人审。
5. **个人助手形态。** 单 Gateway、单活跃模型、单 owner、无租户隔离、无审批链。它的"一个 owner"是个人设备语义，不是我们的租户 / 主体 / 坐席模型。可借机制，不可借部署与权限模型。

## 5. 对已定结论的增量（不重复既有文本）

### 5.1 D-01 要修正一处表述：语义断点不全在 harness

既有表述是"是否/何时/如何说话由工程链路承担——Pipecat 轮次策略 + 自建播出回执"。对照后要收紧为**分层**：

| 层 | 谁做 | Qwen 侧证据 | 我们要补的核实 |
|---|---|---|---|
| 语义断句（这句说完了吗） | **provider 的可配置模式** | `smart_turn`，"configured by the runtime; no manual VAD tuning is exposed" | Pipecat 的 smart turn 是自建模型还是同样依赖 provider 侧能力？决定"停止时延"里有多少是我们可以优化的 |
| 话轮与打断（该不该停、停了要不要接） | harness | `AnnouncementWindow` + 中断分流 | 已有方向，缺实现形状（B1/B2） |
| 播出与送达（播到没播到） | harness + 客户端回执 | `playback.started` | P0-2 缺口，形状可借（B3） |
| 说什么（内容与进度） | 模型 + 运行时注入 | 固定提示词 + `<background_work_progress>` | D1 落点（B4） |

**结论不变（harness 工程式仍成立），但"全双工决策"这个词以后要拆开说**，否则会把 provider 的能力算成自己的账，指标与验收都会错位。

### 5.2 D-02 的停止时延要分两段

报告表 10 里有一组很容易被忽略的事实：3.1 相比 3.0，背景人声响应率从 0.73 降到 0.13（大幅改善），但**用户打断的停止时延从 1.041s 变差到 1.116s**、平滑轮次时延从 1.539s 变差到 1.921s；FDB v3.0 上 `Pass@1` 从 0.57 降到 0.54、`ArgAcc` 从 0.640 降到 0.626。

这组数字有两个用处：

- **支持我们"D-02 不照抄厂商数字"的立场**：单边改善可以与另一侧退步同时发生，这正是"只压一边、另一边必然顶上来"的实证。
- **要求指标分账**：`打断 → 停止播报` 的时延里，provider 侧的停止行为与我们 harness 的停播指令下发是两段。登记时分开测（"指令下发 → 客户端停止" vs "全部停止"），否则优化责任无法归属。这一条建议补进验证计划的指标表述，**不改阈值纪律**。

### 5.3 D1 与 Q2 的答案是"平台固定 + 有限参数化"，不是"做成可配置"

Q2 问的是交互契约落点（Skill/SOP 扩展 vs `AgentSpec` 模态 profile）。这份源码给了一个第三种答案，值得作为 Q2 的候选（**2026-10-21 已采纳，并细化为四档：把"有限参数"再拆成工程参数与体验开关，见[配置合同](CONFIGURATION-LAYERS.md)**）：

| 可配置面 | 内容 | 谁可改 | 理由 |
|---|---|---|---|
| **不开放（平台基线）** | 话轮正确性、打断处理、取消确认、权限流转、"不得声称已完成" | 平台代码 + 边界测试 | 这些是正确性问题，一旦业务方可编辑，就无法验收也无法归因（**C4 的分歧就在这里**：报告把致谢时机训练进模型，仓库把致谢时机从提示词里拿掉、交给进度通道） |
| **有限参数** | 播报节流（间隔/静默窗/重试）、致谢开关、静默策略、通知策略 | 版本内可配，随 `AgentVersion` 冻结 | 可登记、可评测、有明确默认值（B4/A6） |
| **业务内容** | 人设、语气、话术、知识、SOP | 搭建者/策略运营 | 本来就是内容层 |

**这个切法对我们的价值**：把"可配置"从二元判断变成三档，且每档都有验收方式。若 Q2 采纳，`AgentSpec` 只承载第三档与第二档的参数，第一档写进平台契约——这比"新开一个模态 profile"更轻，也不会把话轮正确性降级成业务内容。

### 5.4 一处可以立刻反向引用的强句

> "A spoken promise is neither proof of execution nor an authorization token."（报告 §5.1）

对应我们"失效结果不播报 + 硬规则在模型外 + 不能把口头承诺当执行证据"。这是外部一手材料里与 Loomrise 主张最贴合的一句，适合放进边界与硬规则文档的引注。

## 6. 待确认项（接续既有 Q1–Q5 编号）

| # | 待确认 | 影响 | 阻塞出稿？ |
|---|---|---|---|
| **Q6** | 是否采用**双层状态投影**（内部状态 → 对外 `submitted/working/auth_required/input_required/终态`）作为运行页与服务事项的统一投影？ | 运行域页面规格；以后改内部状态机不再改面板 | 否 |
| **Q7** | 是否把**重启恢复五动作**落成裁决表（含 `queued/running` 重启一律 failed + 显式原因、多目标全或无）？ | `TaskItem` 实现与恢复门；S2-a 持久化前置 | 否（S2-a 实施前须定） |
| **Q8** | 是否把**播报窗口三条件 + 打断/重投分流 + 客户端播出回执**写进 S2-c 语音验收？ | D-02 指标能否落地测；Pipecat 自建范围 | 否 |
| **Q9** | 是否把**记忆准入四道结构校验**与 **90 天衰减**用于专家经验候选？（我们比它多一道评测与审批，缺的是字面锚定） | MEM-1 候选生成的准入规则 | 否 |
| **Q10** | 是否把**评测污染过滤**（配置文本/工具名/对话片段与评测集重叠）写进 S2 评测门禁提案？ | 门禁可信度；与我们"评测是唯一裁决装置"的定位直接相关 | 否（但建议早定） |

**2026-10-21 全部拍定**（上表作为待确认时的记录保留，结论以下处为准）：

| # | 结果 | 落点 |
|---|---|---|
| Q6 | **采纳**双层状态投影：内部多态 → 对外五值 | [Task 体系 §6.1](TASK-SYSTEM-DESIGN.md) |
| Q7 | **采纳**重启恢复裁决表：`running` 一律判失败、委派重挂全或无、已接通不可恢复为未呼；按"尝试 / 事项 / 副作用"三层重写 | [Task 体系 §7.1](TASK-SYSTEM-DESIGN.md) |
| Q8 | **采纳并修正**：播报窗口 + 打断/重投分流 + 客户端回执进 S2-c；第一条件由"用户在说话"改为"用户在**对助手**说话"，归属判定分 P0 声学级 / P1 说话人级 / P2 语义级，处置走"停—判—续" | [语音决策 D-03](VOICE-ARCHITECTURE-DECISIONS.md) |
| Q9 | **采纳**四道结构校验；90 天衰减改为**只降权 + 标需复核**，不自动退休 | [记忆体系 §4.2.1](EXPERT-USER-MEMORY-SYSTEM.md) |
| Q10 | **采纳三条全做**：来源标记 + 重叠检测（最小实现）+ 留出集规则 | [评测门禁提案 §5.5](S2-EVAL-GATE-PROPOSAL.md) |

Q8 的修正同时新增一条配对指标"背景人声导致的非预期停播"，与"背景人声误响应"成对登记——只压一边，另一边必然顶上来，与本文件 §5.2 的实证同构。

另：**Q5（刷新 Qwen Audio Agent pinned 版本并补源码级核对）本轮已完成**——pin 更新为 `ca2e7e2`，源码级核对覆盖 §3 标注 A 的条目。[参考项目](REFERENCE-PROJECTS.md) 的 P0-3 行与本提案同步更新。

## 7. 附录：核对索引

| 关注点 | 位置 |
|---|---|
| 三段式架构与职责边界 | `docs/architecture/overview.md`、`docs/architecture/deep-dive.md` §1 |
| 非阻塞主循环 | `deep-dive.md` §2（含准入与让出名额） |
| 实时边界 / 工具面归属 / 记忆两域 | `deep-dive.md` §3 |
| 任务状态与恢复 | `server/src/task/task-state.mjs`、`task-recovery.mjs` |
| 播报窗口与打断分流 | `server/src/voice/announcement/announcement-window.mjs`、`realtime-presentation-runtime.mjs:713-762` |
| 进度播报节流 | `server/src/voice/announcement/progress-announcement-manager.mjs` |
| 记忆运行时与同步快照 | `server/src/memory/runtime.mjs`、`docs/reference/memory.md` |
| 学习门禁与结构校验 | `docs/reference/preference-learning.md` |
| 确定性门禁 | `docs/reference/frontend-evaluations.md`、`server/eval/` |
| 固定提示词（指令优先级、语音规范） | `config/frontend-agent/PROMPT.md` |
| 核心工具白名单（只在测试里） | `server/test/frontend-tool-registry.test.mjs:35-40` |
| 语音前端与 `smart_turn` | `docs/voice-frontends/qwen-audio-realtime.md` |
| 3.1 Plus 接入方式 | 提交 `cf43ed7`（2026-10-20） |
| 客服示例分工 | `docs/scenarios/customer-service.md`（D 级） |
| 可执行环境与路由评测 | 报告 §4、§7.3、附录 A |

## Sources

- 技术报告：arXiv:2609.25176v2（2026-09-24），本地 `_reference/qwen-audio-3.1-realtime.pdf`
- 项目主页：https://qwenaudio.github.io/qwen-audio-3.1-realtime/ （主动声明"3.1 duplex measurements not yet reported"、"persistent tasks and memory are runtime extensions"）
- 源码：https://github.com/QwenAudio/qwen-audio-agent ，main `ca2e7e2`（2026-10-21 15:11），较 `2b70ebc` 新增 31 提交
