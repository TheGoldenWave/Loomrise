import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { createMaterialController } from '../material-controller.js';
import { createVisitorController } from '../visitor-controller.js';
import { releaseAssetURLs } from '../asset-cache.js';

const previousIndexedDB = globalThis.indexedDB;
const previousDocument = globalThis.document;
const previousAnimationFrame = globalThis.requestAnimationFrame;
let activeStorage;
let activeDownloads;

// Delay real cache reads so context changes and missing files remain observable.
const database = {
  transaction() {
    const storage = activeStorage;
    const transaction = {
      objectStore() {
        return {
          get(key) {
            const request = {};
            const pending = {
              key, done: false,
              complete() {
                assert.equal(pending.done, false);
                pending.done = true;
                request.result = storage.files.get(key);
                request.onsuccess?.();
                transaction.oncomplete?.();
              },
            };
            storage.pending.push(pending);
            return request;
          },
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
globalThis.document = {
  createElement(tag) {
    assert.equal(tag, 'a');
    return { click() { activeDownloads.push({ href: this.href, filename: this.download }); } };
  },
};
globalThis.requestAnimationFrame = callback => { callback(); return 0; };
after(() => {
  releaseAssetURLs();
  for (const [name, previous] of [['indexedDB', previousIndexedDB], ['document', previousDocument], ['requestAnimationFrame', previousAnimationFrame]]) {
    if (previous === undefined) delete globalThis[name];
    else globalThis[name] = previous;
  }
});

async function nextRead(storage) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const pending = storage.pending.find(item => !item.done);
    if (pending) return pending;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail('Expected a pending cache read');
}

function setup() {
  releaseAssetURLs();
  const storage = { files: new Map(), pending: [] };
  const downloads = [];
  activeStorage = storage;
  activeDownloads = downloads;
  const store = createStore();
  store.dispatch('navigate', { page: 'trial' });
  const agent = store.currentAgent();
  agent.config.materialPolicy.enabled = true;
  const blobKey = 'visitor-controller-file';
  const filename = 'fictional-poster.png';
  storage.files.set(blobKey, { blob: new Blob(['x'], { type: 'image/png' }), filename, size: 1 });
  store.state.materials.push({
    id: 'visitor-controller-material', revision: 3, title: '虚构课程海报', kind: 'image',
    filename, mimeType: 'image/png', sourceRef: 'fictional:visitor-controller-test',
    rights: true, expires: '2099-12-31', tags: [], scope: 'selected', agentIds: [agent.id],
    canSend: true, autoSendAllowed: true, status: 'published',
    original: { blobKey, size: 1, available: true },
    summary: { text: '用于介绍虚构课程的海报', reviewed: true, origin: 'manual', baseRevision: 3 },
    variants: [{ id: 'original', label: '原件', blobKey, size: 1, available: true, simulated: false }],
  });
  const started = store.dispatch('trial-start', { question: '请发虚构课程海报' });
  assert.equal(started.ok, true);
  assert.equal(store.dispatch('trial-complete', { id: started.value, availableFiles: store.state.ui.pendingTrial.fileRefs }).ok, true);
  const message = store.state.ui.trialMessages.at(-1);
  assert.equal(message.status, 'material_sent');
  const attachment = message.attachments[0];
  const app = { querySelector() { return null; }, querySelectorAll() { return []; } };
  const materialController = createMaterialController({ store, app, render() {}, formKey() { return 'draft'; }, preserveForm() {} });
  const controller = createVisitorController({ store, app, materialController });
  const data = { surface: 'trial', messageId: message.id, id: attachment.id, revision: attachment.revision, variant: attachment.variant };
  return { store, controller, storage, downloads, message, data, blobKey, filename };
}

test('首读成功但下载二次读取缺失时，不发起下载也不登记下载证据', async () => {
  const env = setup();
  const opening = env.controller.click('visitor-attachment-download', env.data);
  (await nextRead(env.storage)).complete();
  const secondRead = await nextRead(env.storage);
  env.storage.files.delete(env.blobKey);
  secondRead.complete();
  assert.equal(await opening, true);
  assert.deepEqual(env.downloads, []);
  assert.deepEqual(env.message.attachmentInteractions, {});
  assert.deepEqual(env.store.state.runs[0].attachmentInteractions, {});
  assert.match(env.store.state.ui.toast.text, /原文件已不可用/);
});

test('下载二次读取期间切换专家，迟到文件不能触发下载或交互证据', async () => {
  const env = setup();
  const opening = env.controller.click('visitor-attachment-download', env.data);
  (await nextRead(env.storage)).complete();
  const secondRead = await nextRead(env.storage);
  assert.equal(env.store.dispatch('create', { name: '另一位虚构专家' }).ok, true);
  secondRead.complete();
  assert.equal(await opening, true);
  assert.deepEqual(env.downloads, []);
  assert.deepEqual(env.message.attachmentInteractions, {});
  assert.deepEqual(env.store.state.runs[0].attachmentInteractions, {});
});

test('两次缓存读取与上下文核验通过后才发起下载并保存独立证据', async () => {
  const env = setup();
  const opening = env.controller.click('visitor-attachment-download', env.data);
  (await nextRead(env.storage)).complete();
  (await nextRead(env.storage)).complete();
  assert.equal(await opening, true);
  assert.equal(env.downloads.length, 1);
  assert.equal(env.downloads[0].filename, env.filename);
  assert.match(env.downloads[0].href, /^blob:/);
  const key = `${env.data.id}:${env.data.revision}:${env.data.variant}`;
  assert.equal(typeof env.message.attachmentInteractions[key].downloadStartedAt, 'string');
  assert.deepEqual(env.store.state.runs[0].attachmentInteractions, env.message.attachmentInteractions);
  assert.equal(env.message.delivery, 'unknown');
  assert.equal(env.store.state.runs[0].resultEvidence.delivered, false);
  assert.equal(env.store.state.runs[0].resultEvidence.resolved, 'unknown');
});
