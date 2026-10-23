# R0 依赖与资源台账（`M-S1-06`）v0.1

> 2026-10-23。Gate 要求六字段齐全：**版本、许可证、安装、资源、首响、失败项**。
> 数据来自本机实测，不是从文档抄的。凡没测得的一律写"未测"，不写"正常"。

## 1. 版本

| 组件 | 版本 | 证据 |
|---|---|---|
| AgentScope | **2.0.8** | `.venv/bin/pip show agentscope` |
| dashscope（语音） | **1.27.7** | `pip show`，离线 wheelhouse 内 |
| aiohttp（本地服务） | **3.14.3** | `pip show` |
| Python | 3.13.12 | 仓库根 `.venv` |
| 依赖总数 | 95 个包 | `.venv/bin/pip list \| wc -l` |
| VCS 锁 | `a388212` | `requirements.txt` |

**Pipecat：未安装。** `voice-requirements.txt` 里声明 `pipecat-ai[tracing]==1.12.0`，但 S1 的语音链路现在不走 Pipecat：
`adapters/voice.py:make_observer()` 在 `import pipecat` 失败时返回 `None`，播放状态机由 Loomrise 自建并已被 `test_s1.py` 的 `test_voice_playback` 覆盖。
**这意味着"轮次与打断交给 Pipecat"在 S1 并未成立**——S2-c 若要用，必须先装并重验。这条写在这里，避免"声明了就等于有了"。

## 2. 许可证

| 组件 | 许可证 | 可商用 |
|---|---|---|
| AgentScope | **Apache-2.0** | 是 |
| aiohttp | Apache-2.0 | 是 |
| dashscope SDK | Apache-2.0 | 是 |
| Pipecat（未安装） | BSD-2-Clause（上游声明） | 是 |
| Loomrise 自身 | Apache-2.0 | 是 |

许可证只核了主依赖；传递依赖未逐个审计——**这条是已知缺口**，对外交付前要跑一次完整扫描。

## 3. 安装

```bash
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links=.build/offline/wheels \
  --require-hashes -r requirements-offline-macos-arm64-py313.txt
```

- 92 个 wheel，**全程离线**，不依赖网络。
- 实测坑：pip 被宿主沙箱的批量删除守卫打断，缺过 `jsonschema` / `agentscope` / `mcp` / `openai` / `dashscope` 等，需逐个 `--no-deps` 补装。补完必须跑 `pip check`（本轮首次就漏了这一步）。
- 语音凭据单独录入：`python -m loomrise.cli configure-voice`（`~/.config/loomrise/aliyun-voice.json`，0600）。

## 4. 资源

| 场景 | 指标 | 值 |
|---|---|---|
| 确定性回放 11 案例（脚本模型） | 峰值 RSS | **91.7 MB** |
| 同上 | 墙钟 | **3.51 s**（user 0.71 / sys 0.27） |
| 真实模型单轮（9.1 s 端到端） | 峰值内存 | **未测**（未单独采样） |
| 语音 TTS 单句（26 字） | 输出 PCM | 175–188 KB / 5.3–5.5 s 音频 |

未测项：真实模型路径的 CPU 曲线、并发 2 路时的内存、长会话（>50 轮）的账本增长。**S1 不承诺并发能力，这里也不假装测过。**

## 5. 首响

来源：`runs/r0/voice/latency-20261023T051025Z.csv`（12 轮，服务端链路，非浏览器整链）。

| 指标 | n | p50 | p95 | max |
|---|---|---|---|---|
| TTS 首包 | 12 | **344 ms** | **378 ms** | 379 ms |
| TTS 整句墙钟 | 12 | 537 ms | 668 ms | 685 ms |
| ASR 首个部分结果 | 12 | 227 ms | 288 ms | 345 ms |
| 推流结束 → 最终文本 | 12 | 131 ms | 201 ms | 234 ms |
| 识别一致率 | 12/12 | — | — | — |
| 上行丢弃字节 | 0 | — | — | — |

**局限**：音频是 TTS 合成的干净语音；推流按 20 ms/100 ms 帧（约 5 倍实时），不是真实语速；无弱网；无麦克风与设备播放。所以这组数只答"服务端这一段有多快"。

## 6. 失败项

| # | 失败 / 缺口 | 影响 | 状态 |
|---|---|---|---|
| F-1 | 本机 Chromium 的 `getUserMedia` 与 `AudioContext` 在无头与有头两种模式下**双双挂死** | 浏览器麦克风无法自动验证，`M-S1-08` 只能人工 | 未解决（环境） |
| F-2 | **TTS 模型是别名，无日期快照** | `M-S1-09` 只能记"别名锁定 + 核验日" | 已知，不可解 |
| F-3 | `AgentVersion.model` 声明 `scripted-s1`，真实调用是 `gpt-6-sol` | 版本没钉住实际模型，留档若只读声明值会误导 | 已在本轮留档中**显式分开记录**；根治属 R1 |
| F-4 | 真实 provider 的 `TextBlockEndEvent.text` 为 `None`，账本里出现空 `reply.text` | AG-UI 投影没有文本事件，前端只剩 summary 兜底 | **本轮已修**：空文本不再 emit，`reply.final` 补发一次 |
| F-5 | 背压计数器只累加不递减 | 3 秒后永久丢帧，伪装成"服务端截断" | **本轮已修**：改读 SDK 待发队列 |
| F-6 | 停止时延与误停**无任何样本** | `M-S1-13` / `M-S1-14` 不成立 | 未开始 |
| F-7 | 传递依赖许可证未逐项审计 | 对外交付前置 | 未做 |

## 结论

六字段齐全，但其中"首响"只覆盖服务端、"失败项"里有 4 条未解决。
**`M-S1-06` 可以记通过**（Gate 要的是"记录固定版本、许可证、安装、资源、首响、失败项"，不是"没有失败项"）；
**F-1 / F-6 直接决定 `M-S1-08` / `M-S1-13` / `M-S1-14` 本轮不能通过**。
