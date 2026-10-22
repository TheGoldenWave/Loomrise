# 01 · 配置对象模型

> 证据等级：**A-**（`api-reference/agents/create.md` 的类型定义与默认值）+ **B**（叙述文档）
> 语料篇目：`api-reference/agents/create` `get` `update` `drafts/create`、`operate/versioning`、`customization/personalization/overrides`、`customization/personalization/dynamic-variables`、`integrate/environment-variables`
> **本卷不出结论**；判断见总纲 §8.1-2 / §9 EL-2、EL-10。

---

## 1. 一句话

一个 Agent 的配置是**一棵有明确边界的树**：`conversation_config`（七个子块）+ `platform_settings`（十六个字段）+ `workflow`（图）。版本化成快照后**整棵树不可变**；但树里有一小撮字段**不属于版本**，而属于 Agent 本身——这一撮字段是它整个模型里最容易踩坑的地方。

---

## 2. 三个顶层块

| 块 | 内容 | 是否随版本冻结 |
|---|---|---|
| `conversation_config` | `asr` / `turn` / `tts` / `conversation` / `language_presets` / `vad` / `agent` | ✅ 全部 |
| `platform_settings` | 评估、widget、数据采集、overrides、测试、护栏、鉴权、限额、排队、隐私、分析模型、主题发现、情感分析、告警、归档、摘要语言 | ⚠️ **只有一部分**（见 §3） |
| `workflow` | `nodes` / `edges` / `prevent_subagent_loops` | ✅ 全部 |

> 契约事实：`prevent_subagent_loops` 默认 **false**——即**默认不防环**。总纲 §13 记过这条（EL-15 一系）；在 Loomrise 语境里方向相反，图执行必须有环检测。

---

## 3. 版本级 vs 实例级（本节是全卷最重要的一张表）

### 3.1 随版本冻结（可分支、可 diff、可回滚）

| 类别 | 字段 |
|---|---|
| 对话配置 | 系统提示、人格、LLM 选择与参数、TTS 模型与音色、工具配置、知识库、首句、语言设置、话轮检测、打断设置 |
| 版本化的 `platform_settings` 子集 | `evaluation`（判据）、`widget`（外观与行为）、`data_collection`（结构化抽取）、`overrides`（会话发起期覆盖）、`workspace_overrides`（webhook）、`testing`（测试配置）、`safety`（护栏 IVC/非 IVC） |
| 工作流 | 完整 `nodes` + `edges` |

### 3.2 挂在 Agent 上、所有分支共享（**不进版本**）

| 字段 | 说明 |
|---|---|
| `name`、`tags` | 名称与标签 |
| `auth` | 鉴权设置与白名单 |
| `call_limits` | 并发与每日上限 |
| `queueing_config` | 超并发时的等待队列与等待音 |
| `privacy` | 留存期、零留存模式、**user memories** |
| `analysis_llm` | 事后分析所用模型（评估与数据抽取共用） |
| `topic_discovery`、`sentiment_analysis` | Agent 级分析设置 |
| `simulation_library` | 模拟库设置 |
| `alerting` | 告警 webhook 与监控阈值 |
| `ban` | 封禁状态（仅管理员） |

### 3.3 陷阱：静默丢弃

官方原文（`operate/versioning`）：

> Per-agent settings can only be changed on the main branch. On other branches the dashboard shows them as read-only, and publishing a version to a non-main branch **discards any changes to them**. Merging the branch into main afterwards **does not apply them either**.

即：**在非 main 分支改了实例级字段 → 发布会静默丢弃 → 合并也补不回来**。后台走查中这些字段确实显示为只读，但"只读"没能阻止我们理解错——因为我们以为"只读 = 改不了"，而实际语义是"改得进去、发布时扔掉"。这类"看起来成功、实际没发生"的行为，是我们最该避免的形态（与总纲 §8.2-8 同源）。

---

## 4. `conversation_config` 七个子块

### 4.1 `agent`——人格与提示

| 字段 | 默认 | 备注 |
|---|---|---|
| `first_message` | 空 | 空则等用户先开口 |
| `language` | `en` | 同时用于 ASR 与 TTS |
| `hinglish_mode` | `false` | 在印地语/马拉雅拉姆语/泰卢固语/卡纳达语中混入英语 |
| `dynamic_variables` | — | 任意结构，见 §6 |
| `disable_first_message_interruptions` | `false` | **首句不可打断**单独一个开关（不是全局打断开关） |
| `max_conversation_duration_message` | 空 | 超时前播报的收尾语 |
| `text_behavior_overrides` | — | 按渠道覆盖文字行为，未设时用内置渠道默认 |
| `prompt` | — | 含系统提示、工具、知识库、RAG、reasoning summary 等 |

