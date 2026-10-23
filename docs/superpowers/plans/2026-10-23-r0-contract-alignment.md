# R0 合同对齐开工清单 v0.1

> **For agentic workers:** 本文是 R0 的**执行清单**，不是 Gate 权威。Gate 条文见 [ROADMAP](../../ROADMAP.md) 与[客服交付方案 §3](../../CUSTOMER-SERVICE-DELIVERY-PLAN.md)；逐条工件见 [Gate 追溯矩阵](../../RELEASE-GATE-MATRIX.md) `M-S1-*`；版本切分见 [RELEASE-PLAN](../../RELEASE-PLAN.md) §3 R0。复选框只记进度，不代表已实现或已验收。

**Goal:** 把已写下但未落代码的合同（`Verdict` 四层、`subject_scope`、`state` 窗口、条件深度校验）落到代码并过回归，同时补齐 S1 剩下的媒体与 SSE 证据；**不做新功能、不接 adapter、不合主干**。

**Architecture:** 分两条并行轨道。轨道 A 是语音与 SSE 证据：SSE 与合同是黑盒；**语音不是**——原网页只有浏览器端识别与合成，没有音频上传通道，`M-S1-08/09` 要求真实音频与可登记的服务端组合，因此 WP1 新建了一条最小双向媒体通道（**2026-10-23 已实现，服务端侧已验，浏览器侧待人工实测**；只换掉假链路，不改业务逻辑）。轨道 B 是合同迁移（分支开发 + 单测，功能默认不启用）。两轨在 `R0-WP5` 汇合：**先证据齐，再合主干**，同批改 `rules.py` 优先级链与 `adapters/agentscope_runtime.py` 映射，然后重跑自检。

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

- [x] 0.1–0.5 全过（`.venv` 建好、基线 81 项全绿、版本钉已读、证据目录已建、分支 `r0/contract-alignment`）
- [x] 语音阈值登记表已建（[R0-VOICE-THRESHOLD-REGISTRY.md](../../reports/R0-VOICE-THRESHOLD-REGISTRY.md)，时间戳早于任何停止时延采样）。**六项里「语料版本」标缺**——没有观测语料，这直接导致 `M-S1-13/14` 本轮不成立
- [x] `docs/reports/R0-EVIDENCE.md` 已按 17 行逐条写结论（v0.4）：**11 通过（08/10 带偏离）/ 2 部分 / 2 未开始（挂账）/ 2 未覆盖**
- **签核：** 产研 · **证据：** `runs/r0/contract/baseline-test.txt`、登记表 commit

### R0-WP1 · 语音媒体（`M-S1-08…11`）

- [x] **WP1-0 选型（2026-10-23 已定：云端阿里）**：主选 **ASR `fun-asr-realtime-2026-02-28`**（带日期快照，能真正钉版本）+ **TTS `qwen-audio-3.0-tts-flash` / `longanhuan_v3.6`**（别名，风险已声明）；北京地域、专属域名。候选对照见 [阿里云语音选型](../../ALIYUN-VOICE-SELECTION.md)。凭据录入 `python -m loomrise.cli configure-voice`（`~/.config/loomrise/aliyun-voice.json`、`0600`、不覆盖、拒符号链接、`DASHSCOPE_API_KEY` 优先）。**已验：`dashscope 1.27.7` 直接能调，无需升级**（原风险 R-2 关闭）
- [x] **WP1-1 双向媒体通道（已实现，服务端侧已验；浏览器侧未验）**：`/ws/voice` 单条 WS——上行 PCM16/16k 二进制帧 + JSON 控制帧，下行同格式音频。新增 `loomrise/adapters/aliyun_voice.py`（ASR/TTS 流式封装、背压、时序）、`web.py:voice_ws`（协议权威在 docstring）、`web.html`（`getUserMedia` → `AudioWorklet` 降采样 → WS；下行 `AudioBufferSource` 队列播放）。**协议与纪律见 [D-05](../../VOICE-ARCHITECTURE-DECISIONS.md)**。验收：`tests/test_voice_ws.py` 33 项 + `scripts/voice_ws_smoke.py` 真云端往返
- [x] **WP1-1b 浏览器实测（`M-S1-08`）——2026-10-23 人工实测通过**：真人在 Chrome 156 对着本机麦克风点「录音」说一句 → `#input` 出识别文本 → 听到服务端合成语音。**但未开 `--voice-trace`，没留 `ws-*.jsonl`**，矩阵该行通过条件原文「有录制件且可回放」未满足 → 登记偏离 `G-5`（[R0 证据摘要 §5](../../reports/R0-EVIDENCE.md)）
- [x] 中文可懂度（`M-S1-10`）——**判据降级通过**：负责人据同一次实测判定识别准确可读；**未建语料、无判读表、无第三方判读人** → 偏离 `G-4`，补语料后必须复核
- [x] 首响采样：**12 轮**，TTS 首包 p50 344 / p95 378 ms，ASR 首 partial p50 227 / p95 288 ms（`runs/r0/voice/latency-*.csv`）。**限服务端链路**：浏览器整链零样本，故 `M-S1-11` 仍记部分
- **签核：** 产研 · **不做：** 不调轮次策略参数、不改打断逻辑、不接 Pipecat 全链路（那是 S2-c 的语音应用验收）

### R0-WP2 · 语音交互指标（`M-S1-13`、`M-S1-14`）

- [x] 埋点：浏览器侧记打断触发 / 音频节点停止 / 首帧播放，服务端记 `tts.cancel` 与 `tts.done.cancel_ms`，统一进 `runs/r0/voice/ws-*.jsonl`（`--voice-trace` 开启）。**口径按 [D-05](../../VOICE-ARCHITECTURE-DECISIONS.md)：不含扬声器与系统混音缓冲，不能直接当声学级 p95**
- [ ] **本轮不做，决定延后（`G-6`）**——跑登记表里的噪声语料：注册噪声语料未建；用合成音频冒充会让「0 次误停」变成自证
- [ ] **延后**——跑"停—判—续"处置，统计恢复时延 p95 与复读次数
- [ ] **延后**——结果按登记表口径出表；**P1/P2 不测，写"未覆盖"**

> **延后不等于放弃**：这四项仍是 S1 的 Gate（`M-S1-13/14`），只是本轮不做。因此 **R0 未退出**，且"语音已验收"这句话在任何文档里都不成立——已验的是链路与可懂度，未验的是声学鲁棒性。
- **签核：** 产研 · **证据：** `runs/r0/voice/*.csv` + `R0-EVIDENCE.md#m-s1-13`

### R0-WP3 · 真实模型 SSE（`M-S1-12`）

- [x] 真实模型跑通一轮文字咨询（**用脚本客户端消费流，不是浏览器**）：`scripts/sse_live_check.py`，端到端 9.1 s，事件含 `TEXT_MESSAGE_CONTENT`
- [x] 留档：`runs/r0/sse/sse-*.json`（时间轴、首包 236 ms、结束、回复全文）
- [x] 三项标记分开记录：声明模型 `scripted-s1` / 配置模型 `gpt-6-sol` / 事件时间戳。**两者不一致已写入留档**（`model_matches_declared=false`）
- **签核：** 产研 · **不做：** 不改 `web.py` 的协议形状

### R0-WP4 · 合同落地（分支开发，不合主干）

- [x] `Behavior` → **`Verdict` 四值**（`deny`/`require`/`stop`/`dedupe`），`allow` 已删除；场景包同步迁移（两条 `allow` 规则删除、`rule_ids` 同步）
- [x] 授权查询独立：`AuthorizationResult`（不产 `Verdict`），`DecisionPolicy.authorize()` 先查登记；`check()` 的放行是 `verdict is None`
- [x] 优先级链 `(deny, stop, require, dedupe)`，**两两冲突 6 组单测**（`tests/test_contract_semantics.py`）
- [x] `GateOutcome` 落合同，与 `Verdict` 并列（单测验证两者值域不相交）
- [x] `ServiceRequest` 加 `subject_id` + `subject_scope`；`mapped` 缺 `subject_id` **直接抛错**，`ephemeral` 的 `persistent_subject` 恒为 `None`
- [x] `StateWindow` 四值已落，**未实现计数器**（按范围）
- [x] 第九条校验 `loomrise/validation.py`：深度按**组合算子嵌套**计（纯叶子 1 层、`(A or B) and C` 2 层），`llm` 叶不计层；`rule_conditions()` 让硬规则与路由边共用入口
- **签核：** 产研 · **证据：** 单测（每条新语义至少一正一反）
- **不做：** 不接 `adapters/agentscope_runtime.py`、不动 `scripts/live_model_check.py`、不改 `web.py`

### R0-WP5 · 合入与回归（汇合点，前置 = WP1–WP4 全绿）

- [ ] **合主干**——**未合**，DoD 第 1 条要求 `M-S1-01…14` 全通过，当前 08/10/13/14 未完成 · [x] **已改** `adapters/agentscope_runtime.py` 映射（`_VERDICT_MAP`；`STOP`/`DEDUPE` 有损落 `DENY`，差异留在事件 `verdict` 字段）
- [x] 断言已改写：「只读放行」→「放行来自授权查询而非规则」，并新增「未登记工具直接拒绝」「重复写入判 dedupe 而非 deny」
- [x] 重跑：`test_s1.py` **81 项 ok**（原 80 + 新增 1）、`test_contract_semantics.py` **47 项**、`test_voice_ws.py` 33 项、`replay` **11/11**，连续两次一致
- [x] 行为变化清单见 §5 之后，**3 条预期内变化**，逐条写了原因
- **签核：** 产研 · **证据：** `runs/r0/contract/after-test.txt` + 行为变化清单

