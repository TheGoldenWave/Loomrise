# Loomrise

**新会话入口**：[Agent 协作指南](AGENTS.md) · [文档总索引](docs/context/INDEX.md) · [开发路线与 Gate](docs/ROADMAP.md)。导航整理：2026-10-14；专题状态以文件正文和实际证据为准。

> **状态（2026-10-16，产品口径 v0.15）：完整网页客服、业务执行与受控改进、自有云快捷交付方向已确认，专家内任务与渐进披露方案已落文档；新增能力仍为规划。** S0 文档 Gate 已完成；S1 确定性回放 11/11、真实模型六路径 11/11、离线依赖锁定已有历史验收记录，退出 Gate 仍未全部通过。AgentScope 已锁定实际验证 commit；真实模型走本机 Coding Plan 凭据（验收默认 `gpt-6-sol`，`gpt-6-luna` 仅作成本对照）。**仍缺网页音频实测与真实模型端到端 SSE 留档**，尚无公开服务。第二轮本地前端已完成交互实现，真实 S2 服务仍未接入；见[前端交付与评审](docs/S2-FRONTEND-ROUND2.md)。S1 证据见 [S1 交付与验收](docs/S1-BUILD-REPORT.md)，版本钉见 [VERSION-PINS.md](VERSION-PINS.md)。

Loomrise 是一个面向**客服、销售**的开源 Agent 交付平台，服务 **AI 产品经理、解决方案人员、小团队开发者与策略运营**。规划提供配置与验收工作台、完整网页客服应用和统一业务执行服务，让团队从授权资料与流程出发，交付可办理业务、可验收、可持续改进的 Agent，并快捷部署到用户自己的云。

**一句话定位**：完整网页客服能力，加上统一任务与用户上下文、可核验的业务执行、版本验收与受控改进，以可自托管、可迁移的应用交付给用户。

**垂类与模态**：锚定**客服、销售**两类**业务职能场景**（不是行业，行业不限）；**网页文字与网页语音并列一等入口**，共享同一业务请求、权限与结果；IM 与电话在后续阶段独立验收。完整口径（含准入条件、合规排除、两根轴的分界）见[产品定义 §定位](docs/PRODUCT.md)。

**产品边界**：Loomrise 拥有场景包、业务 Agent 配置、任务与运行事实、评测、改动提案和发布版本；AgentScope、Pipecat、OpenTelemetry、AG-UI 等通过 Adapter 接入。不是 Dify / Octop 的整体 fork，也不是任何雇主或第三方内部系统的开源版。

**许可证**：**`Apache-2.0`**（完整原文见 [LICENSE](LICENSE)，署名见 [NOTICE](NOTICE)）。核心开源；未来若出现确需商业化的**独立模块**，**另建仓库**按其自有许可发布，现有开源核心不改协议。理由与协议排序见[开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md) §开源协议。

**已确认的完整产品形态（规划未实现）**：交付工作台 + 官方网页客服应用 + 统一执行内核 + 分类适配器。工作台供搭建者与策略运营使用，官方客服应用提供访客入口与一线 Inbox，也允许接入已有业务应用。以 Knocket 已提供能力为覆盖基线，包含 Widget、知识、模型连接、人工接管、联系页、Telegram/邮箱、通知、统计与移动 WebView；逐项范围与证据见[网页客服与自有云交付建设方案](docs/CUSTOMER-SERVICE-DELIVERY-PLAN.md)。用户可直接用授权资料完成答疑试用，也可选择虚构资料与模拟工具体验；真实业务工具接入后置；首版以单 Agent、单租户实例为目标，版本上线需评测与人工审批。

**自有云交付（规划）**：统一 Linux/容器发行配合厂商部署模板，在用户云账号运行客服应用与执行服务，覆盖认证、持久化、备份恢复、升级与迁移。腾讯云/阿里云优先候选，AWS/Azure 后续候选；具体支持以逐云实测为准。云部署不自动意味着模型、语音等外部 API 的数据处理也在该云。

