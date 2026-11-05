# R3 开发收口与验收对照 v1.1

日期：2026-11-04（18:25 最终验证）。性质：**开发侧收口报告 + QA 对照表**，不是 R3 Gate 通过报告。Gate 权威条文只由 [验证路线 §S2-b](../ROADMAP.md) 与 [客服应用交付建设方案 §3](../CUSTOMER-SERVICE-DELIVERY-PLAN.md#3-阶段依赖与退出-gate) 定义；本文件不新增、不修改任何退出判据，也不把本机 fixture 升级为生产证据。

## 0. 结论先行

| 口径 | 结论 |
|---|---|
| Gate 侧 | [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) 的 `M-B-01…14` 为 `在跑`、`M-B-15` 为 `未开始`，**0/15 通过**；R2 技术 Gate 仍未通过。按授权跳过的只是 **R2 用户快速验收**，不是技术 Gate。 |
| 最终全量验证 | Python **739 项 OK**（`ResourceWarning` 作为错误）、前端 **340/340**、Canvas 构建 Exit 0、S1 自检与合同语义自检**全部通过**。专项：AGI-07/08 **61 项**、Contact／服务周期／算子 **190 项**、WebView 桥合同 **12 项**，均 OK。 |
| 开发侧 | 本轮按不重叠文件边界并行收口的 **4 个工作包全部交付**：AGI-07/08 五缺口修复与两份独立审查工件、服务周期生命周期与 `changed_to` 明确拒绝、Contact 完整批准路径、WebView 桥生命周期合同。累计新增 **45 项测试**（12 + 16 + 9 + 8）。 |
| 状态文档 | 9 份状态文档已同步至 schema **v23**、计数 **739/340**；`AGI-07/08 待实施`、`646/325`、`v19/v20` 等滞后表述已清理，历史分片保留。 |
| 本机不可完成 | 真实 Telegram Bot / Email alias+custom MX 授权收发撤销、系统 Web Push 送达回执与隐藏页生命周期、iOS/Android/RN/Flutter 实机 WebView、公网独立测试网站、真人目标角色任务基线、真实模型 21 类/多样本质量、真实 OCR/视频理解跨平台兼容、真实 harness Provider 与 host Skill 联调、生产服务周期来源签发。一律标为未验证，不用 fixture 冒充。 |

**本文件回答的问题**：哪些开发工作已完成且有可复核工件、哪些 Gate 条件被真实外部环境阻塞、每条阻塞需要什么凭据/设备/环境、如何复跑验证。

## 1. 本轮范围与护栏

- 工作区既有 175+ 项未提交改动（40+ `M`、100+ `??`）全部保留；最终 `git status --short` 为 **184 项**。未执行 `git add` / `commit` / `checkout` / `restore` / `stash` / `reset`，暂存区为空，`private/` 保持 Git 忽略。
- 文档只改「当前状态」段与证据登记；[R3 实施计划](../superpowers/plans/2026-10-30-r3-development.md) §当前状态明载「文末按日期保留的分片记录是当时快照，不覆盖本节」，故 ROADMAP / RELEASE-PLAN / R3 计划里按日期的历史增量**全部保留**，只在其上方新增/刷新 2026-11-04 当前状态段。
- 4 个开发工作包由独立子 agent 按不重叠文件边界并行推进；主 agent 统一收口文档、证据索引与 Gate 矩阵，避免并发写同一文件。首批 4 个 agent 曾因框架 RPC 5000ms 超时在落盘前全部失败，核验无残留写入后以低并发重派成功。
- 所有 shell 命令走 `rtk proxy <cmd>`（全局指令见 `~/.claude/RTK.md`）。
- 历史分片中的旧计数（609/609、617/617、323/323、646/325）不改写；它们描述当时快照。

## 2. 权威退出 Gate 条文（原样摘录）

**客服应用交付建设方案 §3，S2-b 行（`CUSTOMER-SERVICE-DELIVERY-PLAN.md:112`）**：

> 能力矩阵逐项有验收工件；Widget 在独立测试网站安装；Contact Page 生成编辑发布可复核；Telegram/Email 真实授权沙盒收发撤销通过；移动 WebView 按声明平台验证；原件/派生有产物证据，未审/撤回/越权物料不供 Agent，真实附件大小/类型/下载授权与回执分别验证

**验证路线，S2-b 行（`ROADMAP.md:86`）**：

> 客服能力矩阵逐项有证据；独立网站安装与 Contact Page 发布可复核；渠道身份、收发、去重、限流和撤销通过；每个声明支持的移动组合有运行记录；诊断只读、引用可追溯，Worker 受限、可取消，故障不阻断在线与手动编辑

**补充约束**：`CUSTOMER-SERVICE-DELIVERY-PLAN.md:117`「S2-b 的 Telegram 和 Email 是网页客服基线范围，不能再次推迟到 S4」；`ROADMAP.md:91` 同口径，并明确 S3 才验收公网与用户自有云发行。

### 2.1 本机可完成 vs 需真实外部环境

| Gate 条件 | 分类 | 本机可交付的边界 |
|---|---|---|
| 能力矩阵逐项有验收工件 | 部分本机 | 确定性 fixture、单元测试、浏览器 Node VM/fixture 证据可逐项留档；但「完整覆盖」仍受下列外部项约束 |
| Widget 在独立测试网站安装 | **需外部** | 本机 loopback 双独立 BrowserContext 只证明访客隔离与交叉 token 拒绝，公网/云独立站点需真实部署 |
| Contact Page 生成编辑发布可复核 | 本机 | 已闭环：草稿→生成→冻结→批准→版本绑定→公开只读→分享→停用→重启用，以及 8 类权限/版本/Schema 反例 |
| Telegram/Email 真实授权沙盒收发撤销 | **需外部** | 现有 `channel_sandbox.py` 不发起网络请求；需授权 Bot token、alias/custom MX 测试邮箱与回调记录 |
| 移动 WebView 按声明平台验证 | **需外部** | 已补 `loomrise.webview.bridge.v1` 的 8 项本机静态生命周期合同；iOS/Android/RN/Flutter 实机运行与宿主生命周期需真机 |
| 原件/派生产物证据与未审/撤回/越权不供 Agent | 本机 | 已有确定性与浏览器证据 |
| 真实附件大小/类型/下载授权与回执 | **需外部** | 需真实渠道与系统送达回执 |
| 诊断只读、引用可追溯、Worker 受限可取消、故障不阻断在线与手动编辑 | 本机 | AGI-07/08 已落地，专项 61 项 + 两份独立审查工件闭环；**真实 Provider / host 联调另计** |
| 客服能力矩阵完整覆盖 / 目标角色基线 | **需外部** | 需真人搭建者、策略运营、访客、一线坐席参与，本机不代签 |

## 3. 开发工作包收口

本轮按不重叠文件边界并行派 4 个开发任务，覆盖 [R3 实施计划](../superpowers/plans/2026-10-30-r3-development.md) 中 `:40–45`（AGI-07/08 六步）、`:205`（服务周期生命周期与条件算子）、`:221`（Contact 完整批准流程）与 `:227` 的本机桥合同部分。计划中 `:227/:231/:234/:241` 的实机、真实凭据、真实 OCR 质量与真人角色基线仍属外部项，未派单、不伪造。

**关键安全裁决 1**：AGI-07/08 的治理作业入口**未**扩展到 HTTP/MCP——`configuration.py:1108` 明确拒绝「治理作业仅本机 CLI 可用，HTTP/MCP 不暴露作业入口」，以免外部 Agent 借配置服务取得后台作业能力。理由是 job 需注入 Provider 对象且 `run` 为 async，`ConfigurationApplication.execute(action, payload:dict)` 无法承载对象注入，同步 `execute` 内 `asyncio.run` 会与 HTTP 已有 event loop 冲突。语义诊断 5 个动作仍复用应用服务；`external_agent` 的诊断动作白名单改为显式可审计判断。CLI/MCP/HTTP 同合同回归留有拒绝断言。计划 §43 复选框的注已如实标明该偏差，不写成「入口已复用应用服务」。

**关键安全裁决 2**：`M-B-15` 状态**保持 `未开始`**。实现 agent 明确建议不据 8 项 Node VM 静态合同把该行改为 `在跑`；主 agent 采纳保守意见——Gate 通过条件要求每个声明平台组合分别实机/真实 WebView 验证，本机静态合同不构成开始该 Gate。只刷新「证据位置」摘要。

**实际成果与真实回归输出**：见 §9「本轮开发成果回填」。

## 4. Gate 矩阵 `M-B-01…15` 逐条对照

状态列以 [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) 为准，证据细节以 [R3 证据登记](R3-EVIDENCE.md) 为准。本轮刷新了 M-B-04/05/08/10/11/15 的「证据位置」摘要；新增的服务周期生命周期、`changed_to` 拒绝与 AGI 审查工件属 WP1/WP2/AGI 开发证据，**不改变任何 M-B 行状态**。

| ID | 能力 | 本机已有证据（摘要） | 仍缺（不关闭原因） | 状态 |
|---|---|---|---|---|
| M-B-01 | Widget/FAQ/AI 接待 | FAQ 精确来源绑定、公开投影、21 个 Python + 浏览器往返 | 公网/云独立网站、真实模型多样本质量、目标角色基线 | 在跑 |
| M-B-02 | 接待策略与访客字段 | 七天 offline 排班、text/email/tel 本机矩阵 | 真实渠道入站、生产身份边界 | 在跑 |
| M-B-03 | 联系外链 | 21 类 fixture 外链新窗口属性与空块隐藏 | 真实外站预约与客服线程续接 | 在跑 |
| M-B-04 | Widget 安装 | 双独立 BrowserContext 隔离、交叉 token 404、只读 `release.entry.list` 选择已批准入口 | 公网/云独立网站、坐席身份与授权隔离 | 在跑 |
| M-B-05 | Contact Page | 21 类 Schema/候选边界；**9 项端到端批准→冻结→发布→版本绑定→公开只读→分享→停用→重启用**与 8 类反例（专项 45 项 OK，最终全量 739 项 OK） | 21 类真实模型多样本质量、真人目标角色基线、治理层 `release.approve/publish` 通过完整生产预检（本机 fail-closed）、浏览器端独立提交批准按钮 | 在跑 |
| M-B-06 | AI 接待设置 | 七天排班、DST/隔夜/周跨边界、访客字段回归 | 真实渠道入站、生产身份边界、完整行为/角色验收 | 在跑 |
| M-B-07 | 模型连接 | 连接合同/Provider 适配、有限真实模型单样本 | 逐预设可达/认证/流式/工具调用兼容矩阵 | 在跑 |
| M-B-08 | 知识摄入 | URL 摄入→ready/哈希/索引、失败重试、旧 `.doc` 经真实 `textutil` 转换、知识服务 68 项 | 真实 Office/HTML 变体与跨平台 DOC 兼容、来源撤回完整验收 | 在跑 |
| M-B-09 | 授权答疑 | 确定性与有限真实模型 fixture | 多样本引用正确性、未知/冲突/禁答与零副作用完整案例集 | 在跑 |
| M-B-10 | Inbox | 四种筛选 fixture、SSE 冷启动基线/consumer ack、双访客隔离 | 完整多入口队列/附件/移动网页矩阵、坐席认证隔离、公网部署 | 在跑 |
| M-B-11 | 接管与回复辅助 | `inbox.assistance.generate/check`、服务/Provider 32 项、零 DML/快照、gpt-6-sol 单样本 | 多样本摘要/答复质量、策略化转人工建议、恢复/超时完整矩阵 | 在跑 |
| M-B-12 | Telegram | 不发起网络请求的授权沙盒 | 真实 Bot 授权收发、线程映射、限流、失败、回调、撤销 | 在跑 |
| M-B-13 | Email | 不发起网络请求的授权沙盒 | alias/custom MX 授权邮箱收发、重复、附件、拒收、撤销 | 在跑 |
| M-B-14 | 通知与统计 | 持久接待记录统计投影与本机浏览器 fixture | Web Push/Telegram 送达回执、隐藏页生命周期 | 在跑 |
| M-B-15 | 移动入口 | Node VM 桥合同 fixture + 8 项生命周期断言（前端 340/340） | iOS/Android/RN/Flutter 实机 WebView、关闭按钮与宿主生命周期、目标容器能力 | 未开始 |

**汇总**：14 行 `在跑` + 1 行 `未开始`，`通过` 0 行。能力矩阵逐项留档不等于 Gate 通过。

## 5. 验证记录（最终实测 2026-11-04 18:25）

基线命令（工作目录为仓库根；前端命令在 `prototypes/console-next`）：

```bash
# Python 全量
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -q
# 前端全量 / Canvas 构建
cd prototypes/console-next && rtk proxy npm test && rtk proxy npm run build:canvas
# S1 自检 / 合同语义自检
rtk proxy .venv/bin/python tests/test_s1.py
rtk proxy env PYTHONPATH=. .venv/bin/python tests/test_contract_semantics.py
# AGI-07/08 专项（5 模块）
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_diagnostics tests.test_diagnostics_interfaces tests.test_governance_jobs tests.test_harness_provider tests.test_governance_harness_integration -q
# Contact / 服务周期 / 算子专项
rtk proxy .venv/bin/python -W error::ResourceWarning -m unittest tests.test_contact_page tests.test_contact_generation tests.test_contact_approval tests.test_service_cycles tests.test_service_cycle_lifecycle tests.test_changed_to tests.test_graph_runtime tests.test_graph_validation -q
# WebView 桥合同专项
rtk proxy node --test prototypes/console-next/tests/customer-widget-bridge-contract.test.js prototypes/console-next/tests/customer-widget-bridge-lifecycle.test.js
```

| 项目 | 收口前基线 | 最终实测 | 结论 |
|---|---|---|---|
| Python 全量 | `Ran 702 tests ... OK` | `Ran 739 tests in 24.324s` / `OK` | +37 项，全绿 |
| 前端全量 | `332/332` | `# tests 340 / # pass 340 / # fail 0` | +8 项，全绿 |
| AGI-07/08 专项（5 模块） | `Ran 49 tests ... OK` | `Ran 61 tests in 3.826s` / `OK` | +12 项，全绿 |
| Contact／周期／算子专项 | — | `Ran 190 tests in 2.378s` / `OK` | 含 9 + 16 项新增 |
| WebView 桥合同专项 | — | `# tests 12 / # pass 12 / # fail 0` | 4 项既有 + 8 项新增 |
| Canvas 构建 | Exit 0 | Exit 0（stderr 空） | 通过 |
| S1 自检 | 通过 | `全部通过` | 通过 |
| 合同语义自检 | 通过 | `全部通过` | 通过 |

子 agent 各自报告的其他时点输出（714 / 723 / 733 项 OK）为各工作包落盘时点快照；最终口径以本表 739 项为准。开发过程中出现过两次并发中间态失败：`test_diagnostics.py:129` 旧 hash 断言（已按新合同改为「读取仍拒绝 / 撤权始终可执行 / 撤权后读取仍拒绝」三段显式断言）与 `test_service_cycles.py:499` v16 迁移回滚断言（新增独立审计表后补 1 行 `DROP TABLE service_cycle_migrations` 保持整体回滚语义），两者最终均全绿，未删断言绕过。

## 6. 阻塞项与所需外部条件

| 阻塞 | 需要的外部凭据／设备／环境 | 为什么本机 fixture 不能替代 |
|---|---|---|
| M-B-12 Telegram | 获授权测试 Bot token、回调端点、真实消息收发记录 | `channel_sandbox.py` 不发网络请求，无法证明身份、去重、限流、撤销 |
| M-B-13 Email | alias/custom MX 授权测试邮箱、真实 SMTP/IMAP 收发与附件 | 同上；线程关联与拒收需真实邮件 Provider |
| M-B-14 通知送达 | 系统级 Web Push 订阅与送达回执、隐藏页生命周期 | Notification 权限/显示替身与 loopback SSE 均不证明送达 |
| M-B-15 移动平台 | iOS / Android 真机或模拟器、React Native / Flutter WebView 宿主 | Node VM 静态合同只验证消息协议，不验证宿主生命周期与容器能力 |
| M-B-04 独立网站 | 公网/云独立测试站点与部署凭据 | loopback 双 BrowserContext 不等于跨 origin 生产安装 |
| M-B-07/09/05 质量 | 真实模型凭据 + 21 类/多样本真值集 | 单样本不构成兼容或质量矩阵 |
| M-B-08 格式兼容 | 真实 Office/HTML 变体与跨平台 `textutil`/OCR 工具链 | 原创最小 fixture 与单一 RTF→DOC 样本不覆盖变体 |
| WP5/画布角色基线 | 真人搭建者、策略运营、访客、一线坐席参与 | 本机浏览器自动化不代签目标角色可用性 |
| AGI-07/08 联调 | 真实 harness Provider 版本/凭据、真实 host 的 Skill 激活 | `ScriptedChatModel`、`example.invalid`、`test-only-credential` 均为离线替身 |
| 治理层生产预检 | 外部固定样例执行服务与 `fixed_samples_passed` | 本机 `release.approve/publish` 恒 `release_blocked` fail-closed，测试如实验证而非伪造通过 |
| R2 技术 Gate | 固定样例发布门禁、确认等待恢复、未知结果收敛 | 文档与 fixture 不替代技术 Gate；用户快速验收的跳过授权不覆盖此处 |

**内部已知限制（非外部阻塞，需后续技术决策）**：`changed_to` 需「服务端签发、调用方不可自报」的 previous-value 来源并在 `service.py` 注入剥离调用方的可信命名空间，当前代码库无该存储；生产服务周期来源仍是本机虚构 `authority_id`，签发/验签未接入；遗留 v22 库残留表级 UNIQUE 会阻止同 scope 第二个周期行（裁定失败关闭并给明确诊断，不静默复用），彻底消除需一次 FK-safe 表重建。三者均保持明确拒绝/诊断，未以放宽校验制造通过。

## 7. 状态文档同步清单（本轮）

| 文件 | 改动 |
|---|---|
| `README.md` | 当前状态段：schema v23、四工作包收口、最终 739/340、专项 61/190/12、0/15 Gate；导航表版本 v0.46 / v0.8 |
| `docs/ROADMAP.md` | 新增 2026-11-04 当前状态段；状态表 v23 + AGI 四表 + v23 周期增量；第三方 Agent 行去掉「接口／Skills／Worker 未实现」过时表述并改 61 项 |
| `docs/RELEASE-PLAN.md` | 升 v0.46 并新增变更段；R3 当前实施状态段改 739/340、v23、专项 61 项 |
| `docs/context/INDEX.md` | 头部 v23 / 739/340 / 四工作包成果；Gate 矩阵 v0.8；R3 计划 v0.55 + schema v23；:162 状态注改 61 项；登记 [R3 收口与验收对照](../reports/R3-ACCEPTANCE-2026-11-04.md) |
| `docs/superpowers/plans/2026-10-30-r3-development.md` | §21 当前状态改 739/340、v23、四工作包成果；AGI 六步复选框全勾（§43 如实标注作业入口偏差）；§47 验证入口回填 61 项；§205/§221 补本轮增量且保留未勾选 |
| `docs/reports/R3-EVIDENCE.md` | 升 v1.6；摘要 646/325→739/340、v20→v23；**新增 AGI-07/08 与 WP1/WP2 服务周期两份本机证据专节**；M-B-05／M-B-15 段同步 |
| `docs/RELEASE-GATE-MATRIX.md` | 新增 2026-11-04 状态说明；M-B-04/05/08/10/11/15 证据位置补登；M-B-15 状态经裁决保持 `未开始` |
| `docs/S2-ORCHESTRATION-UI.md` | 当前状态同步日期与 R3 计划版本 v0.55 |
| `docs/AGENT-SELF-ITERATION-ROADMAP.md` | E0 基座段的 schema 表述改为「四表由 v21/v22 引入，当前 v23」 |
| `docs/superpowers/specs/2026-11-04-agi-0708-spec-review.md` | **新建**：对照 plan :29-36 最小合同逐条核查（实现位置 + 验证命令 + 结论） |
| `docs/superpowers/reviews/2026-11-04-agi-0708-code-quality-review.md` | **新建**：覆盖 plan :45 九类场景与真实输出，明确未联调项 |
| `docs/reports/R3-ACCEPTANCE-2026-11-04.md` | **新建**：本文件，开发侧收口 + QA 对照 |

**保留不改**：`RELEASE-PLAN.md:452–453` 的 AGI 版本归属表（列结构是编号/说明/优先级/版本/备注，不是状态表）；所有按日期的历史增量段与旧计数；`tests/test_inbox_read_state.py` 的 `test_v19_upgrade` 测试函数名。

## 8. AGENTS.md §7 四项检查

```text
rtk git status --short        # 184 项改动，全部为未提交工作区成果；暂存区为空
rtk git diff --check          # 已跑，无输出（干净）
rtk git check-ignore -v private/   # .gitignore:34:private/  private/
rtk git diff --cached --name-only  # 空
```

本地链接核验：对本轮改动的 **12 份 Markdown 提取 412 条相对链接**，检查目标存在性 → **0 条坏链**。索引覆盖、术语与状态一致性已随 §7 清单核对；`v19`/`646`/`325`/`AGI-07/08 待实施` 等滞后表述仅剩按日期保留的历史分片与 v21/v22 版本说明。

## 9. 本轮开发成果回填（4 个工作包）

### 9.1 AGI-07/08 只读诊断与 Worker 首链（+12 项测试）

- **改动文件**：`loomrise/diagnostics.py`、`loomrise/governance_jobs.py`、`loomrise/adapters/harness.py`、`loomrise/configuration.py`；`tests/test_diagnostics.py`、`test_diagnostics_interfaces.py`、`test_governance_jobs.py`、`test_harness_provider.py`、`test_governance_harness_integration.py`、`test_config_cli.py`。
- **五个确凿缺口全部修复**：① Provider 按 `provider_kind / version / contract_hash` 由服务端校验、禁止调用方自报 `real`，替身成功只登记 `offline_scripted` / `offline_structured`；② 治理作业经 `_GOVERNANCE_JOB_ACTIONS` 显式限定仅本机 CLI，HTTP/MCP 同合同拒绝（含 403 / MCP 工具集无 job 工具 / governance_jobs 表 0 行断言）；③ `external_agent` 诊断动作白名单显式可审计；④ 撤权独立于 `_permission_tx` 的合同/hash/时效校验，旧 hash、来源失效、过期下始终可执行，读路径校验完全未改；⑤ `cancel` 两处 UPDATE 补 `rowcount` 竞争检查。
- **专项回归**：5 模块 `Ran 61 tests ... OK`；8 模块 `Ran 105 tests ... OK`；最终全量 739 项 OK；合同语义自检全部通过。
- **审查工件**：[独立规格审查](../superpowers/specs/2026-11-04-agi-0708-spec-review.md)（172 行）、[代码质量审查](../superpowers/reviews/2026-11-04-agi-0708-code-quality-review.md)（182 行），逐条覆盖 plan :29-36 与 :45 九类场景。
- **仍未覆盖**：真实 harness Provider / 真实 host Skill 激活 / 质量对照均未联调；治理作业未做正向 HTTP/MCP 入口（按不扩大权限前提刻意不暴露）。

### 9.2 服务周期生命周期与条件算子（+16 项测试）

- **改动文件**：`loomrise/service_cycles.py`（`close` / `adjudicate` / `migrate`）、`loomrise/durable_store.py`（`SCHEMA_VERSION 22→23`）、`loomrise/config_validation.py`、`loomrise/graph_validation.py`、`loomrise/graph_runtime.py`、`tests/test_service_cycles.py`（+1 行 DROP）；新建 `tests/test_service_cycle_lifecycle.py`（10 项，338 行）、`tests/test_changed_to.py`（6 项，99 行）。
- **生命周期**：active→closed/cancelled 终态；仅 completed-closed 且无后继的旧周期可裁定新 generation（新 cycle_id、lineage、冻结版本钉死）；迁移需源+目标双 grant，已 cancelled/done/migrated 事项不复活；并发靠 `BEGIN IMMEDIATE` + partial unique index（恰好一个成功）；拒绝跨 authority 换源、旧 generation 绑定与静默复用旧周期。
- **`changed_to` 判定不可行，保留明确拒绝**：`GraphRuntime` 的 state 完全来自调用方 `routing_state`，唯一服务端持久投影 `state_window_counts` 只有 attempts/runs 计数，无按字段可信前值快照；在 `service.py` 注入剥离调用方的可信命名空间超出本轮文件边界，且「直接读 state 前值」正是要防的攻击。6 项反例锁定自报前值被拒、缺来源不启用、否定/短路不能绕过、既有算子与两层深度上限不变。
- **专项回归**：指定专项 `Ran 139 tests ... OK`、扩展专项 `Ran 145 tests ... OK`、与 Contact 合并 `Ran 190 tests ... OK`；最终全量 739 项 OK；合同语义自检全部通过；v16 迁移回滚单测 `Ran 1 test ... OK`。
- **仍未覆盖**：生产业务源签发/验签未接入；遗留 v22 库残留表级 UNIQUE 阻止同 scope 第二周期行（有明确诊断，需 FK-safe 表重建）。

### 9.3 Contact Page 完整批准／发布路径（+9 项测试）

- **改动文件**：仅新建 `tests/test_contact_approval.py`（483 行，9 项）；**未改任何生产代码、未放宽校验、未注入伪造批准行、未新建绕过入口**。
- **能力复核结论**：服务端批准能力真实存在且分两层——策略层 `release.approve/publish/entry.resolve`（治理预检、owner-only，因外部固定样例服务缺失在本机恒 `release_blocked` fail-closed）与执行层 `freeze_candidate → approve_release_candidate → publish_sandbox_candidate → enable_contact_page`（`expected_version_id` 同事务 JOIN 重验批准与版本）。`contact-matrix-fixture-v1` 只是存储级预置批准快照，不构成完整生命周期证据。
- **覆盖**：1 条正向端到端（草稿→生成待审候选→显式采用→冻结→批准绑定→发布重验→入口解析→启用固定版本→公开页只读且与后续草稿隔离→分享→停用 404→重新启用）+ 8 类反例（revision 冲突、viewer/editor/external 不可批准或冻结或启用、版本漂移、坏 Schema/未知块、缺少审批拒绝公开、知识撤回拒绝公开、跨专家/租户、治理层 owner-only 且 fail-closed）。
- **专项回归**：`Ran 45 tests ... OK`（含 `test_contact_page` / `test_contact_generation`）；最终全量 739 项 OK。
- **仍未覆盖**：21 类真实模型多样本质量、真人角色基线、治理层通过完整生产预检、浏览器端独立「提交批准」按钮。

### 9.4 M-B-15 WebView 桥生命周期合同（+8 项前端测试）

- **改动文件**：`loomrise/customer_widget.html`（`emit` 加 try/catch 防宿主消失、`handleBridgeHandoff` 迟到/重复 `session.handoff` 幂等且不丢首个 `request_id`）；新建 `prototypes/console-next/tests/customer-widget-bridge-lifecycle.test.js`（8 项，366 行）。loopback origin、`source`/`origin` allowlist、无 host 安全 no-op 与权威字段校验保持不变。
- **覆盖**：READY 握手与重复握手、迟到/重复 handoff 幂等、dismiss 双向与关闭按钮启用/未启用、父窗口/宿主消失与 `source`/`origin` 边界、未知类型 no-op、19 个权威字段白名单拒绝、既有会话持久化不丢。
- **TDD 失败态**：修实现前 `# tests 8 / # pass 5 / # fail 3`（2 项 `session_start_pending` 缺失、1 项宿主消失未防）；修实现后 8/8。
- **专项回归**：桥合同 12/12；前端全量 340/340；Canvas 构建 Exit 0。
- **仍未覆盖／定性**：全部为**本机静态合同 + Node VM fixture**；不构成 iOS/Android/RN/Flutter 实机 WebView、系统 Web Push、真实渠道或宿主生命周期真机集成验证；集成层只做静态结构断言 + 全脚本语法编译，无真实 DOM 端到端；`M-B-15` 保持 `未开始`。

## 10. 交接与下一步

1. 新会话从 `AGENTS.md` → `README.md` → `docs/context/INDEX.md` → 本文件与 `docs/reports/R3-EVIDENCE.md` 恢复；Gate 状态只认 `docs/RELEASE-GATE-MATRIX.md` 与 §2 权威条文。
2. 要关闭任一 M-B 行，必须先拿到 §6 对应行的外部凭据/设备/环境并留下可复核工件；本机新增 fixture 只能刷新「证据位置」摘要，不能把 `在跑` 改成 `通过`。
3. AGI-07/08 的剩余动作是真实 harness Provider / host 联调与质量对照；代码、专项测试与两份审查工件已落地，不重复实现。
4. 开发侧后续技术决策：`changed_to` 的可信前值来源与 `service.py` 注入、生产服务周期来源签发/验签、遗留 v22 库的 FK-safe 表重建、治理作业是否开放正向 HTTP/MCP 入口（须重新评估权限面）。
5. R2 技术 Gate 与 R3 退出 Gate 均保持未通过，文档同步不改变这一结论。
