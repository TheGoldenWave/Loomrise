# S1 交付与验收 v0.2

状态：**代码已落地，已有 10/10 人工审定案例的确定性回放记录，S1 Gate 未全部通过**，2026-09-27。
本文件是 QA 对照用的验收文档：每条 Gate 指向可复述的证据或命令，不把规划写成已完成。
运行级（L-D）结论仍为空——真实模型、真实音频、时延与资源均未实测，见 §5。

## 1. 交付物

```text
loomrise/                          S1 执行内核（7 个模块 + 3 个适配器）
  contracts.py                     领域合同：ServiceRequest / RunEvent / SkillManifest /
                                   ToolManifest / HardRule / AgentVersion / ScenarioPack / Case
  ledger.py                        RunEvent 账本：追加写入 + 哈希链 + 完整性校验
  context.py                       三段式上下文加载 + 压缩边界（CompactionPolicy）
  rules.py                         硬规则裁决（模型外、确定性）+ 幂等写入账本
  tools.py                         只读知识检索 + 模拟业务写入（含 unknown 结果态）
  service.py                       ExecutionService：文字/语音共用同一业务请求
  cli.py                           run / replay / voice-sim / export / audit
  adapters/
    agentscope_runtime.py          AgentScope 适配：中间件 + 事件投影 + 脚本化确定性模型
    voice.py                       Pipecat 适配：播放四态账本（自建"已确认播出"）
    projection.py                  AG-UI 单向投影 + OTel 属性映射与可选导出
scenarios/course_consult_v1/       虚构场景包：pack.json + 10 个人工审定案例
tests/test_s1.py                   自检脚本（不依赖 pytest）
runs/replay-s1.json                最近一次回放报告（10/10）
VERSION-PINS.md                    版本钉与安装证据
```

## 2. 复用 vs 自建

原则：**能复用就不造轮子；必须自建的只有"上游不提供且产品需要承担责任"的那部分。**

| 能力 | 来自 | 说明 |
|---|---|---|
| Agent 循环、工具调用、ReAct、事件流 | **AgentScope**（`Agent` / `Toolkit` / `FunctionTool` / `reply_stream`） | 全部用上游公开能力，未 fork |
| 权限挂点 | **AgentScope** `MiddlewareBase.on_check_permission` | 复用挂点，**裁决逻辑换成 Loomrise 硬规则** |
| 人工确认与恢复 | **AgentScope** `RequireUserConfirmEvent` / `UserConfirmResultEvent` | 复用状态机，确认在模型外收集 |
| 压缩挂点 | **AgentScope** `MiddlewareBase.on_compress_context` | 复用挂点，**不调用 `next_handler`** 即不让原生压缩生效 |
| 轮次、打断、传输 | **Pipecat**（`InterruptionFrame`、turn 策略、transport） | S1 用合成帧回归播放状态机，未接真实音频 |
| 前端事件协议 | **AG-UI** spec 1.0 | 只做单向投影；确认/取消走 `CUSTOM`（1.0 的 31 类事件里没有对应类型） |
| 跨服务追踪 | **OpenTelemetry**（GenAI 属性子集） | 只作投影，不承担业务事实；semconv 自 pin |
| **业务请求与终态** | 自建 | `ServiceRequest` + 终态只看持久化证据 |
| **上下文加载审计** | 自建 | 逐片段 加载/跳过/过期/预算截断 全部落 `RunEvent` |
| **`unknown` 结果态** | 自建 | 上游 `ToolResultState` 无此态，超时回执未知不得记成功 |
| **"已确认播出"** | 自建 | 上游只有服务端口径播放边界，无设备级回执 |
| **幂等与去重** | 自建 | 同一幂等键跨轮次/跨渠道只写一次 |

## 3. 三个决策问题的落地

### 3.1 上下文压缩冲突：不是 S1 特有，S1 只是止血

- **冲突本身是长期结构性的**：只要产品要回答"模型本轮实际看到了什么、为什么"，未经登记的隐式改写（自动压缩、工具结果截断、运行时注入、图片卸载）就不被允许。S2 之后同样成立。
- **S1 特有的只是"先关掉"**：`InjectionConfig(inject_runtime_state=False)` 关掉四维注入 + `ContextGuardMiddleware.on_compress_context` 不调用 `next_handler`。
- **长期不禁止压缩，而是收编**：`CompactionPolicy` 已预留 `loomrise` 模式；编排器未实现前调用即抛错，不允许把上游压缩包装成 Loomrise 压缩。
- **fail-closed 的表现**是上下文超限时在模型边界显式失败，而不是静默改写。

### 3.2 命名：`Task` → `ServiceRequest`，`Skill` 与 `app/` 维持原判

见 [`NAMING.md`](NAMING.md)。要点：`ServiceRequest` 更准确（跨多轮、含多次 Run、带业务终态）；`SkillManifest` 与上游 Markdown 目录 `Skill` 是"合同 vs 载体"的区别；`app/`（含 IM channel 与 ag-ui 中间件）不采用，但 AG-UI **映射关系**可参照实现。

### 3.3 版本钉：改钉 `a388212`

见 [`VERSION-PINS.md`](../VERSION-PINS.md)。基线由发行 tag `v2.0.8`/`c7d8e31` 改为实际使用的 main 快照 `a388212`；报告中一律标注"源码版本字符串 2.0.8"。

## 4. Gate 对照

复现命令（无需密钥，脚本化确定性模型）：

```bash
cd <repo> && PYTHONPATH=. s1-verify/bin/python -m loomrise.cli replay --out runs/replay-s1.json
```

| S1 Gate | 结果 | 证据 |
|---|---|---|
| 文字和语音使用同一个 `request_id`、`AgentVersion`、权限判断和业务结果 | **部分** | `c9_voice_same_request` 验证模拟语音调用共用执行内核；未覆盖同一请求从文字切换到语音的专项断言，真实媒体链路未接 |
| 同一确认最多产生一次模拟业务写入，并有稳定 `result_id` | **通过** | `c2_booking_confirmed`（写 1 次，有 `result_id`）；`c8_duplicate_write`（同幂等键第二轮被拒，总写入仍为 1） |
| 失败、取消、超时、未知播放状态可在 `RunEvent` 中区分 | **部分** | `c3`（denied）、`c6`（error）、`c7`（unknown）与模拟播放打断已有记录；`cancel()` 仅发出 `run.cancel_requested`，不实际中止执行或确认撤销，无取消专项案例 |
| 固定输入、版本和模拟环境可再次回放 | **通过** | `replay` 连续两次运行结果一致；报告写入 `runs/replay-s1.json` |
| 导出包可在干净目录恢复配置和模拟结果 | **部分** | `export` 命令已实现（场景包 + 代码 + requirements + README）；**未在新目录实跑恢复** |
| 记录固定版本、许可证、安装步骤 | **部分** | `VERSION-PINS.md` 已记录历史安装证据；`requirements.txt` 的 `agentscope==2.0.8` 未锁到验证快照 `a388212`，干净安装复现未完成 |
| 至少能回答：本轮加载了哪些上下文、哪些被跳过、为什么跳过、是否因预算截断、对应版本 | **通过** | `audit` 命令 / 每条报告的 `context_audit`：`loaded` / `skipped`(含 `skip_reason`) / `expired` / `budget_capped` |
| 资源占用、首响、打断、失败项（运行级） | **未验证** | 需真实模型与真实音频，见 §5 |

### 案例回放（10/10）

