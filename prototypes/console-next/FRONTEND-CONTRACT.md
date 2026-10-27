# console-next 前端协作合同 v0.9

状态：2026-10-26，本地前端实施规格。当前配置布局按[线框预览 v0.2](../../docs/CONFIG-UI-PREVIEW.md)和[配置差距需求](../../docs/CONFIG-GAP-REQUIREMENTS.md)实现；验证与未验项见[首轮报告](../../docs/CONFIG-UI-ROUND1-REPORT.md)。代码仍只使用当前浏览器的状态，不连接 `loomrise/` 后端、真实模型、抓取、业务工具、渠道或云服务，CG-23 未实现。

技术：原生 HTML/CSS + ES modules，无构建步骤。XLSX 解析按需加载 `@e965/xlsx@0.20.3`，安装、来源和许可证见[版本钉第 9 节](../../VERSION-PINS.md#9-配置后台前端原型表格解析器2026-10-26)。启动 HTTP 预览前先执行锁定安装，服务目录必须包含 `console-next/node_modules/`；直接打开 `index.html` 不能代替模块与依赖资源预览。

## 当前导航与模块

导航分为工作区与专家两个平面，由 `navigation.js` 的 `routeScope(page)` 根据当前页面决定，不根据 `selectedAgentId` 是否有值决定。工作区可以记住上次选择的专家，但不显示该专家的配置上下文、待处理队列或试一试入口。取消三档深度切换；旧路由保留归属和数据，不新增平行配置库。

| 平面 | 当前入口 | 路由 | 保留页面的新归属 |
|---|---|---|---|
| 工作区 | 专家列表 | `agents` | 名称与“进入”打开专家首页；“去处理”单独定位该专家的待处理事项 |
| 工作区 | 新建专家（列表动作） | `create` | 创建后进入新专家首页，不常驻侧栏 |
| 工作区 | 物料库 | `materials` | 既有资源直达 |
| 工作区 | 模型连接 | `connections` | 既有资源直达 |
| 工作区 | 部署与维护 | `deployment` | 既有资源直达 |
| 专家 | 首页 | `overview` | 当前专家草稿概览 |
| 专家 | 知识库 | `knowledge` | 问答、关键信息、标准话术、核对新资料、按资料看 |
| 专家 | 红线 | `redlines` | 我的红线、平台底线与原转人工触发词 |
| 专家 | 业务办理 | `business` | 原业务动作与结果配置合并为办理卡 |
| 专家 | 对话流程 | `flow` | 同一 `routeGraph` 的流程图和列表 |
| 专家 | 测试 | `test` | `trial`、`runs`、`cases`、`iterations` |
| 专家 | 上线 | `versions` | `inbox`、`widget`、`contact` 放在“接在哪” |
| 专家 | 专家设置 | `settings` | 当前专家设置；`configuration` 为其中的“更多设置” |

工作区侧栏展示专家列表与三个既有资源入口。专家侧栏顶部提供“返回工作区”和当前专家选择器，下面依次为七个工作面与“专家设置”，不加分组或第二个专家列表入口。切换专家保留当前专家工作面的归属，并清理旧专家的临时选择与试用状态；从工作区选专家则进入 `overview`。

桌面展开/收起使用 `toggle-sidebar` 与持久 UI 偏好 `ui.sidebarCollapsed`，不写入专家配置、版本或导航历史。开关固定在顶栏面包屑前，带状态对应的中文无障碍名称、`aria-expanded` 与 `aria-controls`；收起时侧栏不可聚焦，内容区占满宽度。手机继续用独立的 `toggle-nav` / `ui.navOpen` 抽屉，打开、关闭及 Escape 的焦点回到可见控件。布局开关通过订阅动作只更新壳层属性，保留内容区原 DOM、未提交表单与原生文件选择；其他动作继续走正常渲染。

`navigationHash()` 只为专家页面写入 `agent` 参数，`configuration` 可附 `section`；工作区地址不携带专家。首次同步用 `replaceState`，之后仅当页面、专家或配置节的地址发生变化时用 `pushState`，普通编辑不增加历史项。`popstate` / `hashchange` 恢复同一导航状态；不存在或显式为空的专家深链接回到专家列表并提示，不把上次专家当作链接目标。返回工作区关闭侧面板、待处理队列、导航抽屉和历史版本预览，退出只读预览并中止进行中的本地访客轮次；专家草稿、知识和冻结版本保留，重新进入继续读取该专家自己的数据。

本次只调整入口归属。物料仍使用既有资产范围与专家发送策略，模型连接和部署保持既有工作区对象，知识仍按专家保存；不新增共享知识或扩大资源权限。[终态侧栏候选稿](../../docs/S2-SIDEBAR-SPEC.md)中未来的平台设置聚合仍属规划，本原型保留三个已有资源直达入口。

`navigation.js` 负责作用域、地址解析和浏览器历史；`views/shell.js` 负责两平面壳层、主导航和专家待处理队列；`views/knowledge.js` 负责知识与红线；`views/flow.js` 负责流程图和列表；`views/config-pages.js` 负责办理、测试、上线和专家设置；`views/config-panels.js` 负责专家试一试和依据。`app.js` 接线并处理浏览器文件，`store.js` 管理本地状态变更，`domain.js`、`knowledge-model.js` 和 `flow-model.js` 管理纯函数。动态文本仍须转义，视图不在 render 时写状态。

## 当前状态与迁移

原 `schema: 1`、`agents`、`sources`、`runs`、`cases`、`proposals` 和物料结构继续保留。本轮增加 `configurationUiVersion: 2`，以及以下本地字段：

| 对象 | 本轮字段与语义 |
|---|---|
| `config.qaItems` | `{id, question, answer, sourceId, sourceRow?, reviewStatus}`；`reviewStatus` 为 `pending`、`reviewed` 或 `rejected`。旧 FAQ 经 `legacyQaItems(config)` 投影，保留来源关系 |
| `config.keyFacts` | `{id, name, value, unit, effectiveFrom, sourceRef, sourceId?, sourceRow?, reviewStatus}`；文本以 `{名称}` 引用当前值 |
| `config.businessRules` | `{id, title, condition:{field, operator, value}, action, recipient, sourceRef, enabled}`；处理方式闭集为 `handoff`、`confirm`、`refuse`、`end`、`later`。`config.rules` 仍为平台底线 |
| `config.tools` | 在既有字段上增加 `input`、`successField`、`failureAction`、`unknownAction`；写入类仍强制 `requiresConfirm: true` |
| `config.routeGraph` | `{nodes, edges, migratedFrom?}`；节点为 `start`、`decision`、`business`、`reply`、`handoff`，通过 `toolId` 和 `ruleIds` 引用办理及红线。边含 `source`、`target`、`label`、`examples`、`ruleIds` |
| `state.feedback` | 试一试的错误反馈，按 `agentId` 归属，`open` 状态进入待处理；转为测试题后为 `converted` |
| `agent` | `testVersionId`、`liveBindingsHistory` 关联本地冻结快照和入口历史；`changeLog`、`origins` 记录本地修改依据 |
| `ui` | `knowledgeTab`、`reviewBatchId`、`qaEditId`、`factEditId`、`ruleEditId`、`flowView`、`flowSelection`、`flowLayers`、`sideOpen`、`sidePanel: 'trial'|'evidence'`、`pendingOpen`、`quickTrial`、`evidenceTarget`、`testDetailId`、`releaseRequest`、`undoBatch` |

`STORAGE_KEY` 保持 `loomrise:console-next:v1`。旧记录首次保存迁移结果前，原始 JSON 写入 `MIGRATION_BACKUP_KEY`，即 `loomrise:console-next:v1:before-config-ui-v2`；副本写入失败时不覆盖旧记录。旧 `flow` 和 `skills` 转为“开始 → 回复链”，保留 `legacyId`；原转人工词生成带 `legacyHandoff` 的业务红线。迁移属于前端兼容，不证明正式 RouteGraph 合同的全部校验、嵌套或运行时语义已实现。

写操作继续自动保存到 localStorage。保存失败时内容保留在内存，显示重试并允许导出草稿。`undoBatch` 保存当前专家的配置快照，10 秒内可撤销整组核对、关键信息同步和流程批量修改；撤销仅对快照所属专家及适用修订有效，超时或后续配置改动会使旧撤销失效。只读和历史预览继续禁止配置与证据写入。

## 当前交互协议

按钮继续使用 `data-action`，表单继续使用 `data-form`，即时配置控件继续使用 `data-bind`。本轮动作由 `store.dispatch()` 处理：

| 责任 | 动作 |
|---|---|
| 全局面板与待处理 | `pending-toggle`、`pending-open`、`open-trial`、`quick-trial`、`trial-confirm`、`trial-feedback`、`feedback-to-case`、`evidence-open`、`close-side-panel` |
| 知识与关键信息 | `knowledge-tab`、`batch-intake`、`source-review-open`、`qa-edit`、`qa-decision`、`qa-save`、`qa-low-confirm`、`fact-edit`、`fact-save`、`fact-decision` |
| 红线与办理 | `rule-edit`、`rule-template`、`rule-save`、`rule-toggle`、`business-try`、`business-try-run`，办理字段继续用 `update-config` |
| 对话流程 | `flow-view`、`flow-toggle-layer`、`flow-select-node`、`flow-edit-node`、`flow-select`、`flow-filter`、`flow-branch`、`flow-add-fallback`、`flow-node-update`、`flow-node-delete`、`flow-edge-update`、`flow-edge-delete`、`flow-bulk-rule`、`flow-bulk-confirm` |
| 测试与上线 | `test-open`、`test-back`、`case-decide`、`sandbox-deploy`、`release-request`、`release-approve`、`release-rollback`，沿用案例的人工复核与回放动作 |
| 保存与恢复 | `save-now` 仅用于保存失败重试，`undo-batch` 撤销最近可用批量修改，导出草稿使用 `export-config`，设置中的 `export-migration-backup` 可下载迁移前副本 |

`pendingItems(agent, state)` 返回 `{id, level:'block'|'suggest', page, target, text, fix}`。结构化 `validateConfig()`、来源授权与审阅、关键信息出处、办理标志、知识不一致、流程校验、红线近期命中、试用反馈和变差测试题共同产生队列。顶栏、导航计数、首页、专家列表和上线页读取该函数，不从报错文字推断页面归属。

多文件录入使用 `data-batch-files` 和 `data-batch-drop`。`parseBatchText()` 在浏览器中解析 CSV、TSV、TXT 和 Markdown；`parseWorkbook()` 按需加载本地模块，读取 XLSX 的各工作表后转为同类候选。一次最多 500 条候选；PDF、DOCX 和网址抓取仍未接入。整批默认未授权，未完成授权与人工核对的内容不用于脚本答复。风险和不一致检测是本地规则，不代表语义模型解析或真实索引。

`quick-trial` 生成 `mode:'simulation'` 的本地运行记录，分别标记已生成、未送达、解决状态未知；“对”不自动修订真值。“答错了”可转为 `status:'draft'` 的测试题，仍需人工填写和复核。依据面板显示五问及技术详情，链接当前专家的本地记录，不生成服务端审计证据。

问答与关键信息的不同说法须明确裁定，未裁定的新说法不借旧资料抢答。显式问答被否决后，不能再从原 FAQ 或批次正文兜底答复；引用未核对或说法不一致的关键信息时返回待人工确认。红线条件只执行本地确定性匹配；类别词表、金额比较和字面包含分别处理，不冒充真实语义模型或后端规则引擎。`ruleHitCount()` 统一统计同专家过去七天的 `ruleHits`。

流程图与列表共同读写 `routeGraph`。`flow-branch` 以意图、至少三句例句和后续动作生成节点及边；图校验覆盖开始节点、节点与分支上限、连通、例句、其他问题转人工出口、办理引用、写入确认及办成标志。校验问题允许保存草稿，进入待处理并阻止相应测试快照或上线申请。原生 HTML 和 SVG 不含自由代码节点，也不引入画布库。

图按连接遍历，显示多处判断、汇合、执行环和未接入步骤；分支筛选保留前置及后续路径。`flow-edge-update` 允许保存尚未补齐的意图和例句，问题进入待处理；删边保留步骤，删普通链中间步骤时衔接剩余路径。旧 `flow`/`skills` 入口不再提供第二套表单；兼容动作同步同一张图和旧字段投影，并保留稳定步骤的人工保护。

`business-try-run` 只记录人工选择的 `success`、`failed` 或 `unknown` 本地结果，不能作为外部结果 ID 或持久副作用证据。测试题变差时，`case-decide` 记录“答案错了”或“测试题过时了”；后者留存真值修订并回到待人工复核。

`sandbox-deploy` 检查当前草稿并回放已人工复核的测试题，通过后才冻结本地测试快照；无需批准。`release-request` 校验当前修订、测试题签名和阻断项，产生待人工确认申请；`release-approve` 再次核验后更新本地网站客服窗绑定。`release-rollback` 切回前一个绑定快照，保持当前草稿。配置或真值改变会使旧测试、申请或采用依据失效。上述动作不是真实发布门禁或公网部署。

测试快照、申请和最终批准均检查模型连接；回退时重新核验目标版本的可用来源和连接。“答案错了”在改稿后继续阻断，当前草稿重新回放通过才解除。表单暂存按选中值恢复 radio 的 `checked`，不改选项本身的 `value`；流程分支展开状态单独管理，避免重绘循环。

## 前轮协作记录

以下保留截至 2026-10-15 的 v0.6 实施规格和分工，供兼容页面与旧验证定位。四组导航、三档深度切换、旧知识页面、XLSX 仅登记及零新增依赖的描述已由上文替代；旧轮次验证见[第二轮交付报告](../../docs/S2-FRONTEND-ROUND2.md)。

前轮技术为原生 HTML/CSS + ES modules，当时零新增运行依赖。root 负责 store.js、fixtures.js、app.js、helpers.js、index.html 与测试/文档；editor worker 仅 views/editor.js；surfaces worker 仅 views/surfaces.js；visual worker 仅 styles.css、views/shell.js、DESIGN.md。所有人不独占仓库，不撤销他人变更。

### 前轮范围与后继

本轮已按最新产品决定收紧为完整人工创建/配置优先。Agent协助只是后续外部接入说明、复制受限任务摘要和折叠虚构候选review；不提供prompt聊天/生成表单、后台作业或平台内Worker。早期assistant running/fail/cancel状态仅为状态层反例兼容，不是当前UI入口。真实桥接按AGENT-INTEGRATION-PLAN建设，不显示已连接。后端不能把此原型对象直接作为正式合同。

### 视图接口

每个视图导出纯 render 函数，返回 HTML 字符串。参数 ctx={state,agent,ready,readonly}；agent=当前专家；ready=readiness(agent)。所有动态文本用 helpers.escapeHtml。

state={agents,selectedAgentId,connections,runs,cases,proposals,materials:[],ui}。
ui={page,depth:'overview'|'business'|'detailed',section:'service',assistantOpen:false,sidePanel:'preview'|'assistant',createMode:'manual'|'assistant',sourceTab:'FAQ'|'URL'|'File',sourceForm:false,sourceDetail:null,sourceFilter:'all'|'ready'|'pending'|'unavailable',search:'',filter:'all',trialInput:'',trialMessages:[],trialMode:'simulation',trialState:'idle',assistant:{prompt:'',scope:'all',status:'idle',suggestions:[],baseRevision:null,message:''},readonly:false,navOpen:false,toast:null,activeConversation:null,contactPreview:false,deploymentStep:0}。

agent={id,name,revision,config,manualPaths:{},versions:[],bindings:{widget:null,contact:null},checks:{testedRevision:null,approvedRevision:null},conversations:[]}。
config={goal,audience,scope,tone,greeting,fallback,handoff:{phrases:[],recipient,condition,resumeMinutes},sources:[],fields:[],flow:[],skills:[],rules:[],tools:[],outcome:{definition,unknown},model:{connectionId:'simulation',budget:2000},widget:{title,color,language,timezone,hours,formMode,showFaq,bookingUrl,enabled},contact:{title,description,blocks:[],published:false},channels:{telegram:false,email:false}}。
source={id,type:'FAQ'|'URL'|'File',title,question,answer,body,url,status:'received'|'parsed'|'review'|'indexed'|'failed'|'revoked',rights:false,sourceRef,expires,revokeNote,version:1,fictional:false,error:''}。
field={id,label,source:'visitor'|'tool',required:false}; flow step={id,title,instruction}; skill={id,title,description,exit}; rule={id,title,description,scope:'global'|'task',locked:true}; tool={id,title,sideEffect:'read'|'write',mode:'mock',requiresConfirm:true,status:'mock'}。
version={id,revision,config,createdAt,status:'sandbox-approved'|'published',evidence:[],label}；已发布 config 不变。ready={items:[{id,label,status:'ok'|'missing'|'warning',detail,page}],canTrial,canApprove,knowledgeCount,issues:[]}。connections 默认仅 simulation 引用，name/provider/model/status/streaming/tools/cancel 均明确模拟。

### HTML交互协议

button data-action="action-name" data-id="id" / data-page="route" / data-depth="depth" / data-section="module" / data-path="configPath"。
即时字段 data-bind="goal|audience|scope|tone|greeting|fallback|handoff.recipient|..." （不加config前缀），name 可与 path相同，数组输入 data-format="lines" 或 "csv"，number input自动数值。专家名称用 data-agent-name；UI暂存输入 data-ui-bind="trialInput|search|assistant.prompt|assistant.scope"。所有配置控件草稿可编辑、readonly状态禁用；locked rules 不可直接改。
form data-form="create|source|field|flow|skill|tool|connection|trial|inbox|case|proposal"：root event handler读取 FormData提交相应action。创建 fields name/goal/audience/mode；source fields type/title/question/answer/body/url/rights/sourceRef/expires；field id/label/source/required；flow title/instruction；skill title/description/exit；tool title/sideEffect；connection name/provider/model/baseUrl（无key输入）；trial question；inbox message；case title/input/expected/must/forbid；proposal title/reason/path/after。

### actions（root负责真实本地逻辑）

导航：navigate（page）、select-agent（id）、new-agent（mode）、create-mode（mode）、set-depth（depth）、set-section（section）、toggle-assistant、set-side-panel（panel）、toggle-nav、readonly-toggle、dismiss-toast。
助手：assistant-generate（scope/prompt）、assistant-fail、assistant-cancel、assistant-accept（id）、assistant-reject（id）、assistant-clear。建议={id,path,label,before,after,why,origin,risk,blocked,baseRevision,status:'pending'|'accepted'|'rejected'}。只提供确定性模拟建议；发生人工改动后过期建议拒绝采用；manualPaths默认受保护。
知识：source-tab（tab）、source-list、source-form-toggle、source-detail（id）、source-edit（id）、source-stage（id,stage）、source-retry（id）、source-revoke（id）、source-remove（id）、load-demo-sources。URL仅登记演示，不抓取；文本文件可浏览器本地读取；PDF/DOCX/XLSX只登记并显示解析待接入。
配置：field-remove、flow-remove、flow-up、flow-down、skill-remove、tool-remove、rule-propose、recheck、export-config、save-now。
试用：trial-example（kind:'known'|'unknown'|'handoff'）、trial-cancel、trial-clear；trial form提交。所有回答均脚本模拟，实际模型未接。ready.canTrial至少授权索引资料与可用simulation连接；结果留局部源依据，取消时不追加迟到回复。
治理：case-from-run（id）、case-create、case-evaluate、proposal-from-run（id）、proposal-create、proposal-apply（id）、proposal-reject（id）、sandbox-check、sandbox-approve、sandbox-publish（target:'widget'|'contact'）、version-restore（id）、version-preview（id）。所有审批/回放/发布均演示，不假造真实Gate；版本与绑定分开，修改草稿清空当前证据但保留旧绑定。只读禁止配置写入与模拟批准。
应用：inbox-select（id）、inbox-simulate、inbox-handoff、inbox-release；人工回复仅本地；recipient/ownership 与request终态分开。widget-check、widget-copy、contact-add-block（type）、contact-remove-block（id）、contact-move-block（id,direction）、contact-preview、contact-unpublish。
设置：connection-test（id,result:'success'|'failure'）、connection-remove（id）、deployment-next、deployment-back、deployment-retry、deployment-backup、deployment-restore、deployment-upgrade。部署仅模拟步骤，不能生成真实资源或接受云凭据。

### helpers.js exports

escapeHtml(value), attr(value), icon(name,size=18), badge(label,tone='neutral'), button(action,label,{variant='secondary',disabled=false,...data}={}), field(label,bind,value,{type='text',help='',options=[],format='',readonly=false,placeholder='',rows=3}={}), section(title,body,{description='',actions='',className=''}={}), emptyState(title,description,actions=''), formatTime(iso), renderReadiness(ready), pageHeading(title,description,actions='')。视图可自写语义HTML，不依赖未存在的 helpers。

editor.js exports renderAgents,renderCreate,renderOverview,renderConfiguration,renderAssistant。
surfaces.js exports renderKnowledge,renderTrial,renderInbox,renderWidget,renderContact,renderConnections,renderRuns,renderCases,renderIterations,renderVersions,renderDeployment。
shell.js exports routes(数组{id,label,group,icon,scoped,parent?}),renderShell(ctx,body,side='')。Shell侧栏展示四组：配置与资料 / 客服应用 / 运行与验收 / 版本与设置；保留16路由及其scoped对象归属，创建路由隐藏。overview/configuration以parent:'agents'归于专家列表的二级页面，仅选中专家后显示嵌套入口；当前子页高亮，父级标示归属，面包屑可返回列表。二级切换复用set-depth，保留历史快照只读；直接进入配置时深度标签不误选概览。页面上下文用于配置、试用与治理。同一专家版本范围可直接访问概览、业务配置、详细配置（depth），不是新建平行配置库。

样式类建议：app-shell,sidebar,workspace,topbar,page-header,page-content,contextbar,toolbar,section,section-heading,field,control,input,textarea,btn,btn-primary,btn-secondary,btn-ghost,btn-danger,badge,badge-success,badge-warning,badge-danger,badge-neutral,muted,helper,notice,notice-warning,notice-danger,grid-2,split-layout,editor-main,side-panel,panel-tabs,detail-list,table-wrap,data-table,empty-state,stack,inline,summary-list,readiness,chat,chat-message,message-user,message-assistant,source-detail,config-nav,config-layout,config-module,dialog,toast,button-group。纯CSS无外部字体/素材请求。当前视觉世界为白/浅灰、克制蓝主操作、SF系统字体、中高密度后台；默认13/14px正文、22px页标题，桌面36px控件，窄屏44px。

### 最终集成补充

- root新增domain.js（共同校验/就绪/候选/受限任务）、local-files.js（冻结对象/表单与读代次），app.js只负责呈现与事件接线。
- ui.sourceEdit/sourceFileMeta/sourceFileBody、caseEdit/caseForm/proposalForm、runDetail、formDrafts与disclosures负责恢复呈现；这些不成为服务端业务状态。
- source-open/run-open定位依据；source-edit/case-edit修订；case-evaluate有id时行级回放；case/proposal人工编辑共用正式方向的权限和失效语义，本轮只本地模拟。
- proposal.evaluatedSuite为本地固定案例签名，案例或真值改变失效；采用按真实diff路径留证与保护。
- readonly与历史预览均禁写；copy任务采用所见上下文，只含目标/来源元数据，不含全文、凭据或客户会话。
- widgetPreview作为共用外观组件供Widget页与编辑侧栏调用；helper面板可完全收起。

实际验证与未实现范围以[交付报告](../../docs/S2-FRONTEND-ROUND2.md)为准。

### 物料扩展

知识域新增独立 materials 路由；资产原件在 IndexedDB，元数据与 ui.materials 在本地状态，不混入 config.sources。config.materialPolicy 属于同一专家草稿；人工 Inbox 发送支持冻结会话上下文及附件。实际 API/actions/快照字段见 [MATERIALS-CONTRACT](MATERIALS-CONTRACT.md)。

material-domain.js 管理纯状态规则，asset-cache.js 负责 Blob 缓存与 objectURL，material-controller.js 负责上传/预览与发送异步核验，views/materials.js 和 materials.css 负责呈现。后端必须重新设计身份、权限、对象存储、作业、索引、工具幂等和送达回执权威；前端缓存与检查不能替代。

访客扩展由 visitor-domain.js / visitor-controller.js / views/visitor.js / visitor.css 提供。Trial 和 Widget 使用独立本地轮次；Widget 共用预览可传 ctx 开启互动；具体状态/动作与本地观察证据见 [MATERIALS-CONTRACT](MATERIALS-CONTRACT.md#访客入口扩展)。浏览器原件查看不代表真实渠道文件发送或上线版本绑定。


### 知识域工作面扩展

views/knowledge.js 导出 renderKnowledge(ctx)，surfaces.js re-export；library.css提供共用工作面，knowledge.css提供问答与资料布局。sourceForm优先显示编辑，sourceDetail其次显示详情，其余为列表；material form/detail同样互斥。source-list/material-list返回保留筛选；material-list reset=true清空query/kind/status。编辑取消返回当前详情，新建取消返回列表，保存显示新登记详情。

ui.sourceFilter只控制列表展示；可用性继续由sourceValid及授权/撤回/有效期检查决定。data-disclosure-key独立标识折叠对象，data-library-heading用于工作面焦点。data-material-scope-target标记指定专家fieldset；workspace范围隐藏禁用，恢复selected时保留选中值。

原件预览由app记录发起按钮、背景inert和父页面键盘焦点；不改变实际文件校验。物料autoResults为临时检查结果，在重载、切专家、配置或物料/缓存变化后清空，不将旧结果显示为当前专家可检索。字段、版本、文件controller与发送Gate继续按既有合同运行。

### 导航与集合工作面扩展（2026-10-15）

`ui.collections[page] = {query:'',status:'all',detailId:null,form:false}`，page为runs/cases/iterations/connections；对应数据集合为runs/cases/proposals/connections。前三类严格按当前agentId筛选，无归属记录不推断归属；连接为工作区对象。form优先、有效detailId其次、否则列表。切专家清理集合工作面及检索条件。

统一动作：collection-open(page,id)、collection-back(page)、collection-new(page)、collection-edit(page,id，仅案例)、collection-cancel(page)、collection-clear(page)。新建不支持runs；case-create/case-edit/proposal-create/run-open保留兼容。返回列表保留query/status，clear只清筛选；取消编辑返回原详情、新建取消返回列表；成功保存进入相应详情，失败留在表单。`data-ui-bind="collections.<page>.query|status"`仅允许四集合白名单字段。

工作面根节点有data-collection-page/data-collection-mode；标题data-collection-heading及tabindex=-1用于焦点，返回复用library列表滚动与发起行焦点。只读既禁止界面写操作，也在store拒绝提名、回放、候选比较等证据写入；不把前端门禁当作后端权限。

知识source-clear只清search/sourceFilter、不切类型或修改资料；全部资料统计、当前类型数、筛选结果数分别标名。所有标准解答用原生details提供三行摘要与完整展开；不按字符数猜测手机行数。配置空/无效section在进入配置时定位并保存，render不写状态或随缺口变化跳模块。