**配置体验（已确认原则，具体交互待验证）**：用户可完整手动搭建，也可使用可关闭的初始化助手；先用自己的授权资料试用客服，再接业务工具。业务概览和详细配置共用同一版本，助手仅建议候选，不代替授权或发布。面向策略运营的模块说明见[后台配置指南](docs/OPERATOR-CONFIGURATION-GUIDE.md)；其中新增 Task/主动服务能力仍是规划。详细设计见[配置后台体验优化](docs/CONFIGURATION-UX-OPTIMIZATION.md)。

**客服物料（方向已确认，后端未实现）**：独立物料库承载业务常发的图片、视频与文档，业务录入授权、有效期、范围和简介，审阅后的简介/标签供 Agent 检索定位。人工可选文件发送，Agent 自动发送默认关闭并由版本化策略与会话占用限制。本轮前端扩展原件本地缓存、选择与发送仿真，并在客服试用台和 Widget 预览提供访客索取、收件与查看体验；真实压缩、内容理解、检索与外部发送仍待建设，验证见[物料专题](docs/MATERIAL-LIBRARY-AND-DELIVERY.md)与对应前端报告。初始化不强制配置物料。

**第三方 Agent 接入（高优先级方向已确认，未实现）**：统一应用 API + MCP + 配套 Skills + 可选 CLI；S2-a 优先实现受限草稿／候选创建与首个客户端联调，随后建设诊断、受控改进与可选通用 harness Worker。外部 Agent 不取得生产写入或发布权，网页手动路径不依赖助手。见[开发计划](docs/AGENT-INTEGRATION-PLAN.md)。

**任务与用户上下文（方案已确认，规划未实现）**：默认任务和触达策略归属单个专家配置，随 AgentVersion 评测/发布，不建共享策略库；服务周期幂等初始化，触达先候选再采用，Agent 只在批准范围内调整实例。持久事项暂称 `TaskItem`，实际业务仍由 `ServiceRequest/Outcome` 核验。系统装配有界工作集，按需披露事实、Skill、工具 Schema 和证据；记忆不授予触达权。见[Task 设计](docs/TASK-SYSTEM-DESIGN.md)、[用户上下文设计](docs/USER-CONTEXT-DESIGN.md)及[联合计划与首片入口](docs/TASK-MEMORY-INTEGRATION-PLAN.md)。

## 建设阶段与当前边界

| 阶段 | 目标 | 当前状态 |
|---|---|---|
| S1 | 最小咨询/模拟预约切片及剩余音频、SSE Gate | 已有实现和限定验收证据，退出 Gate 未全通过 |
| S2-a | 持久化、配置版本、知识摄入、独立物料资产与最小人工文件交付、沙盒发布和 Widget—Inbox 闭环 | 规划；现有 S2 仅为本地工作台原型 |
| S2-b | 完整网页客服覆盖：联系页、渠道、通知、统计、移动接入及物料后处理/已审简介检索 | 规划 |
| S2-c | 业务工具沙盒、策略化 Agent 文件发送、评测与改进、审批回滚及完整文字/语音应用验收 | 规划 |
| S3 | 标准发行与首个用户自有云快捷交付，验证恢复与升级 | 规划 |
| S4 | 多云模板扩展，其他渠道、多租户或电话独立验收 | 规划 |

阶段依赖和退出 Gate 见[验证路线](docs/ROADMAP.md)。**阶段内部的批次**见[版本切分](docs/RELEASE-PLAN.md)：S1→**R0**、S2-a→**R1+R2**、S2-b→**R3**、S2-c→**R4**、S3→**R5a**、S4→**R5b**；每条 Gate 由哪件工件证明见[追溯矩阵](docs/RELEASE-GATE-MATRIX.md)。完整客服、真实外部业务写入、持续改进与云快捷部署均未因本次文档更新变成已实现能力。

**本轮前端评审入口**：[打开第二轮页面](prototypes/console-next/index.html) · [第二轮 UI 走查与优化计划](docs/CONSOLE-UI-WALKTHROUGH-PLAN.md) · [交付、验证与后端交接](docs/S2-FRONTEND-ROUND2.md)。通过本机 HTTP 预览；默认完整人工配置，Agent 面板仅保留后续接入说明和虚构候选审阅，本轮不做平台内 Worker。Task/Harness 后台前端增量尚未实现，执行入口见[前端开发计划](docs/superpowers/plans/2026-10-19-console-task-harness-frontend.md)。

## 按任务查文档

首次接手先读本页、[产品定义](docs/PRODUCT.md)、[架构](docs/ARCHITECTURE.md)、[开发路线](docs/ROADMAP.md)与[公开边界](docs/OPEN-SOURCE-BOUNDARY.md)，再选择专题。完整文件清单、状态、依赖和后继关系统一放在[文档总索引](docs/context/INDEX.md)，无需按顺序读完所有研究材料。

| 当前问题 | 从哪里开始 | 继续查什么 |
|---|---|---|
| 产品范围、完整网页客服、自有云 | [客服交付建设方案](docs/CUSTOMER-SERVICE-DELIVERY-PLAN.md) | 产品形态、阶段依赖、能力矩阵与部署 Gate |
| 初始化、配置后台与 UI | [配置体验优化](docs/CONFIGURATION-UX-OPTIMIZATION.md) | 工作台 IA、六层合同、前端简报与对应轮次原型 |
| 图片/视频/文档、物料检索与客服发送 | [物料库与文件发送](docs/MATERIAL-LIBRARY-AND-DELIVERY.md) | 独立资产、简介审阅、人工/Agent 策略与后端 Gate |
| 跨会话任务、主动服务、记忆与画像 | [Task 与用户上下文联合计划](docs/TASK-MEMORY-INTEGRATION-PLAN.md) | 专家内版本蓝图、初始化/受限决策首片，主体/事件/调度与 Provider Gate |
| 跨用户经验（专家记忆）、Hy Memory 能复用什么 | [专家-用户记忆体系](docs/EXPERT-USER-MEMORY-SYSTEM.md)、[Hy Memory 三层裁决](docs/HY-MEMORY-LAYERED-ANALYSIS.md) | 三种记忆分工、五个身份合同、MEM-0–5 路线；两个记忆候选并列对照与采用/排除裁决 |
| MCP／Skills／CLI 与后台通用 Agent | [Agent 接入开发计划](docs/AGENT-INTEGRATION-PLAN.md) | AGI-01–11、摄入合同、权限与客户端验证 |
| 后续版本怎么切、每版做什么 | [版本切分与核心交付](docs/RELEASE-PLAN.md)（**v0.6**） | R0 合同对齐 → R1 能配 → R2 能跑 → R3 能扩 → R4 能改 → R5a 能装机 → R5b 能扩云；每版工作包与退出判据；**产品能力／前端／后端三层视图**；MCP/CLI/Skills 与执行耐久 Adapter 落版本；R0 执行状态（代码完成、Gate 未全绿） |
| 马上要做的 R0 怎么做 | [R0 合同对齐开工清单](docs/superpowers/plans/2026-10-23-r0-contract-alignment.md) | 预检命令、证据两层约定、语音阈值登记表、WP0–WP6 复选框与 DoD；合同不合主干 |
| 某条 Gate 由什么证明、证据在哪 | [版本 Gate 追溯矩阵](docs/RELEASE-GATE-MATRIX.md)（**v0.4**） | S1／S2-a／S2-c／S3-S4 父 Gate 与工件映射；耐久子项用于细化故障证据，不新增独立退出条件；**追溯表，不是 Gate 权威** |
| 上一轮评审改了什么、还剩什么 | [评审处置台账](docs/RELEASE-PLAN-REVIEW-RESPONSE.md) | 15 条意见的采纳/部分采纳/不采纳与落点；5 项未关闭 |
| 编排图在后台怎么落地 | [编排视图前端方案](docs/S2-ORCHESTRATION-UI.md)（**提案 v0.1**） | 流程 tab 三投影（图/清单/规则）；`@xyflow/react` v12；坐标不持久化；九条校验的界面落点 |
| 客服/销售的路由策略怎么配 | [路由与能力单元](docs/ROUTE-GRAPH-AND-UNITS.md)（**已采纳合同 v1.0**） | 单元＝契约层＋内容层，收起是节点、展开是图；跨层只走**端口**（跳步）与**边界事件**（异常）；LLM 在闭集里选 + margin 与可校验依据；九条保存前校验；R1 最小实现、R3 嵌套与画布 |
| 评测、候选改进、审批与回滚 | [S2 治理设计](docs/S2-DESIGN.md) | 范围决策与评测提案的已定／待定部分 |
| 已实现什么、怎样复现 | [S1 交付与验收](docs/S1-BUILD-REPORT.md)、[版本钉](VERSION-PINS.md) | 代码、测试、安装与运行证据；各轮原型看对应报告 |
| 选型、竞品、记忆与语音研究 | [参考项目与采用边界](docs/REFERENCE-PROJECTS.md) | 配置对比、记忆／迭代分析、语音验证与[语音架构决策记录](docs/VOICE-ARCHITECTURE-DECISIONS.md)；Qwen Audio 的机制借鉴见[源码研读](docs/QWEN-AUDIO-AGENT-HARNESS-STUDY.md)；ElevenLabs 托管平台的配置对象与能力边界见[分析](docs/ELEVENLABS-AGENTS-ANALYSIS.md)与[9 卷专题](docs/competitive/elevenlabs/00-INDEX.md)（368 篇官方文档原文支撑 + 88 项能力对照矩阵） |
| 旧方案为什么不再适用 | [历史归档索引](docs/archive/README.md) | 原版本、替代范围、现行后继；历史证据仍保留 |

