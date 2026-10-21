import { assetObjectURL, readAssetBlob, saveAssetBlob, deleteAssetBlob } from './asset-cache.js';
import { materialKind, materialSendCheck } from './material-domain.js';

const LIMIT = 50 * 1024 * 1024;
export function createMaterialController({ store, app, render, formKey, preserveForm }) {
  let uploadGeneration = 0;
  let hydrationGeneration = 0;
  let sending = false;
  let previousContext;
  const uploadContext = () => {
    const { ui, selectedAgentId } = store.state;
    if (ui.page !== 'materials' || !ui.materials.form || store.readonly()) return null;
    return `${selectedAgentId}:${ui.materials.session}:${ui.materials.editingId || 'new'}`;
  };
  const notice = (text, tone = 'warning') => { store.state.ui.toast = { text, tone }; render(); };
  function contextChanged() {
    const key = uploadContext();
    if (key !== previousContext) {
      uploadGeneration += 1; previousContext = key;
      if (store.state.ui.materials.uploadStatus === 'saving') {
        store.state.ui.materials.uploadStatus = 'idle';
        store.state.ui.materials.error = '录入上下文已变化，旧文件保存已中止；原有表单保留，可重新选择文件。';
      }
    }
  }
  async function upload(input) {
    const file = input.files?.[0]; if (!file) return;
    const form = input.closest('form'); const key = formKey(form);
    const context = uploadContext(); const generation = ++uploadGeneration;
    const session = store.state.ui.materials.session;
    preserveForm(form);
    if (!context) { notice('当前不可录入，请返回可编辑物料库。'); return; }
    const kind = materialKind(file.name, file.type);
    if (!kind) { notice('请选择支持的图片、视频或文档；本轮不载入 SVG、HTML 或可执行文件。'); return; }
    if (!file.size || file.size > LIMIT) { notice('本地演示接受大于 0 且不超过 50 MB 的文件；未登记或上传。'); return; }
    const blobKey = `material-file-${crypto.randomUUID()}`;
    store.state.ui.materials.uploadStatus = 'saving'; store.state.ui.materials.error = ''; render();
    try {
      await saveAssetBlob(blobKey, file);
      if (generation !== uploadGeneration || context !== uploadContext()) { await deleteAssetBlob(blobKey); return; }
      store.state.ui.formDrafts ||= {}; store.state.ui.formDrafts[key] ||= {};
      if (!store.state.ui.formDrafts[key].title) store.state.ui.formDrafts[key].title = file.name;
      store.dispatch('material-upload-ready', { session, meta: { blobKey, filename: file.name, mimeType: file.type || '', size: file.size, kind, available: true } });
    } catch (error) {
      if (generation === uploadGeneration && context === uploadContext()) store.dispatch('material-upload-failed', { session, error: error.message });
    }
  }
  const fileRef = asset => ({ id: asset.id, revision: asset.revision, blobKey: asset.original?.blobKey, size: asset.original?.size, filename: asset.filename });
  const currentFile = ref => store.state.materials.find(asset => asset.id === ref.id && asset.revision === ref.revision && asset.original?.blobKey === ref.blobKey);
  async function fileAvailable(ref) {
    if (!ref.blobKey) return false;
    const record = await readAssetBlob(ref.blobKey);
    return Boolean(record?.blob && record.size === ref.size && record.filename === ref.filename);
  }
  async function send(action, values) {
    if (sending) { notice('上一条本地附件记录仍在校验，请稍候。'); return; }
    sending = true;
    try {
      let selections = values.attachments;
      if (action === 'material-auto-send' && selections === undefined) {
        const found = store.dispatch('material-auto-retrieve', { query: values.query });
        if (!found.ok) return;
        selections = found.value.slice(0, store.currentAgent().config.materialPolicy.maxCount);
      }
      selections ||= store.state.ui.materials.selected;
      const frozen = { ...values, generation: Number(values.generation), expectedRevision: values.expectedRevision === undefined ? undefined : Number(values.expectedRevision), actor: action === 'material-auto-send' ? 'agent' : 'human', attachments: selections.map(item => ({ id: item.id, revision: item.revision, variant: item.variant })) };
      const checked = materialSendCheck(store.state, frozen);
      if (!checked.ok) { notice(checked.message); return; }
      for (const item of checked.attachments) {
        const asset = store.state.materials.find(asset => asset.id === item.id);
        const ref = fileRef(asset);
        const available = await fileAvailable(ref);
        if (!currentFile(ref)) { notice('物料原件或修订已变化，未发送。请重新选择；输入和选择仍保留。'); return; }
        if (!available) {
          store.dispatch('material-file-availability', { id: item.id, available: false });
          notice('原件本地缓存不可用，未发送。请重新上传；当前文本与附件选择已保留。'); return;
        }
      }
      const result = store.dispatch(action, frozen);
      if (result.ok) { notice('附件已记入本地模拟会话；没有外部发送，送达和问题解决仍未知。', 'success'); return true; }
    } catch (error) { notice(error.message || '文件校验失败，本轮未发送，输入与选择仍保留。', 'danger'); }
    finally { sending = false; }
  }
  async function preview(data, { guard = () => true } = {}) {
    const asset = store.state.materials.find(item => item.id === data.id);
    const variant = asset?.variants.find(item => item.id === (data.variant || 'original'));
    const snapshot = data.snapshot === 'true';
    const metadata = snapshot
      ? { id: data.id, revision: data.revision, title: data.snapshotTitle || data.filename, filename: data.filename, kind: data.kind, mimeType: data.mimeType || '', variant: data.variant, snapshot: true, blobKey: data.blobKey || null }
      : { id: data.id, revision: data.revision || asset?.revision, title: asset?.title || data.filename, filename: data.filename || asset?.filename, kind: asset?.kind, mimeType: asset?.mimeType, variant: data.variant || 'original', snapshot: false, blobKey: data.blobKey || variant?.blobKey || null };
    if (!metadata.blobKey) { notice('该版本没有真正的本地文件；压缩候选仅演示状态，不提供假下载。'); return false; }
    if (data.mode === 'download') {
      try {
        const url = await assetObjectURL(metadata.blobKey);
        if (!guard()) return false;
        const link = document.createElement('a'); link.href = url; link.download = metadata.filename || 'material'; link.click(); return true;
      } catch (error) { if (guard()) notice(error.message); return false; }
    }
    if (!guard()) return false;
    store.state.ui.materials.preview = metadata; render();
    requestAnimationFrame(() => app.querySelector('.material-preview-dialog [data-action="material-preview-close"]')?.focus());
    return true;
  }
  async function reconcileFiles() {
    for (const asset of [...store.state.materials]) {
      if (!asset.original.blobKey) continue;
      const ref = fileRef(asset);
      try { const available = await fileAvailable(ref); const current = currentFile(ref); if (current && current.original.available !== available) store.dispatch('material-file-availability', { id: ref.id, available }); }
      catch { const current = currentFile(ref); if (current?.original.available) store.dispatch('material-file-availability', { id: ref.id, available: false }); }
    }
  }
  async function hydrate() {
    const generation = ++hydrationGeneration;
    for (const element of app.querySelectorAll('[data-material-text]')) {
      try {
        const record = await readAssetBlob(element.dataset.materialText);
        if (!record?.blob) throw new Error('本地文档原件已不可用，请重新录入。');
        const content = await record.blob.slice(0, 256 * 1024).text();
        if (generation !== hydrationGeneration || !element.isConnected) continue;
        element.textContent = content;
        const status = element.closest('.material-preview-dialog')?.querySelector('[data-material-cache-status]');
        if (status) status.textContent = record.blob.size > 256 * 1024 ? '仅展示文档前 256 KB；可下载原件查看完整内容。' : '已读取原件正文；按纯文本展示。';
      } catch (error) { if (generation === hydrationGeneration && element.isConnected) element.textContent = error.message; }
    }
    for (const element of app.querySelectorAll('[data-material-blob]')) {
      const key = element.dataset.materialBlob;
      try {
        const url = await assetObjectURL(key);
        if (generation !== hydrationGeneration || !element.isConnected || element.dataset.materialBlob !== key) continue;
        if (element.tagName === 'IFRAME') {
          const record = await readAssetBlob(key);
          const header = record?.blob ? await record.blob.slice(0, 5).text() : '';
          if (record?.mimeType !== 'application/pdf' || record.blob.type !== 'application/pdf' || header !== '%PDF-') throw new Error('该原件未通过 PDF 格式预检，请下载后用对应应用核实。');
          if (generation !== hydrationGeneration || !element.isConnected) continue;
          element.removeAttribute('sandbox');
        }
        element.src = url;
        const status = element.closest('.material-preview-dialog')?.querySelector('[data-material-cache-status]');
        if (status) status.textContent = '已读取浏览器缓存原件；文件预览由浏览器提供。';
        element.onerror = () => { element.hidden = true; const hint = document.createElement('p'); hint.className = 'helper'; hint.textContent = '浏览器无法预览此格式，可下载原件用对应应用打开。'; element.after(hint); };
      } catch (error) {
        if (generation !== hydrationGeneration || !element.isConnected) continue;
        element.hidden = true; const hint = document.createElement('p'); hint.className = 'notice notice-warning'; hint.textContent = error.message; element.after(hint);
      }
    }
  }
  return {
    contextChanged, hydrate, reconcileFiles, preview,
    async click(action, data) {
      if (action === 'material-preview') { await preview(data); return true; }
      return false;
    },
    async change(target) {
      if (!target.matches('[data-material-file]')) return false;
      await upload(target); return true;
    },
    async submit(form, values) {
      if (form.dataset.form === 'material-upsert') {
        if (store.state.ui.materials.uploadStatus === 'saving') { notice('原件仍在保存，请等待缓存确认后提交。'); return true; }
        const payload = { ...values, agentIds: new FormData(form).getAll('agentIds'), canSend: Boolean(form.elements.namedItem('canSend')?.checked), autoSendAllowed: Boolean(form.elements.namedItem('autoSendAllowed')?.checked), rights: Boolean(form.elements.namedItem('rights')?.checked) };
        const result = store.dispatch('material-upsert', payload);
        if (result.ok) { delete store.state.ui.formDrafts?.[formKey(form)]; store.save(); render(); }
        return true;
      }
      if (form.dataset.form === 'material-retrieve') { store.dispatch('material-auto-retrieve', { query: store.state.ui.materials.autoQuery }); return true; }
      if (form.dataset.form === 'material-auto-send') { await send('material-auto-send', { ...values, explicitRequest: Boolean(form.elements.namedItem('explicitRequest')?.checked) }); return true; }
      if (form.dataset.form === 'inbox' && store.state.ui.materials.selected.length) {
        const sourceKey = formKey(form);
        const sent = await send('material-send', { ...values, attachments: [...store.state.ui.materials.selected] });
        if (sent) { delete store.state.ui.formDrafts?.[sourceKey]; store.save(); render(); }
        return true;
      }
      return false;
    },
  };
}
