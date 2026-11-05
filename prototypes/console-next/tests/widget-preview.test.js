import assert from 'node:assert/strict';
import test from 'node:test';
import { widgetPreview } from '../views/surfaces.js';

const preview = (bookingUrl, widgetOverrides = {}, greeting = '欢迎咨询。') => widgetPreview({
  name: '虚构客服',
  config: {
    greeting,
    fields: [],
    sources: [],
    widget: { bookingUrl, formMode: 'none', showFaq: false, ...widgetOverrides },
  },
});

test('Widget preview exposes a safe external booking link without claiming success', () => {
  const html = preview('https://booking.example.test/schedule?course=demo&slot=1');

  assert.match(html, /<a[^>]+href="https:\/\/booking\.example\.test\/schedule\?course=demo&amp;slot=1"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /打开链接不代表已预约成功/);
});

test('Widget preview omits empty or non-HTTPS booking destinations', () => {
  assert.doesNotMatch(preview(''), /booking\.example\.test|预约外链/);
  assert.doesNotMatch(preview('http://booking.example.test/schedule'), /href="http:/);
  assert.doesNotMatch(preview('javascript:alert(1)'), /href="javascript:/);
});

test('Widget preview provides visible defaults for empty heading and greeting', () => {
  const html = preview('', { title: '' }, '');

  assert.match(html, /<strong>虚构客服<\/strong>/);
  assert.match(html, /你好，有什么可以帮助你？/);
});

test('Widget preview preserves maximum supported text as escaped visible content', () => {
  const title = 'T'.repeat(100);
  const greeting = '<b>G</b>'.repeat(285);
  const html = preview('', { title }, greeting);

  assert.ok(html.includes(`<strong>${title}</strong>`));
  assert.ok(html.includes('&lt;b&gt;G&lt;/b&gt;'.repeat(285)));
  assert.doesNotMatch(html, /<b>G<\/b>/);
});
