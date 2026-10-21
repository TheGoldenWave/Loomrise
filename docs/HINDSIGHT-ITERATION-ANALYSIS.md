# Hindsight 的智能体迭代机制与 Loomrise 适用分析 v0.1

> 状态：**上游源码与文档已核；应用方案为提案、待验证，未接入 Loomrise**。2026-10-12。核对版本：[vectorize-io/hindsight `3ca6a67`](https://github.com/vectorize-io/hindsight/tree/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad)（本地浅克隆于 `_reference/hindsight`，该目录不进入 Git），仓库 `LICENSE` 为 MIT；`hindsight-api` 与 Python client 的 `pyproject.toml` 均声明 `0.10.3`。本次只读代码、文档与示例，**未安装、启动、联调或测量效果**。

## 1. 结论与边界

**列入重点参考项目，重点借鉴“有来源的经验沉淀 → 模式归纳 → 改进假设”这一段；不把 Hindsight 的记忆更新等同于 Loomrise 的 Agent 版本迭代。** Hindsight 解决的是跨交互积累事实、经验与观察，并在后续检索或推理中使用。Loomrise 还必须证明业务终态、区分已审定真值与反馈提名、对候选做配对回放，并由人审批发布。这些发布职责仍由 Loomrise 的 `Case`、`EvalSet`、`ChangeProposal`、`AgentVersion` 和 `Release` 持有。

当前已有 [TencentDB Agent Memory 接入提案](MEMORY-FOUNDATION-DESIGN.md)，不能仅凭 Hindsight 功能列表更换或叠加记忆内核。Hindsight 暂定为 **P0 机制研究与有限对照候选**；是否成为 `MemorySourceAdapter` 的另一个实现，要等同条件试验。S1 未实现长期记忆优化，S2 改进与发布闭环也仍在规划。

## 2. Hindsight 实际怎样“学”

| 环节 | 上游已核机制 | 对 Loomrise 的含义与限制 |
|---|---|---|
| `retain` | 从输入提取事实、实体、关系和时间信息；`metadata` 会随记忆返回。相同 `document_id` 默认替换旧文档及其派生记忆；异步写入可自带 `operation_id` 以安全重试。见 [Retain API](https://hindsight.vectorize.io/developer/api/retain)。 | 可以用 `RunEvent`/已审定 `Case` 的**脱敏摘要**作输入，并绑定源 ID；替换语义与异步完成必须留回执，不能把请求已提交当成记忆已生成。 |
| Observation consolidation | 把相关原子事实合并为可更新的观察结论，保留来源记忆、历史与 `proof_count`；矛盾或新事实可修正结论。可关闭自动整理，按需触发。见 [Observations](https://hindsight.vectorize.io/developer/observations) 及[实现](https://github.com/vectorize-io/hindsight/blob/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad/hindsight-api-slim/hindsight_api/engine/consolidation/consolidator.py)。 | 可为“同类失败反复出现”生成**诊断线索**。`proof_count` 统计支持它的来源记忆数，不等于相互独立的用户数、人工真值数或统计显著性。需要回查原始 `RunEvent`、去重和人工核定。 |
| Mental model | 人明确指定长期要回答的问题；上游在相关记忆变化时后台刷新答案，保存依据和旧版本。见 [Mental Models](https://hindsight.vectorize.io/developer/mental-models)。 | 适合作为“本场景常见失败及证据”这类分析视图。它是可变的派生知识，不能直接写入已发布 `AgentVersion` 或替代冻结的评测集。 |
| `recall` / `reflect` | `recall` 结合语义、关键词、图关系及时间检索；`reflect` 会分层查长期结论、观察和原始事实，返回回答及可选 `based_on` 证据。见 [README](https://github.com/vectorize-io/hindsight/blob/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad/README.md) 与 [Reflect](https://hindsight.vectorize.io/developer/reflect)。 | `recall` 可作上下文候选来源；`reflect` 可给出“可能因为什么失败、下一步试什么”的**提案材料**。生成的分析和引用校验仍不是业务裁决、硬规则或发布批准。 |
| 反馈影响后续选择 | 官方 [Tool Learning 示例](https://github.com/vectorize-io/hindsight/blob/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad/hindsight-docs/src/pages/cookbook/recipes/tool-learning-demo.md) 把人工给出的正确路由写入记忆，随后由包装器检索并注入模型调用；示例脚本对比写入前后的工具选择。 | 这是**记忆增强的行为适应示例**，不是已证明的持续优化效果。示例没有 Loomrise 所需的业务结果持久化、盲测、配置版本、审批与回滚；本次也没有运行该示例。 |

从技术层看，它的循环是 `retain → consolidation → recall/reflect → 后续回答或选择`。其中“行为变化”可以在不生成新版配置的情况下发生。Loomrise 必须把这种**运行时上下文变化**与**受控版本升级**分开记录，否则无法说明一次结果变化究竟来自模型、记忆、资料、工具还是 Skill 版本。

## 3. 映射到 Loomrise 的可行路径

### A. 先做离线诊断线索，不改变线上 Agent

1. 从同一 `ServiceRequest` 的 `RunEvent` 提取已脱敏的工具调用、结果 ID、失败类型、取消/接管事实；一线坏例反馈保持 `CaseNomination`，策略运营审定后才成为 `Case` 真值。
2. 按租户与场景隔离存放摘要，记录 Loomrise 源 ID、源版本、生成时间、授权范围与删除入口。允许 Hindsight 归纳“反复出现的困惑或失败”，但每条结论都必须能回到原始事件，且显示已核定/未核定。
3. 用 `reflect` 形成单个失败模式的候选归因，例如“试听预约被重复提交，可能与确认后重试有关”。策略运营复核后才生成 `ChangeProposal`；提案只修改允许的 Skill/SOP 文本、示例、澄清顺序或有限检索参数。
4. 旧版与候选版仍按 [S2 评测门禁提案](S2-EVAL-GATE-PROPOSAL.md) 回放；`golden` 只判不退步，`blind` 批次用于 Gate，人工审批后才能发布。Hindsight 不接管门禁状态机。

这条路径可与现有记忆内核选型并存为**研究实验**：只把输出作为离线建议，不增加生产运行时依赖。

### B. 通过对照再决定是否接入运行时记忆

若需要跨会话个性化，Hindsight 只能经 `MemorySourceAdapter` 读取，转成带 `source_ref`、`source_version`、有效期、敏感级别和加载原因的 `ContextFragment`，进入现有 `evidence` 段；加载、跳过与失效都写 `RunEvent`。不采用自动拦截模型调用并注入记忆的 LLM Wrapper，因为那会绕过 Loomrise 的上下文选择与留证。记忆不能授予工具权限，也不能覆盖 `HardRule`、`ToolPolicy` 或知识真值。

先将 Hindsight 与 TencentDB Agent Memory 在**相同虚构材料、相同模型与预算**下做小规模对照：跨轮召回是否正确，矛盾纠正是否保留来源，撤销后派生观察是否失效，跨租户/用户是否隔离，超时故障时业务是否继续，以及额外时延、token 与运维负担。对照通过后再决定“保留既有候选 / 增加可选适配器 / 替换候选”，不预设赢家。

## 4. 必须守住的四个风险点

1. **来源数量不是真值**：重复上报、同一事实多次转述都会抬高观察结论的“支持数”。诊断提案需显示独立 `ServiceRequest`/用户数、相反证据与人工审定情况；模型归纳只负责提出待查线索。
2. **隔离不靠标签**：Hindsight 的 bank 是隔离单位，tag 只用于检索分组；`bank_id` 应由 Loomrise 已认证身份构造，不能从外部请求任意指定。上游自托管服务[默认不开启 API 鉴权](https://hindsight.vectorize.io/developer/configuration#authentication)，试验也只能放在受限环境，并核验删除与跨租户读取。
3. **更新不等于发布**：自动 consolidation 和 mental model 刷新会改变后续可见上下文；若接入运行时，每次读取必须记录 ID/版本或内容哈希。上游 `reflect` 的 directive 只是其推理约束，不能代替 Loomrise 模型外的确定性裁决。
4. **隐私、审计与成本**：只提交获授权、已脱敏、可撤销的业务摘要；不送原始录音、客户资料或凭据。上游[默认保留输入文档原文、审计日志默认关闭](https://hindsight.vectorize.io/developer/configuration)，试验配置需显式确认保留策略与审计方式。异步处理、检索与反思的模型成本和时延要单独记账；未运行前不宣称更快、更准或可用于生产。

## 5. 建议的最小验证与通过条件

| 验证 | 可判定的通过条件 |
|---|---|
| 失败模式归纳 | 用虚构的重复预约、错误路由、资料撤销和人工接管记录构造样例；每条观察与提案都能反查源 `RunEvent`/`Case`，提名不会被标成真值。 |
| 更新与撤销 | 同一 `document_id` 重试/替换后不留下重复或过期结论；删除/撤销后，检索与长期结论不再引用失效来源，留操作回执。 |
| 权限与运行边界 | 跨 bank 读取失败；记忆里出现“免确认写入”时，`HardRule` 仍拒绝；记忆服务不可用时 S1 既有 11/11 确定性回放不退步。 |
| 改进闭环 | `reflect` 仅产出带来源的候选归因；候选改动在冻结条件下与父版本配对回放，Gate 结果和人工审批分别留证。 |

**本次完成的是参考项目核查与方案分析，上表均未执行。** 只有这些条件实测通过，才可以把 Hindsight 从“重点机制参考”升级为可选运行时适配器。

## 6. 来源与核查范围

- 上游仓库与许可：[Hindsight `3ca6a67`](https://github.com/vectorize-io/hindsight/tree/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad)、[MIT License](https://github.com/vectorize-io/hindsight/blob/3ca6a67a873f8dd269ae243f1b6c67ff6155a5ad/LICENSE)。已读 `README.md`、两处 `pyproject.toml`、`hindsight-docs/docs/developer/{observations,reflect,mental-models}.mdx`、`api/{retain,memory-banks}.mdx`、工具学习示例及 consolidation 实现；未运行服务或性能/质量 benchmark。
- 官方机制文档：[Retain](https://hindsight.vectorize.io/developer/api/retain)、[Observations](https://hindsight.vectorize.io/developer/observations)、[Mental Models](https://hindsight.vectorize.io/developer/mental-models)、[Reflect](https://hindsight.vectorize.io/developer/reflect)、[Memory Banks](https://hindsight.vectorize.io/developer/api/memory-banks)。上游自述的 benchmark 与生产客户声明未独立核验，不作为本报告选型证据。
- Loomrise 对照：[架构与对象权威](ARCHITECTURE.md)、[S2 评测门禁提案](S2-EVAL-GATE-PROPOSAL.md)、[用户记忆模块基石接入设计](MEMORY-FOUNDATION-DESIGN.md)。
