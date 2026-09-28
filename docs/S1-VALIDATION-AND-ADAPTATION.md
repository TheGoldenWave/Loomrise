# S1 验证结论与轻量适配 v0.4

> 状态：**2026-09-27 更新。** 三个 P0 项目完成源码级验证；AgentScope 与 Pipecat 有安装级（L-C）证据；两个 P1 项目完成轻量适配定义。**S1 精确依赖干净环境及导出环境的 11/11 确定性案例通过**（见[S1 交付与验收](S1-BUILD-REPORT.md)）。基线为 main 快照 `a388212`（§3.4）；上下文压缩冲突为长期结构性问题（A9）；业务对象为 `ServiceRequest`（A10）。**真实模型与网页音频的运行级（L-D）门禁仍未执行**；仅取得脚本回放资源样本。本文件区分历史验证与本次新增证据，阶段与 Gate 见[验证路线](ROADMAP.md)。

## 1. 本轮范围决策

| 分级             | 项目                                                                                                                | 固定版本                                | S1 处理                             |
| -------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------- | --------------------------------- |
| **深入验证**       | AgentScope                                                                                                        | **main 快照 commit `a388212`（源码声明 `__version__ = "2.0.8"`）**；S1 基线即此 commit，**不改用发行 tag `v2.0.8`/`c7d8e31`** | Agent 运行适配候选：验证事件、暂停恢复、权限边界、适配侵入性 |
| **深入验证**       | Pipecat                                                                                                           | 1.12.0（`1559a68`）                   | 网页语音适配候选：验证中断、播放状态、轮次、观测挂点、中文化选项  |
| **深入验证**       | OpenTelemetry（GenAI 语义约定）                                                                                         | 无本地检出版本，按上游规范现状核验                   | 投影与导出层：确认可依赖边界，确认**不承担**业务事实      |
| **轻量适配**       | AG-UI                                                                                                             | spec 1.0（`b8ebd02`）                 | 只做单向事件投影；不进入内部领域模型                |
| **轻量适配**       | Langfuse                                                                                                          | 4.46.0（`fd5c9ee`）                   | 只做可选 OTLP 导出与回看；不做门禁依赖            |
| **参考定位，不纳入实现** | Octop、Dify、Langflow、LiveKit Agents、Qwen Audio Agent、Gander、SkillHone、SkillOpt、skill-up、可插拔 DecisionProvider、IM 渠道 | —                                   | 保持文档参照，S1 不装、不接、不留并行链路            |

本轮**只新增 5 个边界**（3 个适配 + 2 个投影），不新增平台、不新增第二套任务状态、不新增第二个控制面。

## 2. 验证方法与证据级别

固定版本取自本地浅克隆（`_reference/`，Git 忽略），引用即版本，避免"最新版"漂移。

| 级别           | 含义                | 本轮是否完成                                          |
| ------------ | ----------------- | ----------------------------------------------- |
| **L-A 源码级**  | 可在指定文件/行复述的结论     | 完成                                              |
| **L-B 元数据级** | 版本号、许可证、依赖声明      | 完成                                              |
| **L-C 安装级**  | 隔离环境实测安装、导入、依赖一致性 | 部分完成：AgentScope 成功并取得完整数据；Pipecat 被受限环境阻塞（见 §8） |
| **L-D 运行级**  | 端到端运行、时延、资源、成本、音质 | **未完成**，本文所有结论止于 L-C                            |

判据：任一条目未达 L-D 时，只能表述为"源码/安装已确认，运行未验证"。

## 3. AgentScope 深入验证

### 3.1 验证目标

证明在固定稳定版上可以：产出可归一化的结构化事件；支持暂停与人工接管；把权限裁决留在模型外；且 Loomrise 逻辑可挂在公开扩展点上，不 fork 上游。

### 3.2 关键验证点与结论

