const workspacePages = new Set(['agents', 'create', 'materials', 'connections', 'deployment']);

export function routeScope(page) {
  return workspacePages.has(page) ? 'workspace' : 'agent';
}

export function navigationHash(state) {
  const page = state.ui.page;
  const query = new URLSearchParams();
  if (routeScope(page) === 'agent' && state.selectedAgentId) query.set('agent', state.selectedAgentId);
  if (page === 'configuration' && state.ui.section) query.set('section', state.ui.section);
  return `#/${page}${query.size ? `?${query}` : ''}`;
}

export function resolveNavigation(hash, state, pages) {
  const [requestedPage, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const page = pages.includes(requestedPage) ? requestedPage : 'agents';
  const values = new URLSearchParams(query);
  if (routeScope(page) === 'workspace') return { page };
  const agentId = values.has('agent') ? values.get('agent') : state.selectedAgentId;
  if (!state.agents.some(agent => agent.id === agentId)) return { page: 'agents', warning: '链接中的专家不存在，请从工作区重新选择。' };
  return { page, agentId, section: page === 'configuration' ? values.get('section') || undefined : undefined };
}

export function createNavigationHistory({ store, location, history, pages }) {
  let restoring = false;
  let currentHash = null;
  function sync() {
    if (restoring) return;
    const hash = navigationHash(store.state);
    if (hash === currentHash) return;
    history[currentHash === null ? 'replaceState' : 'pushState'](null, '', hash);
    currentHash = hash;
  }
  function restore() {
    if (location.hash === currentHash) return;
    const target = resolveNavigation(location.hash, store.state, pages);
    restoring = true;
    try {
      if (target.agentId && target.agentId !== store.state.selectedAgentId) store.dispatch('select-agent', { id: target.agentId });
      store.dispatch('navigate', { page: target.page, section: target.section });
      if (target.warning) store.dispatch('visitor-notice', { text: target.warning });
    } finally { restoring = false; }
    const hash = navigationHash(store.state);
    if (location.hash !== hash) history.replaceState(null, '', hash);
    currentHash = hash;
  }
  return { sync, restore };
}
