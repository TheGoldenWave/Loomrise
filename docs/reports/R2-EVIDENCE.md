# R2 证据摘要 v0.9（实施中）

日期：2026-10-30。性质：R2 实施与验收交接记录，不替代 [ROADMAP](../ROADMAP.md) 的阶段 Gate 或 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) 的父 Gate 状态。

> v0.6 更新：新增受租户/专家范围限制的只读运行状态摘要 API，不含事件载荷或工具参数；测试覆盖授权、越权、未知运行与只读性。最新后端全量回归 152/152，S1 自检通过，固定案例回放 11/11。Gate 状态不因此自动转为通过。

> v0.7 更新：副作用账本新增外部查询结果的原子收敛写入；已执行结果保存原 `result_id`、幂等记录、审计事件与 outbox，确定未执行才开放显式重试，未知仍阻断。对账事务崩溃、重启后收敛和 100 个独立连接并发竞争均有测试。后端全量 156/156、S1 自检和固定回放 11/11 通过；仍未接入 provider 查询器/迟到回执服务，M-A-07 不通过。

> v0.8 更新：配置 HTTP 支持 Base64 上传不超过 5 MiB 的 TXT/MD/CSV/JSON 知识文件；SQLite schema 升至 v11。上传原件仅供内部摄入/失败重试使用，普通来源读取不返回 BLOB；成功摄入或撤回后清除暂存原件。HTTP 摄入、失败重试保留、撤回清理、超限拒绝和 v10→v11 迁移测试通过；后端全量 162/162。尚未完成浏览器文件上传与公网 URL 内容验收，WP2/M-A-08/09 仍未通过。

> v0.9 更新：SQLite 请求状态新增条件迁移；人工确认期间取消会持久化为 `cancelling`，确认回调退出不得将其覆盖回 `running`。进程在取消收尾前中断时，恢复将请求 fail-closed 收敛为 `failed`，不重新进入可恢复队列，也不声称取消已确认。新增确认中取消和重启中断取消测试；后端全量回归 164/164，S1 自检通过，固定案例 11/11。此证据只覆盖取消状态竞争，不等于持久确认 suspend/wake 或外部副作用撤销。

> v1.0 更新：WP3 补齐物料全部支持格式的上传/下载/备份恢复及 MIME 元数据断言，覆盖四类授权声明的逐版本快照，并以两个独立 SQLite 连接验证版本在发送预检后更新时旧附件被事务拒绝。结合既有到期、撤回、旧版本和旧客服占用代次拒发测试，登记 M-A-14/15 通过。后端全量回归 166/166；S1 自检通过、固定案例 11/11。R2 父 Gate 仍未通过。

> v1.1 更新（2026-10-30）：知识工作页通过隔离 loopback 服务与真实浏览器验收：TXT 上传并摄入、检索命中、撤回后检索零命中；`https://example.org/` 公网 HTTPS 内容抓取成功；`https://127.0.0.1/` 被 SSRF 防护拒绝，失败状态可见、显式重试后尝试次数为 2 且仍标失败。浏览器 console 0 errors。结合既有 FAQ/URL/文件状态机、失败重试、撤回清理索引、已发布版本标 stale 并 fail-closed 的服务测试，M-A-08/09 登记通过。知识工作页路由与专家越权拒绝新增 HTTP 回归。R2 父 Gate 仍未通过。

> v1.2 更新（2026-10-30）：新增 `DurableToolReconciliation` 协调器，注入只读 provider 查询实现；待对账清单只暴露操作键/动作/Run，不暴露工具参数。查询结果 `applied/not_applied/unknown` 及迟到回执均复用 SQLite 原子收敛；查询异常视为 `unknown`，不授权重放。新增 provider 查询、重复迟到回执和查询失败阻断测试。结合百连接幂等竞争与旧代/取消测试，M-A-05/07、M-A-21 证据细化通过；WP4 顺序消息、访客 token 哈希与越权拒绝测试/浏览器证据支持 M-A-10/11 通过。后端全量回归更新为 170/170。R2 父 Gate 仍未通过。

## 开工授权

用户于 2026-10-29 明确授权跳过 R1 前置及本次 R2 逐包的产研/策略运营责任角色复核与签核流程。此为**流程例外**：不代表责任角色签字，不得伪造签核；也不把技术证据不足的 Gate 改为通过。仍按本报告记录代码、可复现测试与运行验收状态。

