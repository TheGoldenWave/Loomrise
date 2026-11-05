import hashlib
import hmac
import json
import unittest

from loomrise.channel_webhook import ChannelWebhookAdapter


class ChannelWebhookTests(unittest.TestCase):
    def test_signature_and_payload_contract(self):
        body = json.dumps({'message_id': 'm', 'thread_id': 't', 'text': 'hello', 'external_account': 'bot'}).encode()
        signature = hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        adapter = ChannelWebhookAdapter(channel='telegram', secret='secret', deliver=lambda event: {'accepted': True})
        result = adapter.receive(body, signature)
        self.assertEqual(result['event']['environment'], 'sandbox')
        self.assertTrue(result['result']['accepted'])
        self.assertEqual(result['evidence'], 'sandbox_callback_adapter')
        with self.assertRaises(PermissionError): adapter.receive(body, 'bad')

    def test_signed_payload_still_requires_closed_nonempty_message_contract(self):
        deliveries = []
        adapter = ChannelWebhookAdapter(channel='telegram', secret='secret', deliver=deliveries.append)
        valid = {'message_id': 'm', 'thread_id': 't', 'text': 'hello', 'external_account': 'bot'}
        cases = [
            {'thread_id': ''}, {'text': ' '}, {'text': None}, {'text': 'x' * 20001},
            {'attachment_ids': ['asset']}, {'external_account': 7},
        ]
        for index, patch in enumerate(cases):
            body = json.dumps(valid | patch).encode()
            signature = hmac.new(b'secret', body, hashlib.sha256).hexdigest()
            with self.subTest(case=index), self.assertRaises(ValueError):
                adapter.receive(body, signature)
        self.assertEqual(deliveries, [])

    def test_malformed_signatures_are_rejected_without_invoking_callback(self):
        deliveries = []
        adapter = ChannelWebhookAdapter(channel='email', secret='secret', deliver=deliveries.append)
        body = b'{"message_id":"m","thread_id":"t","text":"hello","external_account":"mail"}'
        for signature in (None, 123, b'bad', 'é' * 64):
            with self.subTest(signature=signature), self.assertRaises(PermissionError):
                adapter.receive(body, signature)
        self.assertEqual(deliveries, [])

    def test_missing_provider_adapter_is_explicit_and_never_sends_network(self):
        body = b'{"message_id":"m","thread_id":"t","text":"hello","external_account":"bot"}'
        adapter = ChannelWebhookAdapter(channel='email', secret='secret')
        signature = hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        with self.assertRaises(RuntimeError): adapter.receive(body, signature)


if __name__ == '__main__': unittest.main()
