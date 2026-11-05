from pathlib import Path
import re
import unittest


class InboxSseClientContractTests(unittest.TestCase):
    def setUp(self):
        self.html = Path(__file__).parents[1].joinpath('loomrise', 'customer_inbox.html').read_text(encoding='utf-8')
        match = re.search(r'<script>\s*([\s\S]*?)\s*</script>', self.html)
        self.assertIsNotNone(match)
        self.script = match.group(1)

    def test_eventsource_reconnects_and_deduplicates_by_sequence_without_read_ack(self):
        self.assertIn('const stream = new EventSource(url);', self.script)
        self.assertIn("stream.onerror = () => {", self.script)
        self.assertIn('stream.readyState === window.EventSource.CLOSED', self.script)
        self.assertIn("call('inbox.consumer.cursor'", self.script)
        self.assertIn("call('inbox.consumer.ack'", self.script)
        self.assertIn('sessionStorage', self.script)

        start = self.script.index("stream.addEventListener('inbox', event => {")
        end = self.script.index('stream.onerror = () => {', start)
        handler = self.script[start:end]
        self.assertIn('enqueueInboxEvent(value, scope, stream)', handler)
        self.assertNotIn('inboxEventCursor = sequence', handler)
        self.assertNotIn("call('inbox.read'", handler)
        queued = self.script[self.script.index('function enqueueInboxEvent'):self.script.index('async function loadInboxEvents')]
        self.assertIn('sequence <= (inboxEventCursor ?? 0)', queued)
        self.assertIn('queuedInboxEventSequences.has(sequence)', queued)

    def test_client_ack_follows_projection_refresh_and_failed_processing_reconnects(self):
        self.assertIn('async function consumeInboxEvent', self.script)
        start = self.script.index('async function consumeInboxEvent')
        end = self.script.index('async function startInboxEventStream', start)
        consumer = self.script[start:end]
        self.assertLess(consumer.index('await loadList()'), consumer.index("call('inbox.consumer.ack'"))
        self.assertLess(consumer.index('queueInboxNotification'), consumer.index("call('inbox.consumer.ack'"))
        self.assertLess(consumer.index("call('inbox.consumer.ack'"), consumer.index('inboxEventCursor ='))
        self.assertIn('refreshSelected()', consumer)
        self.assertIn('restartInboxEventStream', consumer)

    def test_copied_tab_consumer_id_is_rotated_but_reload_keeps_it(self):
        start = self.script.index('function getInboxConsumerId()')
        end = self.script.index('function eventStreamOrigin()', start)
        consumer = self.script[start:end]
        self.assertIn("navigation?.type === 'reload'", consumer)
        self.assertIn('performance?.navigation?.type === 1', consumer)
        self.assertIn('if (sameTabReload && typeof saved === \'string\'', consumer)
        self.assertIn("/^[A-Za-z0-9_-]{1,128}$/.test(saved)", consumer)


if __name__ == '__main__':
    unittest.main()