> `disable_first_message_interruptions` 值得单独记：它承认了"开场白必须说完"是一个**独立于通用打断策略**的情形。我们的播报窗口（D-03）目前按"是否在播报"判定，没有"哪一段播报不可打断"的分级。

### 4.2 `turn`——话轮检测（关键默认值全在这）

| 字段 | 默认 | 范围 / 取值 | 说明 |
|---|---|---|---|
| `turn_timeout` | `7`s | 1–30 | 静音多久后重新推进 |
| `initial_wait_time` | 未设 | — | 首句为空时等用户开口的时长，未设则用 `turn_timeout` |
| `silence_end_call_timeout` | `-1`（关） | — | 用户最后一次说话后多久挂断 |
| `turn_eagerness` | `normal` | `patient` / `normal` / `eager` | 抢话倾向 |
| `spelling_patience` | `auto` | `auto` / `off` | 用户拼读数字与专名时是否多等 |
| `speculative_turn` | `false` | — | 静音期提前开始生成，降延迟、**升成本** |
| `retranscribe_on_turn_timeout` | `false` | — | VAD 判无语音时，超时后重转写累积音频；开启期间**关闭静音折扣计费** |
| `turn_model` | `turn_v3` | `turn_v2` / `turn_v3` | 话轮检测模型版本 |
| `interruption_ignore_terms` | — | 字符串列表 | **不触发打断的词**（如 "gotcha"、"understood"），大小写不敏感精确匹配 |
| `interruption_ignore_term_languages` | — | 语言码列表 | 按语言启用**预置**忽略词类目；显式存储以免靠词重叠推断 |
| `merge_with_default_ignore_terms` | `false` | — | 在自定义词表之外再叠加官方精编默认词表 |
| `transcribe_on_disabled_interruptions` | `false` | — | 打断被禁用时**仍转写**用户说话并带入下一轮；关则整段忽略 |
| `soft_timeout_config` | 关 | `timeout_seconds` 0.5–8.0，建议 3.0；`message` 1–200 字符，默认 `"Hhmmmm...yeah."`；`use_llm_generated_message` 默认 `false` | 见 §4.2.1 |

#### 4.2.1 软超时的三条硬约束（官方写明）

1. **每轮只触发一次**，防止连续填充语。
2. LLM 生成填充语时，**仍必须有静态兜底**；生成失败回落静态。
3. 生成时只看最近 4 条消息 / 1000 字符上下文。
4. 官方建议：**填充语里不要出现时间承诺**（"One second..."），因为实际耗时不可预测。

> 这一条与我们 D-03 的分工正好互补：D-03 管"用户在说话时是否停"，软超时管"模型还没算完时说什么"。两者是**并列的两支**，不是同一个开关的两档。

### 4.3 `tts`——语音合成

| 字段 | 默认 | 备注 |
|---|---|---|
| `model_id` | `eleven_v4_turbo` | 枚举含 `turbo_v2/2_5`、`flash_v2/2_5`、`multilingual_v2`、`v3_conversational`、`v4`、`v4_turbo` |
| `voice_id` | 内置默认 | — |
| `supported_voices` | — | 多音色候选 |
| `expressive_mode` | `true` | 非 v3 模型**自动禁用** |
| `suggested_audio_tags` | — | 仅 v3/v3_conversational；"建议"不是"白名单"，模型仍可用其他标签 |
| `agent_output_audio_format` | `pcm_16000` | 8k–48k / ulaw |
| `stability` | `0.5` | — |
| `speed` | `1` | — |
| `similarity_boost` | `0.8` | — |
| `text_normalisation_type` | `system_prompt` | **默认把数字规范化指令写进系统提示**；`elevenlabs` 档在生成后规范化，多点延迟 |
| `pronunciation_dictionary_locators` | — | 发音词典（版本化定位器） |
| `enable_phoneme_tags` | `true` | v3 系启用 SSML phoneme |
| `audio_effects` | — | 滤镜预设、距离感 EQ、环境混响 |

