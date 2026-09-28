# Agent 交付工作台：参考项目分级与采用边界 v0.8

> 2026-09-27。本文件记录可以公开复述的候选清单；源码级与安装级验证的具体范围见[S1 验证结论与轻量适配](S1-VALIDATION-AND-ADAPTATION.md)。S1 精确安装、执行中取消、跨渠道及导出恢复已有确定性证据；真实模型/网页音频和运行级门禁仍待验证，见[S1 交付与验收](S1-BUILD-REPORT.md)。详细讨论和个人判断保留在本地工作区。

各项目是否提供 Agent 配置化后台、配置对象与交付侧重的逐项对比见[参考项目的 Agent 配置后台对比](AGENT-CONFIGURATION-COMPARISON.md)。

## 0. 已确认的产品前提

- 核心使用者：**AI 产品经理 / 解决方案人员 / 小团队开发者**；业务 PM 与运营是共同使用者和验收者。
- 独立定位：**从业务资料到可运行、可验收、可部署、可持续改进的 Agent 交付工作台**，而不是底层模型、聊天壳或上游框架的品牌分叉。
- 展示场景：明确标注虚构的成人在线课程咨询；二手车预约用于验证复用。不得使用雇主、第三方或客户的未授权内容、内部 Prompt、真实个人数据。
- 网页文字与网页语音同步做最小纵向切片，共享同一业务请求、权限、工具和结果。电话外呼是后续独立渠道。
- 默认采用“本地应用 + 外部模型 API”降低试用门槛；完全离线是另一种配置，不是首版默认能力。
- 产品形态决策：单一工作台、统一执行内核与分类适配器，首版单 Agent；具体接入和测评门禁见[产品形态与开放接入规范](PRODUCT-FORM-AND-INTEGRATION.md)。

## 1. 首选研究/试接项目

| 优先级 | 项目 / 角色 | 具体借用 | 必须验证的集成条件 | 当前结论 |
|---|---|---|---|---|
| **P0-1** | **AgentScope 2.0**：文本与工具运行 SDK | Agent、工具调用、状态、权限／人工确认、部署与事件扩展 | 固定稳定版；能否按版本输出结构化事件、支持暂停恢复和人工接管；开发版能力不等于稳定承诺 | **首选 SDK 集成候选**，不 fork 整个平台。S1 基线固定 **main 快照 `a388212`**（源码版本字符串 2.0.8，Apache-2.0；**不是发行 tag `v2.0.8`/`c7d8e31`**，见 [`VERSION-PINS.md`](../VERSION-PINS.md)）。源码级与安装级验证均已通过，S1 代码已跑通。适配点确认为 `MiddlewareBase` + `reply_stream` 事件投影。原生压缩/注入只可由 Loomrise 适配器编排并留证（S1 先关闭，长期收编）；业务 `ServiceRequest`/`SkillManifest` 留 Loomrise，自建 `unknown` 结果态。上游 `app/` 服务层（含 IM channel 与 ag-ui 中间件）不采用，AG-UI 只参考映射 |
| **P0-2** | **Pipecat**：网页语音工程骨架 | WebRTC／WebSocket、STT/LLM/TTS、打断、轮次和可观测插件 | 一条中文网页语音链路、打断与播出回执、统一 RunEvent、独立 Voice Worker | **语音主线候选**，先用一种供应商组合。固定 **v1.12.0**（BSD 2-Clause）：中断帧、轮次策略、观测挂点、OTel turn span 均已源码级验证；缺口：**无客户端设备级播出回执**，"已确认播出"须自建 |
| **P0-3** | **Qwen Audio Agent**：前台语音与后台任务样本 | 实时会话、异步任务、取消确认、事件回流和 WebRTC | 能否接同一业务规则、状态、工具与成本账本 | **架构参照 + 限时对照**，不直接套用整套助手（本轮未做源码级验证） |
| **P0-4** | **Langfuse + OTel GenAI**：追踪与评测 | 评分、数据集、实验 UI、OpenTelemetry 导出 | 单机安装负担与数据边界；Lite 可只保存自己的 RunEvent，Langfuse 可选 | **规范先行；完整服务非单机强依赖**。已核：Langfuse 4.46.0 仅接收 OTLP traces（自托管含 6 个服务，`ee/` 另许）；**GenAI 语义约定处于实验/迁移期**，须自 pin 与自持属性映射 |
| **P0-5** | **Microsoft SkillOpt + Alibaba skill-up**：受控优化与评测 | 受限文本修改、独立验证集、环境隔离、工具行为和报告 | 业务成功判定、模拟工具、真实副作用与人工审批；不能把研究 benchmark 当生产保证 | **机制参照；优化器无生产写权限**。同源方法论的 EvoOntology 已单独评估，只取评估与门禁机制，见[S2 评测门禁与改进循环提案](S2-EVAL-GATE-PROPOSAL.md) |
| **P0-6** | **AG-UI**：前端事件协议 | 文字增量、工具状态、人工交接和自定义业务事件 | 最小事件子集、版本冻结、脱敏和投影成本 | **兼容目标**，不决定内部领域模型。已核 spec 1.0：31 个事件类型中**无人工确认/中断事件**，确认与取消只能走 `CUSTOM`；以 schema 协议版本字段为准，不以 `ag-ui-protocol` 包版本推断 |
| **P0-7** | **可插拔 DecisionProvider**：混合决策 | 规则先过滤；必要时使用分类、评分或小型生成模型做选择、拒选和回退 | 分数类型、校准版本、延迟、成本和错误均需记录；无 Provider 时产品仍可运行 | **可选增强，不是首版前置条件** |

