# S1 交付与验收 v0.4

状态：**真实模型（Coding Plan · `gpt-6-sol` 验收默认档）六路径 11/11 通过，离线 wheelhouse/哈希锁与 HTTP-SSE 消费已验证；S1 Gate 仍未全部通过**。验收证据截至 2026-09-28；2026-10-13 同步不支持语音识别时的页面入口描述，未新增 S1 Gate 证据。
本文件是 QA 对照用的验收文档：每条 Gate 指向可复述的证据或命令，不把规划写成已完成。
真实模型的咨询/确认/拒绝/失败/取消/跨渠道与首响数字见 §4.2；**网页音频与浏览器实测仍为空**，只有脚本回放的时延/资源样本，见 §5。

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
  local_config.py                 本机 Coding Plan 凭据（~/.config/loomrise，0600，仓库外）
  web.py / web.html               回环监听的网页入口：AG-UI SSE + 页面人工确认/拒绝/取消
scripts/
  build_offline.py                平台专用 wheelhouse + SHA-256 哈希锁
  verify_offline.sh               离线安装 → 回放 → 自检 → 导出包离线恢复，一遍跑完
scenarios/course_consult_v1/       虚构场景包：pack.json + 11 个人工审定案例
tests/test_s1.py                   自检脚本（不依赖 pytest）
runs/replay-s1.json                旧回放报告（10/10）；本次新报告在临时目录（11/11）
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

### 3.3 版本钉：已锁定 `a388212`

见 [`VERSION-PINS.md`](../VERSION-PINS.md)。`requirements.txt` 使用完整 VCS commit；源码版本字符串仍为 2.0.8，不以发行 tag 代替。

## 4. Gate 对照

复现命令（无需密钥，脚本化确定性模型）：

```bash
cd <repo> && PYTHONPATH=. s1-verify/bin/python -m loomrise.cli replay --out runs/replay-s1.json
```

| S1 Gate | 结果 | 证据 |
|---|---|---|
| 文字和语音使用同一个 `request_id`、`AgentVersion`、权限判断和业务结果 | **通过（脚本模型 + 真实模型）** | `test_cross_channel_same_request`：文字发起 → 模拟语音确认 → 文字重复提交，同请求 ID/版本/权限与结果 ID；真实模型下"文字发起被拒 → 语音确认"同请求、总写入 1 次（§4.2）。真实媒体（麦克风/扬声器）仍未测 |
| 同一确认最多产生一次模拟业务写入，并有稳定 `result_id` | **通过** | `c2_booking_confirmed`（写 1 次，有 `result_id`）；`c8_duplicate_write`（同幂等键第二轮被拒，总写入仍为 1） |
| 失败、取消、超时、未知播放状态可在 `RunEvent` 中区分 | **模拟通过，真实打断待验证** | `c11_cancel_before_write` 验证 `run.cancel_requested` → `run.cancel_confirmed` 且零写入；`c3/c6/c7` 与合成打断覆盖其他状态。已写入结果不宣称可撤销 |
| 固定输入、版本和模拟环境可再次回放 | **通过** | `replay` 连续两次运行结果一致；报告写入 `runs/replay-s1.json` |
| 导出包可在干净目录恢复配置和模拟结果 | **通过（联网 + 离线两种路径）** | 导出目录独立创建新虚拟环境，安装导出依赖、加载包并 11/11 回放；不依赖原工作区或 `_reference/`。`export --offline` 附带 wheelhouse 与哈希锁，第二个干净环境 `--no-index --require-hashes` 安装后再 11/11 |
| 依赖可离线、可哈希校验地固定 | **通过（仅 macOS arm64 / CPython 3.13）** | 92 个 wheel 逐条 SHA-256 写入 `requirements-offline-macos-arm64-py313.txt`；`bash scripts/verify_offline.sh` 复现；自检 `test_offline_lock` 守着"有锁就必须有哈希和 wheel" |
| 客户端经 HTTP/SSE 消费 Loomrise 事件 | **代码级通过（脚本模型），真实模型下待人工实测** | `test_web_sse` 起真实 TCP 站点 + HTTP 流式消费 AG-UI 事件，覆盖事件顺序、跨渠道同请求、页面确认/拒绝/取消。真实模型下的 SSE 链路与页面已就绪（`python -m loomrise.cli web`，`/api/status` 返回 `configured: true`），但事件流由真实模型驱动时的消费尚未形成留档 |
| 记录固定版本、许可证、安装步骤 | **核心通过，语音待重跑** | 完整 commit VCS pin、`pip freeze` 与 `pip check`、独立导出恢复；Pipecat 版本/许可证为历史安装证据 |
| 至少能回答：本轮加载了哪些上下文、哪些被跳过、为什么跳过、是否因预算截断、对应版本 | **通过** | `audit` 命令 / 每条报告的 `context_audit`：`loaded` / `skipped`(含 `skip_reason`) / `expired` / `budget_capped` |
| 资源占用、首响、打断、失败项（运行级） | **仅模拟基线** | 脚本回放样本见 §5；真实模型/网页语音仍未测，Gate 不通过 |

