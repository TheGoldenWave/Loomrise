# 09 · CLI 与 MCP 的定位

> 证据等级：**A-**（MCP server 配置 schema 的枚举与默认值、CLI 命令族）+ **B**（叙述文档，含官方分工原句）
> 语料篇目：`operate/cli` `operate/hosted-mcp` `customization/tools/mcp` `customization/tools/mcp/security` `api-reference/mcp/create` `integrate/environment-variables` `build/overview`
> **本卷前六节只记事实与它的自我定位**；第七节是"对我方的可落点"，**标注为提案，未采纳**，判断与登记在总纲 §8.1-28…30 / §9 EL-17…EL-18。

---

## 1. 一句话

它把"人怎么碰这个平台"拆成**三条通道，各有明确分工，且分工由官方自己写死**：

> **"Use the CLI when you want agents in version control; use the hosted MCP server for conversational management."**

而 MCP 本身**还是两个相反的方向**：让 agent 去用别人的 MCP（入向工具），和让别人来管我的 agent（出向管理面）。三者混为一谈会得出完全错误的结论。

---

## 2. 先把三个对象分开

| 对象 | 方向 | 谁在调用谁 | 官方入口 |
|---|---|---|---|
| **CLI**（`elevenlabs`） | 人 ↔ 平台 | 你的终端／CI／编码 Agent 调平台 | `operate/cli`，源码在 `github.com/elevenlabs/cli` |
| **托管 MCP server**（`/v1/mcp`） | 外部 AI ↔ 平台 | **Claude 等 host 调平台**的管理工具 | `operate/hosted-mcp` |
| **MCP 工具接入**（inbound） | 平台 ↔ 第三方 | **你的 agent 调外部 MCP server** | `customization/tools/mcp` |

三者之间还有两条容易漏的关系：

- **托管 MCP 与 MCP 工具接入是明确互斥的两套文档**，两篇文档各自在开头写了一句"你要的是反方向，去看那篇"。
- **`SKILL.md` 不是 MCP 的一部分**：它是 **CLI 的产物**（`generate-skills` 命令）。所以"工具面"和"操作说明面"在它这里是**两条独立路径**，不是一套协议的两个部分。

---

## 3. CLI：三个用途，一份文件树

官方自我描述的三条用途（原句语义）：

1. **Store agents as code in your version control system**
2. **Set up CI/CD integration to automatically deploy your agents**
3. **Let your coding agent access and manage your voice agents**

### 3.1 落盘形态（这是它最值得看的地方）

```
your_project/
├── agents.json          # 中央注册表
├── tools.json           # 工具定义注册表
├── tests.json           # 测试定义注册表
├── agent_configs/       # 每 agent 一个配置文件
├── tool_configs/
└── test_configs/
```

**注册表 + 分文件**的二元结构：注册表管"有哪些、叫什么"，分文件管"具体内容"。这样一次 diff 只动一个 agent，不产生巨型 JSON 的合并冲突。

### 3.2 命令族

| 组 | 命令 | 备注 |
|---|---|---|
| 初始化 | `agents init` | 建目录与注册表 |
| 鉴权 | `auth login` / `logout` / `status` | **凭据进 OS keyring**（macOS Keychain / Windows Credential Manager / Linux Secret Service）；无 keyring 时回落 `~/.config/elevenlabs/auth-keyring.json`（`0600`）；**CI 用 `ELEVENLABS_API_KEY` 环境变量或 `.env`** |
| 创建 | `agents add "<name>" --template <t>`；`--skip-upload` | **六个内置模板**：`default` / `minimal` / `voice-only` / `text-only` / `customer-service`（temperature 0.1、30 分钟、带判据）/ `assistant` |
| 模板 | `templates list` / `templates show <t>` | 模板可被查看，不只是黑盒 |
| 同步 | `agents push` / **`push --dry-run`** / `agents pull` / `pull --update` / `--branch` | **`pull` 默认跳过本地已存在的 agent**，`--update` 才用远端覆盖 |
| 状态 | `agents status` / `agents list` | — |
| 工具 | `tools add --type webhook\|client` | — |
| 组件 | `agents widget embed <id>` | 直接吐 HTML 片段 |
| **给 AI 用** | **`generate-skills`（`--output-dir`）** | 把每个命令组写成一个 `SKILL.md` 到 `skills/`；**读 CLI 内嵌的 API 定义，离线、不需 API key**，并**随 CLI 版本同步** |

### 3.3 三个必须记的细节

