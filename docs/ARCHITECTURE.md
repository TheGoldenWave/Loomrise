# 架构与对象权威 v0.1

状态：待 spike 验证。区分**产品控制面**、**Agent 运行**、**媒体/渠道**、**观测与评测**，避免用任一参考项目吞并整个产品边界。

```text
原创/获授权资料 → ScenarioPack → AgentSpec 草稿 → Web 文字/网页语音
                                           │              │
                                           │        Voice Adapter/媒体 Session
                                           │              ↓
                                           └────→ 业务策略/工具 ───→ RunEvent/Trace
                                                                 ↓
                                            审批/回滚 ← 固定集回放 ← ChangeProposal ← Case

文本 Adapter → AgentScope 2.0 SDK（候选）
语音 Adapter → Pipecat（候选），并与 AgentScope RealtimeAgent / Qwen Audio Agent 对照
观测导出 → OpenTelemetry → 可选 Langfuse
后续渠道 → 钉钉/企微 adapter；电话媒体与 SIP 单列
```

## 权威对象

| 对象 | 单一权威 | 必要状态/权限 | 删除/撤销 |
|---|---|---|---|
| `ScenarioPack`/原始素材 | 上传者/材料权利人；本项目只托管获授权副本 | 来源、使用许可/模拟标记、有效期 | 用户删除，停止后续检索；已发版本需标记失效并重验 |
| `AgentSpec` 与 `Release` | 本项目 | `draft → tested → approved → released → rolled_back`；版本不可覆盖 | 用户删除/停用；审计元数据依保留策略处理 |
| `RunEvent`/`Session` | 本项目 | 绑定租户、渠道、版本、成本、敏感级别、时间；媒体事件另标 | 租户可删除/脱敏；禁止跨租户可见 |
| `Case`、`EvalSet`、`EvalResult` | 本项目（人工 GT/红线为评测权威） | 题目级 rubric、固定集版本、生成来源 | 用户删除案例/证据引用，评测结果失去证据则失效 |
| `ChangeProposal` | 本项目 | `proposed → evaluated → accepted/rejected`；锁定段不可自改 | 可撤回、拒绝、审计 |
| API key 与 IM/线路授权 | 用户/供应商 | 后端受控保管或短会话代理，绝不写前端 bundle/Trace | 随时撤销/删除；相应运行停止 |
| 个人长期知识（若接 GoldenWave） | GoldenWave | 仅按授权读带引用的 Context Pack | 上游撤回时缓存失效，不复制其正式记忆库 |

## 最小领域合同（不宣称已实现）

- `AgentSpec@v1`：稳定 ID、场景目标、授权资料引用、SOP/安全锁定段、可改段、线索字段、工具权限、模型和预算。
- `RunEvent@v1`：`tenant_id`、`agent_id`、`config_version`、`session_id`、`run_id`、`channel`、序号、时间、事件类型、source ref、耗时/成本、脱敏策略、幂等键。文字、语音输出至少区分生成、发送、已确认播出/未知；打断时不把未播内容记作已被用户听见。
- `ChangeProposal@v1`：原配置版本、证据 Run/Case、结构化 diff、可修改范围、固定集版本、实验结果、提出者与审批人。未知主版本拒绝写入；验证成功不等于上线成功，上线需要单独回执。

## 部署路线（目标，不是已验证结果）

- 单 PC：控制台/API/Worker 尽可能少服务，用外部模型 API 跑通；本地数据默认不出机器，语音媒体单独 Worker，可在一台机器运行。
- 服务器：相同领域合同，关系数据库/对象存储、独立队列、无状态 API 与可扩容的文本/语音 Worker；租户隔离、权限、审计与预算成为上线门禁。
- 公共 Demo：登录、配额/并发/分钟上限；平台补贴与 BYOK 分开计费。服务端代理 BYOK 时透明告知密钥处理范围；不声称密钥只在本地。

## 失败与撤回

工具超时与重复提交需幂等；语音打断使待播片段和过期后台任务失效；上游知识撤回使引用/缓存失效；评测证据删除后不得继续展示无来源的“已验证提升”；用户停用 IM 授权时禁止继续收发。渠道可故障降级，但不得悄悄改为更高权限操作。
