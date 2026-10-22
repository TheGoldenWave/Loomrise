# 06 · 渠道与电话

> 证据等级：**B**（叙述文档）+ **A-**（字段与枚举）
> 语料篇目：`customization/widget` `customization/channel-behavior` `phone-numbers/*`（21 篇）`whatsapp/*`（5 篇）`guides/{call-queueing,batch-calls,chat-mode,realtime-monitoring}` `build/` `integrate/`
> **本卷不出结论**；判断见总纲 §6/§8.2、`PRODUCT.md` 的"模态轴"。

---

## 1. 一句话

渠道对它是**同一个 agent 的多个入口**，不是多个产品：一个配置，挂在 Widget / WebSocket / SIP / Twilio / WhatsApp / Teams 上。**但每个渠道都自带一套隐性约束**（谁能连、能说多久、能不能主动发第一条），这些约束不在 `conversation_config` 里，而在渠道层——这是接渠道时最容易漏的一层。

---

## 2. 渠道总表

| 渠道 | 接入形态 | 鉴权/门槛 | 独有约束 |
|---|---|---|---|
| **Widget**（网页组件） | `<elevenlabs-convai>` 网页标签，或 shareable landing page | **必须公开 agent + 关闭鉴权**；可用 `signed-url` 替代 `agent-id`；可在 Security 配**域名 allowlist** | 变体 tiny/compact/full/expandable；位置六向；`feedback_mode` none/during/end |
| **WebSocket API** | 直连，25 个客户端事件 | API key | 可拿到事件级控制（含 `context_usage`） |
| **WebRTC / Client SDK** | JS / React / React Native / Swift / Kotlin / Python / Java | API key 或签名 | 支持排队事件 |
| **SIP 中继** | 自带号码或 BYOC 中继 | SIP 凭证 | 见 §4 |
| **Twilio**（原生集成） | 托管号码 | Twilio 账户 | 支持 SMS 会话、OTP、区域路由、自定义 LLM 接入 |
| **Six 家运营商** | Bandwidth / Exotel / Plivo / Sinch / Telnyx / Vonage | 各自凭证 | 逐家有独立接入页 |
| **WhatsApp** | Meta Business 账户 | 模板预审 | 见 §5，约束最多 |
| **Microsoft Teams** | 三种接法：Azure Communication Services / Graph media bot / widget tab | Azure 侧配置 | 见 §6 |
| **CCAAS** | Amazon Connect / Five9 / Genesys | 各自 | 企业级联络中心对接 |
| **短信（Twilio）** | SMS conversations + OTP 校验 | Twilio | 与语音不同会话模型 |

---

## 3. Widget：鉴权的硬边界

官方原句（`customization/widget`）：

> Widgets currently require **public agents with authentication disabled**.

这句话是它整个鉴权模型里最容易被忽略的一条限制：**要嵌到公网网页上，就必须放弃 agent 级鉴权**。补偿手段有两个：

1. **`signed-url`**：用签名 URL 代替裸 `agent-id`（属性二选一）。
2. **域名 allowlist**：在 Security 页签限定允许的来源 host。

> 这两条都是"事后加固"，不是"默认安全"。对照我们：`S2-IA-NAV` 若有"试用/预览"入口，**默认形态就应该是签名链接 + 有效期**，而不是"先公开、再加白名单"。

`feedback_mode`（none / during / end）是它收集 **CSAT 1–5** 的机制；CSAT 与成功率是**两个分开的指标**（总纲 §8.1-21）。

---

## 4. 电话侧：三件真正影响设计的

### 4.1 排队（call queueing）

| 项 | 事实 |
|---|---|
| 默认 | **新 agent 默认开启** |
| 触发 | agent 或工作区并发用满（含 burst 容量） |
| 上限 | `wait_timeout_seconds`：1–1800（默认 **180 秒**） |
| 顺序 | 严格按到达顺序；多 agent 共享池时，等得久的优先 |
| 等待音 | 自定义 MP3/WAV，≤40 MB、≤3 分钟；未上传用默认音 |
| 计费 | **排队时间不计费**，不计入 `max_duration_seconds`，不计入会话时长 |
| 超时行为 | 电话正常挂断；WebSocket 客户端收到 `queue_status` = `timed_out`，随后 **close code 4300** |
| 不支持 | 外呼与批量外呼、纯文字 agent、Genesys / AudioCodes / Exotel / WhatsApp / SMS |

**日限额不排队**：超过 agent 日限额的呼叫**立即拒绝**——因为额度到第二天才释放，排队没有意义。

> 这条"日限额不排队"是个很实用的判断：**排队只对"会释放的资源"有意义**。我们的并发/配额设计若照抄"一律排队"，会在不可释放的限额上制造必死等待。

### 4.2 批量外呼（batch calls）

- 收件人列表可带**列**，列即动态变量（`user_name` 等）。
- 可**立即发**或**定时发**。
- **并发自动取"工作区限额的 50%"与"agent 限额的 70%"中的较小者**，以保证来话与 widget 会话仍有余量。
- 有批次总览与明细页，可按批次查状态。

### 4.3 转接与 DTMF