| 案例 | 场景 | 期望终态 | 期望写入 | 结果 |
|---|---|---|---|---|
| c1_consult_success | 咨询课程价格 | success | 0 | PASS |
| c2_booking_confirmed | 确认后预约 | success | 1 | PASS |
| c3_booking_rejected | 用户拒绝 | failed | 0 | PASS |
| c4_missing_material | 资料缺失 | success | 0（说明缺失，不补造） | PASS |
| c5_deny_unknown_course | 硬规则拒绝 | failed | 0 | PASS |
| c6_tool_error | 工具失败 | failed | 0（error） | PASS |
| c7_timeout_unknown | 工具超时 | failed | 0（unknown） | PASS |
| c8_duplicate_write | 重复提交 | success | 1（第二次被去重） | PASS |
| c9_voice_same_request | 语音入口 | success | 1 | PASS |
| c10_budget_capped | 上下文预算截断 | success | 0（记录 budget_capped） | PASS |

`voice-sim` 额外验证播放四态：打断后未确认的片段全部落到 `unknown`，`confirmed` 为空——**未知不是成功**。

### 本次 Git 进度复核（2026-09-27）

- 原 Git HEAD 为 `2f0633a`（S0 文档 Gate）；S1 代码、虚构场景、测试和本报告此前尚未提交，属于本次公开同步范围。
- 本地 `runs/replay-s1.json` 的生成时间为 `2026-09-27T10:07:59`，汇总 10/10、失败 0；这是已有记录，**不是本次重新执行完整回放所得**。运行报告和事件日志保持 Git 忽略，不上传原始日志。
- 本次用 Python 3.13.15 执行 `python3 tests/test_s1.py`：账本、硬规则、上下文、压缩边界、播放状态和事件投影共 **20 条断言通过**；进入案例回放时因缺少 `pydantic` 中止，完整自检未通过，也未验证 SDK 兼容性。
- 本次另行核验已有报告中的逐例判定，以及 10 份 JSONL 账本的序号、前序哈希和内容哈希，共 214 条事件通过完整性检查；这只证明已有工件一致，不等于重跑或新增验收覆盖。
- 当前请求/模拟结果与幂等状态在内存中；CLI 事件 JSONL 的落盘不等于完整业务存储和重启恢复已完成。

## 5. 仍然未验证（不得据此宣称完成或生产可用）

1. **真实模型**：回放全部用脚本化确定性模型；真实模型在同一配置下的路由、工具调用与拒绝行为未测。
2. **真实音频**：Pipecat 只做到"帧类名 → 播放状态机"的回归，未跑 STT/TTS/浏览器链路；中文可懂度、首响、打断恢复、弱网恢复均未测。
3. **时延与资源**：首响、轮次延迟、内存/CPU、单位成功任务成本均无数据。
4. **导出包恢复**：`export` 已实现但未在干净目录实跑恢复。
5. **AG-UI 一致性**：投影已实现，未跑 `spec/1.0/conformance/streams/*.json` 第一方语料。
6. **同进程共存**：AgentScope 与 Pipecat 分装两个环境（符合"可选 Voice Worker"部署形态），未在同一进程内实测。
7. **完整取消与跨渠道请求**：仅有取消请求事件，未实现中止和撤销确认；同一请求文字/语音切换尚无专项验收。
8. **干净环境安装**：发行包版本不等于验证 commit；需锁定实际 SDK 构件并重跑完整自检与回放。

## 6. 已知限制（代码层面）

- token 估算是启发式（中文 1 字≈1 token，西文 4 字符≈1 token），精度上限约 ±30%，只用于预算记账，不用于计费。
- `ScriptedChatModel` 只实现 `_call_api`，不实现真实协议；真实模型走 `LOOMRISE_LIVE_MODEL` + `OPENAI_API_KEY`（未实测）。
- 幂等账本在 `ExecutionService` 进程内存中，重启即失；S2 需要持久化。
- 路由是关键词匹配（确定性），不是模型路由，也不支持条件表达式。
- 单租户（`tenant_demo`），未做租户隔离。
- 未传入确认回调时默认返回同意，仅适用于确定性模拟；尚无可供真实用户操作的确认界面，不代表生产级审批已实现。