## 新 Agent 如何接手

以 [AGENTS.md](AGENTS.md) 为协作入口：检查当前工作区 → 查总索引 → 阅读相关权威文件与实施计划 → 核对实际工件及验证。任务未完成时，把已完成内容、剩余项、证据和下一步写回对应计划／报告，新会话沿同一入口恢复。文档计划不自动授予外部写入或发布权限。

当前工件按目录区分：

| 目录／文件 | 内容与边界 |
|---|---|
| `loomrise/`、`scenarios/`、`tests/`、`scripts/` | S1 最小执行代码、原创样例与验证工具 |
| `docs/` | 现行产品／架构／路线、专题设计、研究与验收报告 |
| [docs/context/INDEX.md](docs/context/INDEX.md) | 按任务导航与文档权威、状态、关联 |
| [docs/archive/](docs/archive/README.md) | 被明确替代的方案及保留原路径的历史依据索引 |
| [prototypes/s2-console/](prototypes/s2-console/index.html) | 首轮本地工作台原型；[规格](docs/S2-PROTOTYPE-SPEC.md)与[走查](docs/UI-WALKTHROUGH-REPORT.md)仅覆盖该轮 |
| [prototypes/console-next/](prototypes/console-next/index.html) | 第二轮本地前端工件；[实施计划](docs/superpowers/plans/2026-10-14-console-round2.md)、[协作合同](prototypes/console-next/FRONTEND-CONTRACT.md)与[视觉设计](prototypes/console-next/DESIGN.md)；集成验证以该轮报告为准 |

两轮原型均用于设计评审，本地模拟的知识、客服、审批、发布与部署操作不能作为真实后台实现或云兼容性证据。

## S1 代码：怎么跑