> `text_normalisation_type` 的默认档是个**产品级取舍**：它选了"污染系统提示"换"零额外延迟"。反过来说明——把确定性处理塞进提示，是行业里为了延迟做的常见妥协。我们不采纳（提示里不写规则），但要承认它的代价是延迟。

### 4.4 `conversation`——会话级

| 字段 | 默认 | 备注 |
|---|---|---|
| `text_only` | `false` | 只走文字，避免音频计费 |
| `max_duration_seconds` | `600` | 60–7200；**全局上限，独立于话轮超时** |
| `client_events` | — | **25 个枚举值**（见下） |
| `monitoring_enabled` | `false` | 开启后可通过 WebSocket 实时旁听 |
| `monitoring_events` | — | 旁听连接发哪些事件，枚举同 `client_events` |
| `dtmf_input_settings` | — | 电话按键采集 |
| `background_sound` | — | 环境音 |
| `source_attribution` | **`false`** | 开启且有知识库内容时，**指示 LLM 报告引用了哪些来源** |
| `file_input` | — | 会话中上传图片/PDF |

**25 个客户端事件**（A-，枚举全量）：
`conversation_initiation_metadata`、`asr_initiation_metadata`、`ping`、`audio`、`interruption`、`user_transcript`、`tentative_user_transcript`、`agent_response`、`agent_response_correction`、`client_tool_call`、`mcp_tool_call`、`mcp_connection_status`、`agent_tool_request`、`agent_tool_response`、`agent_tool_response_full_payload`、`agent_response_metadata`、`vad_score`、`agent_chat_response_part`、`client_error`、`guardrail_triggered`、`dtmf_request`、`agent_response_complete`、`context_usage`、`internal_turn_probability`、`internal_tentative_agent_response`。

> 三件事值得记：
> ① `tentative_user_transcript` 与 `internal_tentative_agent_response` 暴露了**"暂定态"是一等事件**——它的流式架构允许"先给一个可能被推翻的结果"。这与我们"两栏证据不得合并"是同一种诚实，只是它做在事件层、我们做在判定层。
> ② `source_attribution` **默认关**。引用溯源在它这里是**可选增强**，不是默认义务。这正是我们 `source_ref` 不退让的地方。
> ③ `context_usage` 作为事件下发，说明上下文占用是**运行时可观测指标**，不只是配置期估算。

### 4.5 `asr` / `vad` / `language_presets`

- `asr.provider` 默认 `scribe_realtime`，可选 `elevenlabs` / `scribe_v2_turbo`；`user_input_audio_format` 默认 `pcm_16000`；`keywords` 用于**提升特定词识别概率**。
- `vad`：语料中该类型定义**正文为空**（只有标题），字段未见——D 级，不引用。
- `language_presets`：按语言存 `overrides` + **首句译文** + **软超时填充语译文**。即多语言不是"翻译提示"，是"逐语言覆盖 + 两个固定文案的译文"。

---

## 5. `platform_settings` 十六个字段

| 字段 | 用途 | 备注 |
|---|---|---|
| `evaluation` | 判据列表（`criteria`），成功＝满足若干判据的组合 | 见卷 05 |
| `widget` | 组件外观与行为 | `variant` tiny/compact/full/expandable；`placement` 六向；`feedback_mode` **none / during / end** |
| `data_collection` | 结构化抽取项 | 每项含 identifier / type / description |
| `data_collection_scopes` | 每项的作用域 | `conversation` / `agent`，**缺省为 conversation** |
| `analysis_items` | 评估项与采集项"按引用挂载" | 未迁移的 agent 此字段为 `None`，读取回落到旧字段 |
| `overrides` | 会话发起期覆盖 | 见 §7 |
| `workspace_overrides` | 工作区级 webhook | — |
| `testing` | 测试配置 | 见卷 05 |
| `guardrails` | 护栏 | 见卷 05 |
| `auth` | 鉴权 | 见卷 07 |
| `call_limits` | 并发/日限 | 见卷 06 |
| `queueing_config` | 排队 | 见卷 06 |
| `privacy` | 留存、ZRM、user memories | 见卷 04 / 07 |
| `trust_context` | `unknown` / `low` / `high`，默认 `unknown` | 语义未文档化（D） |
| `analysis_llm` | 事后分析模型，**枚举逾百项**（含带日期快照与别名） | 与我们"判官必须版本化"直接对照 |
| `topic_discovery` / `sentiment_analysis` / `alerting` / `archived` / `summary_language` | 主题发现、情感分析、告警、归档、分析输出语言 | — |