1. **`--dry-run` 是一等命令**，不是可选参数。改了 7 个 agent 先看会发生什么。
2. **`pull` 的默认是"不覆盖"**。这条默认会造成**本地与远端分叉而不报错**——它的取舍是"保护你手改的东西"，代价是"你可能一直在推旧配置"。
3. **MCP server 不能通过 CLI 管理**（官方原句：*MCP servers are not yet manageable via the ElevenLabs CLI*）。**能力分工是有缺口的**：能进版本库的只有 agent / tool / test，MCP server 与知识库文档只能走后台或 SDK。

### 3.4 它把 CLI 开源了

平台闭源，**CLI 在 GitHub 上开源**。这不是善意，是取舍：CLI 是**契约的表面**，开源它才能被编码 Agent 读、被 CI 绑、被用户信任"我 push 上去的东西就是我看到的"。同时意味着 **CLI 的输出格式事实上成了公共 API**（结构化输出、退出码、字段稳定性都要当契约维护）。

---

## 4. 托管 MCP：把自己变成别人的工具

| 项 | 事实 |
|---|---|
| 端点 | `https://api.elevenlabs.io/v1/mcp` |
| 鉴权 | **OAuth**；登录后按工作区授予**受限作用域**；**不把 API key 拷进客户端** |
| 分发 | 已进 **Claude Desktop 目录**，搜索 ElevenLabs → Connect → 登录即可 |
| 区域 | 隔离环境要换 URL：EU `api.eu.residency...`／India `api.in.residency...`／Singapore `api.sg.residency...`；隔离环境是**独立工作区与独立账号** |
| 其他客户端 | 指向区域 URL + 走 OAuth 即可；支持 CIMD 的客户端无需注册 |

### 4.1 它能做什么（官方清单）

建 agent / 改任意设置 / 列出与对比配置 / 读会话与转写、跨会话搜索 / 看主题 / 管流程、工具、MCP server、知识库文档 / 建与跑测试 / 操作分支、草稿、流量部署、合并提案 / 读写工单 / 复制与删除 agent / **改前估算 LLM 用量与成本** / 取 widget 配置与分享链接 / 文本转语音返回短期下载链接。

### 4.2 它自己标出的那条警告（最重要）

> **Updating an agent through the MCP server publishes the change directly**, on the branch the assistant targets or on `main` by default. It isn't staged in a draft the way changes from the in-app Architect are.

即：**同一个"AI 帮你改配置"的能力，走了两条不同的写入语义**——

| 入口 | 写入语义 |
|---|---|
| Architect（在应用内） | 改在分支上 → 写测试 → **开 merge proposal** → 人批 |
| 托管 MCP（从 Claude 里） | **直接发布**（目标分支或 main） |

它把这条写在 Warning 里，等于承认：**"便捷"与"可审"在同一个产品里没有统一**。

---

## 5. 入向 MCP：agent 去用别人的工具

### 5.1 开关是工作区级，且有一个权限洞

| 项 | 事实 |
|---|---|
| 默认 | **每个工作区默认关闭**；需有一名成员代表工作区接受 MCP Server Terms，**一接受即对全工作区生效** |
| API | `can_use_mcp_servers` |
| 关闭后 | **保留已有集成，但 agent 无法使用**（关闭 ≠ 删除） |
| 谁能开关 | 官方原句：**任何成员，或任何带 `convai_write` 权限的 API key**，**不限工作区管理员** |

### 5.2 连接参数（A-）

| 字段 | 默认 | 说明 |
|---|---|---|
| `url` | 必填 | **必须 https**；URL 里若含密钥，应存为工作区密钥 |
| `transport` | **`SSE`** | 同时支持 SSE 与 HTTP streamable |
| `approval_policy` | **`require_approval_all`** | 另有 `require_approval_per_tool`（配 `tool_approval_hashes`）；工具级默认 `requires_approval` |
| `secret_token` | — | Authorization 头的值，存为工作区密钥或就地密钥 |
| `request_headers` | — | 额外头 |
| `request_meta` | — | 写进 `tools/call` 的 `_meta`；值可为 JSON 标量，或**工作区密钥／动态变量／环境变量引用**，**每次调用解析** |
| `auth_connection` | — | 可选鉴权连接 |
| `interruption_mode` | `allow` | 作用于该 server 全部工具，可逐工具覆盖 |

### 5.3 三档审批（界面语言）

