# 03 · 运行时与语音

> 证据等级：**A-**（字段枚举与默认值）+ **B**（叙述文档与最佳实践）+ **B+**（界面实见）
> 语料篇目：`customization/conversation-flow` `customization/channel-behavior` `customization/tools/tool-configuration/tool-interruptions` `customization/tools/system-tools` `customization/voice*` `customization/multimodal-input` `guides/realtime-monitoring` `api-reference/tools/update`
> **本卷不出结论**；判断见总纲 §8.1-3/10、§8.2、D-03（`VOICE-ARCHITECTURE-DECISIONS`）。

---

## 1. 一句话

它把"说话这件事"拆成了**四个独立计时器 + 三层打断控制 + 三个工具时序旋钮**，每一个都有默认值和量纲，彼此不耦合。这套拆法本身比任何单个参数都值得看——因为它能回答"用户没说话"和"模型没算完"是**两件不同的事**。

---

## 2. 一次话轮的完整链路

```
用户发声
  → VAD（语音活动检测，`vad_score` 事件可下发）
  → ASR 转写（`user_transcript` / 暂定态 `tentative_user_transcript`）
  → 话轮判定（turn_v2 / turn_v3 模型 + turn_eagerness 三档 + spelling_patience）
  → LLM 生成（可提前：speculative_turn）
  → 工具调用（execution_mode / pre_tool_speech 决定插在哪）
  → TTS 合成（流式，收到"足够词 + 一个逗号"就开始，不等整句）
  → 播报（期间受三层打断控制约束）
  → 用户插话 → 打断判定（含忽略词表）→ 停 / 续
```

其中两处官方明确写了实现细节：

- **TTS 不等整句**：助手在"拿到足够的词和一个逗号"后就开始说话，而不是等完整句子。这是它压延迟的主要手段之一。
- **话轮模型可选版本**：`turn_model` 枚举 `turn_v2` / `turn_v3`，默认 `turn_v3`。**话轮判定本身是一个可替换模型**，不是规则。

---

## 3. 四个计时器（各自独立，别混）

| 计时器 | 字段 | 默认 | 范围 | 计什么 |
|---|---|---|---|---|
| 会话总时长 | `conversation.max_duration_seconds` | `600`s | 60–7200 | 从会话开始起算的**全局上限**，与话轮超时无关 |
| 静音后推进 | `turn.turn_timeout` | `7`s | 1–30 | 用户不说话多久后，助手主动接话 |
| 静音后挂断 | `turn.silence_end_call_timeout` | `-1`（关） | — | 用户最后一次说话后多久挂断 |
| 模型慢时填充 | `turn.soft_timeout_config.timeout_seconds` | `-1`（关） | 0.5–8.0，建议 3.0 | 等 LLM 超过多久就先说填充语 |

外加两个"非计时器但管时序"的：

- `turn.initial_wait_time`：首句为空时等用户先开口；未设则复用 `turn_timeout`。
- `conversation.max_duration_seconds` 到点时会发 `max_conversation_duration_message`（若配置了）。

**渠道差异（易漏）**：WhatsApp 消息会话默认有 **15 分钟不活跃超时**，从助手**最近一次回复**起算；这个超时可能早于 `max_duration_seconds` 生效，企业客户需联系支持才能改。

---

## 4. 软超时：只负责"模型慢"

三条硬约束（官方写明）：

1. **每轮只触发一次**。
2. LLM 生成填充语时**仍必须有静态兜底**；生成失败回落静态。
3. 生成只看最近 **4 条消息 / 1000 字符**。
4. 填充语**不得含时间承诺**（"One second..."），因为实际耗时不可预测。

静态消息默认 `"Hhmmmm...yeah."`，长度 1–200 字符，**支持语言覆盖自动翻译**与**客户端逐次覆盖**。

> 判断"这批参数调得好不好"的官方建议很实用：快响应的 FAQ 机器人应**关掉**软超时——因为填充语只在"慢"的时候有意义，快的时候它只是噪音。

---

## 5. 打断：三层，不是一层

### 5.1 全局层

打断是一个**客户端事件**（`conversation.client_events` 里必须包含 `interruption`）。没勾就没有打断。

### 5.2 工具层（每工具一个）

`interruption_mode` 三值，出现在 webhook 工具、client 工具、系统工具、MCP server 上：

| 值 | 界面名 | 行为 |
|---|---|---|
| `allow`（默认） | Allow | 任何时候都能打断 |
| `disable_during_tool` | Disable during execution | **仅工具执行期间**抑制打断；工具之后的回复仍可被打断 |
| `disable_during_tool_and_turn` | Disable during whole turn | 工具执行 **+ 随之的整段回复**都不可打断 |