- `transfer_to_number`：转到电话号或 SIP URI；`transfer_type` 默认 `conference`；`post_dial_digits`（如 `ww1234` 表示停顿 0.5s 后拨分机，**仅 Twilio**）；`sip_refer_play_dialtone` 控制 REFER 期间是否给原腿放回铃；`uui` 携带 RFC 7433 用户对用户信息（可带 CRM ID / 升级原因**跨转接边界**）。
- `play_keypad_touch_tone`：播 DTMF，用于闯 IVR 菜单。
- `dtmf_input_settings`：采集用户按键。

> `uui` 这个字段值得记：它是**跨系统转接时唯一能带上下文的通道**，而不是"转过去就断片"。我们的转人工若只靠业务应用侧写工单，遇到跨系统（SIP REFER）就会丢上下文。

---

## 5. WhatsApp：约束最多的一条渠道

| 项 | 事实 |
|---|---|
| 自由文本 | **只能在已激活的会话内**发 |
| 主动触达 | 必须先发 **Meta 预审模板** |
| 模板管理 | 在 **WhatsApp Manager** 建与审，**不在 ElevenLabs 内** |
| 审核时长 | 通常几分钟到几小时；**待审/被拒时 API 会接受请求但 Meta 永不投递** |
| 营销模板 | Meta 有**每用户每周期上限**；静默不投递时需自己排查 |
| 模板发出的那一刻 | **开启一个新会话**；agent **保持沉默直到用户回复**；**模板本身是第一句**，用户回复前**任何会话计时器都不启动** |
| 不活跃超时 | 消息会话默认 **15 分钟**，从 agent **最近一次回复**起算 |

> 这一节几乎可以整体搬进我们的 `OutreachPolicy` 讨论：
> ① **主动触达必须过审**（这在制度层面印证"主动触达要独立成轴"）；
> ② **"发出去"≠"送达"**（API 接受、平台不投），必须有投递态；
> ③ **模板消息不启动计时器**——即"我们主动发的第一条"与"对话开始"不是同一个事件。这三条我们目前都没有显式建模。

---

## 6. Teams / CCAAS：企业侧接法

- **Teams 三路**：Azure Communication Services（托管）、Graph media bot（自有 bot 框架）、widget tab（把组件塞进 Teams 页签）。
- **CCAAS 三家**：Amazon Connect / Five9 / Genesys，各自有独立接入页；`Genesys` 同时出现在 `customization/integrations`（CRM 侧）与 `phone-numbers/c-caas`（话务侧），**是两个不同的集成点**。
- `customization/integrations` 另有 20 个业务系统集成（Salesforce / Zendesk / Intercom / HubSpot / Jira / Slack / ServiceNow / Freshdesk / 日历三家 / Telegram / Twilio / 以及 Exa / Parallel / Perplexity / Tavily 等检索类）。

> 20 个集成的存在说明它的策略是**"进客户已有的系统"**，而不是"让客户进我的系统"。这与我们"不建一线客服面、实时接管由业务应用自建"是同向的——但它是把集成做成产品，我们是把集成留给客户。

---

## 7. 渠道差异（`channel-behavior`）

官方有一篇专门讲"同一 agent 在不同渠道上行为不同"，要点：

- 语音与文字在**回复长度、格式、标点、是否可打断**上默认不同，因此有 `text_behavior_overrides`（按渠道覆盖，内置渠道默认）。**未设时用内置默认**——即"渠道默认"是平台给的，不是空。
- 纯文字有两条开启路径：agent 级 `conversation.text_only`（默认 `false`）与**运行时 SDK 覆盖**。
- 文字模式下 `text_only: true` 会**跳过音频处理**，从而避免音频计费。

> 我们的"模态轴"把"网页文字 / 网页语音"并为一等，它这里也是同构：**文字不是语音的降级，是一等渠道**，有自己的默认行为与计费口径。

---

## 8. 事实 → 总纲指针（不新增判断）

| 本卷事实 | 总纲对应 |
|---|---|
| §3 Widget 必须公开 + 签名 URL + allowlist | 入口鉴权（无对应结论，属新增参考） |
| §4.1 排队只对可释放资源有意义 | 并发/配额设计 |
| §4.2 批量外呼并发取 min(50%, 70%) | 主动触达容量口径 |
| §5 WhatsApp 三条（过审 / 投递态 / 模板不算会话开始） | `OutreachPolicy` 发起模式轴 |
| §7 文字与语音并列一等 | 模态轴（与 `PRODUCT.md` 一致） |

---

## 9. 矛盾与存疑

| # | 项 | 状态 |
|---|---|---|
| 1 | Widget"必须关闭鉴权"，但 `signed-url` 属性存在 | 官方未解释二者关系；推测签名 URL 属"受控公开"，D |
| 2 | `Genesys` 同时出现在两个集成目录 | 两个不同集成点，非重复 |
| 3 | 排队不支持 WhatsApp / SMS，但 WhatsApp 有"排队"语义（模板待审） | 概念撞名，非同一机制 |
| 4 | 各运营商的号码携带/合规差异 | 逐家页面未逐条核，D |
| 5 | 中国区号码与运营商支持 | 语料未涉及；**不要假设可用** |
