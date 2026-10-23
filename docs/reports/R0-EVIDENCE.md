# R0 证据摘要 v0.3

> 2026-10-23。**规则见 [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) §0 第 4 条**：原始件留在本地 `runs/r0/`（已 gitignore），本文件只记**结论 + 样本量 + 环境 + 局限**，并给原始件名。矩阵的"证据位置"列指向本文锚点。
>
> **本文件不代替验收。** 写"部分"的地方就是部分，写"未开始"就是没做——不往上凑。
>
> v0.3 变化：补 M-S1-01/02/03/05/06/07 的证据；M-S1-11 补 12 轮采样；M-S1-12 转"通过"（并修掉一个真实缺口）；M-S1-08/10/13/14 **仍不能勾**，原因逐条写清。

## 环境

| 项 | 值 |
|---|---|
| 机器 / 系统 | Apple M4 / macOS 15.6.1 / Apple 芯片 |
| Python | 3.13.12（仓库根 `.venv`，92 wheel 离线锁安装，95 个包） |
| 关键依赖 | `agentscope==2.0.8`（Apache-2.0）、`dashscope==1.27.7`、`aiohttp==3.14.3` |
| 浏览器 | Chrome 156.0.8078.47（仅用于人工实测，自动化不可用） |
| 语音地域 | 华北2（北京），Workspace 专属域名 |
| 网络 | 家用宽带；**未做弱网档** |
| 详细台账 | [依赖与资源台账](R0-DEPENDENCY-LEDGER.md) |

---

## 一、已通过的 Gate

### M-S1-01 跨模态共用同一请求 — **通过**

`tests/test_s1.py::test_cross_channel_same_request`：文字发起 → 语音续接 → 再文字重提。
断言：`request_id` 唯一、`agent_version` 唯一、`channel` 集合为 `{text, voice}`、两次写入只产生一个 `result_id`。
原始件：`runs/events/c8_duplicate_write.jsonl`。

### M-S1-02 同一确认最多一次写入 — **通过**

`c8` 案例：确认两次，写入计数 1，`result_id` 稳定；第二次被判 `dedupe`（不是 `deny`，两者区分见 M-S1-03）。
原始件：`runs/events/c8_duplicate_write.jsonl`。

### M-S1-03 失败/取消/超时/未知可区分 — **通过**

`ToolOutcome`（success/error/interrupted/denied/**unknown**）+ `PlaybackState`（generated/sent/**confirmed**/**unknown**）。
`test_s1.py` 覆盖 unknown 超时与"未确认播出不得记为用户已听见"；本轮新语义把"重复写入"从 deny 拆成 `dedupe`，四类互斥更清晰。

### M-S1-04 确定性回放 11/11 — **通过**

`.venv/bin/python -m loomrise.cli replay` → **11/11**，连续多次一致。
原始件：`runs/replay-s1.json`、`runs/events/*.jsonl`。

### M-S1-05 导出包可在干净目录恢复 — **通过**

`loomrise export --out /tmp/r0-export` → 在 `/tmp/r0-export` 内以该目录为 `PYTHONPATH` 跑 `replay` → **11/11**。
**局限**：复用了本项目已装好依赖的 `.venv`，**没有在新虚拟环境里装一遍**（离线 wheelhouse 未随包携带）。所以这证明"包自足到能跑"，不证明"从零装机"。

### M-S1-06 依赖与资源六字段 — **通过**

见 [依赖与资源台账](R0-DEPENDENCY-LEDGER.md)：版本、许可证、安装、资源（回放峰值 RSS 91.7 MB / 3.51 s）、首响、失败项（7 条，4 条未解决）。
**注意**：台账里 F-1 / F-6 正是 M-S1-08 / 13 / 14 通不过的原因。

### M-S1-07 上下文五问可审计 — **通过**（本轮修过）

`python -m loomrise.cli audit --ledger runs/events/<case>.jsonl` 一次答全：
加载了什么（含 `stage` 与 `tokens`）· 跳过什么 · 为什么（`skip_reason`）· 是否预算截断（`budget_capped`）· 对应规则与知识版本（`rules_hit` + `agent_version` + 每片的 `source_ref@source_version`）。
**本轮改动**：原输出把 `loaded` 裁成 id 列表，丢掉了 `source_version`——第五问在 CLI 上根本不可答，只有底层 `audit_answer()` 有。已补齐。

### M-S1-12 真实模型驱动的客户端 SSE — **通过**（本轮修过一个真缺口）

`scripts/sse_live_check.py`：非脚本模式起服务 → 客户端消费 `/api/runs` 流。
实测时间轴（一次运行）：`RUN_STARTED 236ms → TOOL_CALL 2.8s → TOOL_CALL_RESULT 4.6s → STEP 9.1s → TEXT_MESSAGE_START/CONTENT/END 9.1s → RUN_FINISHED → CUSTOM(summary)`，端到端 9.1 s，回复 131 字。

**修掉的缺口**：真实 provider 的 `TextBlockEndEvent.text` 是 `None`，账本里只留下一条**空文本**的 `reply.text`，投影层因类型不符跳过它 → 前端一直靠 `summary` 兜底，看起来"能用"，实际**没有任何文本事件**。现在空文本不再 emit，`reply.final` 补发一次。

