import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { createMaterialController } from '../material-controller.js';
import { renderMaterialPreview } from '../views/materials.js';

const previousIndexedDB = globalThis.indexedDB;
const previousAnimationFrame = globalThis.requestAnimationFrame;
let activeStorage;

// Delay only the storage boundary; controller, domain and store remain real.
const database = {
  transaction() {
    const storage = activeStorage;
    const transaction = {
      objectStore() {
        const operation = (kind, key, record) => {
          const request = {};
          const pending = {
            kind, key, record, done: false,
            complete() {
              assert.equal(pending.done, false);
              pending.done = true;
              if (kind === 'put') storage.files.set(key, record);
              if (kind === 'delete') storage.files.delete(key);
              request.result = kind === 'get' ? storage.files.get(key) : kind === 'put' ? key : undefined;
              request.onsuccess?.();
              transaction.oncomplete?.();
            },
          };
          storage.pending.push(pending);
          if (kind === 'delete') queueMicrotask(() => pending.complete());
          return request;
        };
        return {
          get: key => operation('get', key),
          put: record => operation('put', record.id, record),
          delete: key => operation('delete', key),
        };
      },
    };
    return transaction;
  },
};

globalThis.indexedDB = {
  open() {
    const request = {};
    queueMicrotask(() => { request.result = database; request.onsuccess?.(); });
    return request;
  },
};
globalThis.requestAnimationFrame = callback => { callback(); return 0; };
after(() => {
  if (previousIndexedDB === undefined) delete globalThis.indexedDB;
  else globalThis.indexedDB = previousIndexedDB;
  if (previousAnimationFrame === undefined) delete globalThis.requestAnimationFrame;
  else globalThis.requestAnimationFrame = previousAnimationFrame;
});

async function pendingOperation(storage, kind, match = () => true) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const pending = storage.pending.find(item => !item.done && item.kind === kind && match(item));
    if (pending) return pending;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail(`Expected a pending ${kind} operation`);
}

function setup() {
  const storage = { files: new Map(), pending: [] };
  activeStorage = storage;
  const store = createStore();
  const controller = createMaterialController({
    store, app: { querySelector() { return null; } }, render() {},
    formKey() { return 'material-draft'; }, preserveForm() {},
  });
  store.subscribe(() => controller.contextChanged());
  controller.contextChanged();
  return { store, controller, storage };
}

function fileInput(file) {
  return { files: [file], matches: () => true, closest: () => ({ dataset: { form: 'material-upsert' } }) };
}

function material(agentId) {
  return {
    id: 'material-controller-fixture', revision: 3, title: '虚构旧物料', kind: 'image',
    filename: 'old.png', mimeType: 'image/png', sourceRef: 'fictional:controller-test',
    rights: true, expires: '2099-12-31', tags: [], usage: '', scope: 'selected', agentIds: [agentId],
    canSend: true, autoSendAllowed: false, status: 'published',
    original: { blobKey: 'old-file', size: 1, available: true },
    summary: { text: '虚构文件简介', reviewed: true, origin: 'manual', baseRevision: 3 },
    processing: { compression: 'none', understanding: 'none' }, history: [],
    variants: [{ id: 'original', label: '原件', blobKey: 'old-file', size: 1, available: true, simulated: false }],
  };
}

test('离开录入解除保存锁定，晚到旧文件不污染新的上传或表单', async () => {
  const { store, controller, storage } = setup();
  store.dispatch('navigate', { page: 'materials' });
  store.dispatch('material-form-toggle');
  store.state.ui.formDrafts = { 'material-draft': { title: '人工名称', description: '人工简介' } };
  const first = controller.change(fileInput(new File(['a'], 'first.png', { type: 'image/png' })));
  const firstWrite = await pendingOperation(storage, 'put');
  assert.equal(store.state.ui.materials.uploadStatus, 'saving');

  store.dispatch('navigate', { page: 'knowledge' });
  assert.equal(store.state.ui.materials.uploadStatus, 'idle');
  store.dispatch('navigate', { page: 'materials' });
  assert.equal(store.state.ui.materials.form, true);
  const second = controller.change(fileInput(new File(['bb'], 'second.png', { type: 'image/png' })));
  const secondWrite = await pendingOperation(storage, 'put', item => item.record.filename === 'second.png');

  firstWrite.complete();
  await first;
  assert.equal(store.state.ui.materials.uploadStatus, 'saving');
  assert.equal(store.state.ui.materials.upload, null);
  assert.equal(storage.files.has(firstWrite.key), false);

  secondWrite.complete();
  await second;
  assert.equal(store.state.ui.materials.uploadStatus, 'ready');
  assert.equal(store.state.ui.materials.upload.filename, 'second.png');
  assert.equal(store.state.ui.materials.upload.blobKey, secondWrite.key);
  assert.deepEqual(store.state.ui.formDrafts['material-draft'], { title: '人工名称', description: '人工简介' });
});

test('旧缓存核验晚到时不把已经替换的原件标记为不可用', async () => {
  const { store, controller, storage } = setup();
  const asset = material(store.currentAgent().id);
  store.state.materials.push(asset);
  const reconciliation = controller.reconcileFiles();
  const oldRead = await pendingOperation(storage, 'get', item => item.key === 'old-file');
  storage.files.set('new-file', { blob: new Blob(['bb']), filename: 'new.png', size: 2 });

  assert.equal(store.dispatch('material-edit', { id: asset.id }).ok, true);
  assert.equal(store.dispatch('material-upload-ready', {
    session: store.state.ui.materials.session,
    meta: { blobKey: 'new-file', filename: 'new.png', mimeType: 'image/png', size: 2, available: true },
  }).ok, true);
  assert.equal(store.dispatch('material-upsert', {
    id: asset.id, title: '虚构新物料', description: '新版简介', sourceRef: 'fictional:controller-test',
    rights: true, expires: '2099-12-31', scope: 'selected', agentIds: [store.currentAgent().id], canSend: true,
  }).ok, true);

  // The old file is missing; that result belongs only to the previous revision.
  oldRead.complete();
  await reconciliation;
  assert.equal(asset.revision, 4);
  assert.equal(asset.filename, 'new.png');
  assert.equal(asset.original.blobKey, 'new-file');
  assert.equal(asset.original.available, true);
  assert.equal(asset.variants[0].available, true);
});

test('历史空 MIME 附件预览保留冻结类型，不借用当前 PDF 元数据', async () => {
  const { store, controller } = setup();
  const current = material(store.currentAgent().id);
  Object.assign(current, { revision: 4, title: '新版 PDF', kind: 'document', filename: 'new.pdf', mimeType: 'application/pdf' });
  current.original.blobKey = 'current-pdf';
  store.state.materials.push(current);
  assert.equal(await controller.click('material-preview', {
    id: current.id, snapshot: 'true', revision: '3', snapshotTitle: '旧版 Markdown',
    filename: 'old.md', kind: 'document', mimeType: '', variant: 'original', blobKey: 'historical-markdown',
  }), true);
  const preview = store.state.ui.materials.preview;
  assert.equal(preview.mimeType, '');
  assert.equal(preview.filename, 'old.md');
  assert.equal(preview.blobKey, 'historical-markdown');
  const html = renderMaterialPreview({ state: store.state });
  assert.match(html, /old\.md · 文件类型未知/);
  assert.match(html, /data-blob-key="historical-markdown"/);
  assert.doesNotMatch(html, /application\/pdf|material-preview-pdf|new\.pdf|新版 PDF/);
});