### 案例回放（11/11，脚本模型）

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
| c11_cancel_before_write | 确认点取消 | cancelled | 0（执行端确认停止） | PASS |

`voice-sim` 额外验证播放四态：打断后未确认的片段全部落到 `unknown`，`confirmed` 为空——**未知不是成功**。

### 本次重新运行（2026-09-27）

- 新建两个隔离虚拟环境：核心环境从 `requirements.txt` 安装，导出目录从自身的同名文件安装；两处 `pip freeze` 均显示 `agentscope @ git+https://github.com/agentscope-ai/agentscope.git@a38821287f35e9e45ed193d9d864cb46f263c946`，`pip check` 均无冲突。
- 核心环境运行 `python tests/test_s1.py` 全部通过，`loomrise.cli replay` 11/11；导出环境从导出目录运行 `loomrise.cli replay` 11/11。两份回放及事件 JSONL 在临时目录，未作为公开原始日志提交。
- AG-UI 上游参考树 commit `b8ebd02`：用 pnpm 10.33.4 执行第一方 TypeScript 客户端 `src/conformance`，**69/69 通过**。这是上游客户端回归，不是 Loomrise 流接入客户端的端到端验证；Loomrise 自检另外用同一份 spec 1.0 schema 校验全部 11 个案例的投影事件，并对照取消 outcome 语料。
- 脚本回放的一次样本：macOS Apple 芯片、Python 3.13.15、11 案例，`/usr/bin/time -l` 得到 0.99s wall、0.65s user + 0.12s sys、峰值 RSS 90,554,368 字节；`c1` 事件时间从 `run.started` 到首条 `reply.text` 为 7ms（同轮结束亦为 7ms）。单次 CLI 启动、脚本模型与合成帧，**不能作为真实首响、音频打断恢复、典型延迟或容量指标**。模拟失败项：拒绝、工具 error、超时 unknown、取消与播放 unknown。
- 待执行的单一组合定为 `gpt-4o-mini`（`LOOMRISE_LIVE_MODEL`）+ OpenAI `whisper-1` STT + `tts-1`/`alloy` TTS；这是**待验证配置，不是已集成链路**。当前环境未提供 `OPENAI_API_KEY`，仓库无网页媒体入口及已验证 STT/TTS 组合，因此真实模型的咨询/确认/拒绝/失败及网页音频打断均未运行。设置真实模型名但缺密钥现在显式报错，不会静默回退脚本模型。

### 4.2 真实模型验收（2026-09-28 实跑，`gpt-6-sol` · Coding Plan Responses API · 验收默认档）

复现命令（需要本机凭据；无凭据时脚本直接退出，不会退回脚本模型冒充真实调用）：

```bash
PYTHONPATH=. .venv/bin/python scripts/live_model_check.py            # 默认档：local_config.DEFAULT_MODEL = gpt-6-sol，结果写入 runs/
PYTHONPATH=. .venv/bin/python scripts/live_model_check.py --model gpt-6-luna   # 成本对照档（非验收基线）
```

六条路径 11/11 通过（切档后用默认档重跑的报告：`runs/live-model-default-20260928-161013.json`，全部场景 `attempts=1`）：

| 场景 | 终态 | 写入 | 关键证据 |
|---|---|---|---|
| 咨询（"数据分析入门多少钱？"） | success | 0 | 答案 3980 元来自检索资料，无写入 |
| 确认写入 | success | 1 | `tool.call_start` 含 `create_booking`；`permission.decision` 出现 `require_confirm` → 人工 allow → 稳定 `result_id` |
| 拒绝 | failed | 0 | `permission.decision` 记 `deny`；零写入 |
| 工具失败（`failure_mode=error`） | failed | 0 | outcomes 记 `error`，不记为成功 |
| 确认前取消 | cancelled | 0 | `run.cancel_confirmed` + 零写入 |
| 文字发起被拒 → 语音确认 | success | 1 | 同一 `request_id`/版本，两轮合计只写一次 |

真实模型时延（本机 → Coding Plan 代理，单轮，含工具往返）：

| 场景 | 首响（`run.started` → 首个文本/工具产出） | 单轮总耗时 |
|---|---|---|
| 咨询 | 3.8 s | 9.8 s |
| 确认写入 | 3.2 s | 13.9 s |
| 拒绝 | 3.1 s | 18.0 s |
| 工具失败 | 4.8 s | 22.9 s |
| 确认前取消 | 3.0 s | 9.8 s |

