# 访客物料试用与 Widget 预览实施计划

日期：2026-10-14。状态：本轮纯前端扩展已实现并验证；正式服务未实现。产品与权限边界沿用[物料专题](../../MATERIAL-LIBRARY-AND-DELIVERY.md)。

> Agent 实施采用分文件并行与独立审查；保留当前工作区其他改动，不暂存或提交无关内容。

**目标：** 在客服试用台与 Widget 预览中，以访客身份输入索取请求，体验检索、策略校验、附件收件、图片查看、视频播放和文档预览/下载。

**架构：** 复用物料资产/策略纯校验和真实浏览器缓存；试用台与 Widget 分别持有本地访客会话，不占用 Inbox。冻结草稿、会话代次和物料版本，异步读取后再次重验；保留 FAQ 与 Run → 案例链。文件简介只定位资产，不进入知识答疑事实。

**技术：** 原生 ES modules、CSS、IndexedDB、Node 行为测试、Playwright 本地 UI 验证；不新增运行依赖。

## 1. 状态与协议

- `visitor-domain.js` 统一试用与 Widget 的状态规则。`visitorSession(state, surface)` 返回 `{input,messages,status,pending,generation,agentId,ownership}`。trial 保留 `ui.trialInput/trialMessages/trialState/pendingTrial`，Widget 用对应 `ui.widgetTrial*` 字段；不复制两份会话状态。
- actions：原 `trial-start/complete/cancel/clear/example` 和对应 `widget-trial-*`；附加 `visitor-received/opened/downloaded`，包含 surface、messageId 和冻结附件引用。domain 返回 `{handled,value?}`，开始返回 pending ID。
- pending 记录 `{id,surface,page,agentId,revision,config,generation,question,intent,attachments,trace}`；物料索取采用明确的确定性请求/类型/关键词匹配，不宣称真实模型或语义搜索。否定发送、普通咨询、人工请求不得被文件名碰巧匹配触发发送。
- complete 传 `{id,availableFiles:[{blobKey,size,filename}]}`。控制器实际读取 Blob 并校验冻结引用；domain 重验当前草稿、代次、物料权限/修订/策略后原子追加回复和附件。FAQ 继续使用现有脚本与来源版本。
- 附件沿用冻结快照，收件用独立 `localReceipt`，打开/下载动作用独立 `attachmentInteractions`；外部 `delivery` 和业务解决仍 unknown。收到模拟压缩卡片不等于收到真实压缩文件。
- 物料请求可独立试用，不强制先加 FAQ；不能借此通过知识批准或发布 Gate。自动发送默认关闭，界面提供指向物料库的准备入口。

## 2. 分工与任务

- [x] 领域：提取 material-domain.js 的资产/策略/快照校验，新增 visitor-domain.js；覆盖自然索取、权限、否定/人工、取消/旧回调、独立会话、FAQ 和 Run 的行为测试。
- [x] 视图：新增 views/visitor.js 与 visitor.css；替换试用台呈现并接入 Widget 共用预览。输入、发送、取消、重开、物料快捷索取、访客附件与可折叠检索证据均可操作。
- [x] 集成：store.js 委托 visitor actions 并恢复/取消运行状态；新增 visitor-controller.js 实际缓存检查、回执/打开动作；app.js 接表单、按钮、渲染与导航失效。共用原件预览，不把 objectURL 放进状态。
- [x] 浏览器：图片/视频/文档访客收件与真实预览/下载；无权限/无文件/撤回拒发；缓存读取期间取消/换专家/修改阻断；试用/Widget互不串线，Inbox不变；桌面与390px检查。
- [x] 独立审查：复核授权、异步冻结、历史快照与本地证据语义，修正有证据问题。
- [x] 文档：更新物料专题、前端合同与交付报告、总索引；如涉及产品定位或服务 Gate 才修改对应权威文档。

## 3. 验证和完成条件

状态/控制器测试：`rtk proxy node --test prototypes/console-next/tests/*.test.js`。UI 验证通过本地 `http://127.0.0.1:8788/console-next/` 的 Playwright 脚本；新测试只用原创虚构文件和独立测试浏览器数据。

旧 FAQ/知识摄入、取消、案例与候选、Inbox 附件流程必须保持；新附件实际读出原件，缓存缺失时不假造收件。真实 AI、后处理、语义检索、消息网络回执与服务端权限仍未实现。

结束前检查本地链接/状态标签、`rtk git diff --check`、`rtk git check-ignore -v private/ .playwright-mcp/` 和暂存区。

## 4. 完成与接力

2026-10-14：领域、共用访客视图、实际缓存/预览/下载控制器及store/app已集成。全套86项Node测试通过；访客浏览器10项、旧主流程11项、反例5项、旧物料9项回归通过；16路由两视窗32项布局无页面溢出或page error。独立审查三项重要问题已复现、修复并回归关闭。额外修正PDF内嵌被sandbox阻断、纯文本正文查看与聊天阅读位置；PDF页面有真实渲染证据。

新增测试文件为tests/visitor.test.js、tests/visitor-controller.test.js、tests/visitor-browser-check.js（均在prototypes/console-next目录）；完整证据与后端局限见[报告第8节](../../S2-FRONTEND-ROUND2.md#8-访客物料试用与-widget-预览扩展)。没有暂存/提交；S1和后端Gate不变。下一步由用户在页面评审默认值、卡片与操作顺序，后端按物料专题验收真实解析/存储/索引、权限与渠道回执。
