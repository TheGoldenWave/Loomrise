import os, tempfile, unittest
from loomrise.configuration import ConfigurationPrincipal
from loomrise.customer_service import CustomerService, CustomerServiceApplication
from loomrise.durable_store import SqliteStore


class CustomerStatisticsTests(unittest.TestCase):
    def test_statistics_are_counts_and_keep_external_delivery_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'stats.db'))
            try:
                app = CustomerServiceApplication(CustomerService(store, None))
                principal = ConfigurationPrincipal(tenant_id='t', actor_id='o', role='owner', agent_ids=('a',))
                app.execute(principal=principal, action='channel.authorize', payload={'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot'})
                app.execute(principal=principal, action='channel.send', payload={'agent_id': 'a', 'channel': 'telegram', 'external_account': 'bot', 'message_id': 'm', 'thread_id': 't', 'text': 'hello'})
                value = app.execute(principal=principal, action='customer.statistics', payload={'agent_id': 'a'})
                self.assertTrue(value['ok']); self.assertEqual(value['result']['channel_messages']['telegram'], 1)
                self.assertIsNone(value['result']['response_latency_ms'])
            finally: store.close()


if __name__ == '__main__': unittest.main()
