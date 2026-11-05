# R3 能力证据登记 v1.6

日期：2026-11-04。状态：实施中；本文件是当前客服矩阵工件索引，不是 R3 Gate 通过报告。

本登记映射[客服交付方案 §1.1](../CUSTOMER-SERVICE-DELIVERY-PLAN.md#11-网页客服能力覆盖矩阵)与[Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md)的 `M-B-01…15`，并记录影响本矩阵判读的 R3 专项证据。本轮最终实测 Python 全量 739 项（`ResourceWarning` 作为错误）、前端 340/340、Canvas 构建、S1 自检与合同语义自检通过；AGI 专项 61 项、Contact／周期／算子专项 190 项、WebView 桥合同 12 项通过。这不表示客服能力矩阵完整验收。Gate 状态只在追溯矩阵维护。当前 SQLite schema 为 v23：v20 为 Inbox consumer durable ack 增量，v21/v22 为 AGI-07/08 诊断许可、不可变证据、诊断报告与 Worker 作业四表的同事务迁移，v23 为服务周期生命周期（generation/state/closure/predecessor lineage、`service_cycle_migrations` 审计表、active 周期 partial unique index、旧库条件式 ALTER 兼容）。SSE 本机 fixture 覆盖无游标冷启动基线与接管提醒优先级，不构成系统 Push 或实际送达证据。AGI-07/08、服务周期生命周期、Contact 完整批准路径与 WebView 桥生命周期的本机证据见下文专节；真实 harness Provider / host 联调无证据。真实渠道、平台、模型质量和送达能力不由本机 fixture 推定；R2/R3 Gate 均保持未通过，`M-B-01…14` 在跑、`M-B-15` 未开始，0/15 正式关闭。逐条 QA 对照见 [R3 收口与验收对照](R3-ACCEPTANCE-2026-11-04.md)。

## R3 编排画布

现有入口：`prototypes/console-next/orchestration/canvas.jsx`、`model.js`、`condition-summary.js`、`unit-auxiliary-editor.jsx`、`tests/orchestration-keyboard-browser-check.js`、`tests/orchestration-validation-browser-check.js`。边条件摘要仅用于扫描，不替代原条件或服务端判断；Unit 事件/等待编辑仅提供当前内容图的有效本层入口及自身出口，未知扩展字段保留，不能安全结构化的原文回退 JSON。节点拖动、自动布局和专注视图只改变 React 会话态，不写草稿、revision 或版本 diff。键盘浏览器 fixture 覆盖表单目标边界与扩展字段保留、节点拖动/重排不改配置、专注模式进出、下钻/返回与视图同步；1440/390px 无横向溢出，page errors 0。服务端校验浏览器 fixture 覆盖根/嵌套边定位、端口字段聚焦和未知路径修复，page errors 0。以上均为虚构配置本机 fixture，不替代搭建者/策略运营目标角色任务基线，不能关闭画布任务 Gate。

## WP3 / WP4 诊断数据面

`tests/test_config_http.py::test_execution_service_diagnostics_survive_reopen_and_http_pagination` 使用版本化虚构 fixture 经 `ExecutionService` 产生 recall/context 事件，持久化后关闭并重开 SQLite，再通过授权 HTTP `run.diagnostics` 验证租户/Agent/版本归属、分页游标、Unicode/标点 Unit ID 与输入/来源文本脱敏。诊断数据面已具备本机可运行端到端证据；选择与执行使用确定性脚本，不证明真实 Provider 质量、生产业务来源授权或多样本召回效果。

## AGI-07/08 只读诊断与可选 Worker 首链（本机证据）

实现入口：`loomrise/diagnostics.py`、`loomrise/governance_jobs.py`、`loomrise/adapters/harness.py`、`loomrise/configuration.py`、`config_cli.py`、`config_http.py`、`adapters/mcp.py`、`skills/loomrise-diagnose/SKILL.md`；测试为 `tests/test_diagnostics.py`、`test_diagnostics_interfaces.py`、`test_governance_jobs.py`、`test_harness_provider.py`、`test_governance_harness_integration.py`。`loomrise/durable_store.py` 的 `SCHEMA_VERSION = 22` 曾以同事务迁移新增诊断许可、不可变证据、诊断报告与 Worker 作业四表（失败整体回滚）；当前 `SCHEMA_VERSION = 23`，v23 为服务周期生命周期增量。

已验证（本机）：`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics tests.test_diagnostics_interfaces tests.test_governance_jobs tests.test_harness_provider tests.test_governance_harness_integration -q` → `Ran 61 tests ... OK`（收口后；收口前为 49 项）。覆盖许可字段与签发/到期/撤销、跨范围运行拒绝、最多 10 run / 每 run 100 事件 / 128 KiB 上限与白名单脱敏、超限显式 gaps、blind 与未知分类拒绝、六类 proposal 与精确 `evidence_id` 引用、8 状态机与 CAS generation/预算/重启裁决、每次外部调用及产物提交前重验许可、CLI/MCP/HTTP 同合同，以及诊断 Skill 与 MCP resource 同源。

未验证／缺口：真实 harness Provider 与真实 host Skill 激活／联调**无证据**——`test_harness_provider.py` 全部注入 `ScriptedChatModel`，唯一构造真实 `OpenAIChatModel` 的用例只断言类型、未发起网络调用；`test_governance_harness_integration.py` 自称 Offline、base_url 为 `example.invalid`、凭据为 `test-only-credential`。上述 5 个确凿缺口已于 2026-11-04 修复并补 12 项测试：Provider 按 `provider_kind / version / contract_hash` 由服务端校验并冻结 `evidence_class`（`offline_scripted` / `offline_structured`），治理作业经 `_GOVERNANCE_JOB_ACTIONS` 显式限定「仅本机 CLI，HTTP/MCP 同合同拒绝」，`external_agent` 诊断动作白名单显式化，撤权独立于 `_permission_tx` 的合同/来源/时效校验（旧 hash、来源失效、过期下始终可执行），cancel 两处 UPDATE 补 `rowcount` 竞争检查。独立规格审查见 [specs/2026-11-04-agi-0708-spec-review.md](../superpowers/specs/2026-11-04-agi-0708-spec-review.md)，代码质量审查见 [reviews/2026-11-04-agi-0708-code-quality-review.md](../superpowers/reviews/2026-11-04-agi-0708-code-quality-review.md)，覆盖 plan :45 九类场景。专项（8 模块）105 项、最终全量 739 项 OK。真实 harness Provider / 真实 host Skill 激活 / 质量对照仍未联调，不构成 AGI-07/08 或 R3 Gate 通过。

## WP1 / WP2 服务周期生命周期与条件算子（本机证据）

实现入口：`loomrise/service_cycles.py`（`ServiceCycleAuthority.close / adjudicate / migrate`，三者均先 `resolve(grant)` 做对象身份授权，`migrate` 需源+目标双 grant）；`loomrise/durable_store.py`（`SCHEMA_VERSION = 23`：`service_cycles` 增 `generation/state/closed_at/predecessor_cycle_id` 四列、移除表级 UNIQUE 改由 `migrate()` 末尾建 `WHERE state='active'` 的 partial unique index、新增 `service_cycle_migrations` 不可变 lineage 审计表、旧库条件式 `ALTER TABLE ADD COLUMN` 兼容、重写 `register_service_cycle` 使新来源只登记 active 周期并拒绝跨 authority 换源、`_validate_cycle` 增 state／旧 generation 拒绝，以及六个周期生命周期存储方法）；`loomrise/config_validation.py` 的 `CHANGED_TO_BLOCKED_REASON`；`loomrise/graph_validation.py` 与 `graph_runtime.py` 的冻结期/运行时同源明确拒绝诊断。

本机验证：新建 `tests/test_service_cycle_lifecycle.py` 10 项、`tests/test_changed_to.py` 6 项，既有 `tests/test_service_cycles.py` 18 项（含 v16 迁移回滚断言，仅增 1 行 `DROP TABLE service_cycle_migrations` 以保持整体回滚语义）。任务指定专项 `Ran 139 tests ... OK`、扩展专项 `Ran 145 tests ... OK`、与 Contact 合并专项 `Ran 190 tests ... OK`；最终全量 739 项 OK、合同语义自检全部通过。覆盖 SQLite 重开、Online Backup 恢复、两连接并发裁定（恰好一个成功）、cancelled 事项不复活、旧 generation 的 `reserve`/`begin_run` 拒绝、无授权/伪造 grant/无 lineage/换 authority 迁移被拒、来源换源拒绝、关闭终态禁静默复用、裁定 lineage 与冻结版本钉死、迁移 root lineage。`changed_to` 6 项反例锁定：调用方自报前值被拒、缺来源或表达式声明来源也不启用、否定与短路不能绕过、既有确定性算子与两层条件深度上限不变。

**明确未交付**：生产业务源签发/验签未接入，周期来源仍是本机虚构 `authority_id`；`changed_to` 判定不可行——`GraphRuntime` 的 state 完全来自调用方 `routing_state`，唯一服务端持久投影 `state_window_counts` 只有 attempts/runs 计数，无按字段可信前值快照，需在 `service.py` 注入剥离调用方的可信命名空间，当前代码库无该存储，故保留明确拒绝而非硬做；遗留 v22 库（旧代码创建、仍带表级 UNIQUE）增量补列后可重开，但残留 UNIQUE 会阻止同 scope 第二个周期行，裁定会失败关闭并给出明确诊断（不静默复用），彻底消除需一次 FK-safe 表重建，不在本次增量范围。以上不改变任何 M-B 行状态，也不关闭 R3 Gate。

## M-B-01

现有入口：`tests/test_widget_configuration.py`、`tests/test_customer_service.py`、`tests/customer_reception_browser_check.js`、`prototypes/console-next/tests/reception-settings.test.js`、`prototypes/console-next/tests/orchestration-reception-settings-browser-check.js`、`prototypes/console-next/tests/widget-configuration-browser-check.js`、`prototypes/console-next/tests/widget-preview.test.js`、`loomrise/widget_configuration.py`、`loomrise/customer_widget.html`。性质：AI 接待版本中的 FAQ 问题逐条绑定精确 `source_id/content_hash`；只允许引用该版本已选来源，最多 8 项、每项 160 个 Unicode code point、拒绝 NUL/空值及 Unicode case-fold 后重复。工作台支持新增、编辑、移除并共用草稿 revision；只读版本不写入。访客公开投影只返回问题文本，Contact Page 不展示 FAQ 建议；点击后走普通 `widget.send` 和正常检索，不将来源或预设答案交给客户端。21 个 Python 专项、308 个前端测试、Canvas 构建，以及确定性浏览器 fixture 的 Widget→接待→Inbox 往返、FAQ 工作台新增/去重/长 Unicode/保存刷新均已通过；浏览器 page errors 0，1440/390px 无溢出。未覆盖：公网/云独立网站、真实模型多样本质量、完整客服能力与目标角色基线；本机 fixture 不关闭 M-B-01。

## M-B-02

现有入口：`tests/test_widget_configuration.py`、`tests/test_customer_reception.py`、`tests/test_customer_service.py`、`prototypes/console-next/tests/widget-live-reception-browser-check.js`、`prototypes/console-next/tests/widget-configuration-browser-check.js`、`prototypes/console-next/tests/widget-offline-reception-browser-check.js`。性质：服务层覆盖 always/offline 开闭、UTC 到 IANA 本地时区、`[start,end)` 边界、DST 春季跳时/秋季重复小时、代表性隔夜/周日跨周一以及固定版本会话同线程消息；`test_offline_reception_obeys_the_full_weekly_schedule` 覆盖周一至周日的 `offline` 策略与 Provider 调用。`hours: []` 浏览器 fixture 验证离线入口留言同线程续接；`ai_reception.mode=offline` 浏览器 fixture 验证开放时段不生成 AI 答复、刷新不重复且 Inbox 同线程可见。访客字段浏览器 fixture 现覆盖必填 text、选填 email/tel 的 input 类型与 `required` 属性，必填缺失不建会话、选填为空可继续，并验证输入值进入原会话 Inbox；服务端测试覆盖空白必填、500/501 字符边界、邮箱格式、任意 tel 文本及选填空/省略。最近专项：`tests.test_widget_configuration` 11 项；客服接待、Widget 配置及客服服务合计 58 项。浏览器复跑 page errors 0，1440/390px 无横向溢出。未覆盖：真实渠道入站、完整公网/生产身份边界和目标角色验收；上述 loopback/确定性 fixture 不关闭 M-B-02。

## M-B-03

现有入口：`tests/test_contact_page.py`、`tests/test_widget_configuration.py`、`prototypes/console-next/tests/contact-editor-browser-check.js`、`loomrise/customer_widget.html`、`loomrise/contact_pages.py`。性质：HTTPS/空值/不安全 URL 与无副作用回归；Contact Page 21 类 fixture 对每个已保存 `href` 验证 URL、`target="_blank"` 和 `rel="noopener noreferrer"`，并验证空 `social/link/booking` 块不显示外链。`tests.test_contact_page` + `tests.test_contact_generation` 本轮 36/36，前端 `npm test` 308/308、Canvas 构建通过；隔离 loopback 浏览器检查 page errors 0、1440/390px 无横向溢出，3 条 console errors 已分别对应预期 `contact.get/not_found/404` 与 `contact.save/revision_conflict/409`。未覆盖：真实外站预约、打开外链后客服线程续接及完整支持矩阵；外跳不代表预约成功，本机 fixture 不关闭 M-B-03。

## M-B-04

现有入口：`tests/test_widget_install.py`、`tests/widget_install_browser_check.js`、`tests/widget_install_site.html`、`prototypes/console-next/tests/widget-installer-ui-browser-check.js`、`prototypes/console-next/tests/run-browser-check.js`。性质：单独 loopback 网站 origin 加载 loader；验证访客留言进入 Inbox、人工接管/回复回到 Widget、allowlist/CSP 来源拒绝；新增两个独立浏览器上下文各自建立访客会话、消息互不可见、交叉 token 读写均以 404 拒绝。工作台通过只读 `release.entry.list` 选择已发布且状态有效的 `entry_id` 后生成本机脚本，不复用版本 ID。浏览器 fixture 在 1440/390px 验证代码、焦点与无横向溢出，page errors 0；CSP 拒绝会产生一条预期 console error。未覆盖：公网/云环境、坐席身份与授权隔离、真实访客规模与外部送达；本机 loopback 证据不构成生产安装通过。

## M-B-05

现有入口：`tests/test_contact_page.py`、`tests/test_contact_generation.py`、`tests/test_contact_approval.py`、`prototypes/console-next/tests/contact-editor-browser-check.js`、`prototypes/console-next/tests/contact-generation-browser-check.js`。性质：21 类 Schema/候选边界、本机草稿/预览与预置批准快照渲染；一次虚构真实模型三块生成样本已保存并重开 SQLite 核验。服务端批准能力经复核**真实存在且分两层**：策略层 `release.approve/publish/entry.resolve`（治理预检、owner-only）与执行层 `freeze_candidate`（冻结候选＝提交审批入口）→ `approve_release_candidate`（批准绑定冻结哈希/入口/版本）→ `publish_sandbox_candidate`（发布重验批准、版本不可漂移、原子绑定入口）→ `enable_contact_page`（`expected_version_id` 同事务 JOIN 重验批准与版本）。`contact-matrix-fixture-v1` 只是存储级预置批准快照（`tests/r1_configuration_http_fixture.py` 注释自证），不构成完整生命周期证据。

本轮新增 `tests/test_contact_approval.py` 9 项端到端断言（未改任何生产代码、未放宽校验）：1 条正向路径走完 草稿保存→生成待审候选（不落盘）→显式采用→冻结→批准绑定→发布重验→入口解析→启用固定版本→公开页只读且与后续草稿隔离→分享→停用 404→重新启用；8 类反例覆盖 revision 冲突、viewer/editor/external 不可批准或冻结或启用、版本漂移拒绝、坏 Schema/未知块、缺少审批拒绝公开、知识撤回拒绝公开与入口解析、跨专家/跨租户拒绝，以及治理层 `release.approve/publish` owner-only 且 fail-closed。专项 `Ran 45 tests ... OK`，最终全量 739 项 OK。21 类矩阵不等同于 21 类生成质量。未覆盖：21 类真实模型多样本质量、真人目标角色基线、治理层 `release.approve/publish` 通过完整生产预检（依赖外部固定样例执行服务，本机恒 `release_blocked` fail-closed，测试如实验证而非伪造通过）、浏览器端独立「提交批准」按钮。M-B-05 仍为「在跑」。

## M-B-06

现有入口：`loomrise/customer_reception.py`、`tests/test_customer_reception.py`、`prototypes/console-next/tests/orchestration-reception-settings-browser-check.js`、`prototypes/console-next/tests/widget-live-reception-browser-check.js`、`prototypes/console-next/tests/widget-configuration-browser-check.js`、`prototypes/console-next/tests/widget-offline-reception-browser-check.js`。性质：接待服务、本机 fixture 设置及关闭 AI 仍入 Inbox、always/offline 开闭、UTC 到 IANA 时区的 `[start,end)`、DST、代表性隔夜周跨边界、固定版本同线程消息和欢迎入口优先级回归；另有七天 `offline` 服务排班矩阵，确认仅关门时触发 Provider。`hours: []` Widget 离线入口留言刷新、Inbox 和坐席回复续接，以及开放时段下 offline-only AI 不作答且留言落入 Inbox 的浏览器断言均通过。访客表单浏览器回归覆盖 text/email/tel 声明、required 策略和多字段 Inbox 投影。未覆盖：真实渠道入站、生产身份边界与完整行为/角色验收；本地 fixture 不关闭 M-B-06。

## M-B-07

现有入口：`tests/test_model_connection.py`、`tests/test_model_provider.py`、`tests/r3_model_provider_live_check.py`。性质：连接合同/Provider 适配测试及有限真实模型样本。未覆盖：逐预设的可达、认证、流式、工具调用兼容矩阵；单个模型样本不构成通过。

## M-B-08

现有入口：`loomrise/knowledge_documents.py`、`tests/test_knowledge_documents.py`、`tests/test_configuration_service.py`、`tests/test_knowledge_fetch.py`、`tests/test_material_retrieval.py`、`tests/test_config_http.py`、`loomrise/material_processing.py`。性质：有界 TXT/MD/CSV/JSON/HTML/HTM/DOCX/XLSX 解析与超限回归；各格式用原创最小 fixture 验证解析或明确 `format_unavailable`，不是来自真实 Office/浏览器的兼容性矩阵。知识文件 PDF 仅提取原生文本，原件上限 5 MiB、只读前 20 页、可选 `pdftotext`、15 秒超时和 8 MiB 输出上限。缺少 `pdftotext`、无文本层/扫描 PDF 明确返回 `format_unavailable`；该知识摄入路径不做 OCR。旧 `.doc` 可选调用 macOS 系统 `textutil`，沿用 5 MiB 输入上限、15 秒超时和 8 MiB stdout 上限；本机原创 RTF 经真实 `textutil` 转成 DOC 后，摄入为 `ready` 并可检索。缺工具的平台仍返回 `format_unavailable`；该单一生成样本不证明外部 Office 变体或跨平台兼容。工具来源及限制见 [VERSION-PINS §14](../../VERSION-PINS.md#14-r3-可选旧-doc-文本提取工具2026-11-03)。

知识服务集成回归补充 URL 成功摄入后的 `ready`、内容哈希和索引检索，以及文件首次读取失败、修复后重试成功、尝试次数递增和内容哈希；URL 成功样本使用替身抓取函数，不是公网来源实测。`tests.test_knowledge_documents` 20/20 通过，真实 DOC 子例未跳过，HTML/HTM 两种后缀均断言可见文本索引和脚本内容剔除。知识服务、材料处理和知识文档合计 68 项以 `ResourceWarning` 为错误复跑通过。物料图片 OCR 与知识文档摄入是不同路径：前者的语言枚举和正文输出均使用 `_run_bounded_stdout`，各限 64,000 字节，超时分别为 5/15 秒，超限终止进程；OCR 仍缺真实工具/语言包质量证据。

未覆盖：真实来源文件的 Office/HTML 变体与跨平台 DOC 兼容、来源失败/重试/撤回与引用的完整验收。M-B-08 与 R3 Gate 仍未通过。

## M-B-09

现有入口：`tests/test_customer_reception.py`、`tests/customer_reception_browser_check.js`、`tests/r3_model_provider_live_check.py`。性质：确定性与有限真实模型 fixture。未覆盖：多样本引用正确性、未知/冲突/禁答质量及零副作用完整案例集。

## M-B-10

现有入口：`tests/test_inbox_read_state.py`、`tests/test_inbox_sse_client.py`、`tests/test_customer_reception.py`、`tests/widget_install_browser_check.js`、`prototypes/console-next/tests/inbox-notifications-browser-check.js`。性质：本机 SQLite、HTTP 与桌面/窄屏浏览器 fixture；Inbox 使用有序脱敏事件日志、可续接 SSE 与逐 consumer durable application ack；客户端刷新 Inbox 投影后确认消费，处理失败不推进 ack，重连按已确认 cursor 重放。SSE 无游标冷启动会建立当前消息基线，同事务接管提醒优先于普通访客消息；独立 Widget 浏览器上下文的访客会话隔离及交叉 token 读写拒绝已通过。Notification 仍为权限/显示替身，不证明系统送达。未覆盖：完整多入口队列/附件/移动网页矩阵、坐席身份认证隔离与公网部署。

本轮筛选入口：`prototypes/console-next/tests/inbox-filters-browser-check.js`。全部／待接管／由我接管／未读四种筛选仅改变当前列表投影；不接管、不确认已读、不丢失现有回复草稿。确定性浏览器 fixture 已通过，完整 M-B-10 Gate 仍未通过。

## M-B-11

现有入口：`tests/test_customer_reception.py`、`tests/test_inbox_read_state.py`、`tests/test_inbox_assistance.py`、`tests/test_model_provider.py`、`tests/customer_reception_browser_check.js`、`prototypes/console-next/tests/reception-settings.test.js`、`prototypes/console-next/tests/inbox-assistance-browser-check.js`。冻结版本支持有界显式转人工短语：最多 20 条、每条 trim 后 1–100 Unicode 字符、拒绝 NUL 和 case-fold 重复；入站事务内字面匹配，不调用模型，不改变已有人工作用域。配置只读/比较视图和父 JSON 表单缓存隔离有专项回归。

Inbox 保留本地消息计数/最近访客摘录和可手动插入的通用确认语，另提供显式生成的模型摘要/回复候选。`inbox.assistance.generate/check` 限本人已接管、当前代次与精确消息序号；全部消息、冻结版本和当前知识授权进入快照，生成后与采用前重验。候选单独以文本展示，采用只填入编辑框，check 等待期间有人工编辑则保留；发送始终需显式 `inbox.reply`。服务/Provider 专项 32 项，以及独立 SQLite trace/`total_changes` 零 DML、快照失效与前端并发检查通过；浏览器 fixture 覆盖无接管拒绝、生成保留草稿/无发送、HTML 转义、明确采用/发送、旧候选/跨线程隔离及 Provider 故障脱敏。1440/390px 无横向溢出、page errors 0。

真实模型复现：`rtk proxy .venv/bin/python -m tests.r3_model_provider_live_check --run-live --inbox-assistance`。本轮仅使用一个原创虚构样本，gpt-6-sol 调用 1 次、零重试，输入/输出 4770/180 tokens、3128ms；19 元候选有来源引用，生成不发消息/不已读，显式人工回复与 SQLite 重开核验通过。这不是多样本模型摘要/答复质量证据。策略化模型转人工建议、授权恢复/超时完整矩阵和完整客服覆盖仍缺；M-B-11 与 R3 Gate 保持未通过。

## M-B-12

现有入口：`loomrise/channel_sandbox.py`、`tests/test_channel_sandbox.py`、`tests/test_channel_webhook.py`。性质：不发起网络请求的授权沙盒。未覆盖：真实 Bot 授权收发、线程映射、限流、失败、回调和撤销。

## M-B-13

现有入口：`loomrise/channel_sandbox.py`、`tests/test_channel_sandbox.py`、`tests/test_channel_webhook.py`。性质：不发起网络请求的授权沙盒。未覆盖：授权测试邮箱的 alias/custom MX 收发、重复、附件、拒收和撤销。

## M-B-14

现有入口：`loomrise/customer_statistics.py`、`tests/test_customer_statistics_window.py`、`prototypes/console-next/tests/customer-statistics-browser-check.js`、`prototypes/console-next/tests/inbox-notifications-browser-check.js`。性质：持久接待记录统计投影和本机浏览器 fixture；当前覆盖请求/运行/入口/版本/结果、可用接管事实、服务端事件时延与已记录模型用量。访客时延和送达未知；历史接管事实可能缺失；当前仅支持文字渠道，语音显示为不支持。Notification 权限/显示不是系统送达。未覆盖：Web Push/Telegram 送达回执及隐藏页生命周期。

## M-B-15

现有入口：`prototypes/console-next/tests/widget-configuration-browser-check.js`、`prototypes/console-next/tests/customer-statistics-browser-check.js` 的窄屏视口检查、`prototypes/console-next/tests/customer-widget-bridge-contract.test.js`，以及新增的 `prototypes/console-next/tests/customer-widget-bridge-lifecycle.test.js`。性质：响应式浏览器视口与 Node VM 静态合同 fixture。桥合同验证 `loomrise.webview.bridge.v1` 的 loopback origin / parent source allowlist、访客字段白名单、既有会话交接与持久化、dismiss 消息及无宿主安全 no-op；生命周期补片新增 8 项断言，覆盖 READY 握手与重复握手、迟到/重复 `session.handoff` 幂等、dismiss 双向消息与关闭按钮在桥启用/未启用时的行为、父窗口消失与 `source`/`origin` 边界、未知 `kind` no-op、权威字段（`tenant/actor/role`）拒绝、既有会话交接不丢持久化，以及 `postMessage` 抛错时会话与缓存仍安全。实现侧对应收紧 `emit` 的 try/catch 与 `session.handoff` 幂等键。`npm test` 由 332/332 增至 **340/340**，Canvas 构建通过。未覆盖：iOS、Android、React Native、Flutter WebView 实际运行、关闭按钮与宿主生命周期集成及目标容器能力；**实现/合同测试已开始，平台运行 Gate 仍未开始且未通过**——本机静态合同不构成 M-B-15 状态变更依据。
