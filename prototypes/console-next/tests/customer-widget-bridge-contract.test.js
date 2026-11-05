import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const html = readFileSync(resolve(root, 'loomrise/customer_widget.html'), 'utf8');

function contractSource() {
  const marker = '/* loomrise-webview-bridge-contract:';
  const markerAt = html.indexOf(marker);
  assert.notEqual(markerAt, -1, 'Widget must declare the bridge contract marker');
  const scriptStart = html.lastIndexOf('<script>', markerAt);
  const scriptEnd = html.indexOf('</script>', markerAt);
  assert.ok(scriptStart >= 0 && scriptEnd > markerAt, 'Bridge contract script must be self-contained');
  return html.slice(scriptStart + '<script>'.length, scriptEnd);
}

function makeHarness({ host = true, referrer = 'http://127.0.0.1:8765/embed' } = {}) {
  const listeners = new Map();
  const outbound = [];
  const parent = {
    postMessage(message, targetOrigin) { outbound.push({ message, targetOrigin }); },
  };
  const windowObject = {
    location: { origin: 'http://127.0.0.1:8788' },
    parent: host ? parent : null,
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name, listener) {
      if (listeners.get(name) === listener) listeners.delete(name);
    },
    __LOOMRISE_WEBVIEW_ALLOWED_ORIGINS__: [],
  };
  const documentObject = {
    referrer,
    body: { dataset: { bridgeAllowedOrigins: 'http://127.0.0.1:8765' } },
  };
  const context = { window: windowObject, document: documentObject, URL, Set, Object, Array };
  vm.runInNewContext(`${contractSource()}\nthis.__contract = window.__LOOMRISE_WEBVIEW_BRIDGE_CONTRACT__;`, context);
  return { contract: context.__contract, parent, windowObject, documentObject, outbound };
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

test('versioned host handoff accepts only loopback origin and parent source', () => {
  const harness = makeHarness();
  const received = [];
  const bridge = harness.contract.create({
    onSessionHandoff: (payload, requestId) => received.push(JSON.parse(JSON.stringify({ payload, requestId }))),
  }, harness.windowObject, harness.documentObject);

  assert.equal(bridge.enabled, true);
  assert.equal(harness.outbound[0].message.type, 'ready');
  assert.equal(harness.outbound[0].targetOrigin, 'http://127.0.0.1:8765');
  assert.equal(bridge.receive({
    source: harness.parent,
    origin: 'http://127.0.0.1:8765',
    data: envelope(harness.contract, bridge.types.HANDOFF, {
      session: { conversation_id: 'conv-same', visitor_token: 'opaque-token' },
      identity: { fields: { display_name: '访客' } },
    }),
  }), true);
  assert.deepEqual(received, [{
    requestId: 'request-1',
    payload: {
      session: { conversation_id: 'conv-same', visitor_token: 'opaque-token' },
      identity: { fields: { display_name: '访客' } },
    },
  }]);
  assert.equal(bridge.receive({
    source: {}, origin: 'http://127.0.0.1:8765',
    data: envelope(harness.contract, bridge.types.HANDOFF, { session: { conversation_id: 'other', visitor_token: 'token' } }),
  }), false);
  assert.equal(bridge.receive({
    source: harness.parent, origin: 'https://evil.invalid',
    data: envelope(harness.contract, bridge.types.HANDOFF, { session: { conversation_id: 'other', visitor_token: 'token' } }),
  }), false);
  assert.equal(bridge.receive({
    source: harness.parent, origin: 'http://127.0.0.1:8778',
    data: envelope(harness.contract, bridge.types.HANDOFF, { session: { conversation_id: 'other', visitor_token: 'token' } }),
  }), false);
  assert.equal(bridge.receive({
    source: harness.parent, origin: 'http://127.0.0.1:8765',
    data: { ...envelope(harness.contract, bridge.types.HANDOFF, { session: { conversation_id: 'other', visitor_token: 'token' } }), extra: true },
  }), false);
});

test('authority-shaped handoffs and outbound payloads are rejected', () => {
  const harness = makeHarness();
  const bridge = harness.contract.create({}, harness.windowObject, {
    body: { dataset: { bridgeAllowedOrigins: 'http://127.0.0.1:8765' } },
    referrer: 'http://127.0.0.1:8765/embed',
  });
  const before = harness.outbound.length;
  assert.equal(bridge.receive({
    source: harness.parent,
    origin: 'http://127.0.0.1:8765',
    data: envelope(harness.contract, bridge.types.HANDOFF, {
      session: { conversation_id: 'conv', visitor_token: 'token' },
      identity: { fields: { actor_id: 'must-not-cross' } },
    }),
  }), false);
  assert.equal(bridge.emit(bridge.types.ACCEPTED, { tenant_id: 'must-not-cross' }), false);
  assert.equal(harness.outbound.length, before);
});

test('dismiss is a symmetric bridge event and no-host mode is a safe no-op', () => {
  const harness = makeHarness();
  const dismissed = [];
  const bridge = harness.contract.create({ onDismiss: (payload, requestId) => dismissed.push(JSON.parse(JSON.stringify({ payload, requestId }))) }, harness.windowObject, {
    body: { dataset: { bridgeAllowedOrigins: 'http://127.0.0.1:8765' } },
    referrer: 'http://127.0.0.1:8765/embed',
  });
  assert.equal(bridge.receive({
    source: harness.parent,
    origin: 'http://127.0.0.1:8765',
    data: envelope(harness.contract, bridge.types.DISMISS, { reason: 'host-close' }, 'dismiss-1'),
  }), true);
  assert.deepEqual(dismissed, [{ payload: { reason: 'host-close' }, requestId: 'dismiss-1' }]);
  assert.equal(bridge.emit(bridge.types.DISMISSED, { reason: 'user' }, 'dismiss-2'), true);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.outbound.at(-1))), {
    targetOrigin: 'http://127.0.0.1:8765',
    message: {
      schema: bridge.version, source: 'loomrise.customer-widget', target: 'loomrise.host',
      type: 'dismissed', request_id: 'dismiss-2', payload: { reason: 'user' },
    },
  });

  const noHost = makeHarness({ host: false, referrer: '' });
  const noHostBridge = noHost.contract.create({}, noHost.windowObject, noHost.documentObject);
  assert.equal(noHostBridge.enabled, false);
  assert.equal(noHostBridge.emit(noHostBridge.types.DISMISSED, { reason: 'user' }), false);
  assert.equal(noHostBridge.receive({}), false);
  assert.equal(noHost.outbound.length, 0);
});

test('widget integration persists a handed-off session and does not claim native platforms', () => {
  assert.match(html, /data-bridge-allowed-origins=/);
  assert.match(html, /sessionStorage\.setItem\(sessionKey, JSON\.stringify\(session\)\)/);
  assert.match(html, /conversation_id: session\.conversation_id, visitor_token: session\.visitor_token/);
  assert.match(html, /postMessage\(\{[\s\S]*schema: VERSION/);
  assert.doesNotMatch(html, /ReactNativeWebView|WKWebView|Android WebView|native iOS|native Android/);
  for (const [, source] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(source);
});
