import { escapeHtml } from '../helpers.js';

const tabs = [
  ['persona', '人设'], ['flow', '流程'], ['boundary', '边界'],
  ['task', '任务蓝图'], ['history', '版本历史'],
];
const e = escapeHtml;
const stringify = value => JSON.stringify(value ?? {}, null, 2);

function control(label, path, value, workspace, { multiline = false, type = 'text', help = '' } = {}) {
  const id = `r1-${path.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const disabled = workspace.status !== 'ready' || workspace.busy || workspace.readOnlySnapshot || workspace.selectedCandidate;
  const input = multiline
    ? `<textarea class="control textarea r1-control" id="${id}" data-r1-bind="${e(path)}" rows="3" ${disabled ? 'disabled' : ''}>${e(value ?? '')}</textarea>`
    : `<input class="control input r1-control" id="${id}" data-r1-bind="${e(path)}" type="${type}" value="${e(value ?? '')}" ${disabled ? 'disabled' : ''}>`;
  return `<div class="field"><label for="${id}">${e(label)}</label>${input}${help ? `<p class="helper">${e(help)}</p>` : ''}</div>`;
}

function jsonEditor(label, path, value, workspace, help = '') {
  const id = `r1-${path.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const raw = workspace.jsonInputs?.[path] ?? stringify(value);
  const error = workspace.jsonErrors?.[path];
  const disabled = workspace.status !== 'ready' || workspace.busy || workspace.readOnlySnapshot || workspace.selectedCandidate;
  return `<div class="field r1-json-field"><label for="${id}">${e(label)}</label><textarea class="control textarea r1-control r1-json-control" id="${id}" data-r1-json="${e(path)}" rows="10" spellcheck="false" aria-invalid="${error ? 'true' : 'false'}" ${disabled ? 'disabled' : ''}>${e(raw)}</textarea>${help ? `<p class="helper">${e(help)}</p>` : ''}${error ? `<p class="field-error" role="alert">JSON 格式错误：${e(error)}</p>` : ''}</div>`;
}

function action(name, label, extra = '', disabled = false, primary = false) {
  return `<button class="btn ${primary ? 'btn-primary' : 'btn-secondary'}" type="button" data-action="${name}" ${extra} ${disabled ? 'disabled' : ''}>${label}</button>`;
}

function issueList(issues = []) {
  if (!issues.length) return '<p class="muted">服务端没有返回字段错误。</p>';
  return `<ul class="r1-issues">${issues.map(issue => `<li><code>${e(issue.path || '$')}</code><span>${e(issue.message || issue.code || '校验失败')}</span></li>`).join('')}</ul>`;
}

function conflictPanel(workspace) {
  const conflict = workspace.conflict;
  if (!conflict?.current) return '';
  const changed = conflict.attemptedConfig ? `<details><summary>查看本地未保存版本</summary><pre class="r1-json-readonly">${e(stringify(conflict.attemptedConfig))}</pre></details>` : '';
  return `<section class="notice notice-warning r1-conflict" role="alert"><strong>草稿 revision 已变化</strong><p>服务端当前为 r${e(conflict.current.revision)}。本页仍保留你刚才提交的内容，不会自动覆盖或合并。</p><details><summary>查看服务端当前草稿 r${e(conflict.current.revision)}</summary><pre class="r1-json-readonly">${e(stringify(conflict.current.config))}</pre></details>${changed}<div class="button-group">${action('r1-reload-conflict', '载入服务端版本')}${conflict.attemptedConfig ? action('r1-retry-conflict', '用本地整份草稿覆盖并重试') : ''}</div>${conflict.attemptedConfig ? '<p class="helper">覆盖重试会以服务端最新 revision 保存本地整份配置，可能替换另一入口刚做的修改；请先比较上方内容。</p>' : ''}</section>`;
}

function historyPanel(workspace) {
  const selected = workspace.readOnlySnapshot || workspace.selectedCandidate;
  const stable = workspace.stableVersions || [];
  const candidates = workspace.candidates || [];
  return `<section class="r1-history"><div class="item-heading"><h3>稳定历史（只读）</h3>${action('r1-refresh', '刷新历史', '', workspace.busy)}</div>${stable.length ? `<ul class="config-list">${stable.map(item => `<li><div class="item-heading"><strong>${e(item.version_id)}</strong><span class="muted">${e(item.content_hash?.slice(0, 12) || '')}</span></div><p class="helper">${e(item.created_at || '')}</p>${action('r1-open-stable', '只读查看', `data-version-id="${e(item.version_id)}"`, workspace.busy)}</li>`).join('')}</ul>` : '<p class="muted">当前服务端尚无稳定快照。</p>'}
    <h3>冻结候选</h3>${candidates.length ? `<ul class="config-list">${candidates.map(item => `<li><div class="item-heading"><strong>${e(item.candidate_id)}</strong><span>${e(item.status || '候选')}</span></div><p class="helper">来源 revision r${e(item.source_revision)} · ${e(item.content_hash?.slice(0, 12) || '')}</p>${action('r1-open-candidate', '查看字段差异', `data-candidate-id="${e(item.candidate_id)}"`, workspace.busy)}</li>`).join('')}</ul>` : '<p class="muted">尚无冻结候选。</p>'}
    ${selected ? `<section class="r1-snapshot"><div class="item-heading"><h3>${workspace.readOnlySnapshot ? `稳定版本 ${e(selected.version_id)} · 只读` : `候选 ${e(selected.candidate_id)} · 未批准`}</h3>${action('r1-close-snapshot', '关闭')}</div>${!workspace.readOnlySnapshot ? releaseChecklist(workspace.releaseChecklist) : ''}${selected.config ? `<p class="helper">配置快照</p><pre class="r1-json-readonly">${e(stringify(selected.config))}</pre>` : ''}${selected.diff ? `<h4>字段级差异</h4><ul class="r1-diff">${selected.diff.map(item => `<li><code>${e(item.path)}</code><div><span>之前</span><pre>${e(item.before_exists === false ? '字段不存在' : stringify(item.before))}</pre></div><div><span>之后</span><pre>${e(item.after_exists === false ? '字段不存在' : stringify(item.after))}</pre></div></li>`).join('') || '<li class="muted">没有字段差异。</li>'}</ul>` : ''}<p class="notice">冻结候选不是审批、稳定版本或发布。</p></section>` : ''}</section>`;
}

function releaseChecklist(checklist) {
  if (!checklist) return '<section class="notice"><strong>发布预检尚未读取</strong></section>';
  const progress = checklist.progress || {};
  const statusText = { passed: '通过', failed: '未通过', pending: '待验证' };
  return `<section class="r1-release-checklist"><div class="item-heading"><h4>发布前检查</h4><span>${e(progress.passed || 0)}/${e(progress.total || 0)} 项通过</span></div><p class="helper">通过 ${e(progress.passed || 0)} · 未通过 ${e(progress.failed || 0)} · 待验证 ${e(progress.pending || 0)}</p><ul class="config-list">${(checklist.checks || []).map(check => `<li><div class="item-heading"><strong>${e(check.label)}</strong><span>${e(statusText[check.status] || check.status)}</span></div><p class="helper">${e(typeof check.detail === 'string' ? check.detail : JSON.stringify(check.detail))}</p></li>`).join('')}</ul><p class="notice ${checklist.ready ? '' : 'notice-warning'}">${checklist.ready ? '检查项已齐备；本版本仍未开放批准或发布。' : '尚有检查未完成；此清单仅供查看，当前不能批准或发布。'}</p></section>`;
}

function configTab(workspace) {
  const config = workspace.readOnlySnapshot?.config || workspace.selectedCandidate?.config || workspace.editorConfig || {};
  const persona = config.persona || {};
  if (workspace.activeTab === 'persona') {
    return `<div class="stack r1-editor-grid"><p class="helper">以下是 R1 服务端 schema 中明确映射的人设字段；未映射字段会随配置保留并在只读区显示。</p>${control('名称', 'persona.name', persona.name, workspace)}${control('服务目标', 'persona.goal', persona.goal, workspace, { multiline: true })}${control('服务对象', 'persona.audience', persona.audience, workspace)}${control('欢迎语', 'persona.greeting', persona.greeting, workspace, { multiline: true })}${control('回答范围', 'persona.scope', persona.scope, workspace, { multiline: true })}${control('资料不足时', 'persona.fallback', persona.fallback, workspace, { multiline: true })}${jsonEditor('业务字段目录', 'persona.fields', persona.fields || {}, workspace, '用于 G0、HardRule 与 Unit 的确定性字段引用。保持未识别字段原样。')}${persona.entry_unit_ids !== undefined ? jsonEditor('入口单元 ID', 'persona.entry_unit_ids', persona.entry_unit_ids, workspace, '路由单元入口声明；需与流程中的 unit_id 对应。') : ''}</div>`;
  }
  if (workspace.activeTab === 'flow') {
    return `<div class="stack"><div class="notice"><strong>R1 流程清单</strong><p>只编辑声明式 Unit 清单，不支持画布执行；完整 R1 Unit 合同保留空的 body。</p></div>${jsonEditor('Unit 清单', 'units', config.units || [], workspace, '必需字段：unit_id、version、load_mode、entry_ports、reads、writes、exit_ports、on_event、fallback、max_rounds、body。R1 不允许 concurrent 提交，body 必须为 {}。')}</div>`;
  }
  if (workspace.activeTab === 'boundary') {
    return `<div class="stack"><div class="notice notice-warning"><strong>边界修改受服务端字段校验</strong><p>HardRule 使用 when / verdict / enforce 合同；不得通过此编辑器授予真实业务权限。</p></div>${jsonEditor('G0 确定性闸门', 'g0_gates', config.g0_gates || [], workspace, '条件命中后 route_to 为 block、suspend 或一个已声明 Unit ID。')}${jsonEditor('HardRule v0.2', 'hard_rules', config.hard_rules || [], workspace, 'verdict.type 为 deny / require / stop / dedupe；enforce 包含 scope、reason、priority、customer_facing、severity 与有效期。')}</div>`;
  }
  if (workspace.activeTab === 'task') {
    return `<div class="stack"><div class="notice notice-warning"><strong>Task 蓝图暂时只读</strong><p>蓝图会随专家版本冻结，但 TaskItem 撤销恢复及主体/用途隔离合同尚未定版；本轮保留已存字段，不通过页面制造未批准的执行语义。</p></div><pre class="r1-json-readonly">${e(stringify(config.task_blueprints || []))}</pre></div>`;
  }
  return historyPanel(workspace);
}

function unknownConfig(config = {}) {
  const known = new Set(['persona', 'units', 'g0_gates', 'hard_rules', 'task_blueprints']);
  const unknown = Object.fromEntries(Object.entries(config).filter(([key]) => !known.has(key)));
  const persona = config.persona || {};
  const knownPersona = new Set(['name', 'role', 'goal', 'audience', 'greeting', 'scope', 'fallback', 'fields', 'entry_unit_ids']);
  const unknownPersona = Object.fromEntries(Object.entries(persona).filter(([key]) => !knownPersona.has(key)));
  if (!Object.keys(unknown).length && !Object.keys(unknownPersona).length) return '';
  return `<details class="r1-unknown"><summary>未映射字段（保留原样，只读）</summary>${Object.keys(unknown).length ? `<h3>配置根字段</h3><pre class="r1-json-readonly">${e(stringify(unknown))}</pre>` : ''}${Object.keys(unknownPersona).length ? `<h3>人设字段</h3><pre class="r1-json-readonly">${e(stringify(unknownPersona))}</pre>` : ''}<p class="helper">保存时保留这些字段；此工作面不会转换或丢弃它们。</p></details>`;
}

function currentReadOnly(workspace) {
  if (workspace.readOnlySnapshot || workspace.selectedCandidate) return true;
  return workspace.status !== 'ready';
}

export function renderR1Configuration(ctx) {
  const workspace = ctx.r1Configuration?.state;
  if (!workspace) return '<section class="notice notice-danger">R1 配置工作面尚未初始化。</section>';
  const dirty = Boolean(workspace.draft && workspace.editorConfig && stringify(workspace.draft.config) !== stringify(workspace.editorConfig));
  const title = workspace.readOnlySnapshot ? `稳定版本 ${workspace.readOnlySnapshot.version_id}` : workspace.selectedCandidate ? `候选 ${workspace.selectedCandidate.candidate_id}` : workspace.draft ? `草稿 r${workspace.draft.revision}` : '服务端配置';
  const disabled = currentReadOnly(workspace) || workspace.busy;
  const statusText = {
    idle: '尚未连接服务端', loading: '正在读取配置服务…', ready: dirty ? '有未保存修改' : '与服务端草稿一致',
    'no-draft': '服务端暂无草稿', error: '配置服务读取失败', conflict: 'revision 冲突待处理',
  }[workspace.status] || workspace.status;
  const configActions = workspace.draft && !workspace.readOnlySnapshot && !workspace.selectedCandidate
    ? `<div class="button-group">${action('r1-save', '保存草稿', '', disabled || !dirty || Object.keys(workspace.jsonErrors || {}).length > 0, true)}${action('r1-validate', '服务端校验', '', disabled || dirty)}${action('r1-freeze', '冻结候选', '', disabled || dirty)}${dirty ? '<p class="helper">先保存当前修改，再运行服务端校验或冻结候选。</p>' : ''}</div>`
    : '';
  const noDraft = workspace.status === 'no-draft'
    ? `<section class="notice"><strong>没有服务端草稿</strong><p>选择一个已登记的稳定版本创建草稿。尚无稳定版本时，通过受信任 owner 的 CLI 导入经过确认的快照。</p>${workspace.stableVersions?.length ? `<div class="button-group">${workspace.stableVersions.map(item => action('r1-create-draft', `基于 ${e(item.version_id)} 创建草稿`, `data-version-id="${e(item.version_id)}"`, workspace.busy, true)).join('')}</div>` : '<p class="helper">稳定快照列表为空；此页不会把本地 demo 自动写入服务端。</p>'}</section>` : '';
  const error = workspace.error ? `<section class="notice notice-danger" role="alert"><strong>${e(workspace.error.message)}</strong>${workspace.error.code ? `<p class="helper">错误码：${e(workspace.error.code)}</p>` : ''}${workspace.status === 'error' ? '<p class="helper">请确认已运行 `loomrise config serve`，并且本机 principal 已授权当前专家。失败时没有本地写入回退。</p>' : ''}</section>` : '';
  const validation = workspace.validation ? `<section class="notice ${workspace.validation.valid ? '' : 'notice-danger'}" role="status"><strong>${workspace.validation.valid ? '服务端校验通过' : '服务端校验发现问题'}</strong><p>校验 revision r${e(workspace.validation.revision)}。</p>${issueList(workspace.validation.issues)}</section>` : '';
  const conflict = conflictPanel(workspace);
  const config = workspace.readOnlySnapshot?.config || workspace.selectedCandidate?.config || workspace.editorConfig;
  const tabsHtml = tabs.map(([id, label]) => `<button class="btn btn-ghost r1-tab ${workspace.activeTab === id ? 'is-active' : ''}" type="button" data-action="r1-tab" data-tab="${id}" aria-pressed="${workspace.activeTab === id}">${label}</button>`).join('');
  return `<section class="r1-service-workspace"><header class="r1-service-header"><div><p class="eyebrow">R1 · 共用配置服务</p><h2>服务端版本工作面</h2><p class="muted">${e(ctx.agent?.name || workspace.agentId)} · ${e(title)} · ${e(statusText)}</p></div><div class="button-group">${action('r1-refresh', '重新读取', '', workspace.busy)}${workspace.readOnlySnapshot || workspace.selectedCandidate ? action('r1-close-snapshot', '返回草稿工作面') : ''}</div></header>
    ${error}${conflict}${validation}${noDraft}
    ${workspace.draft && !workspace.readOnlySnapshot && !workspace.selectedCandidate ? `<section class="r1-server-metadata"><span>服务端 revision <strong>r${e(workspace.draft.revision)}</strong></span><span>基准版本 <strong>${e(workspace.draft.base_version_id || '未登记')}</strong></span><span>更新时间 <strong>${e(workspace.draft.updated_at || '')}</strong></span></section>` : ''}
    ${config || workspace.activeTab === 'history' ? `<div class="r1-tabs" role="group" aria-label="服务端配置分区">${tabsHtml}</div><section class="r1-editor" aria-label="${e(workspace.activeTab)}">${configTab(workspace)}${config && workspace.activeTab !== 'history' ? unknownConfig(config) : ''}${configActions}</section>` : ''}
    ${workspace.status === 'idle' ? '<p class="helper">打开此工作面后将读取共用配置服务；本地示例和原型存储不会导入或覆盖服务端数据。</p>' : ''}
    <details class="r1-api-detail"><summary>连接状态与范围</summary><dl class="definition-list"><div><dt>API</dt><dd><code>${e(ctx.r1Configuration.client.origin)}</code></dd></div><div><dt>数据源</dt><dd>SQLite 配置服务；浏览器仅发送当前授权专家 ID，角色和租户由服务端 principal 决定。</dd></div><div><dt>本地演示状态</dt><dd>专家首页、知识来源、测试、上线与运行记录仍由浏览器原型状态驱动，不属于此 R1 配置 API。</dd></div></dl></details>
  </section>`;
}
