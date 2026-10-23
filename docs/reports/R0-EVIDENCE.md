# R0 证据摘要 v0.2

> 2026-10-23 起。**规则见 [Gate 追溯矩阵](../RELEASE-GATE-MATRIX.md) §0 第 4 条**：原始件留在本地 `runs/r0/`（已被 gitignore），本文件只记**结论 + 样本量 + 环境 + 局限**，并给原始件名。矩阵的"证据位置"列指向本文锚点。
>
> **本文件不代替验收。** 写"部分"的地方就是部分，不往上凑。
>
> v0.2 增补：媒体通道（`/ws/voice`）已实现并跑通**服务端 ↔ 云端**；**浏览器麦克风仍未验证**（见 M-S1-08 的"为什么不能勾"）。

## 环境

| 项 | 值 |
|---|---|
| 机器 / 系统 | macOS darwin arm64，Apple 芯片 |
| Python | 3.13.12（仓库根 `.venv`，92 wheel 离线锁安装） |
| SDK | `dashscope==1.27.7`、`agentscope==2.0.8` |
| 语音地域 | 华北2（北京），Workspace 专属域名 |
| 网络 | 家用宽带；**未做弱网档** |

---

## M-S1-08 真实网页音频 — **未开始**（通道已建，麦克风未验）

**通道建好了，但这一行不能勾。** Gate 要的是"真人对着浏览器麦克风说话，音频经服务端链路被识别"；本轮所有音频都是 **TTS 合成后直接喂 ASR**——没有一次经过浏览器采集。

`loomrise/web.html` 已从 `webkitSpeechRecognition` 换成：`getUserMedia` → `AudioWorklet`（降采样到 16 kHz）→ `Int16` → WebSocket 上行。代码在，但**没有在真浏览器里跑过**：

| 尝试 | 结果 |
|---|---|
| 无头 Chromium（`--use-fake-device-for-media-stream`） | `getUserMedia` 与 `new AudioContext()` **双双挂死**（5–6 s 超时无返回） |
| 有头 Chromium（窗口移出屏幕，真实音频栈） | 同样挂死 |
| 结论 | 本机这个 Chromium 构建的 WebAudio / 媒体栈在自动化环境里不可用，**属环境限制，不是代码结论** |

已做的替代验证：`web.html` 脚本通过 `node --check` 语法检查；状态机逻辑人工通读；WS 协议层由 `tests/test_voice_ws.py` 33 项覆盖。**这些都不证明"麦克风能用"。**

**关闭条件**：人工在本机 Chrome/Safari 打开试用页，点「录音」说一句，`#input` 出现正确文本，`runs/r0/voice/ws-*.jsonl` 里出现 `mic.first_frame` 与 `asr.final`。

## M-S1-09 固定中文 STT/TTS 组合 — **部分**

| 项 | 结论 |
|---|---|
| 组合已定 | ASR `fun-asr-realtime-2026-02-28` + TTS `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6`，参数 `pcm` / `16000` / `language_hints=[zh]` |
| 登记位置 | [VERSION-PINS §8](../../VERSION-PINS.md)（模型、音色、参数、首包、SDK 版本、通道协议） |
| 已证 | 服务端可直连两个端点；`dashscope 1.27.7` 无需升级即可调 `qwen-audio-3.0-*`；**流式 TTS 确实分块推送**（见下"媒体通道"） |
| **未证** | ① 浏览器侧真实采集（同 M-S1-08）；② **TTS 是别名，无日期快照**，只能记"别名锁定 + 核验日" |
| 原始件 | `runs/r0/voice/asr-multi-*.log`、`runs/r0/voice/tts-firstpkt-*.log`、`runs/r0/voice/smoke-*.json` |
| 局限 | 合成语音仅 1–2 句；未做多轮"同输入是否同字节"一致性 |

## M-S1-10 中文可懂度 — **未开始**

未做。需要注册语料 + 判读人。**本轮所有"逐字一致"都是合成语音对合成语音的闭环，不能当可懂度证据**——真人语料还没进过这条链路。

## M-S1-11 首响 — **部分**

