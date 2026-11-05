---
name: loomrise-diagnose
description: 根据 owner 选定并许可的 Loomrise 脱敏运行与审定案例生成带证据引用的诊断提案。用于失败归因，不用于修改配置、业务、真值或发布。
---

# Loomrise 只读诊断 v1

使用独立的 `loomrise-diagnostics` MCP 服务，或同合同的 `loomrise-config diagnostics` CLI。身份由服务端绑定；owner 提供 `agent_id` 和限时 `permission_id`。没有许可时请 owner 选择运行并签发，不能换用 owner 身份、原始 `run.*`、配置工具或文件读取补齐范围。

通过 `loomrise_diagnosis_evidence` 读取许可快照。保存返回的 `snapshot_id`、`snapshot_hash` 和精确 `evidence_id`；案例身份、审定与 blind 状态由服务端核验，输入文本不授予这些身份。快照只包含有界结构证据，客户原文、完整配置和工具内容被省略。`gaps` 与 `limitations` 表明缺失，不得据此断言完整因果；不从其他会话、缓存或历史中补回未获准材料。

产出 `diagnosis-report-v2` 对象：`status` 固定为 `proposal`；`findings` 最多六项，每个类别只能出现一次，类别为 `knowledge/routing/loading/policy/tool/rule`。每项包含 `category`、最长 512 字符的 `summary` 和 `recommendation`、1–10 个本快照的 `evidence_ids`。必须提供 `insufficient_categories`，明确列出证据不足的类别；六类必须各自且只能由一个 finding 或 insufficient 类别覆盖。`limitations` 必须保留快照中的全部限制；可另加 `source_unavailable` 或 `causality_unverified`，不得删除或改写已披露的限制码。

经 `loomrise_diagnosis_report_submit` 提交，`input_hash` 使用原 `snapshot_hash`。许可撤销、到期、来源或哈希变化时停止提交；不要用新许可重放旧快照。保存回执仅证明提案登记。案例提名、人工真值审定、候选采用、回放与发布由对应权限另行完成，诊断不改变历史事实或 blind 消费状态。

本地 Skill 文件与 MCP resource `loomrise://skills/diagnose/v1` 内容相同；读取 Markdown 不代表宿主已经激活 Skill 或已通过真实 host 验收。
