import json
import os
import tempfile
import unittest

from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService
from tests.test_graph_service import graph_pack


class RunAgentScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_trusted_service_identity_is_saved_independently_of_routing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "scope.db")
            store = SqliteStore(database)
            try:
                service = ExecutionService(graph_pack(), store=store, agent_id="expert-a")
                result = await service.handle_text("hello", script=[{"text": "hello"}],
                                                   routing_state={"agent_id": "expert-b"})
                snapshot = json.loads(store.run_row(result.run_id)["snapshot_json"])
                self.assertEqual(snapshot["agent_id"], "expert-a")
            finally:
                store.close()
            restored = SqliteStore(database)
            try:
                model_calls = [event.payload for event in restored.load_events(result.run_id)
                               if event.event_type == "model.call_end"]
                self.assertEqual([call["model"] for call in model_calls], ["scripted-s1"])
                self.assertTrue(restored.verify_chain(result.run_id))
            finally:
                restored.close()


if __name__ == "__main__":
    unittest.main()
