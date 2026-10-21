# Loomrise Agent 协作指南 v0.3

日期：2026-10-14。状态：仓库协作规范；产品与实现状态以对应权威文件及验证证据为准。

本文件是新 Agent 的工作入口，保留文件名 `AGENTS.md`，不另建一份 `agent.md`。面向人的入口是 [README](README.md)，完整任务索引是 [文档总索引](docs/context/INDEX.md)。

## 1. 新会话启动与任务定位

1. **任何 shell 命令前**，先读取并遵循当前环境全局指令指定的绝对路径 `RTK.md`；所有 shell 命令使用 `rtk` 前缀。使用全局指令给出的完整路径，不相对仓库解析，不把本机路径、配置或凭据复制进仓库。
2. 检查 `rtk git status --short` 与已有改动，保留其他会话、用户和 Agent 的工作；未提交不等于废弃或可覆盖。
3. 阅读 [README](README.md) 与 [文档总索引](docs/context/INDEX.md)，确认任务属于产品、配置、客服应用、执行内核、评测、接入或部署。
4. 实质性工作前阅读 [PRODUCT](docs/PRODUCT.md)、[ARCHITECTURE](docs/ARCHITECTURE.md)、[ROADMAP](docs/ROADMAP.md) 与 [OPEN-SOURCE-BOUNDARY](docs/OPEN-SOURCE-BOUNDARY.md)，再按下表读取相关专题；不必先通读全部历史材料。
5. 对照当前代码、任务计划及验收报告，分别确定**已确认方向、待决策细节、已实现范围、未通过 Gate**。聊天记录和计划勾选不能单独证明实现或授权。

| 本次任务 | 专题入口 | 必须一起核对 |
|---|---|---|
| 产品范围、网页客服、自有云 | [客服交付计划](docs/CUSTOMER-SERVICE-DELIVERY-PLAN.md) | PRODUCT、ROADMAP、[产品形态与接入](docs/PRODUCT-FORM-AND-INTEGRATION.md) |
| 配置后台、初始化、前端原型 | [体验优化](docs/CONFIGURATION-UX-OPTIMIZATION.md) → [工作台 IA](docs/S2-IA-NAV.md) | [六层合同](docs/CONFIGURATION-LAYERS.md)、[启动简报](docs/S2-FRONTEND-DESIGN-BRIEF.md)；原型轮次及实施文件查总索引 |
| Task、主动服务、用户记忆/画像/上下文 | [联合计划](docs/TASK-MEMORY-INTEGRATION-PLAN.md) → [Task设计](docs/TASK-SYSTEM-DESIGN.md)、[用户上下文设计](docs/USER-CONTEXT-DESIGN.md) | PRODUCT、ARCHITECTURE、ROADMAP、六层合同与命名；新增合同/分期提案未实现，前端轮次独立 |
| MCP、CLI、外部 Skills、通用 harness | [Agent 接入开发计划](docs/AGENT-INTEGRATION-PLAN.md) | [初始化与摄入](docs/INTAKE-AND-INITIALIZATION.md)、ARCHITECTURE、REFERENCE-PROJECTS |
| S1 代码、依赖或运行验证 | [S1 交付与验收](docs/S1-BUILD-REPORT.md)、[版本钉](VERSION-PINS.md) | 对应 `loomrise/` 模块、`tests/` 与 `scripts/`；[适配验证快照](docs/S1-VALIDATION-AND-ADAPTATION.md)只作历史依据 |
| 改进、评测、审批与发布 | [S2 治理设计](docs/S2-DESIGN.md) → [评测门禁提案](docs/S2-EVAL-GATE-PROPOSAL.md) | [范围决策](docs/S2-SCOPE-DECISIONS.md)、ROADMAP；逐节分清已确认与待确认 |
| 硬规则、记忆或供应商选型 | [硬规则模型](docs/HARD-RULE-MODEL.md)、[记忆提案](docs/MEMORY-FOUNDATION-DESIGN.md)、[参考项目](docs/REFERENCE-PROJECTS.md) | 提案不等于已选型；改技术选择或适配边界前必须读 REFERENCE-PROJECTS |

## 2. 项目事实与权威范围

Loomrise 面向客服、销售，服务 AI 产品经理、解决方案人员、小团队开发者与策略运营。目标形态是**交付工作台 + 官方网页客服应用 + 统一执行内核 + 分类适配器**，从授权材料生成可运行、可验收、可部署和可持续改进的应用。具体定位由 PRODUCT 管理。

- `loomrise/` 已有 **S1 最小纵向切片**；S1 退出 Gate 仍未全部通过。实测结论及缺口以 S1-BUILD-REPORT 和 ROADMAP 为准。
- `prototypes/` 是**本地前端评审工件**。本地保存、脚本答疑、模拟接管、审批、发布或云部署不证明真实 S2 服务实现。
- 完整客服、后台持久化、真实外部业务写入、发布门禁、持续改进、云快捷部署和多租户仍须按阶段验收；禁止从枚举、页面或规划推断功能已完成。
- 工作台供搭建者与策略运营使用；访客和一线坐席使用客服应用。人评真值、实时接管、一线坏例提名是不同事实，权限和产物不能混同。

