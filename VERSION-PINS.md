# 版本钉与安装证据 v0.4

状态：实测记录，2026-10-12。本文件只写**实际装了什么、从哪来、怎么复现**，不写"最新版"。
凡是文档别处出现版本号，都以本文件为准。

**项目自身许可：`Apache-2.0`**（仓库根目录 `LICENSE`，署名见 `NOTICE`）。下表列出的许可证分属**上游依赖**，不是 Loomrise 自己的——`设置 · 系统诊断` 页的许可证清单应同时给出这两类。

本次干净环境复核：`requirements.txt` 使用 VCS 完整 commit `a38821287f35e9e45ed193d9d864cb46f263c946`，不是同名发行包。新虚拟环境安装后 `pip freeze` 显示该 commit，`pip check` 无冲突；完整自检与 11/11 确定性案例通过。导出包在独立目录与新虚拟环境重新安装、加载场景并 11/11 回放；**这不包括语音 Worker 或真实模型验收**。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 系统 | macOS（darwin），Apple 芯片 |
| Python | 原安装记录 3.13.12；本次重跑 3.13.15（隔离虚拟环境） |
| pip | 原安装记录 25.3；本次重跑 26.2 |
| 参考源码 | `_reference/`（浅克隆，Git 忽略） |

两个隔离环境（与[架构文档](docs/ARCHITECTURE.md)的"Lite 本地版 + 可选 Voice Worker"部署形态一致）：

- `s1-verify`：核心执行内核（AgentScope）
- `s1-voice`：语音 Worker（Pipecat）

## 2. AgentScope

| 项 | 值 |
|---|---|
| 基线 | **上游 `main` 分支快照 commit `a388212`**（不是发行 tag） |
| 本地检出 | `_reference/agentscope`，`git log -1` = `a388212 (grafted, HEAD -> main)` |
| 源码版本字符串 | `src/agentscope/_version.py` `__version__ = "2.0.8"` |
| 安装后 `pip list` | `agentscope 2.0.8` |
| 许可证 | Apache-2.0（`pyproject.toml` `license = "Apache-2.0"`） |
| requires-python | `>=3.11` |
| 上游自评 | classifier `Development Status :: 4 - Beta`（**不得表述为 GA 或生产就绪**） |
| 安装耗时 | `real 323.79s`（约 5 分 24 秒，含下载），一次带入 **92 个**分发包 |
| 依赖一致性 | `pip check` → `No broken requirements found.` |
| 重要传递依赖 | `grpcio`、`googleapis-common-protos`、`mcp`、`dashscope`、`anthropic`、`openai`、`tree_sitter`(+`tree_sitter_bash`)、`pypdf`、`python-socketio`、`aiohttp`、`uvicorn`、`starlette`、`jsonschema` |

### 为什么钉 commit 而不是发行 tag

原本钉的是发行 tag `v2.0.8`（`c7d8e31`），但本地检出、安装与全部回归实际都跑在 `main` 快照 `a388212` 上，两者相差 **202 个文件 / +19,059 / -614 行**。版本字符串相同不代表构件相同，所以：

- 基线改为 **`a388212`**，报告中一律写"AgentScope main 快照 `a388212`（源码版本字符串 2.0.8）"；
- 发行 tag `v2.0.8`/`c7d8e31` 不再作为 S1 基线或证据引用；
- 换任何新 commit 都要重跑验证项 A2–A12 并重新记录依赖锁。

详见 `docs/S1-VALIDATION-AND-ADAPTATION.md` §3.4。

## 3. Pipecat

| 项 | 值 |
|---|---|
| 版本 | **1.12.0**（`CHANGELOG.md` `## [1.12.0] - 2026-09-25`，tag `v1.12.0`） |
| 许可证 | BSD 2-Clause（Copyright 2024–2026, Daily） |
| 安装形式 | `pipecat-ai[tracing]==1.12.0`，环境 `s1-voice` |
| 安装结果 | 成功（约 132 秒），一次带入 **54 个**分发包 |
| 导入自检 | 通过：启动横幅 `Pipecat 1.12.0`，`pipecat.frames.frames.InterruptionFrame` 可解析 |
| 重要传递依赖 | `onnxruntime 1.24.4`、`numba`、`numpy`、`soundfile`、`num2words`、`openai`、`aiohttp`、`loguru` |

