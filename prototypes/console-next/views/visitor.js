import { escapeHtml, attr, badge, button, emptyState, formatTime } from '../helpers.js';
import { materialAllowed } from '../material-domain.js';
import { visitorSession } from '../visitor-domain.js';

const e = escapeHtml;
const a = attr;
const list = value => Array.isArray(value) ? value : [];
const stages = { request: '识别本次请求', retrieval: '检索已审物料', policy: '检查发送策略', files: '读取本地原件', send: '生成附件消息' };
const kindNames = { image: '图片', video: '视频', document: '文档' };
const sizeLabel = size => !Number.isFinite(Number(size)) || size == null ? '' : Number(size) < 1024 ? Number(size) + ' B' : Number(size) < 1048576 ? (Number(size) / 1024).toFixed(1) + ' KB' : (Number(size) / 1048576).toFixed(1) + ' MB';
const interactionKey = item => [item.id, item.revision, item.variant || 'original'].join(':');
const receiptStatus = message => message.localReceipt?.status || message.localReceipt?.state || 'pending';

function attachmentAction(action, label, item, message, surface, options = {}) {
  return '<button type="button" class="btn btn-secondary" data-action="' + a(action) + '" data-surface="' + a(surface) + '" data-message-id="' + a(message.id || '') + '" data-run-id="' + a(options.runId || '') + '" data-id="' + a(item.id || '') + '" data-revision="' + a(item.revision || 1) + '" data-variant="' + a(item.variant || 'original') + '"' + (options.disabled ? ' disabled' : '') + '>' + e(label) + '</button>';
}

export function renderVisitorAttachments(message, surface = 'trial', options = {}) {
  if (!list(message.attachments).length) return '';
  return '<div class="visitor-attachments" aria-label="客服发来的文件">' + message.attachments.map(item => {
    const available = !item.simulated && Boolean(item.blobKey);
    const interaction = message.attachmentInteractions?.[interactionKey(item)] || {};
    const opened = Boolean(interaction.openedAt);
    const downloaded = Boolean(interaction.downloadedAt || interaction.downloadStartedAt);
    const title = item.title || item.name || item.filename || '附件';
    const mime = item.mimeType || '';
    const extension = String(item.filename || '').split('.').at(-1).toUpperCase();
    const safeImage = available && item.kind === 'image' && ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif'].includes(mime);
    const safeVideo = available && item.kind === 'video' && ['video/mp4', 'video/webm', 'video/quicktime'].includes(mime);
    const pdf = mime === 'application/pdf';
    const textDocument = ['text/plain', 'text/markdown', 'text/csv'].includes(mime) || /\.(txt|md|csv)$/i.test(item.filename || '');
    const media = safeImage ? '<div class="visitor-attachment-media"><img alt="' + a(title) + '" loading="lazy" data-material-blob="' + a(item.blobKey) + '" data-material-kind="image"></div>' : safeVideo ? '<div class="visitor-attachment-media"><video controls preload="metadata" aria-label="' + a(title) + '" data-material-blob="' + a(item.blobKey) + '" data-material-kind="video">此浏览器无法播放视频，可下载后查看。</video></div>' : '';
    const previewLabel = item.kind === 'image' ? '查看大图' : item.kind === 'video' ? '播放视频' : pdf || textDocument ? '预览文档' : '查看打开方式';
    const downloadLabel = item.kind === 'document' ? '下载文档' : '下载原件';
    const metadata = [kindNames[item.kind] || '文件', extension && extension !== item.filename ? extension : '', sizeLabel(item.size)].filter(Boolean).join(' · ');
    const receipt = item.simulated ? '已显示模拟卡片' : receiptStatus(message) === 'received' ? '本地预览已收件' : '等待本地预览收件';
    return '<article class="visitor-attachment" data-visitor-attachment="' + a(interactionKey(item)) + '">' + media + '<div class="visitor-attachment-body"><strong>' + e(title) + '</strong><p class="helper visitor-file-name">' + e(item.filename || '文件名未登记') + '</p><p class="helper">' + e(metadata) + '</p>' + (item.simulated ? '<p class="notice notice-warning">此压缩版本仅为模拟，没有可查看或下载的文件。</p>' : '') + '<div class="button-group">' + attachmentAction('visitor-attachment-preview', previewLabel, item, message, surface, { disabled: !available, ...options }) + attachmentAction('visitor-attachment-download', downloadLabel, item, message, surface, { disabled: !available, ...options }) + '</div><p class="visitor-attachment-state" aria-live="polite">' + e([receipt, opened ? '已打开' : '', downloaded ? '已发起下载' : ''].filter(Boolean).join(' · ')) + '</p></div></article>';
  }).join('') + '</div>';
}

