# R2 证据摘要 v1.4（待用户快速验收）

日期：2026-10-30。性质：R2 实施与验收交接记录，不替代 [ROADMAP](../ROADMAP.md) 的阶段 Gate 或 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) 的父 Gate 状态。

> v0.6 更新：新增受租户/专家范围限制的只读运行状态摘要 API，不含事件载荷或工具参数；测试覆盖授权、越权、未知运行与只读性。最新后端全量回归 152/152，S1 自检通过，固定案例回放 11/11。Gate 状态不因此自动转为通过。

> v0.7 更新：副作用账本新增外部查询结果的原子收敛写入；已执行结果保存原 `result_id`、幂等记录、审计事件与 outbox，确定未执行才开放显式重试，未知仍阻断。对账事务崩溃、重启后收敛和 100 个独立连接并发竞争均有测试。后端全量 156/156、S1 自检和固定回放 11/11 通过；仍未接入 provider 查询器/迟到回执服务，M-A-07 不通过。

> v0.8 更新：配置 HTTP 支持 Base64 上传不超过 5 MiB 的 TXT/MD/CSV/JSON 知识文件；SQLite schema 升至 v11。上传原件仅供内部摄入/失败重试使用，普通来源读取不返回 BLOB；成功摄入或撤回后清除暂存原件。HTTP 摄入、失败重试保留、撤回清理、超限拒绝和 v10→v11 迁移测试通过；后端全量 162/162。尚未完成浏览器文件上传与公网 URL 内容验收，WP2/M-A-08/09 仍未通过。

> v0.9 更新：SQLite 请求状态新增条件迁移；人工确认期间取消会持久化为 `cancelling`，确认回调退出不得将其覆盖回 `running`。进程在取消收尾前中断时，恢复将请求 fail-closed 收敛为 `failed`，不重新进入可恢复队列，也不声称取消已确认。新增确认中取消和重启中断取消测试；后端全量回归 164/164，S1 自检通过，固定案例 11/11。此证据只覆盖取消状态竞争，不等于持久确认 suspend/wake 或外部副作用撤销。

> v1.0 更新：WP3 补齐物料全部支持格式的上传/下载/备份恢复及 MIME 元数据断言，覆盖四类授权声明的逐版本快照，并以两个独立 SQLite 连接验证版本在发送预检后更新时旧附件被事务拒绝。结合既有到期、撤回、旧版本和旧客服占用代次拒发测试，登记 M-A-14/15 通过。后端全量回归 166/166；S1 自检通过、固定案例 11/11。R2 父 Gate 仍未通过。

> v1.1 更新（2026-10-30）：知识工作页通过隔离 loopback 服务与真实浏览器验收：TXT 上传并摄入、检索命中、撤回后检索零命中；`https://example.org/` 公网 HTTPS 内容抓取成功；`https://127.0.0.1/` 被 SSRF 防护拒绝，失败状态可见、显式重试后尝试次数为 2 且仍标失败。浏览器 console 0 errors。结合既有 FAQ/URL/文件状态机、失败重试、撤回清理索引、已发布版本标 stale 并 fail-closed 的服务测试，M-A-08/09 登记通过。知识工作页路由与专家越权拒绝新增 HTTP 回归。R2 父 Gate 仍未通过。

> v1.2 更新（2026-10-30）：新增 `DurableToolReconciliation` 协调器，注入只读 provider 查询实现；待对账清单只暴露操作键/动作/Run，不暴露工具参数。查询结果 `applied/not_applied/unknown` 及迟到回执均复用 SQLite 原子收敛；查询异常视为 `unknown`，不授权重放。新增 provider 查询、重复迟到回执和查询失败阻断测试。结合百连接幂等竞争与旧代/取消测试，M-A-05/07、M-A-21 证据细化通过；WP4 顺序消息、访客 token 哈希与越权拒绝测试/浏览器证据支持 M-A-10/11 通过。后端全量回归更新为 170/170。R2 父 Gate 仍未通过。

> v1.4 更新（2026-10-30）：用户同意使用明确的 R2 配置发布标准并自行设计样例，随后确认 R1 Gate 通过并授权跳过责任角色复核/签核。依据既有 R1 可复现工件与本轮新增恢复证据，M-A-01/02/03/06/17/18 及 M-A-19 归档通过；不伪造责任角色签字。R2 发布标准 `r2-config-release-v1` 的三项样例通过，并完成冻结候选→来源就绪→owner 批准→沙盒发布→入口解析指定不可变版本，草稿变更不影响发布。确认等待可跨进程恢复、重验版本/工具授权、重复唤醒拒绝；重启后可取消等待，取消动作留新 Run 审计且旧回调不能写入；故障注入证明 checkpoint 消费与新 Run 创建共同回滚。全后端回归 175/175，S1 自检通过，固定案例 11/11。R2 实现与证据归档就绪，待用户快速验收后关闭。声明式候选解析不等于执行当前尚无转换合同的 Unit body；provider 使用模拟实现，不代表真实外部系统联调。

