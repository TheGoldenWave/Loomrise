# 可迭代 Agent 工作台：参考项目分级清单与双模态路线 v0.2

> 2026-09-26；本文件覆盖《可迭代企业Agent开源平台立项探索》里“Octop 优先作为 fork 基座”与“语音后置”的初步假设。这里是**上游文档核对后的候选清单**，不是安装、性能或 API 兼容性的实测结论。本人 GitHub 284 个 Star 已枚举，以下只保留与目标直接相关的项目。

## 0. 已确认的产品前提

- 第一用户：**业务 PM / 运营**，而非首先服务开发者。输入 FAQ、SOP、转人工规则、线索字段，输出可试用 Agent 与解释性运营报告。
- 独立定位：**面向业务人员的 Agent 冷启动和可验证自迭代工作台**。业务价值来自“资料→配置→文字/语音试聊→完整 Trace→Badcase→候选改动→回放→审批/回滚”，而不是底层模型、聊天壳或 fork 的品牌。
- 展示场景：**售前客服 + 线索预约**；用独立创作、明确标注“虚构/模拟”的行业品牌、FAQ、用户和线索，或只使用允许复用的公开资料。不要使用雇主或第三方未授权内容、内部 Prompt、真实客户数据；“典型行业”不能偷换成“真实企业合作案例”。
- 文字、**网页语音**同步做最小纵向切片；电话外呼是后续独立渠道，不等于网页麦克风。教育、二手车/汽车可以做首批模板；保险、牙科、医美仅演示一般信息与预约转接，不做诊断、疗效、收益或价格承诺。
- 首发既能用外部模型 API 在单机跑，也保持将来服务器多实例扩容的边界；不能把“大模型在任意 PC 本地运行”当作默认承诺。

## 1. 首选研究/试接项目（按对首版的决定性排序）

| 优先级 | 项目 / 角色 | 具体借用 | 必须验证的集成条件 | 结论 |
|---|---|---|---|---|
| **P0-1** | **AgentScope 2.0**：文本 Agent 运行底座 | Agent、工具调用、记忆/状态、权限/人类确认、部署与可观测扩展；上游也已提供标为 **Experimental** 的 `RealtimeAgent` 和钉钉渠道，值得做一条统一 Runtime 的最小实验。[1] | 能否按版本实例化、在关键节点出结构化事件、支持人工接管与可重放；其实时语音是否足够支持打断/播放回执；不直接借旧版 AgentScope Runtime/Studio 仓库 | **首选 SDK 集成**，不 fork 整个平台 |
| **P0-2** | **Pipecat**：语音编排/传输候选 | WebRTC/WebSocket、STT/LLM/TTS/实时模型插件、打断/轮次/可观测；复用业务策略服务，不把 Pipecat Frame 硬塞进文本 Agent 核心。[7] | 单机网页语音启动、打断与播出回执、将 tool/文本事件映射到共用 Run、是否能独立部署 Voice Worker | **首选工程骨架**，与 Qwen 语音方案做一次对照 spike |
| **P0-3** | **QwenAudio/qwen-audio-agent**：低时延语音与后台任务样本 | 前台实时语音会话 + 后台持久任务的分工；研究 `spawn_thinking`、事件回流、取消、WebRTC SDK，以及语音直连和外围业务工具如何配合。[3][4] | 前台/后台能否接入本项目版本化业务规则、成本、私有部署要求；不能把它的整套个人助手直接当企业售前 Agent | **架构首选参照 + 语音对照实现**，具体模型/工程可复用度待跑通 |
| **P0-4** | **Langfuse + OTel GenAI**：Trace/评测方法 | 观测、打分、数据集、实验 UI；统一 `tenant_id/agent_id/config_version/session_id/run_id/channel` 与脱敏口径，向 OTel 导出。[9][18] | 单机安装负担和数据可控性；最小首版可仅持久化本项目 RunEvent，并提供 Langfuse 可选导出 | **规范先行；完整服务非单机强依赖** |
| **P0-5** | **Microsoft SkillOpt + alibaba/skill-up**：受控优化候选 | 轨迹分组、限定编辑预算、可变/锁定段、旧版对照、固定集验证与候选 Skill/Prompt。[10][11] | 对业务场景的成功判定不是研究 benchmark；必须独立评测集与人工审批，禁止自动改红线和真实生产版本 | **借机制，不把研究算法包装成可直接生产的自动优化器** |
| **P0-6** | **AG-UI**：网页事件协议参考 | 文字流、工具状态、人工交接、前端事件；可让文字和语音转写/播放状态在一个 UI 中呈现。[12] | 是否需要全部协议事件；最小实现可内部 `RunEvent v1`，外层适配 AG-UI | **协议参考/兼容目标，不让第三方 UI 协议决定领域模型** |

