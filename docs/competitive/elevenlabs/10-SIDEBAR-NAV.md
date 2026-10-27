# 卷 10 · 侧边栏导航排布（两级模型、27 项、7 个交互机制）v0.1

> 本卷属**证据与细节层**：只排事实、标边界、留原文位置，不产出取舍结论。
> 对照 Loomrise 的四类裁决（规划中 / 不做 / 不一致但坚持 / 我们特有）见 [终态侧栏规范 §2](../../S2-SIDEBAR-SPEC.md#2-与-elevenlabs-的四类裁决)。
> 与总纲冲突时以[总纲](../../ELEVENLABS-AGENTS-ANALYSIS.md)为准，并回改本卷。

- 语料时点：**2026-10-26**，5 张登录态截图（工作区级侧栏 1 张、agent 级侧栏 1 张、分支选择器 1 张、⌘K 面板 1 张、Architect 首屏 1 张）
- 证据等级：**B+**（界面实见）。账户为免费层个人工作区，含 1 个由官方 Customer Support 模板生成的 agent
- 样本局限：**只有静态界面，没有点击行为**。每组内条目的可达性、空状态、权限差异、点击后的落点均未核；凡本卷写「管什么」而未见页面正文的，标「（按命名推断）」
- 与 2026-10-21 走查的关系：agent 级仍是 18 项，**唯一改名是 Triage → Issues**；**工作区级侧栏首次实见**（此前 §12.8-B 记为「未达」）。两处一并记在 §6 差异表

---

## 1. 两级导航：一个平台，两套完全不同的侧栏

截图证实它的侧栏不是「一套菜单 + 子项」，而是**两个平面各自一套完整菜单**：

```text
工作区平面（无 agent 上下文）                 agent 平面（已选中某个 agent）
├ 搜索与创建 ⌘K                             ├ 搜索与创建 ⌘K
├ Home                                     ├ ← Back to workspace
├ Architect                                ├ [agent 头像] Customer Support
├ Issues                                   │   └ [分支] Main  ▾  ← 分支选择器
│                                          ├ Overview  : Spotlight · Dashboards · Architect(Alpha) · Issues
├ Agents                                   ├ Configure : Agent · Procedures · Workflow · Version Control
│   ├ Customer Support                     │             · Knowledge Base · Analysis · Tools · Guardrails · Settings
│   └ ⋯ More                               ├ Monitor   : Conversations · Tests · Users
├ Configure                                └ Deploy    : Channels · Outbound
│   ├ Knowledge Base
│   ├ Tools
│   ├ Integrations
│   └ Voices
├ Monitor
│   ├ Conversations
│   ├ Users
│   └ Tests
├ Deploy
│   ├ Channels
│   ├ Phone Numbers
│   ├ WhatsApp
│   └ Outbound
├ Settings
│
├ 〔底部区〕Invite team members 卡片
├ 〔底部区〕Developers
├ 〔底部区〕Upgrade
└ 〔最底部〕ElevenAgents（工作区切换器）
```

**计数**：工作区平面 **17 项 / 4 个分组头 / 4 个顶层项**（Home、Architect、Issues、Settings），另有 3 项底部区与 1 个工作区切换器；agent 平面 **18 项 / 4 个分组头**，另有 3 个常驻控件（返回、agent 选择、分支选择）。两平面**没有共享项**——同名项（Knowledge Base / Tools / Conversations / Tests / Settings）在两级都出现，但不是同一个东西（§7-1）。

---

## 2. 工作区级侧栏逐项

`Agents / Configure / Monitor / Deploy` 是**分组头**（不可点击、无折叠箭头）；`Home / Architect / Issues / Settings` 是**顶层项**，不属任何组。

下表 **21 行** = 1 项常驻控件（搜索与创建）+ 17 项导航 + 3 项底部区；工作区切换器未入表。

| # | 位置 | 条目 | 管什么（界面可见 / 按命名推断） | 形态 |
|---|---|---|---|---|
| 1 | 顶部常驻 | Search & create ⌘K | 全局搜索 + 创建入口，另含 AI 快捷动作（§4-1） | 输入框 + 快捷键 |
| 2 | 顶层 | Home | 工作区首屏：跨 agent 概览、`Overall Success Rate`、`Average CSAT Rating`（据 §12.8-B，2026-10-21 实见字段） | 图标 + 文本 |
| 3 | 顶层 | Architect | 建造助手；工作区级入口（agent 级也有，标 Alpha） | 图标 + 文本 |
| 4 | 顶层 | Issues | 工单/问题板；2026-10-21 时名为 **Triage**，四状态 `Pending / In progress / Resolved / Cancelled` | 图标 + 文本 |
| 5 | Agents 组 | Customer Support | 直接列出 agent，**选中即进入 agent 平面**；当前只有一个 | 头像 + 名称 |
| 6 | Agents 组 | ⋯ More | 折起的其余 agent（推断：≥N 个后的溢出位） | 省略号项 |
| 7 | Configure 组 | Knowledge Base | **工作区知识库**（跨 agent 共享的资料库，推断） | 图标 + 文本 |
| 8 | Configure 组 | Tools | **工作区工具注册表**（共享连接，推断） | 图标 + 文本 |
| 9 | Configure 组 | Integrations | 第三方集成（Zendesk / Salesforce / Slack 等，据 §12.6） | 图标 + 文本 |
| 10 | Configure 组 | Voices | 音色库（平台级资源，推断） | 图标 + 文本 |
| 11 | Monitor 组 | Conversations | 跨 agent 会话列表 | 图标 + 文本 |
| 12 | Monitor 组 | Users | 跨 agent 用户实体（按 user ID 检索、可按 Agent / Branch 过滤，§12.6） | 图标 + 文本 |
| 13 | Monitor 组 | Tests | 跨 agent 测试库 | 图标 + 文本 |
| 14 | Deploy 组 | Channels | 渠道接入总览 | 图标 + 文本 |
| 15 | Deploy 组 | Phone Numbers | 电话号码资源（导入/购买，据 §6） | 图标 + 文本 |
| 16 | Deploy 组 | WhatsApp | WhatsApp 渠道 | 图标 + 文本 |
| 17 | Deploy 组 | Outbound | 批量外呼 | 图标 + 文本 |
| 18 | 顶层 | Settings | 工作区设置（留存/ZRM/并发/账单，2026-10-21 未核，推断） | 图标 + 文本 |
| 19 | 底部区 | Invite team members | 团队邀请卡片，标题 + 一句说明，非菜单项 | 卡片 |
| 20 | 底部区 | Developers | 开发者（API key / webhook，推断） | 图标 + 文本 |
| 21 | 底部区 | Upgrade | 套餐升级，描边按钮样式 | 按钮 |

> **分组语义**：`Configure` 放**共享能力与资源**（库、注册表、集成、音色），`Monitor` 放**跨 agent 的只读事实**（会话、用户、测试），`Deploy` 放**对外接出口与拨出**。三者都不是"配置/部署"的流程阶段，而是**同一批对象的不同归属**——这一点与 Loomrise §1.1 的"一级＝对象域"同向。

---

## 3. agent 级侧栏逐项

| # | 位置 | 条目 | 管什么 | 备注 |
|---|---|---|---|---|
| 1 | 顶部常驻 | ← Back to workspace | 返回工作区平面 | 文字 + 左箭头，弱化样式 |
| 2 | 顶部常驻 | Customer Support + 头像 | 当前 agent；点击推断为 agent 切换 | — |
| 3 | 顶部常驻 | Main ▾ | **分支选择器**，见 §4-2 | 下拉 |
| 4 | Overview 组 | Spotlight | per-agent 首页：`Ready to chat` + 三条入口 + `View Dashboards`（§12.8-A-1） | 图标 + 文本 |
| 5 | Overview 组 | Dashboards | 13 个指标页签（§12.9-9） | 图标 + 文本 |
| 6 | Overview 组 | Architect ｜ **Alpha** | 同一能力在 agent 级也有一入口，带 `Alpha` 标签 | 文本标签 |
| 7 | Overview 组 | Issues | 该 agent 的问题板 | — |
| 8 | Configure 组 | Agent | 提示/开场/语音/模型/话轮（§12.3） | — |
| 9 | Configure 组 | Procedures | 流程对象：可复用、有 `Used by` / `Uses`（§12.2） | — |
| 10 | Configure 组 | Workflow ｜ **3** | 画布编排；**右侧数字角标 3**（§4-3） | 数字徽标 |
| 11 | Configure 组 | Version Control | 三页签 Branches / Proposals / Contributors（§12.5） | — |
| 12 | Configure 组 | Knowledge Base | **这个 agent 的知识接入**（三页签 Sources / Memory(Alpha) / Retrieval，§12.9-1） | 同名不同物 |
| 13 | Configure 组 | Analysis | 判据配置：分析模型、主题发现、情感、来源归因（§12.6） | — |
| 14 | Configure 组 | Tools | **这个 agent 的工具与 MCP 连接**（Tools + MCP 两子页，§12.6） | 同名不同物 |
| 15 | Configure 组 | Guardrails | 四类护栏 + 逐条成本（§12.6） | — |
| 16 | Configure 组 | Settings | **agent 级设置**：Advanced / Security / Architect（§12.1-3） | 同名不同物 |
| 17 | Monitor 组 | Conversations | 该 agent 的会话 | — |
| 18 | Monitor 组 | Tests | Attached Tests / Past Test Runs（§12.4） | — |
| 19 | Monitor 组 | Users | 该 agent 的用户（按 Branch 过滤） | — |
| 20 | Deploy 组 | Channels | 该 agent 的对外渠道 | — |
| 21 | Deploy 组 | Outbound | 该 agent 的批量外呼 | — |

**两处规模差**：agent 级**没有** Phone Numbers / WhatsApp / Integrations / Voices——它们是工作区级资源；工作区级**没有** Agent / Procedures / Workflow / Version Control / Analysis / Guardrails——它们是单个 agent 的配置。**归属按"谁拥有"切，不按"在哪个阶段用"切。**

---

## 4. 七个交互机制（本卷最可复用的部分）

### 4-1 搜索与创建（⌘K）：不是搜索框，是命令面板

按下后弹出居中面板，三段：

| 段 | 内容 | 形态 |
|---|---|---|
| 输入行 | `Search agents...` 占位 + 放大镜 | 单行 |
| Quick actions | `Create agent`（副标题 "Make a new conversational agent"，右侧 `Open ⏎`）· `All agents`（"Browse your agents list"） | 两行大图标列表 |
| 上下文动作段 | 段标题 **`Architect · Customer Support`**（= 当前 agent 作用域），其下 `Rewrite the system prompt`（"Tighten instructions and fix ambiguous behavior"）· `Explain what my agent does` · `Change the agent's tone` · `Write a procedure` · `Review my procedures` | 行 = 图标 + 标题 + 一句说明 |

三条结构事实：
1. **搜索、创建、AI 动作共用一个入口**——三件事都从 ⌘K 起，没有独立的"新建"按钮。
2. **AI 动作按上下文段分组**，段头写明作用域（`Architect · Customer Support`）——同一面板在不同 agent 下给不同的动作集。
3. **动作是"改配置"级别的自然语言指令**（改提示词、改语气、写流程），右侧无确认环节的迹象——这与它"分支内改动即时生效"的模型一致（总纲 §8.2-8）。

### 4-2 分支选择器：站内坐标，常驻且随全站走

| 元素 | 内容 |
|---|---|
| 收起态 | agent 名下一行：`Main ▾` |
| 展开态（截图 5） | 标题 `Main` + 绿标 `Live 100%` + 右对齐 `Updated 5 days ago` + 右侧 `✓`（当前分支） |
| 动作 | 面板底部整宽按钮 `Create new branch` |

结构含义（与总纲 §12.1-1 一致，本卷只补可见形态）：**分支是继承自 agent 的坐标，不是页面**。选中哪个分支，下面所有 18 项都在该分支视角下（路由普遍带 `?branchId=…`）。所以它必须常驻顶部、且没有"分支列表页"——分支管理在 `Version Control · Branches` 页签里。

> **与 Loomrise 的形态差异是根本的**：我们的坐标是**版本**（草稿 / 线上版），不是分支；线上版只读、无"分叉即生效"。见 [终态侧栏规范 §2.3](../../S2-SIDEBAR-SPEC.md#23-思路不一致需要坚持的项)。

### 4-3 数字角标：只在会堆积的那一项上

`Workflow` 右侧有红色圆标 `3`，其余 17 项没有。结合上下文（`Issues` / `Proposals` 都是"会堆积的收件箱"，却**没有**角标），可判定：**角标不是"待办计数"，而是这一项自身有未处理的结构问题**（2026-10-21 走查时曾出现空 procedure 导致整个 agent 校验失败，Preview / Publish 双禁用，§12.8-C）。

> 只记形态，不推断语义。**可确定的只有一条：角标挂在"有阻塞问题的配置项"上，而不是挂在"有消息的收件箱"上。**

### 4-4 `Alpha` 标签：状态直接进菜单文字

`Architect` 在 agent 级显示 `Architect ｜ Alpha`，在**工作区级不显示** `Alpha`。也就是说同一能力的成熟度标注**按平面不同**，不是全局单一状态。

### 4-5 `⋯ More`：agent 列表的溢出位

`Agents` 组只列 1 个 agent + 一个 `⋯ More`。说明 agent 列表**内嵌在侧栏里做快速切换**，不靠独立列表页承接（独立列表页是工作区平面的 `Agents` 与 ⌘K 的 `All agents`）。

### 4-6 底部三件套：把"非导航"的东西也放进侧栏

`Invite team members`（卡片）、`Developers`、`Upgrade`（按钮）、`ElevenAgents`（工作区切换器）依次排在菜单下方，与菜单项**视觉上不分组、但形态明显不同**（卡片 / 描边按钮 / 品牌行）。这一区承担的是**增长与账号动作**，不是对象导航。

### 4-7 `Back to workspace` 与平台切换

工作区平面用最底部一行品牌 `ElevenAgents` 表示"我在哪个平台"（它同时是平台切换器）；agent 平面用顶部 `← Back to workspace` 表示"我在下一层"。**去向在上、来处在下的组合**，读起来像面包屑，但**不是面包屑**（页面顶部另有 `Customer Support › Architect` 面包屑）。

---

## 5. 分组与数量的关系（可量化的观察）

| 平面 | 分组数 | 每组项数 | 结果 |
|---|---|---|---|
| 工作区 | 4 组 + 3 顶层 | Agents 2 · Configure 4 · Monitor 3 · Deploy 4 | 分组头**全部有 ≥2 项**，无一空组 |
| agent | 4 组 | Overview 4 · Configure **9** · Monitor 3 · Deploy 2 | 唯一 9 项的大组是 `Configure` |

两条可迁移的量化经验：
1. **分组头存在的前提是"组内 ≥2 项、组间不是同一类"**。工作区平面 17 项分 4 组，每组至少 2 项，没有为了对称而造的组。
2. **单项数最多的一组是配置组**（9 项）——它的边界最模糊，也最容易继续膨胀。我们在自己的结构里必须为"配置组"预设上限与拆法，否则会复制同一问题（见规范 §3.2）。

---

## 6. 与 2026-10-21 走查的四处差异

| # | 2026-10-21 记录 | 2026-10-26 截图 | 性质 |
|---|---|---|---|
| 1 | agent 级 Overview 组第 4 项名为 **Triage**（工单板四状态） | 名为 **Issues** | **改名**。页面内容是否同步变化**未核**（未打开） |
| 2 | 工作区级 14 个页面**全部「未达」**（§12.8-B） | 工作区级侧栏完整可见（17 项 + 底部区） | **证据升级**：由「未达」升为「实见结构」；字段级仍未核 |
| 3 | 工作区级 Configure 内容未知 | 只有 **Knowledge Base / Tools / Integrations / Voices** 四项 | **新事实**：共享能力只有四类，**不含** agent 配置项 |
| 4 | 未见任何角标 | `Workflow` 带红色数字 `3` | **新事实**：存在项级角标机制 |

> **勘误纪律**：本表不改写 §12 原文，只做增量。原 §12.8-A/B 的核验状态表继续有效，其中 A-4 的页面名以本卷为准（Triage → Issues）。

---

## 7. 五个结构观察（只描述结构，不下取舍）

1. **同名项在两平面复制，且语义不同。** `Knowledge Base` / `Tools` / `Conversations` / `Tests` / `Users` / `Settings` / `Channels` / `Outbound` 八组词根在两级都出现：工作区级是"库"，agent 级是"这个 agent 的接入/用法"。用户要判断"我该去哪一个"，只能靠位置记忆。
2. **配置项最碎、监控项最稳。** `Configure` 9 项且含 5 种不同对象（提示、流程对象、画布、版本、知识、判据、工具、护栏、设置）；`Monitor` 3 项、`Deploy` 2 项从不膨胀。
3. **AI 能力有两个落点、一个标签不一致。** `Architect` 既是顶层项（工作区）又是组内项（agent，带 Alpha），还能从 ⌘K 以"动作"形态调用——三层入口，三种粒度。
4. **"评测"被放在监控里，不在配置与发布的主路径上。**（总纲 §12.1-2 已判，本卷只补一条可见证据：`Tests` 只在 `Monitor` 组出现一次，无任何 Configure 入口。）
5. **导航同时承担"资源归属"与"账号动作"。** 上半是对象，下半是 `Invite / Developers / Upgrade / 工作区切换`——两类东西共用一根侧栏，只靠形态区分。

---

## 8. 引用关系

| 本卷事实 | 应回写 / 已引用的上游 |
|---|---|
| 18 项 agent 级菜单、4 组 | 总纲 §12.1（原文已记 18 页四组） |
| 分组与配置组膨胀 | [终态侧栏规范 §3.2](../../S2-SIDEBAR-SPEC.md#32-为什么专家平面不分组) |
| 分支选择器形态 | 总纲 §12.1-1、§8.2-8 |
| 角标机制 | [终态侧栏规范 §7](../../S2-SIDEBAR-SPEC.md#7-角标与待处理队列) |
| ⌘K 面板的 AI 动作 | 总纲 §8.2-15（同一能力多入口语义不一致） |
| Alpha 标签 | 总纲 §8.1-19（部署检查清单同源：状态可见但非门禁） |

---

## 9. 本卷未核清单（不写入任何结论）

- 工作区级 17 项的**页面正文**：字段、空状态、权限均未打开，`管什么` 一栏凡标「推断」者均未证实
- `Issues` 是否等同原 `Triage` 的四状态工单板（只确认改名，未确认内容）
- `⋯ More` 的触发条件（几个 agent 之后折起）
- `Workflow` 角标 `3` 的确切含义（"3 个校验错误" / "3 个未保存改动" / "3 条待办"，均未证实）
- `Alpha` 标签的判定权（手动标注还是按能力开关）
- 两平面之间的切换是否保留滚动位置、是否记忆上次位置
- 侧栏是否可折叠、窄屏形态、键盘顺序与读屏标签
