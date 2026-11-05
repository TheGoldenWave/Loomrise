# R3 开发实施与接力计划 v0.55

日期：2026-11-03。状态：实施中，尚未通过 R3 退出 Gate。

**目标**：按 [版本计划 R3](../../RELEASE-PLAN.md#r3--能扩s2-b) 推进全部六个工作包，重点参考仓库的 ElevenLabs 配置调研实现画布配置。

**本轮流程决定**：用户明确要求跳过 R2 用户快速验收直接推进 R3。允许继续开发，不代签责任角色，不视为 R2 技术 Gate 或画布任务测试基线已通过。未完成的技术证据仍以 [R2 报告](../../reports/R2-EVIDENCE.md) 与 Gate 矩阵为准；画布效果在缺少目标角色任务测试时只能记为未验证。

**架构**：复用 `console-next` 的服务端版本工作面，以 `ConfigurationApplication` 返回的草稿为唯一配置来源。React Flow 是局部画布组件，图、清单、规则与检视器共用数据和选中态；所有配置修改仍通过原草稿保存、revision、校验、冻结路径。不会把旧原型 `routeGraph` 静默转换成领域合同。React Flow 坐标只是会话视图态，不进入配置或 diff。

**技术栈**：既有原生 JS 工作台 + React Flow v12 / React / dagre 局部组件；esbuild 生成本地静态模块，浏览器不依赖 CDN。新增依赖需登记 VERSION-PINS。

## 当前状态与下一步（2026-11-03）

以下状态以当前代码和本节验证为准；文末按日期保留的分片记录是当时快照，不覆盖本节。

本轮已实现 M-B-11 冻结版本内的显式转人工短语，以及 M-B-10 的全部／待接管／由我接管／未读筛选。短语最多 20 条、每条 trim 后 1–100 个 Unicode 字符，拒绝 NUL 和 case-fold 重复；入站事务内用字面子串匹配复用人工请求与消息幂等路径，不调用模型。筛选只改变 Inbox 列表投影，不确认已读、不接管、不丢失当前回复草稿。只读稳定版、候选和比较视图不混入草稿短语或表单错误；成功替换父 JSON 后清理下属字段缓存，错误 JSON 保留原文和有效配置。配置与 Inbox 浏览器 fixture 已通过；完整辅助矩阵仍未验收。

接管辅助已实现 `inbox.assistance.generate/check` 与折叠候选区：限定本人接管的固定版本线程；生成前后及采用前重验 tenant/Agent/actor/generation、全部消息、冻结版本和当前授权资料快照。严格结构化输出携带知识引用和模型用量；候选使用纯文本展示，生成不写消息、事件、已读或占用；显式采用只填入编辑框，人工在 check 等待期间编辑时保留其内容，发送仍走原 `inbox.reply`。切会话、新消息及占用/版本变化丢弃迟到候选。模型故障脱敏、超时和无效输出失败关闭。专项服务/Provider 32 项、独立零 DML/快照与前端并发检查通过；浏览器 fixture 的接管、采用、手动发送、迟到/线程隔离、故障与 1440/390px 布局通过，page errors 0。一次原创虚构真实模型样本（gpt-6-sol，1 次调用、0 重试，4770/180 input/output tokens、3128ms）通过引用、显式发送及 SQLite 重开；不能推定多样本质量。

本轮集成验证（2026-11-04 收口后最终实测）：Python 全量 739 项（`ResourceWarning` 按错误）、前端 340/340、Canvas 构建、S1 自检与合同语义自检通过；AGI-07/08 专项 61 项、Contact／周期／算子专项 190 项、WebView 桥合同 12 项通过。SQLite 当前为 v23；v20 是 Inbox consumer durable ack 增量，v21/v22 为 AGI-07/08 诊断许可、不可变证据、诊断报告与 Worker 作业四表的同事务迁移，v23 为服务周期生命周期（generation/state/closed_at/predecessor lineage、`service_cycle_migrations` 审计表、active 周期 partial unique index 与旧库条件式 ALTER 兼容）。四个开发工作包均已收口：AGI-07/08 五缺口修复 + 12 项新测试 + 两份独立审查工件；服务周期 `close/adjudicate/migrate` + 10 项生命周期测试；`changed_to` 判定不可行并保留明确拒绝与 6 项反例；Contact 完整批准路径 9 项端到端证据；WebView 桥 8 项生命周期静态合同。真实 harness Provider / host 联调、质量对照、生产服务周期来源签发、真实渠道/Push、OCR/视频理解、实机移动 WebView、模型质量矩阵、目标角色与 R2/R3 Gate 继续保持未通过；见 [R3 收口与验收对照](../../reports/R3-ACCEPTANCE-2026-11-04.md)。

### AGI-07/08：只读诊断与可选 Worker 首链（2026-11-04，代码、五缺口修复与审查工件均已落地）

本项来自 [Agent 接入计划](../../AGENT-INTEGRATION-PLAN.md#agi-0507cli-与只读诊断)和[版本归属](../../RELEASE-PLAN.md#51-外部接入项agi-0111落版本)，补回 R3 六个 WP 之外的明确交付范围。原判定为「现有 `run.diagnostics` 只有 recall/context 脱敏投影，不能代表诊断 Skill 或通用 harness Worker 已实现」。2026-11-04 复核：诊断 Skill 与 Worker 首链代码已落地，五个确凿缺口修复、12 项新测试（专项 61 项）与独立规格／代码质量审查工件均已交付；真实 harness Provider / host Skill 联调与质量对照仍无证据，故不改 Gate 结论。

**目标**：由 owner 明确选定运行和审定案例、签发有时限的诊断许可，外部诊断 Agent 或独立 Worker 读取同一份有界脱敏证据，提出带精确引用的六类根因候选；报告不改业务状态、真值、配置或发布。首链只支持诊断目的，Task 工作集、配置改进、例行调度与完整 Worker 治理仍归对应 TM/R4 工作包。

**最小合同**：

- 许可绑定 tenant、Agent、recipient actor、选定 run/case、证据合同版本/hash、用途、到期时间与撤销状态。调用方不能自报角色、审定身份或生产权限；缺少有效许可时外部 Agent 仍不能调用原运行查询。
- 证据最多 10 个已归属运行、每个最多 100 条白名单事件，总快照最多 128 KiB。只保留已登记的结构字段和原因码，不返回客户文本、完整配置、工具参数/结果、来源原文、自由错误或凭据；超限显式返回缺口，不能把裁剪后的证据当完整轨迹。案例仅引用服务端受信案例登记或明确的原创固定案例清单，保存不可变 source ID/hash、审定/消费状态和用途，并由来源复核；状态未知、未消费 blind 或未知分类拒绝。API 不接受调用方自报 `reviewed=true/blind=false`，诊断参考不创建或修改评测真值、既有 Case 或盲测消费状态。
- 报告为 `proposal`，类别仅 `knowledge/routing/loading/policy/tool/rule`，每个候选至少引用一个已披露的精确证据 ID；未知/不足的部分明确为不足。只允许案例提名建议，不将模型判断升级为事实或业务终态。
- Worker 作业与业务 `Run/ServiceRequest/TaskItem` 分离。冻结发起身份、目的、许可、输入哈希、精确工具 Schema/hash、Provider 标识、总时限/尝试数/输出上限；采用固定最小只读工具子集。显式启动、取消与安全重试；不安装定时任务，不自动恢复运行。
- `queued/running/cancel_requested/cancelled/interrupted/failed/exhausted/succeeded` 与 Provider 的停止/结果 `unknown` 分开留证；本地 interrupted 不证明远端停止。Provider 完成与报告原子落库分开；产物 CAS、许可有效性和冻结输入 hash 重验在同一事务完成，防止撤权与落库竞争。CAS generation 阻止重复领取和迟到输出；取消未确认保持待确认，未知用量保守占用预算，未知执行不能直接重试。重启后旧运行只可经明确恢复检查进入 interrupted，再由获权人显式安全重试，预算不重置。
- 首个真实 harness Provider 先核官方合同、锁版本并隔离工具、文件、网络和凭据；无可用 Provider 时明确不可运行。直接结构化模型、脚本 Provider 与真实通用 harness 分开登记，不能互相替代验收。

**文件与步骤**（所有步骤保留现有未提交工作，不暂存或提交）：

- [x] `loomrise/diagnostics.py` 与 `tests/test_diagnostics.py`：先验证跨范围/未选运行、白名单脱敏、blind 拒读、引用伪造及超限，再实现许可和证据/报告校验。`durable_store.py` 仅增本用例的事务存储与迁移；不重构无关模块。（2026-11-04：代码已落地，专项回归通过）
- [x] `loomrise/governance_jobs.py` 与 `tests/test_governance_jobs.py`：实现独立作业、幂等、预算、取消、重启裁决和代次隔离；Provider 注入用于故障测试，不将替身当真实联调。每次外部调用及产物提交前重验有效许可。（2026-11-04：代码已落地，专项回归通过）
- [x] `loomrise/adapters/harness.py` 与 `tests/test_harness_provider.py`：首 Provider 的受限适配，严格结果、用量/失败和取消证据；供应商私有状态留 Adapter。运行时选择和支持范围按实际验证回填。（2026-11-04：代码已落地，专项回归通过）
- [x] `configuration.py`、`config_cli.py`、`adapters/mcp.py` 与必要的 `config_http.py`：语义诊断/作业入口复用应用服务。诊断 MCP server 只披露该工作流所需工具，不借全部配置工具服务器取得发布/在线业务能力。（2026-11-04：语义诊断入口已复用应用服务；治理作业经安全裁决仅保留本机 CLI，HTTP/MCP 明确不暴露并有拒绝测试，见 `configuration.py:1108`）
- [x] `skills/loomrise-diagnose/SKILL.md`：版本化诊断步骤、合同和证据不足处理；本地包与 MCP resource 使用同一内容。读取资源不冒充真实 host 已完成 Skill 激活。（2026-11-04：代码已落地，专项回归通过）
- [x] 先通过独立规格审查，再做代码质量审查。必须覆盖撤权/到期、旧 Schema/hash、重复提交/回调、取消竞争、重开、预算耗尽、迟到结果、全业务表零写入及故障下手动/在线服务独立可用；同步证据登记与总索引，真实 host、供应商和质量对照仍按实测标状态。（2026-11-04：两份审查工件已落盘并逐条核查，见 `docs/superpowers/specs/2026-11-04-agi-0708-spec-review.md` 与 `docs/superpowers/reviews/2026-11-04-agi-0708-code-quality-review.md`；专项（8 模块）105 项、最终全量 739 项 OK；真实 Provider/host 联调仍无证据）

验证入口（2026-11-04 已实跑）：`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics tests.test_diagnostics_interfaces tests.test_governance_jobs tests.test_harness_provider tests.test_governance_harness_integration -q` → `Ran 61 tests ... OK`；CLI/MCP/HTTP 同合同回归见 `tests/test_diagnostics_interfaces.py`（含治理作业仅 CLI 的拒绝断言），全量 Python 739 项与合同语义自检通过。真实 host / Provider 联调未运行，不预填通过结果。

2026-11-03 后续补证（访客字段、知识摄入与文档处理）：`test_offline_reception_obeys_the_full_weekly_schedule` 按周一至周日验证 offline 服务时段与 Provider 调用；服务端和 Widget 浏览器 fixture 覆盖必填 `text`、选填 `email/tel`、空选填值、多字段 Inbox 投影和长度边界。正确以 `--seed-widget-release` 启动的 loopback 浏览器复跑通过，page errors 0、1440/390px 无横向溢出。知识服务新增 URL 成功摄入→`ready`/哈希/索引检索，以及文件先失败、修复后重试成功的集成回归。图片 OCR 的语言枚举与正文都改用 `_run_bounded_stdout`，分别限制 5s/15s 和 64 KB，超限即终止子进程。旧 `.doc` 使用 macOS 系统 `textutil` 的 15s/8 MiB 有界路径，并以真实 RTF→DOC→摄入/检索 fixture 验证；无该工具的平台仍不可用，未形成跨平台兼容证据。Python 全量 617/617（`ResourceWarning` 为错误）、前端 323/323、Canvas 构建、S1 自检通过。全部为本机/确定性 fixture，不代表公网、真实渠道或目标角色验收；M-B-02/M-B-06/M-B-08 与 R3 Gate 保持未通过。

| 工作包 | 当前工件 | 仍需完成 |
|---|---|---|
| WP1 / WP2 | 共享草稿三投影、嵌套/端口/边编辑；应用后撤销与重做；任意版本画布差异；事件/窗口/正向模型叶构造器；持久嵌套等待和本层 fallback；逐字文本产出；`ExecutionService` 默认真实 Provider 接入闭集路由、completion 与同轮召回；单候选首样本及后续路由/召回各 2 候选的虚构样本均完成持久执行与 SQLite 重开核验，后者 27 条事件、生成模型标识有效；图边正向非空 `llm.prompt` 仅在本层 `llm/hybrid` 可冻结，否定/确定性表面仍拒绝，纯模型/空叶外的三层组合同样拒绝；画布原位更新、键盘焦点与失败收尾均有回归；边界事件/等待结构化编辑、条件摘要、错误定位、会话内拖动/自动布局/专注视图均有浏览器回归，布局坐标只在当前视图态；schema v17 的本机虚构来源周期绑定/跨请求原子计数已有专项覆盖 | 多样本真实模型质量、完整客服/执行回放与兼容矩阵；真实业务源签发、周期生命周期/迁移与 session 来源；目标角色键盘任务基线；未知资源和条件格式继续禁止冻结 |
| WP3 / WP4 | 图外托盘、范围/上限校验；同轮受限 Skill 加载、默认关键词选择器和可注入同步/异步选择器、数量/token 限制与诊断；闭集提示；默认真实 Provider recall 接线；闭集提示忽略审计由服务端重算并写独立记录，进入候选冻结摘要且画布可见；`matches` 正则编辑隐藏类型选择器、保留模式文本，限制 128 字符并提示匹配字段最多 1024 字符；持久执行服务已有单/双候选固定虚构样本；新增真实 `ExecutionService` 发出 recall/context 事件、SQLite 重开后经授权 `run.diagnostics` HTTP 分页与脱敏核验 | 多样本召回/路由质量与模糊输入矩阵、目标角色基线。诊断端到端证据使用确定性脚本和版本化虚构 fixture，不构成真实 Provider 质量或权威生产上下文证据。忽略审计、条件表单及 Canvas 构建已纳入本轮 Python/前端全量回归 |
| WP5 | Contact Page 工作台、固定版本访客会话与可选 AI 起草；严格 21 类生成 Schema，候选须明确采用后另行保存，真实模型已完成一个虚构三块样本及 SQLite 重开核验；21 类草稿/预览和预置批准快照的公开页均有 1440/390px 浏览器证据。Widget/Inbox 配置、真实模型引用答复/历史/人工接管首样本；FAQ 建议按问题 + 精确 `source_id/content_hash` 关联到当前 AI 接待版本，限制 8 项/160 Unicode code point/不重复，Widget 仅公开问题并经普通 `widget.send` 检索；工作台支持结构化编辑、移除和共享草稿持久化。后端/Widget/工作台有本地确定性 fixture 与 Unicode 浏览器回归；关闭时段留言刷新、`ai_reception.mode=offline` 在开放时段转人工且消息留在 Inbox、同线程续接及坐席回复回到原 Widget 会话的浏览器断言已补。营业时间已覆盖开闭/DST、代表性隔夜与周日跨周一边界；服务层七天 `offline` 排班矩阵、必填空白/长度边界，以及 Widget `text/email/tel` 原生字段、必填阻止建会话、选填为空和多字段进入 Inbox 的浏览器回归已通过。以上为本机 fixture，不关闭 M-B-02/M-B-06。知识 URL 成功摄入与索引、文件失败后修复重试已有服务级集成测试。图片 OCR 正文和语言枚举都受 64 KB stdout/5s 与 15s 上限。旧 `.doc` 在 macOS 由系统 `textutil` 有界提取并以真实生成样本通过摄入/检索；其他平台没有该工具时明确不可用，跨平台兼容仍缺。Contact 21 类 fixture 补充外链新窗口 `noopener noreferrer` 与空 `social/link/booking` 隐藏断言。每坐席单调已读游标、访客未读投影与默认关闭的个人偏好已有后端及迁移/回滚/HTTP 证据。SQLite `SCHEMA_VERSION=19`：v16 读游标/偏好、v17 本机周期绑定、v18 脱敏 Inbox 事件、v19 配置告警忽略审计。Inbox SSE 浏览器 fixture 覆盖无游标冷启动基线及同事务接管提醒优先；独立 loopback Widget 双访客浏览器上下文已验证会话/消息隔离与交叉 token 读写拒绝。人工 Inbox 现从持久消息投影显示消息数/最近访客摘要，并仅在本人接管时提供可编辑的通用确认草稿；不调用模型、不自动发送，loopback 浏览器检查验证未接管禁用、手动提交和 1440/390px 布局。Notification 仍仅为权限/显示替身，不证明系统送达。渠道沙盒原子持久化；经审简介检索；FFmpeg 图片预览、视频转码/封面、产物持久化及人工交付。MP4/WebM 内嵌文本字幕可生成待审节选；无文本字幕时最多 5 帧的有界关键帧 OCR 候选仅以替身输出验证。本机缺 Tesseract/语言包，真实 OCR 质量未验；物料 PDF 路径最多前 20 页、10 MiB 原件，原生与 OCR 合计 64 KB、30 秒总时限、单页最长边 2000px/12.5 MB。知识文档 PDF 另走原生文本提取：输入最多 5 MiB、仅前 20 页、可选 `pdftotext`、15 秒超时、输出最多 8 MiB；缺工具或无文本层时不可用，不提供 OCR。客服统计覆盖文字接待记录时间窗内的请求/Run、结果、可用接管事实、服务端处理时延、Provider 用量、入口与版本；访客时延/送达未知，语音不在当前统计源。Widget 安装页读取只读 `release.entry.list`，仅对状态有效、loader ID 格式合法的已发布沙盒入口生成本机脚本；选择后重绘保持焦点，独立 loopback 网站往返及 allowlist/CSP 拒绝有本轮浏览器证据 | 真实 Telegram/Email 授权收发；系统级 Web Push/Telegram 通知与送达回执、隐藏页生命周期、移动 WebView；视频语音转写/多模态理解、真实 OCR 质量与兼容验证，原生文字页中的图片区域仍不 OCR；Contact 多样本/21 类输出质量、完整批准流程与角色基线、完整客服矩阵。Widget 公网/云安装与坐席身份/授权隔离未交付；双访客隔离仅有 loopback fixture 证据，不等于生产身份验收；M-B-01 完整独立网站矩阵仍待验证。模型生成的接管摘要/回复草稿、策略化转人工建议及恢复策略仍未验收。统计仍缺真实访客时延/送达与语音覆盖；HTTP 仍为固定本机 principal |
| WP6 | `run.overlay` 按专家/版本/时间窗/渠道聚合持久事件；图上显示完整层级节点/边计数；低样本不显示比例；`graph-telemetry-v1` 提供明确的解释器节点执行耗时样本及有效终止目标证据；节点角标按精确层级映射进入数、执行时长均值/样本数和终止数 | 目标角色任务测试及开发完成后的最终 UI 走查；耗时是 Unit body 处理时间，嵌套父图包含子图时段，不表示访客等待或已挂起等待时长；终止证据仅在完成状态、节点已先进入且引用最后有效路由步骤时计数 |

2026-11-03 本轮完成 Widget 安装工作台的已发布沙盒入口列表/选择与脚本生成集成；通过只读 `release.entry.list` 读取精简元数据，不以版本 ID 充当 `entry_id`，对 stale entry、非 loopback 服务与 loader 不接受的公开 ID 禁止生成代码。独立来源 Widget 往返、来源拒绝/CSP 与安装页的选择/焦点/响应式浏览器检查均已从登记 runner 复跑通过；仅为 loopback 与固定 principal 的本机 fixture。Inbox 新增消息数/最近访客摘要及本人接管后的通用确认草稿，明确提交仍走原 `inbox.reply`；1440/390px fixture 无溢出、无自动发送。营业时间新增周内隔夜与周日跨周一 `[start,end)` 代表性回归，完整访客字段/整周矩阵仍待补。全量 Python 609/609（`ResourceWarning` 为错误）、前端 323/323、Canvas 构建和 S1 自检通过。下一步继续推进可本机完成的客服矩阵缺口，并保持真实通知/移动入口/视频理解、多样本模型质量、客服矩阵和角色基线分开验收。所有服务周期绑定目前都仅使用本机虚构来源，生产业务源签发、周期关闭/新周期裁定与显式迁移尚未接入，不能把调用方 ID、session/request/run 或计数快照当业务周期。Inbox SSE fixture 覆盖无游标冷启动基线和同事务接管提醒优先；Notification 仍只是权限/显示替身，不是系统送达，轮询仍不能证明外部可靠回执或隐藏页生命周期。接入真实渠道前必须有明确 Provider 授权与回调环境。视频关键帧 OCR 仅有受限候选与替身输出回归，本机缺 Tesseract/语言包的真实质量验证；同页原生文字旁的图片区域未识别，音轨仅留元数据且无转写/多模态理解。真实业务工具沙盒和完整语音执行仍按 R4 验收；R3 角色任务基线、真实 Telegram/Email 和 R2/R3 技术 Gate 未通过，不能以本地回归关闭退出 Gate。

2026-11-03 FAQ 建议版本关联与工作台编辑：AI 接待配置将 FAQ 问题绑定到本版本已允许的精确来源哈希；服务端验证最多 8 项、最多 160 个 Unicode code point、NUL/空值与 Unicode case-fold 重复。公开 Widget 只收到问题文本，点击后走普通 `widget.send`，不携带来源标识或答案。R1 工作台可添加/编辑/移除建议，操作进入共享草稿/revision；只读和冻结态不允许写入。`tests.test_widget_configuration` + `tests.test_customer_service` 21 项通过，前端 `npm test` 307 项、Canvas 构建和 FAQ 工作台浏览器检查通过；FAQ Widget/Inbox确定性 fixture 浏览器检查通过，page errors 0，桌面/390px 均无横向溢出。复现入口见 [R3 能力证据登记](../../reports/R3-EVIDENCE.md#m-b-01)。这些仅为本机 fixture；公网安装、完整客服矩阵、真实模型质量和目标角色基线仍待验证。

2026-11-03 知识文件 PDF 原生文本摄入：`knowledge_documents.py` 复用有界子进程读取器，限制原件 5 MiB、前 20 页、15 秒、输出 8 MiB；`pdftotext` 可选。缺工具和无文本层/扫描 PDF 明确不可用，不做 OCR；旧 `.doc` 仍不可用。`tests.test_knowledge_documents` 17/17 通过，新增回归确认摄入调用沿用页数、时限与输出上限，并确认提取内容进入索引。来源失败/重试/撤回与引用以及格式兼容矩阵仍待验证。本条与物料处理 PDF/OCR 路径分开登记，不改变 R3 Gate。

2026-11-03 回归复跑与时区边界：本轮 Python 全量 599/599、`prototypes/console-next` 前端 308/308、`npm run build:canvas` 均通过，覆盖闭集忽略审计、条件表单与 PDF 摄入专项。`tests.test_customer_reception` 33 项通过；新增 IANA `America/New_York` DST 春季跳时、秋季重复小时回归，按本地 `[start,end)` 判断。该测试不代表完整工作周/隔夜时段和访客浏览器矩阵。M-B-02/M-B-06 已有开闭、UTC 到本地时区边界与固定版本同线程证据；完整在线/离线、浏览器留言续接及真实渠道仍未覆盖。Gate 保持未通过。

2026-11-03 Widget 离线留言续接浏览器检查：扩展 `prototypes/console-next/tests/widget-configuration-browser-check.js`，在 `hours: []` 本机 fixture 验证必填访客资料后创建会话、FAQ 留言走普通 `widget.send`、无 AI 答复且消息进入 Inbox；刷新后 `conversation_id` 不变且留言仅出现一次；Inbox 会话 ID 一致并能看到留言；坐席回复回到同一 Widget 会话。`npm test` 308/308，`npm run build:canvas` 通过，`tests.test_customer_reception` + `tests.test_widget_configuration` 43/43，浏览器 page errors 0 且 1440/390px 无横向溢出。仅关闭本机 fixture 的续接断言缺口；完整时段/访客矩阵、真实渠道、角色基线与 R2/R3 Gate 仍未通过。

2026-11-03 AI 接待 offline 模式浏览器检查：新增 `widget-offline-reception-browser-check.js` 与 `--offline-reception` fixture 开关，验证 Widget 仍开放时，`ai_reception.mode=offline` 返回 `outside_schedule`、不产生 AI 回复、访客消息刷新后不重复且 Inbox 同线程可见。浏览器检查 page errors 0、1440/390px 无溢出；客服接待与 Widget 配置专项 43/43。它补齐一个明确的本机行为分支，不代表完整时段/访客矩阵或真实渠道验收。

2026-11-03 Runtime→diagnostics 端到端：`tests.test_config_http` 使用确定性版本化虚构 pack 经真实 `ExecutionService` 产生 recall/context 事件，写入 SQLite、关闭并重开，再通过授权 HTTP `run.diagnostics` 验证归属、分页、游标边界与脱敏；测试也覆盖 Unicode/标点 Unit ID。WP3/WP4 本机可运行诊断数据面已验证，不能外推真实模型质量或生产来源权威性。聚焦诊断/存储/并发 36 项通过；合并后 Python 全量 608 项、前端 308 项、Canvas 构建和 S1 自检通过。

2026-11-03 Widget 双访客身份隔离浏览器回归：扩展 `tests/widget_install_browser_check.js`，在两个独立 Playwright BrowserContext 各自打开同一 loopback Widget，断言会话 ID 不同、双方消息互不可见，交叉 token 对两边会话的读取与发送都以 404 拒绝；既有访客→Inbox→坐席回复及 allowlist/CSP 检查仍通过。1440/390px 无溢出，page errors 0；CSP 来源拒绝预期产生一条 console error。它仅证明本机访客 token 边界，不证明坐席认证、公开部署或生产身份系统。

2026-11-03 知识格式后缀边界：扩展 `tests.test_knowledge_documents.test_html_ingestion_extracts_visible_text_and_omits_script_content`，`.html` 与 `.htm` 均验证正文进入索引且脚本内容不进入索引。知识摄入其余支持格式已有最小原创 fixture，但不视为真实 Office/浏览器导出兼容矩阵；该专项 17/17 通过。

2026-11-03 Contact Page 外链渲染与隔离 runner：`contact-editor-browser-check.js` 现对 21 类批准快照中的所有 `href` 断言 `target="_blank"` / `rel="noopener noreferrer"`，并验证空 `social/link/booking` 块不出现链接。隔离 `CONSOLE_TEST_APP_URL=http://127.0.0.1:18767/` 和 `CONFIGURATION_TEST_API=http://127.0.0.1:8782` 后完整浏览器矩阵通过：21 类公开块、1440/390px、page errors 0；3 条 console errors 分别对应预期 404/409 API 响应。`npm test` 308/308、Canvas 构建、`tests.test_contact_page` + `tests.test_contact_generation` 36/36 通过。此证据不证明真实外站预约/线程续接或 M-B-03 通过。隔离 runner URL 仅接收 loopback HTTP 根路径，未覆盖地址仍使用原默认值。

2026-11-03 闭集审计与字符串条件表单：`advisory.dismiss` 由服务端按当前 revision/层级重算闭集大小，写入独立 SQLite 忽略记录，不改草稿配置或 revision；操作者与时间在候选冻结时进入只读 `review_summary`，工作台候选摘要与画布均可见。`tests/test_closed_set_advisory.py` 33 项曾通过。画布 `matches` 编辑器隐藏值类型选择器、保留 regex 文本，限制模式 128 字符并提示字段值 1024 字符上限；`prototypes/console-next/tests/orchestration-conditions.test.js` 相关 10 项及 `npm run build:canvas` 曾通过。复现入口：`rtk proxy .venv/bin/python -m unittest tests.test_closed_set_advisory -q`；前端专项从 `prototypes/console-next` 运行 `rtk proxy node --test tests/orchestration-conditions.test.js`，构建运行 `rtk proxy npm run build:canvas`。

2026-11-03 移动 WebView 桥合同首片：`loomrise/customer_widget.html` 加入 `loomrise.webview.bridge.v1` 的 `postMessage` 合同，限定 loopback host origin 与 `window.parent` 来源；仅接收已有会话凭据或按公开 Widget 字段白名单过滤的访客信息，不接受 tenant/actor/role 等权威字段。关闭/关闭确认使用独立消息；无 parent host 时桥调用安全 no-op。`prototypes/console-next/tests/customer-widget-bridge-contract.test.js` 的 Node VM fixture 覆盖来源/Origin、schema、身份拒绝、dismiss、no-host 与同会话持久化合同。此证据仅证明静态合同与浏览器端逻辑；尚无 iOS、Android、React Native、Flutter WebView 运行、生命周期、关闭按钮/桥及真实容器能力验证，M-B-15 仍未通过。

2026-11-02 服务周期、Inbox 事件回放与集成回归：schema v17 的本机受信授权器绑定固定租户/专家/虚构来源，服务请求固定引用周期和冻结配置；循环/回退预算按跨请求事务原子预留并与审计事件同提交，等待恢复/重开/备份/迁移及竞争测试通过。schema v18 新增按 tenant/agent 有序、正文和 actor 脱敏的 Inbox 事件；访客消息、助理答复及接管申请/认领/回复/释放与原状态事务一同写入，`inbox.events` 限页回放。前台使用作用域游标消费，合并同轮提醒；浏览器 fixture 覆盖轮询间发生并结束的接管变化，1440/390px 无横向溢出、page errors 0，2 条 console errors 来自预期失败注入。`tests.test_inbox_read_state` 13 项、`tests.test_service_cycles` 18 项，完整 Python 回归 **526 项**、`npm test` **286 项**、Canvas 构建、S1 自检与合同语义自检通过。以上均为本机 fixture；不构成真实渠道/Push、目标角色基线或 R2/R3 Gate 签核。

2026-11-02 遥测修正与浏览器验证：终止证据必须引用先于终止边进入的同层节点，且对应最后一个有效路由步骤；非法顺序不计入终止目标。路由时长只接受非负 JSON 整数，不把布尔值当作 1ms。`tests.test_run_overlay` 16 项通过；Python 全量 425 项通过；`npm test` 275 项通过；`npm run build:canvas` 通过。浏览器 runner 已登记客服统计与键盘画布检查：统计页 fixture 连续运行两次均验证新增计数增量、服务端累计值、未测指标标识和 1440/390px 布局；键盘画布覆盖嵌套下钻/返回、图与清单共享选中、检视器编辑、边选择，1440/390px 无横向溢出，page errors 0。该证据仅是本机虚构 fixture，不构成角色基线或 Gate 签核。

2026-11-02 PDF 与键盘修正：可选本机 `pdftotext` 26.08.0 仅提取 PDF 前 20 页原生文字；原件上限 10 MiB、输出上限 64 KB、超时 15 秒，输出超限会终止子进程；候选必须人工批准后才可检索。`tests.test_material_processing` 与 `tests.test_material_retrieval` 共 16 项通过；Python 全量 430 项、`npm test` 275 项、`npm run build:canvas` 通过。扫描 PDF、视频理解仍未接入。画布实现图形节点 Enter 下钻与 Escape 返回，按返回路径恢复焦点及父节点选择，键盘浏览器检查已扩展；本轮 Playwright CLI 在启动阶段无输出并以非零退出，**这次修改后的浏览器检查未验证**。草稿编辑触发整个工作面重挂载、影响键盘焦点恢复的问题仍待处理；目标角色任务基线与最终 UI 走查未完成。

2026-11-02 画布焦点、媒体编辑与 WP6 遥测投影：配置工作面收到画布草稿变更时改为原位更新已挂载 React Flow root，避免整页重挂载；键盘浏览器检查验证嵌套下钻/返回、图/清单选择同步、父/子检视器编辑后焦点保持、节点摘要刷新、边选择和 1440/390px 无溢出，page errors 0。WP6 角标按完整层级投影解释器 Unit body 执行耗时均值及样本数、有效终止数；在 SQLite + 实际脚本 ExecutionService RunEvent fixture 验证根/嵌套映射、低样本比例隐藏、稳定版本只读和 1440/390px 画布布局，page errors 0。执行时长包含当前 Unit body 的同步/await 处理时间，父图节点包含嵌套子图时段；不含跨调用挂起等待，也不代表访客等待或外部送达。Contact Page fixture 验证图片、视频、音频内容块的新增/编辑/服务端保存/刷新/草稿预览，图片自然尺寸、WebM 16x16 解码与 WAV 时长，媒体请求由本机 fixture 接管，1440/390px 布局无溢出，page errors 0；检查器报告 2 条未核实 console errors，故不称 console 0。`npm test` 275 项、`npm run build:canvas` 与 Python 全量 430 项通过。以上均为本机虚构 fixture，不是目标角色任务基线；真实模型完整客服/执行服务回放、R3 Gate 仍未通过。

2026-11-02 Provider 失败收尾：`drive_reply` 普通异常现在写脱敏 `run.execution_failed` 并结束 `run.finished` / 耐久 Run；先前或本轮已提交的业务结果保持成功态，SQLite 收尾错误继续透传。新增 `tests.test_service_failure_finalization` 3 项覆盖连接错误、写入后失败与 SQLite 收尾错误。`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_service_failure_finalization tests.test_graph_provider_wiring tests.test_model_provider tests.test_durable_recovery tests.test_graph_service -q`：41 项通过；Python 全量 434 项、`npm test` 275 项及 `npm run build:canvas` 通过。这仅证明本机 SQLite 与注入 Provider 的失败路径，不证明真实 Provider 稳定性或 R3 Gate。

2026-11-02 扫描 PDF 候选首片：仅当 `pdftotext` 无可用文字时才对前 20 页按页调用 Poppler `pdfinfo`/`pdftoppm` 与本地 Tesseract；渲染长边 ≤2000px、每页输出 ≤12.5 MB、OCR 累计输出 ≤64 KB、共享 30 秒时限。缺工具或中/英文语言包时返回 unavailable；超时、坏图、输出超限失败关闭；摘要候选仍待人工批准，替换原件后旧候选不可检索。混合 PDF（已有任意文本层）不对空白扫描页回退 OCR。新增材料处理/检索测试；专项 25 项与 Python 全量 443 项通过。当前本机 Poppler 26.08.0 可用，但没有 Tesseract，故 OCR 仅有模拟进程测试，未验证真实识别质量/兼容矩阵。

2026-11-02 模型叶与真实执行联调：图边允许正向 `{"llm":{"prompt":"非空判据"}}` 参与本层 `llm/hybrid` 闭集；字段/事件/窗口混合组合仍验证完整树和最多两层深度。否定子树、deterministic 路由、G0、HardRule、judge 和确定性 completion 不开放该例外；空判据、未解析引用、额外字段在冻结与运行前拒绝。画布沿用 Loomrise AST，不复制 ElevenLabs 的 `type:"llm"`，支持结构化模型判据并保留未知 JSON。TDD 已观察失败；`tests.test_graph_validation/tests.test_graph_runtime/tests.test_graph_service/tests.test_graph_completion/tests.test_config_validation` 专项 129 项、Python 全量 446 项、前端 277 项与 Canvas 构建通过。`orchestration-diff-browser-check.js` 在临时 SQLite fixture 验证表单→保存→刷新→结构校验→候选冻结、空判据/否定模型拒绝和确定性 completion 无模型叶选项；1440/390px 无溢出，page errors 0，手机表单截图已核看。冻结候选未发布入口，不证明真实模型路由质量。

真实执行复现：`rtk proxy env PYTHONPATH=. .venv/bin/python tests/r3_model_provider_live_check.py --run-live --execution-service`。本机 `gpt-6-sol` 单次虚构样本完成模型 completion、召回 `refund-helper`、答复核对码，零业务工具/写入；SQLite 重开后 20 条事件一致、哈希链有效，Run/Request 为成功。该检查最多两次 Provider 调用及一次生成；候选数 1、不代表多候选质量、真实渠道或 R3 Gate。生成事件的 `model` 字段仍为 null，模型来源仅由本次固定连接与 completion 元数据佐证，不把该样本用于逐模型生成用量统计。本地报告在忽略的 `runs/`，公开仓库保留命令、脚本、样本和限制，不公开本机凭据。

2026-11-02 模型身份与联系页矩阵增量：AgentScope 固定版 `ModelCallEndEvent` 不含模型名，Adapter 改由实际执行的 `agent.model.model` 传给事件投影；输入/输出 token 与结束原因保持原值，SQLite 重开后模型标识和哈希链仍有效。TDD 已观察模型标识为 null 的失败；`tests.test_agentscope_event_projection/tests.test_run_agent_scope/tests.test_graph_service/tests.test_durable_recovery` 30 项通过。真实检查脚本现要求生成事件匹配实际模型；上述旧真实样本不被追认，修复后的真实模型验证另行留证。当前 Agent 组装不配置模型 fallback，本片不声明 fallback 溯源。

联系页复现使用全新 8779 临时 SQLite fixture（启动参数同下文 8778，替换端口），运行 `rtk proxy env CONFIGURATION_TEST_API=http://127.0.0.1:8779 node tests/run-browser-check.js contact-editor-browser-check.js`。21 类草稿块、19 类条目、保存刷新、FAQ 条目删除、块排序/删除、图片/WebM/WAV 解码、批准版单块公开页 1440/390px、停用 404 及 revision 冲突保留输入均通过；page errors 0。两条 console errors 已逐一关联到实际 `contact.get/not_found/404` 与 `contact.save/revision_conflict/409` 响应，不是未核实错误，也不记 console 0。草稿矩阵不替代 21 类批准公开页或角色任务验收。

2026-11-02 独立审查与多候选真实执行：审查复现纯模型叶外的三层组合可冻结、运行却拒绝；同类空叶也少算一层。共享组合计数已修正，模型叶本身仍不计层，外层每个组合都计数；根图与嵌套图的两层接受、三层拒绝先观察到 4 个失败子例，再通过专项 130 项及合同语义自检。该修复收紧不合法配置，不放松确定性裁决或两层上限。

真实多候选复现：`rtk proxy env PYTHONPATH=. .venv/bin/python tests/r3_model_provider_live_check.py --run-live --execution-service --multi-candidate`。脚本保持原单候选模式；新模式最多 3 次 Provider 请求与 1 次生成、禁重试。`gpt-6-sol` 在 2 条嵌套路由边中选择 `choose-refund`、到达 `refund-answer`，在 2 个召回候选中仅选 `refund-helper`，生成带 `R3-LIVE-REFUND-7319` 的答复；生成事件模型标识匹配实际模型。SQLite 重开后 27 条事件与原序列一致、哈希链有效，Run/Request 成功，零业务工具/写入。该次是一个固定虚构样本，不能推出统计质量、模糊输入鲁棒性、fallback 模型溯源或真实渠道通过。本机摘要保留在忽略的 `runs/r3-execution-multi-2026-11-02.json`；公开证据为脚本、固定样本、命令及上述边界。

本片最终回归：Python 以 `ResourceWarning` 为错误运行全量 **450 项通过**（预期脚本耗尽场景仍有 warning，不称零告警）；前端 **277 项通过**；Canvas 构建、S1 自检及合同语义自检通过。没有代签 R2/R3 Gate。

### 2026-11-02 Contact 起草、公开矩阵与混合 PDF 增量

`contact.generate` 沿用本机受信任连接，仅发送本栏显式素材和静态模板/Schema；不发送完整专家配置、业务 Prompt、工具、知识或客户历史。严格 Schema 支持既有 21 类块，生成只开放该类必填条目字段，手工编辑仍保留可选字段。owner/editor 与专家范围、精确 revision、1–4000 字符素材在调用前校验；每次独立预算，单次请求、无工具、无重试、`store=false`，await 后重验 revision。缺连接返回脱敏 503，坏输出/Provider 失败返回脱敏 502；取消透传。数据库仍为 schema v15。

工作台“AI 辅助起草（可选）”先返回待审候选，当前编辑和服务端草稿均不变；“采用并替换编辑内容”只更新编辑器，必须再点保存。只读、忙碌、版本冲突拒绝写入，改稿或切专家使旧候选失效，迟到响应不能回写。候选正文和字段仅渲染转义文本，不显示原始 Provider 元数据。走查发现 FAQ 候选按字母顺序先列回答，现复用手工编辑字段顺序，先问题后回答；回归先见红再通过。手动路径独立可用，无新增依赖或导航。

候选容器原先把模板缩进也按正文换行显示，导致说明与首块之间出现多余空白。现仅在实际文本字段保留换行和长词折行，结构化容器正常折叠模板空白；浏览器间距断言先失败后通过，1440/390px 最终截图已核看，候选顺序与布局正常。复跑前端 282 项及生成浏览器全链路通过。

`contact-generation-browser-check.js` 使用临时 SQLite 与确定性异步 Provider，在 1440/390px 验证生成不保存、采用不保存、显式保存/刷新、批准页不变、脚本转义、中文 composition 事件与焦点、模型失败/await 期间 revision 冲突保留输入、后续本地修改使候选失效；page errors 0，2 条 console errors 精确对应预期的 `generation_failed/502` 与 `revision_conflict/409`。只读权限和切专家迟到响应由单元/API 回归证明，本页无只读切换控件，不称浏览器已覆盖该路径。窄屏无页面横向溢出；截图使用 reduced-motion 避免捕获断点切换动画，生产样式未因此修改。截图在忽略的 `output/playwright/r3-contact-generation-{1440,390}.png`。

生成浏览器复现：根目录启动 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8781 --allowed-origin http://127.0.0.1:18765 --seed-contact-release --contact-generation-fixture`，前端目录运行 `rtk proxy env CONFIGURATION_TEST_API=http://127.0.0.1:8781 node tests/run-browser-check.js contact-generation-browser-check.js`。测试开关显式注入本机生成器并关闭默认接待模型，不消耗远程用量。静态预览仍为 18765；CLI 可通过 `PLAYWRIGHT_CLI` 指向已安装入口。

真实生成复现：`rtk proxy env PYTHONPATH=. .venv/bin/python tests/r3_model_provider_live_check.py --run-live --contact-generation`。已执行一次 `gpt-6-sol` 请求、零重试：新增 anyOf 严格 Schema 被接受，原创虚构素材产出 `text/chat/contact` 三块，保留核对码 `R3-CONTACT-8641` 与 `hello@example.test`；不自动保存，显式保存后 r2，SQLite 重开内容一致。Provider 返回 6098 输入/144 输出 token；这一个样本不证明全部类型生成质量、事实可靠性、批准/发布或送达。忽略的 `runs/r3-contact-generation-2026-11-02.json` 是根据已观察输出整理的摘要，不冒充原始调用日志；未重复前述真实路由/召回检查。

公开页矩阵保留原单块入口，再预置独立 `contact-matrix-fixture-v1` 批准快照；生产批准校验未放宽。`contact-editor-browser-check.js` 验证 21 类块全部可见字段（含顶层说明）、原序、FAQ 展开、图片/WebM 16×16/WAV 解码、固定版本 chat 链接、内部 Prompt 哨兵不泄露和无编辑器/脚本元素、两入口停用 404，以及草稿保存刷新/增删排序/revision 冲突保留输入；1440/390px 无溢出，page errors 0。3 条 console errors 对应两次 `contact.get/not_found/404` 与一次 `contact.save/revision_conflict/409`。这是预置批准快照的渲染矩阵，不是批准流程 Gate 或角色可用性证据。复现采用同一 fixture 参数但端口 8782，不需生成开关；前端运行 `contact-editor-browser-check.js`。截图为 `output/playwright/r3-contact-public-21-blocks-{1440,390}.png` 和媒体/FAQ 近景。

`material_processing.py` 保留 pdftotext 页分隔和末尾空页，仅对前 20 页中的空文本页 OCR，native/scan/native 按原序合并；所有原生文本预先计入共同 64 KB 输出预算。仍保留 10 MiB 输入、30 秒共用截止、2000px/12.5 MB 每页渲染、语言检查和有界 stdout；还有页未处理而预算耗尽时失败，不再返回就绪的截断前缀。缺 OCR 组件/语言时失败关闭，不把原生子集冒充完整候选；原件哈希及人工审核状态保留。原生文字页中的图片区域仍不 OCR，本机缺 Tesseract，真实质量未验。处理/检索专项 28 项通过，新增顺序、尾空页、共同预算等回归先观察失败再实现；规范与独立质量审查均通过。

后端独立质量审查发现共享 Provider 读取器将无效模型名/响应 ID 用 `str()` 转成了非空证据。现先校验原始值为非空、长度不超过 200 且无 NUL 的文本；缺失、null、布尔、数字等失败关闭，不静默替换为请求模型。20 个失败子例先见红，completion/Contact 的脱敏失败与 SQLite 不变回归通过；相关专项 51 项、独立复审 21 项通过，原 Important 已关闭，未为此重复调用真实模型。

本批集成：Python `ResourceWarning` 为错误全量 **467 项通过**，前端 **282 项通过**，Canvas 构建、S1 自检和合同语义自检通过。预期的脚本耗尽场景仍有 warning，不称零告警。后端、前端及处理边界分别经过独立审查；目标角色、真实渠道、OCR 质量与完整客服矩阵仍是未完成项。

文档收尾：8 份当前入口/专题文档的 371 个本地链接、19 个锚点检查通过；`git diff --check` 与 98 个未跟踪文本文件的空白/冲突标记检查通过，`private/` 保持忽略，暂存区为空。仅关闭本批新建的 8781/8782 临时 fixture 服务，保留继承的预览环境；未暂存、提交或发布。

### 2026-11-02 Inbox 已读后端与视频字幕增量

SQLite 升至 schema v16，新增每租户/专家/坐席的读位置及个人提醒偏好，不回填旧消息为已读。`inbox.list` 只读投影访客未读数、最后访客序号和全部消息最大序号；assistant/operator 消息不增加访客未读。`inbox.read` 必须显式提供非负整数且不超过当前消息序号，事务内单调推进，拒绝布尔、未来位置和跨范围会话；不修改会话状态、占用代次或业务结果。新消息在已读确认之后到达仍保持未读；两个 SQLite 连接并发确认不会把位置倒退。通知偏好默认关闭、严格布尔，actor/tenant 只取自 principal，viewer 仍不可写。

新增 `tests/test_inbox_read_state.py` 9 项验证，包括服务层范围/只读隔离、真实 loopback HTTP 合同、v15 迁移、重开/备份恢复及读位置/偏好/迁移提交失败原子回滚。当前 HTTP Adapter 对所有本机请求使用同一个受信任 principal，不能把这些服务层测试外推成逐浏览器访客/坐席登录隔离。新增能力继续属于 loopback 沙盒，未放宽 Host/Origin。

视频候选复用已有 FFmpeg/ffprobe 8.1，仅处理 MP4/WebM 内嵌文本字幕。默认字幕优先、否则最低索引，只取一条支持的文本流，并在 500 字符节选中注明索引、语言和人工审核；原件字节及 SHA-256 保持。输入上限 10 MiB、已知有限时长 ≤300 秒、最多 32 流且索引 0–31，探测和字幕 stdout 分别限 64 KB，共享 30 秒截止。缺组件、无文本轨/仅位图字幕返回 unavailable；坏 metadata/UTF-8/时间戳、进程失败、超时和溢出失败关闭，不返回就绪的截断内容。该预算只涵盖候选提取，不包括随后独立的封面/转码作业。

`tests.test_video_text_processing` 实际生成原创 MP4 `mov_text` 与 WebM `webvtt` 双轨视频，各 3 秒/160×120；默认中文流索引 2 的 `R3-VIDEO-ZH-7319` 和虚构邮箱被保留，备用英文轨不混入。真实工具子例未跳过，`material.process`→SQLite 待审→批准后检索、原件不变均通过。它不覆盖无字幕语音转写、烧录文字 OCR、镜头语义/多模态理解或全部字幕 codec/平台质量。

本增量后端全量以 `ResourceWarning` 为错误运行 **486 项通过**，Canvas 构建通过。独立审查实际运行 Inbox/HTTP 19 项、视频/PDF/物料 48 项通过，未发现指定后端范围的阻断问题；这次后端审查不包含随后完成的 Inbox UI，后者证据如下。

### 2026-11-02 Inbox 前台提醒与操作状态保护

官方 Inbox 显示访客未读数和当前待人工状态；个人偏好持久化与浏览器权限按钮分开，默认关闭。仅在当前线程响应已经渲染、页面可见且请求/选择代次仍有效时确认最大消息序号。列表或通知不确认已读、不接管；旧线程迟到响应不覆盖或误读新线程。轮询保留回复草稿和历史滚动位置，失败保留现有消息。上传、处理、接管、回复和发物料各自保持提交状态，轮询及物料选择不能重新启用未完成动作。提示只限定页面开启期间，通知标题/正文不含访客内容，初次读取和启用建立基线，重复轮询不重复提醒。

浏览器先在旧页观察到缺少控件，再观察到长历史不能滚动与轮询重新启用上传按钮的回归失败；对应修复后通过。作者的独立 8791 fixture 与 root 的全新 8784 SQLite fixture 各完成完整浏览器流程，覆盖权限拒绝/授权、不自动申请、偏好持久化、未读、通知点击不接管、迟到线程、输入/历史滚动保护、两种网络失败、显示异常、不支持降级，以及五类真实后端动作的提交期间保护。1440/390px 无横向溢出，page errors 0；两个 console errors 分别为故意 abort 的偏好保存和消息读取请求，不称 console0。截图为 `output/playwright/r3-inbox-notifications-{1440,390}.png`，root 已核看；390px 另以 viewport 截图复核，DOM 仅一份标题、页面高度 960px，避免将缩放后尚未稳定的截图重绘误判为重复 UI。缩放后检查脚本等待两次动画帧再采图。

复现（cwd `prototypes/console-next`）：`rtk proxy env PLAYWRIGHT_CLI=<已安装 playwright-cli 路径> CONFIGURATION_TEST_API=http://127.0.0.1:8784 node tests/run-browser-check.js inbox-notifications-browser-check.js`。fixture 参数仍为 `tests/r1_configuration_http_fixture.py --port 8784 --allowed-origin http://127.0.0.1:18765 --seed-contact-release --contact-generation-fixture`，接待 Provider 关闭，无模型用量或真实外发。前端 **282 项**、Canvas 构建、S1 自检和合同语义自检本轮重新通过。独立 UI 审查未发现指定切片的 Critical/Important 问题。

Notification 权限/显示使用替身，只证明调用合同；不证明 OS 送达、Web Push、后台唤醒或多标签精确一次。root 额外实际切换 Chromium 页面后，原页 `document.visibilityState` 仍为 visible，因此本环境没有隐藏页运行证据，不能据此追认 hidden guard 或原生后台生命周期。当前状态轮询可能漏掉两次查询间的短暂接管事件，可靠事件流与回执仍缺；HTTP 固定 principal 的身份边界不变。可信服务周期的源登记、请求绑定和原子防环已进入后端实施，尚未验收，R3 Gate 仍未通过。

2026-11-03 画布结构化检查器与会话布局：Unit 边界事件与等待接入结构化表单，事件/等待去处限制在当前 Unit 内容图的有效本层入口或自身出口；未知扩展字段在简单编辑时保留，未知结构仍回退原始 JSON。图节点显示精简条件摘要。画布允许临时拖动、自动恢复拓扑布局和专注视图，坐标只在当前 React 会话态，未进入配置/revision/diff。键盘浏览器检查覆盖事件/等待选项边界、未知元数据保留、拖动/重排不污染草稿、专注模式恢复、键盘路径与 1440/390px 无横向溢出，page errors 0；服务端校验定位检查覆盖根/嵌套边、端口字段与未知路径原文修复，page errors 0。验证：前端全量 323/323、Python 全量 608/608（`ResourceWarning` 作为错误）、Canvas 构建、S1 自检通过。fixture 为虚构本机配置，不是目标角色任务基线或 R3 Gate 通过证据。

## 设计依据与取舍

- [正式 Unit 合同](../../ROUTE-GRAPH-AND-UNITS.md)：契约层与内容层、端口跨层、事件不是边、闭集与 fallback、执行环 `cycle` 上限。
- [画布前端方案](../../S2-ORCHESTRATION-UI.md)：流程 tab 内三投影、一层一画布、坐标不落库、共享选中、清单作为键盘等价路径、端口及边差异。
- [ElevenLabs 总纲](../../ELEVENLABS-AGENTS-ANALYSIS.md) §13 与 [编排卷](../../competitive/elevenlabs/02-ORCHESTRATION.md)：借节点摘要、检查器、显式继承、出边顺序、错误定位与版本快照；保留 Loomrise 确定性权限与发布裁决，不照搬自由覆盖配置、概率护栏和托管绑定。
- 用户和场景沿用 [视觉系统](../../../prototypes/console-next/DESIGN.md)：搭建者/策略运营审阅配置；浅色紧凑后台，系统中文字体、蓝色主操作，错误包含文字与修复入口。

## 执行顺序与文件责任

### 1. WP1 共享服务画布首片

- [x] 新增 `prototypes/console-next/orchestration/model.js`：由 Unit 生成当前层节点、端口、候选出口边，拒绝无法识别形状；不推断不存在的执行顺序或统计。
- [x] 新增 `orchestration/canvas.jsx`、`orchestration/canvas.css`：局部 React Flow、自动布局、共享选中、图/清单/规则、契约检视器与原始 JSON 修复路径。
- [x] 调整 `views/r1-configuration.js`、`app.js`、`r1-configuration.js`：异步加载与卸载组件，草稿单一权威、只读候选、revision 冲突和未知字段保留。
- [x] 验证三投影一致、候选不可改、非法草稿诊断、无布局字段写回，运行前端回归与真实浏览器检查。

首片只投影当前已支持的 Unit 契约；当时不能据此称嵌套图可提交或已执行。当前支持子集图可提交，`tool`/`speak` 与未知资源仍按 Atom 级阻断；R1 非 graph 路径仍拒绝 concurrent 冻结。

第二片已加入显式 `unit-graph-v1` 草稿的单层实际边投影、下钻与面包屑返回；R1 候选出口继续以虚线展示，两种来源不混用。子图节点引用同一 Unit 注册表，检视器仍通过原索引修改同一草稿；同一 Unit 的多个节点实例不生成内容副本。

### 2. WP2 / WP3 / WP4 领域图与执行

- [x] 草稿结构首片：精确 Unit 版本引用、本层端口映射、组合 DAG、移除受限边后执行 DAG、循环计数/window、原子接口读写、逐层 routing.mode、事件作用域与条件深度诊断；接入共享校验服务。
- [x] 跨路径字段首片：分支入口 `requires` 和边条件按可达路径分析，汇合处取字段交集；LLM/否定条件不伪造字段存在证据。
- [x] 纯路由解释器首片：G0 优先、边界事件优先于边、嵌套 Unit 轨迹、确定性边、闭集选择、margin/evidence 校验和 G2 fallback；仅产出内存轨迹，不声明业务副作用。
- [x] RunEvent 适配首片：路由解释器可接受当前 Run 的 `emit` 闭包，写入 `route.graph.started/step/finished` 哈希链事件；不创建身份、不写 `result_id`，尚未替代旧 Skill 路由。
- [x] ExecutionService 集成首片：显式图版本从完整配置快照解析 Unit，要求 `unit_skill_bindings` 精确绑定到现有 Skill；图模式不再调用关键词路由，映射/终点失败关闭并写入 `request.route_failed`，旧版本保持原路径。
- [x] `judge` Atom 运行首片：进入 Unit 时执行确定性条件，将布尔结果仅写入声明的 `result_field`，结果可供后续边及父图读取；调用方输入态不被修改，非法写声明失败关闭并留路由审计步骤。
- [x] `waits` 合同与纯路由：Unit 接受可选 `{on, timeoutMs?, timeoutTo?}`，校验重复事件、超时形状和非法字段；未满足等待返回 `waiting` 及元数据。SQLite 已支持挂起、事件/超时唤醒、取消和快照传递，后台调度进程仍未实现。
- [x] ExecutionService 无 durable store 时等待失败关闭：写入 `request.route_failed`，原因固定为 `graph_wait_suspend_unavailable`，不误报成功且清理活动 Run；有 store 的路径已接持久 waiting。
- [x] 画布等待投影：节点摘要与检视器显示/编辑 `waits`，当前层可唯一解析的 `timeoutTo` 画为独立橙色虚线超时边，未知或歧义目标只留路径诊断，不推断跨层执行关系。
- [x] 闭集提示首片：按当前层 `routing.mode` 统计去重目标数，提供两级非阻断提示和合并/拆包/确定性/两段式替代建议；`concurrent` 单元不进入闭集。
- [x] 执行环计数运行时首片：环边以 JSON 层级路径 + edge id 生成稳定计数键；计数写入声明字段、结果快照与逐次 RunEvent；支持调用方传入先前计数，超 `max_rounds` 时走 `exit`，包括嵌套 Unit 返回父图路径。
- [x] 入口前提运行时检查：根图 `input_fields`、顶层/嵌套 Unit 的 `entry_ports[].requires` 在运行时逐项验证字段存在且非空；缺失时失败关闭并留路由步骤，不调用关键词路由。
- [x] Unit `self/subtree` 边界事件纯路由语义：递归解释嵌套图；`self` 可短路当前原子或图 Unit body，`subtree` 可在后代状态更新后重新求值，按声明图的局部目标跳转或出口向上冒泡；事件只消费一次。根 `global` 命中优先；同一层多 handler 按声明顺序、嵌套 subtree 按最近作用域先匹配。
- [x] 图形 Unit 出口 `completion` 运行检查：正常图返回及 `self` 事件捷径均须满足所选出口条件，否则失败关闭并留 `completion_failed` 轨迹。
- [x] 结构化边编辑：画布/当前层边清单共享边选择；右侧检视器支持本层出口、入口/自身出口、条件 JSON 与执行环字段编辑，优先级通过上移/下移调整真实边数组；嵌套图精确定位同一 Unit 注册表，快照/冲突/忙碌/坏 JSON 拒绝修改。新增边追加至本层末尾并拒绝重复 ID/非法跨层端点；删除支持撤销，后续边数组变化后拒绝旧撤销。既有边 ID 只读。
- [x] 对象级差异：保存回执按前一草稿 revision 比较，冻结候选按其基准稳定版本比较。`configuration.compare` 支持任意稳定版/候选组合。Unit、节点、入口/出口端口和边分别比较，边优先级单列；标识缺失或重复时明确诊断并按位置降级。画布显示增删改和优先级，未保存修改不混入版本回执。
- [x] 端口结构化编辑首片：入口/出口独立分组，可新增、删除、编辑标识；入口逐行配置 `requires` 与图 Unit 的内容层 `goto`；出口分别开关确定性/模型完成判据，保留其他元数据。原子单元固定一个入口/出口；旧格式或坏结构降级为原始 JSON 修复，不静默迁移。改名/删除不级联改写引用，明确提示同步连线后服务端校验。
- [x] 条件表达式构造器：边条件与确定性 completion 共用字段比较、事件名称/属性、24h/forever 状态窗口、带类型字面值和最多两层组合表单。边条件另支持正向非空 `llm.prompt`，保留旧 all/any 与单元素列表 not 别名。未知结构、cycle/session 窗口与复杂旧条件继续原 JSON 修复；否定模型叶和确定性 completion 仍拒绝。未完成表单拒绝应用，禁止空值被解释为无条件边。
- [x] 条件运行语义对齐：not/none_of 同按单元素列表否定；布尔求值前检查整个条件树。事件属性和持久 24h/forever 计数已有运行支持，未支持条件不得经否定或短路变成可通过条件。模型叶只在正向闭集 selector 路径处理。服务层遇到不支持条件失败关闭、清理活动 Run、记零写入；完整算子和周期来源仍缺。
- [x] 端口引用影响与撤销：改名/删除时列出原端口的明确引用路径，覆盖精确版本节点实例、版本/内容入口、边起终点/循环出口、事件、兜底与当前投影支持的 self 出口超时目标；R1 只检查显式候选端口引用。重复标识/未知图版本提示诊断。删除支持应用前撤销，已应用修改进入 workspace 撤销历史。
- [x] `unit-graph-v1` 的冻结序列化子集已接入共享配置路径：精确版本引用、逐层 routing.mode、端口/顺序/条件、事件、waits、循环及并发约束均有字段级校验；未接入资源保持显式拒绝，不静默落到 R1。
- [x] 共享校验服务已验证嵌套图、组合与执行 DAG、接口读写、端口、事件三级作用域及条件深度；中间态可保存、冻结校验拒绝不支持结构。证据见 `tests/test_graph_validation.py` 与 graph runtime/service 专项。
- [x] `ExecutionService` 支持的图子集已接 G0→G1→G2、依据/margin、等待恢复与 timeout、持久 `cycle` 预留和事件优先级；SQLite 重开、等待唤醒、旧代隔离有专项覆盖。生产业务来源签发、周期关闭/新周期裁定和显式迁移仍未接入。
- [x] 并发托盘支持 `concurrent_config.max_units` 和 `load_scope.after/exclude`，可组合限制；改动写回同一草稿且保留未知元数据，坏结构保留原文。范围/端口同次应用，不能丢失排除条件。
- [x] 实际同轮召回/加载接口和诊断；默认关键词选择器只在已过滤闭集中排序，未命中不加载；可注入模型选择器。召回诊断不作发布 Gate。
- [x] 同轮加载适配器：先过滤 Unit/Skill 注册、load_scope 和片段有效性/主体，再向选择器提供摘要闭集；选中片段仍重验预算/有效性。无选择器不全量注入，异常选择不授予权限。主请求与主路由保持唯一，graph 模式工具权限和模型可见 Schema 限于版本与主 Skill 交集。
- [x] 事件属性与 `attempts/runs × 24h/forever` 条件构造器、受限正则字符串 `matches`、端口应用后撤销、任意稳定版/候选对比和画布差异叠加。未知条件保留 JSON；不支持窗口/算子不冻结。跨页面及历史快照查看保留未保存草稿。
- [ ] 完整条件算子与生产业务来源仍未完成：`changed_to` 因缺少「服务端签发、调用方不可自报」的可信 previous-value 来源，保持明确拒绝与诊断（`config_validation.py:33-39`），不能仅凭表达式启用；生产服务周期来源与键盘任务矩阵仍需继续。`matches` 当前仅支持有长度及复杂度上限的 regex，不等同于枚举/关键词模式。（2026-11-04 增量：服务周期生命周期 `close` / `adjudicate` / `migrate` 已实现并有 10 项专项，schema 升 v23 且补 `service_cycle_migrations` lineage 审计表，见 `tests/test_service_cycle_lifecycle.py`；`changed_to` 补 6 项反例与明确拒绝诊断；这不改变生产来源签发与 `changed_to` 算子缺口）

#### 草稿序列化首片（非可发布执行合同）

当前实现 `loomrise/graph_validation.py`，由既有 `validate_configuration` 按显式 discriminator 分派；缺少 discriminator 仍走 R1，未知值明确报错，不静默迁移。顶层为 `orchestration: {schema_version: "unit-graph-v1", kind: "graph", routing: {mode}, nodes, entry, edges, input_fields, on_event, fallback}`；节点为 `{id, unit_ref: {unit_id, version}}`，注册表沿用 `units`，每个 ID 只保存一个精确版本。

每条边为 `{id, from: "本层节点.出口", to: "本层节点.入口" | "self.出口" | "end", condition}`，**数组位置就是优先级**；`end` 只允许顶层。嵌套图的 `entry_ports[].goto` 固定映射本层子节点入口；嵌套 `body` 只包含 `kind/routing/nodes/edges`，不重复保存契约层的入口、事件或兜底。循环边额外声明 `max_rounds/exit/counter/window: "cycle"`。`say` 保留逐字原因并产出原文，`judge` 只写声明的布尔字段；`tool/speak` 未接入的资源解析与执行返回明确问题。

**当前硬边界**：支持的图、`say`/`judge`、边界事件、等待恢复、default_unit、非空文字 completion 判据和已声明 Skill 绑定可以冻结。本层 `llm/hybrid` 边允许正向模型叶，确定性表面仍拒绝。默认本机真实 Provider 已接入图路由、completion 与同轮召回；脚本回放不自动加载本机连接，缺 Provider 或未解析判据仍失败关闭。`tool`/`speak` 与未支持窗口按字段或 Atom 阻断。路由、生成和业务完成分别留证；闭集软提示与忽略审计均已实现并留候选摘要，不代表目标角色基线或真实模型质量。

### 3. WP5 完整客服

- [x] 联系页服务端：共享 revision 草稿保存、模板/受约束候选校验、预览、分享/停用、批准版本固定绑定；客服新会话同版本，入口换版不改变旧页。
- [x] 联系页工作台结构化块编辑、模板、排序/删除、共享 revision 保存/冲突保留、预览、批准入口查询/启用/停用与分享链接；不回退到 localStorage。
- [x] 21 类草稿块空态/编辑/保存/刷新/预览、19 类条目内容、媒体解码和基本增删排序；保留单块批准入口并补齐独立预置批准快照的 21 类公开渲染矩阵，不能据此称生产批准 Gate 通过。
- [x] 可选受约束 AI 起草与采用/单独保存边界、确定性浏览器联调和真实模型三块虚构首样本；生成不写草稿或发布。
- [ ] Contact 生成多样本/21 类输出质量、目标角色交互基线、治理层生产预检与完整客服矩阵验收。（2026-11-04 增量：本机完整批准/冻结/发布/版本绑定/公开只读/分享/停用/重启用路径已由 9 项端到端测试闭环，见 `tests/test_contact_approval.py`；治理层 `release.approve/publish` 仍因外部固定样例证据 fail-closed，不记为通过）
- [x] Inbox 本地接管辅助：从当前持久消息投影显示消息数与最近访客摘要；仅本人接管时可把通用确认草稿填入编辑框，仍需明确人工发送。浏览器检查覆盖未接管禁用、未提交不产生 `inbox.reply`、人工提交仍走原接口及 1440/390px 无溢出；不构成模型生成质量或 M-B-11 完成证据。
- [x] Widget 公开配置、语言/主题/时段、必填访客字段、访客历史与 Inbox 访客信息/人工往返；公开配置不泄露工具或 Prompt，旧会话固定版本。完整欢迎入口和渠道矩阵仍缺。
- [x] Widget 自动答复边界：版本范围内的 responder 生成 assistant 消息；无 responder 不自动回显，人工请求后停止自动答复，生成与访客/人工消息分别持久化。默认本机真实模型接待已有隔离 fixture 单样本，不能替代完整兼容性/质量验收。
- [x] Inbox 每坐席已读/未读、默认关闭的个人提醒偏好、页面开启时的浏览器提醒与五类提交状态保护；后端、独立 UI 审查与 1440/390px 浏览器联调通过，Notification 仅替身。
- [x] Inbox 使用 SQLite 有序脱敏事件日志、可续接 SSE、逐 consumer 应用确认；客户端先刷新投影再 ack，处理失败保持 durable cursor 并重放，服务端/浏览器 fixture 已覆盖。SSE reconnect 以应用确认游标恢复，不把 `Last-Event-ID` 当已应用或已读事实。
- [ ] OS Web Push/Telegram 通知送达回执、隐藏页生命周期及声明移动 WebView 平台真实运行证据；Notification 权限/显示替身与 loopback SSE 均不证明这些能力。
- [x] 物料简介候选：文本与可选原生 PDF 提取、本地图片 OCR 和纯扫描/混合 PDF 空文本页回退 OCR 均只生成待审核候选；缺工具/语言包或不支持格式明确失败关闭。简介候选与文件处理作业分开持久化，只有就绪且来源有效的候选可批准。文件产物不改变原件或自动发送权限；本机无 Tesseract，真实 OCR 仍未验证。
- [x] Telegram/Email 可测授权沙盒：授权/撤销、full/notify_only、线程 ID、消息去重、附件阻断和模拟送达事件；不打开网络连接，不把模拟送达当作真实 provider 证据。
- [x] 沙盒边界复核：连接按 tenant/agent 隔离，notify_only 拒绝内容，出入站方向分开、消息冲突/空 ID 拒绝、授权代次进入 dedupe；每条结果和事件明确 `environment: sandbox`。
- [ ] 真实 provider 凭据/回调验收。
- [x] 经审简介检索：只返回当前版本、已审就绪且授权有效的候选；换版、撤回、过期和拒绝审阅后停止检索；返回来源版本/哈希，不授予发送权。
- [x] 本地图片预览、视频转码和封面后处理，保留实际字节/哈希/尺寸/时长及处理版本。Inbox 可人工选择原件或派生文件，Widget 只可下载已发给本会话的具体文件，撤回与过期仍重验。
- [ ] 有 Tesseract/语言包环境的真实 OCR 质量、同页文字/图片混排区域处理、转写、多模态内容理解与完整媒体格式/平台矩阵；处理失败保留原件，不引入自动发送。
- [ ] 逐项对账客服覆盖矩阵，不以模拟成功替代服务端或渠道证据。

### 4. WP6 运行叠加与整体验证

- [x] 服务端按专家×版本×时间窗聚合实际 RunEvent；节点/边各自独立 Run 数 <30 时只计数。前端仅在稳定版本读取聚合，支持渠道、时间范围与关闭/计数/停留终止视图。
- [x] 节点执行耗时与终止测量合同：`graph-telemetry-v1` 只采 Unit body 本次解释器处理时段及样本数；嵌套父图耗时包含子图时段，挂起时间不计；终止数只接受完成路由中、先进入目标节点且引用最后有效步骤的层级证据。实际进入画布角标和 detail 说明，并用 SQLite RunEvent fixture 验证。
- [ ] 留存画布任务测试基线与对照；缺目标角色参与不宣称可用性通过。
- [x] 本轮 Python/JS/Canvas 构建与键盘、遥测、Contact Page fixture 回归；本地链接、Git diff、private 忽略及暂存区完成检查。
- [x] 同步 R3 计划、版本计划、路线和总索引；未实现项逐项保留，不能将本轮工件当作 R3 退出。

## 交接

当前范围见上方状态表。R2 快速验收跳过，R3 继续实施；下方历史记录中的“尚未”仅描述对应分片日期。其他会话的性能基线与文档改动继续保留。

### 2026-11-01 媒体产物交付与模型完成判据

- `material_derivatives.py` 使用本机 FFmpeg 8.1 生成真实 PNG 预览、MP4 转码与视频封面。输入限定已支持媒体类型，强制对应解复用器，不允许网络协议；输入/输出 10 MiB、图像 4000 万像素、视频 300 秒以及子进程超时均有上限。输出重新探测尺寸/时长并计算哈希；不保证每个文件都比原件小，也不报告虚构压缩率。
- SQLite schema v14 增加 `material_derivative_jobs`、`material_derivatives` 及消息的 `derivative_id`。处理与简介审阅分开。产物提交前重验原件版本、哈希、授权与有效期，处理中撤回会留下 discarded 作业且不保存文件。缺组件、解析失败和超时均不生成假文件，原件继续保留。
- `material.process` 的媒体工作在后台线程执行；`material.derivatives` 和 `material.derivative.download` 提供作用域内查询与下载。Inbox 人工发送将具体派生 ID 固定到消息；Widget 下载只允许该会话已接收的文件，发送派生文件不会连带公开原件。备份恢复、源换版、旧占用代次和撤回均有回归。
- `completion_evaluator(check, state)` 收到冻结 Unit/出口、文字判据、complete/incomplete 闭集及输入副本，不能修改运行事实。确定性完成条件先执行；返回分数、区分度和依据沿用 G1 校验，缺 Provider/未知选择/无效依据不放行。决策写 `route.graph.completion`，按判据和输入哈希缓存；等待快照可复用相同输入的已核验决策，坏缓存拒绝。当前验证使用注入 Provider，默认真实模型接线尚未完成。
- 媒体浏览器流程实际完成上传、FFmpeg 处理、选择派生文件、人工发送和浏览器下载，下载 PNG 实测为 1024×576。1440/390px 检查 pageerror 0。走查发现文件选择框把 390px 页面撑到 455px，按 adapt 调整为受限宽度和单列上传区，并将窄屏控件提升至 44px，复跑后无页面横向溢出；这不是最终整版 UI 验收。
- 复现：根目录运行 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8777 --seed-widget-release`，前端目录运行 `rtk proxy node tests/run-browser-check.js widget-material-browser-check.js`。截图在 `output/playwright/r3-media-inbox-{1440,390}.png`。处理和存储测试为 `tests/test_material_derivatives.py` 与 `tests/test_material_derivative_storage.py`，completion 合同测试为 `tests/test_graph_completion.py`。
- 集成验证：`rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q` **380 项通过**；前端 **273 项通过**，S1 自检通过。另复核图谓词边界，未知字段在冻结和运行时均拒绝，校验问题保持输入字段顺序。编解码样本为原创合成 PNG 和 MP4，含浏览器生成的 1280×720 图片；不能据此外推所有媒体格式或平台已验收。此轮环境为 Python 3.13.12、FFmpeg 8.1。

### 2026-11-01 图运行审查、版本比较与经审简介

- 图校验缺失 helper 导致的 `NameError` 已修。冻结检查覆盖 G0、嵌套 Unit 和边条件，只允许当前解释器支持的窗口、指标与算子。事件属性中的 `state/fact` 是数据，不再当作嵌套条件；缺失属性也不等于显式 null。`completion.llm` 尚未实现，冻结及运行时都明确拒绝。
- default_unit 已接入根图及嵌套图的本层跳转，无匹配边或完成出口时可进入默认单元。目标需通过同层端口和字段前提校验；回退计数受目标 `max_rounds` 限制，等待续接保留计数，耗尽后转人工，不重置为新预算。根图必需输入缺失仍失败关闭。LLM 路由只接收确定性条件已通过的边，模型选择不能绕过失败条件。
- 图 Unit 与深层 Unit 的等待现会挂起。快照保存执行位置、已计算事实、环计数和逐字输出游标；唤醒继续执行，避免重复已完成步骤。唤醒提交后、successor 创建前中断可显式恢复。取消等待重验租户、专家、版本与冻结配置。`say.text` 已进入输出和 `server_generated` 事件，不能据此称客户端已送达。后台调度与跨进程接管仍缺。
- `configuration.compare` 是同租户、同专家的只读比较，支持稳定版本与冻结候选任意组合。前端画布分别显示节点、端口、边和优先级变化，删除对象保留在原层级；右侧只读检视器展示前后值。字段明细默认收起，保留画布审阅空间。
- 草稿应用后的修改可跨分区撤销/重做，最多 100 步。保存、重读、冲突处理或切专家建立新历史边界。查看稳定版、候选和版本比较不覆盖草稿，返回同专家工作面也不自动重读丢弃输入。坏 JSON 保留原文，重读未保存内容需在页面明确选择舍弃。
- 渠道缓存改用 tuple，去重键使用 canonical JSON，消除分隔符碰撞。SQLite 事务内递增授权代次、重验撤销并同时写消息与事件；重启后的入站/出站重复结果都保留 sandbox 标记，同 ID 内容冲突拒绝。`channel_webhook` 仍只是已签名沙盒 envelope，不代表真实供应商回调验收。
- `material.process` 现在需要写权限。`material.search` 只检索经审、当前、有效的简介，并返回候选、版本及来源哈希；摘要仅用于选择物料。审批时重验处理完成及当前原件，过期或陈旧候选不可批准。
- 2026-11-01 集成验证：Python 以 `ResourceWarning` 为错误运行 **363 项通过**；前端 **273 项通过**；S1 自检通过。`orchestration-diff-browser-check.js` 验证事件属性与窗口保存/刷新；`orchestration-history-browser-check.js` 验证应用后撤销、跨页保留、只读比较、端口/删除边及退出比较恢复输入。两种视窗为 1440px 和 390px，页面无横向溢出、pageerror 0；仍是开发中的专项检查。

复现版本比较：静态预览 18765；根目录运行 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8783 --allowed-origin http://127.0.0.1:18765`，前端目录运行 `rtk proxy node tests/run-browser-check.js orchestration-history-browser-check.js`。截图在忽略目录 `output/playwright/r3-version-comparison-{1440,390}.png`。测试使用原创虚构配置与临时 SQLite。当前未完成项见本文件首节，开发完成后的最终 UI 走查仍待执行。

### 2026-11-01 同轮加载与联系页工作台

- `loomrise/concurrent_loading.py` 及 `ContextLedger.stage_concurrent` 接入 `ExecutionService`。同步/异步 `concurrent_selector` 只能返回摘要闭集中的 Unit ID；组级数量与 token 预算分别限制加载。无选择器不全量注入，过期或主体不匹配的片段在选择前过滤，加载时再校验；异步取消终止 Run 并留取消确认。该接口尚未接默认模型召回 Provider，不宣称 WP3 全部完成。
- graph 模式的 ToolPolicy 和模型可见工具改为 AgentVersion × 主 Skill 的交集；召回补充 Skill 不扩权。主 Skill 绑定也必须在冻结版本名单内且唯一，不能只凭 pack 中存在就使用。对应 `tests/test_concurrent_runtime.py` / `tests/test_graph_service.py` 验证主请求唯一、数量/token 上限、过期与范围过滤、无效选择、取消及隐藏工具零写入。
- `contact-workspace.js` / `views/contact-service.js` 已用于实际 `contact` 路由：按服务端 Schema 编辑 21 类块及条目、模板、排序/删除、共享 revision 保存、预览和入口启停。保存防重入，跨专家迟到响应不回写，冲突保留输入；空坏结构和未知 Schema 不静默转换。页面顶栏使用实际服务端保存状态，媒体类型为中文选项。
- 联系页启用携带 `expected_version_id`，同一事务重验批准入口版本，漂移则拒绝；草稿保存不改变已启用页面。工作台可打开分享地址并停用。完整生成调用与逐块交互矩阵仍未完成，服务仍仅回环监听。
- `contact-editor-browser-check.js` 对临时 SQLite 验证保存→刷新→已保存预览、显式启用批准版（内容保持旧冻结版）→分享→停用 404、revision 冲突保留输入；1440/390px 无页面横向溢出，pageerror 0。HTTP 404（尚未启用）和 409（主动制造冲突）为预期响应，不称 console 0。
- 集成回归：后端 ResourceWarning 作为错误运行，**303 项通过**；graph/并发/Widget/渠道/物料专项通过。前端 `rtk proxy npm test` **262 项通过**，画布构建和 `tests/test_s1.py` 自检通过。此前 SQLite 告警经 `PYTHONTRACEMALLOC=5` 定位到 `tests/test_durable_store.py` 的测试连接未关闭，使用 `closing` 后专项及全量通过；不是通过压制告警修复。

复现联系页：静态预览 18765；根目录运行 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8778 --allowed-origin http://127.0.0.1:18765 --seed-contact-release`，前端目录运行 `rtk proxy env CONFIGURATION_TEST_API=http://127.0.0.1:8778 node tests/run-browser-check.js contact-editor-browser-check.js`。fixture 标志仅在测试中预置批准记录，不证明发布前检查已通过。截图在忽略目录 `output/playwright/r3-contact-editor-{1440,390}.png`。

### 2026-11-01 UI 走查与当前证据

- Impeccable detector 对画布、运行叠加、联系页、Widget、Inbox 目标返回空结果；此前侧边提示条的粗色边框已收为 1px 细线。视觉检查覆盖服务端联系页工作台、1440/390 画布、1440/390 Widget，并修复了画布测试入口 favicon 404、联系页旧“已自动保存”文案和窄屏画布节点裁切。
- 代表浏览器路径：`contact-editor-browser-check.js`（服务端草稿保存、刷新、预览、批准版启用/分享/停用、revision 冲突；预期 404/409 响应只表示尚未启用/主动制造冲突）；`orchestration-nested-browser-check.js`（并发组合范围、下钻、端口/边/优先级和窄屏）；`orchestration-overlay-browser-check.js`（SQLite 实际 RunEvent 2/1 次、层级计数、低样本和关闭图层）；`widget-configuration-browser-check.js`（访客必填、版本固定会话、历史、Inbox 人工往返、1440/390）。
- 当前新鲜回归：后端 ResourceWarning 作为错误 **303 项通过**；前端 **262 项通过**；画布构建通过；S1 自检通过；链接/锚点检查覆盖 290 个本地链接，0 个断链；检测器空结果；`git diff --check` 通过、`private/` ignored、暂存区为空。
- UI 走查结束后仍不能关闭 R3：真实 provider 回调/AI 模型接待、完整客服能力矩阵、默认模型召回、节点停留/终止独立测量、真人角色任务基线和未完成条件/任意版本 diff 仍是明确缺口。

### 2026-10-31 并行开发与复核

- 并发配置：`tests/test_concurrent_units.py`、前端 `orchestration-concurrent*.test.js` 验证组级正整数上限、路由 Unit 范围引用、组合条件保持、坏结构修复及只读保护。字段细化为根 `concurrent_config: {max_units}`、单条可选 `load_scope: {after?, exclude?}`；省略 scope 表示候选全池，仍不得全量注入、扩大权限或同时推进多个主请求。
- 运行计数：`loomrise/run_overlay.py` / `SqliteStore.read_graph_overlay` / `run.overlay` 返回 `run-overlay-v1`，键为 `JSON.stringify([...layer, localId])`。按 started 的记录时刻选择 `[from,to)` 整段调用，循环访问数与独立 Run 覆盖率分开；不合并不同层同名节点，不制造超过 100% 的覆盖率。没有 `snapshot.agent_id` 的历史运行不推断归属；执行服务可由可信调用方设置 `agent_id`。`tests/test_run_overlay.py` 与 `tests/test_run_agent_scope.py` 覆盖授权隔离、时间偏移、低样本、坏事件和当前执行器真实轨迹。
- 联系页：`loomrise/contact_pages.py`、`customer_contact.html` 与 `contact.*` 用例提供模板、21 类块的受约束数据/渲染、候选校验、共享草稿保存和预览；公开响应不返回完整 Agent 配置。启停仅 owner，知识撤回/缺审批拒绝公开访问和新会话，停用可重试。`contact.open` 固定版本并复用原 Widget/Inbox；已有线程不因页面停用而被撤销。schema v13 增加联系页绑定、访客字段、渠道沙盒状态和物料处理候选；`tests/test_contact_page.py` 覆盖备份恢复、入口换版、权限、脚本/链接和错误内容。
- 工具 Atom：`route.graph.diagnostic` 区分未冻结引用、坏 Manifest、非法参数及执行未接入；`tests/test_tool_atom_boundary.py` 验证零工具调用/零结果 ID。该拒绝边界不算真实工具执行。
- 浏览器：`orchestration-overlay-browser-check.js` 使用 `tests/r3_overlay_http_fixture.py` 临时 SQLite 与实际脚本执行服务，验证总 2 次、语音 1 次、嵌套计数、稳定版只读与图层关闭；1440/390px 无页面横溢出。缩窄画布后自动适应容器，解决节点被裁切；截图为本地 `output/playwright/r3-overlay-canvas-{1440,390}.png`。fixture 从 storage 层导入测试图，仅用于观察器联调，不是公开冻结 Gate 已通过的证据。
- 嵌套浏览器回归：`orchestration-nested-browser-check.js` 验证 combined scope 应用后仍保留 after/exclude，concurrent 不进图；已有端口/边/优先级/下钻与窄屏检查通过。功能测试不替代 R3 完成后的整轮 UI 走查或真人角色任务基线。

复现运行叠加：静态预览沿用端口 18765；根目录运行 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r3_overlay_http_fixture.py --port 8779`，前端目录运行 `rtk proxy node tests/run-browser-check.js orchestration-overlay-browser-check.js`。测试库和身份文件均在临时目录，不触达生产。

本批集成验证：`rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q` **272 项通过**；前端 `rtk proxy npm test` **252 项通过**，`rtk proxy npm run build:canvas` 通过。后端仍出现既有 SQLite 未关闭连接 `ResourceWarning`，不宣称零告警。设计检测仅报既有提示条粗边框，已收为细线；没有将机械检查当作完整体验验收。Git diff 空白检查通过、`private/` 保持忽略、暂存区为空。

2026-10-30 验证：

- `rtk proxy npm ci`（在 `prototypes/console-next` 执行）：锁定安装与 postinstall 的本地画布构建通过，npm audit 0 vulnerabilities。
- `rtk proxy npm test`：223/223 通过（原 218 项 + `tests/orchestration.test.js` 的 5 项）；新增断言覆盖候选集合语义、端口身份、并发/事件分离、坏草稿/歧义目标、同草稿写回/未知字段保留、只读/冲突/忙碌/非法 JSON 保护。
- `tests/orchestration-browser-check.js`：本机真实浏览器与 SQLite fixture 验证 2 单元/1 候选边、清单→图选中态、检视器修改→保存→刷新值为 4、候选冻结后只读；1440/390 宽无页面横向溢出，page errors 0。截图在忽略目录 `output/playwright/r3-canvas-{desktop,mobile}.png`；截图不代表嵌套或真实渠道验收。

复现浏览器检查：先在仓库根启动 `rtk proxy python3 -m http.server 18765 --bind 127.0.0.1 --directory prototypes/console-next`；另一终端运行 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8766 --allowed-origin http://127.0.0.1:18765`。在 `prototypes/console-next` 执行 `rtk npm run test:orchestration`。fixture 使用临时虚构数据，不连接生产系统。

首片交接边界：R1 `exits` 的顺序不是 `edge_order`，连线明确为“候选出口”，不能推断出执行顺序；第二片显式图按 `edges` 数组顺序展示编号。R1 非 graph 的 body/concurrent 冻结限制仍保留；支持子集图已接入独立执行和冻结，但 `tool`/`speak` 仍拒绝。未实现、未验证项继续保留步骤 2–4 清单。

第二片验证（2026-10-30）：

- `rtk proxy .venv/bin/python -m unittest tests.test_graph_validation tests.test_config_validation tests.test_configuration_service`：45 项通过，其中新增 13 项覆盖嵌套、冻结阻断、SQLite 重启恢复、版本不匹配/布尔版本、非法跨层、组合环/执行环/孤立环、事件逃逸、接口隐瞒和坏 JSON。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：本轮早期快照 180 项通过；全量数量随 R3 增量更新，见本节最新记录。出现既有 SQLite `ResourceWarning`，未宣称无告警。
- `rtk proxy .venv/bin/python tests/test_s1.py`：自检全部通过；依赖不含 pytest，未添加新测试框架。
- `rtk proxy npm test`：226/226 通过；`rtk proxy npm run build:canvas` 通过。新增前端测试覆盖精确图分层、注册表同源、真实边顺序、重复实例、坏引用、失效下钻路径与组合环保护。
- `rtk proxy node tests/run-browser-check.js orchestration-nested-browser-check.js`（`prototypes/console-next`）：真实浏览器验证根层→子层→根层、图/清单共享选中、端口终点与实际边、1440/390 无页面横向溢出，page errors 0。此检查使用独立组件 fixture，不作为 SQLite 端到端运行证据。端口边需等待 React Flow 测量完成后断言。

下一片优先把 Atom/等待/边界事件映射进同一 `ExecutionService` Run 状态，补可恢复等待、持久 cycle 计数、取消/恢复和工具结果对账；图路由与旧 Skill 路由的唯一映射已通过 `unit_skill_bindings` 落下。新图冻结阻断继续保留。下钻已完成，结构化边/端口编辑、对象级 diff 与完整客服仍未完成。

第三片验证（2026-10-30）：

- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime tests.test_graph_validation`：22 项通过；覆盖嵌套轨迹、G0 优先、边界事件优先、精确 Unit 版本、确定性条件、闭集选择、margin/evidence 拒绝和 G2 fallback。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime`：23 项通过；新增验证路由轨迹通过当前 Run-scoped emitter 写入哈希链，且不产生业务结果 ID。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_service`：5 项通过；验证版本图不调用关键词路由、快照绑定、服务端 routing state、G0/G1 失败关闭和旧版本兼容。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_service`：3 项通过；验证图版本不调用关键词路由、绑定缺失失败关闭、路由事件进入同一 Run 账本，旧版本仍保持关键词路由。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime`：11 项通过；新增覆盖根图/嵌套图 `judge` true/false 分支、结果字段声明、输入态隔离与父图读取派生事实。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_service tests.test_graph_runtime`：17 项通过；另验证 ExecutionService 中 judge 派生字段可作为 G1 selector 的 evidence。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：上一片 186 项通过；本片新增等待合同/运行用例后，最新数量见下方记录；仍出现既有 SQLite `ResourceWarning`。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_validation tests.test_graph_runtime`：30 项通过；覆盖 waits 合同、等待元数据、事件满足后继续、嵌套等待与旧 Unit 兼容。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_service tests.test_graph_runtime tests.test_graph_validation`：37 项通过；新增 ExecutionService 等待缺口的明确失败关闭证据。
- `rtk proxy npm test`（`prototypes/console-next`）：227/227 通过；新增等待编辑写回、超时覆盖边、嵌套 `self.*` 目标与未知目标诊断。
- `rtk proxy npm run build:canvas`（`prototypes/console-next`）：画布构建通过。
- `rtk proxy npm test`（`prototypes/console-next`）：228/228 通过；新增闭集阈值分档、强提示与并发排除测试。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime tests.test_graph_service tests.test_graph_validation`：40 项通过；覆盖根/嵌套受限边计数、超限 exit、前序快照注入、非法计数拒绝与 RunEvent 链留痕。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime tests.test_graph_service tests.test_graph_validation`：入口校验补齐后 43 项通过；覆盖根输入、顶层/嵌套 requires、空值拒绝与服务层失败关闭。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：192 项通过；仍出现既有 SQLite `ResourceWarning`。
- `rtk proxy .venv/bin/python tests/test_s1.py`：S1 全部自检通过，包括固定案例、文字/语音共用请求、HTTP/SSE 与取消证据。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：入口前提运行时集成后 195 项通过；仍出现既有 SQLite `ResourceWarning`。
- `rtk proxy .venv/bin/python tests/test_s1.py`：入口前提改动后 S1 全部自检仍通过。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：本片早期 188 项通过；新增服务等待缺口测试后最新数量见下方记录；仍出现既有 SQLite `ResourceWarning`。
- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：189 项通过；仍出现既有 SQLite `ResourceWarning`。

第四片验证（2026-10-31）：

- `rtk .venv/bin/python -m unittest tests.test_graph_runtime -v`：22 项通过；新增原子 Unit `self` 事件短路、条件不匹配继续等待、根 `global` 优先、嵌套原子事件层级轨迹四项覆盖。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：199 项通过；仍出现既有 SQLite `ResourceWarning`。
- `rtk .venv/bin/python tests/test_s1.py`：S1 自检全部通过。
- `rtk git diff --check`、`rtk git check-ignore -v private/` 通过；`rtk git diff --cached --name-only` 为空，未暂存文件。
- 事件范围：`self` 已覆盖顶层图 Unit 与原子 Unit、嵌套原子 Unit；图形 Unit 的递归子树事件和 `subtree` scope 尚未实现，不得据此称三级作用域完成。

第五片验证（2026-10-31）：

- `rtk .venv/bin/python -m unittest tests.test_graph_runtime`：29 项通过；新增递归图执行、嵌套 `subtree` 条件重评与向声明层冒泡/兄弟节点跳转、全局事件消费一次、图 Unit 出口 completion 正/反路径检查。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：206 项通过；仍出现既有 SQLite `ResourceWarning`。
- `rtk .venv/bin/python tests/test_s1.py`：S1 自检全部通过。
- `rtk npm test`（`prototypes/console-next`）：228/228 通过；`rtk npm run build:canvas` 通过。
- `rtk git diff --check`、`rtk git check-ignore -v private/` 通过；`rtk git diff --cached --name-only` 为空，未暂存文件。
- 本片只证明纯路由器的递归图、boundary event 和出口 completion 语义，不代表 ExecutionService 已支持工具/语音副作用、持久等待/恢复、跨服务周期计数或可发布冻结。

第六片验证（2026-10-31）：

- `rtk npm test`（`prototypes/console-next`）：230/230 通过；新增嵌套边写回、优先级数组调整、非法索引与白名单/只读保护测试，保存沿用 revision 合同且保留未知配置。
- `rtk npm run build:canvas`：通过。
- `rtk proxy node tests/run-browser-check.js orchestration-nested-browser-check.js`：真实浏览器使用实际工作区方法验证嵌套边条件/执行环写回、顺序调整后清单重绘、1440/390 无页面横向溢出和 390px 边检视器不交叠，page errors 0。此为独立组件 fixture，未据此声称 SQLite 保存刷新验证或角色任务验收通过。
- `frontend-design` 技能用于本轮检查器渐进披露与响应式交互；沿用已确认工作台视觉系统，不增加外部字体或新主题。
- 剩余：边新增/删除、端口结构化表单、条件表达式表单、对象级 diff；持久等待/恢复等执行缺口仍见上文。

第七片验证（2026-10-31）：

- `rtk npm test`（`prototypes/console-next`）：231/231 通过；专项 `rtk proxy node --test tests/orchestration.test.js`：13/13 通过。新增/删除/撤销覆盖嵌套注册表写回、重复 ID、本层端口/跨层拒绝、只读与忙碌保护、撤销拒绝覆盖后续边变更。
- `rtk npm run build:canvas`：通过。
- `rtk proxy node tests/run-browser-check.js orchestration-nested-browser-check.js`：实际工作区方法的真实浏览器 fixture 完成新增至末尾→删除→撤销并恢复原位置；既有编辑/顺序重绘与 1440/390 布局仍通过，page errors 0。没有连接 SQLite 保存端点，不声明持久化刷新或角色任务验收。
- 剩余：端口结构化表单、条件表达式表单、对象级 diff、完整客服与运行持久化等；R3 Gate 保持未通过。

第八片验证（2026-10-31）：

- `rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：211 项通过；新增稳定标识对齐、边优先级、嵌套端口/边/节点、缺失/重复标识降级、端口增删、未知数组顺序保留和既有边新增字段仍属于修改的验证。SQLite 重启后候选对象差异与冻结时一致，列表/详情/幂等冻结返回一致；既有 SQLite `ResourceWarning` 仍有。
- `rtk npm test`（`prototypes/console-next`）：232/232 通过；新增保存/候选比较基准、未保存修改提示、HTML 转义、null/false 与刷新回执失效验证。`rtk npm run build:canvas` 通过；`rtk proxy .venv/bin/python tests/test_s1.py` 全部通过。
- `rtk proxy node tests/run-browser-check.js orchestration-diff-browser-check.js`：真实浏览器连接独立 SQLite fixture，完成边优先级调整→保存回执仅有优先级项→条件编辑→未保存提示→保存显示边修改→刷新核对持久值；1440/390px 无横向溢出，page errors 0。截图 `output/playwright/r3-object-diff-mobile.png` 属本地忽略工件。
- 复现：沿用 18765 静态预览，另启动 `rtk proxy env PYTHONPATH=. .venv/bin/python tests/r1_configuration_http_fixture.py --port 8767 --allowed-origin http://127.0.0.1:18765`，再运行上述浏览器命令。fixture 使用虚构数据；不连接真实业务渠道。
- API 新增 `object_diff: {changes, diagnostics}` 审阅投影，`path` 中的稳定标识选择器用于阅读，不是 patch JSON path；原 `diff` 仍是字段路径权威。保存回执不持久化，刷新后不伪造“最近保存”；候选投影由不可变候选与基准快照重算，不改审批状态或内容哈希。
- 剩余：端口/条件表单、任意版本对比/画布叠加、完整客服、持久等待/恢复、工具/语音 Atom、cycle 恢复等；图冻结阻断和 R3 Gate 保持不变。

第九片验证（2026-10-31）：

- `rtk npm test`（`prototypes/console-next`）：235/235 通过；新增端口表单序列化、未知元数据保留、原数据不变、重复/跨层标识拒绝、坏结构/旧条件原文修复和判据组合验证。`rtk npm run build:canvas` 通过。本片没有改 Python，不重复计算上一片 211 项为新增验证。
- `rtk proxy node tests/run-browser-check.js orchestration-nested-browser-check.js`：嵌套图 Unit 新增入口/出口、配置 `requires/goto` 与模型判据、应用后删除端口均写回同一注册表；原有边编辑、创建/删除/撤销、下钻和窄屏布局仍通过，page errors 0。此检查仍是独立组件 fixture。
- `rtk proxy node tests/run-browser-check.js orchestration-diff-browser-check.js`：使用 8767 独立 SQLite fixture，验证表单修改→保存→端口级差异→刷新核对 `requires`/`completion` 和未知元数据；非法完成条件不写入共享草稿，原子单元增加端口按钮禁用。1440/390px 检查通过，page errors 0；本地截图 `output/playwright/r3-port-editor-mobile.png`。
- R1 兼容回归使用另一个全新 fixture，启动命令同上文但端口改为 8768；执行 `rtk proxy env CONFIGURATION_TEST_API=http://127.0.0.1:8768 node tests/run-browser-check.js orchestration-browser-check.js`。回归保存/刷新、R1 候选冻结及端口标识/完成判据只读。测试运行器为 diff 单独分配浏览器 session，并允许显式选择本机 fixture，避免其他运行遗留的图草稿污染 R1 检查；未覆盖或重置其他 fixture 的草稿。
- `frontend-design` 用于沿用已确认的浅色紧凑检查器、端口分组与窄屏纵排；确定性条件与模型判据分别呈现，借鉴 ElevenLabs 检查器的渐进披露，不把概率判据伪装成确定性规则。端口变更不会新增工具权限或解除冻结阻断。
- 剩余：端口引用影响精确清单、条件表达式构造器、端口删除撤销、任意版本对比/画布叠加，以及步骤 2–4 的执行与完整客服缺口。R3 仍实施中。

第十片验证（2026-10-31）：

- `rtk npm test`（`prototypes/console-next`）：238/238 通过；`rtk npm run build:canvas` 通过。新增条件序列化测试覆盖带类型字面值、组合/别名往返、深度限制、不完整输入拒绝与未知结构保留。未修改 Python，上一片 211 项不是本片重跑。
- 三个画布浏览器检查均通过，page errors 0：nested 为独立组件 fixture；diff 使用 8767 独立 SQLite，验证字段/两层组合构造→保存→刷新、布尔与列表类型保持、确定性 completion 与模型判据共存；R1 使用 8768 fixture 回归候选只读。支持 say/judge/wait 的图冻结不再被 blanket `graph_runtime_unavailable` 阻断，tool/speak 仍按 Atom 级 issue 拒绝。
- 修复边提交的空字符串 fallback：未完成构造器不能被 `|| '{}'` 静默转为无条件边；原 JSON 模式切换也不能丢弃未完成输入。1440/390px 无页面横向溢出；本地截图 `output/playwright/r3-condition-builder-mobile.png`。
- `frontend-design` 用于沿用同一检查器的字段/判据分组、嵌套缩进与窄屏纵排，借鉴 ElevenLabs 的渐进披露，保留 Loomrise 服务端裁决。事件/状态/模型叶构造器、任意版本对比及运行缺口仍未完成。

第十一片范围（2026-10-31）：

- 新增 `orchestration/port-references.js`，仅检查已识别合同中的目标字段，按精确 Unit 版本解析各层节点实例；结果是只读影响清单，不是级联 patch。重复标识和未知 schema 明确诊断；不在 prompt/条件字符串中搜索或猜测引用。等待目标仅按当前画布支持的 `self.出口` 检查，不把节点级 timeoutTo 当入口端口。
- 端口删除支持应用前撤销，同组后续编辑清除旧撤销；行使用独立表单身份，删除前行不复用后行条件组件。应用后的撤销、未完成条件树的完整恢复仍待完善。
- `rtk npm test`：241/241 通过；新增三项覆盖多实例/嵌套/自身出口、循环出口/事件/兜底/超时、版本不匹配/标识歧义、R1 和未知 schema。`rtk npm run build:canvas` 通过；diff 和 R1 SQLite 浏览器回归通过，page errors 0。
- `rtk proxy node tests/run-browser-check.js orchestration-nested-browser-check.js`：改名预览列出根入口/父边/自身出口的准确路径且未提前改写草稿；恢复名字清除影响、删除首行保留后行判据、撤销恢复位置、同组后续编辑清除旧撤销均通过。补齐独立测试页的工作台基础样式并等待样式加载后重跑；1440/390px 布局通过，page errors 0。该 fixture 不连接 SQLite；手机截图 `output/playwright/r3-port-impact-mobile.png` 已人工查看。
- 三份修改文档的 169 个本地链接目标存在；索引版本/用途同步。`rtk git diff --check` 通过，`private/` 仍忽略，暂存区为空；保留其他会话的性能与文档改动。本片未修改或重跑 Python。
- 下一步：完善端口应用后撤销与事件/状态条件编辑，推进任意版本对比/画布差异；执行工作仍须补齐持久 wait/timeout、工具/语音 Atom、cycle 恢复及取消证据。完整客服与目标角色验收保留未完成，图冻结继续阻断。

第十二片范围与验证（2026-10-31）：

- 条件表单新增已知事件名称，支持与字段/组合条件混用；旧单元素列表 `not` 可进入构造器，往返保留原算子。未知事件、带工具/参数的事件属性、状态窗口和模型叶继续原 JSON。不能据此声称工具/渠道事件源已接入，也没有新增状态窗口运行能力。
- 按 `systematic-debugging` 与 `test-driven-development` 先复现否定语义和未支持条件的错误，再修复解释器。`not` 与 `none_of` 共用单子条件列表解释；布尔短路前检查完整树。未接入状态窗口、未知谓词/算子、事件属性及错误的比较字面值明确报错，不作为布尔值参与否定；模型叶不能直接通过确定性边或用于否定，正向 hybrid/llm 闭集仍走 selector 验证。
- `rtk proxy .venv/bin/python -m unittest tests.test_graph_runtime tests.test_graph_service tests.test_graph_validation`：60 项通过，覆盖边/判断 Atom 的否定、事件名称匹配、不支持条件在 G0/事件/completion/边上停止，以及服务端失败清理/零写入和哈希链。`rtk proxy .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：217 项通过；仍有既有 SQLite `ResourceWarning`。`rtk proxy .venv/bin/python tests/test_s1.py` 全部通过。
- `rtk npm test`：242/242 通过；`rtk npm run build:canvas` 通过。条件测试新增全部已知事件与旧 not 往返、事件属性/状态原文保留和未选事件拒绝。
- 三个浏览器检查通过，page errors 0：diff 使用 8767 SQLite 验证字段/两层组合/事件名称构造→保存→刷新、旧 not 不被改写、未选事件不能应用；共享校验仅剩图运行冻结阻断。nested 复验下钻、边/端口编辑和撤销；8768 的 R1 检查验证事件完成条件被冻结后下拉框只读。1440/390px 无横向溢出，本地截图 `output/playwright/r3-condition-builder-mobile.png`。
- 复现命令沿用前述三项浏览器检查；8767/8768 均为虚构临时 SQLite，不涉及生产。保留完整 R3 未完成项，后续优先恢复型等待/timeout 与持久 cycle；事件属性/状态窗口运行、完整算子/模型 completion 裁决仍需继续审计和实现，不能只移除冻结阻断。

第十三片范围与验证（2026-10-31）：

- `loomrise/durable_store.py` 新增 `run_waits` 持久表及原子 `suspend_wait` / `wake_wait`：等待目标、超时去向、generation、路由快照与 cycle 计数同一事务落库；唤醒只允许一次，租户、AgentVersion 与 generation 不匹配时拒绝，旧 waiting Run 标记为 `wake_superseded`。
- `loomrise/durable_adapter.py` 增加等待查询、挂起和唤醒边界；`RunStatus.WAITING` 与 `RequestState.WAITING` 只表示执行暂停，不表示业务完成。
- `ExecutionService` 的图路由 waiting 分支已接入 durable store；新增 `wake_waiting_request`，事件唤醒会创建新的 successor Run，沿用原请求 lineage 并注入事件状态。无 durable store 的旧路径仍保留明确失败关闭。
- `rtk .venv/bin/python -m unittest tests.test_durable_waiting tests.test_graph_service tests.test_durable_store tests.test_durable_recovery -q`：44 项通过；仍有既有 SQLite `ResourceWarning`。
- 独立脚本验证 waiting → wake → successor success，确认旧 Run 为 `wake_superseded`，事件唤醒不重复执行旧代。未据此宣称跨进程 Worker handoff、timeout 调度器、工具/语音 Atom 或真实业务副作用已完成；R3 Gate 继续未通过。

第十四片范围与验证（2026-10-31）：

- `wake_wait` 现在区分事件唤醒与超时唤醒：超时唤醒必须存在 `timeoutMs` 且已达到截止时间，未到期或没有 timeout 声明均拒绝；租户、AgentVersion、generation 和单次消费约束继续生效。
- successor Run 恢复等待时保存的 `routing_state` 与 `cycle_counters`；图解释器支持显式 `timeoutTo` 分支，超时路径可通过声明的 `self.*` 出口或 `end` 完成，并留下 `wait_timeout` 路由轨迹。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`：220 项通过；仍有既有 SQLite `ResourceWarning`。
- 当前闭环仍是本地 SQLite 单写者语义；没有自动 timeout 调度器、跨进程 Worker handoff、工具/语音 Atom、未知外部结果对账或完整客服验收，R3 Gate 保持未通过。

第十五片范围与验证（2026-10-31）：

- 等待生命周期补齐取消路径：parked Run 可在没有活动 asyncio task 时由 `ExecutionService.cancel` 终止，`run.cancel_requested` 与 `run.cancel_confirmed` 和 waiting 状态更新同一 SQLite 事务提交；取消后的 wait 不可再次 wake。
- `SqliteStore.due_waits` / `DurableRunAdapter.due_waits` 提供只读到期等待查询，作为后续调度器接入点；本片不伪装成后台 scheduler。
- `rtk .venv/bin/python -m unittest tests.test_durable_waiting tests.test_graph_service tests.test_durable_recovery -q`：26 项通过；此前全量 220 项通过，新增取消/到期查询后需再跑全量。
- 仍未实现自动 timeout scheduler、跨进程 Worker handoff、工具/语音 Atom、未知外部结果对账和完整客服验收；R3 Gate 保持未通过。

第十六片范围与验证（2026-10-31）：

- 修复 `wake_waiting_request(wake_kind="timeout")` 的恢复分支：超时唤醒现在确实把 `__wait_timeout_to` 传入图解释器，不再误走普通重启恢复路径。
- 新增 `ExecutionService.wake_due_waits()`：按 `due_waits()` 查询结果逐个消费到期等待；它是调度器调用接口，不在本片声称已有后台 scheduler。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`：222 项通过；仍有既有 SQLite `ResourceWarning`。
- 端到端测试验证 `waiting → timeout wake → timeoutTo → successor success`，并确认原等待记录为 `woken`。跨进程 Worker handoff、真正的后台调度、工具/语音 Atom、未知外部结果对账和完整客服验收仍未完成，R3 Gate 保持未通过。

第十七片范围与验证（2026-10-31）：

- 事件唤醒与超时唤醒现在在 parked Run 的事件链中写入 `run.wait_woken`，与 waiting 状态消费、旧 Run fencing、请求重新排队同一 SQLite 事务提交；恢复后可直接审计唤醒原因和 generation。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`：222 项通过；仍有既有 SQLite `ResourceWarning`。
- 本片没有扩大业务完成语义：`run.wait_woken` 只是执行证据，successor Run 仍须重新经过版本、权限、条件和业务结果裁决。后台 timeout scheduler、跨进程 Worker handoff、工具/语音 Atom、未知外部结果对账和完整客服验收仍未完成，R3 Gate 保持未通过。

第十八片范围与验证（2026-10-31）：

- `wake_due_waits()` 对调度竞态做幂等处理：多个调用者读取同一 due wait 时，只有第一个能消费 waiting 记录并创建 successor；后续调用安全跳过已唤醒记录，不重复执行。
- 新增端到端测试验证同一等待被两次 scheduler 调用时只产生一个 successor Run；`run.wait_woken` 仍保留为旧 Run 的事务审计事件。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`：223 项通过；仍有既有 SQLite `ResourceWarning`。
- 本片仍未实现后台调度进程、跨进程 Worker handoff、工具/语音 Atom、未知外部结果对账和完整客服验收，R3 Gate 保持未通过。

第十九片范围与验证（2026-10-31）：

- 图运行时对 `say` 原子增加运行时保存前同构校验：缺失 `verbatim_reason` 时失败关闭；逐字话术继续不进入模型生成路径。
- `tool` / `speak` 仍由结构校验明确标记为资源解析未接入，本片没有绕过权限与工具合同伪造执行；后续需接入真实 `ToolPolicy`、幂等副作用和语音发送/播放账本后才能放开。
- `rtk .venv/bin/python -m unittest tests.test_graph_runtime tests.test_graph_validation tests.test_graph_service -q`：62 项通过；全量回归待本片结束后重跑。

第二十片范围与验证（2026-10-31）：

- `tool` 原子草稿现在接受显式 `tool_ref: {tool_id, version}` 形状，并对场景包顶层 `ToolManifest` 做唯一且精确的 ID+版本匹配；缺失、版本漂移、重复或格式错误都会给出 `unfrozen_tool_reference`。
- 参数必须是对象；资源引用通过后仍保留 `unsupported_graph_atom`，因为真实 ToolPolicy、参数 Schema、确认、幂等写入和未知结果对账尚未接入。没有把结构校验伪装成可执行能力。
- `rtk .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q`：226 项通过；仍有既有 SQLite `ResourceWarning`。
- 该片只完成资源引用合同与拒绝边界，`tool` / `speak` 执行、跨进程 Worker handoff、完整客服验收仍未完成，R3 Gate 保持未通过。

第二十一片范围与验证（2026-10-31）：

- 画布节点和单元检视器增加内容层摘要：`tool_ref` 显示工具 ID 与冻结版本，未冻结引用、`speak`、`say`、`judge`、子图分别显示明确状态；不把资源摘要写入坐标或另建配置真相。
- 前端继续沿用 ElevenLabs 式“节点摘要 + 右侧检查器 + 原文修复路径”的渐进披露，资源版本漂移风险在图与检视器两处可见。
- `rtk npm test`：242 项通过；`rtk npm run build:canvas` 通过。
- 本片只改善可审阅性与合同可见性，未宣称 `tool` / `speak` 已执行；R3 的真实工具、语音、客服和角色任务验收仍未完成。

第二十二片范围与验证（2026-10-31）：

- 工具原子检视器增加结构化 `tool_id` / `version` 编辑，提交时只更新 `body.tool_ref` 并保留其他未知 body 字段；保存草稿仍不授予执行权限。
- 检视器提示明确区分“冻结引用”和“可执行权限”，沿用 ElevenLabs 式节点摘要、右侧渐进披露与原文修复路径。
- `rtk npm test`：242 项通过；`rtk npm run build:canvas` 通过。
- 该片仍未接入真实工具调用、参数 Schema、确认、幂等副作用或语音执行；R3 Gate 保持未通过。

第二十三片范围与验证（2026-10-31）：

- 修复工具引用表单的共享写回边界：`patchUnit` 现在允许 `body` 仅用于显式 unit-graph-v1 的 `tool` 原子，并要求只改变 `body.tool_ref`；任意其他 body 内容变化、缺失 ID/版本、旧格式和只读/候选/忙碌状态均拒绝。
- 新增前端回归验证同一草稿写回、未知 body 元数据保留、草稿基线不提前改变和只读保护；这条路径不写布局状态，也不授予 ToolPolicy 执行权。
- `rtk npm test`：243 项通过；`rtk npm run build:canvas` 通过。
- 真实工具调用、参数 Schema 解析、确认、幂等副作用和语音执行仍未接入，R3 Gate 保持未通过。