### 首版建议组合

```text
本项目自己的 AgentSpec / ScenarioPack / RunEvent / Case / ChangeProposal / Release
          │                         │
          ├── Text Agent Adapter ─── AgentScope 2.0
          ├── Voice Agent Adapter ── Pipecat（对照 AgentScope RealtimeAgent / QwenAudio）
          ├── Web Transport ──────── Web 文本 + 浏览器麦克风
          ├── Trace Export ───────── OTel → 可选 Langfuse
          └── Eval/Optimizer ─────── 固定案例 + 硬规则 + 人工判定 + 受限候选编辑
```

“文本和语音同步推进”指**同一个业务定义、共享的运行追踪与回归测试**各有一条最小可运行通路，不是首版同时做全双工、SIP 外呼、多租户高并发和全部 IM 渠道。语音有自己的媒体 session、VAD/轮次、打断取消、播放确认；从语音产生的业务意图再进入共用策略/工具服务。Trace 需区分“生成、发出、实际播出”，避免打断后把用户没听到的话写入上下文。此取舍来自作者对实时全双工语音与帧管道语音架构的研究；可公开事实以本文件上游来源为准。

## 2. 平行参考（选型比较 / 第二阶段集成）

| 项目 | 学习价值 | 当前不当主底座的原因或适用条件 |
|---|---|---|
| **Omni-Interaction-Gander/Omni-Interaction-Agent**（腾讯项目） | Cerebellum 快速交互 + Brain 异步强推理/执行的“边聊边办”；全双工与事件系统。[5][6] | **研究标杆而非单 PC 默认依赖**：其研究演示使用多张高端 GPU；不应宣称“腾讯小模型方案可直接低成本部署”。与千问项目确属两条不同路线。[5][6] |
| **TencentCloud/Octop** | 快速自托管、多用户、Web/钉钉/企微、Agent 管理；用它检验自己的冷启动与部署体验是否真的更好。[2] | 整体 fork 会使独立产品边界、升级和品牌难以掌控。优先做**对标与可选渠道适配**；只有明确的扩展合同和上游协作路径成立，才考虑代码层复用。 |
| **LiveKit Agents** | WebRTC/房间模型、SIP/电话能力与大规模实时会话。[8] | 当网页语音要扩成电话或多人媒体、并接受其媒体基础设施时升级；首版不与 Pipecat 双主栈并存。 |
| **Dify / Langflow** | 模板、业务人员冷启动交互、知识/RAG 工作流和公开分享流程。[13][14] | 是产品体验基准，不必对等建设全部节点画布；Dify 代码复用要另查许可和商用条件。 |
| **Tencent/SkillHone** | Skill 决策历史、版本审阅、PR 化更新，可对照产品的变更证据链。[15] | 偏编码 Agent/Skill 管理方法，非本产品完整业务 Agent 后台。 |
| **钉钉官方 Connector** | 官方渠道事件/授权的实现参考。[17] | 对接第二阶段业务 IM，不能替代网页语音接入或电话合规。企微另需按官方接口权限验证。 |
| **GoldenWave**（本人项目） | 长期知识 Candidate/Context Pack 的可选来源 | 不承担本项目的 Run、Agent 配置、渠道或发布权威；避免两个项目复制造“长期记忆平台”。 |

