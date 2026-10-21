# 配置后台 Task/Harness 前端增量开发计划 v0.1

> **For agentic workers:** REQUIRED: 使用 `subagent-driven-development` 将边界清楚的视图/纯函数工作分配给子 Agent；共享状态和集成文件由主 Agent 统一维护。本文复选框记录未来实现进度，不代表已实现或已验收。

**Goal:** 在现有 `console-next` 后台中增量实现专家版本内任务/主动服务配置、服务事项与 Inbox 同源投影、按需证据和版本影响预览；仅验证本地前端交互，不执行真实业务动作。

**Architecture:** 保留原生 HTML/CSS + ES modules、四组导航和三种配置深度；配置仍属于同一专家草稿，服务事项在列表和 Inbox 中共用一份本地投影。新增 `task-domain.js` 与 `task-sandbox.js` 承载确定性规则/模拟，视图只呈现和提交明确标记的本地意图；所有真实权限、持久性、运行、发布与迁移仍由正式服务及其 Gate 决定。

**Tech Stack:** 现有原生 ES modules、HTML/CSS、Node.js 内置 `node:test`；浏览器检查使用仓库已有 Playwright 页面脚本，不新增运行依赖或 UI 框架。

---

日期：2026-10-19。状态：**前端开发计划，全部未开始**。现行设计依据为[体验设计 §12](../../CONFIGURATION-UX-OPTIMIZATION.md#12-专家任务与-harness-的后台增量设计)、[后台 IA §8](../../S2-IA-NAV.md#8-taskharness-后台增量落点)、[启动方案 §8](../../S2-CONSOLE-KICKOFF.md#8-taskharness-后台增量工作包)及[Task 体系设计](../../TASK-SYSTEM-DESIGN.md)。本文细化 CT-00–06，不替代 Python Task 首片[实施计划](2026-10-16-expert-task-harness.md)，也不代替后端/API/渠道 Gate。

## 范围与开工约束

- 唯一实施基线是 `prototypes/console-next/`；`prototypes/s2-console/` 是历史首轮，`loomrise/web.html` 是 S1 客服入口，不作为后台开发底座。
- 仅做浏览器本地原型投影、确定性模拟和旧本地数据兼容。不可连接 API、数据库、真实模型、外部 Agent/MCP、调度器、消息渠道或云服务；不得产生真实 Task、触达、审批、发布、迁移或业务写入。
- 保留四组导航和三种配置深度。“任务与主动服务”是专家配置中的可选模块；“服务事项”是在运行与验收下的集合入口。详情/编辑不另建导航域，不建共享策略库、全量 CRM 或第七层 Harness 配置。
- `AgentSpec.task_blueprints` 随 `AgentVersion` 冻结；默认事项定义与用户实例分离。没有蓝图不阻断手动 FAQ；保存草稿不初始化用户事项；发布预览不默认迁移在途义务。
- 只接受字段目录驱动的有限类型化条件。项目的正式字段/算子合同仍未全部确定，因此先用明确标注的虚构目录测试投影和阻断行为；未知/过期/不兼容条件须原样保留、只读并阻止覆盖。不得用自由文本、脚本或任意 JSON 替代。
- 主动触达必须将身份、目的、当前许可、渠道、频次/去重、停止条件与结果证据分别呈现；先形成候选，采用与执行许可分开。禁止“对所有用户自动联系”的单一开关。
- Tool 保持少量语义入口。前端只展示角色/任务范围下的能力摘要和实际披露快照投影，不新增 CRUD 工具、万能 `invoke` 或通过可见性授权的路径。
- 当前原型已有 16 路由和 `schema: 1` 本地 Store。本轮升级本地浏览器数据格式时目标为 schema 2，并显式测试 schema 1 → 2 的非破坏性迁移；不得推断主体、补造事项或覆盖未知数据。
- 所有操作按钮、身份/权限、证据及结果均应区分“模拟/本地草稿”与真实事实。页面、localStorage、前端门禁和模拟结果不能作为服务端验收证据。

## 文件责任

| 文件 | 责任与归属 |
|---|---|
| `prototypes/console-next/TASKS-CONTRACT.md` | 记录本地投影形状、字段来源、稳定 key、版本/revision、状态分层及模拟边界；不是正式 API 合同 |
| `prototypes/console-next/task-domain.js` | 纯函数：蓝图/事项投影校验、稳定 key、状态与引用/授权展示、受限本地意图规则；不操作 DOM 或存储 |
| `prototypes/console-next/task-sandbox.js` | 固定虚构主体、周期、事件和注入时钟的确定性预览；不写入 store、不发请求 |
| `prototypes/console-next/fixtures.js`、`tests/task-fixtures.js` | 页面演示数据与测试夹具分开；只使用原创虚构主体/事件，不混入真实用户资料 |
| `prototypes/console-next/views/task-config.js` | 蓝图列表/详情/编辑与初始化结果预览；只通过 `ctx` 与 actions 接入 |
| `prototypes/console-next/views/tasks.js` | 服务事项和待采用候选的列表/详情/意图工作面；不得拥有第二份事项状态 |
| `prototypes/console-next/views/task-evidence.js` | 可复用的依赖、能力、主体上下文和 L0–L2 证据摘要/展开组件 |
| `prototypes/console-next/views/editor.js`、`domain.js` | 将新配置模块加入专家配置，并计算概览摘要/就绪缺口；由集成负责人修改 |
| `prototypes/console-next/views/shell.js`、`app.js`、`store.js`、`views/surfaces.js`、`index.html` | 唯一路由、渲染/actions、本地状态与持久化迁移、Inbox 同源摘要及局部 CSS 加载；由集成负责人独占修改，避免子 Agent 冲突 |
| `prototypes/console-next/task-*.css` | 新增模块局部样式；使用现有 token/布局约定，不重写全局视觉系统 |
| `prototypes/console-next/tests/task-*.test.js` | 纯函数、Store、渲染和交互测试；复杂交互还需浏览器脚本验证 |
| `prototypes/console-next/FRONTEND-CONTRACT.md`、`docs/S2-FRONTEND-ROUND2.md` | CT-00 先补本轮接口/文件所有权合同；实际实现后再记录最终状态、浏览器路径和验证证据，不提前写成功结果 |

## 并行分工边界

- **主 Agent / 集成负责人：** 持有 `app.js`、`store.js`、`views/shell.js`、`views/editor.js`、`views/surfaces.js`、`index.html`、根级 `fixtures.js` 和全局入口的唯一写权限；负责合同合并、数据迁移、action 接线、跨视图状态及最终浏览器回归。
- 现有 `FRONTEND-CONTRACT.md` 对 editor/surfaces/visual Agent 的文件所有权继续适用于其既有页面；新增 Task/Harness 工作包的共享文件归属按本计划覆盖。必须在 CT-00 更新合同并列清新增 `ctx/state/ui` 字段、route key、`data-action`/`data-form` 名称与 payload，以及每个新 view 的输入/输出，冻结后才能并行。
- **视图 Agent A：** CT-01，仅负责 `views/task-config.js`、对应模块 CSS 与独立渲染测试；不得改导航、Store、共享编辑器或全局 fixtures。
- **视图 Agent B：** CT-02，仅负责 `views/tasks.js`、列表/详情局部 CSS 与独立渲染测试；Inbox 接线由主 Agent 处理。
- **视图 Agent C：** CT-03，仅负责 `views/task-evidence.js`、局部 CSS 与组件测试；调用点由主 Agent 接入。
- **并行条件：** CT-00 的投影合同、纯函数接口及虚构目录先合并稳定后，CT-01、CT-02、CT-03 可按上述文件所有权并行。CT-04/05 会碰共用试用、案例和版本视图，待视图批次合并后由集成负责人顺序完成。
- 所有 Agent 共用同一工作区；开工前检查状态、编辑前重读目标段落，不回退他人修改，不整包暂存。每个任务先测试再实现、完成后做规格审查和代码质量审查。

## Chunk 1: 投影与版本内配置

### Task 1 / CT-00: 本地投影合同、虚构目录与故障夹具

**Files:** Create `prototypes/console-next/TASKS-CONTRACT.md`、`task-domain.js`、`task-sandbox.js`、`tests/task-fixtures.js`、`tests/task-domain.test.js`、`tests/task-sandbox.test.js`; Modify `prototypes/console-next/fixtures.js` only for explicit fictional page fixtures and `FRONTEND-CONTRACT.md` to freeze this increment's view/action interfaces and shared-file ownership before parallel work.

- [ ] 阅读本计划引用的 UX §12、IA §8、Kickoff §8 与现有 `FRONTEND-CONTRACT.md`，将正式设计与本地 mock projection 分别标注。
- [ ] 先写失败测试，区分“无蓝图”“显式空条件”“条件未命中”；覆盖已有事项、无主体、无许可、撤权、旧 revision、人工锁、未知结果和取消竞争。
- [ ] 写往返测试，确认 `0`、`false`、空数组与未知字段不被 coercion；未知/过期 Schema 保留原值但标为只读和不可提交。
- [ ] 为固定主体/周期/事件/occurrence 编写重复预览与重复回放夹具；同一 occurrence 重放结果稳定，同一周期换版本也不得增加义务或重置历史事实。
- [ ] 定义最小本地投影：专家/版本/`blueprint_key`、主体/服务周期、来源版本与执行版本、候选/事项分层、revision、允许的实例调整摘要、证据引用和模拟来源标签；仅添加计划页面确需字段。
- [ ] 将字段、事件、算子目录定义为可版本化的 fixture 输入；不冻结正式算子集合、阈值、生产字段清单或 HTTP API。
- [ ] 在 `TASKS-CONTRACT.md` 和 `FRONTEND-CONTRACT.md` 冻结本轮本地 `ctx/state/ui` 字段、route key、action/form 名称与 payload、列表/详情/编辑 view 的输入输出，以及共享文件所有权；旧合同的 Agent 分工仍适用于未涉及的既有页面。
- [ ] 实现无 DOM/无存储纯函数及注入时钟的确定性 sandbox，确保条件摘要和模拟命中是不同输出；sandbox 结果不得写入 store。
- [ ] 运行 `rtk proxy node --test prototypes/console-next/tests/task-domain.test.js prototypes/console-next/tests/task-sandbox.test.js`，预期新增正反例全部通过。

**CT-00 Gate:** 合同形状、未知输入保护、空条件差异和确定性模拟测试通过；没有 API 或生产语义被前端 fixture 暗中定案。

### Task 2 / CT-01: 专家版本内蓝图配置与初始化预览

**Files:** Create `prototypes/console-next/views/task-config.js`、`task-config.css`、`tests/task-config.test.js`; Modify `views/editor.js`、`domain.js`、`store.js`、`app.js`、`index.html`、`fixtures.js`（集成负责人）。

- [ ] 先为蓝图列表/详情/编辑、历史只读、概览摘要、空/缺目录/失效引用和初始化预览编写 view/store 测试。
- [ ] 在原“服务流程”配置深度内增加“任务与主动服务”可选模块；业务配置首层显示目标、类型、适用范围、何时提出/采用、下一步/等待原因、怎样算完成、Agent 可调整项/范围与人工锁摘要；详细配置再展开类型化条件、依赖、频次/去重、许可、停止和证据细节。
- [ ] 以稳定 `blueprint_key` 管理对象；同一三深度操作一个草稿，已发布/历史版本只读，编辑历史仅能派生新草稿。
- [ ] 类型化条件编辑器按虚构字段目录选择控件；摘要是逻辑投影而非命中结果。目录加载失败、旧字段、未知算子和值形状不匹配时保留原值并阻止覆盖/提交。
- [ ] 对无蓝图、空条件和未命中分别显示影响和处理结果；只有固定虚构主体/周期/事件/时钟调用 sandbox。保存草稿或查看预览不得创建事项或启动调度。
- [ ] 从概览、服务流程、Skill、约束、工具和知识的蓝图引用可跳至同一专家/版本的蓝图详情；返回后恢复来源模块、筛选和发起控件焦点。
- [ ] 本地 Store 升级到 schema 2，并测试 schema 1 的旧状态迁移保留专家配置/版本/筛选；不猜测主体、不创建默认 Task。未知未来 schema 应安全拒绝或提供恢复提示，不静默重置。
- [ ] 验证关闭任务模块时原 FAQ 手动路径仍可完成本地试用；页面不要求先配置 Task 或接 Harness。
- [ ] 运行 `rtk npm --prefix prototypes/console-next test`，预期现有与新增测试全通过。

**CT-01 Gate:** 配置归属专家草稿和版本；历史只读、三深度同草稿、类型/未知输入安全、模拟预览无副作用、旧本地状态可恢复。

## Chunk 2: 服务事项与渐进披露

### Task 3 / CT-02: 服务事项列表、详情与 Inbox 同源摘要

**Files:** Create `prototypes/console-next/views/tasks.js`、`task-workspace.css`、`tests/task-views.test.js`; Modify `views/shell.js`、`views/surfaces.js`、`store.js`、`app.js`、`index.html`（共享文件由集成负责人接入）。

- [ ] 先为集合列表、详情、候选分区、筛选/返回定位及 Inbox 同源摘要写渲染/Store 测试。
- [ ] 在“运行与验收”组新增“服务事项”集合入口；导航仍由 routes 单一表生成，四组导航不变。版本筛选之外，默认查看当前有权范围内的各来源/执行版本未决义务；草稿不能隐藏旧版本未决事项。
- [ ] 详情按“业务摘要 → 计划与可调范围 → 尝试/结果/证据”呈现；候选、采用、计划、尝试、回执、Outcome 为不同事实。未知、取消待协调、结果待核验和人工锁不得折叠成成功或普通完成。
- [ ] 将 Inbox 作为同一服务事项投影/链接，不复制 TODO 清单、不生成第二份状态；接管本身不自动取消义务。
- [ ] 所有允许的“调整/采用/取消请求”按钮只提交本地受限意图，并显示模拟角色、基准 revision 和确认结果；越界、无主体/许可、撤权、过期 revision、人工锁均须保留输入并显示阻断原因。
- [ ] 测试无权范围不出现在列表和错误详情中；不得把前端按钮禁用视为后端 RBAC 已验证。
- [ ] 运行 `rtk npm --prefix prototypes/console-next test`，预期所有 collection、Inbox 与 Task 新增测试通过。

**CT-02 Gate:** 一个事项 store、两个角色投影；全版本未决事项可见，分层时间线和阻断状态清晰，过期/越界操作可恢复。

### Task 4 / CT-03: 依赖、主体上下文、能力摘要与证据展开

**Files:** Create `prototypes/console-next/views/task-evidence.js`、`task-evidence.css`、`tests/task-evidence.test.js`; Modify `index.html` 及 `views/editor.js`、`views/task-config.js`、`views/tasks.js` 的调用点由集成负责人接入。

- [ ] 先写组件测试，覆盖依赖缺失/撤权/过期、主体来源/新鲜度、L0/L1/L2 默认折叠、旧披露快照与 host 降级；L0 校验有界工作集、角色、版本、目的、授权和预算，L1 校验精确 Tool ID/版本/Schema hash 及 loaded/skipped 原因，L2 校验可重建输入与能力快照。
- [ ] 默认仅显示当前决定所需的摘要/缺口；按需展开同一对象的蓝图、Skill、知识、字段、工具 Schema 和证据，不把完整历史或全量上下文常驻页面。
- [ ] 分开显示“已登记”“该 AgentVersion 已授权”“本次快照实际披露”；不能用工具存在/连接成功/名称可见代替本次授权。
- [ ] L0–L2 作为上下文信息深度而非权限等级；停止、安全、权限阻断信息保持可见，预算不足时显示阻断，不用截断隐藏关键限制。
- [ ] L2 允许按授权范围展开必要事实/尝试/回执/结果证据的稳定引用、来源版本和用途；更正、撤回或 forget 改变依赖时，使相关预览/候选失效并解释原因。
- [ ] 从流程、Skill、约束、工具和知识引用跳转到对应版本的蓝图定义，并验证返回时恢复来源位置与焦点。
- [ ] 组件接收明确标记的本地快照；旧版本、撤权和未知 Schema 显示原引用与原因并阻止沿用，不在 UI 内自行扩大可用能力。
- [ ] 运行 `rtk npm --prefix prototypes/console-next test`，预期所有证据组件测试通过。

**CT-03 Gate:** 组件默认最小披露；层级展开不扩大权限；引用、版本、授权与实际披露可区分且可追溯。

## Chunk 3: 模拟验收与版本治理

### Task 5 / CT-04: 固定情景试用和运行前事项回放

**Files:** Modify `task-sandbox.js`、`views/surfaces.js`、`store.js`、`tests/task-sandbox.test.js`、现有/新增浏览器检查脚本；复用当前试用台和案例/运行入口，不另建试用台。

- [ ] 固定虚构主体、时区、周期、事件、occurrence、回执和虚拟时钟；添加正向内部核查、触达候选、无主体、条件未命中、撤权、未知结果和取消竞争夹具。
- [ ] 重复相同 occurrence 的预览/回放及同周期换版本均返回稳定结果、不增加义务或重置历史；切换情景/周期必须显示输入差异。
- [ ] 显示“证据引用 → 确定性模拟裁决 → 事项结果投影”；无蓝图、空条件和不匹配分别有可解释输出。纯条件摘要只显示表达式，不显示命中徽标。
- [ ] 触达情景只产生“候选/阻断”模拟结果，不出现可发送按钮；内部事项模拟不创建持久 Task、不伪造 ServiceRequest/Run、不调用渠道。
- [ ] 覆盖取消、切换情景和迟到结果时不污染当前界面；刷新后页面仍明确本地模拟来源。
- [ ] 运行 Task sandbox 测试并用 Playwright 页面检查完整情景路径，预期所有输出可从固定夹具复现。

**CT-04 Gate:** 情景输出确定、可复现且无副作用；生成、采用、尝试、回执和结果彼此区分。

### Task 6 / CT-05: 蓝图 Diff 与在途影响预览

**Files:** Create `prototypes/console-next/tests/task-version-diff.test.js`; Modify `task-domain.js`、版本/改进视图（通常为 `views/surfaces.js`）、`store.js`、`app.js`（集成负责人）。

- [ ] 先测试两版蓝图按 `blueprint_key` 与字段做新增/删除/修改/未变差异；数组位置不作为对象身份。
- [ ] 显示来源/目标版本与基准 revision、主体/服务周期、明确的事项集合、各实例 revision、依赖状态、模拟权限快照和计算时间；状态须区分“完整计算为 0”“未加载”“无权读取”“计算失败/未知”，不能把后四者显示为 0。
- [ ] 过期基准要求重新计算并保留人工输入；冲突按字段提示旧值/新值/人工编辑，不自动覆盖。
- [ ] 发布和迁移是不同操作；默认发布只影响新服务周期/新建义务，不重初始化同一周期，也不迁移现有事项。模拟投影在缺权限或授权时必须拒绝迁移确认，运行中事项不换版；回滚不恢复退订/删除/取消等历史事实。
- [ ] 删除蓝图前显示引用及在途影响；定义移除不删除已登记服务事项。
- [ ] 运行 `rtk npm --prefix prototypes/console-next test` 并逐条检查 Diff/未知影响/撤权拒绝浏览器路径。

**CT-05 Gate:** Diff 稳定且语义化；发布不默迁；未知影响不误报安全；过期、无权、运行中和历史事实均受保护。

## Chunk 4: 集成、无障碍与交接

### Task 7 / CT-06: 全量回归、恢复路径和前端合同交接

**Files:** Modify `prototypes/console-next/FRONTEND-CONTRACT.md`、`prototypes/console-next/DESIGN.md`、`docs/S2-FRONTEND-ROUND2.md`；必要时补 `tests/task-*.test.js`、`views/*.css` 和实现文件。仅记录真实已运行结果。

- [ ] 对比主分支/起始工作区状态，确认所有任务文件归属清晰、没有覆盖既有未提交工作。
- [ ] 运行 `rtk npm --prefix prototypes/console-next test`；预期全量通过，并记录测试数量、Node 版本和实际命令。
- [ ] 用 `console-optimization-browser-check.js`、`knowledge-workspace-browser-check.js`、`materials-browser-check.js`、`visitor-browser-check.js`、`browser-check.js`、`browser-edge-check.js`、`layout-check.js`、`terminology-browser-check.js` 及新增 Task 浏览器脚本检查配置、引用往返、事项、Inbox、证据、试用、Diff；桌面/手机视窗至少覆盖 1440px 和 390px；检查键盘操作、对话框返回焦点、返回保留筛选、加载/保存失败保留输入。
- [ ] 手动检查浏览器 200% 缩放与屏幕阅读器（VoiceOver/NVDA，当前电脑可用其一）；未执行就明确保留为未通过/未验 Gate，不用 DOM 快照替代实际朗读。
- [ ] 验 schema 1 本地数据迁移、未知未来 schema、损坏存储/配额错误、刷新恢复、详情加载失败、草稿并发 revision、相同意图重试和模拟迟到结果。
- [ ] 检查视觉和文案没有声称真实调度、自动触达、API 权限、正式审批/发布或跨版本迁移已实现。
- [ ] 只在新增轮次实际实现后更新前端合同及报告；记录改动文件、测试输出/浏览器流程、未测项和后端交接依赖。不得修改 README/ROADMAP 的实现状态，除非有独立真实服务验收证据。
- [ ] 收尾运行 `rtk git status --short`、`rtk git diff --check`、`rtk git check-ignore -v private/`、`rtk git diff --cached --name-only`；检查本计划、本地合同、README/索引链接锚点和暂存区敏感范围。

**CT-06 Gate:** 现有回归无退化；新增状态/恢复路径有可复现测试；可访问性与未覆盖项分开报告；本地前端完成不关闭 TM/AGI/渠道/发布 Gate。

## 明确不在本计划

- 正式 `AgentSpec` / `AgentVersion` / `TaskItem` API 或数据库合同、服务端 schema、身份认证、租户隔离和 RBAC。
- Task 首片 Python 服务、事务/幂等/恢复、真实调度/领取/取消对账或 Worker。
- 真实主动触达、渠道连接/许可验证、消息发送/送达、业务工具写入和结果回执。
- 真实 Harness/host 接入、动态 Tool Schema 发现、生产 Skill/知识检索和模型成本收益结论。
- 真实评测、审批、发布、回滚、批量版本迁移、在途迁移、云部署和多租户。

## 给新会话的启动顺序

1. 阅读仓库 `AGENTS.md`，按全局规则先读取 RTK 并检查工作区；再读 `README.md`、总索引、PRODUCT/ARCHITECTURE/ROADMAP/OPEN-SOURCE-BOUNDARY，以及本计划开头引用的设计。
2. 核对当前代码和计划状态；不把本计划勾选状态、现有 prototype localStorage 或过去轮次测试当成本轮 Task 验收。
3. 先由主 Agent 完成 CT-00 并锁定仅本地投影接口；随后可将 CT-01/02/03 按“并行分工边界”分给三个视图 Agent。CT-04/05 等前序视图完成后再由集成负责人推进。
4. 每个任务按测试先行与两阶段审查执行；任何正式合同未确定处保留阻断/只读状态，记录为后端或产品依赖，不自行补产品政策。