| #   | 关键验证点              | 判定标准                                   | 证据                                                                                                                                                                                                                                                                                  | 结论                                                                                                                                                             |
| --- | ------------------ | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A1  | 版本可固定、可识别          | 版本号可取，非开发分支                            | `src/agentscope/_version.py` `__version__ = "2.0.8"`；`pyproject.toml` `license = "Apache-2.0"`、`requires-python = ">=3.11"`、classifier `Development Status :: 4 - Beta`；上游 `v2.0.8` 解析为 `c7d8e31`                                                                                                             | **S1 基线通过：固定 `v2.0.8` / `c7d8e31`。** 本地检出 `a388212` 是 main 分支快照，不是发行 tag，不能因内部版本字符串仍为 2.0.8 就视为同一构件。"稳定版"须限定为"最新正式发布版"，上游自评 Beta，不得表述为 GA 或生产就绪 |
| A2  | 结构化事件              | 事件具备类型、ID、时间戳，覆盖回复/模型调用/文本增量/工具调用/工具结果 | `event/_event.py` `EventBase(id, created_at, metadata)`；`event/__init__.py` 导出 28 个事件类型                                                                                                                                                                                             | 通过                                                                                                                                                             |
| A3  | 事件可直接充当 `RunEvent` | 事件自带租户/任务/运行/渠道标识                      | 事件仅含 `session_id` / `reply_id` / `tool_call_id`，**无** `request_id` / `tenant` / `channel`                                                                                                                                                                                              | 不通过（预期内）。事件是**供应商事件**，必须由 `ExecutionService` 归一化并做关联                                                                                                           |
| A4  | 暂停 + 人工接管原语        | 存在等待外部输入的显式状态                          | `RequireUserConfirmEvent`（待确认工具调用）、`RequireExternalExecutionEvent`（待外部执行）、`ConfirmResult`、`UserConfirmResultEvent`、`ExternalExecutionResultEvent`                                                                                                                                   | 通过                                                                                                                                                             |
| A5  | 取消语义可分离            | 取消请求与执行端确认不混为一谈                        | `UserInterruptEvent` 文档明示：只对 parked reply 有效；中断运行中的回复须取消底层 task，由 agent 自行 `CancelledError` 清理                                                                                                                                                                                      | 通过但语义有限 → **"取消请求已发送"与"业务动作已撤销"必须由 Loomrise 分别记账**，不能依赖上游表达                                                                                                    |
| A6  | 权限在模型外裁决           | 规则可声明、确定性裁决、含拒绝                        | `permission/_rule.py` `PermissionRule(tool_name, rule_content, behavior, source)`；`permission/_types.py` `PermissionBehavior = ALLOW/DENY/ASK/PASSTHROUGH`；模式含 `DONT_ASK`（把所有 ASK 转 DENY，安全默认）                                                                                      | 通过。但作用域是**工具/路径语义**（Bash 子串、读写 glob），不是业务确认语义；Loomrise `HardRule` 仍须自建                                                                                         |
| A7  | 工具终态可判定            | 成功/失败/中断/拒绝可区分                         | `message/_block.py` `ToolResultState = success/error/interrupted/denied/running`                                                                                                                                                                                                    | 部分通过。**缺 `unknown`**；超时后回执未知必须由 Loomrise 侧显式建模，不得映射成 success                                                                                                   |
| A8  | 适配不侵入上游            | 无需 fork，可挂在公开扩展点                       | `middleware/_base.py` `MiddlewareBase`：`on_reply` / `on_reasoning` / `on_acting` / **`on_check_permission`** / `on_model_call` / `on_compress_context` / `on_system_prompt` / `list_tools`；`tool/_base.py` `ToolMiddlewareBase`；事件流入口 `Agent.reply_stream()`（`agent/_agent.py:288`） | 通过。**适配 = 一个 MiddlewareBase 实现 + `reply_stream` 事件投影**，这是本轮最主要的落地结论                                                                                            |
| A9  | 上下文加载完全可控          | S1 三段式加载不被 SDK 既有机制改写                  | `agent/_config.py` `ContextConfig(...)`、`InjectionConfig(inject_runtime_state, ...)`；`Agent.reply_stream()` 在推理前调用 `compress_context()` 与 `_inject_runtime_state()`                                                                                               | **不通过。冲突是长期结构性的，不是 S1 特有；S1 特有的只是"先关掉"这个止血动作。** 只要产品要回答"模型本轮实际看到了什么、为什么"，未经登记的隐式改写（自动压缩、工具结果截断、运行时注入、图片卸载）就不被允许——这条约束在 S2 及以后同样成立。S1 的三步处理：① `InjectionConfig(inject_runtime_state=False)` 一次性关闭时间／计划任务／上下文水位／工具重试四维注入（`_agent.py:1407` 处直接 return）；② `ContextGuardMiddleware.on_compress_context` 拦截压缩，**不调用** `next_handler`，原生压缩与截断即不生效，并在估算达到阈值时落 `context.compaction_blocked` 事件；③ 不能只把 `trigger_ratio` 调高当作关闭。**长期不禁止压缩，而是收编**：由 `ContextCompactionService` 编排并记录输入快照、摘要／截断算法、来源覆盖、输入输出哈希、token 变化与成功／失败事件，上游 SDK 只做执行器。fail-closed 的表现是上下文超限时在模型边界**显式失败**，而不是静默改写 |
| A10 | 与领域对象无命名冲突         | 上游对象不得成为 Loomrise 权威                   | 上游 `state/_task.py` `Task(subject, description, state=pending\|in_progress\|completed)`；`skill/_base.py` `Skill(name, description, dir, markdown)`                                                                                                                                  | **两边都不该用裸名，裁决见[命名决策](NAMING.md)。** Loomrise 的业务对象改名为 **`ServiceRequest`**：它跨多轮、可含多次 `Run`、带业务终态，不是"一件工作"，叫 `Task` 会让"跑了几轮"和"请求完了没有"永远说不清；上游对象只在适配器内部别名为 `RuntimeTask`/`PlanTask`。Loomrise 的公开配置对象是 **`SkillManifest`**（UI 可简称 Skill）；上游 Markdown 目录对象别名为 `MarkdownSkill`/`SkillDirectory`——它描述的是 Skill 的**载体/格式**而非能力本身。两者都不进入对方合同 |
| A11 | 自带追踪               | 有 OTel，且使用 GenAI 语义约定                  | `middleware/_tracing/_setup.py` `trace.get_tracer("agentscope", __version__)`；`_attributes.py` 从 `opentelemetry.semconv._incubating.attributes.gen_ai_attributes` 导入                                                                                                                | 通过，但取自 `_incubating` 命名空间 → 见 §5                                                                                                                               |
| A12 | 上游服务层不被误用          | 识别并排除自带控制面                             | `src/agentscope/app/` 自带服务、路由、中间件与 channel（飞书/钉钉/Discord）；`service` extra 依赖 `fastapi、uvicorn、apscheduler、ag-ui-protocol>=0.1.10`                                                                                                                                                   | 明确**不采用** `app/` 服务层：S1 不引 IM、不自建第二控制面，只取 SDK 与事件                                                                                                              |

