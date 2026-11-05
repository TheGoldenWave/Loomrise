import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

// 本机静态合同证据：只载入 HTML 里的桥合同 script 并校验集成层源码结构，
// 不加载真实 DOM / 网络 / 平台 WebView，不代表任何实机运行结果。
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const html = readFileSync(resolve(root, 'loomrise/customer_widget.html'), 'utf8');

function contractSource() {
  const marker = '/* loomrise-webview-bridge-contract:';
  const markerAt = html.indexOf(marker);
  assert.notEqual(markerAt, -1, 'Widget 必须声明桥合同标记');
  const scriptStart = html.lastIndexOf('<script>', markerAt);
  const scriptEnd = html.indexOf('</script>', markerAt);
  assert.ok(scriptStart >= 0 && scriptEnd > markerAt, '桥合同 script 必须自包含');
  return html.slice(scriptStart + '<script>'.length, scriptEnd);
}

function makeHarness({
  host = true,
  referrer = 'http://127.0.0.1:8765/embed',
  selfParent = false,
  datasetOrigins = 'http://127.0.0.1:8765',
  extraAllowedOrigins = [],
} = {}) {
  const listeners = new Map();
  const outbound = [];
  const state = { gone: false };
  const parent = {
    postMessage(message, targetOrigin) {
      if (state.gone) throw new Error('host window is gone');
      outbound.push({ message, targetOrigin });
    },
  };
  const windowObject = {
    location: { origin: 'http://127.0.0.1:8788' },
    parent: host ? parent : null,
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name, listener) {
      if (listeners.get(name) === listener) listeners.delete(name);
    },
    __LOOMRISE_WEBVIEW_ALLOWED_ORIGINS__: extraAllowedOrigins,
  };
  if (selfParent) windowObject.parent = windowObject;
  const documentObject = {
    referrer,
    body: { dataset: { bridgeAllowedOrigins: datasetOrigins } },
  };
  const context = { window: windowObject, document: documentObject, URL, Set, Object, Array };
  vm.runInNewContext(`${contractSource()}\nthis.__contract = window.__LOOMRISE_WEBVIEW_BRIDGE_CONTRACT__;`, context);
  return { contract: context.__contract, parent, windowObject, documentObject, outbound, listeners, state };
}

function envelope(contract, type, payload, requestId = 'request-1') {
  return {
    schema: contract.VERSION,
    source: contract.HOST_SOURCE,
    target: contract.WIDGET_SOURCE,
    type,
    request_id: requestId,
    payload,
  };
}

function handoffData(contract, overrides = {}) {
  return { ...envelope(contract, contract.INCOMING.HANDOFF,
    { session: { conversation_id: 'c', visitor_token: 't' } }), ...overrides };
}

function hostEvent(harness, data, overrides = {}) {
  return { source: harness.parent, origin: 'http://127.0.0.1:8765', data, ...overrides };
}

test('READY 握手只发一次且信封固定，重复 create 视为独立新握手', () => {
  const harness = makeHarness();
  const bridge = harness.contract.create({}, harness.windowObject, harness.documentObject);

  assert.equal(bridge.enabled, true);
  assert.equal(bridge.version, 'loomrise.webview.bridge.v1');
  assert.equal(harness.outbound.length, 1, 'create 只发一条 READY');
  const ready = harness.outbound[0];
  assert.equal(ready.targetOrigin, 'http://127.0.0.1:8765');
  assert.deepEqual(JSON.parse(JSON.stringify(ready.message)), {
    schema: 'loomrise.webview.bridge.v1',
    source: 'loomrise.customer-widget',
    target: 'loomrise.host',
    type: 'ready',
    payload: {},
  });
  assert.ok(!('request_id' in ready.message), 'READY 不携带 request_id');

  // 合法消息不会重复触发 READY 握手
  assert.equal(bridge.receive(hostEvent(harness, handoffData(harness.contract))), true);
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    { reason: 'host-close' }, 'd-1'))), true);
  assert.equal(harness.outbound.filter(item => item.message.type === 'ready').length, 1,
    '握手后不再重复发 READY');

  // dispose 移除监听；重新 create 是独立的新握手
  assert.equal(harness.listeners.has('message'), true);
  bridge.dispose();
  assert.equal(harness.listeners.has('message'), false);
  const again = harness.contract.create({}, harness.windowObject, harness.documentObject);
  assert.equal(again.enabled, true);
  assert.equal(harness.outbound.filter(item => item.message.type === 'ready').length, 2,
    '重复握手（新实例）各发一条 READY');
});