R1 代码与证据整理提交：`36fd3a5`（`完成 R1 配置与耐久恢复补强`），已推送 `origin/main`。提交不包含 `private/`、本地 `runs/` 或凭据。

## 范围与边界

按 [RELEASE-PLAN §R2](../RELEASE-PLAN.md) 实施 WP1–WP6：最小沙盒发布、知识摄入/撤回、物料与人工发送、最小 Widget/Inbox、运行时可信、证据归档。Workflow 画布仍属 R3；完整客服渠道、真实业务写入与云端交付不在本版本范围。

## 工作包状态

| 工作包 | 状态 | 实现/证据 |
|---|---|---|
| WP1 最小沙盒发布 | 部分实现 | SQLite 批准/发布/入口绑定与不可变版本读取已接入；草稿不改变绑定。固定样例检查未接入，统一服务路径仍会阻断发布，不能称发布闭环完成。 |
| WP2 知识摄入与撤回 | 已实现（M-A-08/09 通过） | FAQ、HTTPS URL 与 UTF-8 文本文件支持状态/失败/重试/撤回；配置 HTTP 支持最多 5 MiB 的 TXT/MD/CSV/JSON 上传，SQLite schema v11 暂存原件，普通读取不返回 BLOB，成功摄入/撤回后清除。浏览器已走通 TXT 上传/检索/撤回零命中、公网 `https://example.org/` 内容摄入，以及私网 URL 拒绝与失败重试；console 0 errors。撤回删除旧索引、搜索归零并标记沙盒版本待重验，URL 抓取固定公网 DNS 并限制跳转/体积。仅为本机隔离服务证据，不代表公开部署。 |
| WP3 物料与人工发送 | 已实现（M-A-14/15 通过） | SQLite 原件 BLOB、校验和及版本；schema v10 将显示名、文件名、格式、授权和有效期固化到每个物料版本，并为 v9 数据提供事务迁移回填；支持上传/下载/备份恢复、撤回。全部支持格式及 MIME 上传/下载/恢复往返通过；四类授权声明按版本回读一致；有效期、撤回、旧版本、旧客服占用代次和版本更新并发时均拒绝失效发送。浏览器完成 README 上传、人工发送、访客下载往返。 |
| WP4 最小 Widget/Inbox | 已实现（M-A-10/11 通过） | loopback Widget/Inbox 页面和 API 支持访客文本、请求人工、客服接管/回复、物料发送及顺序记录；访客令牌仅存哈希，客服操作按可信 principal 限制。浏览器往返 console 0 errors；尚非公开部署，也没有 AI 自动接待回复。 |
| WP5 运行时可信 | 部分实现 | 工具意图、provider 查询协调器/迟到回执和原子收敛已支持，`run.status` 是受限只读摘要，不暴露事件或工具参数；M-A-05/07 与 M-A-21 证据细化通过。取消状态已持久化并覆盖确认中取消与重启中断取消；仍缺持久确认 suspend/wake 和授权上下文恢复。 |
| WP6 证据归档与关闭 | 未开始 | 父 Gate 仍有不通过/未开始项；流程例外不替代签核或技术验收。 |

<a id="wp1wp4-服务端切片"></a>

## WP1–WP4 服务端切片

`ConfigurationApplication`、CLI 与 MCP 提供受角色限制的知识来源动作；知识撤回后 `release.entry.resolve` fail-closed。SQLite schema v8 新增来源、文档与索引表，v9 新增物料原件/版本、访客会话与消息账本，v10 将物料授权元数据提升为逐版本快照，v11 为知识文件增加暂存 BLOB。配置 HTTP 支持不超过 5 MiB 的 TXT/MD/CSV/JSON Base64 上传；原件只在内部摄入与失败重试时读取，普通来源 API 不返回 BLOB，摄入成功或撤回时清除。失败原件可显式重试。物料仅接受 PNG/JPEG/WebP/MP4/WebM/PDF/TXT/MD，限制 10 MiB 并校验部分文件签名；下载历史版本可审计，但新发送只允许当前版本。超限 Base64 在解码前拒绝。

Widget 与 Inbox 由同一个 loopback HTTP 服务提供。访客凭 256-bit 随机令牌访问自己会话；服务端仅保存 SHA-256 摘要。消息写入事务使用会话序号；客服 claim 递增占用代次，回复/附件发送按当前客服和代次拒绝旧请求。浏览器实际走查已验证“访客提问并请求人工 → Inbox 接管 → 客服回复 → 客服上传 README → 选择并发送物料 → 访客页面出现附件 → 点击下载并取得 README.md”，浏览器 console 0 errors。此测试 server 是本地 fixture，不证明公开/生产渠道。

证据：`tests/test_configuration_service.py`、`tests/test_customer_service.py`、`tests/test_config_http.py`、`tests/test_knowledge_fetch.py`、`tests/test_durable_store.py` 与 `tests/test_durable_transaction_crashes.py`。Python 3.13 锁定 wheel 环境执行完整后端 `unittest discover` **170/170** 通过；复用仓库本机离线 wheelhouse 后 `tests/test_s1.py` 自检全项通过；固定案例回放 **11/11**，当前输出 `/tmp/loomrise-r2-final-replay.json`。这些结果不覆盖公开部署或真实外部渠道验收。

<a id="wp5-副作用意图首片"></a>

## WP5 副作用意图首片

`loomrise/durable_store.py` 最初在 schema v6 新增 `tool_attempts`；当前 schema 为 v11。写工具进入执行适配器前，先把具体动作、参数摘要和绑定该动作的稳定幂等键写入 SQLite；键复用到不同动作/参数会拒绝。确定失败可显式记为 `failed`；成功结果通过原 `commit_write` 路径与业务幂等记录、事件和 outbox 一起提交，并将意图原子转为 `succeeded`。

超时、Run 收尾时仍有未决意图、或重启时旧 Run 被判中断，会将意图转为 `reconciling`。`DurableToolReconciliation` 枚举待对账操作并调用注入的只读 provider 查询器，`applied` 原子登记原 `result_id`、幂等账本、`tool.reconciled` 事件和 outbox；`not_applied` 才允许后续显式重试；`unknown` 或查询异常保持阻断。迟到回执同样经过该协调器和原子账本路径。可在旧 Run 已中断后收敛，但不会复活旧执行者。参数仅持久化哈希，避免把工具参数副本扩散到新表。provider 实现仍需按实际外部业务适配；当前测试使用模拟 provider，不等于生产 provider 联调。

证据：`tests/test_durable_side_effects.py` 覆盖 100 个独立连接竞争（恰有一个执行资格）、重复意图拒绝、参数重绑定拒绝、重启后进入 `reconciling` 并由注入 provider 查询后收敛、迟到回执重复提交、查询异常/未知状态阻断、确定未执行后的显式重试、对账事务崩溃回滚及事件链完整。provider 仍是模拟实现，真实外部系统联调未做。当前全量后端 **170/170**。

### 取消状态竞争（2026-10-30）

耐久请求状态现支持条件迁移。取消仅在请求仍为 `running` 或 `waiting_confirm` 时写入 `cancelling`；确认回调的收尾只允许 `waiting_confirm → running`，因此迟到回调不能覆盖已接受的取消。若进程在取消确认事件提交前退出，启动恢复把 `cancelling` 请求与旧 Run 一起收敛为 `failed`，不会再次列入自动恢复；这不伪称外部业务动作已撤销或取消已确认。

证据：`tests/test_durable_recovery.py::TestPersistedRun.test_cancel_during_confirmation_is_durable_and_not_overwritten_by_callback` 与 `TestRecovery.test_interrupted_cancellation_fails_closed_instead_of_reentering_recovery`。这两项证明本地状态竞争与重启 fail-closed，不覆盖 provider 侧取消/撤销，也不覆盖确认等待的原 Run suspend/wake。

## 验证与限制

开工前基线：R1 证据报告记录 123/123。该历史结果不证明任一 R2 Gate 通过。

本轮浏览器 fixture 与状态数据库写在系统临时目录，不属于项目交付工件，也不提交仓库。测试下载件写在 `.playwright-mcp/README.md`。本地页面只作为服务端集成证据的一部分，不替代公开渠道或生产验收。知识资料浏览器验收的本机临时数据库位于 `/tmp/loomrise-r2-pw/configuration.db`，临时 principal 仅授权 `fixture-agent`；Playwright CLI 会话 `loomrise-r2-knowledge` 验证上传、抓取、重试、撤回和检索。固定样例发布检查、WP5 确认等待 suspend/wake 与授权上下文恢复仍待实现或验证；provider 查询使用模拟实现，真实外部业务联调未做。取消状态竞争已有本地故障/恢复测试，但不等于所有 R2 运行 Gate。`run.status` 仅为只读摘要切片，不能替代上述耐久性证据。R2 Gate 继续保持未关闭。