这些是**本轮实测值，不是产品指标**：同时包含代理排队、模型自身时延和 Responses API 流式切分，未做多轮取样、未分离代理与模型耗时，也不代表其他模型档位。切换默认档为 `gpt-6-sol` 的直接原因是稳定性——同脚本下该档全部场景 `attempts=1`，不需要重试兜底；`gpt-6-luna` 的对照数据见下节。

真实模型暴露并被修掉的三处缺陷（都是脚本模型掩盖的）：

1. **资料里没有 `course_id`**：真实模型遵守"不补造事实"，因此拒绝调用 `create_booking`（脚本案例硬编码了 `data-analysis-101`）。已新增证据片段 `kb.course_catalog` 暴露 `course_id` 与可选时段。
2. **模型把"人工确认"理解成对话式提问**：SOP 说"用户确认后调用"，模型于是停在"请确认？"而永不调用写入工具。已把输出合同改为"确认由系统在工具调用前收集，模型不得用提问代替执行"。
3. **跨轮次丢历史**：每轮新建 Agent，真实模型第二轮看不到前文（脚本模型不依赖上下文，故未暴露）。现按 `request_id` 复用 `AgentState`，文字→语音续接可用。

顺带补齐一处可观测性缺口：人工拒绝后 SDK 不再回权限钩子，账本原本没有拒绝证据；现在 `drive_reply` 为每个答案显式落 `permission.decision`（`deny`），确定性回放 11/11 不受影响。

### 4.3 模型档位对照（同一脚本，只换模型名）

同一脚本、同一场景、只换模型名（`--model`）：

| 模型 | 角色 | 结果 | 首响 | 单轮总耗时 | 说明 |
|---|---|---|---|---|---|
| `gpt-6-sol`（1–1.5×） | **验收默认档**（`local_config.DEFAULT_MODEL`） | 11/11（跑 2 次） | 2.4–4.8 s | 7.2–22.9 s | 两次运行全部场景 `attempts=1`，未出现"停在提问不调用工具"；报告 `runs/live-model-gpt-6-sol-20260928-124258.json`、`runs/live-model-default-20260928-161013.json`。同档两次单轮耗时差异明显（如拒绝 13.4 s vs 18.0 s），属未做多轮取样的样本波动 |
| `gpt-6-luna`（0.05–0.1×） | 成本对照档（`--model gpt-6-luna`） | 11/11 | 10.8–14.8 s | 21.8–56.5 s | 最便宜，但指令跟随不稳定：观测到部分轮次不发起 `create_booking`（4 次运行中 1 次失败重试后通过）。脚本对需要写入工具的场景最多重试 3 次，`attempts` 写进报告；报告 `runs/live-model-20260928-123620.json` |

结论：提示改动本身有效（两个模型都能走到写入路径），但便宜档的稳定性与时延不适合当验收基线，因此**默认改为 `gpt-6-sol`，`gpt-6-luna` 只留作成本对照**——需要压低额度成本时可显式 `--model gpt-6-luna` 跑，但结论必须带上 `attempts` 与重试说明。两档都只是单轮单次样本，未做多次取样与方差统计。

### 本轮新增（2026-09-28 实跑）

| 新增 | 位置 | 验收结果 |
|---|---|---|
| HTTP/SSE 客户端消费 | `loomrise/web.py` + `web.html`（回环监听），AG-UI 事件经 `text/event-stream` 投送 | **通过（脚本模型）**：`test_web_sse` 起真实 TCP 服务 + HTTP 客户端流式消费，断言文字发起 → 语音继续 → 文字重复提交同源请求/版本/结果、写入仅一次、页面拒绝不写入、取消有 `cancelled` outcome。真实模型下的端到端仍未跑 |
| 网页语音 + 设备级播出回执 | 浏览器 Web Speech（`zh-CN` 识别 + `speechSynthesis` 播报） | **待人工实测**：回执链路有断言（播出完成/打断分别落 `confirmed`/`unknown`）；中文可懂度、首响、打断恢复数字仍缺 |
| 真实模型（改走 Coding Plan Responses API） | `local_config.py` + `build_model`（`OpenAIResponseModel`，默认 `gpt-6-sol`）+ `scripts/live_model_check.py` | **已实跑 11/11**：咨询/确认/拒绝/失败/取消/跨渠道六路径全通过，真实首响与单轮耗时见 §4.2；真实模型暴露的三处缺陷已修（见 §4.2）。凭据隔离：仓库外 `~/.config/loomrise/coding-plan.json`、0600、不覆盖、缺密钥不静默回退 |
| 离线 wheelhouse 与哈希锁 | `scripts/build_offline.py`、`scripts/verify_offline.sh` | **通过**：92 个 wheel 逐条 SHA-256；干净环境 `--no-index --require-hashes` 安装 → `pip check` → 11/11 回放 + 自检全通过 → `--offline` 导出 → 第二个干净环境离线恢复 11/11。仅 macOS arm64 / CPython 3.13 |