**排除项**：Flowise 仅研究历史 UI/模板，不再作为基座；上游已公告维护终止。[16] Tencent Gander 和 Meta HyperAgents 这类研究系统只能在隔离环境研究，不用于自改生产配置。模型训练、音色克隆、数字人不进入首版。

## 3. 让它成为“你的独立项目”的四条规则

1. **产品合同原创**：`AgentSpec` 描述业务目标、语料、知识版本、SOP/安全边界、线索字段与转人工；`RunEvent` 描述跨渠道执行事实；`ChangeProposal` 绑定坏例、diff、实验和审批；都由本项目维护版本/迁移/示例与文档。
2. **供应商依赖只在 Adapter**：AgentScope、Pipecat、Qwen、Langfuse 可替换；不要沿用其项目名称充当自己的领域对象、数据库主键或导出格式。实际选用依赖遵守上游许可证和署名，不以“独立品牌”掩盖其贡献。
3. **案例包是传播资产**：先发布原创的“虚构在线课程咨询/预约”与“虚构二手车预约试驾”两份可下载 ScenarioPack，附资料、人工写的 expected behavior、坏例、回放报告；明确虚构与生成方式，绝不宣传成真实企业效果。
4. **传播持续围绕真实进展**：公开冷启动时间、语音打断成功率、错误类型、改动前后固定集结果与部署门槛，记录失败和取舍；“企业级”需靠权限、隔离、审计和扩容实测逐项兑现，首版只声明单机可试用。

## 4. 两条并行纵向 spike（决策门）

- **A：文本**：AgentScope 单 Agent，导入原创教育/二手车案例包，生成可编辑 AgentSpec → Web 文字问答/线索预约 → 人工转接 → 一条 RunEvent 链 → 固定集回放 → 改动候选及人工确认。
- **B：语音**：同一 AgentSpec 从网页麦克风发起 → 语音链路获取业务答复 → 打断/恢复 → 预约字段更新 → Trace 记录转写片段、推理、合成、播放确认；先跑 Pipecat 最小服务，并用 AgentScope `RealtimeAgent` 检验单一 SDK 路线能否减轻集成；QwenAudio 则检验“轻前台+后台任务”是否值得做 Voice Adapter。不得用单机完全本地化作为通过条件；可使用 BYOK 的云模型但必须设置分钟/并发预算。
- **A/B 共用验收**：相同业务约束与线索字段；各自有可追踪版本和错误；业务 PM 不改代码能看到失败原因并执行一次审批/回滚。选定依赖前记录许可证、活跃维护、最低硬件、单机启动步骤与真实启动耗时。**当前均未运行安装与负载测试。**

## 5. 来源与本地参照

作者的私人研究笔记曾用于归纳语音 Agent、评测和经验迭代模式；本清单的公开事实与项目引用以以下上游来源为准。私人资料和雇主内部系统不随本仓库发布。

## Sources

[1] https://github.com/agentscope-ai/agentscope
[2] https://github.com/TencentCloud/Octop
[3] https://github.com/QwenAudio/qwen-audio-agent
[4] https://github.com/QwenAudio/qwen-audio-agent/blob/main/docs/architecture/deep-dive.md
[5] https://github.com/Omni-Interaction-Gander/Omni-Interaction-Agent
[6] https://arxiv.org/pdf/2609.08977
[7] https://github.com/pipecat-ai/pipecat
[8] https://github.com/livekit/agents
[9] https://github.com/langfuse/langfuse
[10] https://github.com/microsoft/SkillOpt
[11] https://github.com/alibaba/skill-up
[12] https://github.com/ag-ui-protocol/ag-ui
[13] https://github.com/langgenius/dify
[14] https://github.com/langflow-ai/langflow
[15] https://github.com/Tencent/SkillHone
[16] https://github.com/FlowiseAI/Flowise/discussions/6727
[17] https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector
[18] https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai
