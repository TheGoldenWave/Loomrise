# Loomrise

> **状态（2026-09-27）：S0 文档 Gate 已完成；S1 纵向样例代码已落地，已有 10/10 确定性案例回放记录，但 S1 退出 Gate 尚未全部通过。** 本次基础自检 20 条断言通过，完整回放因当前 Python 缺少依赖未重跑。AgentScope 与 Pipecat 的源码级与安装级证据已有记录；**真实模型、真实音频、取消确认、导出恢复及运行级指标仍待验证**，尚无公开服务。当前进度见[验证路线](docs/ROADMAP.md)。项目名已定为 **Loomrise**；命名记录见 [命名决策](docs/NAMING.md)，验证结论见 [S1 验证结论与轻量适配](docs/S1-VALIDATION-AND-ADAPTATION.md)，交付与验收对照见 [S1 交付与验收](docs/S1-BUILD-REPORT.md)，版本钉见 [VERSION-PINS.md](VERSION-PINS.md)。

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
9. [开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md)
10. [命名决策](docs/NAMING.md)

## S1 代码：怎么跑

回放使用**脚本化确定性模型**，不需要 API 密钥，也不需要音频设备。以下为运行入口；当前 `requirements.txt` 仅锁发行包版本，未锁到实际验证的 AgentScope main 快照 `a388212`，所以安装复现尚待补齐，不能视为已验证的一键安装：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m loomrise.cli replay --out runs/replay-s1.json   # 10/10 案例
PYTHONPATH=. .venv/bin/python -m loomrise.cli voice-sim                          # 播放四态回归
PYTHONPATH=. .venv/bin/python -m loomrise.cli run --text "数据分析入门这门课多少钱？"
PYTHONPATH=. .venv/bin/python tests/test_s1.py                                   # 自检
```

语音 Worker（Pipecat）需单独环境，且有一个安装前置（`docopt` 无 wheel），见 [VERSION-PINS.md](VERSION-PINS.md)。

## 当前确认 / 尚未确认

- **确认（产品决策，尚未实现）**：核心使用者为 AI 产品经理／解决方案人员／小团队开发者；首个完整交付场景为明确标注虚构的成人在线课程咨询；单一工作台、统一执行内核、分类适配器、首版单 Agent、发布前固定测评集门禁；网页文字与网页语音共享同一业务请求与运行证据。
- **已实现的最小切片**：命令行执行、业务合同、模型外规则、模拟预约、上下文审计、模拟语音入口及事件投影；不含网页界面。10/10 是已有确定性回放记录，不是真实模型或音频验收。
- **待验证/补齐**：AgentScope 实际 commit 的依赖锁定与干净环境复现；完整取消确认；跨渠道同一请求专项测试；Pipecat 中文网页音频链路；导出恢复、AG-UI 一致性、时延与资源；单机和服务端部署规模；评测与受控改进闭环。
- **待决策**：开源许可证；公共 Demo 的额度与 BYOK 策略；首个 IM/外呼供应商及真实电话是否立项；场景级测评阈值；判别式决策 Provider 是否进入默认安装。

公开仓库只发布经过整理、可以脱离个人语境独立理解的结论，以及可复现的计划、代码和证据。尚未确认的讨论、个人判断和商业化假设保留在本地 `private/` 工作区；分类与晋升规则见 [开源与私有工作区边界](docs/OPEN-SOURCE-BOUNDARY.md)。

不会使用雇主或第三方的私有代码、真实客户数据、内部 Prompt、未获授权的业务材料或个人敏感信息。对外 Demo 只展示原创或有权复用的资料，并明确标注模拟数据。电话外呼、企微／钉钉均不属于初始可运行承诺。

本仓库目前完成了 **S0 的产品定位、架构边界、开源边界、接入与评测规范**，以及 **S1 的接入方验证结论、轻量适配范围与纵向样例代码**（源码级、安装级与案例回放证据）。S1 代码覆盖的是"用户发起对话后，Agent 在证据、权限和业务结果约束下完成一次可回放请求"这一条纵向切片，不含 B 端工作台、多场景、多租户、真实外部写入与发布闭环。

**未实现的仍然是多数**：真实模型、真实音频、时延与资源、导出包恢复、AG-UI 一致性、自进化与发布门禁都在 S2 之后。后续每一阶段都必须以实际运行和验收数据替代文档假设；源码级与安装级结论不得当作运行已完成。