音频选型说明：**没有引入云端流式 ASR/TTS，也没有引入本地 ASR 运行时**。LifeSub 那套本地方案依赖桌面 Rust 运行时与模型下载，且不含 TTS；本轮先用浏览器原生中文识别与播报做零成本实机验证，代价是**能力跟随浏览器**（Chrome/Edge 可用；Safari 与 Firefox 支持不齐，不支持时不展示录音按钮）。这只是验证手段，不是最终形态——真实音频 Gate 仍要按 §5.2 用固定 STT/TTS 组合在浏览器外重测。

### 历史记录（替代前，2026-09-27）

- 原 Git HEAD 为 `2f0633a`（S0 文档 Gate）；S1 代码、虚构场景、测试和本报告此前尚未提交，属于本次公开同步范围。
- 本地旧 `runs/replay-s1.json` 的生成时间为 `2026-09-27T10:07:59`，汇总 10/10；此前完整自检因缺少 `pydantic` 中止。本次新运行证据见上节，不将旧文件当新报告。
- 本次另行核验已有报告中的逐例判定，以及 10 份 JSONL 账本的序号、前序哈希和内容哈希，共 214 条事件通过完整性检查；这只证明已有工件一致，不等于重跑或新增验收覆盖。
- 当前请求/模拟结果与幂等状态在内存中；CLI 事件 JSONL 的落盘不等于完整业务存储和重启恢复已完成。

## 5. 仍然未验证（不得据此宣称完成或生产可用）

1. **真实音频**：Pipecat 只做到"帧类名 → 播放状态机"的回归，未跑 STT/TTS/浏览器链路；中文可懂度、语音首响、打断恢复、弱网恢复均未测。浏览器 Web Speech 入口已就绪（`python -m loomrise.cli web`，本机 8765），但**必须由人在浏览器里实测并留档**。
2. **真实链路时延与资源**：真实模型首响/单轮耗时已有样本（§4.2），但只有单轮单次、未分离代理与模型耗时、未做多轮取样；内存/CPU、并发、单位成功任务成本仍无数据。
3. **客户端端到端协议**：第一方客户端语料 69/69、Loomrise 全 11 案例投影 schema 检查、`test_web_sse` 的真实 HTTP/SSE 消费断言，三者是独立证据且均已通过；但**都只在脚本模型下跑过**。真实模型驱动的事件流经 SSE 送入客户端尚未形成留档。
4. **模型档位稳定性**：默认档已切到 `gpt-6-sol`（两次运行共 10 个需写入场景全部 `attempts=1`），但仍是单轮少量样本，未做多轮取样与方差统计，不能写成"该模型长期稳定"。成本对照档 `gpt-6-luna` 会在部分轮次不发起写入工具（§4.3），靠脚本重试兜底；用它跑出的结论必须带上 `attempts`。
5. **同进程共存**：AgentScope 与 Pipecat 分装两个环境（符合"可选 Voice Worker"部署形态），未在同一进程内实测。
6. **持久化与外部撤销**：取消在当前执行任务中已专项验证，已完成写入无法撤销；重启后业务请求/幂等账本恢复、真实媒体跨渠道和真实业务撤销仍未实现。

## 6. 已知限制（代码层面）

- token 估算是启发式（中文 1 字≈1 token，西文 4 字符≈1 token），精度上限约 ±30%，只用于预算记账，不用于计费。
- `ScriptedChatModel` 只实现 `_call_api`，不实现真实协议；真实模型优先读本机 Coding Plan 凭据（`~/.config/loomrise/coding-plan.json`，走 Responses API），其次 `LOOMRISE_LIVE_MODEL` + `OPENAI_API_KEY`（缺密钥显式报错），两者都未配置时 `cli run` 仍会落到脚本模型——使用前先看 `/api/status` 的 `"configured"` 字段，不要把脚本输出当成真实模型结果。
- 幂等账本在 `ExecutionService` 进程内存中，重启即失；S2 需要持久化。直接依赖固定了 AgentScope commit、OTel、Pydantic 与 aiohttp；离线 wheelhouse 与哈希锁（`scripts/build_offline.py`）已实跑通过，但只针对 macOS arm64 / CPython 3.13，换平台要重跑并改名；语音 Worker 不在该锁内。
- 路由是关键词匹配（确定性），不是模型路由，也不支持条件表达式。
- 单租户（`tenant_demo`），未做租户隔离。
- 未传入确认回调时默认拒绝；回放显式传入脚本确认，CLI 没有人工确认界面，不代表生产级审批已实现。