### 3.3 对 S1 的四条硬边界

1. **S1 关闭 SDK 侧运行时注入，并 fail-closed 拦截未登记的原生压缩/截断**（A9）；仅调整阈值不算关闭。否则 Gate "能回答本轮加载/跳过/原因" 不成立。
2. **长期不禁止压缩，但压缩必须归 Loomrise 编排**：保留不可变输入上下文，生成带来源覆盖和版本证据的摘要/截断，并把压缩作为可审计事件；供应商 SDK 只能作为执行器，不能成为事实源。代码中 `CompactionPolicy` 已预留 `loomrise` 模式，编排器未实现前调用即抛错，不允许把上游压缩包装成 Loomrise 压缩。
3. **业务 `ServiceRequest` / `SkillManifest` / 硬规则 / 结果语义留在 Loomrise**（A6/A7/A10）；上游 `permission` 与 `RuntimeTask`/`MarkdownSkill` 只在 SDK 适配器内部生效。
4. **`unknown` 状态自建**（A7）：工具超时、外部回执缺失一律进 Loomrise 的未知态，不得由上游 `running` 或 `success` 兜底。

### 3.4 版本钉：改钉 main 快照 `a388212`（已决策，2026-09-27）

**S1 基线由发行 tag `v2.0.8`/`c7d8e31` 改为上游 `main` 分支快照 commit `a388212`。** 重新核对后的事实与取舍：

| 项 | 事实 |
|---|---|
| 本地 `_reference/agentscope` | `main` 分支，HEAD = `a388212`（grafted，浅克隆） |
| 源码声明版本 | `src/agentscope/_version.py` `__version__ = "2.0.8"` |
| 与发行 tag `v2.0.8`/`c7d8e31` 的差异 | **202 个文件、增加 19,059 行、删除 614 行**；涉及 Agent 核心取消传播、事件时间戳、外部工具结果校验、Realtime、SOP、分类器、TUI、渠道和服务层 |
| S1 实测安装来源 | 由本地 `main` 快照构建/安装，隔离环境 `s1-verify`，`pip list` 显示 `agentscope 2.0.8` |

决策理由：`__version__` 字符串相同不代表构件相同，因此**不能把 a388212 的实测结果写成"v2.0.8 已验证"**；反过来，既然本地检出、安装与全部回归都跑在 `a388212` 上，把基线钉在一个没有实测过的 tag 上只是把证据链切断。所以选择**把基线改钉到实际使用的 commit**，并把它写成显式事实。

因此：

