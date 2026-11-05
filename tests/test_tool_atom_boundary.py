"""R3 tool Atom boundary: graph drafts reject before business execution."""

from __future__ import annotations

from dataclasses import asdict, replace
import unittest

from loomrise.contracts import ScenarioPack
from loomrise.service import ExecutionService


def graph_with_tool(pack: ScenarioPack) -> dict:
    tool = asdict(next(item for item in pack.tools if item.tool_id == "create_booking"))
    unit = {
        "unit_id": "tool-entry", "version": 1, "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}],
        "reads": [], "writes": [],
        "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
        "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 1,
        "body": {
            "kind": "tool",
            "tool_ref": {"tool_id": tool["tool_id"], "version": tool["version"]},
            "arguments": {"course_id": "data-analysis-101", "idempotency_key": "booking-1"},
        },
    }
    return {
        "persona": {"fields": {}}, "units": [unit],
        "tools": [tool], "g0_gates": [], "hard_rules": [], "task_blueprints": [],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph", "routing": {"mode": "deterministic"},
            "nodes": [{"id": "tool", "unit_ref": {"unit_id": "tool-entry", "version": 1}}],
            "entry": "tool.from_start",
            "edges": [{"id": "finish", "from": "tool.done", "to": "end", "condition": {}}],
            "on_event": [], "fallback": {"kind": "human"},
        },
    }


class ToolAtomBoundaryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_tool_rejection_does_not_enter_policy_or_business_write_path(self) -> None:
        pack = ScenarioPack.load("scenarios/course_consult_v1/pack.json")
        graph = graph_with_tool(pack)
        pack.agent_version = replace(
            pack.agent_version,
            version_id="course-consult-r3-tool-boundary-v1",
            orchestration=graph,
            unit_skill_bindings={"tool-entry": "course_consult_booking"},
        )
        service = ExecutionService(pack)

        result = await service.handle_text("预约", script=[])

        self.assertEqual(result.request.state.value, "failed")
        self.assertEqual(service.ledger.find("route.graph.diagnostic")[-1].payload["code"], "tool_atom_runtime_unavailable")
        self.assertFalse(service.ledger.find("permission.decision"))
        self.assertFalse(service.ledger.find("tool.call_start"))
        self.assertFalse(service.ledger.find("tool.outcome"))
        self.assertFalse(service.ledger.find("request.routed"))
        self.assertEqual(service.ledger.find("run.finished")[-1].payload["write_count"], 0)
        self.assertEqual(service._active, {})
        self.assertTrue(service.ledger.verify())


if __name__ == "__main__":
    unittest.main()
