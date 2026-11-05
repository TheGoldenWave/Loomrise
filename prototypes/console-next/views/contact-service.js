import { escapeHtml as e, button, pageHeading, section } from '../helpers.js';

const labels = { question: '问题', answer: '回答', label: '名称', href: '目标链接', description: '说明', title: '标题',
  src: '媒体地址', alt: '媒体说明', media_type: '媒体类型', quote: '评价内容', author: '评价人', value: '内容', price: '价格说明',
  day: '日期', hours: '时段', address: '地址', period: '起止时间', time: '时间', location: '地点' };
const fieldOrder = ['title', 'label', 'question', 'answer', 'quote', 'author', 'description', 'value', 'price', 'day', 'hours', 'time', 'period', 'address', 'location', 'media_type', 'src', 'alt', 'href'];

function field(label, path, value, disabled, multiline = false) {
  const key = JSON.stringify(path);
  const id = `contact-field-${path.join('-')}`;
  const attributes = `id="${e(id)}" data-contact-bind="${e(key)}" ${disabled ? 'disabled' : ''}`;
  const input = path.at(-1) === 'media_type'
    ? `<select class="control input" ${attributes}><option value="">请选择</option>${[['image', '图片'], ['video', '视频'], ['audio', '音频']].map(([key, title]) => `<option value="${key}" ${value === key ? 'selected' : ''}>${title}</option>`).join('')}</select>`
    : multiline ? `<textarea class="control textarea" ${attributes} rows="3">${e(value || '')}</textarea>`
    : `<input class="control input" ${attributes} value="${e(value || '')}">`;
  return `<div class="field"><label for="${e(id)}">${e(label)}</label>${input}</div>`;
}

function renderDrafting(state, types, disabled) {
  const candidate = state.proposal?.contact;
  const review = candidate ? `<div class="contact-preview" data-contact-proposal><h3 class="source-text">${e(candidate.title)}</h3><p class="source-text">${e(candidate.description || '')}</p>
    <p class="helper">待核对候选 · ${candidate.blocks.length} 个内容块 · 采用后仍需保存。</p>
    ${candidate.blocks.map(block => {
      const kind = types.find(type => type.type === block.type);
      return `<div class="contact-block"><h4 class="source-text">${e(kind?.label || block.type)}${block.title ? ` · ${e(block.title)}` : ''}</h4><p class="source-text">${e(block.body || '')}</p>
        ${(block.items || []).map(item => `<dl class="definition-list">${[...(kind?.item_fields || [])].sort((a, b) => fieldOrder.indexOf(a) - fieldOrder.indexOf(b)).filter(key => item[key] !== undefined && item[key] !== '').map(key => `<dt>${e(labels[key] || key)}</dt><dd class="source-text">${e(item[key])}</dd>`).join('')}</dl>`).join('')}</div>`;
    }).join('')}
    <div class="button-group">${button('cs-contact-adopt-proposal', '采用并替换编辑内容', { disabled })}${button('cs-contact-discard-proposal', '丢弃候选', { disabled })}</div></div>` : '';
  return `<details class="contact-generation" ${state.status === 'generating' || candidate || state.generationError ? 'open' : ''}><summary>AI 辅助起草（可选）</summary><div class="stack">
    <p class="helper" id="contact-generation-help">使用当前模型连接，仅发送本栏素材和所选模板类型，可能产生模型用量。请核对候选内容、联系方式与业务承诺后再采用。</p>
    <div class="field"><label for="contact-generation-brief">页面素材与要求</label><textarea class="control textarea" id="contact-generation-brief" data-contact-generation-brief aria-describedby="contact-generation-help" rows="5" maxlength="4000" ${disabled ? 'disabled' : ''}>${e(state.generationBrief || '')}</textarea></div>
    <div class="field"><label for="contact-generation-template">起草参考模板</label><select class="control input" id="contact-generation-template" data-contact-generation-template ${disabled ? 'disabled' : ''}><option value="">不指定模板</option>${state.templates.map(template => `<option value="${e(template.id)}" ${state.generationTemplateId === template.id ? 'selected' : ''}>${e(template.name)}</option>`).join('')}</select></div>
    <div class="button-group">${button('cs-contact-generate', state.status === 'generating' ? '正在起草…' : '生成待审候选', { disabled: disabled || !state.generationBrief?.trim() })}<span role="status">${state.status === 'generating' ? '正在起草，当前编辑内容已保留。' : candidate ? '候选尚未采用，当前编辑内容保持原样。' : '生成候选后，可逐块核对再采用。'}</span></div>
    ${state.generationError ? `<p class="notice notice-danger" role="alert">${e(state.generationError.message)}${state.conflict ? ' 本地内容已保留，请核对服务端新版本。' : ' 可继续手动编辑。'}</p>` : ''}${review}
    </div></details>`;
}

