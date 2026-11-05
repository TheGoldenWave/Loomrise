const clone = value => structuredClone(value);
const emptyContact = () => ({ title: '联系页', description: '', blocks: [] });

function setAt(root, path, value) {
  let target = root;
  for (const key of path.slice(0, -1)) target = target[key];
  target[path.at(-1)] = value;
}

export function createContactWorkspace({ client, onChange = () => {}, isReadOnly = () => false } = {}) {
  const state = { agentId: null, status: 'idle', revision: 0, contact: emptyContact(), base: null, dirty: false, conflict: null, templates: [], schema: null, error: null,
    entryId: '', entry: null, entryBusy: false, entryError: null, livePage: null,
    generationBrief: '', generationTemplateId: '', proposal: null, generationError: null };
  let generation = 0;
  let blockSequence = 0;
  let proposalBaseline = null;
  const changed = () => {
    const content = JSON.stringify(state.contact);
    state.dirty = content !== JSON.stringify(state.base);
    if (state.proposal && (state.proposal.base_revision !== state.revision || proposalBaseline !== content)) {
      state.proposal = null; proposalBaseline = null;
      state.generationError = new Error('页面内容或版本已改变，请重新生成候选。');
    }
    onChange(state);
  };
  function writable() {
    return !isReadOnly() && state.status === 'ready' && !state.conflict
      && state.contact && typeof state.contact === 'object' && !Array.isArray(state.contact)
      && Array.isArray(state.contact.blocks)
      && (!Object.hasOwn(state.contact, 'schema_version') || state.contact.schema_version === 'contact-page-v1');
  }
  async function load(agentId) {
    const current = ++generation;
    Object.assign(state, { entryId: '', entry: null, entryBusy: false, entryError: null, livePage: null,
      generationBrief: '', generationTemplateId: '', proposal: null, generationError: null });
    proposalBaseline = null;
    state.agentId = agentId; state.status = 'loading'; state.error = null; state.conflict = null; changed();
    try {
      const [draft, templates] = await Promise.all([
        client.request('draft.get', { agent_id: agentId }),
        client.customerRequest('contact.templates', { agent_id: agentId }),
      ]);
      if (current !== generation) return false;
      state.revision = draft.revision; state.contact = clone(Object.hasOwn(draft.config || {}, 'contact') ? draft.config.contact : emptyContact());
      state.base = clone(state.contact); state.templates = templates.items || []; state.schema = templates.schema || null; state.status = 'ready'; changed(); return true;
    } catch (error) { if (current === generation) { state.status = 'error'; state.error = error; changed(); } return false; }
  }
  const kindFor = block => state.schema?.block_types?.find(kind => kind.type === block?.type);
  const validIndex = (array, index) => Array.isArray(array) && Number.isInteger(index) && index >= 0 && index < array.length;
  function edit(path, value) {
    if (!writable() || !Array.isArray(path) || typeof value !== 'string') return false;
    let allowed = path.length === 1 && ['title', 'description'].includes(path[0]);
    if (path[0] === 'blocks' && validIndex(state.contact.blocks, path[1])) {
      const block = state.contact.blocks[path[1]];
      if (!block || typeof block !== 'object' || Array.isArray(block)) return false;
      allowed ||= path.length === 3 && ['title', 'body'].includes(path[2]);
      allowed ||= path.length === 5 && path[2] === 'items' && validIndex(block.items, path[3])
        && kindFor(block)?.item_fields.includes(path[4]);
    }
    if (!allowed) return false;
    if (path.length === 5 && !kindFor(state.contact.blocks[path[1]]).required_item_fields.includes(path[4]) && value === '') {
      delete state.contact.blocks[path[1]].items[path[3]][path[4]];
    } else setAt(state.contact, path, value);
    changed(); return true;
  }
  function addBlock(type = 'text') {
    const kind = state.schema?.block_types?.find(item => item.type === type);
    if (!writable() || !kind || !Array.isArray(state.contact.blocks)
      || state.contact.blocks.length >= (state.schema?.max_blocks || 64)) return false;
    let id;
    do { id = `block-${++blockSequence}`; } while (state.contact.blocks.some(block => block?.id === id));
    state.contact.blocks.push({ id, type, title: kind.label, body: '', items: [] }); changed(); return true;
  }
  function addItem(blockIndex) {
    if (!writable() || !validIndex(state.contact.blocks, blockIndex)) return false;
    const block = state.contact.blocks[blockIndex];
    if (!kindFor(block)?.item_fields.length) return false;
    block.items ||= [];
    if (block.items.length >= (state.schema?.max_items || 50)) return false;
    block.items.push({}); changed(); return true;
  }
  function removeBlock(index) {
    if (!writable() || !validIndex(state.contact.blocks, index)) return false;
    state.contact.blocks.splice(index, 1); changed(); return true;
  }
  function moveBlock(index, offset) {
    if (!writable() || ![-1, 1].includes(offset) || !validIndex(state.contact.blocks, index)
      || !validIndex(state.contact.blocks, index + offset)) return false;
    const block = state.contact.blocks.splice(index, 1)[0]; state.contact.blocks.splice(index + offset, 0, block); changed(); return true;
  }
  function removeItem(index, itemIndex) {
    if (!writable() || !validIndex(state.contact.blocks, index) || !validIndex(state.contact.blocks[index].items, itemIndex)) return false;
    state.contact.blocks[index].items.splice(itemIndex, 1); changed(); return true;
  }
  function applyTemplate(id) { if (!writable()) return false; const template = state.templates.find(item => item.id === id); if (!template) return false; state.contact = clone(template.contact); changed(); return true; }
  function setGenerationBrief(value) {
    if (!writable() || typeof value !== 'string' || value.length > 4000) return false;
    state.generationBrief = value; state.proposal = null; state.generationError = null; proposalBaseline = null;
    changed(); return true;
  }
  function setGenerationTemplate(id) {
    if (!writable() || (id !== '' && !state.templates.some(template => template.id === id))) return false;
    state.generationTemplateId = id; state.proposal = null; state.generationError = null; proposalBaseline = null;
    changed(); return true;
  }
  async function generate() {
    if (!writable() || !state.generationBrief.trim() || state.generationBrief.length > 4000) return false;
    const current = generation;
    const revision = state.revision;
    const baseline = JSON.stringify(state.contact);
    const payload = { agent_id: state.agentId, expected_revision: revision, brief: state.generationBrief.trim(),
      ...(state.generationTemplateId ? { template_id: state.generationTemplateId } : {}) };
    state.status = 'generating'; state.proposal = null; state.generationError = null; proposalBaseline = null; changed();
    try {
      const result = await client.customerRequest('contact.generate', payload);
      if (current !== generation) return false;
      if (result?.state !== 'proposal' || result.base_revision !== revision || !result.contact
        || typeof result.contact !== 'object' || !Array.isArray(result.contact.blocks)
        || typeof result.contact.title !== 'string' || !result.contact.title.trim()
        || (result.contact.schema_version && result.contact.schema_version !== 'contact-page-v1')) {
        throw Object.assign(new Error('生成结果无法采用，请重新生成或继续手动编辑。'), { code: 'invalid_response' });
      }
      state.proposal = clone(result); proposalBaseline = baseline;
      state.status = 'ready'; changed(); return true;
    } catch (error) {
      if (current !== generation) return false;
      state.generationError = error;
      if (error.code === 'revision_conflict') state.conflict = { error, attempted: clone(state.contact) };
      state.status = state.conflict ? 'conflict' : 'ready'; changed(); return false;
    }
  }
  function adoptProposal() {
    if (!writable() || !state.proposal || state.proposal.base_revision !== state.revision
      || proposalBaseline !== JSON.stringify(state.contact)) return false;
    const contact = clone(state.proposal.contact);
    state.proposal = null; proposalBaseline = null; state.generationError = null; state.contact = contact;
    changed(); return true;
  }
  function discardProposal() {
    if (!writable() || !state.proposal) return false;
    state.proposal = null; proposalBaseline = null; state.generationError = null; changed(); return true;
  }
  async function save() {
    if (!writable() || !state.dirty) return false;
    const current = generation;
    const attempted = clone(state.contact);
    state.status = 'saving'; state.error = null; changed();
    try {
      const result = await client.customerRequest('contact.save', { agent_id: state.agentId, expected_revision: state.revision, contact: attempted });
      if (current !== generation) return false;
      state.revision = result.revision; state.base = clone(result.contact); state.contact = clone(result.contact); state.conflict = null; state.status = 'ready'; changed(); return true;
    } catch (error) {
      if (current !== generation) return false;
      state.error = error;
      state.conflict = error.code === 'revision_conflict' ? { error, attempted } : null;
      state.status = state.conflict ? 'conflict' : 'ready'; changed(); return false;
    }
  }
  function setEntryId(value) {
    if (state.entryBusy || typeof value !== 'string') return false;
    state.entryId = value; state.entry = null; state.livePage = null; state.entryError = null; changed(); return true;
  }
  async function queryEntry() {
    if (!state.agentId || !state.entryId.trim() || state.entryBusy) return false;
    const current = generation;
    state.entryBusy = true; state.entryError = null; changed();
    try {
      const payload = { agent_id: state.agentId, entry_id: state.entryId.trim() };
      const entry = await client.request('release.entry.resolve', payload);
      let livePage = null;
      try { livePage = await client.customerRequest('contact.get', payload); }
      catch (error) { if (error.code !== 'not_found') throw error; }
      if (current !== generation) return false;
      state.entry = entry; state.livePage = livePage; return true;
    } catch (error) {
      if (current === generation) { state.entry = null; state.livePage = null; state.entryError = error.message; }
      return false;
    } finally { if (current === generation) { state.entryBusy = false; changed(); } }
  }
  async function setEntryEnabled(enabled) {
    if (!writable() || state.entryBusy || !state.entryId.trim() || (enabled && !state.entry)) return false;
    const current = generation;
    state.entryBusy = true; state.entryError = null; changed();
    try {
      const result = await client.customerRequest(enabled ? 'contact.enable' : 'contact.disable', {
        agent_id: state.agentId, entry_id: state.entryId.trim(),
        ...(enabled ? { expected_version_id: state.entry.version_id } : {}),
      });
      if (current !== generation) return false;
      state.livePage = enabled ? result : null; return true;
    } catch (error) { if (current === generation) state.entryError = error.message; return false; }
    finally { if (current === generation) { state.entryBusy = false; changed(); } }
  }
  return { state, client, writable, load, edit, addBlock, addItem, removeBlock, moveBlock, removeItem, applyTemplate, save,
    setGenerationBrief, setGenerationTemplate, generate, adoptProposal, discardProposal,
    setEntryId, queryEntry, setEntryEnabled };
}
