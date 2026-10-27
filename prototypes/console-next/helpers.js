export function escapeHtml(value = '') {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
export const attr = escapeHtml;

const paths = {
  agents: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="M6 16c0-3 6-3 6 0m4-6h3m-3 4h3"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  chat: '<path d="M21 14a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M7 8h10M7 12h7"/>',
  inbox: '<path d="m3 13 3-9h12l3 9v7H3Z"/><path d="M3 13h5l2 3h4l2-3h5"/>',
  widget: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 8h18M8 8v13"/>',
  contact: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M9 6h6M9 10h6M9 14h4M10 18h4"/>',
  play: '<path d="m8 5 11 7-11 7V5Z"/>',
  runs: '<path d="M4 4v16h16M8 16v-5m4 5V8m4 8V5"/>',
  cases: '<rect x="5" y="4" width="14" height="18" rx="2"/><path d="M9 4V2h6v2M8 11l2 2 5-5m-7 10h8"/>',
  change: '<path d="M4 8h14l-4-4M20 16H6l4 4M18 8v5M6 16v-5"/>',
  versions: '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5m-18 5 9 5 9-5"/>',
  book: '<path d="M12 5c-4-3-8-2-9-1v15c3-2 6-2 9 0 3-2 6-2 9 0V4c-1-1-5-2-9 1Zm0 0v14"/>',
  plug: '<path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0V8Zm6 9v5"/>',
  cloud: '<path d="M6 18a5 5 0 1 1 1-10 7 7 0 0 1 13 3 4 4 0 0 1-1 7H6Z"/>',
  settings: '<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  'panel-left': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
};
export function icon(name, size = 18) {
  return `<svg width="${Number(size)}" height="${Number(size)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
}
export function badge(label, tone = 'neutral') {
  return `<span class="badge badge-${attr(tone)}">${escapeHtml(label)}</span>`;
}
export function button(action, label, options = {}) {
  const { variant = 'secondary', disabled = false, className = '', title = '', ...data } = options;
  const attributes = Object.entries(data).map(([key, value]) => `data-${key.replace(/[A-Z]/g, char => '-' + char.toLowerCase())}="${attr(value)}"`).join(' ');
  return `<button type="button" class="btn btn-${attr(variant)} ${attr(className)}" data-action="${attr(action)}" ${attributes} ${disabled ? 'disabled' : ''} ${title ? `title="${attr(title)}"` : ''}>${escapeHtml(label)}</button>`;
}
export function field(label, bind, value, options = {}) {
  const { type = 'text', help = '', readonly = false, placeholder = '', format = '', rows = 3 } = options;
  const id = 'field-' + bind.replace(/[^a-zA-Z0-9]/g, '-');
  const common = `id="${attr(id)}" name="${attr(bind)}" data-bind="${attr(bind)}" ${format ? `data-format="${attr(format)}"` : ''} ${readonly ? 'disabled' : ''}`;
  let input;
  if (type === 'textarea') input = `<textarea class="control textarea" ${common} rows="${Number(rows)}" placeholder="${attr(placeholder)}">${escapeHtml(value)}</textarea>`;
  else if (type === 'select') input = `<select class="control" ${common}>${(options.options || []).map(item => {
    const [val, text] = typeof item === 'string' ? [item, item] : Array.isArray(item) ? item : [item.value, item.label];
    return `<option value="${attr(val)}" ${String(val) === String(value) ? 'selected' : ''}>${escapeHtml(text)}</option>`;
  }).join('')}</select>`;
  else if (type === 'checkbox') input = `<input type="checkbox" ${common} ${value ? 'checked' : ''}>`;
  else input = `<input class="control input" type="${attr(type)}" ${common} value="${attr(value)}" placeholder="${attr(placeholder)}">`;
  return `<div class="field ${type === 'checkbox' ? 'field-checkbox' : ''}"><label for="${attr(id)}">${escapeHtml(label)}</label><div class="field-control">${input}${help ? `<p class="helper">${escapeHtml(help)}</p>` : ''}</div></div>`;
}
export function section(title, body, options = {}) {
  return `<section class="section ${attr(options.className || '')}"><div class="section-heading"><div><h2>${escapeHtml(title)}</h2>${options.description ? `<p class="muted">${escapeHtml(options.description)}</p>` : ''}</div>${options.actions || ''}</div>${body}</section>`;
}
export function emptyState(title, description, actions = '') {
  return `<div class="empty-state"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p><div class="inline">${actions}</div></div>`;
}
export function formatTime(iso) {
  if (!iso) return '尚未记录';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? escapeHtml(iso) : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
export function renderReadiness(ready) {
  return `<ul class="readiness">${ready.items.map(item => `<li><div class="inline">${badge(item.status === 'ok' ? '已具备' : item.status === 'warning' ? '演示' : '待补齐', item.status === 'ok' ? 'success' : 'warning')}<strong>${escapeHtml(item.label)}</strong></div><p>${escapeHtml(item.detail)}</p>${item.page ? button('navigate', '查看', { page: item.page, variant: 'ghost' }) : ''}</li>`).join('')}</ul>`;
}
export function pageHeading(title, description, actions = '') {
  return `<header class="page-header"><div><h1>${escapeHtml(title)}</h1>${description ? `<p>${escapeHtml(description)}</p>` : ''}</div><div class="inline">${actions}</div></header>`;
}
