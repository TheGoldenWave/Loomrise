# 版本钉与安装证据 v0.2

状态：实测记录，2026-09-27。本文件只写**实际装了什么、从哪来、怎么复现**，不写"最新版"。
凡是文档别处出现版本号，都以本文件为准。

本次进度复核补充：以下安装结果为已有记录，并非本次重装。当前 `requirements.txt` 使用 `agentscope==2.0.8`，**没有锁定实际验证的 main commit `a388212`**；因此第 5 节命令只是运行入口，不是已验证的精确构件复现。导出包同样使用发行包版本且未附本文件。需补齐实际 commit/构件锁定、导出依赖边界及干净环境安装回放后，才能声称安装可复现。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 系统 | macOS（darwin），Apple 芯片 |
| Python | 3.13.12（隔离托管版本，不污染系统 Python） |
| pip | 25.3 |
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
| AG-UI | **spec `1.0`** | 以 `spec/1.0/schema.json` 的 `protocolVersion` 为准，**不要用 `ag-ui-protocol` 包版本号推断协议版本** |
| Langfuse 摄取 | `x-langfuse-ingestion-version: 4` | 实现拒绝高于 4 的版本，硬约束 |

## 5. 复现命令

```bash
# 核心环境
python3 -m venv s1-verify && s1-verify/bin/pip install -r requirements.txt
cd <repo> && PYTHONPATH=. s1-verify/bin/python -m loomrise.cli replay --out runs/replay-s1.json

# 语音环境（先补 docopt，见 §3）
python3 -m venv s1-voice && s1-voice/bin/pip install "pipecat-ai[tracing]==1.12.0"
```

回放使用**脚本化确定性模型**，不需要 API 密钥；设置 `LOOMRISE_LIVE_MODEL` + `OPENAI_API_KEY` 才会切到真实 OpenAI 兼容模型（该路径未实测）。