export function renderContactService(ctx) {
  const workspace = ctx.contactWorkspace;
  const state = workspace.state;
  const heading = pageHeading('联系页', '编辑同一份服务端草稿，已启用页面保持批准的版本。', button('cs-contact-reload', '重新读取', { disabled: ['saving', 'generating'].includes(state.status) }));
  if (state.agentId !== ctx.agent?.id || ['idle', 'loading'].includes(state.status)) return heading + '<p role="status">正在读取联系页与内容块定义…</p>';
  if (state.status === 'error') return heading + `<p class="notice notice-danger" role="alert">${e(state.error?.message || '读取失败')}。请检查服务连接与专家授权后重试。</p>`;
  const disabled = !workspace.writable();
  const config = state.contact;
  const types = state.schema?.block_types || [];
  if (!config || !Array.isArray(config.blocks)) return heading + '<p role="alert">联系页结构无法解析，请通过服务端配置原文修复后重新读取。</p>';
  const preview = `${workspace.client.origin}/contact-preview/${encodeURIComponent(state.agentId)}`;
  const summary = `<div class="button-group">${button('cs-contact-save', state.status === 'saving' ? '正在保存…' : '保存修改', { disabled: disabled || !state.dirty, variant: 'primary' })}<a class="btn btn-secondary" href="${e(preview)}" target="_blank" rel="noopener">预览已保存草稿</a><span role="status">${state.dirty ? '有未保存修改' : '已保存到服务端'} · r${e(state.revision)}</span></div>`;
  const error = state.error ? `<p class="notice notice-danger" role="alert">${e(state.error.message)}${state.conflict ? '。本地输入已保留，请先核对服务端新版本。' : ''}</p>` : '';
  const conflict = state.conflict ? `<details open><summary>冲突中的本地内容（可复制保留）</summary><pre class="r1-json-readonly">${e(JSON.stringify(state.conflict.attempted, null, 2))}</pre></details>` : '';
  const templates = `<details><summary>从模板开始</summary><p class="helper">选择模板会替换当前编辑内容；保存后仍不改变已启用版本。</p><div class="button-group">${state.templates.map(template => button('cs-contact-template', template.name, { id: template.id, disabled })).join('')}</div></details>`;
  const blocks = config.blocks.map((block, index) => {
    const kind = types.find(type => type.type === block?.type);
    if (!kind) return `<section class="config-module"><p role="alert">第 ${index + 1} 个内容块类型无法识别，原文保持不变。</p><pre>${e(JSON.stringify(block, null, 2))}</pre></section>`;
    const items = Array.isArray(block.items) ? block.items : [];
    return `<section class="config-module" data-contact-block="${e(block.id)}"><div class="section-heading"><h3>${e(kind.label)}</h3><div class="button-group">${button('cs-contact-up', '上移', { index, disabled: disabled || index === 0 })}${button('cs-contact-down', '下移', { index, disabled: disabled || index === config.blocks.length - 1 })}${button('cs-contact-remove', '删除块', { index, disabled })}</div></div>
      ${field('块标题', ['blocks', index, 'title'], block.title, disabled)}${field('块说明', ['blocks', index, 'body'], block.body, disabled, true)}
      ${items.map((item, itemIndex) => `<fieldset class="contact-item"><legend>内容 ${itemIndex + 1}</legend>${[...kind.item_fields].sort((a, b) => fieldOrder.indexOf(a) - fieldOrder.indexOf(b)).map(key => field(`${labels[key] || key}${kind.required_item_fields.includes(key) ? '（必填）' : ''}`, ['blocks', index, 'items', itemIndex, key], item[key], disabled, ['answer', 'description', 'quote'].includes(key))).join('')}${button('cs-contact-remove-item', '删除此项', { index, itemIndex, disabled })}</fieldset>`).join('')}
      ${kind.item_fields.length ? button('cs-contact-add-item', '添加内容', { index, disabled }) : ''}</section>`;
  }).join('');
  const add = `<label for="contact-new-type">新增内容块</label><div class="button-group"><select class="control input" id="contact-new-type" ${disabled ? 'disabled' : ''}>${types.map(type => `<option value="${e(type.type)}">${e(type.label)}</option>`).join('')}</select>${button('cs-contact-add', '添加内容块', { disabled })}</div>`;
  const entry = section('分享与停用', `<div class="field"><label for="contact-entry-id">已批准的沙盒入口标识</label><input class="control input" id="contact-entry-id" data-contact-entry value="${e(state.entryId || '')}" ${state.entryBusy ? 'disabled' : ''}></div><div class="button-group">${button('cs-contact-query-entry', state.entryBusy ? '处理中…' : '查看入口版本', { disabled: state.entryBusy || !state.entryId?.trim() })}${button('cs-contact-enable', state.entry ? `启用批准版 ${state.entry.version_id}` : '启用批准版本', { disabled: disabled || state.entryBusy || !state.entry })}${button('cs-contact-disable', '停用此联系页', { disabled: disabled || state.entryBusy || !state.entryId?.trim() })}</div>
    ${state.entryError ? `<p class="field-error" role="alert">${e(state.entryError)}</p>` : ''}
    ${state.livePage ? `<p>已启用版本：${e(state.livePage.version_id)}</p><a class="btn btn-secondary" href="${e(workspace.client.origin + state.livePage.share_path)}" target="_blank" rel="noopener">打开联系页 / 获取分享地址</a>` : `<p class="helper">${state.entry ? '此入口的联系页尚未启用。' : '输入入口标识后查询当前批准版本。'}</p>`}
    <p class="helper">启用使用上方明确显示的批准版本。当前草稿修改需经原版本检查与批准流程后，才能更新入口。</p>`);
  return heading + error + conflict + summary + templates + renderDrafting(state, types, disabled) + section('页面内容', `<div class="stack">${field('页面标题', ['title'], config.title, disabled)}${field('页面说明', ['description'], config.description, disabled, true)}${blocks || '<p class="helper">暂无内容块，可从模板开始或添加一个内容块。</p>'}${add}</div>`) + entry;
}