### 安装前置：`docopt` 只有源码分发

`num2words>=0.5.14` → `docopt>=0.6.2`，而 `docopt` 在 PyPI 上**没有 wheel**，pip 需要就地解包构建。在受限环境（对 pip 临时目录 `mkdir` 有拦截）会失败：

```text
ERROR: Could not install packages due to an OSError: EEXIST: file already exists,
mkdir '.../pip-install-*/docopt_*'
```

已排除的干扰：单独装 `docopt` 同样失败（与 Pipecat 无关）；`--no-build-isolation` 无效；换 `TMPDIR` 无效。`pip check` 无冲突 → **不是版本冲突，是环境限制**。

解决办法（已用于本次安装）：

```bash
curl -sL https://files.pythonhosted.org/packages/a2/55/8f8cab2afd404cf578136ef2cc5dfb50baa1761b68c9da1fb1e4eed343c9/docopt-0.6.2.tar.gz -o docopt-0.6.2.tar.gz
tar -xzf docopt-0.6.2.tar.gz
cp docopt-0.6.2/docopt.py <venv>/lib/python3.13/site-packages/
mkdir -p <venv>/lib/python3.13/site-packages/docopt-0.6.2.dist-info
# 在该目录写 METADATA / WHEEL / RECORD / INSTALLER 四个最小文件
pip install "pipecat-ai[tracing]==1.12.0"
```

等价替代：预置 `docopt` wheel，或先 `pip download` 缓存后离线安装。**这一步必须写进 Lite 安装文档，否则首次安装会失败。**

## 4. 观测与协议版本钉

| 依赖 | 钉住的值 | 为什么 |
|---|---|---|
| `opentelemetry-api` / `sdk` | `1.45.0` | 两个环境实测解析到的版本 |
| `opentelemetry-semantic-conventions` | **`0.66b0`** | 由 `opentelemetry-instrumentation` 精确锁定；GenAI 语义约定处于实验/迁移期（已迁出主 semconv 仓库）。Loomrise **自 pin 且自持属性映射**，不跟随上游 |
| `opentelemetry-exporter-otlp` | `1.45.0` | 可选导出 |
| `pydantic` | `2.13.5` | 直接依赖（contracts 校验），本次实装版本 |
| `aiohttp` | `3.14.3` | 新增直接依赖：本机网页/HTTP-SSE 入口；同时是 AgentScope 传递依赖，显式钉住避免解析漂移 |
| AG-UI | **spec `1.0`** | 以 `spec/1.0/schema.json` 的 `protocolVersion` 为准，**不要用 `ag-ui-protocol` 包版本号推断协议版本** |
| Langfuse 摄取 | `x-langfuse-ingestion-version: 4` | 实现拒绝高于 4 的版本，硬约束 |

## 5. 复现命令

```bash
# 核心环境
python3 -m venv s1-verify && s1-verify/bin/pip install -r requirements.txt
cd <repo> && PYTHONPATH=. s1-verify/bin/python -m loomrise.cli replay --out runs/replay-s1.json

# 语音环境（先补 docopt，见 §3；本次未重跑真实音频）
python3 -m venv s1-voice && s1-voice/bin/pip install "pipecat-ai[tracing]==1.12.0"
```

回放使用**脚本化确定性模型**，不需要 API 密钥；设置 `LOOMRISE_LIVE_MODEL` + `OPENAI_API_KEY` 才会切到真实 OpenAI 兼容模型（该路径未实测）。

导出命令复制核心 `requirements.txt` 与本文件，并另写 `voice-requirements.txt`。直接依赖固定为 Pydantic 2.13.5 与 aiohttp 3.14.3。上述导出恢复成功都是在**联网**条件下。