回放使用**脚本化确定性模型**，不需要 API 密钥，也不需要音频设备。核心依赖通过 VCS 完整 commit 锁定 AgentScope `a388212`（需要访问 GitHub）：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m loomrise.cli replay --out runs/replay-s1.json   # 11/11 案例
PYTHONPATH=. .venv/bin/python -m loomrise.cli voice-sim                          # 播放四态回归
PYTHONPATH=. .venv/bin/python -m loomrise.cli run --text "数据分析入门这门课多少钱？"
PYTHONPATH=. .venv/bin/python tests/test_s1.py                                   # 自检
```

真实模型验收（需要本机 Coding Plan 凭据；**无凭据时脚本直接退出，不会退回脚本模型冒充真实调用**）：

```bash
PYTHONPATH=. .venv/bin/python -m loomrise.cli configure-model   # 一次性录入 → ~/.config/loomrise（仓库外，0600）；模型默认 gpt-6-sol
PYTHONPATH=. .venv/bin/python scripts/live_model_check.py       # 咨询/确认/拒绝/失败/取消/文字→语音，结果写 runs/
PYTHONPATH=. .venv/bin/python scripts/live_model_check.py --model gpt-6-luna   # 成本对照档（非验收基线）
```

本机网页试用（**只监听 127.0.0.1**，不是公开服务）：

```bash
PYTHONPATH=. .venv/bin/python -m loomrise.cli configure-model   # 一次性录入 Coding Plan 凭据 → ~/.config/loomrise（仓库外）
PYTHONPATH=. .venv/bin/python -m loomrise.cli web --port 8765   # 浏览器打开 http://127.0.0.1:8765
PYTHONPATH=. .venv/bin/python -m loomrise.cli web --scripted    # 不消耗额度：仍用脚本模型
```

网页的音视频不依赖云端 ASR/TTS：中文识别用浏览器 Web Speech，播报用浏览器语音合成，设备级播出回执独立于业务成功；浏览器不支持识别时不展示录音按钮。真实模型需要 Coding Plan 凭据，**回放不需要任何密钥**。

离线依赖（macOS arm64 / Python 3.13，已实跑通过：92 个 wheel 逐条 SHA-256）：

```bash
python scripts/build_offline.py      # 生成 .build/offline/wheels 与哈希锁
bash scripts/verify_offline.sh       # 干净环境离线安装 → 回放 → 自检 → 导出包离线恢复
```

语音 Worker（Pipecat）需单独环境，且有一个安装前置（`docopt` 无 wheel），见 [VERSION-PINS.md](VERSION-PINS.md)。

## 当前确认 / 尚未确认

- **确认（产品方向，规划未实现）**：交付工作台服务搭建者与策略运营；官方客服应用服务访客与一线客服，保留已有业务应用接入。首个完整应用为网页客服，虚构成人课程咨询为首个场景包。完整客服覆盖、业务执行/验收/持续改进、用户自有云快捷部署进入分阶段建设；同一执行内核、版本、权限与结果权威保持不变。**核心按 `Apache-2.0` 开源，未来独立商业模块另仓发布。**
- **已实现的最小切片**：命令行执行、模型外规则、模拟预约、上下文审计、取消执行确认、跨渠道同请求代码级断言、模拟语音入口及事件投影；另有**仅回环监听的网页入口**（文字/语音输入 + AG-UI SSE + 页面人工确认/拒绝/取消）。11/11 是确定性回放，不是真实模型或音频验收。
- **待验证/补齐**：真实网页语音链路、**浏览器外**的固定 STT/TTS 组合、语音首响与打断恢复数字；客户端按 HTTP/SSE 消费 Loomrise 事件的端到端**（脚本模型下已有真实 TCP/SSE 断言，真实模型下未留档）**；真实链路的资源占用与并发；单机和服务端部署规模；评测与受控改进闭环。
- **待决策/验证**：首云入口与支持规格、各云真实兼容性；公共 Demo 的额度与 BYOK 策略；Telegram/邮箱的具体适配方案、其他 IM/外呼供应商及真实电话是否立项；场景级测评阈值；判别式决策 Provider 是否进入默认安装。

公开仓库只发布经过整理、可以脱离个人语境独立理解的结论，以及可复现的计划、代码和证据。尚未确认的讨论、个人判断和商业化假设保留在本地 `private/` 工作区；分类与晋升规则见 [开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md)。

不会使用雇主或第三方的私有代码、真实客户数据、内部 Prompt、未获授权的业务材料或个人敏感信息。对外 Demo 只展示原创或有权复用的资料，并明确标注模拟数据。电话外呼、企微／钉钉均不属于初始可运行承诺。

本仓库目前完成了 **S0 的产品定位、架构边界、开源边界、接入与评测规范**，以及 **S1 的接入方验证结论、轻量适配范围与纵向样例代码**（源码级、安装级与案例回放证据）。S1 代码覆盖的是"用户发起对话后，Agent 在证据、权限和业务结果约束下完成一次可回放请求"这一条纵向切片，不含 B 端工作台、多场景、多租户、真实外部写入与发布闭环。

**未实现的仍然是多数**：真实音频、真实链路资源与并发、自进化与发布门禁均未验收。真实模型只覆盖了文字通道的六条路径，导出恢复和 AG-UI 第一方客户端语料已单独验证，但不等于真实渠道端到端验收。后续每一阶段都必须以实际运行和验收数据替代文档假设。