test('referrer 不可信时不主动 READY，合法 origin 的宿主消息仍可完成握手', () => {
  const harness = makeHarness({ referrer: '' });
  const bridge = harness.contract.create({}, harness.windowObject, harness.documentObject);
  assert.equal(bridge.enabled, false);
  assert.equal(harness.outbound.length, 0, '无可信 host origin 时不发 READY');
  assert.equal(bridge.receive(hostEvent(harness, handoffData(harness.contract))), true);
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { conversation_id: 'c' }), true);
  assert.equal(harness.outbound.at(-1).targetOrigin, 'http://127.0.0.1:8765',
    '首条合法宿主消息确定 hostOrigin 后即可回执，仍限定在 loopback allowlist 内');
});

test('迟到/重复 session.handoff：传输层不破坏状态，集成层按幂等回执', () => {
  const harness = makeHarness();
  const received = [];
  const bridge = harness.contract.create({
    onSessionHandoff: (payload, requestId) => received.push({ payload, requestId }),
  }, harness.windowObject, harness.documentObject);
  const repeated = envelope(harness.contract, bridge.types.HANDOFF,
    { session: { conversation_id: 'conv-same', visitor_token: 'tok' } }, 'req-repeat');

  // 同一 request_id 重复送达：如实回调，不改写 hostOrigin、不发意外消息
  assert.equal(bridge.receive(hostEvent(harness, repeated)), true);
  assert.equal(bridge.receive(hostEvent(harness, repeated)), true);
  assert.equal(received.length, 2);
  assert.ok(received.every(item => item.requestId === 'req-repeat'));
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { conversation_id: 'conv-same' }, 'req-repeat'), true);
  assert.equal(harness.outbound.at(-1).targetOrigin, 'http://127.0.0.1:8765',
    '重复消息不漂移 hostOrigin');
  assert.equal(harness.outbound.filter(item => item.message.type === 'ready').length, 1);

  // 集成层静态合同证据：迟到/重复交接保留首个、不覆盖、不丢 request_id
  assert.match(html, /if \(!bridgeStartComplete\)/);
  assert.match(html, /session_start_pending/, '重复交接必须显式幂等回执，不覆盖首个缓冲');
  assert.match(html, /bridgeReply\(same \? widgetBridge\.types\.ACCEPTED : widgetBridge\.types\.REJECTED, requestId/);
  assert.match(html, /bridgeStartComplete = true/);
  assert.match(html, /await handleBridgeHandoff\(handoff, requestId\)/);
  // 已激活会话的重复交接走 same/different 幂等分支，不重写既有会话
  assert.match(html, /reason: 'session_already_active'/);
  assert.match(html, /payload\.session\.conversation_id === session\.conversation_id/);
});

