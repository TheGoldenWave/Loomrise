# Loomrise

> **状态（2026-09-28）：S0 文档 Gate 已完成；S1 确定性回放 11/11、真实模型六路径 11/11、离线依赖锁定均已实跑通过，退出 Gate 仍未全部通过。** AgentScope 已锁定实际验证 commit；真实模型走本机 Coding Plan 凭据（验收默认 `gpt-6-sol`，`gpt-6-luna` 仅作成本对照）。**仍缺的是网页音频实测（中文可懂度、语音首响、打断恢复）与真实模型下的端到端 SSE 留档**，尚无公开服务。逐条证据见 [S1 交付与验收](docs/S1-BUILD-REPORT.md)，版本钉见 [VERSION-PINS.md](VERSION-PINS.md)。

Loomrise 是一个面向 **AI 产品经理、解决方案人员和小团队开发者** 的开源 Agent 交付工作台，帮助业务团队把获授权的资料、流程和工具做成可试用、可验收、可部署、可持续改进的 Agent 应用。业务 PM／运营是重要使用者和最终验收者，但项目首先优化的是交付者的搭建与验证体验。

**一句话定位**：从一份业务资料出发，交付带业务界面、验收用例与部署配置的 Agent 应用，并让每次运行成为下一次受控改进的证据。

**产品边界**：Loomrise 拥有场景包、业务 Agent 配置、任务与运行事实、评测、改动提案和发布版本；AgentScope、Pipecat、OpenTelemetry、AG-UI 等通过 Adapter 接入。不是 Dify / Octop 的整体 fork，也不是任何雇主或第三方内部系统的开源版。

**已确认的产品形态（未实现）**：一个面向交付者的 B 端工作台、一套文字/语音共用的业务执行内核，以及按渠道、信息源、知识和业务工具分类的适配器。用户先用虚构场景取得可核验的模拟结果，再以授权资料和沙盒连接接入自己的业务；首版以单 Agent 为主，版本发布前需通过固定测评集的批量回放和人工审批。完整决策与待验证边界见[产品形态与开放接入规范](docs/PRODUCT-FORM-AND-INTEGRATION.md)。

## 阅读顺序

1. [产品定位与黄金路径](docs/PRODUCT.md)
2. [产品形态与开放接入规范](docs/PRODUCT-FORM-AND-INTEGRATION.md)
3. [六层配置合同](docs/CONFIGURATION-LAYERS.md)
4. [架构与对象权威](docs/ARCHITECTURE.md)
5. [分阶段验证路线](docs/ROADMAP.md)
6. [S1 验证结论与轻量适配](docs/S1-VALIDATION-AND-ADAPTATION.md)
7. [S1 交付与验收](docs/S1-BUILD-REPORT.md) · [VERSION-PINS.md](VERSION-PINS.md)
8. [参考项目与采用边界](docs/REFERENCE-PROJECTS.md)
   - [参考项目的 Agent 配置后台对比](docs/AGENT-CONFIGURATION-COMPARISON.md)
9. [开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md)
10. [命名决策](docs/NAMING.md)
11. [初始化与摄入通道](docs/INTAKE-AND-INITIALIZATION.md)（提案，待确认：上传 vs 本地 CLI/MCP）
12. [S2 评测门禁与改进循环提案](docs/S2-EVAL-GATE-PROPOSAL.md)（决策一已确认：Reserve 走 blind 批次、golden 只判不退步；同条件配对评估、改进 run 预算与状态机仍待确认）
13. [用户记忆模块基石接入设计](docs/MEMORY-FOUNDATION-DESIGN.md)（提案，待确认：以 TencentDB Agent Memory 为记忆内核的选型、边界红线与分期；**未实现**）
14. [S2 平台信息架构与主菜单定义](docs/S2-IA-NAV.md)（**S2 工作台设计的权威**：6 域 / 16 二级页 / 22 面；设计草案待定稿）
15. [配置化后台启动方案](docs/S2-CONSOLE-KICKOFF.md)（执行方案：前置依赖、启动顺序 T0–T3、契约缺口、待确认五项）
16. [S2 前端设计启动简报](docs/S2-FRONTEND-DESIGN-BRIEF.md)（设计立项汇总：页面与功能总表、页面关系、文档关联）

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

网页的音视频不依赖云端 ASR/TTS：中文识别用浏览器 Web Speech，播报用浏览器语音合成，设备级播出回执独立于业务成功；浏览器不支持识别时录音按钮禁用。真实模型需要 Coding Plan 凭据，**回放不需要任何密钥**。

离线依赖（macOS arm64 / Python 3.13，已实跑通过：92 个 wheel 逐条 SHA-256）：

```bash
python scripts/build_offline.py      # 生成 .build/offline/wheels 与哈希锁
bash scripts/verify_offline.sh       # 干净环境离线安装 → 回放 → 自检 → 导出包离线恢复
```

语音 Worker（Pipecat）需单独环境，且有一个安装前置（`docopt` 无 wheel），见 [VERSION-PINS.md](VERSION-PINS.md)。

## 当前确认 / 尚未确认

- **确认（产品决策，尚未实现）**：核心使用者为 AI 产品经理／解决方案人员／小团队开发者；首个完整交付场景为明确标注虚构的成人在线课程咨询；单一工作台、统一执行内核、分类适配器、首版单 Agent、发布前固定测评集门禁；网页文字与网页语音共享同一业务请求与运行证据。
- **已实现的最小切片**：命令行执行、模型外规则、模拟预约、上下文审计、取消执行确认、跨渠道同请求代码级断言、模拟语音入口及事件投影；另有**仅回环监听的网页入口**（文字/语音输入 + AG-UI SSE + 页面人工确认/拒绝/取消）。11/11 是确定性回放，不是真实模型或音频验收。
- **待验证/补齐**：真实网页语音链路、**浏览器外**的固定 STT/TTS 组合、语音首响与打断恢复数字；客户端按 HTTP/SSE 消费 Loomrise 事件的端到端**（脚本模型下已有真实 TCP/SSE 断言，真实模型下未留档）**；真实链路的资源占用与并发；单机和服务端部署规模；评测与受控改进闭环。
- **待决策**：开源许可证；公共 Demo 的额度与 BYOK 策略；首个 IM/外呼供应商及真实电话是否立项；场景级测评阈值；判别式决策 Provider 是否进入默认安装。

公开仓库只发布经过整理、可以脱离个人语境独立理解的结论，以及可复现的计划、代码和证据。尚未确认的讨论、个人判断和商业化假设保留在本地 `private/` 工作区；分类与晋升规则见 [开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md)。

不会使用雇主或第三方的私有代码、真实客户数据、内部 Prompt、未获授权的业务材料或个人敏感信息。对外 Demo 只展示原创或有权复用的资料，并明确标注模拟数据。电话外呼、企微／钉钉均不属于初始可运行承诺。

本仓库目前完成了 **S0 的产品定位、架构边界、开源边界、接入与评测规范**，以及 **S1 的接入方验证结论、轻量适配范围与纵向样例代码**（源码级、安装级与案例回放证据）。S1 代码覆盖的是"用户发起对话后，Agent 在证据、权限和业务结果约束下完成一次可回放请求"这一条纵向切片，不含 B 端工作台、多场景、多租户、真实外部写入与发布闭环。

**未实现的仍然是多数**：真实音频、真实链路资源与并发、自进化与发布门禁均未验收。真实模型只覆盖了文字通道的六条路径，导出恢复和 AG-UI 第一方客户端语料已单独验证，但不等于真实渠道端到端验收。后续每一阶段都必须以实际运行和验收数据替代文档假设。
