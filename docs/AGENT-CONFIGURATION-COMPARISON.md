# 参考项目的 Agent 配置后台对比 v0.2

> 状态：公开资料与本地源码快照核对后的研究结论，非安装或端到端验收。2026-09-28；2026-10-21 补入 ElevenLabs ElevenAgents（商业托管，仅文档级核对）。范围以[参考项目清单](REFERENCE-PROJECTS.md)为准；本地浅克隆索引记录于 2026-09-26，各条公开来源直接指向对应上游提交。上游持续变化，以下只表示所引版本可见的能力，不保证其他部署版本或商业版相同。

## 判定口径与结论

这里的**Agent 配置化后台**指交付者可以在网页中创建或编辑 Agent／应用的运行配置（例如模型、指令、工具、知识、流程），并保存供试用或调用；只有聊天页、运行监控页、凭据设置页或用代码定义 Agent，均不算完整的配置化后台。“没有”表示**该参考项目本身未提供此类完整后台**，不是说它不能被接入带后台的产品。以下分类依据公开 README 与对应源码快照；未逐项启动 UI 验收。

| 分类 | 项目 | 判定依据与配置范围 |
|---|---|---|
| **有，产品型配置后台** | **Octop** | Web dashboard 管理多个 Agent；编辑页含名称、默认模型、运行参数、知识库、MCP、工作区等，并另有渠道、定时任务和连接器管理。面向个人/团队助手与多 Agent 使用。见[上游功能](https://github.com/TencentCloud/Octop/blob/c04aacc/README.md)与[编辑表单](https://github.com/TencentCloud/Octop/blob/c04aacc/dashboard/src/pages/Experts/components/EditAgentDrawer.tsx)。 |
| **有，产品型配置后台** | **Dify** | Web dashboard 中配置应用、Prompt、模型、知识与工具；工作流使用可视画布，Agent 可作为聊天应用或工作流步骤。见[上游功能](https://github.com/langgenius/dify/blob/3960b571/README.md)。 |
| **有，产品型配置后台** | **Langflow** | 可视化构建 Agent／Flow，组件连接模型、工具、检索等；在 playground 试运行，Flow 可作为 API／MCP 工具或 JSON 导出。见[上游功能](https://github.com/langflow-ai/langflow/blob/df9711c/README.md)。 |
| **有，产品型配置后台（商业托管，非开源）** | **ElevenLabs ElevenAgents** | 网页后台配置 prompt、LLM、voice、tools（client／webhook／code／MCP／system）、knowledge base、workflow 图、guardrails、evaluation、data collection、widget，并有版本／分支／流量切分、测试、实验与分析。是完整的托管式 Agent 配置与发布台，但**闭源、不可自托管**，配置权威在平台账户。见[配置方案与能力边界](ELEVENLABS-AGENTS-ANALYSIS.md)。 |
| **有服务 UI，但不等同于业务配置后台** | **AgentScope 2.0** | 除 SDK 外，另有 Agent Service 与示例 Web UI，覆盖会话、MCP／Skill Hub、资源共享、渠道和调度；Agent 定义与业务合同仍偏代码及服务组合。不能据此称它没有 Web UI，也不能把示例 UI 当作完整的业务 Agent 配置／发布台。见[Agent Service](https://github.com/agentscope-ai/agentscope/blob/a388212/README.md)与[示例页面](https://github.com/agentscope-ai/agentscope/tree/a388212/examples/web_ui/frontend/src/pages)。 |
| **有设置界面，但不是通用 Agent 配置后台** | **Qwen Audio Agent** | WebUI／桌面端提供语音前台、后端 Agent 选择与常用设置；其后端 Agent 的模型、工具、Skill 等配置可以复用外部宿主。重点是实时语音与异步任务协同，而不是创建、评测、发布一套独立业务 Agent。见[功能](https://github.com/QwenAudio/qwen-audio-agent/blob/2b70ebc/README.md)与[配置说明](https://github.com/QwenAudio/qwen-audio-agent/blob/2b70ebc/docs/configuration.md)。 |
| **有邻接后台，不是 Agent 配置后台** | **Langfuse** | Web 产品管理 Prompt、版本、数据集、实验、Trace，并提供 Playground；不负责定义整个 Agent 的权限、工具执行、业务结果和发布。见[上游功能](https://github.com/langfuse/langfuse/blob/fd5c9ee/README.md)。 |
| **有邻接工作台，不是 Agent 配置后台** | **SkillHone** | 本地工作台审阅 Skill 的 Issue、测试、修复、Diff、PR 和审批状态；管理的是 Skill 改进及决策历史，不是完整的 Agent 运行配置。见[决策审阅](https://github.com/Tencent/SkillHone/blob/c613aa9/README.md)。 |
| **有监控 UI，不是 Agent 配置后台** | **SkillOpt** | 可选 WebUI 用来监控优化实验；训练／评测仍由代码和配置驱动。见[WebUI](https://github.com/microsoft/SkillOpt/blob/79124b3/README.md)。 |
| **无此类后台，开发者／基础设施型** | **Pipecat、LiveKit Agents、skill-up** | 前两者主要用代码搭建语音 Agent／媒体链路，后者用声明式 `eval.yaml` 与案例评测 Skill／Agent；仓库中的 CLI、样例或工具界面不是通用 Agent 配置后台。见 [Pipecat](https://github.com/pipecat-ai/pipecat)、[LiveKit Agents](https://github.com/livekit/agents)、[skill-up](https://github.com/alibaba/skill-up/blob/fd0bcf2/README.md)。 |
| **无此类后台，研究／协议型** | **Omni-Interaction-Agent (Gander)、AG-UI** | 前者是全双工交互研究与运行样例；后者是前后端 Agent 事件协议及示例，不是替用户管理 Agent 配置的产品。见 [Gander](https://github.com/Omni-Interaction-Gander/Omni-Interaction-Agent)、[AG-UI](https://github.com/ag-ui-protocol/ag-ui)。 |

清单中的 **OpenTelemetry GenAI** 是观测语义约定，**DecisionProvider** 是 Loomrise 的可选适配边界，**钉钉 Connector／Stream SDK** 是渠道接入：它们都不是与 Octop 等同级的 Agent 配置产品。不能因为 Langfuse、SkillHone 或 SkillOpt “有后台／WebUI”，就将它们计为“有 Agent 配置化后台”。

**ElevenLabs 单独说明**：它是本表中唯一的**商业托管服务**（不是开源仓库），因此不参与"源码快照级"的能力比较，也无法核对实现细节。列入本表只为回答一个具体问题——**"配置对象与发布机制做到什么程度算完整"**。它给出两个其他项目都没有的参照：① 配置被显式切成"随版本冻结"与"随实例固定"两组；② 分支 + 确定性流量切分 + 字段级 diff 的发布机制。但它**没有审批门**，合并或改流量即上线，这一点不能作为 Loomrise 的目标。

## 配置部分：共同点和差异

| 维度 | Octop | Dify | Langflow | AgentScope Service／Qwen Audio Agent |
|---|---|---|---|---|
| **主配置对象** | 多个助手／专家 Agent，各自工作区及资源 | 应用、Agent 与工作流 | 节点组件构成的 Flow／Agent | AgentScope：代码定义的 Agent 加服务资源；Qwen：语音前台和外部后端 Agent 的连接／覆盖设置 |
| **创建方式** | Agent 表单与资源页，辅以专家文件和扩展配置 | Prompt IDE、应用设置、可视化工作流 | 可视组件拖拽连线，开发者可写 Python 组件 | AgentScope 偏 SDK／服务组装；Qwen 偏选择已有后端，不是通用业务构建器 |
| **模型、指令** | 默认模型、采样／迭代参数、persona／工作区指令 | 模型管理、Prompt 与节点参数 | 模型组件和 Agent／Flow 节点参数 | AgentScope 在代码／共享资源中装配；Qwen 可配置前台服务并复用或覆盖后端模型 |
| **工具、知识和连接** | MCP、Skill、知识库、连接器及渠道 | 工具／MCP、知识库／RAG、工作流节点 | 工具、向量库、检索和自定义组件 | AgentScope 有 Toolkit、Hub／RAG／Channel 服务；Qwen 复用后端能力并配置前台扩展 |
| **试用与交付重心** | 多用户助手使用、Web／IM／定时任务 | 快速构建、测试并通过应用／API 交付 | Playground 调试，Flow 以 API、MCP 或 JSON 输出 | AgentScope 提供可组合服务和示例 UI；Qwen 强调全双工语音与后台任务回流 |

它们的**共同点**是把模型、指令、工具／知识和试运行连接起来；差异首先在“配置的权威对象”：Octop 管理助手及其工作区，Dify 管理应用／工作流，Langflow 管理可复用 Flow，AgentScope 管理运行与服务资源，Qwen Audio Agent 主要管理语音入口到已有 Agent 的连接。不能把“有工具列表或画布”直接推断为业务权限、持久结果与审批语义一致。

**相邻后台**另成一层：Langfuse 的 Prompt 版本与评测可作为证据和调试来源；SkillHone 的 Skill 变更审阅与 SkillOpt 的实验监控可作为改进机制参照。它们各自只覆盖 Agent 生命周期的一部分，不能代替 AgentSpec／业务执行内核。上述比较是配置表面的能力对照，**没有完成相同场景下的安装、操作耗时、权限隔离或发布回滚测试**。

## 对 Loomrise 的采用边界

1. **学习体验，不继承对象权威**：参考 Octop 的 Agent／资源管理、Dify 的低门槛应用配置与 Langflow 的即时试用；不要求 Loomrise 复制全部画布。Loomrise 的 `ScenarioPack`、`AgentSpec/AgentVersion`、`ServiceRequest/RunEvent`、`Case`、`ChangeProposal` 和 `Release` 仍归自身管理。
2. **后台围绕业务结果串联**：规划中的 B 端工作台应把“场景 → 接入 → 试用 → 验收 → 发布”连成单一路径；模型外硬规则、工具确认、幂等、真实结果 ID、固定集回放和人工批准不应只是 Prompt 字段。六层配置职责见[配置合同](CONFIGURATION-LAYERS.md)。
3. **分清当前实现**：目前 S1 只有纵向执行切片和本机网页文字／语音试用入口，**没有**上述 B 端配置化后台、完整版本发布与改进闭环。AgentScope 使用的是运行适配，不引入其上游 `app/` 控制面；Langfuse 等仅为候选参照。现状证据见[S1 交付报告](S1-BUILD-REPORT.md)。

## 核验边界

本次依据仓库已有的浅克隆及其 README／关键 UI 文件作静态核对；公开引用直接指向上游对应提交。未启动这些项目的完整服务，也未验证各项功能在不同版本、部署方式或授权层级下是否可用。“无此类后台”只针对上述定义和参考仓库本身，不是对生态插件或第三方托管产品的穷尽结论。