- **多工具并行时取最严的那一档**。
- 旧布尔字段 `disable_interruptions` 已废弃，但与 `interruption_mode` **保持同步**：`true` 等价于 `disable_during_tool_and_turn`。
- MCP server 自带 `interruption_mode` 作用于其全部工具；单个工具可通过 `tool_overrides` 覆盖，**工具级优先于 server 默认**。

### 5.3 首句层

`agent.disable_first_message_interruptions`（默认 `false`）：**只有首句**不可打断。与工具时序无关。

### 5.4 判定层：忽略词表

| 字段 | 默认 | 行为 |
|---|---|---|
| `turn.interruption_ignore_terms` | — | 用户说出这些词**不触发打断**（如 "gotcha"、"understood"、"mm-hmm"），**大小写不敏感精确匹配** |
| `turn.interruption_ignore_term_languages` | — | 按语言码启用官方**预置**忽略词类目；显式存储，以免靠词重叠反推显示 |
| `turn.merge_with_default_ignore_terms` | `false` | 在自定义词表上再叠加官方精编默认词表 |

### 5.5 打断被禁时，用户说的话还算不算

`turn.transcribe_on_disabled_interruptions`（默认 `false`）：

- **开**：打断虽被禁，仍**转写**用户说的话，并可带入下一轮。
- **关**：不可打断那一轮里用户说的话**整段忽略**，不会触发话轮。

> 这一条是整套设计里最像"踩过坑"的字段：它承认了"打断被禁"与"用户说的话被丢掉"是两件事，并给了独立开关。

---

## 6. 与 D-03 播报窗口的对应（只列事实，不判优劣）

D-03 的处置是"停—判—续"：停止即时、判定窗静音、判否再恢复且**不复读**。它这套给出的是**参数化版本**：

| D-03 的要素 | 它的对应物 | 性质差异 |
|---|---|---|
| 第一条件不是"用户在说话"，是"用户在对着助手说话" | **无对应物**。它的打断判定是声学/话轮级，没有"是否对着助手说"这一层 | 我们有、它没有 |
| 硬打断（称呼词 / 指令词 / 超阈值连续发声） | `interruption_ignore_terms` 是**反过来的**：定义"哪些不算打断" | 它做减法，我们做加法 |
| 判定窗静音 | **无对应物**。它没有"停之后先静音再决定"的阶段 | 我们有、它没有 |
| 判否再恢复、不复读 | 无对应物；`agent_response_correction` 事件接近"改口"，但是**内容修正**不是**打断恢复** | 概念不同 |
| 某些内容不可打断 | 三层中断控制（全局 / 工具 / 首句） | 它更细：**按工具**、**按"是否首句"** |
| 不可打断时用户说的话 | `transcribe_on_disabled_interruptions` | 它显式建模了这个副作用 |
| 0 容忍误停 | 无对应指标 | 它没有误停率口径 |

> 净结论（事实层）：**它把"打断"做成了抑制策略，我们把"打断"做成了判定过程。** 抑制策略的好处是可枚举、可配置、零歧义；它缺的正是"停错了怎么恢复"这一半。

---

## 7. 工具时序：三个旋钮

### 7.1 `execution_mode`（什么时候执行）

| 值 | 行为 |
|---|---|
| `immediate`（默认） | 模型一请求就执行 |
| `post_tool_speech` | **等助手把话说完再执行** |
| `async` | 后台执行、不阻塞对话；适合长任务 |

> `post_tool_speech` 是"副作用不得先于播报"这条约束的**产品化实现**：模型说要退款，先把"我帮您处理"说完，再真的退。我们在 `VOICE-ARCHITECTURE-DECISIONS` D-04 里把这条写成了原则，它在工具层做成了枚举。

### 7.2 `pre_tool_speech`（调用前要不要先说一句）

| 值 | 行为 |
|---|---|
| `auto`（默认） | **按该工具最近的延迟**决定 |
| `force` | 总是要求助手先说一句 |
| `off` | 完全不说，无视延迟 |

旧字段 `force_pre_tool_speech`（布尔，默认 `false`）已废弃。

> `auto` 按"最近延迟"自适应，是它把"用户体验"接到"工程指标"上的一个具体做法：**慢的工具自动补一句话垫场，快的工具不啰嗦**。

### 7.3 `response_timeout_secs`(超时)

默认 **20 秒**；不同工具类型范围不同：`1–120`（webhook / client，或 `-1` 无限等客户端响应）· `5–300`（另一类）。

---

## 8. 系统工具：9 个（不是 8，也不是 11）