### 渐进式上下文加载的参考判断

开源项目中存在相近做法，但通常是局部机制，不是与 Loomrise 六层配置完全相同的统一抽象：

- **Dify / Langflow**：知识检索、变量和工作流节点让资料在特定步骤进入上下文，可借鉴“按阶段加载”，但不照搬完整画布或把节点状态当作 Loomrise 业务权威。
- **AgentScope 等运行 SDK**：工具描述与工具结果通常按调用边界进入运行上下文，可借鉴“工具按需暴露、结果按需注入”；权限、确认和业务结果仍由 Loomrise `ExecutionService` 负责。
- **MCP**：能力发现与资源读取天然支持先看声明、再取具体内容，可借鉴“元数据先行、内容后取”；外部声明不能直接授予 Loomrise 工具权限。
- **SkillOpt / skill-up / SkillHone**：更接近技能选择、受限改动和历史证据管理，说明稳定规则与可优化文本应分离；它们不是 S1 的运行时上下文加载器，也不构成已验证的兼容承诺。
- **长期上下文/记忆系统**：可作为受治理的 Context Pack 来源，适合后续摘要、检索和跨会话加载；不承担 Loomrise 的任务、权限、工具或发布权威。

因此，Loomrise 的选择是“借鉴相邻模式，保持自己的执行合同”：S1 只做三段式加载和事件审计；S2 再验证更细的检索、摘要、缓存和质量门禁，并把 Skill 自进化限定为候选生成、独立评测和人工审批后的版本发布。当前这些判断属于架构参照，未完成兼容性或性能实测。

自进化规划还吸收了以下共同约束：原始轨迹不可变，失败先归因再改 Skill；候选 Skill 需要 provenance、依赖图、回归/迁移评测、成本记录和回滚；作者、执行者、审计者应逻辑隔离；生产运行只加载已发布版本。长期任务再引入结构化状态补丁和 reducer，不能靠不断拼接完整历史解决上下文增长。

### 首版建议组合

```text
Loomrise 自有：
ScenarioPack / AgentSpec / AgentVersion / ExecutionService
ServiceRequest / RunEvent / DecisionPolicy / Case / EvalSet / EvalResult
ChangeProposal / Release
                         │
     ┌───────────────────┼────────────────────────┐
     │                   │                        │
渠道/媒体适配       Agent 运行适配             外部能力适配
Web/Pipecat        AgentScope 候选       信息源/知识检索/业务工具
     │                   │                        │
     └───────────── ExecutionService ────────────┘
                         │
             AG-UI / OTel 事件投影与导出

DecisionPolicy 在执行内核中实施硬规则；DecisionProvider 可选且仅给建议。
```

文字和语音共享的是业务定义、任务状态、工具授权、取消语义和结果落库，不只共享一份提示词。AgentScope 是候选运行适配，不是文字专属业务权威；外部检索/工具供应商不直接决定领域对象。首版不同时建设 Pipecat、AgentScope Realtime、Qwen 三条生产语音链路；选定后只维护一条默认链路，其余保持实验或删除。

## 2. 平行参考与采用条件