- S1 安装、运行和报告均以 **`a388212`** 为准，报告中一律写 "AgentScope main 快照 `a388212`（源码版本字符串 2.0.8）"；
- 发行 tag `v2.0.8`/`c7d8e31` 不再是 S1 基线，也不作为证据引用；
- 升级到任何新 commit（含未来的发行 tag）都必须重跑 A2–A12 并重新记录依赖锁，尤其是取消传播、事件时间戳、压缩与服务层排除项；
- 依赖钉与安装前置统一记录在 [`VERSION-PINS.md`](../VERSION-PINS.md)。

### 3.5 安装级实测（L-C）

见 §8。

## 4. Pipecat 深入验证

### 4.1 验证目标

证明固定版本上可以：跑通一条中文网页语音链路；用户打断可被广播并可被业务侧感知；播放状态可区分；观测可挂接而不改上游。

### 4.2 关键验证点与结论

| #   | 关键验证点                | 判定标准                         | 证据                                                                                                                                                                                                                                                                                                                                              | 结论                                                                                                                                                              |
| --- | -------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1  | 版本可固定                | tag 与许可证明确                   | `CHANGELOG.md` `## [1.12.0] - 2026-09-25`；git tag `v1.12.0`；`LICENSE` BSD 2-Clause（Copyright 2024–2026, Daily）                                                                                                                                                                                                                                  | 通过                                                                                                                                                              |
| B2  | 网页实时传输可用             | 至少提供一种网页实时传输                 | `transports/`：`websocket`、`smallwebrtc`、`daily`、`livekit`、`local`                                                                                                                                                                                                                                                                               | 通过。S1 **只选一种**，不同时维护多条链路                                                                                                                                        |
| B3  | 打断可触发                | 用户开口即产生打断广播                  | `frames/frames.py` `InterruptionFrame`；`turns/user_turn_strategies.py` `enable_interruptions: bool = True`；`turns/user_start/*` 各策略实现                                                                                                                                                                                                           | 通过                                                                                                                                                              |
| B4  | 播放状态可四态区分            | 生成 / 已发送 / **已确认播出** / 未知 可辨 | `TTSStartedFrame`、`TTSStoppedFrame`、`BotStartedSpeakingFrame`、`BotStoppedSpeakingFrame`、`TTSTextFrame`；`transports/websocket/` 无设备级回执模型                                                                                                                                                                                                         | **不通过**。只有"已发出/播放缓冲结束"边界，**没有客户端设备级播出回执** → "已确认播出"必须由 Loomrise 自建，未知态必须显式保留，不得记为用户已听见                                                                          |
| B5  | 轮次切分                 | 有轮次概念与可替换策略                  | `turns/`：`user_turn_controller`、`user_turn_strategies`、`speculation_gate`、`eager_end_of_turn_mixin`、`user_idle_controller`                                                                                                                                                                                                                      | 通过                                                                                                                                                              |
| B6  | 时延可测量                | 首响/轮次延迟有内置观测                 | `observers/user_bot_latency_observer.py`、`startup_timing_observer.py`、`service_metrics_observer.py`、`metrics/metrics.py`                                                                                                                                                                                                                        | 通过（取值待 L-D）                                                                                                                                                     |
| B7  | 观测可挂接                | 有公开挂点，无需改上游                  | `pipeline/worker.py` `add_observer` / `remove_observer`；`observers/base_observer.py` `on_push_frame(FramePushed)`                                                                                                                                                                                                                               | 通过。Loomrise 语音事件导出 = 一个 observer                                                                                                                                |
| B8  | 自带 OTel 且用 GenAI 键   | 有 OTel 支持，属性可对齐              | `utils/tracing/setup.py`（`OPENTELEMETRY_AVAILABLE` try/except，导出器由用户注入）；`service_attributes.py` 含 `gen_ai.operation.name`、`gen_ai.provider.name`、`gen_ai.request.model`、`gen_ai.system_instructions`、`gen_ai.output.type`，并并存自有键 `metrics.ttfb`、`function_calls.*`、`tools.*`、`transcript.is_input`；`turn_trace_observer.py` `TurnTraceObserver` | 通过。语义约定是**子集 + 自造键并存**，不能假设与 AgentScope 全等                                                                                                                      |
| B9  | 中文化链路有候选             | 存在中文 STT/TTS 供应商             | `services/`：`funasr`、`qwen`、`fish`、`minimax`、`azure`、`deepgram`、`gladia`、`soniox`、`speechmatics`、`whisper`；本地 TTS：`piper`、`kokoro`、`xtts`                                                                                                                                                                                                       | 通过。S1 选**一种**组合，其余保持可用但不并行                                                                                                                                      |
| B10 | 与 AgentScope 的依赖边界一致 | 两者 OTel 声明不冲突                | Pipecat `tracing` extra：`opentelemetry-sdk/api>=1.33,<2`、`opentelemetry-instrumentation>=0.54b0,<1`；而 `opentelemetry-instrumentation` 对 `opentelemetry-semantic-conventions` 是**精确锁定**（安装实测解析为 `==0.66b0`）。AgentScope 核心依赖只声明 `opentelemetry-semantic-conventions>=0.60b0`                                                                      | **不一致且方向相反**：Pipecat 侧**间接硬锁** semconv 版本，AgentScope 侧是宽松下界。实际解析到的 semconv 版本由 `opentelemetry-instrumentation` 决定 → Loomrise 必须自己统一 pin 并在适配层断言版本，不得依赖"上游会带对版本" |