文件冲突按**问题所属范围**核对：PRODUCT 管定位；ARCHITECTURE 管领域对象与权威；ROADMAP 管阶段与 Gate；客服交付计划管覆盖矩阵；Agent 接入计划管 AGI 工作包；S1-BUILD-REPORT 管实际验收；VERSION-PINS 管实际构件。索引只指路，研究与历史快照不覆盖现行决策。详细分工和局部替代关系见总索引；无法消解的矛盾应记录待决策，不能按“文件日期最新”自动改方案。

## 3. 架构与授权护栏

- Loomrise 拥有 `ScenarioPack`、`AgentSpec`、`AgentVersion`、`ExecutionService`、`ServiceRequest`、`RunEvent`、`DecisionPolicy`、`Case`、`ChangeProposal` 与 `Release`；目标合同与 S1 最小实现分别标注。
- AgentScope、Pipecat、AG-UI、OpenTelemetry、Langfuse 及通用 harness 的私有状态留在 Adapter，不能进入公共领域合同；不整体 fork Dify、Octop 或上游 runtime。
- 文字与语音共用业务状态、版本、权限、工具、取消语义及持久结果。生成、发送、播放和业务完成分别记账。
- 模型声称完成不是证据；业务完成需要持久结果及适用的外部结果 ID。保留幂等、取消执行确认、执行前权限重验、预算和审计。
- 可执行配置与评测集均须版本化。硬规则、业务价格与承诺、工具权限、验收真值和批准权不能由模型分数或优化作业静默修改。
- 初始化助手可关闭，完整手动路径独立可用；先用授权资料试用客服，再接业务工具。概览与详细配置共用版本。
- Task体系统一运营预设策略与会话TODO，事项暂称TaskItem，不覆盖ServiceRequest或上游RuntimeTask；实例调整只在批准范围，策略/权限/承诺变更仍评测审批。用户记忆、派生画像与本次上下文统一治理、保留各自权威，记忆不能授予触达权或持有任务执行终态；新增合同/模块仍为提案，未实现。
- 外部创作 Agent、后台 harness Worker 与在线客服执行分工；共用应用服务和合同，不开放外部 Agent 的生产业务写入或直接发布权。外部使用 Skills 与内部 `SkillManifest` 分开。
- 公开示例只使用原创虚构或明确授权材料，不使用雇主、客户或第三方私有资产。

## 4. 公开与私有边界

[OPEN-SOURCE-BOUNDARY](docs/OPEN-SOURCE-BOUNDARY.md) 是分类权威。`private/` 仅本地使用、已被 Git 忽略：

- 不暂存、不强制添加、不把私有原文引入公开文件，不让公开文档依赖私有链接。
- 未确认个人判断、商业化、预算、职业策略、雇主语境和原始私有研究留在 `private/`。
- 晋升到公开侧前先分类、脱敏、重构为独立可读的结论并标记证据状态。
- `private/` 不是密钥管理器；API key、密码、token 与客户隐私不能因 Git 忽略而存入其中。

## 5. 文档维护与归档

- 中文写作，保留必要英文标识。演进文档写版本、日期、范围和状态，区分已确认、待决策、待验证、规划、已实现与已验证；单文件可按节有不同状态。
- 新资料先归类：现行依据、专题设计／计划、验证证据、研究参照或历史归档。优先更新既有权威文件，避免同题多份“最终方案”。
- 新建、改名、移动或替代文件时同步 [总索引](docs/context/INDEX.md) 的用途、状态、关联与后继；README 保留少量任务入口，不恢复为全文档长清单。
- 归档按 [归档说明](docs/archive/README.md) 执行：完整失效文件可迁移；仅一节失效则归档该节并保留现行正文。研究、未决提案、仍在用的原型和证据不能因“较旧”直接归档。
- 定位变化必须同步 README、PRODUCT、ARCHITECTURE、ROADMAP 和受影响专题。仅导航整理不改变产品承诺或实现状态。
- 未经明确公开授权，不发布预算、工时报价、个人品牌或营销排期；无可复现证据不宣称生产级、企业级、统计显著、首创或测得性能。

## 6. 工作流程与会话交接

1. 检查工作区并保护无关改动，先判断信息属于公开还是私有。
2. 用总索引选择权威文件和相关计划，检查依赖、开放问题与已有验证；先确定本轮最小完整范围。
3. 按当前用户授权执行，修改尽量局部；并行会话可能更新同一文件，写入前重读受影响段落，禁止用旧快照覆盖整份文件。
4. 同步交叉引用、状态和对应计划；依据实际工件完成适当验证。
5. 结束时报告**改了什么、实际验证了什么、仍缺什么**。需要接力的多步骤工作在对应实施计划或报告留下：范围、已完成工件、剩余任务／阻塞、验证命令与证据位置、下一步及依赖；总索引登记其入口。公开交接只记录可公开任务事实，不抄聊天或私人授权材料。
6. 新会话从这些文件与当前工作区恢复；不把历史计划当作启动自动化、外部写入、消息发送或发布的新增授权。

## 7. 必须验证

文档工作完成前执行：

```text
rtk git status --short
rtk git diff --check
rtk git check-ignore -v private/
rtk git diff --cached --name-only
```

另外检查修改范围的本地链接、目录与锚点、索引覆盖、术语和状态；移动文件要检查入链与相对路径，历史目录中的文件也算检查范围。若暂存区出现 `private/` 或敏感文件，停止并移出暂存区后再继续。未经用户明确要求，不重写 Git 历史或强制添加文件。
