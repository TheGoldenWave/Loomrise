# 阿里云端到端语音选型（STT/TTS）v0.1

> 2026-10-23。**性质：选型调研与候选登记，不是已验证事实。** 本文只回答三件事：**用哪两个模型、怎么锁版本、还差什么才能算 `M-S1-09` 通过**。API key 未到位前，本文所有结论停留在"文档已核"，不是"已跑通"。
>
> 依据：阿里云百炼官方文档（2026-09/10 更新版）与产品动态页；本地实测仅限 SDK 版本检查。逐条工件映射见 [Gate 追溯矩阵](RELEASE-GATE-MATRIX.md) `M-S1-08/09/10/11`。

## 1. 结论（先给答案）

| 角色 | 主选 | 理由 | 对照项 |
|---|---|---|---|
| **流式 ASR** | **`fun-asr-realtime-2026-02-28`** | **模型名带日期快照**，能真正"钉住版本"；实时流式；中文为主场景；0.00033 元/秒 | `paraformer-realtime-v2`（更便宜 0.00024、更老更稳）、`qwen-audio-3.0-asr-flash-streaming`（质量上限，但**无日期快照**） |
| **流式 TTS** | **`qwen-audio-3.0-tts-flash`** + 音色 **`longanhuan_v3.6`** | Flash 版首包 ≈300ms 级，适合对话；支持 PCM/WAV/MP3/Opus 与 16k/24k/48k | `cosyvoice-v3.5-flash`（前代，能力接近） |
| **地域** | **华北2（北京）** | ASR 实时族只在北区（Paraformer 明确限北区）；专属域名为 `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference` | 新加坡区**没有**完整的实时 ASR 族 |

**一句话**：ASR 选**能钉日期快照**的那个，TTS 选**首包最低**的那个。质量更好的 `qwen-audio-3.0-asr-flash-streaming` 可以跑对照，但**不进 `M-S1-09`**——它锁不住快照。

## 2. 为什么"锁版本"是这一节的真正主题

`M-S1-09` 要的是"一条固定组合"，而阿里这边的模型命名分两类：

| 命名形态 | 例子 | 能不能钉 |
|---|---|---|
| **带日期快照** | `fun-asr-realtime-2026-02-28`、`fun-asr-flash-8k-realtime-2026-01-28` | **能**。写进 `VERSION-PINS` 后语义固定 |
| **无日期别名** | `qwen-audio-3.0-asr-flash-streaming`、`qwen-audio-3.0-tts-flash` | **不能**。提供方升级别名时行为会变，只能记"别名 + 核验日" |

所以：

- ASR **必须**选带日期的，否则 `M-S1-09` 只能记"别名锁定"，验收记录要写"版本为别名，提供方可在不通知的情况下变更"——这句话本身就等于不合格。
- TTS **当前没有带日期的实时快照**。处置：钉 `模型名 + 音色名 + 输出格式 + 采样率`，并在验收记录里显式声明"别名风险"。这不是理想状态，但比浏览器 `speechSynthesis`（完全无法登记）好得多。

## 3. 接口形状（决定 WP1-1 怎么写）

### 3.0 三个入口不要混（最容易错的一处）

同一个 Workspace 下有**三个不同的根**，拿错一个就会得到 404 或"模型不存在"：

| 用途 | URL 形态 | 说明 |
|---|---|---|
| **对话模型**（OpenAI 兼容） | `https://{ws}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | 走 `/chat/completions`。**这条不能用于语音**——语音没有 OpenAI 兼容形态 |
| DashScope SDK 的 HTTP 根 | `https://{ws}.cn-beijing.maas.aliyuncs.com/api/v1` | SDK 里叫 `base_http_api_url` |
| **流式 ASR / 流式 TTS** | `wss://{ws}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference` | SDK 里叫 `base_websocket_api_url`；语音**只走这条** |

`{ws}` 就是 Workspace ID（形如 `llm-xxxxxxxxxxxxxxxx`）。**三个 URL 都从 Workspace ID 推导，不在代码里手写**——实现见 `loomrise/voice_config.py:endpoints()`。

### 3.1 ASR：WebSocket 双向流

握手用 `Authorization: Bearer <API_KEY>`，之后四步：

```
建立连接 → 发 run-task（action=run-task, streaming=duplex）
        → 收 task-started
        → 持续送二进制音频帧 → 收 result-generated（sentence_end=false 为中间结果）
        → 发 finish-task → 收 task-finished → 关闭
```

`run-task` 里影响我们验收的参数：

| 参数 | 取值建议 | 为什么 |
|---|---|---|
| `format` | `pcm` | 免容器解析，浏览器侧直接出 PCM16 |
| `sample_rate` | `16000` | 语音交互标准档；与 VAD 阈值配合 |
| `language_hints` | `["zh"]` | 不设则自动检测，自动检测会带来额外抖动，影响首响 |
| `semantic_punctuation_enabled` | `false` | **VAD 分段延迟更低**，适合交互；语义分段更适合会议转写 |
| `max_sentence_silence` | `800–1300` 可调 | 默认 1300ms，交互场景偏长，会拖"这句话说完了"的判定 |
| `heartbeat` | `true` | 静音段保活，否则连接会被超时关掉——**这条直接关系到"用户思考时不掉线"** |
| `disfluency_removal_enabled` | `true` | 去"嗯/那个"，减少下一层模型的噪声 |

服务端事件里有两样**恰好对上我们的合同**：`sentence_end`（句末）与 `words[]` 的 `begin_time/end_time`（词级时间戳）。后者可直接进 `RunEvent` 的证据字段，用于 `M-S1-13` 的"停止时延"埋点对齐。

### 3.2 TTS：流式合成