### 4.3 对 S1 的两条硬边界

1. **"已确认播出"自建**（B4）：`BotStoppedSpeakingFrame` 只代表服务端口径的播放边界，进入 `RunEvent` 时必须能与"已确认播出"分开，未知播放状态不是成功。
2. **语音链路只留一条**（B2/B9）：候选组合多不等于多链路，S1 只维护一条默认链路。

## 5. OpenTelemetry 深入验证

### 5.1 验证目标

确认 OTel 在 S1 中的角色只是**投影与导出**，并确认 GenAI 语义约定是否已稳定到可以长期依赖。

### 5.2 关键验证点与结论

| #  | 关键验证点           | 判定标准             | 证据                                                                                                                                                                                                                                                                                           | 结论                                                                              |
| -- | --------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| C1 | GenAI 语义约定是否稳定  | 可长期依赖，不预期破坏性变更   | GenAI 语义约定页面已从 OpenTelemetry 主语义约定仓库**迁出至独立仓库**（`open-telemetry/semantic-conventions-genai`），主仓页面标注不再维护；AgentScope 从 `semconv._incubating.attributes.gen_ai_attributes` 导入；`opentelemetry-semantic-conventions` 版本号为 `0.x.yb` 预发布形态，安装实测解析为 `0.66b0`，且被 `opentelemetry-instrumentation` 精确锁定 | **不通过**。GenAI 语义约定处于实验/迁移期，且版本由第三方包间接决定 → Loomrise **自己 pin 版本 + 自持属性映射**，不跟随上游 |
| C2 | 是否可承担业务事实       | 账本、审批、发布不依赖 OTel | OTel 定位为可采样、可批量导出的遥测；`BatchSpanProcessor` 等导出路径天然有丢样可能                                                                                                                                                                                                                                       | 不通过（设计如此）。`RunEvent` 为业务事实，OTel / Langfuse / AG-UI 皆为投影                         |
| C3 | 跨服务可关联          | 有稳定关联字段          | OTel 原生 `trace_id` / `span_id`；AgentScope 另有 `gen_ai.conversation.id`；Pipecat 有 turn 级 span                                                                                                                                                                                                  | 通过。`request_id` / `run_id` / `media_session_id` / `trace_id` 分别编号                  |
| C4 | Lite 部署不强依赖观测后端 | 无观测后端时功能与证据不退化   | 依赖 C1/C2：进程内 API + 可选 OTLP 导出即可                                                                                                                                                                                                                                                              | 采用。S1 默认关闭外部导出，开启只走 OTLP                                                        |

### 5.3 S1 验收判据

- 关闭全部导出后，任务结果、`RunEvent` 与回放结论不变。
- 开启导出后，`RunEvent` 与 Trace 可按 `(run_id, request_id)` 对齐。
- 每次运行记录所用语义约定版本；属性映射版本与 `AgentVersion` 一同冻结。

## 6. AG-UI 轻量适配

### 6.1 适配范围

- **做**：单向投影。Loomrise `RunEvent` → AG-UI 事件流（SSE），协议版本冻结在 `spec/1.0`。
- **不做**：不引入 AG-UI 作为内部领域模型；S1 不建设双向前端控制通道；不用第三方 AG-UI 客户端作为验收权威；不使用 `STATE_SNAPSHOT/DELTA` 与 `MESSAGES_SNAPSHOT`（避免产生第二套会话状态权威）。

### 6.2 最小事件子集

