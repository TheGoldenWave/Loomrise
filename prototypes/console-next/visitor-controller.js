import { readAssetBlob } from './asset-cache.js';
import { visitorSession } from './visitor-domain.js';

const ACTION_PREFIX = { trial: 'trial', widget: 'widget-trial' };
const PAGES = { trial: ['trial'], widget: ['widget', 'overview', 'configuration'] };

export function createVisitorController({ store, app, materialController, delay = 450 }) {
  const tasks = new Map();
  let receiptScheduled = false;
  const scrollPositions = new Map();
  const scrollKey = chat => { const container = chat.closest('[data-visitor-surface]'); return `${container?.dataset.agentId}:${container?.dataset.visitorSurface}`; };
  const lastMessage = chat => [...chat.querySelectorAll('[data-visitor-message]')].at(-1)?.dataset.visitorMessage || '';
  function beforeRender() {
    for (const chat of app.querySelectorAll('.visitor-chat')) scrollPositions.set(scrollKey(chat), { top: chat.scrollTop, last: lastMessage(chat), follow: chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 32 });
  }
  const session = surface => visitorSession(store.state, surface);
  const action = (surface, suffix) => `${ACTION_PREFIX[surface]}-${suffix}`;
  const notice = text => store.dispatch('visitor-notice', { text });
  const stillCurrent = token => {
    const current = session(token.surface);
    return current.status === 'running' && current.pending?.id === token.id && current.generation === token.generation
      && store.state.selectedAgentId === token.agentId && store.state.ui.page === token.page
      && !store.readonly() && store.currentAgent()?.revision === token.revision;
  };
  function stop(surface) {
    const task = tasks.get(surface);
    if (task?.timer != null) clearTimeout(task.timer);
    tasks.delete(surface);
  }
  function contextChanged() {
    for (const [surface, task] of tasks) {
      if (stillCurrent(task.token)) continue;
      stop(surface);
      if (session(surface).status === 'running' && session(surface).pending?.id === task.token.id) store.dispatch(action(surface, 'cancel'));
    }
  }
  async function finish(token, refs) {
    const availableFiles = [];
    let fileError = '';
    try {
      if (refs.length && stillCurrent(token)) store.dispatch(action(token.surface, 'stage'), { id: token.id, stage: 'files', detail: '读取并核验浏览器中的原件' });
      for (const ref of refs) {
        if (!stillCurrent(token)) return;
        const record = await readAssetBlob(ref.blobKey);
        if (!stillCurrent(token)) return;
        const current = store.state.materials.find(item => item.id === ref.id);
        if (current?.revision !== ref.revision || current.original?.blobKey !== ref.blobKey) break;
        const available = Boolean(record?.blob && record.blob.size === ref.size && record.size === ref.size && record.filename === ref.filename);
        if (!available) {
          store.dispatch('material-file-availability', { id: ref.id, available: false });
          fileError = '原件缓存不可用，请重新录入文件后再试。';
          break;
        }
        availableFiles.push({ blobKey: ref.blobKey, size: ref.size, filename: ref.filename });
      }
    } catch (error) { fileError = error.message || '读取文件失败，未发送附件。'; }
    finally {
      if (stillCurrent(token)) store.dispatch(action(token.surface, 'complete'), { id: token.id, availableFiles, fileError });
      if (tasks.get(token.surface)?.token.id === token.id) stop(token.surface);
    }
  }
  function start(surface, question, expected = {}) {
    if (!ACTION_PREFIX[surface] || !PAGES[surface].includes(store.state.ui.page)) return false;
    const current = session(surface);
    if ((expected.agentId && expected.agentId !== store.state.selectedAgentId)
      || (expected.generation !== undefined && Number(expected.generation) !== current.generation)) return false;
    const result = store.dispatch(action(surface, 'start'), { question });
    if (!result.ok) return false;
    stop(surface);
    const pending = session(surface).pending;
    if (!pending || pending.id !== result.value) return false;
    const token = { surface, id: pending.id, agentId: pending.agentId, revision: pending.revision, generation: pending.generation, page: pending.page };
    const refs = (pending.fileRefs || []).map(ref => ({ ...ref }));
    const task = { token, timer: null };
    tasks.set(surface, task);
    task.timer = setTimeout(() => { task.timer = null; finish(token, refs); }, delay);
    return true;
  }
  function afterRender() {
    for (const chat of app.querySelectorAll('.visitor-chat')) {
      const previous = scrollPositions.get(scrollKey(chat));
      const follow = !previous || previous.follow || previous.last !== lastMessage(chat);
      chat.scrollTop = follow ? chat.scrollHeight : previous.top;
      if (follow) for (const media of chat.querySelectorAll('img,video')) media.addEventListener(media.tagName === 'IMG' ? 'load' : 'loadedmetadata', () => { if (chat.isConnected) chat.scrollTop = chat.scrollHeight; }, { once: true });
    }
    if (receiptScheduled) return;
    receiptScheduled = true;
    queueMicrotask(() => {
      receiptScheduled = false;
      for (const element of app.querySelectorAll('[data-visitor-message]')) {
        const surface = element.dataset.surface;
        if (!ACTION_PREFIX[surface]) continue;
        const message = session(surface).messages.find(item => item.id === element.dataset.visitorMessage);
        if ((message?.localReceipt?.status || message?.localReceipt?.state) === 'pending' && element.isConnected && element.getClientRects().length > 0) {
          store.dispatch('visitor-received', { surface, messageId: message.id });
        }
      }
    });
  }
  const findAttachment = data => {
    if (!ACTION_PREFIX[data.surface]) return null;
    const run = data.runId ? store.state.runs.find(item => item.id === data.runId && item.agentId === store.state.selectedAgentId && item.surface === data.surface) : null;
    const message = run || session(data.surface).messages.find(item => item.id === data.messageId);
    const attachment = message?.attachments?.find(item => item.id === data.id && item.revision === Number(data.revision) && item.variant === data.variant);
    return attachment ? { message, attachment } : null;
  };
  async function openAttachment(actionName, data) {
    const found = findAttachment(data);
    if (!found || found.attachment.simulated || !found.attachment.blobKey) return;
    const { message, attachment } = found;
    const agentId = store.state.selectedAgentId;
    const generation = session(data.surface).generation;
    try {
      const record = await readAssetBlob(attachment.blobKey);
      if (!record?.blob || record.blob.size !== attachment.size || record.filename !== attachment.filename) {
        notice('这份历史附件的本地原件已不可用，未打开文件。'); return;
      }
      const guard = () => agentId === store.state.selectedAgentId && generation === session(data.surface).generation
        && findAttachment(data)?.message.id === message.id && (data.runId ? store.state.ui.page === 'runs' : PAGES[data.surface].includes(store.state.ui.page));
      if (!guard()) return;
      const download = actionName === 'visitor-attachment-download';
      const executed = await materialController.preview({
        id: attachment.id, revision: attachment.revision, variant: attachment.variant, blobKey: attachment.blobKey,
        filename: attachment.filename, snapshotTitle: attachment.title, kind: attachment.kind, mimeType: attachment.mimeType || '',
        snapshot: 'true', ...(download ? { mode: 'download' } : {}),
      }, { guard });
      if (executed && guard()) store.dispatch(download ? 'visitor-downloaded' : 'visitor-opened', { ...data });
    } catch (error) { notice(error.message || '本地附件无法读取，请检查文件缓存。'); }
  }
  return {
    start, contextChanged, beforeRender, afterRender,
    async click(actionName, data) {
      if (['visitor-attachment-preview', 'visitor-attachment-download'].includes(actionName)) {
        await openAttachment(actionName, { ...data, variant: data.attachmentVariant || data.variant }); return true;
      }
      const surface = actionName.startsWith('widget-trial-') ? 'widget' : actionName.startsWith('trial-') ? 'trial' : null;
      if (surface && ['cancel', 'clear'].some(suffix => actionName === action(surface, suffix))) stop(surface);
      return false;
    },
    async submit(form, values) {
      const surface = form.dataset.form === 'trial' ? 'trial' : form.dataset.form === 'widget-trial' ? 'widget' : null;
      if (!surface) return false;
      start(surface, values.question || values.widgetQuestion, { agentId: values.agentId, generation: values.generation });
      return true;
    },
  };
}