function messageSources(sources) {
  return list(sources).length ? '<div class="message-sources"><span class="muted">依据资料</span> ' + sources.map(source => '<span class="inline">' + badge((source.title || source.id || '资料') + ' · v' + (source.version || 1)) + button('source-open', '查看来源', { id: source.id || '', disabled: !source.id, variant: 'ghost' }) + '</span>').join(' ') + '</div>' : '';
}

function renderMessage(message, surface) {
  const visitor = ['user', 'visitor'].includes(message.role || message.sender);
  const system = message.role === 'system';
  const label = visitor ? '你' : system ? '会话提示' : '客服';
  const text = message.text ?? message.content ?? '';
  return '<article class="chat-message ' + (visitor ? 'message-user' : system ? 'message-system' : 'message-assistant') + '" data-visitor-message="' + a(message.id || '') + '" data-surface="' + a(surface) + '"><div class="message-meta"><strong>' + label + '</strong>' + (message.time || message.createdAt ? '<time>' + e(formatTime(message.time || message.createdAt)) + '</time>' : '') + '</div>' + (text ? '<p>' + e(text) + '</p>' : '') + messageSources(message.sources) + renderVisitorAttachments(message, surface) + (message.status === 'cancelled' ? badge('已取消') : '') + '</article>';
}

function quickRequests(ctx, surface, busy) {
  const assets = list(ctx.state.materials).filter(asset => materialAllowed(asset, ctx.agent.id) && asset.autoSendAllowed === true && asset.original?.available === true && Boolean(asset.original.blobKey)).slice(0, 3);
  if (!assets.length) return '';
  return '<div class="visitor-quick-requests"><span class="helper">试着索取文件</span><div class="button-group">' + assets.map(asset => button(surface === 'widget' ? 'widget-trial-example' : 'trial-example', asset.title || asset.filename, { question: '请发' + (asset.title || asset.filename) + '给我', disabled: busy || ctx.readonly, className: 'visitor-quick-request' })).join('') + '</div></div>';
}

export function renderVisitorConversation(ctx, { surface = 'trial', compact = false } = {}) {
  if (!ctx.agent) return emptyState('先选择一位专家', '访客试用使用当前专家的草稿。');
  const session = visitorSession(ctx.state, surface);
  const busy = session.status === 'running' || Boolean(session.pending);
  const messages = list(session.messages);
  const widget = surface === 'widget';
  const prefix = widget ? 'widget-trial' : 'trial';
  const name = widget ? 'widgetQuestion' : 'question';
  const uiBind = widget ? 'widgetTrialInput' : 'trialInput';
  const inputId = 'visitor-' + surface + '-question';
  const emptyText = widget ? '向客服提问，也可以直接索取图片、视频或文档。' : '输入业务问题，或用“请发课程海报给我”索取一份物料。';
  const busyText = session.pending?.intent?.type === 'material' || session.pending?.attachments?.length ? '正在检索物料并检查文件…' : '正在处理你的问题…';
  const examples = compact ? '' : '<div class="button-group visitor-examples">' + button(prefix + '-example', '资料内问题', { kind: 'known', disabled: busy || ctx.readonly }) + button(prefix + '-example', '资料外问题', { kind: 'unknown', disabled: busy || ctx.readonly }) + button(prefix + '-example', '请求人工', { kind: 'handoff', disabled: busy || ctx.readonly }) + '</div>';
  return '<div class="visitor-conversation' + (compact ? ' visitor-conversation-compact' : '') + '" data-visitor-surface="' + a(surface) + '" data-agent-id="' + a(ctx.agent.id) + '">' + examples + '<div class="chat visitor-chat" role="log" aria-live="polite" aria-label="' + (widget ? '网站客服窗访客预览对话' : '访客试用对话') + '">' + (messages.length ? messages.map(message => renderMessage(message, surface)).join('') : emptyState('开始一次访客咨询', emptyText)) + (busy ? '<article class="chat-message message-assistant" aria-busy="true"><strong>' + e(busyText) + '</strong><p class="helper">可以取消本轮。</p></article>' : '') + '</div>' + (session.status === 'cancelled' ? '<p class="helper" role="status">本轮已取消，不会追加后续答复或文件。</p>' : session.status === 'failed' ? '<p class="notice notice-danger" role="status">本轮未能完成。请重试，或展开试用证据检查原因。</p>' : '') + quickRequests(ctx, surface, busy) + '<form data-form="' + prefix + '" class="visitor-compose stack"><input type="hidden" name="agentId" value="' + a(ctx.agent.id) + '"><input type="hidden" name="generation" value="' + a(session.generation) + '"><div class="field"><label for="' + inputId + '">' + (widget ? '发给客服' : '以访客身份发消息') + '</label><textarea id="' + inputId + '" name="' + name + '" class="control textarea" rows="2" required data-ui-bind="' + uiBind + '" placeholder="提问，或告诉客服你需要哪个文件"' + (busy || ctx.readonly ? ' disabled' : '') + '>' + e(session.input || '') + '</textarea></div><div class="visitor-compose-actions button-group"><button class="btn btn-primary" type="submit"' + (busy || ctx.readonly ? ' disabled' : '') + '>' + (busy ? '处理中…' : widget ? '发送消息' : '发送测试问题') + '</button>' + (busy ? button(prefix + '-cancel', '取消本轮', { variant: 'danger' }) : '') + button(prefix + '-clear', session.ownership === 'waiting' || session.ownership === 'human' ? '开始新对话' : '清空对话', { disabled: busy || !messages.length, title: '清空当前本地访客会话，运行证据仍保留' }) + '</div></form></div>';
}