| 项目 | 学习价值 | 当前不当主底座的原因或适用条件 |
|---|---|---|
| **TencentCloud/Octop** | 自托管、多用户、Web／IM、Agent 管理体验 | 整体 fork 会增加产品模型、升级和品牌耦合；作为应用参照和紧急交付备选 |
| **Dify / Langflow** | 模板、业务人员冷启动、知识与工作流体验 | 产品体验基准；不必对等建设全部画布，代码复用需另查许可 |
| **LiveKit / LiveKit Agents** | WebRTC 房间、SIP 与电话能力 | 网页语音扩到多人媒体或电话时再评估；不与 Pipecat 同时作为默认主栈 |
| **Omni-Interaction-Agent / Gander** | 全双工、改目标和过期结果处理 | 研究标杆；官方配置依赖较高资源，不进入普通 PC 默认部署 |
| **Tencent/SkillHone** | 决策历史、版本审阅和提案持久化 | P1 产品参照；首版不强迫本地 Lite 安装 Git 工作台 |
| **钉钉官方 Connector / Stream SDK** | 渠道事件、授权和消息去重 | 第二阶段验证具体宿主、接口类型与租户连接所有权 |
| **长期上下文系统（可选外部系统）** | 经治理的 Context Pack 来源 | 不承担 Loomrise 的运行、Agent 配置、渠道或发布权威 |

排除项：研究性自我修改系统不直接用于生产配置；模型训练、音色克隆、数字人、批量营销外呼不进入首版。

## 3. 保持独立产品的四条规则

1. **产品合同原创**：`AgentSpec` 描述业务目标、资料、知识快照、SOP／安全边界、字段和权限；`ServiceRequest/RunEvent` 描述执行事实；`ChangeProposal` 绑定坏例、diff、实验和审批。
2. **供应商依赖只在 Adapter**：AgentScope、Pipecat、Qwen、AG-UI、OpenTelemetry 和观测后端可替换；不沿用上游私有类型作为公开领域对象。
3. **案例包是传播资产**：发布可以下载、导入和验证的虚构场景包，包含资料、期望行为、坏例和回放报告，明确数据为模拟。
4. **传播围绕真实证据**：公开冷启动时间、任务成功、语音失败类型、前后对照与部署门槛；未运行的功能标记“规划”或“待验证”，不把仓库声明转成交付承诺。

供应商“开放兼容”先指可版本化的接入合同，不意味着已实现多家供应商。MCP 或 OpenAPI 可以作为业务方自定义工具的入口候选，但必须经过 Loomrise 的权限、确认、幂等、沙盒回放和结果审计；第三方工具声明本身不是授权。

## 4. 首个纵向 spike 的决策门

- **统一业务门**：文字与语音完成同一咨询和模拟预约，只产生一次业务写入。
- **事件门**：每次运行可关联任务、版本、渠道、工具、成本与真实终态。
- **恢复门**：取消请求与执行端确认分离；重启或弱网恢复不重复写入。
- **配置门**：场景可导出到干净实例并恢复相同配置与模拟结果。
- **音频门**：中文可懂度、首响、打断、播放确认、弱网恢复和媒体成本达到预先记录的业务标准。
- **退出条件**：若 AgentScope 适配持续侵入上游，比较 LangGraph 等替代；若语音对照无法在限时预算内通过，保留 Pipecat 主线或降低语音承诺。

**除 AgentScope 与 Pipecat 的隔离环境安装实测外，仍未运行语音质量、打断恢复、资源、时延或负载测试。** 源码级与安装级结论见[S1 验证结论与轻量适配](S1-VALIDATION-AND-ADAPTATION.md)。

## Sources

- AgentScope: https://github.com/agentscope-ai/agentscope
- Pipecat: https://github.com/pipecat-ai/pipecat
- Qwen Audio Agent: https://github.com/QwenAudio/qwen-audio-agent
- Octop: https://github.com/TencentCloud/Octop
- Dify: https://github.com/langgenius/dify
- Langflow: https://github.com/langflow-ai/langflow
- LiveKit Agents: https://github.com/livekit/agents
- Gander: https://github.com/Omni-Interaction-Gander/Omni-Interaction-Agent
- SkillHone: https://github.com/Tencent/SkillHone
- Microsoft SkillOpt: https://github.com/microsoft/SkillOpt
- EvoOntology: https://github.com/ruc-datalab/EvoOntology（arXiv:2609.15779；只取评估与门禁机制，见[S2 评测门禁与改进循环提案](S2-EVAL-GATE-PROPOSAL.md)）
- Alibaba skill-up: https://github.com/alibaba/skill-up
- AG-UI: https://github.com/ag-ui-protocol/ag-ui
- Langfuse: https://github.com/langfuse/langfuse
- OpenTelemetry GenAI: https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai
