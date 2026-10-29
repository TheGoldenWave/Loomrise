# R2 证据摘要 v0.5（实施中）

日期：2026-10-30。性质：R2 实施与验收交接记录，不替代 [ROADMAP](../ROADMAP.md) 的阶段 Gate 或 [Gate 矩阵](../RELEASE-GATE-MATRIX.md) 的父 Gate 状态。

> v0.5 更新：Inbox 浏览器上传物料、选择版本、发送到访客会话及访客下载完整走通；浏览器 console 无错误。最新后端全量回归 151/151，S1 自检通过，固定案例回放 11/11。Gate 状态不因此自动转为通过。

## 开工授权

用户于 2026-10-29 明确授权跳过 R1 前置及本次 R2 逐包的产研/策略运营责任角色复核与签核流程。此为**流程例外**：不代表责任角色签字，不得伪造签核；也不把技术证据不足的 Gate 改为通过。仍按本报告记录代码、可复现测试与运行验收状态。

R1 代码与证据整理提交：`36fd3a5`（`完成 R1 配置与耐久恢复补强`），已推送 `origin/main`。提交不包含 `private/`、本地 `runs/` 或凭据。

## 范围与边界

按 [RELEASE-PLAN §R2](../RELEASE-PLAN.md) 实施 WP1–WP6：最小沙盒发布、知识摄入/撤回、物料与人工发送、最小 Widget/Inbox、运行时可信、证据归档。Workflow 画布仍属 R3；完整客服渠道、真实业务写入与云端交付不在本版本范围。

## 工作包状态

| 工作包 | 状态 | 实现/证据 |
|---|---|---|
| WP1 最小沙盒发布 | 部分实现 | SQLite 批准/发布/入口绑定与不可变版本读取已接入；草稿不改变绑定。固定样例检查未接入，统一服务路径仍会阻断发布，不能称发布闭环完成。 |
| WP2 知识摄入与撤回 | 部分实现 | FAQ、HTTPS URL 与 UTF-8 文本文件有状态/失败/重试/撤回；撤回删除旧索引、搜索归零并标记沙盒版本待重验。URL 抓取只接受公网 HTTPS、固定 DNS 地址、限制重定向/体积；文件当前由受信服务读取本机路径，不是浏览器上传。 |
| WP3 物料与人工发送 | 部分实现 | SQLite 原件 BLOB、校验和及版本；schema v10 将显示名、文件名、格式、授权和有效期固化到每个物料版本，并为 v9 数据提供事务迁移回填；支持上传/下载/备份恢复、撤回，Inbox 附件发送前校验当前客服占用代次、物料版本与该版本有效期。浏览器完成 README 上传、人工发送、访客下载往返。支持格式/授权类型和并发失效矩阵仍未全覆盖。 |
| WP4 最小 Widget/Inbox | 部分实现 | loopback Widget/Inbox 页面和 API 支持访客文本、请求人工、客服接管/回复、物料发送及顺序记录；访客令牌仅存哈希，客服操作按可信 principal 限制。浏览器 console 0 errors；尚非公开部署，也没有 AI 自动接待回复。 |
| WP5 运行时可信 | 部分实现 | 工具意图首片见下文；仍缺可信外部结果查询/回执收敛、迟到结果对账出口、完整确认 suspend/wake、取消竞争确认与只读运行状态服务。 |
| WP6 证据归档与关闭 | 未开始 | 父 Gate 仍有不通过/未开始项；流程例外不替代签核或技术验收。 |

<a id="wp1wp4-服务端切片"></a>

## WP1–WP4 服务端切片

`ConfigurationApplication`、CLI 与 MCP 提供受角色限制的知识来源动作；知识撤回后 `release.entry.resolve` fail-closed。SQLite schema v8 新增来源、文档与索引表，v9 新增物料原件/版本、访客会话与消息账本，v10 将物料授权元数据提升为逐版本快照。物料仅接受 PNG/JPEG/WebP/MP4/WebM/PDF/TXT/MD，限制 10 MiB 并校验部分文件签名；下载历史版本可审计，但新发送只允许当前版本。超限 Base64 在解码前拒绝。

Widget 与 Inbox 由同一个 loopback HTTP 服务提供。访客凭 256-bit 随机令牌访问自己会话；服务端仅保存 SHA-256 摘要。消息写入事务使用会话序号；客服 claim 递增占用代次，回复/附件发送按当前客服和代次拒绝旧请求。浏览器实际走查已验证“访客提问并请求人工 → Inbox 接管 → 客服回复 → 客服上传 README → 选择并发送物料 → 访客页面出现附件 → 点击下载并取得 README.md”，浏览器 console 0 errors。此测试 server 是本地 fixture，不证明公开/生产渠道。

证据：`tests/test_configuration_service.py`、`tests/test_customer_service.py`、`tests/test_config_http.py`、`tests/test_knowledge_fetch.py`、`tests/test_durable_store.py` 与 `tests/test_durable_transaction_crashes.py`。配置、摄入、客服 HTTP、物料版本元数据、备份恢复及 schema 崩溃迁移定向测试通过；临时 Python 3.13 环境执行完整后端 `unittest discover` **151/151** 通过（`PYTHONTRACEMALLOC=5`、`ResourceWarning` 作为错误）；`tests/test_s1.py` 独立自检全部通过；固定案例回放 **11/11**，输出 `/tmp/loomrise-r2-replay-20261030.json`，事件输出 `/tmp/events/`。这些结果不覆盖公开部署或真实外部渠道验收。

<a id="wp5-副作用意图首片"></a>

## WP5 副作用意图首片

`loomrise/durable_store.py` 最初在 schema v6 新增 `tool_attempts`；当前 schema 为 v10。写工具进入执行适配器前，先把具体动作、参数摘要和绑定该动作的稳定幂等键写入 SQLite；键复用到不同动作/参数会拒绝。确定失败可显式记为 `failed`；成功结果通过原 `commit_write` 路径与业务幂等记录、事件和 outbox 一起提交，并将意图原子转为 `succeeded`。

超时、Run 收尾时仍有未决意图、或重启时旧 Run 被判中断，会将意图转为 `reconciling`。相同幂等键再次请求不会重放工具，而是要求先对账。参数仅持久化哈希，避免把工具参数副本扩散到新表。此实现没有在该记录上自动查询外部系统，也没有把对账结果收敛回业务账本；因此未知状态可以被区分并安全阻断，但 `M-A-07` 所要求的对账出口尚缺。

证据：`tests/test_durable_side_effects.py` 覆盖并发连接竞争（恰有一个执行资格）、重复意图拒绝、参数重绑定拒绝、进程重启后转 `reconciling`、新 Run 对同操作键仍不得再次执行。未知操作会安全停在 `reconciling`，但没有外部查询器/收敛服务，不能据此通过 `M-A-07`。本轮全量后端 **146/146**。本轮还复跑了 S1 独立自检与固定案例；其他媒体/真实模型运行验收不以历史结果替代。

## 验证与限制

开工前基线：R1 证据报告记录 123/123。该历史结果不证明任一 R2 Gate 通过。

本轮浏览器 fixture 与状态数据库写在系统临时目录，不属于项目交付工件，也不提交仓库。测试下载件写在 `.playwright-mcp/README.md`。本地页面只作为服务端集成证据的一部分，不替代公开渠道或生产验收。固定样例发布检查、浏览器知识文件摄入/外网验收、WP5 确认等待恢复、未知结果收敛、取消竞争和只读运行状态服务仍待实现或验证；R2 Gate 继续保持未关闭。