function renderTrace(trace) {
  return list(trace).length ? '<ol class="visitor-trace">' + trace.map((entry, index) => {
    const item = typeof entry === 'string' ? { detail: entry } : entry || {};
    const status = item.status || 'complete';
    const label = item.label || stages[item.stage || item.step] || '步骤 ' + (index + 1);
    const detail = item.detail || item.text || item.message || '';
    return '<li><div class="inline"><strong>' + e(label) + '</strong>' + badge(status === 'blocked' || status === 'failed' ? '未通过' : status === 'pending' ? '进行中' : '已记录', status === 'blocked' || status === 'failed' ? 'warning' : 'neutral') + '</div>' + (detail ? '<p class="helper">' + e(detail) + '</p>' : '') + '</li>';
  }).join('') + '</ol>' : '<p class="helper">发送一条消息后，这里会显示本轮请求识别、物料匹配和发送检查。</p>';
}

export function renderVisitorEvidence(ctx, surface = 'trial') {
  const session = visitorSession(ctx.state, surface);
  const latest = [...list(session.messages)].reverse().find(message => list(message.trace).length || message.materialEvidence);
  const trace = session.pending?.trace || latest?.materialEvidence?.trace || latest?.trace || [];
  const attachments = session.pending ? [] : list(latest?.attachments);
  return '<details class="visitor-evidence"><summary>查看' + (surface === 'widget' ? '网站客服窗' : '') + '试用证据</summary><p class="helper">本轮使用确定性脚本匹配名称、标签和已审简介。物料简介只定位文件，不作为答疑事实。</p>' + renderTrace(trace) + (attachments.length ? '<p class="helper">消息 ' + e(latest.id) + ' · ' + (receiptStatus(latest) === 'received' ? '访客预览已登记本地收件' : '等待访客预览登记本地收件') + ' · ' + e(attachments.map(item => (item.title || item.filename) + ' r' + item.revision).join('、')) + '</p>' : '') + '<p class="helper">本地收件、打开和发起下载分别留证。外部送达与业务解决尚未验证。</p></details>';
}

export function renderVisitorRunEvidence(run) {
  if (!run.materialEvidence && !list(run.attachments).length) return '';
  const message = { id: run.messageId, attachments: run.attachments, localReceipt: run.localReceipt, attachmentInteractions: run.attachmentInteractions };
  return '<div class="visitor-run-evidence"><h3>物料检索与访客收件</h3>' + renderTrace(run.materialEvidence?.trace || run.trace) + renderVisitorAttachments(message, run.surface || 'trial', { runId: run.id }) + '<p class="helper">附件保留发送时的文件引用和修订；原件仍须能从当前浏览器缓存读取。此处不证明外部渠道送达或业务请求已解决。</p></div>';
}