**局限**：文本是**整块**到达（在 `reply.final` 处一次性发出），不是逐字流式。要真流式得消费 provider 的增量事件，属 S2 的体验项，不在 R0。

**模型标识必须分开读**：`AgentVersion.model` 声明 `scripted-s1`，本机配置实际调用 `gpt-6-sol`，两者**不一致**（`model_matches_declared=false`）。留档已分三个字段记录，不合并。
原始件：`runs/r0/sse/sse-*.json`。

### M-S1-17 真实模型六路径 11/11 — **见下节**

---

## 二、部分完成（不能勾"通过"）

### M-S1-09 固定中文 STT/TTS 组合 — **部分**

| 项 | 结论 |
|---|---|
| 组合已定 | ASR `fun-asr-realtime-2026-02-28` + TTS `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6`，`pcm` / `16 kHz` / `language_hints=[zh]` / `max_sentence_silence=1500` |
| 登记位置 | [VERSION-PINS §8](../../VERSION-PINS.md) |
| 已证 | 服务端直连两个端点；`dashscope 1.27.7` 无需升级；流式 TTS 分块推送（26 字 → 13 块） |
| **未证** | ① 浏览器侧真实采集（同 M-S1-08）；② **TTS 是别名，无日期快照**，只能记"别名锁定 + 核验日" |
| 原始件 | `runs/r0/voice/asr-multi-*.log`、`tts-firstpkt-*.log`、`latency-*.csv`、`smoke-*.json` |

**这一行不会因为"跑得很顺"变成通过**：别名风险是结构性的，不是调优能解决的。

### M-S1-11 首响 — **部分**

12 轮服务端采样（`runs/r0/voice/latency-20261023T051025Z.csv`）：

| 指标 | n | p50 | p95 | max |
|---|---|---|---|---|
| TTS 首包 | 12 | 344 ms | 378 ms | 379 ms |
| ASR 首个部分结果 | 12 | 227 ms | 288 ms | 345 ms |
| 推流结束 → 最终文本 | 12 | 131 ms | 201 ms | 234 ms |
| 识别一致 | 12/12 | — | — | — |

**未证**：① 浏览器整链（采集→上行→识别→合成→播放）**零样本**；② 无弱网档；③ 推流按 5 倍实时，不是真实语速。
`M-S1-11` 的 Gate 说"首响"，用户感知的那一段恰好是没测的那一段，所以只能记部分。

---

## 三、未开始（原因不分淡）

### M-S1-08 真实网页音频 — **未开始**

通道已建（`/ws/voice` + `AudioWorklet` + `getUserMedia`），**但没有一次真人对着浏览器麦克风说过话**。

| 尝试 | 结果 |
|---|---|
| 无头 Chromium（假麦克风） | `getUserMedia` 与 `AudioContext` 双双挂死（5–6 s 无返回） |
| 有头 Chromium（窗口移出屏幕） | 同样挂死 |
| 结论 | 本机 Chromium 媒体栈在自动化环境不可用，**属环境限制，不是代码结论** |

**关闭条件**：人工打开试用页点「录音」说一句，`#input` 出文本，`runs/r0/voice/ws-*.jsonl` 出现 `mic.first_frame` 与 `asr.final`。

### M-S1-10 中文可懂度 — **未开始**

需要注册语料 + 判读人。**本轮所有"逐字一致"都是合成语音对合成语音**，不能当可懂度证据。

### M-S1-13 停止时延 — **未开始**

埋点已就位（浏览器侧三个时刻 + 服务端 `tts.cancel` / `cancel_ms`），阈值已登记（[登记表](R0-VOICE-THRESHOLD-REGISTRY.md) p95 ≤ 300 ms，时间戳早于采样），**但一个样本都没有**——播放侧依赖浏览器音频栈，与 M-S1-08 同因。

### M-S1-14 声学级误停 — **未开始**

注册噪声语料未建。用合成音频冒充"电视/旁人/键盘"会让"0 次误停"变成自证。

### M-S1-15 / M-S1-16 — **未覆盖（S2-c）**

P1 说话人级、P2 语义级。R0 验收记录里显式标注，不冒充。

---

## 四、媒体通道实测（服务端 ↔ 云端，不含浏览器）

| 项 | 结论 |
|---|---|
| 上行识别 | 4.85 s 音频 → `end_ms=4640`、`dropped=0`、文本完整 |
| 下行合成 | 5.49 s 音频、首块 402 ms（边合成边可播） |
| 背压 | 修前 `dropped=50880`（伪装成服务端截断）→ 修后 0 |
| 协议层 | `tests/test_voice_ws.py` 33 项（不触网，fake 适配器） |

原始件：`runs/r0/voice/smoke-*.json`、`smoke-downlink-*.pcm`、`ws-*.jsonl`。

---

## 结论：R0 还不能退出

17 行里 **8 行通过**（01/02/03/04/05/06/07/12）、**2 行部分**（09/11）、**4 行未开始**（08/10/13/14）、**2 行未覆盖**（15/16）、1 行待定（17）。

未通过的五项里有 **四项同一个根因**：本机浏览器媒体栈在自动化环境不可用 → 麦克风与播放都没法验。这不是代码问题，是必须人工做一次的问题。

**代码侧 R0 已完成**（合同四层、九条校验、媒体通道、SSE 文本事件），**验收侧 R0 未完成**，缺口集中在"真人 + 真麦克风 + 真语料"。
