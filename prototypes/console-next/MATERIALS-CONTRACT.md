# 物料库与文件发送前端合同 v0.4

日期2026-10-14。状态：本地前端已实现并验证；图片/视频/文档原件实际本地Blob缓存和预览，压缩/内容理解仅明确模拟，不发外部消息。用户本轮要求也设计Agent自动发物料，不做平台AgentWorker。

## 模块责任

material-domain.js 管纯状态与发送规则；asset-cache.js 管 IndexedDB Blob/objectURL；material-controller.js 管上传、预览、缓存核验和异步上下文。store.js 负责持久化与恢复，app.js 接事件与视图；views/materials.js、materials.css 及 Inbox/导航提供呈现。这些是前端协作投影，不能直接作为后端权限/API合同。

## state与记录

state.materials=[] 独立工作区库，不混入agent.config.sources；旧schema1补缺省，不丢旧数据。
asset={id,revision,title,kind:'image'|'video'|'document',filename,mimeType,sourceRef,rights:false,expires,tags:[],usage:'',scope:'selected'|'workspace',agentIds:[],canSend:true,autoSendAllowed:false,status:'draft'|'published'|'revoked',original:{blobKey,size,available:true},summary:{text:'',candidate:'',reviewed:false,origin:'manual'|'simulation',baseRevision,candidateBaseRevision},processing:{compression:'none'|'mock-ready'|'failed',understanding:'none'|'candidate'|'failed'},variants:[{id:'original'|'compressed-demo',label,blobKey,size,available,simulated}],history:[],fictional:false}。

当前压缩候选可记录compressed-demo variant simulated=true、blobKey=null、size=null（未真实重编码，不能下载为压缩文件）；选择它发送只记录明确模拟附件。原件variant实际Blob存在才能本地预览/下载。不能报告虚假压缩率或视频理解结果。简介候选仅演示元数据建议，人工可直接填写真实简介，并审阅。

ui.materials={query:'',kind:'all',status:'all',form:false,editingId:null,detailId:null,session:0,upload:null,uploadStatus:'idle',error:'',picker:false,pickerQuery:'',selected:[],sendContext:null,autoQuery:'',autoExplicit:true,autoResults:[],preview:null}。upload仅元数据{blobKey,filename,mimeType,size,kind,available}，File/Blob在IndexedDB，绝不放localStorage。

agent.config.materialPolicy={enabled:false,requireExplicitRequest:true,preferredVariant:'original',allowOriginalFallback:true,maxCount:1}（本地演示上限1–5）；配置层追加data-bind白名单与旧状态缺省，改策略进同一草稿。自动发送是当前草稿隔离模拟，正式线上须冻结批准版与ToolPolicy；UI须明确。

## 纯domain API

export ensureMaterialState(state); materialKind(filename,mimeType); materialAllowed(asset,agentId,today?); materialSearch(state,query,{agentId,forAgent=false}={}); materialSendCheck(state,{agentId,conversationId,generation,attachments,actor:'human'|'agent',explicitRequest,expectedRevision?}); handleMaterialAction(state,action,data,{agent,readonly,uid,now,changed})。

handle返回{handled:true,value?}；未匹配返回{handled:false}；错误throw Error root负责toast/save/notify。请勿直接读取Blob/DOM。
materialSearch只对Agent返回published/有效授权/范围匹配/已审简介；人工可看到草稿并搜索title/filename/tags/summary/usage，撤回不得Agent召回。

## actions/forms

material-form-toggle（新建/关闭，重置editing/upload/session）；material-edit(id)；material-detail(id)；material-list(reset?:true)；material-filter(path:'query'|'kind'|'status'|'pickerQuery'|'autoQuery',value)；material-upload-ready(meta,session)；material-upload-failed(error,session)；material-upsert(form fields id/title/description/tags/usage/sourceRef/rights/expires/scope/autoSendAllowed/canSend)；material-review-summary(id)；material-publish(id)；material-revoke(id)；material-summary-demo(id)；material-summary-fail(id)；material-apply-summary(id，候选基准必须仍匹配当前修订)；material-compress-demo(id)；material-compress-fail(id)；material-picker-open（冻结选中agentId+conversationId+generation，picker=true，selected=[]）；material-picker-close（取消并清选择）；material-picker-done（完成选择、保留冻结引用供发送）；material-pick(id,variant:'original'|'compressed-demo')；material-unpick(id,variant)；material-send(agentId,conversationId,generation,message,attachments?,actor:'human')；material-auto-retrieve(query)；material-auto-send(query,explicitRequest:true/false,agentId,conversationId,generation,expectedRevision?)；material-preview(id,variant,blobKey?)；material-preview-close（controller处理cache展示）；material-file-availability(id,available，写入前冻结修订/原件引用再核验)；material-load-demo（3条无实际原件metadata示例，不能自动发）。

form data-form=material-upsert（原件当前限大于0且不超过50MB，仅为浏览器演示边界；title可用上传文件名默认；description人工简介；sourceRef/rights/expires显式确认；scope=selected|workspace默认selected；tags逗号分隔；usage适用说明），file input data-material-file，name=file，accept图片/视频/文档常见扩展（SVG/HTML可不支持）。处理队列允许图片/视频压缩与理解简介状态演示，不能假造真实产生文件。

form data-form=material-auto-send query+explicitRequest checkbox，hidden agentId/conversationId/generation/revision，旁有material-auto-retrieve。策略field helpers绑定materialPolicy.*（root支持）。Agent自动发必须enabled + asset.autoSendAllowed + 已发布已审简介 + 有效权限/范围 + 当前AI占用 + 对请求/数量/版本再次校验；人工接管阻断，不被通知回执等替代。人发必须当前人工占用，允许纯附件消息。

material-send form来自Inbox原data-form=inbox（root可转换），hidden agentId/conversationId/generation，按钮选择物料打开picker；selected存{id,revision,variant}。domain发送重新核验后将attachments快照加入本地messages；status='local-recorded', delivery='unknown'、actor、人/Agent及generation；不称送达/解决。发送失败保留输入与选择，成功清当前scope选择。历史快照不随物料改名/变更更新；空MIME/文件名也不借用当前资产新版元数据。Agent消息另冻结requestEvidence={query,explicitRequest,origin:operator-simulated-request}与materialPolicy，明确不是实际访客输入或线上批准策略。

## views与样式

views/materials.js导出renderMaterials(ctx)、renderMaterialPicker(ctx)、renderMaterialAttachments(attachments)、renderMaterialPreview(ctx)；helpers.js已有escapeHtml/attr/button/field/section/badge/pageHeading/icon等，动态文本必转义。

新增route{id:'materials',label:'物料库',group:'知识',icon:'book',scoped:false}。Knowledge页加去物料库入口，解释知识File解析与可发送物料不同。Inbox集成picker/选中附件/attachment cards/media预览按钮，旧文本/引用呈现保持。global library位于知识域（原层六层不增加），显示可用专家范围。

素材预览可用<img>/<video controls>/<iframe仅PDF>或文档下载；root hydrate提供objectURL：元素data-material-blob=blobKey、data-material-kind；不渲染HTML/SVG脚本，普通Office只文件名/下载。消息附件冻结snapshot可用preview button data-blob-key，撤回只阻断新发送不会重写历史。root处理异步缓存/readonly/渲染代次。

CSS放materials.css并复用library.css，沿用现有灰白/蓝后台。列表、详情、编辑互斥；内容与当前可用性优先，类型/发布状态/标签筛选，完整授权/派生/处理/历史按需展开，轻量picker和手机内容行保留。选择器按Inbox上下文显示，无权限原因明示。

## 验收

独立库与知识sourceValid互不影响；旧schema1/文本消息恢复；原件跨刷新预览；未审简介不供Agent；压缩失败不丢原件；撤回/过期/范围/旧revision选择后重验；人工占用/readonly/旧generation阻断人或Agent发送；Agent策略默认off、真实送达unknown；历史附件冻结；异步读取离开/换素材/二次选择失效；无真实外部调用。

验证：全套57/57状态与控制器测试、9/9物料浏览器任务及旧主流程/反例通过；16路由两视窗布局检查通过。复现实例和后端未实现范围见[交付报告](../../docs/S2-FRONTEND-ROUND2.md#7-物料库与-agent-自动发送扩展)。

## 访客入口扩展

visitor-domain.js 复用 materialAssetSendCheck(state,{agentId,attachments,actor,explicitRequest,expectedRevision,date}) 与 materialPreferredVariant(asset,policy)，独立管理 trial/widget 轮次；materialSendCheck 的 Inbox 上下文/占用检查仍独立生效。

visitorSession(state,surface) 返回只读快照 {input,messages,status,pending,generation,agentId,ownership}。trial 继续用 ui.trialInput/trialMessages/trialState/pendingTrial，Widget 用 ui.widgetTrialInput/widgetTrialMessages/widgetTrialState/pendingWidgetTrial；两者 generation/agentId/ownership 分别管理，不复制消息权威。

actions 为 trial-start/complete/cancel/clear/example/stage 与 widget-trial-*；example 可带具体 question。pending 冻结 id/surface/page/agentId/revision/config/generation/question/intent/attachments/fileRefs/trace；fileRefs={id,revision,blobKey,size,filename}。complete 的 availableFiles={blobKey,size,filename} 来自实际缓存读取，domain 完成前重新校验，不从元数据或模型说法推断有文件。旧 pending 缺新字段时只能安全取消，不能继续发送。

消息另存 localReceipt={status:pending|received,scope:local-preview,time}、attachmentInteractions={'id:revision:variant':{openedAt?,downloadStartedAt?}}。visitor-received/opened/downloaded 只改变本地观察记录，附件资产快照不变；Run 同步这些观察。requestEvidence.origin=local-visitor-input，区别于 Inbox 操作员模拟索取；materialPolicy 与 materialEvidence/trace 固定在当轮。

views/visitor.js 渲染共用访客对话、附件和折叠证据；visitor-controller.js 接 trial/widget-trial 表单（question/widgetQuestion）与 visitor-attachment-preview/download，参数 surface/messageId/id/revision/variant（Run 历史可带 runId）。控制器不冒充 Inbox，不通过物料测试设置知识 testedRevision。

material-controller.preview(data,{guard}) 返回执行是否成功，click 仍只返回已处理事件；实际下载前后检查上下文，成功后才登记发起下载。原件正文预览用 data-material-text，最多256KB且明示范围；PDF只在 MIME/文件头预检后交给浏览器原生查看器，保留下载入口。浏览器原生PDF不得用统一 iframe sandbox 阻断，依据 [MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#embedding_pdfs)；其他网页/SVG仍不嵌入。

验证见[本轮报告](../../docs/S2-FRONTEND-ROUND2.md#8-访客物料试用与-widget-预览扩展)：86项状态/控制器测试、10项访客浏览器任务及既有回归。未验证正式权限、网络回执或真实AI。


## 工作区交互扩展（2026-10-14）

material-list返回列表不清筛选，reset=true同时清query/kind/status；material-edit打开同一对象的编辑面，取消回详情；新录入取消回列表。三个工作面互斥且保存后进入详情。source与物料两个库仍分开，不改变审阅、发布、授权或发送校验合同。

指定专家fieldset用data-material-scope-target；scope=workspace时隐藏禁用，切回selected恢复选中值。标签、用途、发送细项和版本偏好下探。专家自动发送策略只在库列表作为默认收起的独立区域；autoResults属于临时检查结果，重载、切专家、配置/物料/缓存变化均清空。

app.js保存发起预览的data-selector，打开时背景inert、父页面Tab焦点循环，关闭后返回原件/访客附件按钮；实际文件读取与guard语义不变。最新92项Node、新9项工作区浏览器任务与原9项物料/10项访客回归见[本轮报告第10节](../../docs/S2-FRONTEND-ROUND2.md#10-知识资料与物料库工作区优化)。上方57/86项是对应扩展的历史验证范围。
