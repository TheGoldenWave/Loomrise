"""AGI-07: scoped, immutable diagnostic evidence and proposal-only reports.

Only trusted application principals enter this service. No method changes a
business row, case truth, configuration, or release. Provider adapters receive
the bounded projection rather than a Run or its original payloads.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .configuration import CONFIG_SCHEMA_VERSION, ConfigurationPrincipal
from .contracts import RequestState, new_id
from .durable_store import SqliteStore

EVIDENCE_SCHEMA_VERSION = "diagnosis-evidence-v1"
REPORT_SCHEMA_VERSION = "diagnosis-report-v2"
MAX_RUNS = 10
MAX_CASES = 10
MAX_EVENTS_PER_RUN = 100
MAX_SNAPSHOT_BYTES = 128 * 1024
MAX_REPORT_BYTES = 16 * 1024
MAX_PERMISSION_SECONDS = 3600
REPORT_CATEGORIES = ("knowledge", "routing", "loading", "policy", "tool", "rule")
REPORT_LIMITATIONS = (
    "customer_text_omitted", "configuration_omitted", "tool_content_omitted",
    "events_omitted", "events_truncated", "source_unavailable",
    "limited_sample", "causality_unverified",
)
_BASE_LIMITATIONS = (
    "customer_text_omitted", "configuration_omitted", "tool_content_omitted",
    "limited_sample", "causality_unverified",
)
REPORT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "status", "findings", "insufficient_categories", "limitations"],
    "properties": {
        "schema_version": {"type": "string", "const": REPORT_SCHEMA_VERSION},
        "status": {"type": "string", "const": "proposal"},
        "findings": {
            "type": "array", "maxItems": 6,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["category", "summary", "recommendation", "evidence_ids"],
                "properties": {
                    "category": {"type": "string", "enum": list(REPORT_CATEGORIES)},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 512},
                    "recommendation": {"type": "string", "minLength": 1, "maxLength": 512},
                    "evidence_ids": {
                        "type": "array", "minItems": 1, "maxItems": 10,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": "^ev_[a-f0-9]{24}$"},
                    },
                },
            },
        },
        "insufficient_categories": {
            "type": "array", "maxItems": 6, "uniqueItems": True,
            "items": {"type": "string", "enum": list(REPORT_CATEGORIES)},
        },
        "limitations": {
            "type": "array", "minItems": 1, "maxItems": len(REPORT_LIMITATIONS),
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(REPORT_LIMITATIONS)},
        },
    },
}
# Public alias for integrations that name the domain rather than the encoding.
DIAGNOSTIC_REPORT_SCHEMA = REPORT_JSON_SCHEMA

_RUN_STATES = frozenset({"running", "waiting", "succeeded", "failed", "interrupted", "cancelled"})
_REQUEST_STATES = frozenset(str(state) for state in RequestState)
_EVENT_TYPES = frozenset({
    "run.started", "run.finished", "run.interrupted", "run.cancel_confirmed",
    "run.execution_failed", "request.routed", "request.route_failed", "request.route_waiting",
    "recall.diagnostic", "context.fragment", "rule.evaluated", "rule.verdict",
    "tool.outcome", "permission.decision", "policy.evaluated", "route.graph.started", "route.graph.step",
    "route.graph.finished",
})
_RECALL_CODES = frozenset({
    "invalid_concurrent_limit", "invalid_load_scope", "before_load_scope",
    "excluded_current_unit", "unavailable_skill_context", "selector_failed",
    "no_eligible_candidates", "invalid_selection", "selected",
})
_ENUM_VALUES = {
    "scope": frozenset({"global", "task", "skill", "evidence"}),
    "stage": frozenset({"baseline", "task_local", "on_demand", "concurrent", "reply_generation"}),
    "load_status": frozenset({"loaded", "skipped", "expired", "budget_capped"}),
    "outcome": frozenset({"success", "error", "interrupted", "denied", "unknown"}),
    "verdict": frozenset({"deny", "require", "stop", "dedupe", "pass"}),
    "request_state": _REQUEST_STATES,
    "code": _RECALL_CODES,
    "provider": frozenset({"injected", "deterministic-keyword-v1"}),
    "failure_code": frozenset({"reply_generation_failed"}),
}
_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "run.finished": ("request_state", "write_count"),
    "run.cancel_confirmed": ("write_prevented", "business_action_revoked"),
    "run.execution_failed": ("stage", "failure_code", "business_result_preserved"),
    "recall.diagnostic": ("code", "candidate_count", "selected_count", "max_units", "provider", "diagnostic_only"),
    "context.fragment": ("scope", "stage", "load_status", "token_estimate"),
    "rule.evaluated": ("verdict",), "rule.verdict": ("verdict",),
    "permission.decision": ("verdict", "authorized"),
    "tool.outcome": ("outcome", "duration_ms", "no_result"),
}
_NUMERIC_MAX = {"write_count": 100_000, "candidate_count": 100_000, "selected_count": 100_000,
                "max_units": 100_000, "token_estimate": 1_000_000, "duration_ms": 86_400_000}
_BOOL_FIELDS = frozenset({"write_prevented", "business_action_revoked", "business_result_preserved",
                          "diagnostic_only", "no_result", "authorized"})
_DIGEST = re.compile(r"^[a-f0-9]{64}$")

# Stable schema descriptor: adding/removing projected data changes the hash
# and makes already-issued evidence permissions stale rather than ambiguous.
EVIDENCE_CONTRACT_DESCRIPTOR: dict[str, Any] = {
    "schema_version": EVIDENCE_SCHEMA_VERSION,
    "snapshot_fields": ["schema_version", "snapshot_id", "permission_id", "purpose", "created_at",
                        "runs", "cases", "limitations", "snapshot_hash"],
    "evidence_identity_fields": ["evidence_id", "kind", "source_id", "source_hash"],
    "run_fields": ["evidence_id", "kind", "source_id", "source_hash", "run_status", "request_state", "events", "gaps"],
    "run_status_values": sorted(_RUN_STATES),
    "event_item_fields": ["evidence_id", "kind", "source_id", "source_hash", "sequence", "event_type", "data"],
    "gap_fields": ["total_event_count", "whitelisted_event_count", "included_event_count",
                   "omitted_event_count", "truncated", "reasons"],
    "case_item_fields": ["evidence_id", "kind", "source_id", "source_hash", "data"],
    "case_fields": {"status": ["reviewed_original"], "purpose": ["diagnosis"],
                    "blind_status": ["not_blind"], "channel": ["text", "voice"],
                    "expected_state": sorted(_REQUEST_STATES),
                    "tool_failure_mode": ["none", "error", "timeout_unknown"],
                    "expected_write_count_max": 100_000},
    "event_types": sorted(_EVENT_TYPES),
    "event_fields": {key: list(_EVENT_FIELDS[key]) for key in sorted(_EVENT_FIELDS)},
    "values": {key: sorted(values) for key, values in sorted(_ENUM_VALUES.items())},
    "numeric_max": dict(sorted(_NUMERIC_MAX.items())),
    "boolean_fields": sorted(_BOOL_FIELDS),
    "limits": {"runs": MAX_RUNS, "cases": MAX_CASES, "events_per_run": MAX_EVENTS_PER_RUN,
               "snapshot_bytes": MAX_SNAPSHOT_BYTES},
    "limitations": list(REPORT_LIMITATIONS),
}
EVIDENCE_SCHEMA_HASH = hashlib.sha256(json.dumps(
    EVIDENCE_CONTRACT_DESCRIPTOR, ensure_ascii=False, sort_keys=True,
    separators=(",", ":"), allow_nan=False,
).encode("utf-8")).hexdigest()


class DiagnosticIntegrityError(ValueError):
    """A server-owned frozen source no longer matches its registered content."""


@dataclass(frozen=True)
class TrustedDiagnosticCase:
    """Server construction only; request payloads never register or review cases."""

    case_id: str
    path: Path
    content_hash: str
    status: str = "reviewed_original"
    purpose: str = "diagnosis"
    blind_status: str = "not_blind"


_CASE_HASHES = {
    "c1_consult_success": "2130b0114c6c29a211e051bf4f9989dc448c065ef387a77dc22ef3bbda4d1b8c",
    "c2_booking_confirmed": "371238c015d6d3b2b5e51d4f9fbb0e919da9ccf5c7d866aaf48baa5756f2e747",
    "c3_booking_rejected": "85b54314a6a8f1b818199035e89779961c18b853f6face38d57087da233a1e93",
    "c4_missing_material": "a81f0a38f83ee493813998b53bead142d4528b8a01e819a0f84c38f84512dc6b",
    "c5_deny_unknown_course": "3d8d863854ee9697a1d2c0430e80e19d62fe85040f3861dcd248fa4fa8f49810",
    "c6_tool_error": "4ffb230c245aa6ada0a5011d2cb40438d0d522d4798f72d387f419bcad168876",
    "c7_timeout_unknown": "56967273033936369432281c589bb0ca27bbbbd607d9b6e53132d606a8e024e4",
    "c8_duplicate_write": "d29afa3e9d17f5022f3bae775da19ae0b3ad37c8c65addf91c45f42f31911cf3",
    "c9_voice_same_request": "0db2da85f6914bad21be365197ccc9624a84b4c82207f98416064aecb924ba16",
    "c10_budget_capped": "a9ef81b928124cc8f0ff49622bd70860d63e7f7aaa1114a9b8938642e5f238bc",
    "c11_cancel_before_write": "e0c830548dacf681093d0ef297b51e0b5b2957b5fde58f2c8a885c0145b7d933",
}
_CASE_DIR = Path(__file__).resolve().parents[1] / "scenarios/course_consult_v1/cases"
ORIGINAL_CASE_REGISTRY = MappingProxyType({
    key: TrustedDiagnosticCase(key, _CASE_DIR / f"{key}.json", digest)
    for key, digest in _CASE_HASHES.items()
})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


# 服务端拥有的治理 Provider 登记合同。Provider 适配器只可声明被登记的非真实
# 类别；real harness 类别保留给经过真实联调的服务端登记，调用方一律不得自报，
# 也绝不把脚本/替身结果写入真实 Provider 证据分类。descriptor 必须绑定当前
# 合同 hash，旧版或错误合同的 Provider 不得被当作当前 Provider 接受。
PROVIDER_KIND_OFFLINE_SCRIPTED = "offline_scripted"
PROVIDER_KIND_STRUCTURED = "structured"
PROVIDER_KIND_REAL_HARNESS = "real_harness"
ALLOWED_PROVIDER_KINDS = frozenset({PROVIDER_KIND_OFFLINE_SCRIPTED, PROVIDER_KIND_STRUCTURED})
PROVIDER_VERSIONS = {
    PROVIDER_KIND_OFFLINE_SCRIPTED: "agentscope-diagnosis-offline-scripted-v1",
    PROVIDER_KIND_STRUCTURED: "agentscope-diagnosis-structured-v1",
    PROVIDER_KIND_REAL_HARNESS: "agentscope-diagnosis-v1",
}
PROVIDER_CONTRACT = {
    "version": "governance-provider-contract-v2",
    "allowed_provider_kinds": sorted(ALLOWED_PROVIDER_KINDS),
    "provider_versions": PROVIDER_VERSIONS,
    "report_schema_hash": _hash(REPORT_JSON_SCHEMA),
}
PROVIDER_CONTRACT_HASH = _hash(PROVIDER_CONTRACT)


def _id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("诊断标识无效")
    return value


def _selected(values: Any, maximum: int) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > maximum:
        raise ValueError("诊断来源必须是有界的显式 ID 列表")
    result = [_id(value) for value in values]
    if len(result) != len(set(result)):
        raise ValueError("诊断来源不能重复")
    return result


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("诊断有效期无效")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("诊断有效期无效") from None
    if result.tzinfo is None:
        raise ValueError("诊断有效期必须含时区")
    return result.astimezone(timezone.utc)


class DiagnosticsService:
    """Owner-issued diagnosis permission, recipient-scoped evidence and reports."""

    def __init__(self, store: SqliteStore, *,
                 case_registry: Mapping[str, TrustedDiagnosticCase] | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.case_registry = MappingProxyType(dict(ORIGINAL_CASE_REGISTRY if case_registry is None else case_registry))
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("诊断时钟必须含时区")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _principal(principal: ConfigurationPrincipal, agent_id: str, *, owner: bool = False) -> None:
        if (not isinstance(principal, ConfigurationPrincipal)
                or principal.schema_version != CONFIG_SCHEMA_VERSION
                or principal.role not in {"owner", "editor", "external_agent"}
                or agent_id not in principal.agent_ids):
            raise PermissionError("无诊断作用域权限")
        _id(principal.tenant_id)
        _id(principal.actor_id)
        _id(agent_id)
        if owner and principal.role != "owner":
            raise PermissionError("诊断许可仅限 owner 管理")

    @staticmethod
    def _owned_run(cur: sqlite3.Cursor, *, tenant_id: str, agent_id: str, run_id: str) -> sqlite3.Row:
        row = cur.execute(
            "SELECT r.*,q.state AS request_state FROM runs r "
            "JOIN requests q ON q.request_id=r.request_id AND q.tenant_id=r.tenant_id "
            "JOIN configuration_stable_versions v ON v.tenant_id=r.tenant_id "
            "AND v.agent_id=? AND v.version_id=r.agent_version "
            "WHERE r.tenant_id=? AND r.run_id=? "
            "AND CASE WHEN json_valid(r.snapshot_json) THEN json_extract(r.snapshot_json,'$.agent_id') END=?",
            (agent_id, tenant_id, run_id, agent_id),
        ).fetchone()
        if row is None:
            raise PermissionError("诊断运行未归属当前租户和专家")
        return row

    @staticmethod
    def _run_identity(row: sqlite3.Row, agent_id: str) -> dict[str, str]:
        identity = {"run_id": row["run_id"], "tenant_id": row["tenant_id"], "agent_id": agent_id,
                    "request_id": row["request_id"], "agent_version": row["agent_version"]}
        return {"run_id": row["run_id"], "source_id": _hash(["run", row["run_id"]]),
                "source_hash": _hash(identity)}

    def _case(self, case_id: str) -> tuple[TrustedDiagnosticCase, dict[str, Any]]:
        source = self.case_registry.get(case_id)
        if (not isinstance(source, TrustedDiagnosticCase) or source.case_id != case_id
                or source.status != "reviewed_original" or source.purpose != "diagnosis"
                or source.blind_status != "not_blind"):
            raise PermissionError("案例不是诊断可用的已审原创固定来源")
        if not isinstance(source.content_hash, str) or not _DIGEST.fullmatch(source.content_hash):
            raise DiagnosticIntegrityError("固定案例登记无效")
        try:
            with Path(source.path).open("rb") as handle:
                raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES or hashlib.sha256(raw).hexdigest() != source.content_hash:
                raise DiagnosticIntegrityError("固定案例 hash 不匹配")
            case = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise DiagnosticIntegrityError("固定案例来源不可用") from None
        if not isinstance(case, dict) or case.get("case_id") != case_id:
            raise DiagnosticIntegrityError("固定案例 ID 不匹配")
        # File-level claims of review, blind consumption, or purpose grant nothing.
        return source, case

    def issue(self, *, principal: ConfigurationPrincipal, agent_id: str,
              recipient_actor_id: str, run_ids: list[str], case_ids: list[str] | None = None,
              expires_in_seconds: int = 900) -> dict[str, Any]:
        self._principal(principal, agent_id, owner=True)
        _id(recipient_actor_id)
        selected_runs = _selected(run_ids, MAX_RUNS)
        selected_cases = _selected([] if case_ids is None else case_ids, MAX_CASES)
        if not selected_runs and not selected_cases:
            raise ValueError("诊断许可至少选择一个来源")
        if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= MAX_PERMISSION_SECONDS:
            raise ValueError("诊断许可有效期必须为 1 至 3600 秒")
        now = self._now()
        permission_id = new_id("dperm")
        with self.store._tx() as cur:
            runs = [self._run_identity(self._owned_run(cur, tenant_id=principal.tenant_id,
                    agent_id=agent_id, run_id=key), agent_id) for key in selected_runs]
            cases = []
            for key in selected_cases:
                source, _ = self._case(key)
                cases.append({"case_id": key, "source_id": _hash(["original_case", key]),
                              "source_hash": source.content_hash})
            selection = {"runs": runs, "cases": cases,
                         "evidence_contract": {"schema_version": EVIDENCE_SCHEMA_VERSION,
                                               "schema_hash": EVIDENCE_SCHEMA_HASH}}
            value = {"permission_id": permission_id, "tenant_id": principal.tenant_id,
                     "agent_id": agent_id, "recipient_actor_id": recipient_actor_id,
                     "issued_by": principal.actor_id, "purpose": "diagnosis",
                     "issued_at": now.isoformat(),
                     "expires_at": (now + timedelta(seconds=expires_in_seconds)).isoformat(),
                     "selection": selection}
            cur.execute("INSERT INTO diagnosis_permissions VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                        (permission_id, principal.tenant_id, agent_id, recipient_actor_id,
                         principal.actor_id, "diagnosis", _canonical(selection), _hash(value),
                         value["issued_at"], value["expires_at"]))
        return {**value, "revoked_at": None}

    def _permission_tx(self, cur: sqlite3.Cursor, *, principal: ConfigurationPrincipal,
                       agent_id: str, permission_id: str, recipient: bool = True,
                       require_active: bool = True) -> dict[str, Any]:
        self._principal(principal, agent_id)
        _id(permission_id)
        row = cur.execute("SELECT * FROM diagnosis_permissions WHERE permission_id=? AND tenant_id=? AND agent_id=?",
                          (permission_id, principal.tenant_id, agent_id)).fetchone()
        if row is None or (recipient and row["recipient_actor_id"] != principal.actor_id):
            raise PermissionError("无诊断许可")
        try:
            selection = json.loads(row["selection_json"])
            value = {key: row[key] for key in ("permission_id", "tenant_id", "agent_id", "recipient_actor_id",
                                              "issued_by", "purpose", "issued_at", "expires_at")}
            value["selection"] = selection
            if row["permission_hash"] != _hash(value):
                raise DiagnosticIntegrityError("诊断许可 hash 不匹配")
            if not isinstance(selection, dict) or selection.get("evidence_contract") != {
                "schema_version": EVIDENCE_SCHEMA_VERSION, "schema_hash": EVIDENCE_SCHEMA_HASH,
            }:
                raise DiagnosticIntegrityError("诊断许可绑定的证据合同已失效")
            if not all(isinstance(selection.get(key), list) for key in ("runs", "cases")):
                raise DiagnosticIntegrityError("诊断许可来源列表无效")
            current = self._now()
            if row["purpose"] != "diagnosis":
                raise DiagnosticIntegrityError("诊断许可用途无效")
            if (require_active and (row["revoked_at"] is not None
                    or not _timestamp(row["issued_at"]) <= current < _timestamp(row["expires_at"]))):
                raise PermissionError("诊断许可已过期或撤销")
        except (TypeError, json.JSONDecodeError):
            raise DiagnosticIntegrityError("诊断许可损坏") from None
        self._verify_sources_tx(cur, value)
        return {**value, "revoked_at": row["revoked_at"]}

    def _verify_sources_tx(self, cur: sqlite3.Cursor, permission: dict[str, Any]) -> None:
        for selected in permission["selection"]["runs"]:
            run = self._owned_run(cur, tenant_id=permission["tenant_id"], agent_id=permission["agent_id"],
                                  run_id=selected["run_id"])
            if self._run_identity(run, permission["agent_id"]) != selected:
                raise DiagnosticIntegrityError("诊断运行来源已变化")
        for selected in permission["selection"]["cases"]:
            source, _ = self._case(selected["case_id"])
            if selected != {"case_id": source.case_id, "source_id": _hash(["original_case", source.case_id]),
                            "source_hash": source.content_hash}:
                raise DiagnosticIntegrityError("固定案例来源登记已变化")

    def read_permission(self, *, principal: ConfigurationPrincipal, agent_id: str,
                        permission_id: str) -> dict[str, Any]:
        """Recipient permission check for trusted Worker/application integration."""
        with self.store._lock:
            cur = self.store._conn.cursor()
            try:
                return self._permission_tx(cur, principal=principal, agent_id=agent_id, permission_id=permission_id)
            finally:
                cur.close()

    def revoke(self, *, principal: ConfigurationPrincipal, agent_id: str,
               permission_id: str) -> dict[str, Any]:
        self._principal(principal, agent_id, owner=True)
        _id(permission_id)
        with self.store._tx() as cur:
            row = cur.execute("SELECT * FROM diagnosis_permissions WHERE permission_id=? AND tenant_id=? AND agent_id=?",
                              (permission_id, principal.tenant_id, agent_id)).fetchone()
            if row is None:
                raise PermissionError("无诊断许可")
            # 撤销是安全动作：即使证据合同/Schema/hash 已变更、来源已失效或
            # 许可已过期，也必须始终可执行。这里只做 owner 身份与租户/专家归属
            # 校验，不复用 _permission_tx 的合同、来源与时效校验（旧记录下那会
            # 抛错而把撤销锁死）。撤销只收紧授权，既不读取也不扩大任何权限。
            revoked_at = row["revoked_at"] or self._now().isoformat()
            cur.execute("UPDATE diagnosis_permissions SET revoked_at=? WHERE permission_id=?", (revoked_at, permission_id))
        return {"permission_id": permission_id, "revoked_at": revoked_at}

    @staticmethod
    def _evidence(snapshot_id: str, *, kind: str, source_id: str,
                  source_hash: str, **data: Any) -> dict[str, Any]:
        return {"evidence_id": "ev_" + _hash([snapshot_id, source_id])[:24], "kind": kind,
                "source_id": source_id, "source_hash": source_hash, **data}

    @staticmethod
    def _project_event(row: sqlite3.Row, run: sqlite3.Row) -> tuple[dict[str, Any] | None, bool]:
        try:
            event = json.loads(row["event_json"])
            payload = event.get("payload") if isinstance(event, dict) else None
            if not isinstance(payload, dict) or event.get("hash") != row["hash"]:
                return None, True
            if any(event.get(key) != expected for key, expected in (
                ("seq", row["seq"]), ("event_type", row["event_type"]), ("run_id", run["run_id"]),
                ("request_id", run["request_id"]), ("tenant_id", run["tenant_id"]),
                ("agent_version", run["agent_version"]),
            )):
                return None, True
            sealed = hashlib.sha256(json.dumps({k: v for k, v in event.items() if k != "hash"},
                sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
            if not _DIGEST.fullmatch(row["hash"]) or sealed != row["hash"]:
                return None, True
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, True
        data: dict[str, Any] = {}
        for key in _EVENT_FIELDS.get(row["event_type"], ()):
            value = payload.get(key)
            if key in _ENUM_VALUES and isinstance(value, str) and value in _ENUM_VALUES[key]:
                data[key] = value
            elif key in _NUMERIC_MAX and type(value) is int and 0 <= value <= _NUMERIC_MAX[key]:
                data[key] = value
            elif key in _BOOL_FIELDS and type(value) is bool:
                data[key] = value
        return data, bool(set(payload) - set(data))

    def _snapshot_tx(self, cur: sqlite3.Cursor, permission: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = new_id("dsnap")
        value: dict[str, Any] = {"schema_version": EVIDENCE_SCHEMA_VERSION,
            "snapshot_id": snapshot_id, "permission_id": permission["permission_id"],
            "purpose": "diagnosis", "created_at": self._now().isoformat(),
            "runs": [], "cases": [], "limitations": list(_BASE_LIMITATIONS)}
        for selected in permission["selection"]["runs"]:
            run = self._owned_run(cur, tenant_id=permission["tenant_id"],
                                  agent_id=permission["agent_id"], run_id=selected["run_id"])
            if self._run_identity(run, permission["agent_id"]) != selected:
                raise DiagnosticIntegrityError("诊断运行来源已变化")
            state = run["status"] if run["status"] in _RUN_STATES else "unknown"
            request_state = run["request_state"] if run["request_state"] in _REQUEST_STATES else "unknown"
            item = self._evidence(snapshot_id, kind="run", source_id=selected["source_id"],
                source_hash=_hash({"identity_hash": selected["source_hash"], "run_status": state,
                                   "request_state": request_state}),
                run_status=state, request_state=request_state, events=[])
            total = cur.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (selected["run_id"],)).fetchone()[0]
            marks = ",".join("?" for _ in _EVENT_TYPES)
            event_types = sorted(_EVENT_TYPES)
            allowed = cur.execute(f"SELECT COUNT(*) FROM events WHERE run_id=? AND event_type IN ({marks})",
                                 (selected["run_id"], *event_types)).fetchone()[0]
            rows = cur.execute(f"SELECT seq,event_type,hash,CASE WHEN length(event_json)<=? THEN event_json END AS event_json "
                f"FROM events WHERE run_id=? AND event_type IN ({marks}) ORDER BY seq LIMIT ?",
                (MAX_SNAPSHOT_BYTES, selected["run_id"], *event_types, MAX_EVENTS_PER_RUN)).fetchall()
            reasons = {"payload_fields_omitted"}
            if total > allowed:
                reasons.add("unsupported_events_omitted")
            if allowed > len(rows):
                reasons.add("event_limit")
            for row in rows:
                data, redacted = self._project_event(row, run)
                if data is None:
                    reasons.add("invalid_events_omitted")
                    continue
                item["events"].append(self._evidence(snapshot_id, kind="event",
                    source_id=_hash(["event", selected["run_id"], row["seq"]]), source_hash=row["hash"],
                    sequence=row["seq"], event_type=row["event_type"], data=data))
                if redacted:
                    reasons.add("payload_fields_omitted")
            item["gaps"] = {"total_event_count": total, "whitelisted_event_count": allowed,
                "included_event_count": len(item["events"]), "omitted_event_count": total - len(item["events"]),
                "truncated": allowed > len(rows), "reasons": sorted(reasons)}
            value["runs"].append(item)
        for selected in permission["selection"]["cases"]:
            source, case = self._case(selected["case_id"])
            if selected != {"case_id": source.case_id, "source_id": _hash(["original_case", source.case_id]),
                            "source_hash": source.content_hash}:
                raise DiagnosticIntegrityError("固定案例来源登记已变化")
            data: dict[str, Any] = {"status": "reviewed_original", "purpose": "diagnosis", "blind_status": "not_blind"}
            for key, allowed_values in (("channel", {"text", "voice"}), ("expected_state", _REQUEST_STATES),
                                        ("tool_failure_mode", {"none", "error", "timeout_unknown"})):
                if isinstance(case.get(key), str) and case[key] in allowed_values:
                    data[key] = case[key]
            count = case.get("expected_write_count")
            if type(count) is int and 0 <= count <= 100_000:
                data["expected_write_count"] = count
            value["cases"].append(self._evidence(snapshot_id, kind="case", source_id=selected["source_id"],
                                                source_hash=source.content_hash, data=data))
        # Include the final gap metadata in each size check. Every selected source
        # retains its summary when the global byte budget removes event details.
        while True:
            value["limitations"] = list(_BASE_LIMITATIONS)
            if any(item["gaps"]["omitted_event_count"] for item in value["runs"]):
                value["limitations"].append("events_omitted")
            if any(item["gaps"]["truncated"] for item in value["runs"]):
                value["limitations"].append("events_truncated")
            if len(_canonical({**value, "snapshot_hash": "0" * 64}).encode("utf-8")) <= MAX_SNAPSHOT_BYTES:
                break
            candidates = [item for item in value["runs"] if item["events"]]
            if not candidates:
                raise ValueError("诊断快照超过大小限制")
            item = max(candidates, key=lambda run: len(run["events"]))
            item["events"].pop()
            item["gaps"]["included_event_count"] -= 1
            item["gaps"]["omitted_event_count"] += 1
            item["gaps"]["truncated"] = True
            item["gaps"]["reasons"] = sorted(set(item["gaps"]["reasons"]) | {"snapshot_budget"})
        value["snapshot_hash"] = _hash(value)
        return value

    @staticmethod
    def _load_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        try:
            value = json.loads(row["snapshot_json"])
            body = {key: item for key, item in value.items() if key != "snapshot_hash"}
            if (value.get("schema_version") != EVIDENCE_SCHEMA_VERSION
                    or value.get("snapshot_id") != row["snapshot_id"]
                    or value.get("permission_id") != row["permission_id"]
                    or value.get("snapshot_hash") != row["input_hash"]
                    or _hash(body) != row["input_hash"]
                    or len(_canonical(value).encode("utf-8")) > MAX_SNAPSHOT_BYTES):
                raise DiagnosticIntegrityError("诊断快照 hash 或 Schema 不匹配")
        except (TypeError, AttributeError, json.JSONDecodeError):
            raise DiagnosticIntegrityError("诊断快照损坏") from None
        return value

    def read_evidence(self, *, principal: ConfigurationPrincipal, agent_id: str,
                      permission_id: str) -> dict[str, Any]:
        with self.store._tx() as cur:
            permission = self._permission_tx(cur, principal=principal, agent_id=agent_id, permission_id=permission_id)
            row = cur.execute("SELECT * FROM diagnosis_snapshots WHERE permission_id=?", (permission_id,)).fetchone()
            if row is not None:
                return self._load_snapshot(row)
            snapshot = self._snapshot_tx(cur, permission)
            cur.execute("INSERT INTO diagnosis_snapshots VALUES(?,?,?,?,?)", (snapshot["snapshot_id"], permission_id,
                snapshot["snapshot_hash"], _canonical(snapshot), snapshot["created_at"]))
            return snapshot

    @staticmethod
    def validate_report(report: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(report, dict) or set(report) != {
            "schema_version", "status", "findings", "insufficient_categories", "limitations",
        }:
            raise ValueError("诊断报告字段无效")
        if report["schema_version"] != REPORT_SCHEMA_VERSION or report["status"] != "proposal":
            raise ValueError("诊断报告只能作为提案")
        findings = report["findings"]
        insufficient = report["insufficient_categories"]
        limitations = report["limitations"]
        if (not isinstance(findings, list) or len(findings) > 6
                or not isinstance(insufficient, list) or len(insufficient) > 6
                or not all(isinstance(category, str) and category in REPORT_CATEGORIES for category in insufficient)
                or len(set(insufficient)) != len(insufficient)
                or not isinstance(limitations, list) or not 1 <= len(limitations) <= len(REPORT_LIMITATIONS)
                or not all(isinstance(code, str) and code in REPORT_LIMITATIONS for code in limitations)
                or len(set(limitations)) != len(limitations)):
            raise ValueError("诊断报告必须说明证据不足且不能超出分类和大小限制")
        required = set(snapshot["limitations"])
        if not required.issubset(limitations):
            raise ValueError("诊断报告不能省略快照的证据缺口")
        evidence_ids = {item["evidence_id"] for item in snapshot["runs"] + snapshot["cases"]}
        evidence_ids.update(event["evidence_id"] for item in snapshot["runs"] for event in item["events"])
        categories = set()
        for finding in findings:
            if not isinstance(finding, dict) or set(finding) != {"category", "summary", "recommendation", "evidence_ids"}:
                raise ValueError("诊断发现字段无效")
            category = finding["category"]
            if not isinstance(category, str) or category not in REPORT_CATEGORIES or category in categories:
                raise ValueError("诊断分类必须来自六类且不能重复")
            categories.add(category)
            for key in ("summary", "recommendation"):
                text = finding[key]
                if (not isinstance(text, str) or not text.strip() or len(text) > 512
                        or any(ord(c) < 32 and c not in "\n\t" for c in text)):
                    raise ValueError("诊断文本无效或超过限制")
            refs = finding["evidence_ids"]
            if (not isinstance(refs, list) or not 1 <= len(refs) <= 10
                    or not all(isinstance(ref, str) and ref in evidence_ids for ref in refs)
                    or len(set(refs)) != len(refs)):
                raise ValueError("诊断发现必须引用当前快照中的精确证据")
        if categories & set(insufficient) or categories | set(insufficient) != set(REPORT_CATEGORIES):
            raise ValueError("诊断报告必须逐类提供发现或明确标记证据不足")
        if len(_canonical(report).encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("诊断报告超过大小限制")
        return deepcopy(report)

    def _submit_report_tx(self, cur: sqlite3.Cursor, *, principal: ConfigurationPrincipal,
                          agent_id: str, permission_id: str, snapshot_id: str,
                          input_hash: str, report: dict[str, Any]) -> dict[str, Any]:
        """Trusted caller must own store._tx; Worker CAS belongs in this same tx."""
        if cur.connection is not self.store._conn or not cur.connection.in_transaction:
            raise RuntimeError("诊断报告提交必须使用同一存储事务")
        self._permission_tx(cur, principal=principal, agent_id=agent_id, permission_id=permission_id)
        _id(snapshot_id)
        if not isinstance(input_hash, str) or not _DIGEST.fullmatch(input_hash):
            raise ValueError("诊断输入 hash 无效")
        row = cur.execute("SELECT * FROM diagnosis_snapshots WHERE permission_id=? AND snapshot_id=?",
                          (permission_id, snapshot_id)).fetchone()
        if row is None or row["input_hash"] != input_hash:
            raise DiagnosticIntegrityError("诊断报告输入与冻结快照不一致")
        snapshot = self._load_snapshot(row)
        value = self.validate_report(report, snapshot)
        result = {"report_id": new_id("dreport"), "permission_id": permission_id,
                  "snapshot_id": snapshot_id, "input_hash": input_hash,
                  "created_at": self._now().isoformat(), "report": value}
        cur.execute("INSERT INTO diagnosis_reports VALUES(?,?,?,?,?,?,?)", (result["report_id"],
            permission_id, snapshot_id, input_hash, _canonical(value), principal.actor_id, result["created_at"]))
        return result

    def submit_report(self, *, principal: ConfigurationPrincipal, agent_id: str,
                      permission_id: str, snapshot_id: str, input_hash: str,
                      report: dict[str, Any]) -> dict[str, Any]:
        with self.store._tx() as cur:
            return self._submit_report_tx(cur, principal=principal, agent_id=agent_id,
                permission_id=permission_id, snapshot_id=snapshot_id, input_hash=input_hash, report=report)

    def read_report(self, *, principal: ConfigurationPrincipal, agent_id: str,
                    report_id: str) -> dict[str, Any]:
        self._principal(principal, agent_id)
        _id(report_id)
        with self.store._lock:
            cur = self.store._conn.cursor()
            try:
                row = cur.execute("SELECT r.* FROM diagnosis_reports r JOIN diagnosis_permissions p "
                    "ON p.permission_id=r.permission_id WHERE r.report_id=? AND p.tenant_id=? AND p.agent_id=?",
                    (report_id, principal.tenant_id, agent_id)).fetchone()
                if row is None:
                    raise PermissionError("无诊断报告读取权限")
                self._permission_tx(cur, principal=principal, agent_id=agent_id, permission_id=row["permission_id"])
                snap = cur.execute("SELECT * FROM diagnosis_snapshots WHERE snapshot_id=? AND permission_id=?",
                                   (row["snapshot_id"], row["permission_id"])).fetchone()
                if snap is None or row["input_hash"] != snap["input_hash"]:
                    raise DiagnosticIntegrityError("诊断报告快照关联损坏")
                report = self.validate_report(json.loads(row["report_json"]), self._load_snapshot(snap))
                return {key: row[key] for key in ("report_id", "permission_id", "snapshot_id", "input_hash", "created_at")} | {"report": report}
            finally:
                cur.close()


__all__ = ["DiagnosticsService", "DiagnosticIntegrityError", "TrustedDiagnosticCase", "ORIGINAL_CASE_REGISTRY",
           "REPORT_JSON_SCHEMA", "DIAGNOSTIC_REPORT_SCHEMA", "REPORT_SCHEMA_VERSION", "EVIDENCE_SCHEMA_VERSION",
           "EVIDENCE_SCHEMA_HASH", "EVIDENCE_CONTRACT_DESCRIPTOR",
           "PROVIDER_KIND_OFFLINE_SCRIPTED", "PROVIDER_KIND_STRUCTURED", "PROVIDER_KIND_REAL_HARNESS",
           "ALLOWED_PROVIDER_KINDS", "PROVIDER_VERSIONS", "PROVIDER_CONTRACT", "PROVIDER_CONTRACT_HASH",
           "MAX_RUNS", "MAX_CASES", "MAX_EVENTS_PER_RUN", "MAX_SNAPSHOT_BYTES", "MAX_REPORT_BYTES"]