| Loomrise 事实    | AG-UI 事件                                         | 说明                                                                                                                          |
| -------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| 运行开始 / 结束 / 错误 | `RUN_STARTED` / `RUN_FINISHED` / `RUN_ERROR`     | 必选。`run_id` 用 Loomrise `run_id`，不用上游 reply id                                                                               |
| 文本回复增量         | `TEXT_MESSAGE_START` / `_CONTENT` / `_END`       | `message_id` 用内容块 ID                                                                                                        |
| 工具调用与结果        | `TOOL_CALL_START` / `_ARGS` / `_END` / `_RESULT` | 结果必须携带 `result_id`                                                                                                          |
| 模型调用步骤         | `STEP_STARTED` / `STEP_FINISHED`                 | 可选                                                                                                                          |
| 思考块            | `REASONING_*`                                    | S1 默认**不投影**，避免把内部推理当成对外内容                                                                                                  |
| **人工确认与取消**    | `CUSTOM`                                         | **AG-UI 1.0 事件枚举共 31 类，其中无人工确认/中断类型** → 确认与取消只能走 `CUSTOM`（`require_user_confirm` / `user_confirm_result`），并视为 Loomrise 私有扩展 |
| 上下文加载/跳过证据     | `CUSTOM`                                         | 审计用途，不投影给终端业务界面                                                                                                             |

补充两条取舍：AG-UI 对文本与工具调用同时提供"离散三段"（`START`/`CONTENT`/`END`）与"单块"（`*_CHUNK`）两种形态，S1 **只投影离散三段**，避免同一事实两种编码；`SUBAGENT_STARTED` / `_FINISHED` / `_ERROR` 在 S1 不使用（首版单 Agent）。

### 6.3 集成方式

1. **位置**：事件导出边界（与渠道适配、Agent 运行适配并列），输入是 `RunEvent` 流，输出是 AG-UI 事件；业务结果与权限判断不经过投影层。
2. **映射参照而非依赖**：AgentScope 自带 `app/middleware/_protocol/_agui.py`（`AGUIProtocolMiddleware`）给出了一套 1:1 映射，可作为**映射参照**。但**不直接复用该中间件**，理由有二：其源码自述"Per-instance state; safe under typical single-stream usage but not across concurrent requests"；且它位于上游 `app/` 服务层，会把上游控制面一并引入（见 A12）。
3. **校验方式**：直接用 AG-UI 自带一致性语料 `spec/1.0/conformance/streams/*.json`（含 `MANIFEST.txt` 双向断言）回归投影，而不是自建测试集。注意该语料是**第一方客户端回归套件**，覆盖协议 MUST 与客户端自选行为，不构成 Loomrise 验收权威。
4. **版本判定**：以 `spec/1.0/schema.json` 的协议版本字段（schema 含 `protocolVersion`）为准。上游 Python 包版本号为 `ag-ui-protocol>=0.1.10`，与规范 1.0 **号不同**，不得用包版本推断协议版本。
5. 许可证：MIT。


## 7. Langfuse 轻量适配

### 7.1 适配范围

- **做**：可选 OTLP/Traces 导出，供人工回看与对照。
- **不做**：不作为发布门禁依赖；不部署完整自托管栈作为 S1 前置；不使用 `ee/` 目录功能。

### 7.2 证据与集成方式

| 项 | 事实 | 对适配的影响 |
|---|---|---|
| 端点 | `POST /api/public/otel/v1/traces`（`fern/apis/server/definition/opentelemetry.yml`），仅 `resourceSpans`（**仅 traces**） | 只投影 trace，不指望用它承载指标/日志 |
| 格式 | 支持 protobuf 与 JSON protobuf，支持 gzip | 与 OTel 标准 exporter 兼容 |
| 版本握手 | 直连 exporter 必须带 `x-langfuse-ingestion-version: 4`；实现拒绝高于 4 的版本（`web/src/server/otel/processOtelIngestion.ts`） | 摄取版本是**硬约束**，须写入适配层常量并随版本冻结 |
| 许可证 | MIT，但 `ee/`、`web/src/ee/`、`worker/src/ee/` 走 `ee/LICENSE` | 交付包与依赖清单只含 MIT 部分；EE 功能不进 S1 |
| 自托管足迹 | `docker-compose.yml` 含 6 个服务：`langfuse-web`、`langfuse-worker`、`clickhouse`、`minio`、`redis`、`postgres` | 印证"完整服务非单机强依赖"：S1 只做可选导出，不做本地必需组件 |
| 版本 | 4.46.0 | 与 `_reference/README.md` 索引一致 |