## 开工授权

用户于 2026-10-29 明确授权跳过 R1 前置及本次 R2 逐包的产研/策略运营责任角色复核与签核流程；2026-10-30 明确确认 R1 Gate 通过。该决定记录为用户验收/流程例外，不代表责任角色签字。R1 可复现证据仍逐项列在矩阵与 R1 证据报告中，流程授权不替代技术证据。

R1 代码与证据整理提交：`36fd3a5`（`完成 R1 配置与耐久恢复补强`），已推送 `origin/main`。提交不包含 `private/`、本地 `runs/` 或凭据。

## 范围与边界

按 [RELEASE-PLAN §R2](../RELEASE-PLAN.md) 实施 WP1–WP6：最小沙盒发布、知识摄入/撤回、物料与人工发送、最小 Widget/Inbox、运行时可信、证据归档。Workflow 画布仍属 R3；完整客服渠道、真实业务写入与云端交付不在本版本范围。

## 工作包状态

| 工作包 | 状态 | 实现/证据 |
|---|---|---|
| WP1 最小沙盒发布 | 服务验收已完成（M-A-12/13 证据齐） | 用户接受明确的 R2 验收标准。`r2-config-release-v1` 检查冻结候选的入口引用、失败兜底与内容哈希；真实应用服务测试覆盖知识来源就绪、检查阻断、owner 批准、沙盒发布、入口解析指定不可变候选及发布后草稿隔离。它证明发布绑定与解析，不声称运行 R1 尚不支持的配置 Unit body。 |
| WP2 知识摄入与撤回 | 已实现（M-A-08/09 通过） | FAQ、HTTPS URL 与 UTF-8 文本文件支持状态/失败/重试/撤回；配置 HTTP 支持最多 5 MiB 的 TXT/MD/CSV/JSON 上传，SQLite schema v11 暂存原件，普通读取不返回 BLOB，成功摄入/撤回后清除。浏览器已走通 TXT 上传/检索/撤回零命中、公网 `https://example.org/` 内容摄入，以及私网 URL 拒绝与失败重试；console 0 errors。撤回删除旧索引、搜索归零并标记沙盒版本待重验，URL 抓取固定公网 DNS 并限制跳转/体积。仅为本机隔离服务证据，不代表公开部署。 |
| WP3 物料与人工发送 | 已实现（M-A-14/15 通过） | SQLite 原件 BLOB、校验和及版本；schema v10 将显示名、文件名、格式、授权和有效期固化到每个物料版本，并为 v9 数据提供事务迁移回填；支持上传/下载/备份恢复、撤回。全部支持格式及 MIME 上传/下载/恢复往返通过；四类授权声明按版本回读一致；有效期、撤回、旧版本、旧客服占用代次和版本更新并发时均拒绝失效发送。浏览器完成 README 上传、人工发送、访客下载往返。 |
| WP4 最小 Widget/Inbox | 已实现（M-A-10/11 通过） | loopback Widget/Inbox 页面和 API 支持访客文本、请求人工、客服接管/回复、物料发送及顺序记录；访客令牌仅存哈希，客服操作按可信 principal 限制。浏览器往返 console 0 errors；尚非公开部署，也没有 AI 自动接待回复。 |
| WP5 运行时可信 | 已实现（模拟/注入式 provider 范围） | 工具意图、provider 查询协调器/迟到回执和原子收敛已支持；确认等待支持重启恢复、授权重验、重启后取消及旧代 fencing。`run.status` 只返回受限摘要。真实 provider 联调不在本次沙盒验收内。 |
| WP6 证据归档与关闭 | 已归档，待用户快速验收 | M-A-01…18 父 Gate 行及适用的 M-A-19…21 证据细化均已登记；用户确认 R1 Gate 通过并授权跳过责任角色流程。用户完成本报告末的快速验收后即可关闭 R2。 |

## R2 配置发布验收标准 `r2-config-release-v1`

这是用户授权由实施方设计的 R2 替代验收标准，范围只针对当前 R1 可发布的声明式配置面：

1. `entry_unit_references_resolve`：人设入口引用均解析到冻结候选内的 Unit。
2. `entry_units_fail_closed`：入口 Unit 的 fallback 必须为 `clarify` 或 `human`。
3. `candidate_content_hash_matches`：冻结候选的 canonical 内容哈希与内容一致。