test('未知/反向/畸形消息类型一律安全 no-op，不触发回调也不污染 hostOrigin', () => {
  const harness = makeHarness();
  const calls = [];
  const bridge = harness.contract.create({
    onSessionHandoff: () => calls.push('handoff'),
    onDismiss: () => calls.push('dismiss'),
  }, harness.windowObject, harness.documentObject);
  assert.equal(harness.outbound.length, 1);

  const badTypes = ['ready', 'session.accepted', 'session.rejected', 'dismissed', 'unknown', '', 42, null, undefined];
  for (const type of badTypes) {
    assert.equal(bridge.receive(hostEvent(harness, handoffData(harness.contract, { type }))), false,
      `type=${String(type)} 必须 no-op`);
  }
  const missingType = handoffData(harness.contract); delete missingType.type;
  assert.equal(bridge.receive(hostEvent(harness, missingType)), false);
  for (const key of ['schema', 'source', 'target', 'payload']) {
    const data = handoffData(harness.contract); delete data[key];
    assert.equal(bridge.receive(hostEvent(harness, data)), false, `缺 ${key} 必须 no-op`);
  }
  assert.equal(bridge.receive(hostEvent(harness, handoffData(harness.contract,
    { source: 'loomrise.customer-widget' }))), false);
  assert.equal(bridge.receive(hostEvent(harness, handoffData(harness.contract,
    { target: 'loomrise.host' }))), false);

  // 方向隔离：widget 不发 INCOMING 类型，未知 OUTGOING 类型也拒
  assert.equal(bridge.emit(bridge.types.HANDOFF, {}), false);
  assert.equal(bridge.emit(bridge.types.DISMISS, { reason: 'x' }), false);
  assert.equal(bridge.emit('unknown', {}), false);

  assert.deepEqual(calls, [], 'no-op 不触发任何回调');
  assert.equal(harness.outbound.length, 1, 'no-op 不产生任何外发消息');
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { conversation_id: 'c' }), true);
  assert.equal(harness.outbound.at(-1).targetOrigin, 'http://127.0.0.1:8765');
});

test('父窗口/宿主消失与 source/origin allowlist 边界', () => {
  // 自引用 parent（顶层窗口，无宿主）→ 安全 no-op
  const self = makeHarness({ selfParent: true });
  const selfBridge = self.contract.create({}, self.windowObject, self.documentObject);
  assert.equal(selfBridge.enabled, false);
  assert.equal(selfBridge.emit(selfBridge.types.READY), false);
  assert.equal(selfBridge.receive(hostEvent(self, handoffData(self.contract))), false);
  assert.equal(self.outbound.length, 0);

  // 无 parent → 安全 no-op（即便携带完整合法信封）
  const noHost = makeHarness({ host: false, referrer: '' });
  const noHostBridge = noHost.contract.create({}, noHost.windowObject, noHost.documentObject);
  assert.equal(noHostBridge.enabled, false);
  assert.equal(noHostBridge.receive({ source: null, origin: 'http://127.0.0.1:8765',
    data: handoffData(noHost.contract) }), false);
  assert.equal(noHost.outbound.length, 0);

  const harness = makeHarness();
  const calls = [];
  const bridge = harness.contract.create({ onSessionHandoff: () => calls.push(1) },
    harness.windowObject, harness.documentObject);
  const ok = handoffData(harness.contract);

  // source 边界
  for (const source of [null, undefined, {}, harness.windowObject, 'host']) {
    assert.equal(bridge.receive(hostEvent(harness, ok, { source })), false);
  }
  // origin 边界（event.origin 不归一化，必须精确命中 allowlist）
  const badOrigins = [
    'http://127.0.0.1:8765/', 'http://127.0.0.1:8765/embed', 'HTTP://127.0.0.1:8765',
    'http://127.0.0.1:8765.evil.invalid', 'https://127.0.0.1:8765', 'http://127.0.0.1:9999',
    'http://localhost:8765.evil.invalid', 'https://evil.invalid', '', null, 123,
  ];
  for (const origin of badOrigins) {
    assert.equal(bridge.receive(hostEvent(harness, ok, { origin })), false,
      `origin=${String(origin)} 必须拒绝`);
  }
  assert.deepEqual(calls, []);

  // allowlist 内的第二个 loopback origin 被接受（现状，可复核）
  assert.equal(bridge.receive(hostEvent(harness, ok, { origin: 'http://localhost:8765' })), true);
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { conversation_id: 'c' }), true);
  assert.equal(harness.outbound.at(-1).targetOrigin, 'http://localhost:8765',
    'hostOrigin 跟随最近一次合法 origin，仍限定在 allowlist 内');

  // dataset / 注入的非 loopback origin 被 normalizeOrigin 拒绝
  const injected = makeHarness({
    datasetOrigins: 'http://127.0.0.1:8765,https://evil.invalid',
    extraAllowedOrigins: ['http://10.0.0.1:8765'],
  });
  const injectedBridge = injected.contract.create({}, injected.windowObject, injected.documentObject);
  assert.equal(injectedBridge.receive(hostEvent(injected, handoffData(injected.contract),
    { origin: 'https://evil.invalid' })), false);
  assert.equal(injectedBridge.receive(hostEvent(injected, handoffData(injected.contract),
    { origin: 'http://10.0.0.1:8765' })), false);

  // 宿主消失：postMessage 抛错时 emit 安全返回 false，不冒泡
  harness.state.gone = true;
  assert.doesNotThrow(() => {
    assert.equal(bridge.emit(bridge.types.DISMISSED, { reason: 'user' }, 'd-gone'), false);
    assert.equal(bridge.emit(bridge.types.READY), false);
  });
  bridge.dispose();
});