`dashscope.audio.tts_v2.SpeechSynthesizer(model=..., voice=...)`，`call()` 返回二进制音频；`get_first_package_delay()` 给出**首包时延**（可直接进 `M-S1-11` 的采样表）。注意首包时延含建连时间，所以要区分"首次调用"与"复用连接"两组数——否则 p95 会被建连抖动污染。

## 4. 与现有链路的差距（这才是工作量）

现状：`loomrise/web.html` 只有浏览器端 `webkitSpeechRecognition` + `speechSynthesis`，**没有任何音频上传路径**。

要满足 Gate，必须补三个零件（都在 R0-WP1）：

1. **浏览器采集**：`AudioWorklet` 采 PCM16 / 16k 单声道，100–200ms 一帧推给本地 WS。不用 `MediaRecorder` 做主链路——它输出 webm/opus，还得转码；`MediaRecorder` 只用来**留档录制件**（`M-S1-08` 的证据）。
2. **本地服务通道**：`loomrise/web.py`（已有 aiohttp）加一条 WS 路由，浏览器 ↔ 服务端 ↔ DashScope 双向转发。**音频不进 `RunEvent`**，只记引用与时长。
3. **服务端适配器**：新增 `adapters/aliyun_voice.py`，实现"打开 ASR 任务 → 转发帧 → 拿最终文本 → 交给 `ExecutionService`"与"文本 → TTS → 音频帧"两个方向。业务状态一律不进适配器（与 `agentscope_runtime.py` 同一条边界）。

## 5. 成本与限制（已知/未知分开写）

| 项 | 值 | 来源/状态 |
|---|---|---|
| ASR 实时（fun-asr-realtime） | **0.00033 元/秒** ≈ 1.19 元/小时；每月 36000 秒（10 小时）免费 | 第三方汇总文章，**未在控制台核** |
| ASR 实时（paraformer-realtime-v2） | 0.00024 元/秒 | 同上 |
| TTS 计费 | **未核**（按字符计费，Flash/Plus 不同价） | 待控制台确认 |
| 并发上限 / QPS | **未核** | 待确认；影响 `M-S1-11` 的采样轮次安排 |
| SDK | 本机 venv 已有 `dashscope 1.27.7`（随 wheelhouse 装） | **已实测存在**；但官方要求"最新 SDK"，`qwen-audio-3.0-*` 可能需要更高版本 → 待验 |

**一条前置风险**：如果 `dashscope 1.27.7` 不认识 `qwen-audio-3.0-tts-flash`，要么升级 SDK（需要联网装包，会破坏"离线可复现"），要么按 WebSocket 协议直连手写客户端。**这个必须在 WP1-01 第一步验掉**，否则整条 TTS 路径要重写。

## 6. 凭据存哪里（已实现，勿另起一套）

**不在仓库里，也不在 `.env` 里。** 与模型凭据同一套纪律，另存一个文件：

| 项 | 位置 / 做法 |
|---|---|
| 文件 | `~/.config/loomrise/aliyun-voice.json`（仓库外，`0600`，父目录 `0700`） |
| 写入 | `python -m loomrise.cli configure-voice`（交互式，key 用 `getpass`，不回显、不打印） |
| 覆盖 | **不覆盖**：已存在则 `O_EXCL` 失败，改 key 先手动删文件，留一次显式意图 |
| 符号链接 | 拒绝写入（防把凭据写到别处） |
| 读取 | 非 `0600` 或非普通文件直接报错，不做"尽力而为" |
| 环境变量 | `DASHSCOPE_API_KEY` **优先于**文件——容器/CI 不落盘；两者都没有就返回 `None`，由调用方**显式失败**，不静默回退到浏览器识别 |
| 导出 | 场景包与 `dist/` 导出**不含**该文件；验收脚本另有断言 |

理由：混进 `coding-plan.json` 会让"轮换一个 key"变成"重写整个模型配置"；放进 `.env` 则会被 `dist/`、demo、截图、`git add -f` 反复咬到。**`VERSION-PINS` 只记模型与参数，不记 key。**

## 7. 要落进 `VERSION-PINS` 的字段（key 到位后填）

```
语音地域        华北2（北京）/ WorkspaceId: <待填，不入公共文档>
ASR 模型        fun-asr-realtime-2026-02-28        ← 带日期快照，可钉
ASR 参数        pcm / 16000 / language_hints=[zh] / heartbeat=true / max_sentence_silence=1000
TTS 模型        qwen-audio-3.0-tts-flash           ← 别名，风险已声明
TTS 音色        longanhuan_v3.6
TTS 输出        pcm / 24000
SDK             dashscope==<实测可用版本>
核验日          <填>
```

> Workspace ID 本身不是密钥，但它是账号标识：**写在本地凭据文件里，不写进公共仓库**。仓库文档一律用 `{ws}` 占位。

## 8. 还差什么（清单，key 到手后按序做）

- [ ] 控制台核对计费与并发上限，把"未核"两行补上
- [ ] 验 `dashscope 1.27.7` 能否直接调 `qwen-audio-3.0-tts-flash`；不能则定"升 SDK"或"直连 WebSocket"
- [ ] 跑一次最小 ASR：10 秒中文音频 → 出文本 + `words[]` 时间戳
- [ ] 跑一次最小 TTS：一句话 → 出 PCM，记录首包时延（分"新建连接/复用连接"两组）
- [ ] 三条 ASR 候选各跑同一段 5 分钟中文语料，出**字错率对照**（决定主选是否换 `qwen-audio-3.0-asr-flash-streaming`）
- [ ] 把最终组合写进 [VERSION-PINS](../VERSION-PINS.md) 与阈值登记表

**没有第 5 项就不要定稿主选**——现在的主选依据是"能钉快照"，不是"中文更准"。这两件事必须分开证。