### R0-WP6 · 证据记录与签核（`M-S1-06`、`M-S1-07`）

- [x] 六字段台账：[R0-DEPENDENCY-LEDGER.md](../../reports/R0-DEPENDENCY-LEDGER.md)。**Pipecat 未安装**（声明了但没用），已在台账写明
- [x] 五问可答（本轮修过：原 `audit` 输出丢掉 `source_version`，第五问在 CLI 上根本答不了）
- [x] 17 行逐条写结论；矩阵状态已更新（8 通过 / 2 在跑 / 4 未开始 / 2 未覆盖）
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
- **唯一外部依赖已解除**：WP1-0 的 STT/TTS 选型已定、凭据已录、SDK 已验证可用。**剩余阻塞变成"人工在真浏览器里说一句话"（WP1-1b）**——自动化替代不了，本机 Chromium 的 WebAudio 在自动化环境里不可用。

## 4.1 行为变化清单（WP5 产出）

与 §0 的基线快照（81 项全绿 + 11/11）逐项对比后，**有 4 条可观察变化，均为预期内**。没有一条改变业务结果。

| # | 变化 | 为什么会变 | 是否影响业务终态 |
|---|---|---|---|
| C-1 | `permission.decision` 事件的字段 `behavior`（值 `allow`/`deny`/`require_confirm`）改为 `verdict`（值 `pass`/`deny`/`require`/`stop`/`dedupe`） | 合同要求四值且删 `allow`；"放行"不是裁决，因此记为 `pass` 并另带 `authorized` 字段 | 否（只是账本字段与措辞） |
| C-2 | 重复写入的裁决从 `deny` 变为 `dedupe` | `deny` 说"不允许"，`dedupe` 说"这是同一个写入" —— 两者对账本与重试策略的含义不同 | 否（`create_booking` 仍返回 `DENIED` outcome 与已知 `result_id`） |
| C-3 | 真实模型路径新增一条 `reply.text` 事件（在 `reply.final` 处补发）；`TextBlockEndEvent.text` 为 `None` 时不再写空事件 | 原行为：账本里有事件、无内容，AG-UI 一条文本都投影不出，前端只能靠 summary 兜底 | 否（回复文本与终态不变，只是现在客户端真能收到文本事件） |
| C-4 | `loomrise audit` 的 `loaded` 从 id 列表变为对象（含 `stage`/`source`/`tokens`），新增 `agent_version`、`budget_capped`、`rules_hit` | 原输出丢掉 `source_version`，第五问在 CLI 上不可答 | 否（只影响审计输出；有下游脚本解析该 JSON 时需同步） |

**没有变化的**：两条 `allow` 规则删除后，`search_knowledge` 与 `create_booking` 的裁决结果与之前完全一致（登记即放行），11/11 回放与 81 项自检逐条对齐。

## 5. 完成定义（R0 DoD）



1. `M-S1-01…14` + `M-S1-17` 在矩阵中全为 `通过`；
2. `M-S1-15/16` 明确标"未覆盖（S2-c）"，不冒充通过；
3. `Verdict` / `GateOutcome` / `subject_scope` 三处**合同与代码一致**（同一字段名、同一枚举值）；
4. 语音登记表**时间戳早于采样**，六项齐全——**本轮「语料版本」项缺**，因此 `M-S1-13/14` 只能未开始；
5. 行为变化清单为空，或每条变化都有记录与理由（本轮 4 条，见 §4.1）；
6. `R0-EVIDENCE.md` 可让人不看代码就判断"哪条 Gate 靠哪件工件过去"；
7. 自检 `tests/test_s1.py`（**81 项 ok** + "全部通过"）与 `cli replay`（11/11）在本机 `.venv` 上连续两次结果一致——只跑通一次不算。

**任何一条不满足，R0 不退出**——不是"基本完成"。

### 当前状态（2026-10-23 第二轮，据负责人决定）

| DoD | 状态 |
|---|---|
| 1 | ✗ **11/14 通过**，但 08/10 是**带偏离的通过**（`G-5` 无原始件、`G-4` 判据降级）；13/14 **零样本、延后挂账 `G-6`** → 按"未通过"对待 |
| 2 | ✓ 15/16 标未覆盖 |
| 3 | ✓ 合同与代码一致（`test_contract_semantics.py` 47 项） |
| 4 | ✗ 六项仍缺「语料版本」（正是 `G-6`） |
| 5 | ✓（4 条已记录，见 §4.1） |
| 6 | ✓ |
| 7 | ✓ 连续两次 81 项 + 11/11 一致 |

**结论：代码完成，Gate 未全绿，R0 未退出。** 已验的是**链路与可懂度**；未验的是**声学鲁棒性**（停止时延、误停）。

**合主干与退出是两件事**：代码可合（81 项 + 11/11 不回退任何已通过项），**合入不改变任何 Gate 状态**，也不产生"R0 已退出"的结论。R1 可以开工——配置器与持久化不依赖声学指标。

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