| 档 | 行为 |
|---|---|
| **Always Ask**（推荐，API 默认） | 每次执行都要显式批准 |
| **Fine-Grained** | 逐工具分三类：**自动批准**（低频只读/完全信任）/ **需批准**（改数据、读敏感、有风险）/ **禁用** |
| **No Approval** | 不提示，仅限"彻底审查过、高度信任"的 server |

配套一句官方警告值得原样记：MCP 的 `destructiveHint` / `readOnlyHint` 标注"**可以提供线索，但不应单独作为安全决策依据**"。

### 5.4 一条硬性互斥（合规相关）

> **MCP support is not currently available for users on Zero Retention Mode or those requiring HIPAA compliance.**

且明确：`can_use_mcp_servers` **不能覆盖**这条限制。→ **零留存与 MCP 入向能力是互斥的**，不是"开关没开"。

### 5.5 责任边界

官方在文档最顶部单独放了一段 **User Responsibility**：第三方 MCP server 的安全、合规与行为由**用户**负责，平台"提供集成的场所，但不管理、不背书、不保障"外部 server。配套建议还包括：数据流（会话内容会发给外部 server）、凭据存储、HTTPS、私网防火墙、**静态出口 IP 白名单**。

---

## 6. 三者怎么选（它的隐含决策树）

```
你要把配置放进 git / 走 CI / 让编码 Agent 批量改   → CLI
你要在 Claude 里用自然语言改一个具体配置              → 托管 MCP
你要让 agent 会用外部系统（Zapier / 自建 / 客户内网） → 入向 MCP
你要给第三方 Agent 一份"怎么用我"的说明书             → CLI 的 generate-skills 产物
```

**能力缺口（它自己承认的）**：MCP server 与知识库文档**进不了** CLI 的版本库；`Skills` **只能由 CLI 生成**，托管 MCP 不产 Skills。

---

## 7. 对 Loomrise 的可落点（**提案，未采纳**）

前提：我方**方向已定**——`ARCHITECTURE.md`「统一 API、MCP／Skills／CLI 与后台 Worker」+ `AGENT-INTEGRATION-PLAN.md` AGI-01…09。所以下面**不新增方向**，只补"方向定了但没定的那几处细节"，并且**不改任何既有结论**。

### 7.1 已定 vs 本卷补的（先对齐）

| 维度 | 我方已定 | 本卷补的细节 |
|---|---|---|
| 谁是权威 | 统一应用服务是业务权威；网页／MCP／CLI 只调用例，**不各写一套状态** | ✅ 与之相符。它的 CLI `pull` 默认不覆盖会造成分叉，我们**不能照抄**（见 7.2-①） |
| MCP 角色 | 第三方 host 的工具与资源入口；外部 Agent **只获受限草稿／候选**，不开放生产业务写入、未消费 `blind`、真值修改、直接发布 | ✅ **它正好是反面**：托管 MCP 直接发布（§4.2）。我们的写法避开了这个洞 |
| Skills | 外部 `SKILL.md` 教第三方 Agent 用 Loomrise；内部 `SkillManifest` 定义客服策略；**各自版本化** | 它给出一个**生成方式**（§3.2 `generate-skills`），我们没定"谁写" |
| CLI 优先级 | **P1／AGI-05**：使用同一服务合同；结构化输出、退出码、revision／幂等、失败恢复 | 它给出**落盘形态**与 `--dry-run`（§3.1、3.3），我们没定"配置能不能落成一个目录" |
| 工具审批 | `ToolPolicy` 有批准包络 | 它给出**三档 + 默认全批**的具体形状（§5.3） |

### 7.2 可借三条（→ 总纲 §8.1-28…30）

**① 配置落盘＝"注册表 + 分文件"，且 `--dry-run` 是一等命令**（§3.1、3.3）

对"**可迁移**"这个定位承诺，这是最直接的物证：客户能把自己的 Agent 带走成**一个目录**，而不是从平台导出的一坨 JSON。

但**必须改一处**：它的 `pull` 默认"本地已存在就跳过"，`--update` 才覆盖 → 会静默分叉。我们的做法应是**带 revision 比较的显式冲突**：本地记录的 revision 与远端不一致就停下并要求选择，不允许"跳过"或"静默覆盖"。理由与我们"保存 ≠ 提交"同源——**任何静默成功都是事故面**。

**② Skills 从工具合同生成，而不是手写**（§3.2 `generate-skills`）

它的做法：读 CLI **内嵌的 API 定义** → 按命令组写 `SKILL.md` → **离线、不需 API key、随 CLI 版本同步**。

