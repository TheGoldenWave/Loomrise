# R0 合同对齐开工清单 v0.1

> **For agentic workers:** 本文是 R0 的**执行清单**，不是 Gate 权威。Gate 条文见 [ROADMAP](../../ROADMAP.md) 与[客服交付方案 §3](../../CUSTOMER-SERVICE-DELIVERY-PLAN.md)；逐条工件见 [Gate 追溯矩阵](../../RELEASE-GATE-MATRIX.md) `M-S1-*`；版本切分见 [RELEASE-PLAN](../../RELEASE-PLAN.md) §3 R0。复选框只记进度，不代表已实现或已验收。

**Goal:** 把已写下但未落代码的合同（`Verdict` 四层、`subject_scope`、`state` 窗口、条件深度校验）落到代码并过回归，同时补齐 S1 剩下的媒体与 SSE 证据；**不做新功能、不接 adapter、不合主干**。

**Architecture:** 分两条并行轨道。轨道 A 是语音与 SSE 证据：SSE 与合同是黑盒；**语音不是**——现有网页只有浏览器端识别与合成，没有音频上传通道，`M-S1-08/09` 要求真实音频与可登记的服务端组合，因此 WP1 必须新增一条最小音频通道（只换掉假链路，不改业务逻辑）。轨道 B 是合同迁移（分支开发 + 单测，功能默认不启用）。两轨在 `R0-WP5` 汇合：**先证据齐，再合主干**，同批改 `rules.py` 优先级链与 `adapters/agentscope_runtime.py` 映射，然后重跑自检。

**边界（越界即停）:** 不加 `stop`/`dedupe` 之外的任何能力；不建配置器；不动 `prototypes/`；不改 S2 页面与 `S2-IA-NAV` 计数；不发布、不接真实业务写入、不引入新依赖。

---

## 0. 开工前 30 分钟（预检，必须先过）

| # | 动作 | 命令 / 检查点 | 不通过怎么办 |
|---|---|---|---|
| 0.1 | 建本地环境（仓库根 `.venv`，已 gitignore） | `python3 -m venv .venv && .venv/bin/pip install --no-index --find-links=.build/offline/wheels --require-hashes -r requirements-offline-macos-arm64-py313.txt`（92 wheel 离线装，不依赖网络） | 若 pip 被宿主沙箱拦在中途，按报错缺失的包逐个 `--no-deps` 补装（实测缺过 `jsonschema`、`agentscope`、`mcp`、`openai`），补完再验 |
| 0.2 | 确认当前基线可跑 | `.venv/bin/python tests/test_s1.py` → 应输出 **80 个 `ok` + "全部通过"**；把输出存 `runs/r0/contract/baseline-test.txt` | 少一个 ok 就停下修，R0 不启动 |
| 0.3 | 确认依赖版本与锁定 | 读 [VERSION-PINS](../../../VERSION-PINS.md) 与 `requirements.txt` 的 VCS commit（`a388212`） | 版本不符则先复现环境 |
| 0.4 | 建证据目录 | `runs/r0/{voice,sse,contract}/` | 目录不进 Git（`runs/` 已忽略），摘要另存 §1 |
| 0.5 | 建分支 | `git switch -c r0/contract-alignment` | 主干保持可回放 |
| 0.6 | 记基线快照 | 把 0.2 的输出存 `runs/r0/contract/baseline-test.txt` | 没有基线就无法证明"迁移不改变既有行为" |

## 1. 证据两层（v0.2 新增，先定再干活）

`runs/` 被 `.gitignore` 忽略（S1 运行产物），所以**证据必须分两层存**，否则矩阵里的"证据位置"在公开仓库里指向空气：

| 层 | 位置 | 内容 | 是否入库 |
|---|---|---|---|
| **原始件** | `runs/r0/...` | 音频录制件、事件 JSONL、时延采样 CSV、日志 | 否（本地保留） |
| **摘要** | `docs/reports/R0-EVIDENCE.md`（开工时新建） | 每行 Gate ID → 结论 → 样本量 → 原始件文件名与哈希 → 局限 | 是（脱敏） |

**规则**：摘要不得只写"已通过"，必须写**样本量、环境、语料版本、未覆盖项**。矩阵 `证据位置` 列填摘要里的锚点（如 `R0-EVIDENCE.md#m-s1-13`），原始件作为附注。

## 2. 语音阈值登记表（`M-S1-13` 的前置，必须在第一次采样前写入）

新建 `docs/reports/R0-VOICE-THRESHOLD-REGISTRY.md`，按下表逐项填写。**六项缺一，Gate 不成立**。

| 项 | 填什么 | 示例（示意，不是阈值） |
|---|---|---|
| 登记时间戳 | 精确到分，且早于首条采样 | `2026-10-23T14:05+08:00` |
| 绝对上限 | 停止时延 p95 的毫秒数 | `≤ ___ ms`（跑基线后填，不允许跑完再改） |
| 零容忍项 | 逐条列出并写计数口径 | 声学级误停 0 / 复读 0 / 漏判抢话 0 / 过期片段误播 0 |
| 语料版本 | 哪套中文语料、条目数 | 噪声 30 条（电视/旁人/键盘各 10）、对第三人说话 12 条、附和 8 条 |
| 设备与网络矩阵 | 机型、浏览器、麦克风、带宽档 | `MacBook M3 / Chrome 1xx / 内置麦 / 家用宽带` + 至少一档弱网 |
| 样本量与方法 | 每场景最少条数、是否含重复轮次 | 每场景 ≥10 次，含 2 次重复 |
| 未覆盖声明 | P1/P2 本轮不验就明写 | "P1 说话人级、P2 语义级未覆盖，留 S2-c" |

**纪律**：登记表提交（commit）之后才允许跑采样；跑完发现阈值定错，**新增一条登记**（带新时间戳）并说明原因，**不改原条目**。

## 3. 工作包

### R0-WP0 · 预检与登记

- [ ] 0.1–0.5 全过
- [ ] 语音阈值登记表填写并提交（§2 六项）
- [ ] `docs/reports/R0-EVIDENCE.md` 建骨架（17 行 Gate 占位）
- **签核：** 产研 · **证据：** `runs/r0/contract/baseline-test.txt`、登记表 commit

### R0-WP1 · 语音媒体（`M-S1-08…11`）

- [ ] **WP1-0 选型（2026-10-23 已定方向：云端阿里）**：主选 **ASR `fun-asr-realtime-2026-02-28`**（带日期快照，能真正钉版本）+ **TTS `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6`**（别名，风险已声明）；北京地域、专属域名。候选对照与"锁不住快照"的处置见 [阿里云语音选型](../../ALIYUN-VOICE-SELECTION.md)。**key 到位后第一步先验 `dashscope 1.27.7` 能否调新模型**——不能则要么升 SDK（破坏离线可复现，须记录）要么直连 WebSocket 手写客户端
- [ ] **WP1-1 音频通道（必须新建，别当成已有能力）**：现状是 `loomrise/web.html` 只有**浏览器端**识别与合成（`webkitSpeechRecognition` + `speechSynthesis`），**没有任何把音频送上服务端的路径**。要满足 `M-S1-08`（真实网页音频）与 `M-S1-09`（服务端固定组合），必须新增最小通道：浏览器 `MediaRecorder` 采集 → 上传（HTTP 或 WebSocket）→ 服务端 STT adapter → 文本进 `ExecutionService`；返回音频同理。这是 R0 里**唯一新增代码的语音部分**，属"换掉假链路"，不是加功能
- [ ] 真实网页音频采集：走 WP1-1 通道，产出录制件（`M-S1-08`）
- [ ] 中文可懂度：固定语料逐条判读，记录判读人与原文（`M-S1-10`）
- [ ] 首响采样：≥10 轮，报 p50/p95，记录设备与网络（`M-S1-11`）
- **签核：** 产研 · **不做：** 不调轮次策略参数、不改打断逻辑、不接 Pipecat 全链路（那是 S2-c 的语音应用验收）

### R0-WP2 · 语音交互指标（`M-S1-13`、`M-S1-14`）

- [ ] 埋点：`barge-in` 事件时间戳 → 最后一帧停止时间戳，落 `RunEvent`（字段名与已有事件风格一致）
- [ ] 跑登记表里的噪声语料，统计声学级误停（目标 0）与漏响应率（防 VAD 过严）
- [ ] 跑"停—判—续"处置，统计恢复时延 p95 与复读次数
- [ ] 结果按登记表口径出表；**P1/P2 不测，写"未覆盖"**
- **签核：** 产研 · **证据：** `runs/r0/voice/*.csv` + `R0-EVIDENCE.md#m-s1-13`

### R0-WP3 · 真实模型 SSE（`M-S1-12`）

- [ ] `python -m loomrise.cli web --port 8765`（**不加 `--scripted`**），浏览器端跑通一轮文字咨询
- [ ] 留档：客户端收到的 AG-UI 事件序列、首包时间、结束时间、中断点
- [ ] 写明"真实模型驱动"的三项可核标记：模型 ID、`attempts`、请求-响应时间戳
- **签核：** 产研 · **不做：** 不改 `web.py` 的协议形状

### R0-WP4 · 合同落地（分支开发，不合主干）

- [ ] `Behavior`（`contracts.py:106`，`ALLOW`/`DENY`/`ASK`）→ **`Verdict` 四值** `deny`/`require`/`stop`/`dedupe`；**删除 `Verdict.allow`**——"放行"由 `ToolPolicy` 登记表达，不由规则声明
- [ ] **授权查询独立于裁决**：先查 `ToolPolicy`，未登记直接拒；`rules.py:52` 现在用 `Behavior.DENY` 报"未在 ToolPolicy 中登记"，改为 `AuthorizationResult`（不产 `Verdict`）
- [ ] `rules.py:66` 的优先级链 `(DENY, ASK, ALLOW)` 改为 `(deny, stop, require, dedupe)` 的显式顺序，并写单测覆盖两两冲突
- [ ] `GateOutcome`（`route_to` / `block` / `suspend`）落合同；与 `Verdict` **并列而非从属**
- [ ] `ServiceRequest` 加 `subject_id` + `subject_scope: mapped | ephemeral`；**禁止"空值即默认主体"**（缺 `subject_id` 只能落 `ephemeral` 且不落库）
- [ ] 新增 `StateWindow` 枚举：`cycle`（默认）/ `24h` / `forever` / `session`；**本轮只落枚举与校验，不实现计数器**
- [ ] 新增第九条校验 `validate_condition_depth()`：深度 ≤2 层，`llm` 叶不计层，硬规则 `when` 与路由边 `condition` 共用。建议放新模块 `loomrise/validation.py`（纯函数，R1 配置器直接复用）
- **签核：** 产研 · **证据：** 单测（每条新语义至少一正一反）
- **不做：** 不接 `adapters/agentscope_runtime.py`、不动 `scripts/live_model_check.py`、不改 `web.py`

### R0-WP5 · 合入与回归（汇合点，前置 = WP1–WP4 全绿）

- [ ] 合主干；同批改 `adapters/agentscope_runtime.py` 的映射（`Behavior` → `Verdict`/`GateOutcome`）
- [ ] 改写 `tests/test_s1.py` 的"只读放行"断言 → "**授权查询放行**"
- [ ] 重跑 `.venv/bin/python tests/test_s1.py`（**80 项 ok + 全部通过**）与 `.venv/bin/python -m loomrise.cli replay`（**11/11**），新增语义测试全绿
- [ ] 与 0.1 的基线快照逐项对比，列出"行为变化清单"（预期内 = 无；有则记录原因）
- **签核：** 产研 · **证据：** `runs/r0/contract/after-test.txt` + 行为变化清单

