const DATABASE = 'loomrise-material-files-v1';
let opening;
const objectURLs = new Map();

function database() {
  if (!opening) opening = new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('files', { keyPath: 'id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { opening = null; reject(new Error('浏览器文件存储无法打开，请检查存储权限或可用空间')); };
    request.onblocked = () => { opening = null; reject(new Error('文件存储升级被其他页面阻止，请关闭旧预览后重试')); };
  });
  return opening;
}
async function transaction(mode, operation) {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('files', mode);
    const request = operation(tx.objectStore('files'));
    let value;
    request.onsuccess = () => { value = request.result; };
    tx.oncomplete = () => resolve(value);
    tx.onerror = () => reject(new Error('本地文件读写失败，文件可能超过浏览器可用空间'));
    tx.onabort = () => reject(new Error('本地文件事务已中止，未确认保存成功'));
  });
}
export function saveAssetBlob(id, file) {
  return transaction('readwrite', store => store.put({ id, blob: file, filename: file.name || '', mimeType: file.type || '', size: file.size, time: new Date().toISOString() }));
}
export function readAssetBlob(id) { return transaction('readonly', store => store.get(id)); }
export async function deleteAssetBlob(id) {
  if (objectURLs.has(id)) { URL.revokeObjectURL(objectURLs.get(id)); objectURLs.delete(id); }
  return transaction('readwrite', store => store.delete(id));
}
export async function assetObjectURL(id) {
  if (objectURLs.has(id)) return objectURLs.get(id);
  const record = await readAssetBlob(id);
  if (!record?.blob) throw new Error('本地原文件已不可用，请重新上传；元数据不是文件内容');
  const url = URL.createObjectURL(record.blob); objectURLs.set(id, url); return url;
}
export function releaseAssetURLs() {
  objectURLs.forEach(url => URL.revokeObjectURL(url)); objectURLs.clear();
}