## 6. 离线 wheelhouse 与哈希锁（2026-09-28 干净环境实跑通过）

- `python scripts/build_offline.py`：先校验 `_reference/agentscope` HEAD 确为 `a388212…` 且 `requirements.txt` 的 VCS pin 未被改动，再用 `pip wheel` 把核心 `requirements.txt` 的直接依赖**及其传递依赖**打成 wheel，落到 `.build/offline/wheels/`（Git 忽略），逐个记录 SHA-256，生成 `requirements-offline-macos-arm64-py313.txt`（每行 `name==version --hash=sha256:…`，首行 `--only-binary=:all:`）。重建前会清空旧 wheel，避免同一依赖出现多个构件。
- 离线安装：`pip install --no-index --find-links=.build/offline/wheels --require-hashes -r requirements-offline-macos-arm64-py313.txt`。
- 交付包：`loomrise.cli export --offline` 会把锁文件与 wheelhouse 一起放进导出目录，可在无网目标机恢复。
- 一次跑完上述链条：`bash scripts/verify_offline.sh`（构建 → 干净环境离线安装 → 11 案例回放 + 自检 → `--offline` 导出 → 另一个干净环境离线恢复并回放）。
- 适用面：**仅 macOS arm64 / CPython 3.13**；换平台必须重跑脚本并按平台改名。语音 Worker（`voice-requirements.txt`）不进本锁，仍按 §3 单独安装。
- 实测（2026-09-28）：`bash scripts/verify_offline.sh` 一遍跑完——锁定 **92 个 wheel**（含 agentscope 2.0.8，由 `a388212` 源码本地构建）；干净虚拟环境 `--no-index --find-links=.build/offline/wheels --require-hashes` 安装成功，`pip check` 无冲突；11/11 案例回放 + 自检全部通过；`export --offline` 导出后，在**第二个干净环境**用同一份锁与 wheelhouse 离线安装并再次 11/11 回放。
- 自检 `test_offline_lock` 校验锁内每条依赖都带 `--hash=sha256:` 且对应 wheel 在库内（锁缺失时跳过，不判红）。
- 回归：真实模型改动（`kb.course_catalog` 片段、输出合同、`AgentState` 复用、拒绝记账）落地后于 2026-09-28 13:00 重跑 `verify_offline.sh`，`pip check` 无冲突，核心与导出恢复两处仍 11/11。

## 7. 本机 Coding Plan 凭据（不出仓库）

- 一次性录入：`python -m loomrise.cli configure-model`，交互三项：API root（HTTPS，形如 `https://<host>/v1`）、模型名（默认 `gpt-6-sol`，验收基线；`gpt-6-luna` 为低倍率成本对照档，可改）、密钥（getpass 隐藏输入）。
- 存放位置：**`~/.config/loomrise/coding-plan.json`（仓库外）**。放在仓库里再怎么 `.gitignore` 都挡不住 `git add -f` 或误提交，所以默认路径不进工作树。
- 保护方式：目录 `0700`、文件 `0600`；拒绝通过符号链接写入；重复录入不覆盖（抛 `FileExistsError`，需人工先删除）；读取时校验权限位，非仅所有者可读即报错。
- 密钥不进入任何运行事件、账本、导出包与日志；导出包从不含任何 `coding-plan.json`（自检有断言）。**Gitignored 存储不等于密钥管理器**，仅限本机开发试用。
- 真实模型实测（2026-09-28）：`scripts/live_model_check.py` 在 `gpt-6-sol`（**验收默认**，跑 2 次）与 `gpt-6-luna`（成本对照，跑 1 次）下均 11/11；首响 `gpt-6-sol` 2.4–4.8 s、`gpt-6-luna` 10.8–14.8 s（单轮单次，含代理往返，未做多轮取样）。`gpt-6-luna` 偶发"不发起写入工具"，脚本最多重试 3 次并把 `attempts` 写进报告；`gpt-6-sol` 全部场景 `attempts=1`。默认档位由 `loomrise/local_config.py:DEFAULT_MODEL` 决定，改档位要同步改这里并重跑脚本。模型名不是版本钉：Coding Plan 侧的档位与倍率随时可变，换档位必须重跑该脚本。

