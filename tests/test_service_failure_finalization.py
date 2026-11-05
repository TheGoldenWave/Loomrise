from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError

from loomrise.adapters.agentscope_runtime import ScriptedChatModel
from loomrise.contracts import ScenarioPack
from loomrise.durable_store import SqliteStore
from loomrise.service import ExecutionService


PRIVATE_PROVIDER_DETAIL = "credential-bearing provider response"


class FailingModel(ScriptedChatModel):
    async def _call_api(self, *args, **kwargs):
        raise APIConnectionError(
            message=PRIVATE_PROVIDER_DETAIL,
            request=httpx.Request("POST", "https://provider.invalid/v1/responses"),
        )


class WriteThenFailModel(ScriptedChatModel):
    async def _call_api(self, *args, **kwargs):
        if self.cursor < len(self.script):
            return await super()._call_api(*args, **kwargs)
        raise APIConnectionError(
            message=PRIVATE_PROVIDER_DETAIL,
            request=httpx.Request("POST", "https://provider.invalid/v1/responses"),
        )


class ServiceFailureFinalizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "loomrise.db")
        self.pack = ScenarioPack.load("scenarios/course_consult_v1/pack.json")

    def tearDown(self):
        self.tmp.cleanup()

    def make_service(self):
        store = SqliteStore(self.db_path, owner_id="failure-test")
        return ExecutionService(self.pack, store=store, owner_id="failure-test"), store

    async def test_model_connection_error_finishes_failed_run_without_provider_text(self):
        service, store = self.make_service()
        try:
            with patch("loomrise.service.build_model", return_value=FailingModel()):
                result = await service.handle_text("咨询课程", script=None)

            self.assertEqual(result.request.state.value, "failed")
            self.assertEqual(result.run_status.value, "failed")
            self.assertEqual(service._active, {})
            self.assertEqual(service.ledger.find("run.execution_failed")[-1].payload["failure_code"], "reply_generation_failed")
            self.assertNotIn(PRIVATE_PROVIDER_DETAIL, str(service.ledger.events))

            persisted = store.load_events(result.run_id)
            self.assertIn("run.execution_failed", [event.event_type for event in persisted])
            self.assertEqual(persisted[-1].event_type, "run.finished")
            self.assertEqual(persisted[-1].payload["request_state"], "failed")
            self.assertEqual(store.run_row(result.run_id)["status"], "failed")
        finally:
            store.close()

    async def test_provider_error_after_committed_write_preserves_success(self):
        service, store = self.make_service()
        model = WriteThenFailModel(script=[
            {"tool": "search_knowledge", "args": {"query": "数据分析入门 开班", "limit": 2}},
            {"tool": "create_booking", "args": {
                "course_id": "data-analysis-101",
                "learner_name": "李雷",
                "slot": "周二晚 20:00",
                "idempotency_key": "failure-after-write",
            }},
        ])
        try:
            with patch("loomrise.service.build_model", return_value=model):
                result = await service.handle_text(
                    "我想报名数据分析入门，帮我预约一下",
                    script=None,
                    ask_confirm=lambda calls: [True] * len(calls),
                )

            self.assertEqual(result.request.state.value, "success")
            self.assertEqual(result.run_status.value, "succeeded")
            self.assertEqual(result.write_count, 1)
            self.assertTrue(service.ledger.find("run.execution_failed"))
            finished = service.ledger.find("run.finished")[-1]
            self.assertEqual(finished.payload["request_state"], "success")
            self.assertEqual(finished.payload["result_ids"], result.written_result_ids)
            outbox_payload = json.loads(store.pending_outbox()[0]["payload_json"])
            self.assertEqual(outbox_payload["result_id"], result.written_result_ids[0])
            self.assertNotIn(PRIVATE_PROVIDER_DETAIL, str(service.ledger.events))
        finally:
            store.close()

    async def test_sqlite_finish_error_is_not_swallowed_during_failure_cleanup(self):
        service, store = self.make_service()
        try:
            with patch("loomrise.service.build_model", return_value=FailingModel()), patch.object(
                store, "finish_run", side_effect=sqlite3.OperationalError("disk I/O error")
            ):
                with self.assertRaisesRegex(sqlite3.OperationalError, "disk I/O error"):
                    await service.handle_text("咨询课程", script=None)
            self.assertEqual(service._active, {})
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