> `data_collection_scopes` 的 `conversation` / `agent` 二值，与 `evaluation` 里"判整通还是判行为"是同一套作用域思想；`summary_language` 则承认了"分析输出的语言"是独立于"对话语言"的一个设置。

---

## 6. 个性化：动态变量与 overrides

- **动态变量**是会话发起时注入的键值（`dynamic_variables`），也被工具返回值写入（`update_state` 系统工具 / `update state` 节点）。它可用于：提示插值 `{{customer_id}}`、表达式条件、工具参数固定取值（`source: "dynamic_variable"`）、Say 步骤译文之外的插值。
- **overrides** 允许**客户端在发起会话时覆盖服务端配置**（如 prompt、首句、TTS、工具、知识库）。逐字段默认关；一旦开启某字段，客户端就能整段替换。
- 两者在语料里被反复建议用于"同一 agent 服务多租户"，但**都没有版本概念**：覆盖发生在运行时，不进任何快照。

> 合约性质：**这是配置权威的外部出口**。总纲 §8.2-3 已定不借。

---

## 7. 草稿：语义比"草稿"两个字复杂

| 事实 | 出处 |
|---|---|
| 草稿是 **per-user, per-branch**——每人每分支各有独立草稿 | `operate/versioning`、`customization/procedures` |
| 提交新版本时，**该用户该分支的草稿被丢弃** | 同上 |
| **合并进某分支时，该分支上的草稿也被丢弃** | 同上 |
| 保存 agent 草稿（`POST /agents/{id}/drafts`）**会触发结构化流程校验**，但保存**单条流程草稿**（`PATCH /procedures/{id}/draft`）**不校验** | `customization/procedures/structured-procedures` |
| 版本化一旦启用**不可关闭** | `operate/versioning` |

> 差异点：我们的"保存 ≠ 提交"要求草稿**可长期存在且不污染稳定版**；它的草稿是**按人隔离**的，所以不污染别人——但同一个人在同分支上的半成品对**自己**是生效的（编辑即生效，`Publish` 才推到生产）。这是"分支即工作副本"模型的必然结果，与总纲 §8.2-8 对应。

---

## 8. 环境与鉴权（配置视角）

- `integrate/environment-variables`：环境变量分三类（密钥 / 工作区标识 / 运行时开关），具体键名以原文为准。
- 配置的四种下发通道：Dashboard、CLI（`agents pull` / `push`，文件落在 `agent_configs/<name>.json`）、API/SDK、MCP。**同一份 JSON 四通道等价**——这是它能被 CI/CD 接住的原因。
- 本卷不评"哪个通道更好"；只记事实：**CLI 的 pull/push 与 API 的 update 指向同一份配置**，没有第二套真相。

---

## 9. 事实 → 总纲指针（不新增判断）

| 本卷事实 | 总纲对应 |
|---|---|
| §3 版本级 / 实例级二分 | §8.1-2（补一格"实例级设置"，归 ②a） |
| §3.3 静默丢弃 | §8.2-8（分支即工作副本） |
| §4.2 忽略词表 + 禁用打断时仍转写 | D-03 播报窗口的判定支路 |
| §4.2.1 软超时 | §8.1-10 |
| §4.4 `source_attribution` 默认关 | 与 `source_ref` 不退让的对照 |
| §4.4 25 个事件 / `context_usage` | 运行时可观测性口径 |
| §6 overrides | §8.2-3 |
| §7 草稿 per-user per-branch | §8.2-8 |

---

## 10. 矛盾与存疑

| # | 项 | 状态 |
|---|---|---|
| 1 | `vad` 类型在 `create.md` 中**定义体为空** | D，不引用字段 |
| 2 | `trust_context` 三值语义无任何叙述文档 | D |
| 3 | `analysis_llm` 枚举含大量未来时点模型名（如 `gpt-6-astra`、`claude-opus-5-5`） | 说明枚举是**白名单快照**而非能力承诺；引用时只说"枚举存在" |
| 4 | `privacy` 含 "user memories" 但**无独立文档页** | 见卷 04 §5 |
| 5 | `disable_interruptions`（布尔，已废弃）与 `interruption_mode`（三值）**保持同步** | 两套并存，见卷 03 |