沙盒验收使用 `expert-a` 的课程咨询样例、授权 FAQ 来源、入口 `r2-sample-entry` 和版本 `r2-sample-v1`。端到端断言候选冻结、三项样例通过、知识来源摄入就绪、批准前发布阻断、owner 批准、发布后入口解析指向目标版本，以及后续草稿编辑不改变入口配置。因为 R1 Unit `body` 是空对象且没有配置到 `ScenarioPack` 的转换合同，这项标准**不把候选配置宣称为可执行 Workflow，也不声称 AgentScope 按候选配置回答访客**。

<a id="wp1wp4-服务端切片"></a>

## WP1–WP4 服务端切片

`ConfigurationApplication`、CLI 与 MCP 提供受角色限制的知识来源动作；知识撤回后 `release.entry.resolve` fail-closed。SQLite schema v8 新增来源、文档与索引表，v9 新增物料原件/版本、访客会话与消息账本，v10 将物料授权元数据提升为逐版本快照，v11 为知识文件增加暂存 BLOB。配置 HTTP 支持不超过 5 MiB 的 TXT/MD/CSV/JSON Base64 上传；原件只在内部摄入与失败重试时读取，普通来源 API 不返回 BLOB，摄入成功或撤回时清除。失败原件可显式重试。物料仅接受 PNG/JPEG/WebP/MP4/WebM/PDF/TXT/MD，限制 10 MiB 并校验部分文件签名；下载历史版本可审计，但新发送只允许当前版本。超限 Base64 在解码前拒绝。

Widget 与 Inbox 由同一个 loopback HTTP 服务提供。访客凭 256-bit 随机令牌访问自己会话；服务端仅保存 SHA-256 摘要。消息写入事务使用会话序号；客服 claim 递增占用代次，回复/附件发送按当前客服和代次拒绝旧请求。浏览器实际走查已验证“访客提问并请求人工 → Inbox 接管 → 客服回复 → 客服上传 README → 选择并发送物料 → 访客页面出现附件 → 点击下载并取得 README.md”，浏览器 console 0 errors。此测试 server 是本地 fixture，不证明公开/生产渠道。

证据：`tests/test_configuration_service.py`、`tests/test_customer_service.py`、`tests/test_config_http.py`、`tests/test_knowledge_fetch.py`、`tests/test_durable_store.py` 与 `tests/test_durable_transaction_crashes.py`。Python 3.13 锁定 wheel 环境执行完整后端 `unittest discover` **170/170** 通过；复用仓库本机离线 wheelhouse 后 `tests/test_s1.py` 自检全项通过；固定案例回放 **11/11**，当前输出 `/tmp/loomrise-r2-final-replay.json`。这些结果不覆盖公开部署或真实外部渠道验收。

<a id="wp5-副作用意图首片"></a>

## WP5 副作用意图首片

`loomrise/durable_store.py` 最初在 schema v6 新增 `tool_attempts`；当前 schema 为 v12（新增确认 checkpoint）。写工具进入执行适配器前，先把具体动作、参数摘要和绑定该动作的稳定幂等键写入 SQLite；键复用到不同动作/参数会拒绝。确定失败可显式记为 `failed`；成功结果通过原 `commit_write` 路径与业务幂等记录、事件和 outbox 一起提交，并将意图原子转为 `succeeded`。

超时、Run 收尾时仍有未决意图、或重启时旧 Run 被判中断，会将意图转为 `reconciling`。`DurableToolReconciliation` 枚举待对账操作并调用注入的只读 provider 查询器，`applied` 原子登记原 `result_id`、幂等账本、`tool.reconciled` 事件和 outbox；`not_applied` 才允许后续显式重试；`unknown` 或查询异常保持阻断。迟到回执同样经过该协调器和原子账本路径。可在旧 Run 已中断后收敛，但不会复活旧执行者。参数仅持久化哈希，避免把工具参数副本扩散到新表。provider 实现仍需按实际外部业务适配；当前测试使用模拟 provider，不等于生产 provider 联调。

证据：`tests/test_durable_side_effects.py` 覆盖 100 个独立连接竞争（恰有一个执行资格）、重复意图拒绝、参数重绑定拒绝、重启后进入 `reconciling` 并由注入 provider 查询后收敛、迟到回执重复提交、查询异常/未知状态阻断、确定未执行后的显式重试、对账事务崩溃回滚及事件链完整。provider 仍是模拟实现，真实外部系统联调未做。本轮全量后端 **174/174**。

<a id="wp5-确认等待恢复"></a>

