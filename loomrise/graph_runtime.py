"""Interpreter for versioned routes and closed-set provider decisions.

Tool execution, business writes and durable RunEvent persistence remain owned
by ExecutionService. Provider decisions never grant those permissions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from copy import deepcopy
import json
import hashlib
import inspect
import math
import re
import time
from typing import Any, Callable

from .config_validation import CHANGED_TO_BLOCKED_REASON, KNOWN_EVENTS
from .graph_validation import _MATCHES_MAX_VALUE_LENGTH, _safe_matches_pattern
from .state_window import evaluate_state_window


@dataclass(frozen=True)
class RouteStep:
    kind: str
    target: str
    reason: str
    edge_id: str | None = None
    layer: tuple[str, ...] = ()
    source: str | None = None
    unit_id: str | None = None


@dataclass(frozen=True)
class _BoundaryJump:
    owner_path: tuple[str, ...]
    target: str


@dataclass
class RouteResult:
    status: str
    steps: list[RouteStep] = field(default_factory=list)
    selected_edges: list[str] = field(default_factory=list)
    fallback: str | None = None
    gate: str | None = None
    warnings: list[str] = field(default_factory=list)
    terminal_target: str | None = None
    terminal_unit_id: str | None = None
    terminal_node: dict[str, Any] | None = None
    node_dwell_samples: list[dict[str, Any]] = field(default_factory=list)
    waiting_on: str | None = None
    wait_timeout_ms: int | None = None
    wait_timeout_to: str | None = None
    cycle_counters: dict[str, int] = field(default_factory=dict)
    cycle_events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    message_cursor: int = 0
    continuation: dict[str, Any] = field(default_factory=dict)
    waiting_path: tuple[str, ...] = ()
    # Runtime diagnostics are route evidence, not business outcomes.  In R3 a
    # tool atom is deliberately rejected before any ToolPolicy/Sandbox or
    # durable side-effect boundary is entered; callers can inspect why.
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    completion_checks: list[dict[str, Any]] = field(default_factory=list)
    completion_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    _reserve_cycle: Callable[..., Any] | None = field(default=None, repr=False)


class GraphRuntimeError(ValueError):
    pass


class GraphRuntime:
    """Check deterministic conditions and bounded provider decisions."""

    def __init__(self, config: Mapping[str, Any], *, selector: Callable[..., Any] | None = None,
                 completion_evaluator: Callable[..., Any] | None = None) -> None:
        orchestration = config.get("orchestration")
        if not isinstance(orchestration, Mapping) or orchestration.get("schema_version") != "unit-graph-v1":
            raise GraphRuntimeError("only unit-graph-v1 can be interpreted")
        self.config = config
        self.units = {
            unit.get("unit_id"): unit
            for unit in config.get("units", [])
            if isinstance(unit, Mapping) and isinstance(unit.get("unit_id"), str)
        }
        self.selector = selector
        self.completion_evaluator = completion_evaluator

    @staticmethod
    def _record_node_dwell(result: RouteResult, node_id: str, layer: tuple[str, ...], started_ns: int) -> None:
        elapsed_ms = max(0, round((time.perf_counter_ns() - started_ns) / 1_000_000))
        result.node_dwell_samples.append({
            "node_id": node_id,
            "layer": list(layer),
            "dwell_ms": elapsed_ms,
        })

    @classmethod
    def _measure_node_dwell(cls, result: RouteResult, node_id: str, layer: tuple[str, ...],
                            operation: Callable[[], Any]) -> Any:
        started_ns = time.perf_counter_ns()
        try:
            return operation()
        finally:
            cls._record_node_dwell(result, node_id, layer, started_ns)

    @staticmethod
    def _set_terminal_node(result: RouteResult, node_id: str, unit: Mapping[str, Any],
                           exit_port: str, layer: tuple[str, ...], *, evidence_kind: str,
                           step_index: int, edge_id: str | None = None) -> None:
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            return
        result.terminal_target = f"{node_id}.{exit_port}"
        result.terminal_unit_id = unit_id
        result.terminal_node = {
            "node_id": node_id,
            "unit_id": unit_id,
            "exit_port": exit_port,
            "layer": list(layer),
            "evidence_kind": evidence_kind,
            "step_index": step_index,
            "edge_id": edge_id,
        }

    def requires_service_cycle(self) -> bool:
        """生产执行须为所有配置了环/默认单元的路径提供可信周期。"""
        def condition_uses_cycle(condition: Any) -> bool:
            if not isinstance(condition, Mapping):
                return False
            state = condition.get('state')
            if isinstance(state, Mapping) and state.get('window') == 'cycle':
                return True
            return any(
                isinstance(condition.get(key), list)
                and any(condition_uses_cycle(child) for child in condition[key])
                for key in ('all_of', 'any_of', 'none_of', 'all', 'any', 'not')
            )

        root = self.config['orchestration']
        conditions = [gate.get('when') for gate in self.config.get('g0_gates', [])
                      if isinstance(gate, Mapping)]
        owners = [root, *self.units.values()]
        for owner in owners:
            body = owner.get('body') if owner is not root else None
            graph = body if isinstance(body, Mapping) and body.get('kind') == 'graph' else owner
            conditions.extend(edge.get('condition') for edge in graph.get('edges', [])
                              if isinstance(edge, Mapping))
            handlers = list(owner.get('on_event', []))
            if graph is not owner:
                handlers.extend(graph.get('on_event', []))
            conditions.extend(handler.get('when') for handler in handlers if isinstance(handler, Mapping))
            conditions.extend(port.get('completion', {}).get('deterministic')
                              for port in owner.get('exit_ports', [])
                              if isinstance(port, Mapping)
                              and isinstance(port.get('completion'), Mapping))
            if isinstance(body, Mapping) and body.get('kind') == 'judge':
                conditions.append(body.get('condition'))
        if any(condition_uses_cycle(condition) for condition in conditions):
            return True
        for owner in owners:
            fallback = owner.get('fallback', {})
            if isinstance(fallback, Mapping) and fallback.get('kind') == 'default_unit':
                return True
            body = owner.get('body')
            graph = body if isinstance(body, Mapping) and body.get('kind') == 'graph' else owner
            if any(isinstance(edge, Mapping) and self._is_loop(edge) for edge in graph.get('edges', [])):
                return True
        return False

    def cycle_budget(self, kind: str, layer: tuple[str, ...], identity: str) -> tuple[int, str | None]:
        """Resolve a reservation against the same frozen local graph contract."""
        owner = graph = self.config['orchestration']
        for node_id in layer:
            owner = self._unit(self._node(graph, node_id))
            if owner is None or not isinstance(owner.get('body'), Mapping) or owner['body'].get('kind') != 'graph':
                raise GraphRuntimeError('cycle budget layer is outside the pinned graph')
            graph = owner['body']
        if kind == 'loop':
            edge = next((edge for edge in graph.get('edges', []) if edge.get('id') == identity), None)
            if edge is not None and self._is_loop(edge) and edge.get('window') == 'cycle':
                limit = edge['max_rounds']
                if type(limit) is int and limit > 0 and isinstance(edge.get('counter'), str):
                    return limit, edge['counter']
        elif kind == 'fallback':
            fallback = owner.get('fallback', {})
            if (fallback.get('kind') == 'default_unit' and fallback.get('target') == identity
                    and identity.count('.') == 1):
                node_id, entry = identity.split('.')
                unit = self._unit(self._node(graph, node_id))
                if unit and any(port.get('port') == entry for port in unit.get('entry_ports', [])):
                    limit = unit.get('max_rounds')
                    if type(limit) is int and limit > 0:
                        return limit, None
        raise GraphRuntimeError('cycle budget identity is not declared in the pinned graph contract')

    def route(self, state: Mapping[str, Any], *, max_steps: int = 64,
              cycle_counters: Mapping[str, Any] | None = None,
              continuation: Mapping[str, Any] | None = None,
              reserve_cycle: Callable[..., Any] | None = None) -> RouteResult:
        checkpoint = deepcopy(dict(continuation or {}))
        counters = dict(cycle_counters if cycle_counters is not None else checkpoint.get("cycle_counters", {}))
        if any(not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0
               for key, value in counters.items()):
            raise GraphRuntimeError("cycle_counters must map stable keys to non-negative integers")
        result = RouteResult(status="routed", cycle_counters=counters, _reserve_cycle=reserve_cycle)
        decisions = checkpoint.get('completion_decisions', {})
        if not isinstance(decisions, Mapping):
            raise GraphRuntimeError('invalid model completion checkpoint')
        result.completion_decisions = dict(decisions)
        counters = result.cycle_counters
        # Derived atom facts are local to this route and never mutate the request snapshot.
        saved_state = dict(checkpoint.get("state", {}))
        for transient in ("event", "event_attributes", "state_window_counts", "__wait_timeout_to",
                          "__wait_resume_path", "__wait_event_consumed", "__wait_timeout_consumed"):
            saved_state.pop(transient, None)
        # Completed pure steps own their committed facts. Repeated original
        # request input cannot overwrite a judge result during continuation.
        working_state = {**state, **saved_state}
        for context_field in ("input", "recent_turns"):
            if context_field in state:
                working_state[context_field] = state[context_field]
        frames = checkpoint.get("frames", {})
        completed_waits = checkpoint.get("completed_waits", {})
        result.messages = checkpoint.get("messages", [])
        result.message_cursor = checkpoint.get("message_cursor", 0)
        # Frames retain route positions and computed facts. Verified completion
        # decisions are reused only for the same criterion and input hash.
        result.continuation = {"state": working_state, "frames": frames,
                               "completed_waits": completed_waits, "messages": result.messages,
                               "cycle_counters": counters,
                               "fallback_counts": checkpoint.get('fallback_counts', {}),
                               'completion_decisions': result.completion_decisions}
        gate = self._gate(working_state)
        if gate is not None:
            result.status, result.gate = "gated", gate
            result.steps.append(RouteStep("g0", gate, "deterministic gate matched"))
            return result
        root = self.config["orchestration"]
        missing_inputs = self._missing_fields(root.get("input_fields", []), working_state)
        if missing_inputs:
            return self._fallback(result, root, f"root input fields are not ready: {', '.join(missing_inputs)}")
        event_target = self._event_target(root, working_state)
        event_consumed = {"value": event_target is not None}
        if event_target is not None:
            frames.clear()
            completed_waits.clear()
            result.steps.append(RouteStep("event", event_target, "boundary event has priority over edges"))
            if event_target.startswith("self."):
                return self._fallback(result, root, "root event cannot target self")
            current = self._normalize_entry(event_target)
        else:
            current = frames.get("[]", {}).get("current", root.get("entry"))
        graph = root
        layer: tuple[str, ...] = ()
        for _ in range(max_steps):
            frame = self._frame(frames, layer, current)
            if current == "end":
                result.status = "completed"
                result.continuation = {}
                return result
            if not isinstance(current, str) or current.count(".") != 1:
                return self._fallback(result, graph, "invalid graph entry")
            node_id, port = current.split(".")
            node = self._node(graph, node_id)
            if node is None:
                return self._fallback(result, graph, f"unknown node {node_id}")
            unit = self._unit(node)
            if unit is None:
                return self._fallback(result, graph, f"unresolved unit {node_id}")
            missing = self._entry_missing(unit, port, working_state)
            if missing:
                return self._fallback(result, graph, f"entry {node_id}.{port} requires unavailable fields: {', '.join(missing)}")
            result.steps.append(RouteStep("enter", f"{node_id}.{port}", "entry selected", layer=layer))
            body = unit.get("body")
            if isinstance(body, Mapping) and body.get("kind") == "graph":
                node_work_started_ns = time.perf_counter_ns()
                unit_event = None if event_consumed["value"] else self._matching_unit_event(unit, working_state, "self")
                if unit_event is not None:
                    self._record_node_dwell(result, node_id, layer, node_work_started_ns)
                    nested = unit_event.get("goto")
                    event_consumed["value"] = True
                    result.steps.append(RouteStep("event", str(nested), "Unit self boundary event matched", layer=layer))
                else:
                    nested = self._measure_node_dwell(
                        result, node_id, layer,
                        lambda: self._run_nested(
                            body, unit, port, working_state, result, layer + (node_id,),
                            max_steps - len(result.steps), counters,
                            owner_path=layer + (node_id,), event_consumed=event_consumed,
                            frames=frames, completed_waits=completed_waits,
                            active_events=self._subtree_events(unit, layer + (node_id,)),
                        ),
                    )
                if nested == "waiting":
                    result.status = "waiting"
                    return result
                if nested is None:
                    target = self._default_target(graph, graph, result, layer, 'nested Unit did not complete')
                    if target is not None:
                        current = target
                        continue
                    return self._fallback(result, graph, f"nested unit {node_id} did not complete")
                if nested.startswith("self."):
                    self._clear_unit(frames, completed_waits, layer + (node_id,))
                    exit_port = nested[5:]
                    if not self._exit_port_complete(unit, exit_port, working_state, result):
                        return self._fallback(result, graph, f"completion condition failed for {node_id}.{exit_port}")
                    edge = self._choose_edge(graph, f"{node_id}.{exit_port}", working_state, result)
                    if edge is None:
                        target = self._default_target(graph, graph, result, layer, 'no matching edge')
                        if target is not None:
                            current = target
                            continue
                        return self._fallback(result, graph, f"no matching edge from {node_id}.{exit_port}")
                    edge_id = str(edge.get("id", ""))
                    target = edge.get("to")
                    result.selected_edges.append(edge_id)
                    if self._is_loop(edge):
                        counter_field = edge.get("counter")
                        if not isinstance(counter_field, str):
                            return self._fallback(result, graph, f"bounded cycle {edge_id} has no counter field")
                        if not self._advance_loop(result, edge, layer, working_state):
                            target = edge.get("exit")
                            result.steps.append(RouteStep("cycle_limit", str(target), "cycle max_rounds reached", edge_id, layer,
                                                          f"{node_id}.{exit_port}", unit.get("unit_id")))
                        else:
                            result.steps.append(RouteStep("edge", str(target), "bounded cycle", edge_id, layer,
                                                          f"{node_id}.{exit_port}", unit.get("unit_id")))
                    else:
                        result.steps.append(RouteStep("edge", str(target), "nested unit completed", edge_id, layer,
                                                      f"{node_id}.{exit_port}", unit.get("unit_id")))
                    if target == "end":
                        self._set_terminal_node(result, node_id, unit, exit_port, layer,
                                                evidence_kind=result.steps[-1].kind,
                                                step_index=len(result.steps) - 1, edge_id=edge_id)
                    current = target
                    continue
                current = nested
                continue
            node_work_started_ns = time.perf_counter_ns()
            unit_event = None if event_consumed["value"] else self._matching_unit_event(unit, working_state, "self")
            if unit_event is not None:
                self._record_node_dwell(result, node_id, layer, node_work_started_ns)
                event_goto = unit_event.get("goto")
                event_consumed["value"] = True
                result.steps.append(RouteStep("event", str(event_goto), "Unit self boundary event matched", layer=layer))
                exit_port = event_goto[5:] if isinstance(event_goto, str) and event_goto.startswith("self.") else None
                atom_status = "ok"
            else:
                atom_status = self._measure_node_dwell(
                    result, node_id, layer,
                    lambda: (
                        self._wait_status(unit, working_state, result, layer + (node_id,), completed_waits)
                        if frame.get("phase") == "wait"
                        else self._execute_atom(unit, body, working_state, result, f"{node_id}.{port}", layer,
                                                completed_waits=completed_waits)
                    ),
                )
                if atom_status == "waiting":
                    frame["phase"] = "wait"
                    result.status = "waiting"
                    return result
            if isinstance(atom_status, str) and atom_status.startswith("timeout:"):
                timeout_target = atom_status[8:]
                result.steps.append(RouteStep("wait_timeout", timeout_target, "wait timeout branch", layer=layer,
                                              source=f"{node_id}.{port}", unit_id=unit.get("unit_id")))
                if timeout_target == "end":
                    result.status = "completed"
                    self._set_terminal_node(result, node_id, unit, port, layer, evidence_kind="wait_timeout",
                                            step_index=len(result.steps) - 1)
                    return result
                if not timeout_target.startswith("self."):
                    return self._fallback(result, graph, f"invalid wait timeout target {timeout_target}")
                exit_port = timeout_target[5:]
            else:
                exit_port = None
                if atom_status != "ok":
                    return self._fallback(result, graph, f"atom execution failed for {node_id}.{port}")
            if exit_port is None:
                exit_port = self._choose_exit(unit, port, working_state, result)
            if exit_port is None:
                target = self._default_target(graph, graph, result, layer, 'no completed exit')
                if target is not None:
                    current = target
                    continue
                return self._fallback(result, graph, f"no completion for {node_id}.{port}")
            if not self._exit_port_complete(unit, exit_port, working_state, result):
                return self._fallback(result, graph, f"completion condition failed for {node_id}.{exit_port}")
            self._clear_unit(frames, completed_waits, layer + (node_id,))
            frame["phase"] = "enter"
            source = f"{node_id}.{exit_port}"
            edge = self._choose_edge(graph, source, working_state, result)
            if edge is None:
                target = self._default_target(graph, graph, result, layer, 'no matching edge')
                if target is not None:
                    current = target
                    continue
                return self._fallback(result, graph, f"no matching edge from {source}")
            edge_id = str(edge.get("id", ""))
            result.selected_edges.append(edge_id)
            target = edge.get("to")
            if self._is_loop(edge):
                counter_field = edge.get("counter")
                if not isinstance(counter_field, str):
                    return self._fallback(result, graph, f"bounded cycle {edge_id} has no counter field")
                if not self._advance_loop(result, edge, layer, working_state):
                    target = edge.get("exit")
                    result.steps.append(RouteStep("cycle_limit", str(target), "cycle max_rounds reached", edge_id, layer,
                                                  source, unit.get("unit_id")))
                else:
                    result.steps.append(RouteStep("edge", str(target), "bounded cycle", edge_id, layer,
                                                  source, unit.get("unit_id")))
            else:
                result.steps.append(RouteStep("edge", str(target), "condition matched", edge_id, layer,
                                              source, unit.get("unit_id")))
            if target == "end":
                self._set_terminal_node(result, node_id, unit, exit_port, layer,
                                        evidence_kind=result.steps[-1].kind,
                                        step_index=len(result.steps) - 1, edge_id=edge_id)
            if isinstance(target, str) and target.startswith("self."):
                return target
            current = target
        result.status = "cycle_limit"
        result.fallback = "human"
        result.warnings.append("route exceeded max_steps; no business completion claimed")
        return result

    def route_and_emit(
        self,
        state: Mapping[str, Any],
        emit: Callable[..., Any],
        *,
        max_steps: int = 64,
        cycle_counters: Mapping[str, Any] | None = None,
        continuation: Mapping[str, Any] | None = None,
        reserve_cycle: Callable[..., Any] | None = None,
    ) -> RouteResult:
        """Persist decision facts through the caller's RunEvent emitter.

        The callback is expected to be the current Run-scoped ``emit`` closure;
        this adapter cannot create request/run identities or report business
        side effects. Event payloads contain route decisions only.
        """
        started = time.perf_counter()
        result = self.route(state, max_steps=max_steps, cycle_counters=cycle_counters,
                            continuation=continuation, reserve_cycle=reserve_cycle)
        emit("route.graph.started", schema_version="unit-graph-v1")
        for index, step in enumerate(result.steps):
            emit(
                "route.graph.step",
                step_index=index,
                kind=step.kind,
                target=step.target,
                reason=step.reason,
                edge_id=step.edge_id,
                layer=list(step.layer),
                source=step.source,
                unit_id=step.unit_id,
            )
        for diagnostic in result.diagnostics:
            # This is a route-level rejection record.  It intentionally has no
            # result_id or business write fields: R4 owns real tool execution
            # and unknown-result reconciliation.
            emit("route.graph.diagnostic", **diagnostic)
        for check in result.completion_checks:
            emit('route.graph.completion', **check)
        for event in result.cycle_events if reserve_cycle is None else []:
            emit("route.graph.cycle", edge_id=event["edge_id"], layer=event["layer"],
                 counter=event["counter"], cycle_count=event["count"], max_rounds=event["max_rounds"])
        emit(
            "route.graph.finished",
            route_status=result.status,
            selected_edges=list(result.selected_edges),
            fallback=result.fallback,
            gate=result.gate,
            warnings=list(result.warnings),
            waiting_on=result.waiting_on,
            wait_timeout_ms=result.wait_timeout_ms,
            wait_timeout_to=result.wait_timeout_to,
            waiting_path=list(result.waiting_path),
            cycle_counters=dict(result.cycle_counters),
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            telemetry_schema_version="graph-telemetry-v1",
            terminal_node=result.terminal_node,
            node_dwell_samples=list(result.node_dwell_samples),
        )
        return result

    def _run_nested(
        self,
        graph: Mapping[str, Any],
        owner: Mapping[str, Any],
        owner_entry: str,
        state: dict[str, Any],
        result: RouteResult,
        layer: tuple[str, ...],
        budget: int,
        counters: dict[str, int],
        *,
        owner_path: tuple[str, ...],
        event_consumed: dict[str, bool],
        frames: dict[str, Any],
        completed_waits: dict[str, list[int]],
        active_events: tuple[tuple[tuple[str, ...], Mapping[str, Any]], ...] = (),
    ) -> str | _BoundaryJump | None:
        entry = next((port.get("goto") for port in owner.get("entry_ports", []) if isinstance(port, Mapping) and port.get("port") == owner_entry), None)
        if not isinstance(entry, str):
            return None
        current = frames.get(json.dumps(list(layer)), {}).get("current", entry)
        owner_wait_completed = False
        for _ in range(max(1, budget)):
            frame = self._frame(frames, layer, current)
            if current.startswith("self."):
                if not self._exit_port_complete(owner, current[5:], state, result):
                    result.steps.append(RouteStep('completion_failed', f'{layer[-1]}.{current[5:]}',
                                                  'Unit exit completion condition failed', layer=layer[:-1]))
                    target = self._default_target(owner, graph, result, layer, 'owner completion not satisfied')
                    if target is not None:
                        current = target
                        continue
                    return None
                if not owner_wait_completed:
                    wait_status = self._wait_status(owner, state, result, owner_path, completed_waits)
                    if wait_status == "waiting":
                        return "waiting"
                    if wait_status.startswith("timeout:"):
                        target = wait_status[8:]
                        if not self._wait_target_valid(owner, target):
                            raise GraphRuntimeError(f"invalid wait timeout target {target}")
                        owner_wait_completed = True
                        result.steps.append(RouteStep("wait_timeout", target, "graph wait timeout branch", layer=layer))
                        current = target
                        continue
                    if wait_status != "ok":
                        return None
                return current
            if current == "end":
                return "end"
            parts = current.split(".")
            if len(parts) != 2:
                return None
            node_id, port = parts
            node = self._node(graph, node_id)
            unit = self._unit(node) if node else None
            if unit is None:
                return None
            missing = self._entry_missing(unit, port, state)
            if missing:
                result.steps.append(RouteStep("requires_failed", current, f"unavailable fields: {', '.join(missing)}", layer=layer))
                return None
            result.steps.append(RouteStep("enter", current, "nested entry selected", layer=layer))
            node_work_started_ns = time.perf_counter_ns()
            unit_event = None if event_consumed["value"] else self._matching_unit_event(unit, state, "self")
            if unit_event is not None:
                self._record_node_dwell(result, node_id, layer, node_work_started_ns)
                event_goto = unit_event.get("goto")
                event_consumed["value"] = True
                result.steps.append(RouteStep("event", str(event_goto), "Unit self boundary event matched", layer=layer))
                exit_port = event_goto[5:] if isinstance(event_goto, str) and event_goto.startswith("self.") else None
            else:
                subtree_match = None
                if not event_consumed["value"]:
                    scope_paths = list(dict.fromkeys(scope_path for scope_path, _ in active_events))
                    for scope_path in reversed(scope_paths):
                        subtree_match = next((entry for entry in active_events
                                              if entry[0] == scope_path and self._event_handler_matches(entry[1], state)), None)
                        if subtree_match is not None:
                            break
                if subtree_match is not None:
                    self._record_node_dwell(result, node_id, layer, node_work_started_ns)
                    scope_path, handler = subtree_match
                    target = handler["goto"]
                    event_consumed["value"] = True
                    result.steps.append(RouteStep("event", target, "Unit subtree boundary event matched", layer=layer))
                    if scope_path != owner_path:
                        return _BoundaryJump(scope_path, target)
                    if target.startswith("self."):
                        return target
                    current = target
                    continue

                body = unit.get("body")
                if isinstance(body, Mapping) and body.get("kind") == "graph":
                    nested = self._measure_node_dwell(
                        result, node_id, layer,
                        lambda: self._run_nested(
                            body, unit, port, state, result, layer + (node_id,), max(1, budget - 1), counters,
                            owner_path=layer + (node_id,), event_consumed=event_consumed,
                            frames=frames, completed_waits=completed_waits,
                            active_events=active_events + self._subtree_events(unit, layer + (node_id,)),
                        ),
                    )
                    if isinstance(nested, _BoundaryJump):
                        if nested.owner_path != owner_path:
                            return nested
                        if nested.target.startswith("self."):
                            return nested.target
                        current = nested.target
                        continue
                    if nested == "waiting":
                        return "waiting"
                    if nested is None or not nested.startswith("self."):
                        target = self._default_target(owner, graph, result, layer, 'nested Unit did not complete')
                        if target is not None:
                            current = target
                            continue
                        return None
                    exit_port = nested[5:]
                else:
                    atom_status = self._measure_node_dwell(
                        result, node_id, layer,
                        lambda: (
                            self._wait_status(unit, state, result, layer + (node_id,), completed_waits)
                            if frame.get("phase") == "wait"
                            else self._execute_atom(unit, body, state, result, current, layer,
                                                    completed_waits=completed_waits)
                        ),
                    )
                    if atom_status == "waiting":
                        frame["phase"] = "wait"
                        return "waiting"
                    if isinstance(atom_status, str) and atom_status.startswith("timeout:"):
                        timeout_target = atom_status[8:]
                        result.steps.append(RouteStep("wait_timeout", timeout_target, "wait timeout branch", layer=layer))
                        if timeout_target == "end":
                            return "self." + str(unit.get("exit_ports", [{}])[0].get("port", "done"))
                        if not timeout_target.startswith("self."):
                            return None
                        exit_port = timeout_target[5:]
                    elif atom_status != "ok":
                        return None
                    else:
                        exit_port = self._choose_exit(unit, port, state, result)
            if exit_port is None:
                target = self._default_target(owner, graph, result, layer, 'no completed exit')
                if target is not None:
                    current = target
                    continue
                return None
            if not self._exit_port_complete(unit, exit_port, state, result):
                result.steps.append(RouteStep("completion_failed", f"{node_id}.{exit_port}",
                                              "Unit exit completion condition failed", layer=layer))
                return None
            self._clear_unit(frames, completed_waits, layer + (node_id,))
            frame["phase"] = "enter"
            edge = self._choose_edge(graph, f"{node_id}.{exit_port}", state, result)
            if edge is None:
                target = self._default_target(owner, graph, result, layer, 'no matching edge')
                if target is not None:
                    current = target
                    continue
                return None
            target = edge.get("to")
            result.selected_edges.append(str(edge.get("id", "")))
            edge_id = str(edge.get("id", ""))
            if self._is_loop(edge):
                counter_field = edge.get("counter")
                if not isinstance(counter_field, str) or not isinstance(state, dict):
                    return None
                if not self._advance_loop(result, edge, layer, state):
                    target = edge.get("exit")
                    result.steps.append(RouteStep("cycle_limit", str(target), "cycle max_rounds reached", edge_id, layer,
                                                  f"{node_id}.{exit_port}", unit.get("unit_id")))
                else:
                    result.steps.append(RouteStep("edge", str(target), "bounded cycle", edge_id, layer,
                                                  f"{node_id}.{exit_port}", unit.get("unit_id")))
            else:
                result.steps.append(RouteStep("edge", str(target), "nested condition matched", edge_id, layer,
                                              f"{node_id}.{exit_port}", unit.get("unit_id")))
            if target == "end":
                self._set_terminal_node(result, node_id, unit, exit_port, layer,
                                        evidence_kind=result.steps[-1].kind,
                                        step_index=len(result.steps) - 1, edge_id=edge_id)
            current = target
        return None

    @staticmethod
    def _subtree_events(unit: Mapping[str, Any], owner_path: tuple[str, ...]) -> tuple[tuple[tuple[str, ...], Mapping[str, Any]], ...]:
        return tuple((owner_path, handler) for handler in unit.get("on_event", [])
                     if isinstance(handler, Mapping) and handler.get("scope") == "subtree")

    def _event_handler_matches(self, handler: Mapping[str, Any], state: Mapping[str, Any]) -> bool:
        if handler.get("event") != state.get("event"):
            return False
        return "when" not in handler or self._condition(handler.get("when"), state)

    def _choose_edge(self, graph: Mapping[str, Any], source: str, state: Mapping[str, Any], result: RouteResult) -> Mapping[str, Any] | None:
        candidates = [edge for edge in graph.get("edges", []) if isinstance(edge, Mapping) and edge.get("from") == source]
        mode = graph.get("routing", {}).get("mode") if isinstance(graph.get("routing"), Mapping) else None
        eligible = [edge for edge in candidates if self._condition(edge.get("condition", {}), state, allow_model=mode in ("hybrid", "llm"))]
        if mode == "deterministic":
            return eligible[0] if eligible else None
        if mode == "hybrid" and not eligible:
            return None
        closed_set = eligible
        if closed_set and self.selector:
            try:
                decision = self.selector(deepcopy(closed_set), deepcopy(state))
            except Exception as exc:
                raise GraphRuntimeError('graph routing provider failed') from exc
            chosen, reason = self._verify_selection(decision, closed_set, state)
            if chosen is not None:
                result.warnings.append("G1 choice accepted from a closed set with validated margin and evidence")
                return chosen
            result.warnings.append(f"G1 rejected; G2 fallback: {reason}")
        return None

    def _verify_selection(self, decision: Any, candidates: list[Mapping[str, Any]], state: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str]:
        if not isinstance(decision, Mapping):
            return None, "selection response is not an object"
        edge_id = decision.get("edge_id")
        chosen = next((edge for edge in candidates if edge.get("id") == edge_id), None)
        if chosen is None:
            return None, "selected edge is outside the closed set"
        scores = decision.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != {str(edge.get("id")) for edge in candidates}:
            return None, "scores must cover every closed-set candidate exactly"
        if any(not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) for score in scores.values()):
            return None, "scores must be finite numbers"
        ranked = sorted(scores.values(), reverse=True)
        margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
        if margin < 0.15:
            return None, "candidate margin below 0.15"
        if scores[str(edge_id)] != ranked[0]:
            return None, "selected edge is not the top-scoring candidate"
        evidence = decision.get("evidence")
        if not isinstance(evidence, Mapping):
            return None, "verifiable evidence is missing"
        fields = evidence.get("fields", [])
        if not isinstance(fields, list) or any(not isinstance(field, str) or not self._read(state, field)[1] for field in fields):
            return None, "evidence refers to a field that is not present in state"
        utterance = evidence.get("utterance")
        recent = state.get("recent_turns", [])
        if (utterance is not None and not isinstance(utterance, str)) or (
                utterance and (not isinstance(recent, list) or not any(isinstance(turn, str) and utterance in turn for turn in recent))):
            return None, "evidence utterance is not present in recent turns"
        if not fields and not utterance:
            return None, "evidence must identify a present field or recent utterance"
        return chosen, "accepted"

    def _choose_exit(self, unit: Mapping[str, Any], entry: str, state: Mapping[str, Any], result: RouteResult) -> str | None:
        ports = [port for port in unit.get("exit_ports", []) if isinstance(port, Mapping)]
        for port in ports:
            completion = port.get("completion", {})
            if not isinstance(completion, Mapping):
                continue
            port_id = port.get('port')
            if isinstance(port_id, str) and self._exit_port_complete(unit, port_id, state, result):
                return port_id
        return None

    def _exit_port_complete(self, unit: Mapping[str, Any], exit_port: str, state: Mapping[str, Any], result: RouteResult) -> bool:
        port = next((item for item in unit.get("exit_ports", [])
                     if isinstance(item, Mapping) and item.get("port") == exit_port), None)
        if port is None:
            return False
        completion = port.get("completion", {})
        if not isinstance(completion, Mapping):
            return False
        condition = completion.get("deterministic")
        if condition is not None and not self._condition(condition, state):
            return False
        if 'llm' not in completion:
            return True
        criterion = completion['llm']
        if not isinstance(criterion, str) or not criterion.strip():
            raise GraphRuntimeError('model completion requires a resolved text criterion')
        check = {'unit_ref': {'unit_id': unit['unit_id'], 'version': unit['version']},
                 'exit_port': exit_port, 'criterion': criterion, 'choices': ['complete', 'incomplete']}
        if any(not isinstance(key, str) for key in state):
            raise GraphRuntimeError('model completion state requires string field names')
        visible = {key: value for key, value in state.items() if not key.startswith('__')}
        try:
            serialized = json.dumps([check, visible], sort_keys=True, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise GraphRuntimeError('model completion state must contain finite JSON values') from exc
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        cached = result.completion_decisions.get(fingerprint)
        if cached is not None:
            if (not isinstance(cached, Mapping) or cached.get('input_hash') != fingerprint
                    or type(cached.get('satisfied')) is not bool or cached.get('unit_ref') != check['unit_ref']):
                raise GraphRuntimeError('invalid model completion checkpoint')
            return cached.get('satisfied') is True
        if self.completion_evaluator is None:
            raise GraphRuntimeError('model completion provider is unavailable')
        try:
            response = self.completion_evaluator(deepcopy(check), deepcopy(visible))
        except Exception as exc:
            raise GraphRuntimeError('model completion provider failed') from exc
        if inspect.isawaitable(response):
            if inspect.iscoroutine(response):
                response.close()
            raise GraphRuntimeError('model completion provider must return a synchronous decision')
        proposed = dict(response) if isinstance(response, Mapping) else {}
        proposed['edge_id'] = proposed.get('decision')
        chosen, reason = self._verify_selection(proposed, [{'id': 'complete'}, {'id': 'incomplete'}], visible)
        satisfied = chosen is not None and chosen['id'] == 'complete'
        evidence = {key: proposed['evidence'][key] for key in ('fields', 'utterance')
                    if key in proposed['evidence']} if chosen is not None else None
        record = {**check, 'input_hash': fingerprint, 'satisfied': satisfied,
                  'accepted': chosen is not None, 'decision': chosen['id'] if chosen else None,
                  'reason': reason, 'evidence': deepcopy(evidence),
                  'scores': dict(proposed['scores']) if chosen is not None else None}
        metadata = proposed.get('model_evidence')
        if isinstance(metadata, Mapping):
            record['model_evidence'] = {
                key: deepcopy(metadata[key]) for key in ('model', 'response_id', 'usage', 'duration_ms', 'provider')
                if key in metadata
            }
        result.completion_decisions[fingerprint] = record
        result.completion_checks.append(record)
        return satisfied

    def _execute_atom(
        self,
        unit: Mapping[str, Any],
        body: Any,
        state: dict[str, Any],
        result: RouteResult,
        location: str,
        layer: tuple[str, ...],
        *,
        completed_waits: dict[str, list[int]],
        ) -> str:
        """Execute the currently supported pure atom semantics."""
        if not isinstance(body, Mapping):
            return "failed"
        kind = body.get("kind")
        if kind == "tool":
            diagnostic = self._tool_atom_diagnostic(body)
            result.diagnostics.append(diagnostic)
            tool_id = diagnostic.get("tool_id") or "<unknown>"
            version = diagnostic.get("tool_version") or "<unknown>"
            result.steps.append(
                RouteStep(
                    "tool_rejected",
                    f"{tool_id}@{version}",
                    diagnostic["code"],
                    layer=layer,
                ),
            )
            return "failed"
        if kind == "say":
            if (not isinstance(body.get("verbatim_reason"), str)
                    or not isinstance(body.get("text"), str) or not body["text"].strip()):
                return "failed"
            result.messages.append({"unit_id": unit.get("unit_id"), "target": location,
                                    "layer": list(layer), "text": body["text"]})
            status = self._wait_status(unit, state, result, layer + (location.split('.')[0],), completed_waits)
            return status
        if kind != "judge":
            return "failed"
        field = body.get("result_field")
        fields = self.config.get("persona", {}).get("fields", {}) if isinstance(self.config.get("persona"), Mapping) else {}
        declaration = fields.get(field) if isinstance(fields, Mapping) and isinstance(field, str) else None
        declared_writes = unit.get("writes")
        if (
            not isinstance(field, str)
            or not isinstance(declared_writes, list)
            or field not in declared_writes
            or not isinstance(declaration, Mapping)
            or declaration.get("type") != "boolean"
            or not isinstance(body.get("condition"), Mapping)
            or not self._is_deterministic_condition(body["condition"])
        ):
            return "failed"
        value = bool(self._condition(body["condition"], state))
        state[field] = value
        result.steps.append(RouteStep("judge", f"{field}={str(value).lower()}", "deterministic condition evaluated", layer=layer))
        return self._wait_status(unit, state, result, layer + (location.split('.')[0],), completed_waits)

    def _tool_atom_diagnostic(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Return the explicit R3 rejection for a graph ``tool`` atom.

        The R3 plan keeps real tool execution in R4-WP1.  This method performs
        only boundary-shape checks so malformed or unfrozen drafts cannot look
        executable, then records the capabilities that remain intentionally
        unavailable.  It must stay side-effect free: no policy check, sandbox
        call, durable intent, idempotency record, or result ID is created here.
        """
        ref = body.get("tool_ref")
        tool_id = ref.get("tool_id") if isinstance(ref, Mapping) else None
        version = ref.get("version") if isinstance(ref, Mapping) else None
        diagnostic: dict[str, Any] = {
            "code": "tool_atom_runtime_unavailable",
            "reason": "tool atom execution is reserved for R4-WP1 real-tool sandbox",
            "blocked_capabilities": [
                "tool_policy",
                "argument_schema",
                "confirmation",
                "idempotency",
                "unknown_result_reconciliation",
            ],
            "tool_id": tool_id if isinstance(tool_id, str) else None,
            "tool_version": version if isinstance(version, str) else None,
        }
        manifests = self.config.get("tools")
        if not isinstance(ref, Mapping) or set(ref) != {"tool_id", "version"}:
            diagnostic["code"] = "tool_atom_unfrozen_reference"
            diagnostic["reason"] = "tool_ref must contain exact tool_id and version"
            return diagnostic
        if not isinstance(tool_id, str) or not tool_id.strip() or not isinstance(version, str) or not version.strip():
            diagnostic["code"] = "tool_atom_unfrozen_reference"
            diagnostic["reason"] = "tool_ref must contain non-empty tool_id and version"
            return diagnostic
        if not isinstance(manifests, list):
            diagnostic["code"] = "tool_atom_unfrozen_reference"
            diagnostic["reason"] = "tool registry is not an array"
            return diagnostic
        matches = [
            manifest for manifest in manifests
            if isinstance(manifest, Mapping) and manifest.get("tool_id") == tool_id
        ]
        if len(matches) != 1 or matches[0].get("version") != version:
            diagnostic["code"] = "tool_atom_unfrozen_reference"
            diagnostic["reason"] = "tool_ref does not match one exact ToolManifest"
            return diagnostic
        manifest = matches[0]
        required = {
            "tool_id", "version", "business_meaning", "side_effect_level",
            "idempotent", "requires_confirm", "timeout_ms", "result_id_required",
        }
        if (
            set(manifest) != required
            or not isinstance(manifest.get("business_meaning"), str)
            or not manifest["business_meaning"].strip()
            or manifest.get("side_effect_level") not in {"none", "read_only", "mock_write", "real_write"}
            or not isinstance(manifest.get("idempotent"), bool)
            or not isinstance(manifest.get("requires_confirm"), bool)
            or not isinstance(manifest.get("timeout_ms"), int)
            or isinstance(manifest.get("timeout_ms"), bool)
            or manifest["timeout_ms"] < 1
            or not isinstance(manifest.get("result_id_required"), bool)
        ):
            diagnostic["code"] = "tool_atom_invalid_manifest"
            diagnostic["reason"] = "ToolManifest requires exact fields and valid values: " + ", ".join(sorted(required))
            return diagnostic
        arguments = body.get("arguments", {})
        if not isinstance(arguments, Mapping):
            diagnostic["code"] = "tool_atom_invalid_arguments"
            diagnostic["reason"] = "tool arguments must be an object"
            return diagnostic
        return diagnostic

    def _wait_status(self, unit: Mapping[str, Any], state: dict[str, Any], result: RouteResult,
                     path: tuple[str, ...], completed_waits: dict[str, list[int]]) -> str:
        waits = unit.get("waits", [])
        if waits is None:
            return "ok"
        if not isinstance(waits, list):
            return "failed"
        event = state.get("event")
        key = json.dumps(list(path))
        completed = completed_waits.setdefault(key, [])
        for index, wait in enumerate(waits):
            if not isinstance(wait, Mapping) or not isinstance(wait.get("on"), str):
                return "failed"
            if ("timeoutMs" in wait) != ("timeoutTo" in wait):
                raise GraphRuntimeError("wait timeout requires both timeoutMs and timeoutTo")
            if index in completed:
                continue
            if (event == wait["on"] and not state.get("__wait_event_consumed")
                    and state.get("__wait_resume_path", list(path)) == list(path)):
                completed.append(index)
                state["__wait_event_consumed"] = True
                continue
            timeout_target = state.get("__wait_timeout_to")
            if (isinstance(timeout_target, str) and timeout_target == wait.get("timeoutTo")
                    and not state.get("__wait_timeout_consumed")
                    and state.get("__wait_resume_path", list(path)) == list(path)):
                if not self._wait_target_valid(unit, timeout_target):
                    raise GraphRuntimeError(f"invalid wait timeout target {timeout_target}")
                completed[:] = list(range(len(waits)))
                state["__wait_timeout_consumed"] = True
                return f"timeout:{timeout_target}"
            result.waiting_on = wait["on"]
            result.wait_timeout_ms = wait.get("timeoutMs") if isinstance(wait.get("timeoutMs"), int) else None
            result.wait_timeout_to = wait.get("timeoutTo") if isinstance(wait.get("timeoutTo"), str) else None
            result.waiting_path = path
            result.steps.append(RouteStep("wait", wait["on"], "external event required", layer=path))
            return "waiting"
        return "ok"

    @staticmethod
    def _frame(frames: dict[str, Any], layer: tuple[str, ...], current: str) -> dict[str, Any]:
        key = json.dumps(list(layer))
        if frames.get(key, {}).get("current") != current:
            frames[key] = {"current": current, "phase": "enter"}
        return frames[key]

    @staticmethod
    def _clear_unit(frames: dict[str, Any], waits: dict[str, Any], path: tuple[str, ...]) -> None:
        for values in (frames, waits):
            for key in list(values):
                if tuple(json.loads(key)[:len(path)]) == path:
                    del values[key]

    def _wait_target_valid(self, unit: Mapping[str, Any], target: str) -> bool:
        if target.startswith("self."):
            return any(isinstance(port, Mapping) and port.get("port") == target[5:]
                       for port in unit.get("exit_ports", []))
        if target.count(".") != 1:
            return False
        body = unit.get("body")
        if not isinstance(body, Mapping) or body.get("kind") != "graph":
            return False
        node_id, entry = target.split(".")
        child = self._unit(self._node(body, node_id))
        return child is not None and any(isinstance(port, Mapping) and port.get("port") == entry
                                         for port in child.get("entry_ports", []))

    def _is_deterministic_condition(self, condition: Any) -> bool:
        try:
            self._check_condition(condition)
        except GraphRuntimeError:
            return False
        return True

    def _check_condition(self, condition: Any, *, allow_model: bool = False, depth: int = 0) -> None:
        """Check the entire tree before boolean short-circuiting can hide an unknown leaf."""
        if not isinstance(condition, Mapping):
            raise GraphRuntimeError("graph condition must be an object")
        if not condition:
            return
        for key in ("all_of", "all", "any_of", "any", "none_of", "not"):
            if key not in condition:
                continue
            values = condition[key]
            negative = key in ("none_of", "not")
            if len(condition) != 1 or depth >= 2 or not isinstance(values, list) or not values or (negative and len(values) != 1):
                raise GraphRuntimeError("graph condition requires a non-empty list, single-child negation and at most two combination layers")
            for item in values:
                self._check_condition(item, allow_model=allow_model and not negative, depth=depth + 1)
            return
        if "llm" in condition or "llm_judge" in condition:
            if len(condition) != 1 or not allow_model:
                raise GraphRuntimeError("model condition requires a positive closed-set selector predicate")
            model = condition.get("llm", condition.get("llm_judge"))
            if not isinstance(model, Mapping) or set(model) != {"prompt"} or (
                not isinstance(model.get("prompt"), str) or not model["prompt"].strip()
            ):
                raise GraphRuntimeError("model condition requires a resolved non-empty prompt")
            return
        if "state" in condition:
            predicate = condition['state']
            if len(condition) != 1 or not isinstance(predicate, Mapping) or set(predicate) != {'metric', 'window', 'op', 'value'}:
                raise GraphRuntimeError('state condition requires metric, window, op and value only')
            try:
                if predicate.get('window') not in {'cycle', '24h', 'forever'} or predicate.get('metric') not in {'attempts', 'runs'}:
                    raise ValueError('unsupported state window')
                if predicate.get('op') not in {'gt', 'gte', 'lt', 'lte', 'eq', 'ne'}:
                    raise ValueError('unsupported state window operator')
                if type(predicate['value']) not in (int, float) or not math.isfinite(predicate['value']):
                    raise ValueError('state comparison requires a finite numeric value')
                return
            except (TypeError, ValueError) as exc:
                raise GraphRuntimeError(str(exc)) from exc
        if "event" in condition:
            event = condition["event"]
            if len(condition) != 1 or not isinstance(event, Mapping) or not isinstance(event.get("event"), str) or event["event"] not in KNOWN_EVENTS:
                raise GraphRuntimeError("graph event condition supports known event names only; event attribute matching unavailable")
            attrs = event.get('attributes', {})
            if set(event) - {'event', 'attributes'} or not isinstance(attrs, Mapping):
                raise GraphRuntimeError('graph event attributes must be an object')
            return
        fact = condition.get("fact", condition)
        # changed_to 一律明确拒绝：调用方自报的前值或在表达式里声明来源都不构成可信来源，
        # 且拒绝不能被否定或短路绕过（整棵树在布尔求值前已逐叶检查）。
        if isinstance(fact, Mapping) and fact.get("op") == "changed_to":
            raise GraphRuntimeError(CHANGED_TO_BLOCKED_REASON)
        if ("fact" in condition and len(condition) != 1) or not isinstance(fact, Mapping) or set(fact) - {"field", "op", "value"}:
            raise GraphRuntimeError("graph condition contains an unsupported predicate")
        op = fact.get("op", "eq")
        if not isinstance(fact.get("field"), str) or not fact["field"].strip() or not isinstance(op, str) or op not in {"eq", "ne", "exists", "is_set", "is_unset", "in", "not_in", "gt", "gte", "lt", "lte", "between", "matches"}:
            raise GraphRuntimeError("graph condition field or operator is unsupported")
        if op not in ("exists", "is_set", "is_unset") and "value" not in fact:
            raise GraphRuntimeError("graph comparison condition requires a value")
        expected = fact.get("value")
        if op in ("in", "not_in") and not isinstance(expected, list):
            raise GraphRuntimeError("graph membership condition requires a list value")
        if op == "between" and (
            not isinstance(expected, list) or len(expected) != 2
            or any(type(bound) not in (int, float) or not math.isfinite(bound) for bound in expected)
            or expected[0] > expected[1]
        ):
            raise GraphRuntimeError("graph between condition requires two finite ordered numeric bounds")
        if op == "matches" and not _safe_matches_pattern(expected):
            raise GraphRuntimeError("graph matches condition requires a safe string regex of at most 128 characters")
        if op in ("gt", "gte", "lt", "lte") and (not isinstance(expected, (int, float)) or isinstance(expected, bool) or not math.isfinite(expected)):
            raise GraphRuntimeError("graph numeric condition requires a finite number value")

    def _gate(self, state: Mapping[str, Any]) -> str | None:
        for gate in self.config.get("g0_gates", []):
            if isinstance(gate, Mapping) and self._condition(gate.get("when", {}), state):
                return str(gate.get("route_to", gate.get("gate_id", "blocked")))
        return None

    def _event_target(self, graph: Mapping[str, Any], state: Mapping[str, Any]) -> str | None:
        event_name = state.get("event")
        if not isinstance(event_name, str):
            return None
        for handler in graph.get("on_event", []):
            if not isinstance(handler, Mapping) or handler.get("event") != event_name:
                continue
            if "when" in handler and not self._condition(handler.get("when"), state):
                continue
            target = handler.get("goto")
            if isinstance(target, str):
                return target
        return None

    def _matching_unit_event(self, unit: Mapping[str, Any], state: Mapping[str, Any], scope: str) -> Mapping[str, Any] | None:
        event_name = state.get("event")
        if not isinstance(event_name, str):
            return None
        for handler in unit.get("on_event", []):
            if not isinstance(handler, Mapping) or handler.get("scope") != scope or handler.get("event") != event_name:
                continue
            if "when" in handler and not self._condition(handler.get("when"), state):
                continue
            if isinstance(handler.get("goto"), str):
                return handler
        return None

    def _normalize_entry(self, target: str) -> str:
        if "." in target or target == "end":
            return target
        unit = self.units.get(target)
        ports = unit.get("entry_ports", []) if isinstance(unit, Mapping) else []
        port = next((item.get("port") for item in ports if isinstance(item, Mapping) and isinstance(item.get("port"), str)), "from_start")
        return f"{target}.{port}"

    def _default_target(self, owner: Mapping[str, Any], graph: Mapping[str, Any],
                        result: RouteResult, layer: tuple[str, ...], reason: str) -> str | None:
        fallback = owner.get('fallback')
        if not isinstance(fallback, Mapping) or fallback.get('kind') != 'default_unit':
            return None
        target = fallback.get('target')
        if not isinstance(target, str) or target.count('.') != 1:
            raise GraphRuntimeError('default_unit requires an explicit local entry port')
        node_id, entry = target.split('.')
        unit = self._unit(self._node(graph, node_id))
        if unit is None or not any(isinstance(port, Mapping) and port.get('port') == entry
                                   for port in unit.get('entry_ports', [])):
            raise GraphRuntimeError('default_unit target is outside the current graph')
        limit = unit.get('max_rounds')
        if type(limit) is not int or limit < 1:
            raise GraphRuntimeError('default_unit target requires positive max_rounds')
        counts = result.continuation['fallback_counts']
        key = json.dumps([*layer, target], ensure_ascii=False)
        count = counts.get(key, 0)
        if type(count) is not int or count < 0:
            raise GraphRuntimeError('invalid fallback count snapshot')
        count = max(count, sum(step.kind == 'enter' and step.layer == layer
                               and step.target.split('.')[0] == node_id for step in result.steps))
        if result._reserve_cycle is not None:
            reservation = result._reserve_cycle(kind='fallback', layer=layer, identity=target,
                                                max_rounds=limit, minimum=count)
            count, allowed = reservation['count'], reservation['allowed']
            counts[key] = count
        else:
            allowed = count < limit
            if allowed:
                counts[key] = count + 1
        if not allowed:
            result.steps.append(RouteStep('fallback_limit', target, 'default Unit max_rounds reached', layer=layer))
            return None
        frames = result.continuation['frames']
        previous = frames.get(json.dumps(list(layer)), {}).get('current')
        if isinstance(previous, str) and '.' in previous and not previous.startswith('self.'):
            self._clear_unit(frames, result.continuation['completed_waits'], layer + (previous.split('.')[0],))
        result.steps.append(RouteStep('fallback_route', target, reason, layer=layer))
        return target

    def _advance_loop(self, result: RouteResult, edge: Mapping[str, Any], layer: tuple[str, ...],
                      state: dict[str, Any]) -> bool:
        edge_id, limit = str(edge.get('id', '')), int(edge.get('max_rounds', 0))
        key = self._cycle_key(layer, edge_id)
        if result._reserve_cycle is not None:
            reservation = result._reserve_cycle(kind='loop', layer=layer, identity=edge_id,
                                                max_rounds=limit, counter=edge['counter'])
            count, allowed = reservation['count'], reservation['allowed']
        else:
            # Standalone interpreter fixtures have no durable authority.
            count = result.cycle_counters.get(key, 0) + 1
            allowed = count <= limit
        result.cycle_counters[key] = count
        state[edge['counter']] = count
        result.cycle_events.append({'edge_id': edge_id, 'layer': list(layer), 'counter': edge['counter'],
                                    'count': count, 'max_rounds': limit})
        return allowed

    def _fallback(self, result: RouteResult, graph: Mapping[str, Any], reason: str) -> RouteResult:
        fallback = graph.get("fallback") if isinstance(graph.get("fallback"), Mapping) else {"kind": "human"}
        result.status = "fallback"
        result.fallback = str(fallback.get("kind", "human"))
        if result.fallback == 'default_unit':
            result.fallback = 'human'
        result.steps.append(RouteStep("fallback", result.fallback, reason))
        return result

    def _condition(self, condition: Any, state: Mapping[str, Any], *, allow_model: bool = False) -> bool:
        self._check_condition(condition, allow_model=allow_model)
        if not condition:
            return True
        if "llm" in condition or "llm_judge" in condition:
            # The model leaf is a deferred selector predicate. It keeps the
            # edge in the closed set; _choose_edge still requires a verified
            # selector decision before taking it.
            return True
        if 'state' in condition:
            predicate = condition['state']
            try:
                if 'state_window_counts' not in state:
                    raise ValueError('graph state condition requires a durable window provider')
                return evaluate_state_window(**predicate, counts=state.get('state_window_counts', {}))
            except (TypeError, ValueError) as exc:
                raise GraphRuntimeError(str(exc)) from exc
        for key in ("all_of", "all"):
            if key in condition:
                return all(self._condition(item, state, allow_model=allow_model) for item in condition[key])
        for key in ("any_of", "any"):
            if key in condition:
                return any(self._condition(item, state, allow_model=allow_model) for item in condition[key])
        if "none_of" in condition:
            return not any(self._condition(item, state) for item in self._list(condition["none_of"]))
        if "not" in condition:
            return not self._condition(condition["not"][0], state)
        if "event" in condition:
            event = condition["event"]
            attributes = state.get('event_attributes', {})
            if not isinstance(attributes, Mapping):
                raise GraphRuntimeError('current event attributes must be an object')
            return (state.get('event') == event['event'] and all(
                key in attributes and attributes[key] == value
                for key, value in event.get('attributes', {}).items()
            ))
        fact = condition.get("fact", condition)
        if not isinstance(fact, Mapping):
            return False
        value, present = self._read(state, fact.get("field"))
        expected, op = fact.get("value"), fact.get("op", "eq")
        if op == "matches":
            return (present and isinstance(value, str) and len(value) <= _MATCHES_MAX_VALUE_LENGTH
                    and re.search(expected, value) is not None)
        if op == "between":
            return (present and type(value) in (int, float) and math.isfinite(value)
                    and expected[0] <= value <= expected[1])
        try:
            return {"eq": lambda: value == expected, "ne": lambda: value != expected, "exists": lambda: present, "is_set": lambda: present and value is not None, "is_unset": lambda: not present or value is None, "in": lambda: value in expected if isinstance(expected, list) else False, "not_in": lambda: value not in expected if isinstance(expected, list) else False, "gt": lambda: value > expected, "gte": lambda: value >= expected, "lt": lambda: value < expected, "lte": lambda: value <= expected}.get(op, lambda: False)()
        except TypeError:
            return False

    def _node(self, graph: Mapping[str, Any], node_id: str) -> Mapping[str, Any] | None:
        return next((node for node in graph.get("nodes", []) if isinstance(node, Mapping) and node.get("id") == node_id), None)

    def _unit(self, node: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        if node is None or not isinstance(node.get("unit_ref"), Mapping):
            return None
        ref = node["unit_ref"]
        unit = self.units.get(ref.get("unit_id"))
        return unit if unit is not None and unit.get("version") == ref.get("version") and unit.get("load_mode") == "routed" else None

    @staticmethod
    def _is_loop(edge: Mapping[str, Any]) -> bool:
        return all(key in edge for key in ("max_rounds", "exit", "counter", "window"))

    @staticmethod
    def _cycle_key(layer: tuple[str, ...], edge_id: str) -> str:
        return json.dumps([*layer, edge_id], ensure_ascii=False, separators=(",", ":"))

    def _entry_missing(self, unit: Mapping[str, Any], entry: str, state: Mapping[str, Any]) -> list[str]:
        port = next((item for item in unit.get("entry_ports", [])
                     if isinstance(item, Mapping) and item.get("port") == entry), None)
        requires = port.get("requires", []) if isinstance(port, Mapping) else []
        return self._missing_fields(requires, state)

    @classmethod
    def _missing_fields(cls, fields: Any, state: Mapping[str, Any]) -> list[str]:
        if not isinstance(fields, list):
            return ["<invalid requirements>"]
        return [field for field in fields
                if not isinstance(field, str) or not cls._read(state, field)[1] or cls._read(state, field)[0] is None]

    @staticmethod
    def _list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else [value]

    @staticmethod
    def _read(state: Mapping[str, Any], field: Any) -> tuple[Any, bool]:
        if not isinstance(field, str):
            return None, False
        current: Any = state
        for part in field.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return None, False
            current = current[part]
        return current, True


__all__ = ["GraphRuntime", "GraphRuntimeError", "RouteResult", "RouteStep"]