test('访客字段白名单拒绝 tenant/actor/role 等权威字段（含嵌套与外发）', () => {
  const harness = makeHarness();
  const received = [];
  const bridge = harness.contract.create({
    onSessionHandoff: (payload) => received.push(JSON.parse(JSON.stringify(payload))),
  }, harness.windowObject, harness.documentObject);
  const authorityKeys = ['tenant', 'tenant_id', 'tenantId', 'actor', 'actor_id', 'actorId',
    'subject', 'subject_id', 'user', 'user_id', 'userId', 'role', 'principal', 'permissions',
    'authorization', 'agent_id', 'agentId', 'entry_id', 'entryId'];
  for (const key of authorityKeys) {
    assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.HANDOFF,
      { identity: { fields: { [key]: 'must-not-cross' } } }))), false, `字段 ${key} 必须拒绝`);
  }
  // session 内夹带权威字段
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.HANDOFF,
    { session: { conversation_id: 'c', visitor_token: 't', role: 'admin' } }))), false);
  // 顶层 payload 夹带权威字段
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.HANDOFF,
    { session: { conversation_id: 'c', visitor_token: 't' }, permissions: {} }))), false);
  // 嵌套结构中的权威字段
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.HANDOFF,
    { identity: { fields: { nested: { actor_id: 'x' } } } }))), false);
  // 外发 payload 的嵌套权威字段
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { nested: { tenant_id: 'x' } }), false);
  // 合法访客字段通过（不是一律拒绝）
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.HANDOFF,
    { identity: { fields: { display_name: '访客', phone: '13800000000' } } }))), true);
  assert.deepEqual(received.map(item => item.identity.fields), [
    { display_name: '访客', phone: '13800000000' },
  ]);
  // 集成层二次白名单（静态）
  assert.match(html, /function visitorFieldsFromBridge\(fields = \{\}\)/);
  assert.match(html, /const allowed = new Set\(configuration\.widget\.fields\.map\(field => field\.id\)\)/);
  assert.match(html, /allowed\.has\(key\)/);
});