### R0-WP6 · 证据记录与签核（`M-S1-06`、`M-S1-07`）

- [ ] 六字段台账：AgentScope/Pipecat 版本、许可证、安装步骤、资源占用、首响、失败项
- [ ] 上下文五问审计可答：加载了什么 / 跳过什么 / 为什么 / 是否预算截断 / 对应规则与知识版本（`python -m loomrise.cli audit --ledger <path>`）
- [ ] `R0-EVIDENCE.md` 17 行填完；矩阵 `M-S1-01…14`、`M-S1-17` 状态改 `通过`/`不通过`，`M-S1-15/16` 标"未覆盖（S2-c）"
- **签核：** 产研 · **证据：** 摘要文档 + 矩阵状态更新

## 4. 顺序与并行

```
WP0 ──┬─ WP1（选型→媒体→可懂度→首响）──┐
      ├─ WP2（埋点→语料跑测）──────────┼─ WP5（合入+回归）
      ├─ WP3（真实模型 SSE）────────────┘        │
      └─ WP4（合同分支：四值→授权→窗口→校验）────┘
                                                  └─ WP6（台账+签核）
```

- **可并行**：WP1 / WP3 / WP4 互不依赖，可同时开。
- **硬串行**：WP2 依赖 WP1 的链路；WP5 依赖 WP1–WP4 全绿；WP6 依赖 WP5。
- **唯一外部依赖**：WP1-0 的 STT/TTS 选型。选型不决，WP1 不启动，但 WP3/WP4 不受影响。

## 5. 完成定义（R0 DoD）

1. `M-S1-01…14` + `M-S1-17` 在矩阵中全为 `通过`；
2. `M-S1-15/16` 明确标"未覆盖（S2-c）"，不冒充通过；
3. `Verdict` / `GateOutcome` / `subject_scope` 三处**合同与代码一致**（同一字段名、同一枚举值）；
4. 语音登记表**时间戳早于采样**，六项齐全；
5. 行为变化清单为空，或每条变化都有记录与理由；
6. `R0-EVIDENCE.md` 可让人不看代码就判断"哪条 Gate 靠哪件工件过去"；
7. 自检 `tests/test_s1.py`（80 项 ok + "全部通过"）与 `cli replay`（11/11）在本机 `.venv` 上连续两次结果一致——只跑通一次不算。

**任何一条不满足，R0 不退出**——不是"基本完成"。

## 6. 提交与分支纪律

- 分支 `r0/contract-alignment`，**不合主干直到 WP5**。
- 一个 WP 一个 commit，消息前缀 `r0-wpN:`，正文写"证据位置"。
- 登记表、摘要文档单独 commit（`r0-wp0:` / `r0-wp6:`），便于回溯"阈值何时定的"。
- 不提交 `runs/`（已忽略）；不提交凭据；音频录制件只留本地，仅摘录入库。

## 7. 失败与回退

| 情形 | 处置 |
|---|---|
| 语音选型不可行（无凭据/费用超限） | 退回浏览器 Web Speech，但**必须**在 `M-S1-09` 记"版本不可锁"，并把 Gate 标 `不通过`——不允许用"能跑"替换"可复现" |
| 11/11 在 WP5 挂了 | 回退合入，保留分支；**不回退证据**（WP1–WP3 的结论仍有效） |
| 授权查询改造影响面超预期 | 拆成两步：先落 `AuthorizationResult` 只读并存，再切 `Verdict`；两步都要有单测 |
| 条件深度校验与硬规则算子对不上 | 停，先改 `HARD-RULE-MODEL` 的算子口径，再动代码——**不能代码先走、文档后补** |

## 8. 明确不做（写在这里防扩散）

- 不做 `stop`/`dedupe` 之外的规则能力；不实现计数器（只落枚举）；
- 不建配置器、不做 `Unit` 清单投影（属 R1）；
- 不动 `prototypes/` 与工作台 IA；
- 不接真实业务写入、不发真实消息、不部署；
- 不因"顺手"引入新依赖或新抽象层。