集成方式：`RunEvent` → span 投影（span 名 = 事件类型，属性含 `run_id` / `request_id` / `agent_version` / `channel`）；`trace_id` 复用 Loomrise `trace_id`；导出失败只降级观测，不影响业务结果与审计。

## 8. 安装级实测（L-C）

**环境**：macOS（darwin）、Python 3.13.12（隔离托管版本）、两个全新 venv（`s1-verify` / `s1-voice`，不污染系统 Python）、pip 25.3。

**部署形态的决策（本轮新增）**：最初试图把两个 SDK 装进同一环境以暴露依赖冲突，但实测被两处环境问题卡住（见下）。结合[架构文档](ARCHITECTURE.md)已有的"Lite 本地版 + 可选 Voice Worker"部署目标，S1 采用**两个隔离环境**：核心执行内核装 AgentScope，语音 Worker 装 Pipecat，两者通过 `RunEvent` 合同协作，不共享进程。这既绕开了环境限制，也与实际部署形态一致。

| 项 | AgentScope（main 快照 `a388212`） | Pipecat 1.12.0（`[tracing]`） |
|---|---|---|
| 环境 | `s1-verify` | `s1-voice` |
| 安装结果 | **成功**（本轮 S1 基线即该 commit，见 §3.4） | **成功**（补齐上一轮缺失的 L-C 证据） |
| 耗时 | `real 323.79s`（约 5 分 24 秒，含下载） | 约 132 秒（含下载） |
| 一次带入分发包 | **92 个** | **54 个** |
| 依赖一致性 | `pip check` → `No broken requirements found.` | 导入自检通过：`Pipecat 1.12.0` 启动横幅，`frames.frames.InterruptionFrame` 可解析 |
| 带入的 OTel 包 | 10 个，其中 `opentelemetry-semantic-conventions-0.66b0`、`opentelemetry-exporter-otlp-common-0.66b0`、`opentelemetry-exporter-http-transport-0.66b0` 为 `0.x.yb` 预发布号 | `opentelemetry-api/sdk 1.45.0`、`opentelemetry-instrumentation 0.66b0`、`opentelemetry-semantic-conventions 0.66b0` |
| 其余重要传递依赖 | `grpcio`、`googleapis-common-protos`、`mcp`、`dashscope`、`anthropic`、`openai`、`tree_sitter`(+`tree_sitter_bash`)、`pypdf`、`python-socketio`、`aiohttp`、`uvicorn`、`starlette`、`jsonschema` | `onnxruntime 1.24.4`、`numba`、`numpy`、`soundfile`、`num2words`、`openai`、`aiohttp`、`loguru` |

**上一轮 Pipecat 失败的真实原因（本轮定位到根因）**：失败点不在依赖冲突，而在核心依赖链 `num2words` → `docopt`。`docopt` 在 PyPI 上**只有源码分发**（无 wheel），pip 需要就地解包构建；当前工作环境对 pip 临时目录的 `mkdir` 有拦截，报：

```text
ERROR: Could not install packages due to an OSError: EEXIST: file already exists,
mkdir '.../pip-install-*/docopt_*'
```

已排除三重干扰：(1) 单独执行 `pip install docopt` 同样失败，与 Pipecat 无关；(2) 关闭构建隔离（`--no-build-isolation`）后同样失败；(3) 更换 `TMPDIR` 到工作区路径同样失败。**根因是运行环境对"就地解包源码分发"的限制，不是版本冲突**（`pip check` 无冲突报告）。

**解决办法与 S1 安装前置（必须写进安装文档）**：从 PyPI 取 `docopt-0.6.2.tar.gz` → 用系统 `tar` 解包 → 把 `docopt.py` 拷入 site-packages → 补 `docopt-0.6.2.dist-info/{METADATA,WHEEL,RECORD,INSTALLER}`。手工补齐后 Pipecat 一次安装成功。等价的更省事做法：预置 `docopt` wheel 或缓存后离线安装。

**仍未取得的安装级证据**：Pipecat 在受限环境下的**无人值守**安装（不手工补 docopt）；两个 SDK 在**同一进程**内的共存实测（当前按部署形态拆分为两个环境，故未测，也不再是 S1 前置）。

## 9. S1 验证结论汇总