| 项 | 结论 |
|---|---|
| TTS 首包（服务端计时） | **331.9 / 339 / 364.7 / 371 / 402.1 / 411 ms**（6 次，**全部新建连接**，含握手） |
| 流式分块 | 一句 26 字 → **13 块**、188 KB；首块 388 ms，末块 1007 ms（边合成边可播） |
| ASR 端到端 | 2.0–3.0 s（音频总长 4.9–8.6 s，按 20 ms/帧推送；**这是推流节奏的产物，不是 ASR 延迟**） |
| **未证** | ① 样本量仍不足（要求 ≥10 轮）；② 未分"新建连接 / 复用连接"两组；③ 无弱网档；④ **浏览器整链首响（采集→上行→识别→合成→播放）完全没有样本** |
| 原始件 | `runs/r0/voice/tts-firstpkt-*.log`、`runs/r0/voice/smoke-*.json` |

## M-S1-13 停止时延 p95 — **埋点就位，无样本**

浏览器侧已埋三个点：打断触发时刻、音频节点停止时刻、首帧播放时刻；服务端记录 `tts.cancel` 与 `tts.done.cancel_ms`。**但一个样本都没跑**（浏览器音频栈不可用）。

口径必须分开写，见 [D-05](../VOICE-ARCHITECTURE-DECISIONS.md)：浏览器侧量到的是"指令 → `AudioBufferSource` 停止"，**不含扬声器与系统混音缓冲**；声学级时延只能录音回采测。两者不能用一个数字顶。

## M-S1-12 真实模型 SSE — **未开始**

待做：`python -m loomrise.cli web --port 8765`（不加 `--scripted`）+ 客户端收流留档。本轮启动的都是 `--scripted`，只验了媒体通道，**没有产生真实模型 SSE 证据**。

---

## 媒体通道实测（服务端 ↔ 云端，不含浏览器）

`scripts/voice_ws_smoke.py`：起真服务 → WS 连 `/ws/voice` → 上行 TTS 合成的 PCM → 收 `asr.final`/`asr.closed` → 发 `tts.speak` → 收二进制音频块。

| 轮次 | 源音频 | 识别 `end_ms` | 丢弃字节 | 下行音频 | TTS 首块 |
|---|---|---|---|---|---|
| 第 1 次（**有缺陷**） | 4.93 s | 3080（截断） | **50880** | 5.33 s | 331.9 ms |
| 第 2 次（**有缺陷**） | 4.69 s | 3080（截断） | **50880** | 5.33 s | 364.7 ms |
| 第 3 次（修好后） | 4.85 s | **4640** | **0** | 5.49 s | 402.1 ms |

第 3 次识别文本：`你好，我想问一下成人在线课程的价格晚上有课吗？`（原文含一个逗号，标点被省，语义完整）。

**这两次"截断"值得单独记**：表面现象是"服务端在 3.08 秒判了句尾"，实际是自己把后半段音频丢了——背压计数器只累加不递减，越过上限后永久丢帧。教训写进 [D-05](../VOICE-ARCHITECTURE-DECISIONS.md) 第 2 条：**背压必须读真实队列**。

原始件：`runs/r0/voice/smoke-*.json`、`runs/r0/voice/smoke-downlink-*.pcm`、`runs/r0/voice/ws-*.jsonl`（会话时序）。

---

## 一次闭环的实际输出（留档）

```
[tts] bytes=138240 first_pkg_ms=364 text_len=24
[asr] FINAL t=120-4120 你好，我想了解一下成人在线课程的价格和上课时间。
[asr] match= True
```

三条 ASR 候选在同一段合成语音上：

| 模型 | 结果 | 端到端 |
|---|---|---|
| `fun-asr-realtime-2026-02-28` | 逐字一致 | 1.97–1.98 s |
| `paraformer-realtime-v2` | 逐字一致 | 2.02–2.12 s |
| `qwen-audio-3.0-asr-flash-streaming` | 逐字一致 | 2.07–2.97 s |

**这张表不能用来选型**：三个都满分，说明这段合成分太干净，没有区分度。选型仍按"能否钉快照"——只有 `fun-asr-realtime-2026-02-28` 能。