对我们 AGI-03 的价值是**消掉一类必然的漂移**：手工维护的 `SKILL.md` 与真实工具面会分叉（文档写了这个工具、实际没有），而我们要求"**披露事件可还原**"——披露记录里的 Tool ID / Schema 版本 / hash 必须与真实合同同源。**生成式 Skills 天生满足这一点**，手写的不满足。

代价要写清：生成物只能覆盖"工具怎么调"，**不能覆盖"什么时候不该调、失败怎么处理"**——那部分仍是人写的策略，必须与生成部分**分开存放**，否则下次生成会覆盖人的判断。

**③ MCP 工具审批：三档 + 默认全批 + "标注不等于信任"**（§5.3、§5.1）

- **默认 `require_approval_all`** 是安全默认的正确方向。我们的 `ToolPolicy` 应取同一个默认：**新增外部工具默认需批准**，自动批准要逐工具显式开。
- **逐工具三分（自动／需批／禁用）** 比"开关"更细，且"禁用"与"未配置"是两种状态——我们现在的 `ToolPolicy` 只有允许集合，没有"显式禁用"这一档。
- 它承认 `destructiveHint` / `readOnlyHint` **不能单独作为安全依据** → 直接支持我们"声明式标注不等于权限"。这条可以原样引为外部佐证。

### 7.3 两条不借（反向印证）

**④ 同一能力两套写入语义**（§4.2）

它在应用内走"草稿 + 提案"，在托管 MCP 里走"直接发布"。**同一个 AI 改同一个字段，从两个入口进，一个有审一个没有**——这不是简化，是分裂。

我们的 AGI-02 已写"无发布或生产业务写权限"，**保持这条不动**。可以补一句验收口径：**任何入口对同一资源的写入语义必须一致**；若某入口做不到草稿，就**不给写权限**，而不是"给写权限但不走草稿"。

**⑤ 权限边界过宽**（§5.1）

"任何成员或任何带 `convai_write` 的 key 都能开关工作区级 MCP"——一个 workspace 级安全开关，权限下放到"有写权限即可"。我们的工作区级设置（告警阈值等）是**仅管理员**，这个口径要**一致地贯彻到 MCP 开关**，不能因为"MCP 只是个集成"就放松。

### 7.4 一条必须进准入清单的硬事实

**⑥ 零留存类要求与入向 MCP 互斥**（§5.4）

事实：ZRM / HIPAA 工作区**不能用 MCP server**，且该限制**不被工作区开关覆盖**。

对我们的意义不在"照抄它的档位"，而在**准入判断**：客户的合规要求若包含"对话内容不得流向未受控第三方"，那么**入向 MCP 整块不可用**——这不是配置项，是**方案可行性**问题，必须在准入阶段就问，而不是实施时发现。这与 `PRODUCT.md` 的三条准入（资料可授权）同构：**外部 MCP server 是一个新的数据出口，必须纳入同一套授权口径**。

---

## 8. 与本项目既有文档的关系

| 文档 | 本卷动作 |
|---|---|
| `AGENT-INTEGRATION-PLAN.md` | **不改**。AGI-02/03/05 的验收项已被本卷 §7.2 补细，可作为日后修订的输入 |
| `ARCHITECTURE.md` §统一 API | **不改**。本卷 §7.3-④ 是它的外部佐证（"外部 Agent 不开放直接发布"是对的） |
| 总纲 `ELEVENLABS-AGENTS-ANALYSIS.md` | §8.1 增 28–30；§9 增 EL-17／EL-18 |
| `OPEN-SOURCE-BOUNDARY.md` | **待 EL-17 定了再动**：若 CLI 落盘目录成为交付物的一部分，"带走的是什么"要写进边界 |

---

## 9. 矛盾与存疑

| # | 项 | 状态 |
|---|---|---|
| 1 | CLI 定位说"给 coding agent 用"，但 **MCP server 与知识库文档进不了 CLI** | 能力缺口，官方自陈；说明"版本库"覆盖的不是全部配置 |
| 2 | `approval_policy` 的 API 枚举名（`require_approval_all`）与界面名（Always Ask）不一致 | 文档内部两套命名，非冲突但易错 |
| 3 | 托管 MCP 能"删除 agent"，但被描述为"受限作用域" | 作用域粒度未公开（D）；我们不能据此判断它是否可细分到只读 |
| 4 | 它把 CLI 开源、平台闭源 | 对我们的启示是"契约表面要可读"，不是"照抄开源边界" |
| 5 | `generate-skills` 读"内嵌 API 定义" | 内嵌定义与线上 API 的版本偏差如何保证，未说明（D） |