| 工具 | 作用 | 备注 |
|---|---|---|
| `end_call` | 结束对话 | 参数 `reason`（必填）、`message`（可选，先说再挂） |
| `language_detection` | 自动切到用户语言 | — |
| `agent_transfer` | 转给另一个 AI agent | 可指定目标 agent / 分支 / 节点 |
| `transfer_to_number` | 转到电话号或 SIP URI | 见卷 06 |
| `skip_turn` | 让助手这一轮不说话 | **配套 `wait_timeout_secs`**：跳过之后等多久再主动关心；`-1` 表示一直静音直到用户开口，且**此时"静音挂断"计时器继续走** |
| `play_keypad_touch_tone` | 播 DTMF 音 | 用于闯 IVR 菜单 |
| `voicemail_detection` | 识别语音信箱并可选留言 | 外呼必需 |
| `update_state` | **用表达式赋值动态变量** | 与 `update state` 节点同源表达式 |
| `flag_issue_for_review` | 模型主动打标进复核队列 | 见卷 05 |

> **8 / 9 / 11 的口径冲突来源**：`system-tools` 索引页列 8 个（不含 `flag_issue_for_review`，它有独立页）；算上它＝9；另有页面在讲"工具总数"时把工作流节点工具也计入，得到 11。**以本表 9 个为准**（逐个有独立文档页），其余口径记为 D。

**`skip_turn` 的 `wait_timeout_secs` 有一处精妙之处**：它显式声明"等待期间静音挂断计时器**暂停**"，而 `-1` 档则声明"计时器**继续跑**"。同一个字段的两种取值改变了**另一个计时器**的行为——这是它几个计时器之间唯一一处耦合，值得单独记。

---

## 9. 语音：TTS / ASR / 多语言

### 9.1 TTS 关键项（详见卷 01 §4.3）

| 项 | 事实 |
|---|---|
| 模型 | 默认 `eleven_v4_turbo`；枚举含 turbo / flash / multilingual / v3_conversational / v4 |
| 表达模式 | `expressive_mode` 默认 `true`，**非 v3 模型自动禁用** |
| 音频标签 | v3 系可用；`suggested_audio_tags` 是"建议"不是白名单 |
| 逐字控制 | `text_normalisation_type` 默认 `system_prompt`（把数字规范化写进提示）；`elevenlabs` 档在生成后规范化、多点延迟 |
| 发音 | `pronunciation_dictionary_locators`（版本化定位器）+ `enable_phoneme_tags`（SSML phoneme → IPA） |
| 音效 | `audio_effects`：滤镜预设、距离感 EQ、环境混响 |
| 参数 | `stability` 0.5 · `speed` 1 · `similarity_boost` 0.8 |

### 9.2 ASR

`provider` 默认 `scribe_realtime`（可选 `elevenlabs` / `scribe_v2_turbo`）；`user_input_audio_format` 默认 `pcm_16000`；`keywords` **用于提升特定词识别概率**。

### 9.3 多语言不是"翻译提示"

`language_presets` 的结构说明它的做法：按语言存一份 `overrides`，**外加两个固定文案的译文**——`first_message_translation` 与 `soft_timeout_translation`。

> 也就是说：**只有"每句都要一模一样"的两句话被单独建模**。其余全部交给"该语言的整套覆盖"。这个取舍很实用——多语言里最容易出错的恰恰是首句与填充语。

### 9.4 多模态输入

会话中可上传图片/PDF；`file_input` 配置，`max_files_in_memory`（默认 10，范围 1–10）、`max_files_per_conversation`（默认 10，`-1` 无限制）。超过内存上限的旧文件**被摘要替代**、字节释放。上传按文件计费。

---

## 10. 实时旁听

`conversation.monitoring_enabled`（默认 `false`）开启后，可通过 WebSocket **实时旁听**，并用 `monitoring_events` 选择发哪些事件（枚举同 `client_events`，25 个）。

> 注意它只做"旁听 + 发事件"，语料里**没有**"实时接管"（人工插话接话）的配置项。人工接管不在它的产品面里——这与我们"B 类实时接管由业务应用自建"的判断同构，但它连事件回流的完整语义也没承诺。

---

## 11. 矛盾与存疑

| # | 项 | 状态 |
|---|---|---|
| 1 | 系统工具 8 / 9 / 11 三种计数 | 以 9 为准（§8），其余 D |
| 2 | `disable_interruptions`（废弃）与 `interruption_mode` 双轨同步 | 两套并存，`true` = `disable_during_tool_and_turn` |
| 3 | `vad` 类型定义正文为空 | 字段不可知，D |
| 4 | 打断的"误停率"无任何口径 | 它没有这个指标，不能与之对比 |
| 5 | 护栏 `streaming` 模式在语音下"约 500ms 音频已播出才被 block" | 见卷 05；这是它自己承认的窗口 |
| 6 | 中文/方言的识别与打断表现 | 语料无数据；我们未实测 → D |