## 8. 阿里云语音（STT/TTS）与凭据（2026-10-23 首次实测）

- 一次性录入：`python -m loomrise.cli configure-voice`，交互五项：Workspace ID、ASR 模型、TTS 模型、音色、密钥（getpass 隐藏）。
- 存放位置：**`~/.config/loomrise/aliyun-voice.json`（仓库外，0600）**。与 §7 分离：轮换一个 key 不该重写整份模型配置。
- 三个端点**由 Workspace 推导**（`loomrise/voice_config.py:endpoints`），不在调用点手写：对话 `https://{ws}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`、SDK HTTP 根 `https://{ws}.../api/v1`、流式语音 `wss://{ws}.../api-ws/v1/inference`。**语音只走最后一条**。

| 项 | 值 | 证据 |
|---|---|---|
| 地域 | 华北2（北京） | 实时 ASR 族仅此地域 |
| ASR 模型 | `fun-asr-realtime-2026-02-28`（**带日期快照，可钉**） | 2026-10-23 闭环实测 |
| ASR 参数 | `pcm` / `16000` / `language_hints=[zh]` / `max_sentence_silence=1500` | 同上；1500 是**我们显式传的**，默认 800 会把中文逗号停顿判成句尾 |
| TTS 模型 | `qwen-audio-3.0-tts-flash`（**别名，不可钉快照**） | 同上 |
| TTS 音色 | `longanhuan_v3.6` | 同上 |
| TTS 输出 | `PCM_16000HZ_MONO_16BIT`（本次探针） | 同上 |
| SDK | `dashscope==1.27.7`（离线 wheelhouse 内） | `pip check` 无冲突 |
| 首包时延 | **331.9 / 339 / 364.7 / 371 / 402.1 / 411 ms**（6 次，均新建连接） | `runs/r0/voice/tts-firstpkt-*.log`、`smoke-*.json` |
| ASR 闭环 | TTS 合成 → ASR 识别，**逐字一致** | `runs/r0/voice/asr-multi-*.log` |
| 媒体通道 | `/ws/voice`：上行 PCM16/16k 二进制帧（100 ms/3200 B）+ JSON 控制帧；下行同格式 PCM | `loomrise/web.py:voice_ws` docstring 是协议权威 |
| 通道纪律 | 凭据缺失显式失败、背压读真实队列、一句一 TTS 实例、`final` 只是句尾 | [D-05](docs/VOICE-ARCHITECTURE-DECISIONS.md) |

- **`dashscope 1.27.7` 能直接调 `qwen-audio-3.0-tts-flash` 与三条 ASR 候选**，无需升级 SDK（此前列为风险 R-2，已关闭）。
- **别名风险未消除**：TTS 无日期快照，提供方升级别名时行为可变。验收记录必须写"版本为别名"。
- 三条 ASR 候选（`fun-asr-realtime-2026-02-28` / `paraformer-realtime-v2` / `qwen-audio-3.0-asr-flash-streaming`）在同一段**合成**语音上均逐字一致；**这不等于真人噪声语料下的准确率**，字错率对照仍未做。
- **媒体通道与业务通道分离**：`/ws/voice` 只搬声音，识别文本仍走 `POST /api/runs` → 同一 `ExecutionService`。语音不是第二条执行路径（[D-05](docs/VOICE-ARCHITECTURE-DECISIONS.md)）。
- **浏览器侧尚未验证**：`web.html` 已换成 `getUserMedia` + `AudioWorklet` + WS，但本机 Chromium 的 WebAudio 在自动化环境里不可用，**没有真浏览器运行证据**。M-S1-08 仍记"未开始"。