| 项目 | S1 定位 | 结论 | 是否阻塞 S1 Gate | 必须先处理的边界 |
|---|---|---|---|---|
| AgentScope（`a388212`） | Agent 运行适配 | **通过（源码级 + 安装级）**；S1 代码已跑通 | 否 | 关闭 SDK 侧上下文压缩与注入（`InjectionConfig` + `on_compress_context` 拦截）；`ServiceRequest`/`SkillManifest`/权限/结果语义归 Loomrise；自建 `unknown` |
| Pipecat 1.12.0 | 网页语音适配 | **通过（源码级 + 安装级）**；播放状态机已用合成帧回归 | 否 | 安装前置：手工预置 `docopt`；"已确认播出"自建（四态）；语音只留一条链路 |
| OpenTelemetry GenAI | 投影与导出 | 只作投影，版本自 pin | 否 | 语义约定实验期，属性映射自持 |
| AG-UI 1.0 | 前端投影 | 轻量可用 | 否 | 确认/取消只能走 `CUSTOM`；协议版本以 schema 为准 |
| Langfuse 4.46.0 | 可选观测后端 | 轻量可用 | 否 | 仅 traces；摄取版本号硬约束；排除 EE 与完整栈 |
| Octop / Dify / Langflow / LiveKit / Qwen Audio / Gander / SkillHone / SkillOpt / skill-up / DecisionProvider / IM | 参考定位 | 不纳入 S1 | 否 | 不安装、不接入、不留并行链路 |

### 本次补齐与仍然未验证

1. 首响、轮次时延、打断恢复、资源占用、单位成功任务成本。
2. 中文链路实际可懂度与具体供应商组合选型。
3. 同一请求“文字发起 → 模拟语音确认 → 文字重复提交”的 ID、版本、权限、结果与一次写入断言已通过；真实媒体链路未接。
4. 取消/超时/未知播放状态在端到端运行中的可区分性。
5. 交付包已在干净目录与新虚拟环境安装、加载并 11/11 回放；离线安装和重启后的业务状态恢复未验证。
6. AG-UI 第一方 TypeScript 客户端一致性语料 69/69；Loomrise 11 案例投影通过第一方 1.0 schema 校验。两者不是 Loomrise 输出经 SSE 到客户端的端到端测试。
7. ~~Pipecat 的安装级证据~~ —— 本轮已补齐（§8）。
8. **真实模型下的行为**：S1 回放使用脚本化确定性模型保证可复现，未验证真实模型在相同配置下的路由、工具调用与拒绝行为。
9. **取消与精确安装复现**：VCS 完整 commit 已锁定，完整自检与 11/11 回放通过；取消专项验证执行端停止、零写入，以及写入后取消保留结果 ID、不伪称撤销。真实外部写入撤销和重启恢复未验证；详见[S1 交付与验收](S1-BUILD-REPORT.md)。

上述任一项取得可复现记录前，不得对外宣称适配完成、多供应商即插即用或生产可用。

## 10. 明确不纳入 S1 实现范围

Octop、Dify、Langflow（应用体验参照）；LiveKit Agents（网页语音扩到多人媒体或电话时再评估，不与 Pipecat 并行做主栈）；Qwen Audio Agent（限时对照，需另行立项）；Gander（研究标杆）；SkillHone、SkillOpt、skill-up（S2 的机制参照）；可插拔 `DecisionProvider`（可选增强，非前置）；IM（钉钉/飞书/企微）与真实电话外呼（S4 且需独立授权）。

## 附：本轮证据索引

- AgentScope：`_reference/agentscope/src/agentscope/{_version.py, pyproject.toml, event/_event.py, event/__init__.py, permission/_rule.py, permission/_types.py, message/_block.py, middleware/_base.py, middleware/_tracing/_setup.py, middleware/_tracing/_attributes.py, agent/_agent.py, agent/_config.py, state/_task.py, skill/_base.py, tool/_base.py, app/middleware/_protocol/_agui.py}`
- Pipecat：`_reference/pipecat/{CHANGELOG.md, LICENSE, pyproject.toml, src/pipecat/frames/frames.py, src/pipecat/turns/*, src/pipecat/transports/*, src/pipecat/observers/*, src/pipecat/utils/tracing/*, src/pipecat/services/*}`
- OpenTelemetry：GenAI 语义约定已迁出主 semantic-conventions 仓库；本地侧证据取自 AgentScope `_incubating` 导入与两者 semconv 依赖声明差异
- AG-UI：`_reference/ag-ui/spec/1.0/{schema.json, proto-freeze.txt, conformance/README.md, conformance/streams/MANIFEST.txt}`、`LICENSE`
- Langfuse：`_reference/langfuse/{LICENSE, docker-compose.yml, fern/apis/server/definition/opentelemetry.yml, web/src/server/otel/processOtelIngestion.ts, package.json}`
