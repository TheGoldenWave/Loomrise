let current = null;
let generation = 0;
let modulePromise;

function loadStyles() {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = new URL('../dist/orchestration.css', import.meta.url).href;
    link.onload = resolve;
    link.onerror = () => { link.remove(); reject(new Error('canvas stylesheet unavailable')); };
    document.head.append(link);
  });
}

export function unmountOrchestration() {
  generation += 1;
  current?.();
  current = null;
}

export function updateOrchestration(workspace) {
  current?.update?.(workspace);
}

export async function hydrateOrchestration(container, workspace) {
  if (!container) return;
  const request = ++generation;
  try {
    modulePromise ||= Promise.all([import('../dist/orchestration.js'), loadStyles()])
      .then(([module]) => module).catch(error => { modulePromise = null; throw error; });
    const module = await modulePromise;
    if (request !== generation || !container.isConnected) return;
    current = module.mountOrchestration(container, workspace);
  } catch {
    if (request !== generation || !container.isConnected) return;
    container.textContent = '画布模块未能载入。请运行 npm run build:canvas 后刷新；下方原始清单仍可编辑。';
    container.setAttribute('role', 'alert');
  }
}
