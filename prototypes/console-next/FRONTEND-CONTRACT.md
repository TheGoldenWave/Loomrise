# 第二轮前端协作合同 v0.6

状态：2026-10-15，实施规格；仅本地前端演示，不接模型、抓取、工具、渠道或云服务。最初分工保留作历史，当前分工见[本轮实施计划](../../docs/superpowers/plans/2026-10-15-console-ui-optimization.md)。

技术：原生 HTML/CSS + ES modules，零新增运行依赖。root 负责 store.js、fixtures.js、app.js、helpers.js、index.html 与测试/文档；editor worker 仅 views/editor.js；surfaces worker 仅 views/surfaces.js；visual worker 仅 styles.css、views/shell.js、DESIGN.md。所有人不独占仓库，不撤销他人变更。

## 当前范围与后继

本轮已按最新产品决定收紧为完整人工创建/配置优先。Agent协助只是后续外部接入说明、复制受限任务摘要和折叠虚构候选review；不提供prompt聊天/生成表单、后台作业或平台内Worker。早期assistant running/fail/cancel状态仅为状态层反例兼容，不是当前UI入口。真实桥接按AGENT-INTEGRATION-PLAN建设，不显示已连接。后端不能把此原型对象直接作为正式合同。

## 视图接口

每个视图导出纯 render 函数，返回 HTML 字符串。参数 ctx={state,agent,ready,readonly}；agent=当前专家；ready=readiness(agent)。所有动态文本用 helpers.escapeHtml。

state={agents,selectedAgentId,connections,runs,cases,proposals,materials:[],ui}。
ui={page,depth:'overview'|'business'|'detailed',section:'service',assistantOpen:false,sidePanel:'preview'|'assistant',createMode:'manual'|'assistant',sourceTab:'FAQ'|'URL'|'File',sourceForm:false,sourceDetail:null,sourceFilter:'all'|'ready'|'pending'|'unavailable',search:'',filter:'all',trialInput:'',trialMessages:[],trialMode:'simulation',trialState:'idle',assistant:{prompt:'',scope:'all',status:'idle',suggestions:[],baseRevision:null,message:''},readonly:false,navOpen:false,toast:null,activeConversation:null,contactPreview:false,deploymentStep:0}。

agent={id,name,revision,config,manualPaths:{},versions:[],bindings:{widget:null,contact:null},checks:{testedRevision:null,approvedRevision:null},conversations:[]}。
config={goal,audience,scope,tone,greeting,fallback,handoff:{phrases:[],recipient,condition,resumeMinutes},sources:[],fields:[],flow:[],skills:[],rules:[],tools:[],outcome:{definition,unknown},model:{connectionId:'simulation',budget:2000},widget:{title,color,language,timezone,hours,formMode,showFaq,bookingUrl,enabled},contact:{title,description,blocks:[],published:false},channels:{telegram:false,email:false}}。
source={id,type:'FAQ'|'URL'|'File',title,question,answer,body,url,status:'received'|'parsed'|'review'|'indexed'|'failed'|'revoked',rights:false,sourceRef,expires,revokeNote,version:1,fictional:false,error:''}。
field={id,label,source:'visitor'|'tool',required:false}; flow step={id,title,instruction}; skill={id,title,description,exit}; rule={id,title,description,scope:'global'|'task',locked:true}; tool={id,title,sideEffect:'read'|'write',mode:'mock',requiresConfirm:true,status:'mock'}。
version={id,revision,config,createdAt,status:'sandbox-approved'|'published',evidence:[],label}；已发布 config 不变。ready={items:[{id,label,status:'ok'|'missing'|'warning',detail,page}],canTrial,canApprove,knowledgeCount,issues:[]}。connections 默认仅 simulation 引用，name/provider/model/status/streaming/tools/cancel 均明确模拟。

## HTML交互协议

button data-action="action-name" data-id="id" / data-page="route" / data-depth="depth" / data-section="module" / data-path="configPath"。
即时字段 data-bind="goal|audience|scope|tone|greeting|fallback|handoff.recipient|..." （不加config前缀），name 可与 path相同，数组输入 data-format="lines" 或 "csv"，number input自动数值。专家名称用 data-agent-name；UI暂存输入 data-ui-bind="trialInput|search|assistant.prompt|assistant.scope"。所有配置控件草稿可编辑、readonly状态禁用；locked rules 不可直接改。
form data-form="create|source|field|flow|skill|tool|connection|trial|inbox|case|proposal"：root event handler读取 FormData提交相应action。创建 fields name/goal/audience/mode；source fields type/title/question/answer/body/url/rights/sourceRef/expires；field id/label/source/required；flow title/instruction；skill title/description/exit；tool title/sideEffect；connection name/provider/model/baseUrl（无key输入）；trial question；inbox message；case title/input/expected/must/forbid；proposal title/reason/path/after。

## actions（root负责真实本地逻辑）

导航：navigate（page）、select-agent（id）、new-agent（mode）、create-mode（mode）、set-depth（depth）、set-section（section）、toggle-assistant、set-side-panel（panel）、toggle-nav、readonly-toggle、dismiss-toast。
助手：assistant-generate（scope/prompt）、assistant-fail、assistant-cancel、assistant-accept（id）、assistant-reject（id）、assistant-clear。建议={id,path,label,before,after,why,origin,risk,blocked,baseRevision,status:'pending'|'accepted'|'rejected'}。只提供确定性模拟建议；发生人工改动后过期建议拒绝采用；manualPaths默认受保护。
知识：source-tab（tab）、source-list、source-form-toggle、source-detail（id）、source-edit（id）、source-stage（id,stage）、source-retry（id）、source-revoke（id）、source-remove（id）、load-demo-sources。URL仅登记演示，不抓取；文本文件可浏览器本地读取；PDF/DOCX/XLSX只登记并显示解析待接入。
配置：field-remove、flow-remove、flow-up、flow-down、skill-remove、tool-remove、rule-propose、recheck、export-config、save-now。
试用：trial-example（kind:'known'|'unknown'|'handoff'）、trial-cancel、trial-clear；trial form提交。所有回答均脚本模拟，实际模型未接。ready.canTrial至少授权索引资料与可用simulation连接；结果留局部源依据，取消时不追加迟到回复。
治理：case-from-run（id）、case-create、case-evaluate、proposal-from-run（id）、proposal-create、proposal-apply（id）、proposal-reject（id）、sandbox-check、sandbox-approve、sandbox-publish（target:'widget'|'contact'）、version-restore（id）、version-preview（id）。所有审批/回放/发布均演示，不假造真实Gate；版本与绑定分开，修改草稿清空当前证据但保留旧绑定。只读禁止配置写入与模拟批准。
应用：inbox-select（id）、inbox-simulate、inbox-handoff、inbox-release；人工回复仅本地；recipient/ownership 与request终态分开。widget-check、widget-copy、contact-add-block（type）、contact-remove-block（id）、contact-move-block（id,direction）、contact-preview、contact-unpublish。
设置：connection-test（id,result:'success'|'failure'）、connection-remove（id）、deployment-next、deployment-back、deployment-retry、deployment-backup、deployment-restore、deployment-upgrade。部署仅模拟步骤，不能生成真实资源或接受云凭据。

## helpers.js exports

escapeHtml(value), attr(value), icon(name,size=18), badge(label,tone='neutral'), button(action,label,{variant='secondary',disabled=false,...data}={}), field(label,bind,value,{type='text',help='',options=[],format='',readonly=false,placeholder='',rows=3}={}), section(title,body,{description='',actions='',className=''}={}), emptyState(title,description,actions=''), formatTime(iso), renderReadiness(ready), pageHeading(title,description,actions='')。视图可自写语义HTML，不依赖未存在的 helpers。

editor.js exports renderAgents,renderCreate,renderOverview,renderConfiguration,renderAssistant。
surfaces.js exports renderKnowledge,renderTrial,renderInbox,renderWidget,renderContact,renderConnections,renderRuns,renderCases,renderIterations,renderVersions,renderDeployment。
shell.js exports routes(数组{id,label,group,icon,scoped,parent?}),renderShell(ctx,body,side='')。Shell侧栏展示四组：配置与资料 / 客服应用 / 运行与验收 / 版本与设置；保留16路由及其scoped对象归属，创建路由隐藏。overview/configuration以parent:'agents'归于专家列表的二级页面，仅选中专家后显示嵌套入口；当前子页高亮，父级标示归属，面包屑可返回列表。二级切换复用set-depth，保留历史快照只读；直接进入配置时深度标签不误选概览。页面上下文用于配置、试用与治理。同一专家版本范围可直接访问概览、业务配置、详细配置（depth），不是新建平行配置库。

样式类建议：app-shell,sidebar,workspace,topbar,page-header,page-content,contextbar,toolbar,section,section-heading,field,control,input,textarea,btn,btn-primary,btn-secondary,btn-ghost,btn-danger,badge,badge-success,badge-warning,badge-danger,badge-neutral,muted,helper,notice,notice-warning,notice-danger,grid-2,split-layout,editor-main,side-panel,panel-tabs,detail-list,table-wrap,data-table,empty-state,stack,inline,summary-list,readiness,chat,chat-message,message-user,message-assistant,source-detail,config-nav,config-layout,config-module,dialog,toast,button-group。纯CSS无外部字体/素材请求。当前视觉世界为白/浅灰、克制蓝主操作、SF系统字体、中高密度后台；默认13/14px正文、22px页标题，桌面36px控件，窄屏44px。

## 最终集成补充

- root新增domain.js（共同校验/就绪/候选/受限任务）、local-files.js（冻结对象/表单与读代次），app.js只负责呈现与事件接线。
- ui.sourceEdit/sourceFileMeta/sourceFileBody、caseEdit/caseForm/proposalForm、runDetail、formDrafts与disclosures负责恢复呈现；这些不成为服务端业务状态。
- source-open/run-open定位依据；source-edit/case-edit修订；case-evaluate有id时行级回放；case/proposal人工编辑共用正式方向的权限和失效语义，本轮只本地模拟。
- proposal.evaluatedSuite为本地固定案例签名，案例或真值改变失效；采用按真实diff路径留证与保护。
- readonly与历史预览均禁写；copy任务采用所见上下文，只含目标/来源元数据，不含全文、凭据或客户会话。
- widgetPreview作为共用外观组件供Widget页与编辑侧栏调用；helper面板可完全收起。

实际验证与未实现范围以[交付报告](../../docs/S2-FRONTEND-ROUND2.md)为准。

## 物料扩展

知识域新增独立 materials 路由；资产原件在 IndexedDB，元数据与 ui.materials 在本地状态，不混入 config.sources。config.materialPolicy 属于同一专家草稿；人工 Inbox 发送支持冻结会话上下文及附件。实际 API/actions/快照字段见 [MATERIALS-CONTRACT](MATERIALS-CONTRACT.md)。

material-domain.js 管理纯状态规则，asset-cache.js 负责 Blob 缓存与 objectURL，material-controller.js 负责上传/预览与发送异步核验，views/materials.js 和 materials.css 负责呈现。后端必须重新设计身份、权限、对象存储、作业、索引、工具幂等和送达回执权威；前端缓存与检查不能替代。

访客扩展由 visitor-domain.js / visitor-controller.js / views/visitor.js / visitor.css 提供。Trial 和 Widget 使用独立本地轮次；Widget 共用预览可传 ctx 开启互动；具体状态/动作与本地观察证据见 [MATERIALS-CONTRACT](MATERIALS-CONTRACT.md#访客入口扩展)。浏览器原件查看不代表真实渠道文件发送或上线版本绑定。


## 知识域工作面扩展

views/knowledge.js 导出 renderKnowledge(ctx)，surfaces.js re-export；library.css提供共用工作面，knowledge.css提供问答与资料布局。sourceForm优先显示编辑，sourceDetail其次显示详情，其余为列表；material form/detail同样互斥。source-list/material-list返回保留筛选；material-list reset=true清空query/kind/status。编辑取消返回当前详情，新建取消返回列表，保存显示新登记详情。

ui.sourceFilter只控制列表展示；可用性继续由sourceValid及授权/撤回/有效期检查决定。data-disclosure-key独立标识折叠对象，data-library-heading用于工作面焦点。data-material-scope-target标记指定专家fieldset；workspace范围隐藏禁用，恢复selected时保留选中值。

原件预览由app记录发起按钮、背景inert和父页面键盘焦点；不改变实际文件校验。物料autoResults为临时检查结果，在重载、切专家、配置或物料/缓存变化后清空，不将旧结果显示为当前专家可检索。字段、版本、文件controller与发送Gate继续按既有合同运行。

## 导航与集合工作面扩展（2026-10-15）

`ui.collections[page] = {query:'',status:'all',detailId:null,form:false}`，page为runs/cases/iterations/connections；对应数据集合为runs/cases/proposals/connections。前三类严格按当前agentId筛选，无归属记录不推断归属；连接为工作区对象。form优先、有效detailId其次、否则列表。切专家清理集合工作面及检索条件。

统一动作：collection-open(page,id)、collection-back(page)、collection-new(page)、collection-edit(page,id，仅案例)、collection-cancel(page)、collection-clear(page)。新建不支持runs；case-create/case-edit/proposal-create/run-open保留兼容。返回列表保留query/status，clear只清筛选；取消编辑返回原详情、新建取消返回列表；成功保存进入相应详情，失败留在表单。`data-ui-bind="collections.<page>.query|status"`仅允许四集合白名单字段。

工作面根节点有data-collection-page/data-collection-mode；标题data-collection-heading及tabindex=-1用于焦点，返回复用library列表滚动与发起行焦点。只读既禁止界面写操作，也在store拒绝提名、回放、候选比较等证据写入；不把前端门禁当作后端权限。

知识source-clear只清search/sourceFilter、不切类型或修改资料；全部资料统计、当前类型数、筛选结果数分别标名。所有标准解答用原生details提供三行摘要与完整展开；不按字符数猜测手机行数。配置空/无效section在进入配置时定位并保存，render不写状态或随缺口变化跳模块。
