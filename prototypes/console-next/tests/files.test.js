import test from 'node:test';
import assert from 'node:assert/strict';
import { createLocalFileReader } from '../local-files.js';

test('文件晚到回调不串入另一专家，来回切换仍使旧读取失效', async () => {
  let key = 'agent-a:new:File'; let finish;
  const reader = createLocalFileReader(() => key);
  const read = reader.read({ name: 'old.txt', size: 20, text: () => new Promise(resolve => { finish = resolve; }) });
  key = 'agent-b:new:File'; reader.invalidate(); key = 'agent-a:new:File';
  finish('旧专家资料'); assert.equal((await read).status, 'stale');
});
test('再次选择文件使更早的读取失效，只保留最后一份', async () => {
  let finish; const reader = createLocalFileReader(() => 'agent-a:new:File');
  const old = reader.read({ name: 'first.txt', size: 20, text: () => new Promise(resolve => { finish = resolve; }) });
  const current = await reader.read({ name: 'second.txt', size: 20, text: async () => '最后选择的文本' });
  finish('更早的文本'); assert.equal((await old).status, 'stale');
  assert.equal(current.status, 'ready'); assert.equal(current.meta.name, 'second.txt'); assert.equal(current.body, '最后选择的文本');
});
test('读取失败返回可恢复提示，超限/未接入格式不伪造正文', async () => {
  const reader = createLocalFileReader(() => 'agent-a:new:File');
  const failed = await reader.read({ name: 'failed.txt', size: 20, text: async () => { throw new Error('read failed'); } });
  assert.equal(failed.status, 'error'); assert.match(failed.message, /草稿仍保留/);
  const large = await reader.read({ name: 'large.txt', size: 512001, text: async () => '不会读取' }); assert.equal(large.status, 'error');
  const pdf = await reader.read({ name: 'guide.pdf', size: 20, text: async () => '不会当作文本读取' }); assert.equal(pdf.meta.metadataOnly, true); assert.equal(pdf.body, '');
});
