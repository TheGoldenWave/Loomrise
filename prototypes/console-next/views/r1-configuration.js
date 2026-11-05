import { escapeHtml } from '../helpers.js';

const tabs = [
  ['persona', '人设'], ['flow', '流程'], ['boundary', '边界'],
  ['task', '任务蓝图'], ['history', '版本历史'],
  ['reception', '客服接待'],
];
const e = escapeHtml;
const stringify = value => JSON.stringify(value ?? {}, null, 2);
const diffValue = value => JSON.stringify(value, null, 2) ?? 'null';
const viewingSnapshot = workspace => Boolean(workspace.readOnlySnapshot || workspace.selectedCandidate || workspace.comparison);
const displayedConfig = workspace => workspace.comparison?.after.config || workspace.readOnlySnapshot?.config || workspace.selectedCandidate?.config || workspace.editorConfig;

function control(label, path, value, workspace, { multiline = false, type = 'text', help = '' } = {}) {
  const id = `r1-${path.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const disabled = currentReadOnly(workspace) || workspace.busy;
  const input = multiline
    ? `<textarea class="control textarea r1-control" id="${id}" data-r1-bind="${e(path)}" rows="3" ${disabled ? 'disabled' : ''}>${e(value ?? '')}</textarea>`
    : `<input class="control input r1-control" id="${id}" data-r1-bind="${e(path)}" type="${type}" value="${e(value ?? '')}" ${disabled ? 'disabled' : ''}>`;
  return `<div class="field"><label for="${id}">${e(label)}</label>${input}${help ? `<p class="helper">${e(help)}</p>` : ''}</div>`;
}

function jsonEditor(label, path, value, workspace, help = '') {
  const id = `r1-${path.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const raw = viewingSnapshot(workspace) ? stringify(value) : workspace.jsonInputs?.[path] ?? stringify(value);
  const error = viewingSnapshot(workspace) ? null : workspace.jsonErrors?.[path];
  const disabled = currentReadOnly(workspace) || workspace.busy;
  return `<div class="field r1-json-field"><label for="${id}">${e(label)}</label><textarea class="control textarea r1-control r1-json-control" id="${id}" data-r1-json="${e(path)}" rows="10" spellcheck="false" aria-invalid="${error ? 'true' : 'false'}" ${disabled ? 'disabled' : ''}>${e(raw)}</textarea>${help ? `<p class="helper">${e(help)}</p>` : ''}${error ? `<p class="field-error" role="alert">JSON 格式错误：${e(error)}</p>` : ''}</div>`;
}

function action(name, label, extra = '', disabled = false, primary = false) {
  return `<button class="btn ${primary ? 'btn-primary' : 'btn-secondary'}" type="button" data-action="${name}" ${extra} ${disabled ? 'disabled' : ''}>${label}</button>`;
}

function issueList(issues = []) {
  if (!issues.length) return '<p class="muted">服务端没有返回字段错误。</p>';
  return `<ul class="r1-issues">${issues.map(issue => `<li><code>${e(issue.path || '$')}</code><span>${e(issue.message || issue.code || '校验失败')}</span></li>`).join('')}</ul>`;
}

function objectDiffPanel(diff, source, expanded = true) {
  if (!diff) return '';
  const value = item => JSON.stringify(item, null, 2) ?? 'null';
  const kinds = { unit: 'Unit', node: '节点', entry_port: '入口端口', exit_port: '出口端口', edge: '边', edge_order: '边优先级', configuration: '配置' };
  const operations = { added: '新增', removed: '删除', changed: '修改', priority: '优先级变化', positional: '按位置比较' };
  return `<details class="r1-object-diff" ${expanded ? 'open' : ''}><summary>对象级差异 · ${e(source)}</summary><p class="helper">按标识对齐 Unit、节点、端口与边；边列表从前到后优先级递减。此视图不代表审批或发布。</p>${(diff.diagnostics || []).map(item => `<p class="notice notice-warning"><code>${e(item.path)}</code> ${e(item.message)}</p>`).join('')}<ul class="r1-diff">${(diff.changes || []).map(item => `<li><strong>${e(kinds[item.object_type] || item.object_type)} ${e(item.object_id)} · ${e(operations[item.operation] || item.operation)}</strong><code>${e(item.path)}</code><div><span>之前</span><pre>${e(item.before_exists === false ? '不存在' : value(item.before))}</pre></div><div><span>之后</span><pre>${e(item.after_exists === false ? '不存在' : value(item.after))}</pre></div></li>`).join('') || '<li class="muted">没有对象差异。</li>'}</ul></details>`;
}

function conflictPanel(workspace) {
  const conflict = workspace.conflict;
  if (!conflict?.current) return '';
  const changed = conflict.attemptedConfig ? `<details><summary>查看本地未保存版本</summary><pre class="r1-json-readonly">${e(stringify(conflict.attemptedConfig))}</pre></details>` : '';
  return `<section class="notice notice-warning r1-conflict" role="alert"><strong>草稿 revision 已变化</strong><p>服务端当前为 r${e(conflict.current.revision)}。本页仍保留你刚才提交的内容，不会自动覆盖或合并。</p><details><summary>查看服务端当前草稿 r${e(conflict.current.revision)}</summary><pre class="r1-json-readonly">${e(stringify(conflict.current.config))}</pre></details>${changed}<div class="button-group">${action('r1-reload-conflict', '载入服务端版本')}${conflict.attemptedConfig ? action('r1-retry-conflict', '用本地整份草稿覆盖并重试') : ''}</div>${conflict.attemptedConfig ? '<p class="helper">覆盖重试会以服务端最新 revision 保存本地整份配置，可能替换另一入口刚做的修改；请先比较上方内容。</p>' : ''}</section>`;
}

function advisoryReviewSummary(items = []) {
  if (!items.length) return '';
  return `<section class="notice r1-advisory-review" aria-label="画布提示忽略记录"><strong>画布提示忽略记录 · ${items.length}</strong><ul>${items.map(item => `<li>闭集 ${e(item.closed_set_size)} · ${e((item.layer_path || []).join(' / ') || '版本路由')} · r${e(item.source_revision)} · ${e(item.actor_id)} · ${e(item.created_at)}</li>`).join('')}</ul><p class="helper">这是配置评审摘要，不构成发布门禁或审批。</p></section>`;
}

function historyPanel(workspace) {
  const selected = workspace.readOnlySnapshot || workspace.selectedCandidate;
  const stable = workspace.stableVersions || [];
  const candidates = workspace.candidates || [];
  return `<section class="r1-history">${comparisonPicker(workspace)}<div class="item-heading"><h3>稳定历史（只读）</h3>${action('r1-refresh', '刷新历史', '', workspace.busy)}</div>${stable.length ? `<ul class="config-list">${stable.map(item => `<li><div class="item-heading"><strong>${e(item.version_id)}</strong><span class="muted">${e(item.content_hash?.slice(0, 12) || '')}</span></div><p class="helper">${e(item.created_at || '')}</p>${action('r1-open-stable', '只读查看', `data-version-id="${e(item.version_id)}"`, workspace.busy)}</li>`).join('')}</ul>` : '<p class="muted">当前服务端尚无稳定快照。</p>'}
    <h3>冻结候选</h3>${candidates.length ? `<ul class="config-list">${candidates.map(item => `<li><div class="item-heading"><strong>${e(item.candidate_id)}</strong><span>${e(item.status || '候选')}</span></div><p class="helper">来源 revision r${e(item.source_revision)} · ${e(item.content_hash?.slice(0, 12) || '')}</p>${action('r1-open-candidate', '查看字段差异', `data-candidate-id="${e(item.candidate_id)}"`, workspace.busy)}</li>`).join('')}</ul>` : '<p class="muted">尚无冻结候选。</p>'}
    ${selected ? `<section class="r1-snapshot"><div class="item-heading"><h3>${workspace.readOnlySnapshot ? `稳定版本 ${e(selected.version_id)} · 只读` : `候选 ${e(selected.candidate_id)} · 未批准`}</h3>${action('r1-close-snapshot', '关闭')}</div>${!workspace.readOnlySnapshot ? releaseChecklist(workspace.releaseChecklist) : ''}${!workspace.readOnlySnapshot ? advisoryReviewSummary(selected.review_summary) : ''}${selected.config ? `<p class="helper">配置快照</p><pre class="r1-json-readonly">${e(stringify(selected.config))}</pre>` : ''}${selected.diff ? `<h4>字段级差异</h4><ul class="r1-diff">${selected.diff.map(item => `<li><code>${e(item.path)}</code><div><span>之前</span><pre>${e(item.before_exists === false ? '字段不存在' : stringify(item.before))}</pre></div><div><span>之后</span><pre>${e(item.after_exists === false ? '字段不存在' : stringify(item.after))}</pre></div></li>`).join('') || '<li class="muted">没有字段差异。</li>'}</ul>` : ''}<p class="notice">冻结候选不是审批、稳定版本或发布。</p></section>` : ''}</section>`;
}

function comparisonPicker(workspace) {
  const options = [
    ...(workspace.stableVersions || []).map(item => ({ value: `stable:${item.version_id}`, label: `稳定版本 ${item.version_id}` })),
    ...(workspace.candidates || []).map(item => ({ value: `candidate:${item.candidate_id}`, label: `候选 ${item.candidate_id}` })),
  ];
  const selection = workspace.comparisonSelection || {};
  const select = (side, label) => `<div class="field"><label for="r1-compare-${side}">${label}</label><select id="r1-compare-${side}" class="control" data-r1-comparison="${side}" ${workspace.busy ? 'disabled' : ''}><option value="">选择版本或候选</option>${options.map(item => `<option value="${e(item.value)}" ${selection[side] === item.value ? 'selected' : ''}>${e(item.label)}</option>`).join('')}</select></div>`;
  return `<section class="r1-comparison-picker" aria-label="版本比较"><h3>选择两个版本比较</h3><div class="r1-comparison-fields">${select('before', '比较基准（之前）')}${select('after', '比较目标（之后）')}${action('r1-compare', workspace.comparisonStatus === 'loading' ? '正在比较…' : '查看差异', '', workspace.busy || workspace.comparisonStatus === 'loading' || !selection.before || !selection.after)}</div><p class="helper">稳定版本与冻结候选均可选；比较仅供审阅，未保存草稿会保留。</p>${workspace.comparisonError ? `<p class="field-error" role="alert">${e(workspace.comparisonError)}</p>` : ''}</section>`;
}

function comparisonPanel(workspace) {
  const comparison = workspace.comparison;
  if (!comparison) return '';
  const label = item => `${item.kind === 'stable' ? '稳定版本' : '候选'} ${item.id}`;
  return `<section class="r1-comparison-result" aria-label="所选版本差异"><div class="item-heading"><h3>${e(label(comparison.before))} → ${e(label(comparison.after))} · 只读比较</h3>${action('r1-close-comparison', '退出比较')}</div><p class="helper">配置分区展示比较目标；流程画布单独标出节点、端口、边与优先级变化。</p>${objectDiffPanel(comparison.object_diff, `${label(comparison.before)} → ${label(comparison.after)}`, false)}<details><summary>字段级差异 · ${comparison.diff.length} 项</summary><ul class="r1-diff">${comparison.diff.map(item => `<li><code>${e(item.path)}</code><div><span>之前</span><pre>${e(item.before_exists === false ? '字段不存在' : diffValue(item.before))}</pre></div><div><span>之后</span><pre>${e(item.after_exists === false ? '字段不存在' : diffValue(item.after))}</pre></div></li>`).join('') || '<li class="muted">没有字段差异。</li>'}</ul></details></section>`;
}

function releaseChecklist(checklist) {
  if (!checklist) return '<section class="notice"><strong>发布预检尚未读取</strong></section>';
  const progress = checklist.progress || {};
  const statusText = { passed: '通过', failed: '未通过', pending: '待验证' };
  return `<section class="r1-release-checklist"><div class="item-heading"><h4>发布前检查</h4><span>${e(progress.passed || 0)}/${e(progress.total || 0)} 项通过</span></div><p class="helper">通过 ${e(progress.passed || 0)} · 未通过 ${e(progress.failed || 0)} · 待验证 ${e(progress.pending || 0)}</p><ul class="config-list">${(checklist.checks || []).map(check => `<li><div class="item-heading"><strong>${e(check.label)}</strong><span>${e(statusText[check.status] || check.status)}</span></div><p class="helper">${e(typeof check.detail === 'string' ? check.detail : JSON.stringify(check.detail))}</p></li>`).join('')}</ul><p class="notice ${checklist.ready ? '' : 'notice-warning'}">${checklist.ready ? '检查项已齐备；本版本仍未开放批准或发布。' : '尚有检查未完成；此清单仅供查看，当前不能批准或发布。'}</p></section>`;
}

function configTab(workspace) {
  const config = displayedConfig(workspace) || {};
  const persona = config.persona || {};
  if (workspace.activeTab === 'reception') return receptionSettings(workspace, config);
  if (workspace.activeTab === 'persona') {
    return `<div class="stack r1-editor-grid"><p class="helper">以下是 R1 服务端 schema 中明确映射的人设字段；未映射字段会随配置保留并在只读区显示。</p>${control('名称', 'persona.name', persona.name, workspace)}${control('服务目标', 'persona.goal', persona.goal, workspace, { multiline: true })}${control('服务对象', 'persona.audience', persona.audience, workspace)}${control('欢迎语', 'persona.greeting', persona.greeting, workspace, { multiline: true })}${control('回答范围', 'persona.scope', persona.scope, workspace, { multiline: true })}${control('资料不足时', 'persona.fallback', persona.fallback, workspace, { multiline: true })}${jsonEditor('业务字段目录', 'persona.fields', persona.fields || {}, workspace, '用于 G0、HardRule 与 Unit 的确定性字段引用。保持未识别字段原样。')}${persona.entry_unit_ids !== undefined ? jsonEditor('入口单元 ID', 'persona.entry_unit_ids', persona.entry_unit_ids, workspace, '路由单元入口声明；需与流程中的 unit_id 对应。') : ''}</div>`;
  }
  if (workspace.activeTab === 'flow') {
    const formatHint = config.orchestration?.schema_version === 'unit-graph-v1'
      ? '图版本支持嵌套单元和图外并发能力；未支持的运行能力会在冻结时指出具体字段。'
      : '此版本使用 R1 清单格式，body 保持为空对象；concurrent 需显式图版本。';
    return `<div class="stack"><div data-orchestration><p class="helper">正在载入流程投影…</p></div><details ${workspace.jsonErrors?.units ? 'open' : ''}><summary>原始 Unit 清单与修复</summary>${jsonEditor('Unit 清单', 'units', config.units ?? [], workspace, formatHint)}</details></div>`;
  }
  if (workspace.activeTab === 'boundary') {
    return `<div class="stack"><div class="notice notice-warning"><strong>边界修改受服务端字段校验</strong><p>HardRule 使用 when / verdict / enforce 合同；不得通过此编辑器授予真实业务权限。</p></div>${jsonEditor('G0 确定性闸门', 'g0_gates', config.g0_gates || [], workspace, '条件命中后 route_to 为 block、suspend 或一个已声明 Unit ID。')}${jsonEditor('HardRule v0.2', 'hard_rules', config.hard_rules || [], workspace, 'verdict.type 为 deny / require / stop / dedupe；enforce 包含 scope、reason、priority、customer_facing、severity 与有效期。')}</div>`;
  }
  if (workspace.activeTab === 'task') {
    return `<div class="stack"><div class="notice notice-warning"><strong>Task 蓝图暂时只读</strong><p>蓝图会随专家版本冻结，但 TaskItem 撤销恢复及主体/用途隔离合同尚未定版；本轮保留已存字段，不通过页面制造未批准的执行语义。</p></div><pre class="r1-json-readonly">${e(stringify(config.task_blueprints || []))}</pre></div>`;
  }
  return historyPanel(workspace);
}

function receptionSettings(workspace, config) {
  const policy = config.ai_reception ?? {}, options = workspace.receptionOptions || {};
  const disabled = currentReadOnly(workspace) || workspace.busy;
  if (!policy || typeof policy !== 'object' || Array.isArray(policy) || !Array.isArray(policy.sources ?? [])
      || (policy.mode !== undefined && !['always', 'offline'].includes(policy.mode))
      || (policy.sources || []).some(ref => !ref || typeof ref.source_id !== 'string' || typeof ref.content_hash !== 'string')
      || !Array.isArray(policy.faq_suggestions ?? [])
      || !Array.isArray(policy.handoff_phrases ?? [])
      || (policy.handoff_phrases || []).some(phrase => typeof phrase !== 'string')
      || (policy.faq_suggestions || []).some(item => !item || typeof item.question !== 'string'
        || typeof item.source_id !== 'string' || typeof item.content_hash !== 'string')) {
    return jsonEditor('AI 接待配置', 'ai_reception', policy, workspace, '当前结构不能表单化，原文保持不变。修复后再读取。');
  }
  const selected = policy.sources || [], sources = options.sources || [], suggestions = policy.faq_suggestions || [];
  const pinned = new Map(selected.map(item => [item.source_id, item.content_hash]));
  const missing = selected.filter(ref => !sources.some(source => source.source_id === ref.source_id && source.content_hash === ref.content_hash && source.state === 'ready'));
  const availableSources = selected.map(ref => sources.find(source => source.source_id === ref.source_id
    && source.content_hash === ref.content_hash && source.state === 'ready')).filter(Boolean);
  const invalidSuggestions = suggestions.filter(item => !selected.some(ref => ref.source_id === item.source_id
    && ref.content_hash === item.content_hash));
  const phraseError = viewingSnapshot(workspace) ? null : workspace.jsonErrors?.['ai_reception.handoff_phrases'];
  const phraseInput = viewingSnapshot(workspace) ? null : workspace.jsonInputs?.['ai_reception.handoff_phrases'];
  const faqRows = suggestions.map((item, index) => {
    const source = sources.find(candidate => candidate.source_id === item.source_id
      && candidate.content_hash === item.content_hash && candidate.state === 'ready');
    const sourceName = source?.display_name || '来源版本不可用';
    return `<li class="r1-faq-row"><div class="r1-faq-copy"><input class="control input r1-control" data-r1-bind="ai_reception.faq_suggestions.${index}.question" value="${e(item.question)}" aria-label="常见问题 ${index + 1}" ${disabled ? 'disabled' : ''}><small class="field-error" data-r1-faq-edit-error hidden></small><small>${e(sourceName)} · ${e(item.source_id)} · ${e(item.content_hash.slice(0, 12))}</small></div>${action('r1-remove-faq-suggestion', '移除', `data-index="${index}"`, disabled)}</li>`;
  }).join('');
  return `<section class="stack r1-reception-settings" aria-label="AI 客服接待配置"><h3>AI 接待与授权资料</h3><p class="helper">配置随候选版本冻结。保存草稿不会改变当前访客入口；未启用时消息仍进入人工收件箱。</p>
    <label class="r1-reception-choice"><input type="checkbox" data-r1-bind="ai_reception.enabled" ${policy.enabled ? 'checked' : ''} ${disabled ? 'disabled' : ''}>启用 AI 接待</label>
    <div class="field"><label for="r1-reception-mode">接待时机</label><select id="r1-reception-mode" class="control" data-r1-bind="ai_reception.mode" ${disabled ? 'disabled' : ''}><option value="always" ${policy.mode !== 'offline' ? 'selected' : ''}>始终接待</option><option value="offline" ${policy.mode === 'offline' ? 'selected' : ''}>仅人工离线时接待</option></select><p class="helper">离线时间依据此版本 Widget 的时区与时段。请求人工后自动答复停止。</p></div>
    ${control('固定模型 ID', 'ai_reception.model_id', policy.model_id || '', workspace, { help: '填入服务端配置的模型 ID。模型连接改变后，旧版本会停止自动答复，需重新验收。' })}
    <div class="field"><label for="r1-handoff-phrases">显式转人工短语</label><textarea id="r1-handoff-phrases" class="control r1-control" rows="3" data-r1-bind="ai_reception.handoff_phrases" aria-describedby="r1-handoff-help r1-handoff-error" aria-invalid="${Boolean(phraseError)}" ${disabled ? 'disabled' : ''}>${e(phraseInput ?? (policy.handoff_phrases || []).join('\n'))}</textarea><p id="r1-handoff-help" class="helper">每行一条，最多 20 条、每条 100 个字符。访客消息包含任一短语时直接请求人工，忽略大小写，不调用模型。留空时仅按访客按钮或模型建议转人工。</p><p id="r1-handoff-error" class="field-error" data-r1-handoff-error ${phraseError ? '' : 'hidden'}>${e(phraseError || '')}</p></div>
    <p role="status">${options.model?.configured ? `服务端已配置：${e(options.model.model_id)}。配置存在不代表连接测试通过。` : options.status === 'loading' ? '正在读取模型和资料…' : '尚未读取到有效模型连接；凭据只由服务端保存。'}</p>
    ${action('r1-reception-resources', '重新读取模型与资料', '', options.status === 'loading')}${options.error ? `<p role="alert" class="field-error">${e(options.error)}</p>` : ''}
    <h4>允许答疑的资料</h4><p class="helper">只选择已就绪的授权来源；采用当前内容哈希。后续新增资料不会自动加入这个版本。</p>
    ${sources.filter(source => source.state === 'ready').map(source => `<label class="r1-reception-choice"><input type="checkbox" data-r1-source="${e(source.source_id)}" ${pinned.get(source.source_id) === source.content_hash ? 'checked' : ''} ${disabled ? 'disabled' : ''}><span>${e(source.display_name)}<small>${e(source.source_id)} · ${e(source.content_hash?.slice(0, 12) || '缺内容哈希')}</small></span></label>`).join('') || '<p class="helper">暂无可选的已就绪资料。先通过知识来源摄入并核验，再重新读取。</p>'}
    ${missing.length ? `<p class="notice notice-warning">已保存引用中有 ${missing.length} 项当前不可核验。内容保持原样，请重新选择版本或在下方移除失效引用。</p>` : ''}
    <section class="r1-faq-editor" aria-label="FAQ 问题建议"><h4>常见问题建议 <small>${suggestions.length}/8</small></h4>
      ${suggestions.length ? `<ul class="r1-faq-list">${faqRows}</ul>` : '<p class="muted">暂无问题建议。</p>'}
      ${invalidSuggestions.length ? `<p class="notice notice-warning" role="status">有 ${invalidSuggestions.length} 项建议未引用当前允许的资料版本。</p>` : ''}
      <div class="r1-faq-add"><div class="field"><label for="r1-faq-question">问题</label><input class="control input" id="r1-faq-question" data-r1-faq-question ${disabled || suggestions.length >= 8 ? 'disabled' : ''}></div>
        <div class="field"><label for="r1-faq-source">依据资料</label><select class="control" id="r1-faq-source" data-r1-faq-source ${disabled || !availableSources.length || suggestions.length >= 8 ? 'disabled' : ''}><option value="">选择资料</option>${availableSources.map(source => `<option value="${e(source.source_id)}">${e(source.display_name)}</option>`).join('')}</select></div>
        ${action('r1-add-faq-suggestion', '添加', '', disabled || !availableSources.length || suggestions.length >= 8)}
      </div><p class="field-error" role="status" data-r1-faq-error hidden></p>
    </section>
    <details><summary>固定来源与原始配置</summary>${jsonEditor('AI 接待配置', 'ai_reception', policy, workspace, '公开页面只显示接待状态，不获得来源全文、Prompt 或模型凭据。')}</details>
  </section>`;
}

function unknownConfig(config = {}) {
  const known = new Set(['persona', 'units', 'g0_gates', 'hard_rules', 'task_blueprints', 'ai_reception']);
  const unknown = Object.fromEntries(Object.entries(config).filter(([key]) => !known.has(key)));
  const persona = config.persona || {};
  const knownPersona = new Set(['name', 'role', 'goal', 'audience', 'greeting', 'scope', 'fallback', 'fields', 'entry_unit_ids']);
  const unknownPersona = Object.fromEntries(Object.entries(persona).filter(([key]) => !knownPersona.has(key)));
  if (!Object.keys(unknown).length && !Object.keys(unknownPersona).length) return '';
  return `<details class="r1-unknown"><summary>未映射字段（保留原样，只读）</summary>${Object.keys(unknown).length ? `<h3>配置根字段</h3><pre class="r1-json-readonly">${e(stringify(unknown))}</pre>` : ''}${Object.keys(unknownPersona).length ? `<h3>人设字段</h3><pre class="r1-json-readonly">${e(stringify(unknownPersona))}</pre>` : ''}<p class="helper">保存时保留这些字段；此工作面不会转换或丢弃它们。</p></details>`;
}

function currentReadOnly(workspace) {
  if (viewingSnapshot(workspace)) return true;
  return workspace.status !== 'ready';
}

export function renderR1Configuration(ctx) {
  const workspace = ctx.r1Configuration?.state;
  if (!workspace) return '<section class="notice notice-danger">R1 配置工作面尚未初始化。</section>';
  const dirty = Boolean(workspace.draft && workspace.editorConfig && (stringify(workspace.draft.config) !== stringify(workspace.editorConfig) || Object.keys(workspace.jsonInputs || {}).length));
  const title = workspace.comparison ? '版本比较（只读）' : workspace.readOnlySnapshot ? `稳定版本 ${workspace.readOnlySnapshot.version_id}` : workspace.selectedCandidate ? `候选 ${workspace.selectedCandidate.candidate_id}` : workspace.draft ? `草稿 r${workspace.draft.revision}` : '服务端配置';
  const disabled = currentReadOnly(workspace) || workspace.busy;
  const statusText = {
    idle: '尚未连接服务端', loading: '正在读取配置服务…', ready: dirty ? '有未保存修改' : '与服务端草稿一致',
    'no-draft': '服务端暂无草稿', error: '配置服务读取失败', conflict: 'revision 冲突待处理',
  }[workspace.status] || workspace.status;
  const configActions = workspace.draft && !viewingSnapshot(workspace)
    ? `<div class="button-group">${action('r1-save', '保存草稿', '', disabled || !dirty || Object.keys(workspace.jsonErrors || {}).length > 0, true)}${action('r1-validate', '服务端校验', '', disabled || dirty)}${action('r1-freeze', '冻结候选', '', disabled || dirty)}${dirty ? '<p class="helper">先保存当前修改，再运行服务端校验或冻结候选。</p>' : ''}</div>`
    : '';
  const noDraft = workspace.status === 'no-draft'
    ? `<section class="notice"><strong>没有服务端草稿</strong><p>选择一个已登记的稳定版本创建草稿。尚无稳定版本时，通过受信任 owner 的 CLI 导入经过确认的快照。</p>${workspace.stableVersions?.length ? `<div class="button-group">${workspace.stableVersions.map(item => action('r1-create-draft', `基于 ${e(item.version_id)} 创建草稿`, `data-version-id="${e(item.version_id)}"`, workspace.busy, true)).join('')}</div>` : '<p class="helper">稳定快照列表为空；此页不会把本地 demo 自动写入服务端。</p>'}</section>` : '';
  const error = workspace.error ? `<section class="notice notice-danger" role="alert"><strong>${e(workspace.error.message)}</strong>${workspace.error.code ? `<p class="helper">错误码：${e(workspace.error.code)}</p>` : ''}${workspace.status === 'error' ? '<p class="helper">请确认已运行 `loomrise config serve`，并且本机 principal 已授权当前专家。失败时没有本地写入回退。</p>' : ''}</section>` : '';
  const validation = workspace.validation ? `<section class="notice ${workspace.validation.valid ? '' : 'notice-danger'}" role="status"><strong>${workspace.validation.valid ? '服务端校验通过' : '服务端校验发现问题'}</strong><p>校验 revision r${e(workspace.validation.revision)}。</p>${issueList(workspace.validation.issues)}</section>` : '';
  const conflict = conflictPanel(workspace);
  const config = displayedConfig(workspace);
  const history = workspace.history || { past: [], future: [] };
  const historyDisabled = disabled || Object.keys(workspace.jsonErrors || {}).length > 0;
  const historyErrors = Object.keys(workspace.jsonErrors || {}).length > 0;
  const historyHelp = workspace.activeTab === 'flow'
    ? `撤销覆盖所有分区（≤100 步）；保存、重新读取或处理冲突后重开历史。${historyErrors ? '请先修复 JSON 原文。' : ''}`
    : `跨分区撤销已应用的修改；保存、重新读取或处理冲突后开始新历史，最多保留 100 步。${historyErrors ? '请先修复 JSON 原文，再撤销或重做。' : ''}`;
  const historyControls = workspace.draft && !viewingSnapshot(workspace) ? `<section class="r1-draft-history" aria-label="草稿撤销历史"><div class="button-group">${action('r1-undo', '撤销修改', '', historyDisabled || !history.past.length)}${action('r1-redo', '重做修改', '', historyDisabled || !history.future.length)}</div><p class="helper">${historyHelp}</p></section>` : '';
  const tabsHtml = tabs.map(([id, label]) => `<button class="btn btn-ghost r1-tab ${workspace.activeTab === id ? 'is-active' : ''}" type="button" data-action="r1-tab" data-tab="${id}" aria-pressed="${workspace.activeTab === id}">${label}</button>`).join('');
  return `<section class="r1-service-workspace"><header class="r1-service-header"><div><p class="eyebrow">R1 · 共用配置服务</p><h2>服务端版本工作面</h2><p class="muted">${e(ctx.agent?.name || workspace.agentId)} · ${e(title)} · ${e(statusText)}</p></div><div class="button-group">${action('r1-refresh', '重新读取', '', workspace.busy)}${workspace.readOnlySnapshot || workspace.selectedCandidate ? action('r1-close-snapshot', '返回草稿工作面') : ''}</div></header>
    ${error}${conflict}${validation}${noDraft}
    ${workspace.refreshPending ? `<section class="notice notice-warning" role="alert"><strong>未保存内容已保留</strong><p>重新读取会舍弃本地配置和 JSON 原文，并清空撤销历史。</p><div class="button-group">${action('r1-cancel-refresh', '继续编辑')}${action('r1-discard-refresh', '舍弃本地修改并重新读取')}</div></section>` : ''}
    ${workspace.draft && !viewingSnapshot(workspace) ? `<section class="r1-server-metadata"><span>服务端 revision <strong>r${e(workspace.draft.revision)}</strong></span><span>基准版本 <strong>${e(workspace.draft.base_version_id || '未登记')}</strong></span><span>更新时间 <strong>${e(workspace.draft.updated_at || '')}</strong></span></section>` : ''}
    ${historyControls}${comparisonPanel(workspace)}
    ${!viewingSnapshot(workspace) ? objectDiffPanel(workspace.draft?.object_diff, `最近一次保存：r${workspace.draft?.revision - 1} → r${workspace.draft?.revision}${dirty ? '（另有未保存修改，不含在本回执中）' : ''}`) : objectDiffPanel(workspace.selectedCandidate?.object_diff, '冻结候选与其基准稳定版本')}
    ${config || workspace.activeTab === 'history' ? `<div class="r1-tabs" role="group" aria-label="服务端配置分区">${tabsHtml}</div><section class="r1-editor" aria-label="${e(workspace.activeTab)}">${configTab(workspace)}${config && workspace.activeTab !== 'history' ? unknownConfig(config) : ''}${configActions}</section>` : ''}
    ${workspace.status === 'idle' ? '<p class="helper">打开此工作面后将读取共用配置服务；本地示例和原型存储不会导入或覆盖服务端数据。</p>' : ''}
    <details class="r1-api-detail"><summary>连接状态与范围</summary><dl class="definition-list"><div><dt>API</dt><dd><code>${e(ctx.r1Configuration.client.origin)}</code></dd></div><div><dt>数据源</dt><dd>SQLite 配置服务；浏览器仅发送当前授权专家 ID，角色和租户由服务端 principal 决定。</dd></div><div><dt>本地演示状态</dt><dd>专家首页、知识来源、测试、上线与运行记录仍由浏览器原型状态驱动，不属于此 R1 配置 API。</dd></div></dl></details>
  </section>`;
}