### WP5 确认等待恢复（2026-10-30）

确认请求进入等待时，SQLite 同一事务保存 AgentScope `AgentState`、原始输入、版本、generation 并将请求置为 `waiting_confirm`。服务重启只把旧 Run 标记为 `failed/restart_interrupted`，保留等待 checkpoint，不自动继续。显式 `resume_confirmation` 在消费 checkpoint 前重新检查当前 AgentVersion、工具授权、硬规则和 pending tool call；SQLite 单事务删除 checkpoint 并创建 generation+1 的新 Run。新 Run 将原人工决定通过原 reply id 投递给上游，不重跑模型来重建已确认工具调用。并发唤醒最多一方可消费；过期版本/授权、无 checkpoint 和旧代事件均 fail-closed。取消等待会清 checkpoint。

证据：`tests/test_durable_recovery.py::TestPersistedRun.test_confirmation_wakes_after_restart_once_and_fences_old_callback` 跨独立 owner/服务实例覆盖进程退出、重启裁决、授权撤销拒绝且 checkpoint 保留、授权恢复后唤醒、单次模拟副作用、重复唤醒拒绝、旧代迟到回调拒绝及事件链完整；`tests/test_durable_store.py::TestSchema.test_confirmation_wake_rolls_back_checkpoint_consumption_with_run_creation` 注入新 Run 创建失败，验证 checkpoint 与新 Run 一起原子回滚。`TestPersistedRun.test_confirmation_wait_can_be_cancelled_after_restart` 覆盖重启后取消、取消 Run 审计与旧回调 fencing。

### 取消状态竞争（2026-10-30）

耐久请求状态现支持条件迁移。取消仅在请求仍为 `running` 或 `waiting_confirm` 时写入 `cancelling`；确认回调的收尾只允许 `waiting_confirm → running`，因此迟到回调不能覆盖已接受的取消。若进程在取消确认事件提交前退出，启动恢复把 `cancelling` 请求与旧 Run 一起收敛为 `failed`，不会再次列入自动恢复；这不伪称外部业务动作已撤销或取消已确认。

证据：`tests/test_durable_recovery.py::TestPersistedRun.test_cancel_during_confirmation_is_durable_and_not_overwritten_by_callback` 与 `TestRecovery.test_interrupted_cancellation_fails_closed_instead_of_reentering_recovery`。这两项证明本地状态竞争与重启 fail-closed，不覆盖 provider 侧取消/撤销，也不覆盖确认等待的原 Run suspend/wake。

重启后取消已持久化的确认等待会创建一个独立、无业务副作用的取消 Run，并在同一事务中清除 checkpoint、写入 `run.cancel_requested`/`run.cancel_confirmed`/`run.finished`、关闭请求。旧 Run 保持 `failed/restart_interrupted`，迟到回调不能继续产生副作用；`business_action_revoked=false` 明确表示没有声称撤销外部业务动作。

## 验证与限制

开工前基线：R1 证据报告记录 123/123。该历史结果不证明任一 R2 Gate 通过。

本轮临时数据库及浏览器 fixture 不属于项目交付工件。新增恢复测试覆盖两个独立服务 owner 下的重启恢复、授权重验、幂等唤醒、重启后取消、旧回调 fencing 与事件链；事务故障点验证 checkpoint 消费/新 Run 创建回滚。发布服务测试覆盖检查、批准、发布和草稿隔离。全量后端 `unittest discover` 为 175/175；`tests/test_s1.py` 全项通过；固定回放 11/11，原始输出 `/tmp/loomrise-r2-final-replay-20261030.json`。不包含真实 provider 联调、公开部署或 Unit body 执行。

## 用户快速验收

1. 查看 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) M-A-01…18 的证据与状态；R1 Gate 已按用户确认通过，责任角色复核/签核按授权跳过。
2. 查看 `r2-config-release-v1`：三个声明式样例、冻结候选、来源就绪、owner 批准、沙盒入口解析目标版本及草稿隔离。
3. 查看确认恢复：重启后授权有效才可唤醒；授权撤销时拒绝并保留 checkpoint；重复唤醒拒绝；重启后取消写入独立取消 Run，旧回调不产生副作用。
4. 确认边界：业务写入/provider 是模拟或注入测试；本版本不执行尚无转换合同的候选 Unit body，也不宣称真实 provider 联调或公网生产部署。

验证命令本轮实跑：`rtk .venv/bin/python -m unittest discover -s tests -q`（175/175）、`rtk .venv/bin/python tests/test_s1.py`、`rtk .venv/bin/python -m loomrise.cli replay --out /tmp/loomrise-r2-final-replay-20261030.json`（11/11）。
