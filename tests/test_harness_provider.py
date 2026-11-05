from __future__ import annotations

import importlib.util
import asyncio
import json
import unittest

from agentscope.message import TextBlock

from loomrise.adapters import harness
from loomrise.adapters.agentscope_runtime import ScriptedChatModel
from loomrise.diagnostics import (
    REPORT_SCHEMA_VERSION, PROVIDER_CONTRACT_HASH, PROVIDER_VERSIONS,
    PROVIDER_KIND_OFFLINE_SCRIPTED, PROVIDER_KIND_REAL_HARNESS,
)


SNAPSHOT = {
    "snapshot_id": "snapshot-fixture",
    "snapshot_hash": "fixture-hash",
    "limitations": ["limited_sample"],
    "runs": [],
    "cases": [],
}
REPORT = {
    "schema_version": REPORT_SCHEMA_VERSION,
    "status": "proposal",
    "findings": [],
    "insufficient_categories": ["knowledge", "routing", "loading", "policy", "tool", "rule"],
    "limitations": ["limited_sample"],
}
CONFIG = {
    "provider_id": "scripted-fixture",
    "model": "scripted-harness",
    "base_url": "https://provider.example.invalid/v1",
    "key": "local-test-credential",
    "deadline_seconds": 2,
    "max_output_tokens": 512,
}


class CapturingScriptedChatModel(ScriptedChatModel):
    def __init__(self, script):
        super().__init__(model_name=CONFIG["model"], script=script)
        self.seen_tools = []
        self.seen_messages = []

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        self.seen_tools.append(tools)
        self.seen_messages.append(messages)
        return await super()._call_api(model_name, messages, tools, tool_choice, **kwargs)


class WaitingScriptedChatModel(ScriptedChatModel):
    def __init__(self, started):
        super().__init__(model_name=CONFIG["model"])
        self.started = started

    async def _call_api(self, *args, **kwargs):
        self.started.set()
        await asyncio.Future()


def make_provider(script, *, model_class=CapturingScriptedChatModel, config=None):
    provider_type = getattr(harness, "AgentScopeDiagnosisProvider", None)
    if provider_type is None:
        return None, None
    model = model_class(script)
    return provider_type(config or CONFIG, model=model), model

class HarnessProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_diagnosis_harness_provider_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("loomrise.adapters.harness"))

    async def test_provider_has_one_read_only_tool_and_returns_confirmed_structured_report(self):
        model = CapturingScriptedChatModel([
            {"tool": "diagnosis_evidence"},
            {"text": json.dumps(REPORT)},
        ])
        provider_type = getattr(harness, "AgentScopeDiagnosisProvider", None)
        self.assertIsNotNone(provider_type, "diagnosis provider is missing")
        provider = provider_type(CONFIG, model=model)
        evidence_reads = []

        def read_evidence():
            evidence_reads.append(True)
            return dict(SNAPSHOT)

        result = await provider.run(
            snapshot=dict(SNAPSHOT),
            read_evidence=read_evidence,
            token_budget=8000,
            max_output_bytes=16384,
        )

        self.assertEqual(set(result), {"report", "usage", "provider_state"})
        self.assertEqual(result["report"], REPORT)
        self.assertEqual(result["provider_state"], "stopped")
        self.assertEqual(result["usage"]["output_tokens"], 128)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(model.seen_tools), 2)
        for tools in model.seen_tools:
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["function"]["name"], "diagnosis_evidence")
            self.assertEqual(tools[0]["function"]["parameters"]["properties"], {})
            self.assertFalse(tools[0]["function"]["parameters"]["additionalProperties"])
        self.assertEqual(len(evidence_reads), 4)
        self.assertNotIn(CONFIG["key"], json.dumps(provider.descriptor))

    async def test_provider_requires_explicit_credential_configuration(self):
        provider_type = getattr(harness, "AgentScopeDiagnosisProvider", None)
        self.assertIsNotNone(provider_type, "diagnosis provider is missing")
        with self.assertRaises(ValueError):
            provider_type({"model": CONFIG["model"]}, model=ScriptedChatModel(model_name=CONFIG["model"]))

    async def test_provider_rejects_query_or_fragment_in_base_url(self):
        provider_type = getattr(harness, "AgentScopeDiagnosisProvider", None)
        self.assertIsNotNone(provider_type, "diagnosis provider is missing")
        for suffix in ("?token=must-not-be-recorded", "#token=must-not-be-recorded"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                provider_type(
                    {**CONFIG, "base_url": f"https://provider.example.invalid/v1{suffix}"},
                    model=ScriptedChatModel(model_name=CONFIG["model"]),
                )

    async def test_provider_does_not_fall_back_to_scripted_model_without_injection(self):
        provider_type = getattr(harness, "AgentScopeDiagnosisProvider", None)
        self.assertIsNotNone(provider_type, "diagnosis provider is missing")
        provider = provider_type(CONFIG)
        self.assertEqual(provider.model.model, CONFIG["model"])
        self.assertNotIsInstance(provider.model, ScriptedChatModel)

    async def test_provider_rejects_invalid_json_and_schema(self):
        for text in ("not json", json.dumps({**REPORT, "extra": True})):
            with self.subTest(text=text):
                provider, _ = make_provider([
                    {"tool": "diagnosis_evidence"},
                    {"text": text},
                ])
                self.assertIsNotNone(provider, "diagnosis provider is missing")
                with self.assertRaises(ValueError):
                    await provider.run(
                        snapshot=dict(SNAPSHOT),
                        read_evidence=lambda: dict(SNAPSHOT),
                        token_budget=8000,
                        max_output_bytes=16384,
                    )

    async def test_provider_rejects_output_over_byte_limit(self):
        provider, _ = make_provider([
            {"tool": "diagnosis_evidence"},
            {"text": " " * 300},
        ])
        self.assertIsNotNone(provider, "diagnosis provider is missing")
        with self.assertRaises(ValueError):
            await provider.run(
                snapshot=dict(SNAPSHOT),
                read_evidence=lambda: dict(SNAPSHOT),
                token_budget=8000,
                max_output_bytes=256,
            )

    async def test_provider_rejects_a_second_tool_call_or_exceeding_model_calls(self):
        provider, model = make_provider([
            {"tool": "diagnosis_evidence"},
            {"tool": "diagnosis_evidence"},
        ])
        self.assertIsNotNone(provider, "diagnosis provider is missing")
        with self.assertRaises(ValueError):
            await provider.run(
                snapshot=dict(SNAPSHOT),
                read_evidence=lambda: dict(SNAPSHOT),
                token_budget=8000,
                max_output_bytes=16384,
            )
        self.assertLessEqual(len(model.calls), 2)

    async def test_provider_cancellation_does_not_claim_stop(self):
        started = asyncio.Event()
        provider, _ = make_provider([], model_class=lambda _: WaitingScriptedChatModel(started))
        self.assertIsNotNone(provider, "diagnosis provider is missing")
        task = asyncio.create_task(provider.run(
            snapshot=dict(SNAPSHOT),
            read_evidence=lambda: dict(SNAPSHOT),
            token_budget=8000,
            max_output_bytes=16384,
        ))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_config_cannot_self_report_provider_kind(self):
        # 即使注入脚本替身，调用方也不能自报真实 Provider 类别。
        with self.assertRaises(ValueError):
            harness.AgentScopeDiagnosisProvider(
                {**CONFIG, "provider_kind": PROVIDER_KIND_REAL_HARNESS},
                model=ScriptedChatModel(model_name=CONFIG["model"]),
            )

    async def test_injected_scripted_model_is_registered_as_offline_evidence(self):
        provider = harness.AgentScopeDiagnosisProvider(
            CONFIG, model=ScriptedChatModel(model_name=CONFIG["model"]))
        self.assertEqual(provider.descriptor["provider_kind"], PROVIDER_KIND_OFFLINE_SCRIPTED)
        self.assertEqual(provider.descriptor["contract_hash"], PROVIDER_CONTRACT_HASH)
        self.assertEqual(provider.descriptor["version"],
                         PROVIDER_VERSIONS[PROVIDER_KIND_OFFLINE_SCRIPTED])
        self.assertNotEqual(provider.descriptor["version"],
                            PROVIDER_VERSIONS[PROVIDER_KIND_REAL_HARNESS])


if __name__ == "__main__":
    unittest.main()