test('dismiss 双向消息与关闭按钮在桥启用/未启用时的行为', () => {
  const harness = makeHarness();
  const dismissed = [];
  const bridge = harness.contract.create({
    onDismiss: (payload, requestId) => dismissed.push(JSON.parse(JSON.stringify({ payload, requestId }))),
  }, harness.windowObject, harness.documentObject);

  // 非法 dismiss payload 一律 no-op
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    { reason: 'x', extra: 1 }))), false);
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    { reason: 42 }))), false);
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    { reason: 'x'.repeat(101) }))), false);
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    { reason: 'user' }))), true);
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISS,
    {}, 'd-empty'))), true);
  assert.deepEqual(JSON.parse(JSON.stringify(dismissed)), [
    { payload: { reason: 'user' }, requestId: 'request-1' },
    { payload: { reason: 'host' }, requestId: 'd-empty' },
  ]);

  // 方向隔离：host 不发 widget 的 OUTGOING 类型，widget 不发 INCOMING 类型
  assert.equal(bridge.receive(hostEvent(harness, envelope(harness.contract, bridge.types.DISMISSED,
    { reason: 'x' }))), false);
  assert.equal(bridge.emit(bridge.types.DISMISS, { reason: 'x' }), false);
  // 回执发往宿主
  assert.equal(bridge.emit(bridge.types.DISMISSED, { reason: 'user' }, 'd-out'), true);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.outbound.at(-1))), {
    targetOrigin: 'http://127.0.0.1:8765',
    message: {
      schema: bridge.version, source: 'loomrise.customer-widget', target: 'loomrise.host',
      type: 'dismissed', request_id: 'd-out', payload: { reason: 'user' },
    },
  });

  // 桥未启用时关闭按钮的 emit 为 no-op（行为证据）
  const noHost = makeHarness({ host: false, referrer: '' });
  const noHostBridge = noHost.contract.create({}, noHost.windowObject, noHost.documentObject);
  assert.equal(noHostBridge.enabled, false);
  assert.equal(noHostBridge.emit(noHostBridge.types.DISMISSED, { reason: 'user' }), false,
    '桥未启用时点击关闭不产生外发消息，按钮不会被禁用');

  // 集成层静态合同证据：关闭按钮默认隐藏，仅桥启用时显示
  assert.match(html, /<button id="dismiss" hidden[^>]*aria-label="关闭"/,
    '关闭按钮默认隐藏（桥未启用不可见）');
  assert.match(html, /if \(widgetBridge\?\.enabled\) dismiss\.hidden = false;/,
    '仅桥启用时显示关闭按钮');
  assert.match(html, /dismiss\.addEventListener\('click'/);
  assert.match(html, /if \(widgetBridge\?\.emit\(widgetBridge\.types\.DISMISSED, \{ reason: 'user' \}\)\) dismiss\.disabled = true;/,
    '点击时 emit 成功才禁用，桥未启用 emit 返回 false 即 no-op');
  assert.match(html, /function handleBridgeDismiss\(payload, requestId\)/);
  assert.match(html, /document\.querySelector\('main'\)\.hidden = true;/);
  assert.match(html, /bridgeReply\(widgetBridge\.types\.DISMISSED, requestId, \{ reason: payload\.reason \}\)/,
    '宿主 dismiss 双向：隐藏主区域并回执');
});

test('既有会话交接不丢持久化，且明确仅为本机静态合同证据', () => {
  // 会话交接写入 sessionStorage，启动路径先读回
  assert.match(html, /session = payload\.session;/);
  assert.match(html, /session = handoff\.session;/);
  assert.match(html, /sessionStorage\.setItem\(sessionKey, JSON\.stringify\(session\)\)/);
  assert.match(html, /session = JSON\.parse\(sessionStorage\.getItem\(sessionKey\) \|\| 'null'\)/);
  assert.match(html, /conversation_id: session\.conversation_id, visitor_token: session\.visitor_token/);
  // 重复交接不覆盖既有会话：same 比较 + already_active 回执 + 失败清理
  assert.match(html, /reason: 'session_already_active'/);
  assert.match(html, /session = null; sessionStorage\.removeItem\(sessionKey\);/);
  // 迟到/重复交接显式幂等分支
  assert.match(html, /session_start_pending/);
  assert.match(html, /bridgeStartComplete = true/);
  // 明确不声称任何平台实机 / WebView 能力
  assert.doesNotMatch(html, /ReactNativeWebView|WKWebView|Android WebView|native iOS|native Android|Flutter/);
  assert.match(html, /browser host handoff only; no native platform claim/);
  for (const [, source] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(source);
});
