# Hy Memory 三层开源架构：调研结论与 Loomrise 采用裁决 v0.1

日期：2026-10-16。状态：**调研与裁决文档。未安装 Hy Memory / MemHub，未启动任何服务，未发任何 API 请求，未拉取模型权重，未做端到端联调或性能实测。** 本文只输出「三层分别是什么、可复用什么、不采用什么」，不构成已批准选型。

调研来源：官方发布文（mp.weixin.qq.com/s/HEUBvaCF7ZoWjVqZ_n7dog）、GitHub `Tencent-Hunyuan/Hy-Memory`（创建于 2026-10-15，调研时 star 40 / fork 4 / open issues 0）、HuggingFace `tencent/Hy-Memory-30B-A3B`、arXiv:2610.22196。三条线分别由独立调研执行，本文做交叉核对与裁决。

> **口径提醒**：本文与[用户上下文设计](USER-CONTEXT-DESIGN.md)、[既有内核提案](MEMORY-FOUNDATION-DESIGN.md)是**新增关系**，不改写那两份的结论。[MEMORY-FOUNDATION-DESIGN.md](MEMORY-FOUNDATION-DESIGN.md) §2 的「采用 TDAI」是 2026-10-09 的推荐，**不等于已批准或已选定底座**；本文对 Hy Memory 的裁决同样不构成选定。专家-用户记忆体系的正向设计见[专家-用户记忆体系](EXPERT-USER-MEMORY-SYSTEM.md)。

## 0. 结论先行

| 层 | 一句话裁决 | 定位 |
|---|---|---|
| **Hy Memory 框架** | 机制值得抄，工程形态**不能直接用**。无鉴权、无多租户、HTTP Server 无 token 校验、图谱默认关闭、L4/L5 未启用。**作为机制参照 + 只读候选 Provider，不作运行时底座。** | 与 TDAI 并列的第二个具名候选，同条件对照 |
| **Hy-Memory-30A3B 模型** | **不采用权重。** 自定义 `hy_v3` 架构未发布 modeling 代码、无量化版本、BF16 约 60GB，且官方评测不可复现。只借鉴其**训练方法设计**。 | 训练方法机制参照 |
| **MemHub 应用** | **不作为 Loomrise 依赖**（本地明文 SQLite + 依赖托管端点 + 面向个人跨工具记忆）。但它是**搭建者个人层**的可用工具，且其注入预算与授权放行机制值得借鉴。 | 个人层工具（与产品运行时严格隔离）+ 机制参照 |

**最重要的一条区分**：MemHub 解决的是「**同一个人在多个 AI 工具之间不重复交代自己**」；Loomrise 需要的是「**业务用户跨会话的服务连续性 + 专家跨版本的可控改进**」。两者主体不同、生命周期不同、授权模型不同。**不能用「我们也有记忆了」把两者合并。** 详见 [专家-用户记忆体系 §1](EXPERT-USER-MEMORY-SYSTEM.md)。

## 1. 三层架构实测速览

### 1.1 仓库与发布事实

| 项 | 实测值 |
|---|---|
| 仓库 | `Tencent-Hunyuan/Hy-Memory`，创建 2026-10-15，最后推送 2026-10-16（**调研时仅发布 1 天**） |
| 许可 | `LICENSE` 为「腾讯声明 + Apache-2.0 正文」；`pyproject.toml` 写 `license = "Apache-2.0"`；`memhub/NOTICE` 明示无附加限制 → **可商用** |
| 结构 | monorepo：`hy_memory/`（框架）+ `memhub/`（桌面/CLI 应用）+ `plugins/openclaw/` + `docs/` + `tests/` |
| Python SDK | **已发 PyPI**：`hy-memory==2.0.1`（2026-10-15 上传），历史共 29 个版本 |
| TS SDK | **无**。TypeScript 只有 MemHub 的 Electron/CLI 与 OpenClaw 插件 |
| npm | `memhub-cli` **registry 查无此包**；官方主推的 `npm install -g memhub-cli` 当前走不通 |
| GitHub Release | 仅 `v1.0.0`，**只有 3 个资产**（macOS arm64 DMG / linux-arm64 / linux-x64），声明的 macOS x64 与两份 macOS Runtime 缺失 |
| Windows | 不支持 |
| Docker / K8s | **无** |
| 依赖 | `pydantic, numpy, openai, chromadb, kuzu, langdetect, scikit-learn, tiktoken, json-repair, rank-bm25, jieba`；extras：`qdrant / faiss / graph(neo4j) / mysql / rerank(torch,transformers)` |
| 版本策略 | CHANGELOG 自陈「**未采用任何兼容或弃用策略**」 |

### 1.2 模型事实

| 项 | 实测值 |
|---|---|
| 架构 | MoE，`HYV3ForCausalLM`，`model_type: hy_v3`（**混元自研，非 Qwen/Mixtral 派生**） |
| 参数 | 总参 **30,064,719,872**；47 个稀疏层 ×(128 专家选 8 + 1 共享)，独立核算激活 ≈ **3.1B**，与「3B 激活」一致 |
| 上下文 | `max_position_embeddings: 262144`（256K），`rope_theta: 11158840.0` |
| 初始化 | Hy3-30B-A3B **instruction-tuned** checkpoint（不是 Base） |
| 权重 | 51 个 safetensors 分片，BF16 推算 **约 60GB**；**未合并** |
| 许可 | **Apache-2.0**，无附加协议、无地域限制 |
| 缺失 | **无 `generation_config.json`、无 `modeling_hy_v3.py`（自定义代码未随仓发布）、无任何量化版本** |
| 推理框架 | 模型卡只给 vLLM（标注 tested with v0.31.0）；SGLang / llama.cpp / TensorRT-LLM **官方无任何表述** |
| 社区信号 | 发布不足 24h：**downloads = 0**，likes 9，仓库 open issues 0 |

## 2. 框架层：值得抄的十个机制

以下均为一手代码/文档实证，是本文最有复用价值的部分。

| # | 机制 | 出处 | 对 Loomrise 的用法 |
|---|---|---|---|
| 1 | **L1_RAW 提取后降级 SHADOW 而非删除**——保留可追溯性但不污染召回层 | `hy_memory/pipelines/writer.py:12-16` | 直接对应 Loomrise「记忆可撤销但需留删除回执」的要求，是**撤销语义**的实现范式 |
| 2 | **`statement`（进向量）/ `details`（不进向量）双字段分离**——摘要负责能被找到，原文负责找到后真的有那个值 | `hy_memory/coding/types.py` | 用于专家经验：可检索形态与权威原文分离，避免长 diff 挤占召回预算 |
| 3 | **`supersedes` / `superseded_by` / `is_latest` 三字段双向版本链**，召回时折叠到链头 | `hy_memory/models/memory.py:273-275` + `_retrieval/evolution.py` | 与 Loomrise `candidate/active/superseded` 状态机同构，但需补**跨主体与授权校验** |
| 4 | **演化总结刻意不进向量库**——避免已作废措辞重新获得召回力 | `coding/types.py` `fact_chain_summary` 注释 | 直接支撑 Loomrise「派生摘要不得重新获得召回力」的撤销设计 |
| 5 | **事实层 SUPERSEDE 软删 + `fact_link` 回填，并把被覆盖事实的经验链过继给新事实** | `coding/fact_reconciler.py:8-11` | 解决「事实更新后经验随旧事实沉默」的隐蔽泄漏 |
| 6 | **prompt 明令 `Never DELETE just because a candidate looks "stale"`**——删除权限收紧到「有明确否定证据」 | `coding/reconciler.py:75-76` | Loomrise 的**记忆删除必须同此收紧**；模型不得因「看起来过时」而删 |
| 7 | **来源过滤下推到 DB 层**（Qdrant Filter / Chroma where / FAISS ID selector / Neo4j 属性预筛），拒绝 over-fetch 后过滤 | `docs/hy_memory_search_skill.md:116-118` | 授权过滤必须在检索层执行，不能「先取回再判断」 |
| 8 | **`mixed` 记忆在开启任意 source 过滤时 fail-closed 默认排除** | `docs/usage.md:162-163` | 白名单须显式包含；默认拒绝方向正确 |
| 9 | **RRF 只看 rank 不看绝对分**，规避 cosine [0,1] 与 BM25 [0,+∞) 不可比 | `_retrieval/rrf.py:6-8` | 若 Loomrise 自建混合检索，必须用 rank-based 融合 |
| 10 | **`chain_store` 定位为「装饰器而非检索器」**——不做相似度、不选版本，判定权交还指令本身 | `coding/chain_store.py:9-14,47-52` | 强化既有结论：**存储层不裁决，裁决在 `HardRule`** |

另有一条**检索工程细节**值得记：Episode 按**时间间隔免费切分**（`MEMORY_EPISODE_GAP_SECONDS=1800`）、episode 关闭时才总结一次，替代固定窗口摘要的「重复付费 + 旧摘要自我作废」（`agent/episode_summary.py:1-26`）。

### 2.1 冲突消解：Hy Memory 有三套并行机制

| 链路 | 机制 | 关键限制 |
|---|---|---|
| Chat L2 | `MemoryStatus` 六态（`ACTIVE/SUPERSEDED/NEGATED/CONFLICTED/SHADOW/ARCHIVED`）+ 双向链 + `UpdateType`（override/supplement/temporal/negate/conflict） | 层号保留 v1/v2/v3 三代兼容别名，说明层号经过重编号 |
| 工作/代码·经验层 | LLM 产出 `ReconcileOp`：**ADD / UPDATE / DELETE / SKIP** | **覆盖式 update，不留历史** |
| 工作/代码·事实层 | LLM 产出 `FactReconcileOp`：**INSERT / SUPERSEDE**；软删 + `fact_link` + 经验链过继 | **无 TTL**，不靠过期淘汰，靠 embed 召回 + LLM 判覆盖保新鲜 |

**三套机制并存本身就是风险**：同一份记忆在不同链路下语义不同、保留策略不同。Loomrise 若借鉴，必须**先定一套状态机再映射**，不能照搬三套。

### 2.2 已核实的框架层局限（不可忽略）

| 局限 | 证据 | 对业务场景的含义 |
|---|---|---|
| **无鉴权、无多租户** | 内置 HTTP Server 是 stdlib `ThreadingHTTPServer`，默认绑 `127.0.0.1:19527`，声明了 `Access-Control-Allow-Headers: Authorization` 但**无任何 token 校验代码** | **不能暴露公网，不能承担租户隔离** |
| 图谱（事件脉络/实体关联）**默认关闭** | `MEMORY_ENABLE_GRAPH` 默认 `false`，仅 `ultra` 强制开 | 2.0 主打的「事件脉络」在默认配置下**不可用** |
| L4/L5 层 Reserved | README 明标 Identity / Knowledge 为 "Reserved" | 「身份画像层」未启用 |
| L7 Intention 默认关闭 | `intention_limit` 默认 0 | 主动意图能力需显式开启 |
| 无全局 token budget | 仅两处局部分层 bundle 预算（各 400）；主要靠「少而精」而非预算裁剪 | Loomrise 的预算纪律（条数+token+时间+用量）**必须自己实现** |
| 无显式分层降级 | 实际是**并列多通道 + 配额**，非「上层不够→回落底层」 | 不能假设 Provider 帮我们做了降级 |
| `hybrid` Reader 在默认 Chroma 上退化为纯向量 | `docs/hy_memory_search_skill.md:21-22` | 混合检索需换 Qdrant 才生效 |
| 强制 working/coding 无 tool 时**静默回退 chat** | `docs/scene_coding_usage.md:62` | 不报错，调用方难以察觉，是**观测陷阱** |
| `subject` 硬锚点闸门**默认关闭** | `_SUBJECT_GATE_DEFAULT = False`；官方注释自陈关掉后「跨主体误合并会回来」 | 跨主体误合并风险**默认存在** |
| Entity Store 当前 Reader 不读 | `docs/env_reference.md:182` | 实体能力名义存在、实际不通 |
| 无兼容/弃用策略 | CHANGELOG 自陈 | **不能作为生产强依赖** |
| 12 个召回辅助开关默认 false | `docs/env_reference.md` | 「上下文组装」多数增强需逐个开启，配置面很大 |

## 3. 模型层：方法可抄，权重不用

### 3.1 训练方法（arXiv:2610.22196，一手）

两阶段，都是这轮记忆专用模型里最扎实的设计：

**Stage 1 · Memory On-Policy Distillation (OPD)**
- 教师**不生成示范轨迹**，只在学生自己生成的 token 流上给 top-50 分布，做 **reverse-KL 蒸馏**；损失中**无标准 CE/SFT 项**
- **on-policy 状态链**：每个 chunk 配对「前序学生写入产生的 harness state」，非静态模板；chunk ≈10 turns，不跨 session
- 超参：2 rollouts/row，LR 1e-6，entropy coef 0.005，prompt ≤4096，response ≤126,976

**Stage 2 · Memory RL（Attributed RL）**
- 组合奖励 `s[t] = 1·prm[t] + 2·orm[t] − 0.3·pen[t]`，**γ=0**（不向过去广播未来分数）
- **per-chunk recall reward (prm)**：8 类探针（specificity / 语义精度 / plain recall / 次要维度 / transition / should-not-store / content-not-meta / 闲聊细节）。论文特意澄清 **PRM 指 per-chunk recall reward，不是对隐藏推理链的过程奖励**
- **attributed cross-chunk reward (orm)**：judge 判断答案恢复了多少「由 chunk t 引入的 gold evidence」；gold facts 对 judge 可见但**不入库、不进 query、不进 answer prompt**
- **over-storage 控制**：trap probes（不该存的问候/空泛赞美存了就扣分）+ bank-growth penalty（**按 token 而非条数计**，防止靠拉长旧记录膨胀）
- **chunk-level GRPO**：8 rollouts × ≤5 chunks 网格，advantage **按列归一化**（最佳 rollout 可随 chunk 改变）；最佳 bank 按 `Σ_t s[i][t]` 选出并**携带到下一个 window**
- 防 call-count 偏置：多调用 chunk 的多个 segment 共享 advantage 但**只算 1 票 baseline**
- 规模：batch 64 windows × 8 rollouts = 512 trajectories，LR 5e-6，**128×H20**
- 奖励数据：正探针 **164,576**、traps **8,599**、outcome questions **~60.8k**、chunk 级 gold-fact 引用 **222,395**

**明确没有的**（官方原文）：
- ❌ **无 CoT / reflection / 长链推理**——"We do not label a hidden reasoning chain"，改监督外部可验证后果
- ❌ **记忆操作未 token 化**——模型生成结构化 JSON / tool-call 式输出由各 harness 解析；ADD/UPDATE/DELETE/NOOP 属相关工作 Memory-R1，不是本模型统一 action 词表
- ❌ **未训练 retrieval**——只替换 write path 的 LLM，reader 与检索逻辑保持框架原生

### 3.2 「55.49 > Opus 5 54.62」的诚实解读

官方协议：只替换 memory writer，固定 harness 版本/prompt/检索配置/answer model/judge，每个 writer 从空 bank 起步；四 harness × 六指标等权平均。

| Harness | vs Opus 5 | 性质 |
|---|---|---|
| Hy-Memory（自家） | **+0.02** | **论文自述 parity，非显著** |
| MemOS | **+0.01** | **论文自述 parity，非显著** |
| Mem0 | +0.60 | 未做显著性检验 |
| **EverMemOS（held-out）** | **+2.86** | **唯一有实质分量的迁移性证据** |
| 宏观平均 | +0.87 | |

**逐指标看并非全面领先**：Mem0 harness 上 LoCoMo **59.54 vs Opus 69.47（落后近 10 分）**；Hy-Memory harness 上 LME / PM-v2 / Shop. / CMB 四项**全部落后**，仅靠 Travel / LoCoMo 补回。

**六重削弱**：
1. 主矩阵全部跑在 **fixed 20% benchmark subsample** 上，题量、抽样算法、种子**均未披露**
2. 每指标小数点后两位（如 18.33 / 21.11，实为 9 题量级的离散值）——**采样噪声量级很可能与报告差距同阶**
3. **无任何正式 ablation**：chunk-level vs window-level GRPO、归因 ORM vs 广播、trap probes、growth penalty、OPD vs 通用 SFT、单框架 vs 混合训练，全部未做对照
4. **评测代码未开源**——仓库根目录实测 `.env.example/.github/docs/hy_memory/memhub/plugins/scripts/tests`，`evals/`、`eval/`、`benchmarks/` 均 Not Found
5. **judge 与 answer model 身份未披露、prompt 未开源**；论文自己把「judge 对 prompt/模型/重复采样的敏感性」列为**未来工作**
6. 成本与时延数据**完全未公布**

**正面回答**：「自家框架 bias」假设**基本不成立**——在自家框架上仅领先 0.02 分，无主场优势；最强增益反而出现在完全未参与训练的 EverMemOS。

### 3.3 不采用权重的四个理由

1. `hy_v3` 是自定义架构且**未发布 modeling 代码**，`generation_config.json` 也缺失——第三方框架适配存在实质门槛，这是当前最大部署风险点
2. BF16 约 60GB，**官方无任何量化版本**；量化数字只能引自同架构兄弟模型的第三方实测，**非本模型实测**
3. 评测不可复现 → **无法判断它是否在我们的场景更好**
4. 仓库 README **默认配置就是 `deepseek-chat` + `text-embedding-v3`**，官方框架本身默认不挂这个专用模型——说明整套 pipeline 在通用模型上可跑通

### 3.4 真正值得抄的四条

| # | 机制 | Loomrise 用法 |
|---|---|---|
| 1 | **trap probes（不该存就不存）** | 「记得」类记忆最常见的失效是**过写**。应在人评与标注环节建立「本不该入库」反例集，作为硬门禁 |
| 2 | **bank-growth penalty 按 token 而非条数计** | 记忆预算应按 **token 体量**而非条数计费，防止靠拉长旧记录膨胀 |
| 3 | **on-policy 状态链训练**（chunk 配对前序写入产生的状态） | Loomrise 自建抽取评测集时，**评测输入必须是「已积累记忆的状态」而非空 bank**，否则测不出冲突消解能力 |
| 4 | **γ=0 的逐 chunk 奖励 + 最佳 bank 跨 window 携带** | 「把下一步建立在当前最佳记忆状态上」是长程记忆的正确评估姿势，可直接进我们的评测方法 |

## 4. 应用层：MemHub 的实证与定位

### 4.1 技术栈与交付

| 项 | 实证 |
|---|---|
| 桌面 App | **Electron**（`electron ^44.0.0`），非 Swift/Tauri |
| Web 管理台 | React + TypeScript（`apps/web`，253 文件） |
| CLI | Node/TS（`apps/cli`，105 文件），**40 个顶层命令** |
| 内核 | Python 3.12 / FastAPI（`apps/core`，677 文件），依赖 `hy-memory==2.0.1` |
| 安装 | `npm install -g memhub-cli` → `memhub install`（bootstrap CLI 仅 ~384KB）——**但 npm 包不存在，只能手动下 DMG** |
| auto-updater | **无** |
| 成熟度 | 仓库仅 1 个 issue（且无关）；README 多处「未完成真机验收」 |

### 4.2 数据安全（对业务场景最关键）

- 纯本地 SQLite 单文件：`~/.one-memory/one-memory.sqlite3`；向量侧 chromadb PersistentClient + kuzu
- **无静态加密**：全库无 SQLCipher/cipher 引用，Evidence 原文可被任何本机进程读取
- API Key 存 macOS Keychain
- **无上传，但有条件外发**：`PRIVACY.md` 明确「选择第三方模型服务时，会把完成任务所需的获授权内容发送给该服务」。`ProviderKind` 含 `HY_DEFAULT`（**端点由产品托管、不可自定义 base_url**）→ **抽取环节默认走云端，会外发对话内容**
- Hy-Memory-30A3B 是 HF 上的开源权重，但 **MemHub 默认并不本地跑它**
- ⚠️ debug 模式（`MEMORY_LOG_LLM_CONTENT=true`）会落盘完整对话正文，**切回 info 不会自动删除已写文件**
- 官方明确不采集屏幕/AXTree/OCR/键鼠/剪贴板/录音

### 4.3 跨工具接入机制（已查实）

**双向两条独立通道**：
- 「一键插入应用」= MemHub → Harness 的 **Recall**（读记忆）
- 「同步开关」= Harness → MemHub 的 **Capture**（读会话）
- Capture 有两条实现并存：**Core 定时轮询扫描本地会话文件**（`live_sync_interval_seconds=60` + 文件 watcher）+ **宿主 Hook 实时入口**。**不是 API 代理。**

| Harness | Recall | Capture | 数据源 |
|---|---|---|---|
| **WorkBuddy** | `.codebuddy-plugin` 内 MCP + Skill | Plugin Hooks | `~/.workbuddy/projects` |
| Cursor | MCP + Skill | Capture Hooks | Cursor DB 扫描 |
| Claude Code | MCP + Skill | Capture Hooks | `~/.claude/projects` |
| Codex | MCP + Skill（TOML） | Capture Hooks | `~/.codex/sessions` |
| Hermes | MCP + Skill | 无 Hook，纯扫描 | `~/.hermes` SQLite |
| Qwen Code | MCP + Skill | 无 Hook | `$QWEN_HOME/projects` |
| OpenCode | MCP，**无 Skill** | JS Capture Plugin | OpenCode DB |
| Pi | **CLI Skill，不用 MCP** | JS Capture Extension | Pi session |
| DeepSeek Harness | **Profile 级 MCP Patch** | 无 Hook | `$DSH_HOME/sessions` |
| OpenClaw | **已冻结，开关不可用** | 无 | Adapter 冻结 |
| Qwen Work | 无 Recall 目标 | — | `~/.qwenworkcn/projects` |

**官方宣称「10 种工具」与仓库实际有偏差**：实际 11 个 `source_id`，其中 OpenClaw 已冻结、DeepSeek 存在仓库自陈的 UI Bug → **可用数为 9～10**。

**WorkBuddy 接入是全仓库唯一真正落成 `.codebuddy-plugin` 目录的宿主**，产物：

```
~/.workbuddy/plugins/marketplaces/one-memory/plugins/one-memory-recall/
  .codebuddy-plugin/plugin.json | hooks/hooks.json | skills/memhub-recall/SKILL.md
~/.workbuddy/plugins/cache/one-memory/one-memory-recall/1.0.0/   ← MCP 从这里加载
```

MCP 工具名（stdio JSON-RPC → Broker → Core）：`om_recall` / `om_ask` / `om_conversations` / `om_matters` / `om_context` / `om_memory_write` / `om_memory_write_status` / `om_diagnostic_trace`。

### 4.4 记忆如何进入宿主上下文：两条路并存

1. **主动注入（hook 边界）**——`recall-injection.ts` 在 `SessionStart` / `UserPromptSubmit` 用**用户原话**检索，以 `additionalContext` 交给宿主。硬预算 3500ms、正常门限 1.5s、最多 8 条、单条 640 字符、总 4000 字符，**fail-open**。宿主侧靠 `strip_injected_memory` 防回声。
2. **工具调用按需拉取**——模型自主调 `om_recall` / `om_context`，受 Scope/Tools 授权门控。

**第 1 条路正是 [MEMORY-FOUNDATION-DESIGN.md](MEMORY-FOUNDATION-DESIGN.md) §2.2 已否决的「把记忆 blend 进 system prompt」形态。** MemHub 做得比 TDAI Proxy 细致（fail-open、硬预算、回声剥离、身份重验），但**形态冲突不因工程细致而消失**：模型看到的内容与 Loomrise 记录的加载事实将不一致。**若将来评估 MemHub，只能走第 2 条路（工具按需拉取）。**

### 4.5 值得借鉴的五个工程机制

1. **把「读」与「写」拆成两个独立授权开关**（一键插入 / 同步），组合出 4 种状态，比单一开关清晰
2. **派生键去重**替代「查重再入队」——从根上消除 hook 与扫描器双路的 race（`intake_dedupe.py`，派生键如 `session:first_round-last_round`）
3. **Broker 二次鉴权 + fail-closed**：凭据按 installation revision 绑定，放行前重验，撤销立即生效
4. **响应逐条校验 lane 与 raw source**——防御「Core 缺陷把 raw 泄给只有 memory 权限的安装」，这是最易踩的越权坑（`docs/contracts/host-context-transport-v1.md`）
5. **两阶段危险操作**：`plan --json` → `--approve <fingerprint>` / `apply --plan-file --confirm`，比 `--yes` 更能防误触

### 4.6 命名反直觉处（记录以免误用）

- **没有 `memhub forget`**——删除走 `memories plan delete` + `apply --confirm` 两步
- **没有 `memhub mcp`**——MCP 由 App bundle 内的 Electron 入口承载
- 记忆编辑：`memories plan correct|delete|scope`；注入防污染：解析层剥离 `<automation_system_reminder>`、`<codex_internal_context>` 等宿主生成前缀

## 5. 与既有候选的关系：不是替代，是并列

| 候选 | 定位 | 与 Hy Memory 的关键差异 |
|---|---|---|
| **TencentDB Agent Memory（TDAI）** | 具名候选，MIT，**108 个接口**，L0–L3 分层 + 四类 Memory Asset + ACL 可见性模型 | TDAI **有** ACL/可见性语义（private/team/restricted/agent）与业务对象绑定；Hy Memory **无鉴权无多租户** |
| **Hindsight** | 机制参照（retain → observation consolidation → recall/reflect），MIT | Hindsight 的 `reflect` 是建议；Hy Memory 强在**状态更新与冲突消解的工程细节** |
| **Hy Memory** | 新增并列候选，Apache-2.0，**有状态更新/冲突消解/工作·代码记忆** | 业务编排、租户、ACL、留证**全部缺失**，需 Loomrise 侧自建 |

**裁决**：
1. 三个候选**同条件并列**，先冻结合同与故障集，再挑**一个**做只读 Adapter 实测。**不叠加多个记忆内核**（沿用 [USER-CONTEXT-DESIGN.md](USER-CONTEXT-DESIGN.md) §9 与 [联合计划](TASK-MEMORY-INTEGRATION-PLAN.md) §4 的纪律）
2. 若实测，**Hy Memory 优先验证「工作/代码记忆 + 冲突消解」这一路**——这是它相对 TDAI/Hindsight 的真实增量，而聊天记忆能力三家重叠
3. Hy Memory 的自动 reconcile 管线（LLM 直接判 ADD/UPDATE/DELETE）**必须降级为候选生成器**：Loomrise 侧写入一律为 `candidate`，与 [MEMORY-FOUNDATION-DESIGN.md](MEMORY-FOUNDATION-DESIGN.md) §2.4 第 1 条、TDAI 裁决完全一致
4. **不 fork 代码、不引入 Proxy 注入、不暴露其 HTTP Server**

## 6. 与专家记忆的关键冲突（必须改造后才可用）

Hy Memory 的工作/代码记忆**不能直接映射**到 Loomrise 的 `AgentVersion`：

| 维度 | Hy Memory | Loomrise | 结论 |
|---|---|---|---|
| 版本语义 | git `branch`（开发过程） | `AgentVersion`（**已发布业务契约**，冻结、评测、发布、可回滚） | **语义完全不同，禁止映射** |
| 经验归属 | `user_id + agent_id + workspace_id` | 须为 `tenant_id + expert_id`，**跨版本连续** | 需新增归属维度 |
| 适用条件 | `boundary_envs` + LLM 判断 | `HardRule` **条件只能引用已声明字段、禁止自由文本**（[HARD-RULE-MODEL.md](HARD-RULE-MODEL.md)） | **自由文本适用条件无法确定性裁决，必须改造** |
| 写入路径 | 自动 reconcile 直接改状态 | `candidate → 采用 → 评测 → 审批 → 发布` | **自动管线必须降级为候选** |
| 撤销 | SHADOW + 恢复 | `revoked/forgotten` + 删除回执 + 派生失效 | 需补派生失效链 |

**核心风险提示**：Hy Memory 的「经验 + 适用条件 + 复用前校验」与 Loomrise 的硬规则体系**方向一致但载体冲突**——它的适用条件由 LLM 判断，我们的适用条件必须可确定性裁决。若不改造，专家记忆会成为唯一一条「模型说了算」的路径，直接违反[产品定义](PRODUCT.md) §合规排除与[六层合同](CONFIGURATION-LAYERS.md) §7.4。

## 7. 落地动作（本轮不做）

| # | 动作 | 前置 | 归属阶段 |
|---|---|---|---|
| 1 | 把「工作/代码记忆 + 冲突消解」加入只读 Adapter 实测候选，与 TDAI 同条件对照 | 稳定 `subject_id` 合同冻结 | TM-0x |
| 2 | 把 trap probes（不该存就不存）纳入人评与标注的反例集 | 验收域第 4 页「人评与修正」 | S2-c |
| 3 | 把「按 token 计的记忆预算」写入预算纪律 | 预算阈值登记 | TM-0x |
| 4 | 把 §2 十个机制逐条对照「我们要不要 / 我们已有 / 我们明确不做」 | 记忆合同冻结 | TM-0x |
| 5 | MemHub 作为**搭建者个人层**工具单独评估（与产品运行时隔离） | 确认是否纳入个人工具链 | 个人层，不进 ROADMAP |
| 6 | 若评估 MemHub 接入，**只允许工具按需拉取**，禁用 hook 主动注入 | 与 §2.2 裁决一致 | 接入评估时 |

## 8. 信息可信度标注

**✅ 一手实证（代码/元数据，可复核）**：全部仓库元数据、schema 字段与状态枚举、冲突消解三套机制与 prompt 原文、检索融合权重与默认值、PyPI 已发布 / npm 未发布、HTTP Server 无鉴权、Kuzu 单进程锁、图谱默认关闭、L4/L5 Reserved、15 项框架局限、模型 config 与 safetensors 实测、WorkBuddy `.codebuddy-plugin` 产物结构、40 个 CLI 命令、SQLite 路径与无加密、11 个 `source_id` 映射、MCP 工具名与 Broker 鉴权模型、`ProviderKind` 枚举、Apache-2.0。

**✅ 论文一手（arXiv:2610.22196 v1）**：两阶段训练方法、全部超参与奖励数据规模、per-chunk recall reward 澄清、γ=0、chunk-level GRPO 与 bank carry-over、20% 子采样、作者自述 0.01–0.02 为 parity、judge/answer model 身份未披露、无 ablation、无成本数据。

**⚠️ 二手（官方发布文，仓库未披露，无法复核）**：全部 Benchmark 分数（55.31% / 64.2% / 35.6% / 28.3% / 72.6%）、「开源第一」结论、LoCoMo token 1159→703（−39.3%）、**「三类场景存储占用均很小」——只有三张散点图，正文无任何字节数或压缩率**、腾讯内部业务数据（自选股 64.3→79.6、iWiki 36.7% vs 24.7%、腾讯新闻 91.68）。

**❌ 未证实 / 存疑**：CodeMemoryBench 任务形态与打分方式；MemoryArena 55.31% 的子集与口径；SWE-ContextBench 28.3% 与原论文 Lite 基线（Mem0 24.24% / OpenViking 29.20% / Supermemory 30.30%）**不一致**，按原论文 29.20% 的 OpenViking 数字则 28.3% 并非第一；LoCoMo 72.6% 的 writer 与配置；召回时「剥离前后冲突」是否有独立 LLM 步骤；`rrf.py` 是否仍在主链路（`reconcile_retrieval.py` 用的是 additive 融合）；`TemporalEvent`/`UserTimeline` 是否真正接入链路；是否需要注册腾讯账号才能用 `HY_DEFAULT`；macOS x64 制品是否补发。

**🔴 需纠正的官方宣称**：① 「benchmark 上均为开源第一」——评测口径与代码未开源，不可独立复核；② 「平均分超过 Opus5」——在 4 个 harness 中有 2 个是作者自述的 parity；③ 「10 种 AI 工具」——实际 11 个 `source_id`，OpenClaw 已冻结、DeepSeek 有 Bug；④ 「存储占用均很小」——无任何可复核数字；⑤ `npm install -g memhub-cli`——包不存在。

## 9. Sources

- GitHub: <https://github.com/Tencent-Hunyuan/Hy-Memory>（调研时 commit `fba347a`，main）
- HuggingFace: <https://huggingface.co/tencent/Hy-Memory-30B-A3B> · config: `.../raw/main/config.json`
- 技术报告: <https://arxiv.org/abs/2610.22196> · 全文 HTML: <https://arxiv.org/html/2610.22196v1>
- 官方发布文: <https://mp.weixin.qq.com/s/HEUBvaCF7ZoWjVqZ_n7dog>
- 官方站点（另一套评测口径，与 55.49 不可混用）: <https://memory.hunyuan.tencent.com/simple/index.html>
- 关键文件路径：`hy_memory/models/memory.py`、`hy_memory/coding/{types,reconciler,fact_reconciler,store,chain_store}.py`、`hy_memory/pipelines/writer.py`、`hy_memory/_retrieval/{evolution,dedup,rrf,temporal,underflow}.py`、`hy_memory/agent/episode_summary.py`、`docs/pro_graph_design.md`、`docs/usage.md`、`docs/env_reference.md`、`docs/hy_memory_search_skill.md`、`docs/contracts/host-context-transport-v1.md`、`memhub/apps/core/src/one_memory/{config,imports/sources/workbuddy}.py`、`memhub/docs/harness-support/workbuddy.md`
- 未做：安装、启动服务、发 API 请求、下载权重、端到端联调、性能与召回质量实测、第三方复现