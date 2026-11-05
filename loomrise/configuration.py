"""R1 configuration lifecycle shared by HTTP, CLI, and MCP adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .contracts import new_id
from .config_validation import validate_configuration
from .durable_store import SqliteStore, StaleConfigurationRevision
from .graph_advisories import closed_set_advisory
from .knowledge_fetch import fetch_https_text
from .knowledge_documents import (
    KNOWLEDGE_FILE_SUFFIXES,
    MAX_FILE_BYTES,
    KnowledgeFormatUnavailable,
    extract_knowledge_file_text,
)

CONFIG_SCHEMA_VERSION = "config-api-v1"
_WRITE_ROLES = frozenset({"editor", "owner"})
_READ_ROLES = frozenset({"viewer", "editor", "owner", "external_agent"})
# 外部 Agent 在诊断命名空间内仅允许以下显式动作；许可签发/撤销与治理作业
# 一律不在其中，避免 diagnostics.* 的 early return 绕过角色白名单。
_EXTERNAL_AGENT_DIAGNOSTICS_ACTIONS = frozenset({
    "diagnostics.evidence", "diagnostics.report.submit", "diagnostics.report.read",
})
# 治理作业需要注入本地 Provider 并异步调用外部模型，仅本机 CLI 专用入口可用；
# HTTP/MCP 不暴露作业能力（不扩大权限）。应用服务在此显式登记并拒绝，使三条
# 接口共享同一套「作业仅 CLI」合同，不留半成品入口。
_GOVERNANCE_JOB_ACTIONS = frozenset({
    "diagnostics.job.create", "diagnostics.job.run", "diagnostics.job.read",
    "diagnostics.job.cancel", "diagnostics.job.recover", "diagnostics.job.retry",
})
_EXTERNAL_SAFE_PATHS = frozenset({
    "persona.name", "persona.goal", "persona.audience", "persona.greeting",
    "persona.scope", "persona.fallback",
})
_RELEASE_CHECKS = (
    ("candidate_frozen", "配置已冻结为候选", "automatic"),
    ("configuration_valid", "配置结构与规则校验通过", "automatic"),
    ("sources_identified", "知识来源已登记", "knowledge"),
    ("source_permissions", "知识来源授权范围有效", "knowledge"),
    ("knowledge_ready", "知识摄入已完成", "knowledge"),
    ("fixed_samples", "固定验收样例已准备", "evaluation"),
    ("fixed_samples_passed", "固定验收样例全部通过", "evaluation"),
    ("sandbox_selected", "沙盒环境已明确", "release"),
    ("entry_version_bound", "入口绑定目标版本", "release"),
    ("human_approval", "责任人已批准", "approval"),
)
_MISSING = object()


class RevisionConflict(RuntimeError):
    def __init__(self, current: dict[str, Any]) -> None:
        self.current = deepcopy(current)
        super().__init__(f"草稿 revision 已变化，当前为 r{current['revision']}")


class ConfigurationValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = deepcopy(issues)
        super().__init__(f"配置有 {len(issues)} 项提交错误")


class StableVersionError(RuntimeError):
    pass


class ReleaseBlocked(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_path_member(path: str, key: str) -> str:
    if key.isidentifier():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def _same_json_scalar(before: Any, after: Any) -> bool:
    if isinstance(before, bool) or isinstance(after, bool):
        return isinstance(before, bool) and isinstance(after, bool) and before is after
    return before == after


def field_diff(before: Any, after: Any, path: str = "$") -> list[dict[str, Any]]:
    """Return deterministic JSON-path leaf changes, including array indices."""
    if before is _MISSING or after is _MISSING:
        return [{
            "path": path,
            "before": None if before is _MISSING else deepcopy(before),
            "after": None if after is _MISSING else deepcopy(after),
            "before_exists": before is not _MISSING,
            "after_exists": after is not _MISSING,
        }]
    if isinstance(before, dict) and isinstance(after, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(before.keys() | after.keys()):
            child_path = _json_path_member(path, key)
            old = before[key] if key in before else _MISSING
            new = after[key] if key in after else _MISSING
            result.extend(field_diff(old, new, child_path))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = []
        for index in range(max(len(before), len(after))):
            old = before[index] if index < len(before) else _MISSING
            new = after[index] if index < len(after) else _MISSING
            result.extend(field_diff(old, new, f"{path}[{index}]"))
        return result
    if not _same_json_scalar(before, after):
        return [{"path": path, "before": deepcopy(before), "after": deepcopy(after)}]
    return []


def object_diff(before: Any, after: Any) -> dict[str, Any]:
    """Review projection only; stable IDs align objects without changing field_diff."""
    changes: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    collections = {
        "units": ("unit_id", "unit"), "nodes": ("id", "node"),
        "edges": ("id", "edge"), "entry_ports": ("port", "entry_port"),
        "exit_ports": ("port", "exit_port"),
    }

    def walk(old: Any, new: Any, path: str, member: str = "",
             context: dict[str, str] | None = None, *, object_boundary: bool = False) -> None:
        owner = context or {"object_type": "configuration", "object_id": "$"}
        collection = collections.get(member) if (
            path == "$.units"
            or path in {"$.orchestration.nodes", "$.orchestration.edges"}
            or (owner["object_type"] == "unit" and (
                (member in {"entry_ports", "exit_ports"} and path.endswith(f"].{member}"))
                or (member in {"nodes", "edges"} and path.endswith(f"].body.{member}"))
            ))
        ) else None
        if collection:
            if old is _MISSING and isinstance(new, list):
                old = []
            if new is _MISSING and isinstance(old, list):
                new = []
        if isinstance(old, list) and isinstance(new, list) and collection:
            identity, kind = collection

            def index(items: list[Any]) -> dict[str, Any] | None:
                result = {}
                for item in items:
                    key = item.get(identity) if isinstance(item, dict) else None
                    if not isinstance(key, str) or not key.strip() or key in result:
                        return None
                    result[key] = item
                return result

            left, right = index(old), index(new)
            if left is None or right is None:
                diagnostics.append({"path": path, "code": "ambiguous_identity",
                                    "message": "标识缺失或重复，以下明细仅按数组位置比较，无法对齐对象。"})
                changes.extend({**item, **owner, "operation": "positional"}
                               for item in field_diff(old, new, path))
                return
            # Only edge array order defines routing priority; other collections are registries.
            if member == "edges" and list(left) != list(right):
                changes.append({**owner, "object_type": "edge_order", "path": path,
                                "operation": "priority", "before": list(left), "after": list(right)})
            for key in sorted(left.keys() | right.keys()):
                child = f"{path}[{identity}={json.dumps(key, ensure_ascii=False)}]"
                child_owner = {"object_type": kind, "object_id": key}
                walk(left.get(key, _MISSING), right.get(key, _MISSING), child,
                     context=child_owner, object_boundary=True)
            return
        if old is _MISSING or new is _MISSING:
            changes.extend({**item, **owner,
                            "operation": ("added" if old is _MISSING else "removed")
                            if object_boundary else "changed"}
                           for item in field_diff(old, new, path))
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                walk(old.get(key, _MISSING), new.get(key, _MISSING),
                     _json_path_member(path, key), key, owner)
            return
        changes.extend({**item, **owner, "operation": "changed"}
                       for item in field_diff(old, new, path))

    walk(before, after, "$")
    return {"changes": changes, "diagnostics": diagnostics}


def _issues(spec: dict[str, Any], *, submitting: bool) -> list[dict[str, Any]]:
    found = validate_configuration(spec, submitting=submitting)
    return [
        issue.to_dict() if hasattr(issue, "to_dict") else {
            "path": issue.path, "code": issue.code, "message": issue.message,
        }
        for issue in found
    ]


class ConfigurationService:
    """Configuration use cases; storage and validation are server-owned."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def register_stable_version(
        self, *, tenant_id: str, agent_id: str, version_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        if not isinstance(version_id, str) or not version_id.strip():
            raise ValueError("version_id 必须是非空字符串")
        _require_config_object(config)
        value = deepcopy(config)
        issues = _issues(value, submitting=True)
        if issues:
            raise ConfigurationValidationError(issues)
        return self.store.register_stable_config(
            tenant_id=tenant_id, agent_id=agent_id, version_id=version_id,
            config=value, content_hash=_hash(value),
        )

    def get_stable_version(
        self, *, tenant_id: str, agent_id: str, version_id: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        if not isinstance(version_id, str) or not version_id.strip():
            raise ValueError("version_id 必须是非空字符串")
        row = self.store.get_stable_config(
            tenant_id=tenant_id, agent_id=agent_id, version_id=version_id,
        )
        if row is None:
            raise KeyError("未知稳定版本")
        return row

    def list_stable_versions(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        return self.store.list_stable_configs(tenant_id=tenant_id, agent_id=agent_id)

    def update_stable_version(self, **_: Any) -> None:
        raise StableVersionError("稳定版本只读；请创建草稿并冻结候选")

    def delete_stable_version(self, **_: Any) -> None:
        raise StableVersionError("稳定版本不可删除")

    def create_draft(
        self, *, tenant_id: str, agent_id: str, config: dict[str, Any],
        base_version_id: str | None = None,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        _require_config_object(config)
        value = deepcopy(config)
        return self.store.create_config_draft(
            tenant_id=tenant_id, agent_id=agent_id,
            base_version_id=base_version_id, config=value,
        )

    def create_draft_from_stable(
        self, *, tenant_id: str, agent_id: str, base_version_id: str,
    ) -> dict[str, Any]:
        base = self.get_stable_version(
            tenant_id=tenant_id, agent_id=agent_id, version_id=base_version_id,
        )
        return self.create_draft(
            tenant_id=tenant_id, agent_id=agent_id,
            base_version_id=base_version_id, config=base["config"],
        )

    def get_draft(self, *, tenant_id: str, agent_id: str) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        row = self.store.get_config_draft(tenant_id=tenant_id, agent_id=agent_id)
        if row is None:
            raise KeyError("未知配置草稿")
        return row

    def dismiss_graph_advisory(
        self, *, tenant_id: str, agent_id: str, expected_revision: int,
        layer_path: list[str], actor_id: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        _require_revision(expected_revision)
        if (not isinstance(layer_path, list) or len(layer_path) > 16
                or any(not isinstance(item, str) or not item.strip() for item in layer_path)):
            raise ValueError("layer_path 必须是有效图层路径")
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("当前身份缺少操作者标识")
        draft = self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if draft["revision"] != expected_revision:
            raise RevisionConflict(draft)
        advisory = closed_set_advisory(draft["config"], layer_path)
        if advisory is None:
            raise ValueError("当前草稿图层没有可忽略的闭集提示")
        try:
            return self.store.dismiss_config_advisory(
                tenant_id=tenant_id, agent_id=agent_id, source_revision=expected_revision,
                advisory_key=advisory["advisory_key"], layer_path=advisory["layer_path"],
                closed_set_size=advisory["closed_set_size"], actor_id=actor_id,
            )
        except StaleConfigurationRevision:
            raise RevisionConflict(self.get_draft(tenant_id=tenant_id, agent_id=agent_id)) from None

    def save_draft(
        self, *, tenant_id: str, agent_id: str, expected_revision: int,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        _require_revision(expected_revision)
        _require_config_object(config)
        current = self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        value = deepcopy(config)
        diff = field_diff(current["config"], value)
        saved, conflict = self.store.save_config_draft(
            tenant_id=tenant_id, agent_id=agent_id,
            expected_revision=expected_revision, config=value,
        )
        if conflict is not None:
            raise RevisionConflict(conflict)
        return {**saved, "diff": diff, "object_diff": object_diff(current["config"], value)}

    def patch_draft(
        self, *, tenant_id: str, agent_id: str, expected_revision: int,
        changes: list[dict[str, Any]], allowed_paths: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        _require_revision(expected_revision)
        if not isinstance(changes, list):
            raise ValueError("changes 必须是 JSON 对象数组")
        current = self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        config = deepcopy(current["config"])
        allow = set(allowed_paths) if allowed_paths is not None else None
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "value"}:
                raise ValueError("每个 change 必须且仅包含 path 与 value")
            path = change.get("path")
            if not isinstance(path, str) or not path.startswith("$."):
                raise ValueError("patch path 必须是 JSON path")
            normalized = path[2:]
            if allow is not None and normalized not in allow:
                raise PermissionError(f"字段不可修改: {path}")
            _set_json_path(config, path, deepcopy(change.get("value")))
        return self.save_draft(
            tenant_id=tenant_id, agent_id=agent_id,
            expected_revision=expected_revision, config=config,
        )

    def validate_draft(
        self, *, tenant_id: str, agent_id: str, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        if expected_revision is not None:
            _require_revision(expected_revision)
        current = self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if expected_revision is not None and current["revision"] != expected_revision:
            raise RevisionConflict(current)
        issues = _issues(current["config"], submitting=True)
        return {"revision": current["revision"], "valid": not issues, "issues": issues}

    def freeze_candidate(
        self, *, tenant_id: str, agent_id: str, expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        _require_revision(expected_revision)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key 必须是非空字符串")
        previous = self.store.get_config_candidate_by_idempotency_key(
            tenant_id=tenant_id, agent_id=agent_id, idempotency_key=idempotency_key,
        )
        if previous is not None:
            if previous["source_revision"] != expected_revision:
                raise ValueError("幂等键已用于其他草稿 revision")
            return self._candidate_review(previous)
        current = self.get_draft(tenant_id=tenant_id, agent_id=agent_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        issues = _issues(current["config"], submitting=True)
        if issues:
            raise ConfigurationValidationError(issues)
        base = self.get_stable_version(
            tenant_id=tenant_id, agent_id=agent_id,
            version_id=current["base_version_id"],
        )["config"] if current["base_version_id"] else {}
        diff = field_diff(base, current["config"])
        candidate, conflict = self.store.freeze_config_candidate(
            tenant_id=tenant_id, agent_id=agent_id,
            candidate_id=f"cp_{_hash([tenant_id, agent_id, idempotency_key])[:20]}",
            idempotency_key=idempotency_key, expected_revision=expected_revision,
            content_hash=_hash(current["config"]), diff=diff,
        )
        if conflict is not None:
            raise RevisionConflict(conflict)
        return self._candidate_review(candidate)

    def _candidate_review(self, candidate: dict[str, Any]) -> dict[str, Any]:
        base = self.get_stable_version(
            tenant_id=candidate["tenant_id"], agent_id=candidate["agent_id"],
            version_id=candidate["base_version_id"],
        )["config"] if candidate["base_version_id"] else {}
        return {**candidate, "object_diff": object_diff(base, candidate["config"])}

    def get_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("candidate_id 必须是非空字符串")
        row = self.store.get_config_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
        )
        if row is None:
            raise KeyError("未知冻结候选")
        return self._candidate_review(row)

    def list_candidates(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        return [self._candidate_review(row) for row in self.store.list_config_candidates(
            tenant_id=tenant_id, agent_id=agent_id,
        )]

    def compare_snapshots(
        self, *, tenant_id: str, agent_id: str,
        before: dict[str, str], after: dict[str, str],
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)

        def resolve(reference: dict[str, str]) -> dict[str, Any]:
            if (not isinstance(reference, dict) or set(reference) != {'kind', 'id'}
                    or reference.get('kind') not in ('stable', 'candidate')
                    or not isinstance(reference.get('id'), str) or not reference['id'].strip()):
                raise ValueError('比较对象必须是明确的 stable 或 candidate 标识')
            if reference['kind'] == 'stable':
                snapshot = self.get_stable_version(
                    tenant_id=tenant_id, agent_id=agent_id, version_id=reference['id'],
                )
            else:
                snapshot = self.get_candidate(
                    tenant_id=tenant_id, agent_id=agent_id, candidate_id=reference['id'],
                )
            return {**reference, 'config': snapshot['config'], 'content_hash': snapshot['content_hash']}

        left, right = resolve(before), resolve(after)
        return {
            'before': left, 'after': right,
            'diff': field_diff(left['config'], right['config']),
            'object_diff': object_diff(left['config'], right['config']),
        }

    def release_checklist(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        environment: str | None = None, entry_id: str | None = None,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
        )
        issues = _issues(candidate["config"], submitting=True)
        checks = []
        for key, label, source in _RELEASE_CHECKS:
            if key == "candidate_frozen":
                status, detail = (
                    ("passed", "候选状态为 frozen")
                    if candidate["status"] == "frozen"
                    else ("failed", f"候选状态为 {candidate['status']}")
                )
            elif key == "configuration_valid":
                status = "failed" if issues else "passed"
                detail = issues if issues else "服务端配置校验通过"
            elif key == "sources_identified":
                sources = [source for source in self.store.list_knowledge_sources(
                    tenant_id=tenant_id, agent_id=agent_id,
                ) if source["state"] != "revoked"]
                status, detail = (
                    ("passed", {"source_count": len(sources)})
                    if sources else ("pending", "尚无知识来源")
                )
            elif key == "source_permissions":
                sources = [source for source in self.store.list_knowledge_sources(
                    tenant_id=tenant_id, agent_id=agent_id,
                ) if source["state"] != "revoked"]
                invalid = [source["source_id"] for source in sources if source["authorization"] not in {
                    "owned", "licensed", "public_domain", "consented",
                }]
                status, detail = (
                    ("failed", invalid) if invalid else
                    (("passed", "来源授权范围已登记") if sources else ("pending", "尚无授权来源"))
                )
            elif key == "knowledge_ready":
                ready_sources = [source for source in self.store.list_knowledge_sources(
                    tenant_id=tenant_id, agent_id=agent_id,
                ) if source["state"] == "ready"]
                if environment == "sandbox" and version_id:
                    release_state = self.store.sandbox_release_knowledge_state(
                        tenant_id=tenant_id, agent_id=agent_id, version_id=version_id,
                    )
                    if release_state == "stale":
                        status, detail = "failed", "该沙盒版本因知识来源撤回而待重新验收"
                    elif ready_sources:
                        status, detail = "passed", {"ready_source_count": len(ready_sources)}
                    else:
                        status, detail = "pending", "尚无成功摄入且授权有效的知识来源"
                else:
                    status, detail = (
                        ("passed", {"ready_source_count": len(ready_sources)})
                        if ready_sources else ("pending", "尚无成功摄入且授权有效的知识来源")
                    )
            elif key == "fixed_samples" or key == "fixed_samples_passed":
                status, detail = "pending", "固定样例执行服务尚未接入"
            elif key == "sandbox_selected":
                status, detail = (
                    ("passed", "目标环境为 sandbox")
                    if environment == "sandbox" else ("pending", "尚未明确目标沙盒环境")
                )
            elif key == "entry_version_bound":
                status, detail = (
                    ("passed", {"entry_id": entry_id, "version_id": version_id})
                    if environment == "sandbox" and entry_id and version_id
                    else ("pending", "尚未明确沙盒入口与目标版本")
                )
            elif key == "human_approval":
                approval = self.store.release_approval(
                    tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
                    content_hash=candidate["content_hash"],
                    environment=environment or "sandbox", entry_id=entry_id or "",
                    version_id=version_id or "",
                ) if environment and entry_id and version_id else None
                status, detail = (
                    ("passed", {"approved_by": approval["approved_by"], "created_at": approval["created_at"]})
                    if approval else ("pending", "尚无绑定目标沙盒入口/版本的人工批准")
                )
            else:
                status, detail = "pending", "对应服务尚未提供可验证证据"
            checks.append({
                "key": key, "label": label, "source": source,
                "status": status, "detail": detail,
            })
        counts = {status: sum(check["status"] == status for check in checks)
                  for status in ("passed", "failed", "pending")}
        return {
            "candidate_id": candidate_id,
            "checks": checks,
            "progress": {**counts, "total": len(checks)},
            "ready": counts["failed"] == 0 and counts["pending"] == 0,
            "publish_enabled": counts["failed"] == 0 and counts["pending"] == 0,
        }

    def approve_sandbox_release(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        entry_id: str, version_id: str, approved_by: str,
    ) -> dict[str, Any]:
        if not all(isinstance(value, str) and value.strip() for value in
                   (entry_id, version_id, approved_by)):
            raise ValueError("entry_id、version_id、approved_by 必须是非空字符串")
        candidate = self.get_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
        )
        checklist = self.release_checklist(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
            environment="sandbox", entry_id=entry_id, version_id=version_id,
        )
        blockers = [check for check in checklist["checks"]
                    if check["key"] != "human_approval" and check["status"] != "passed"]
        if blockers:
            raise ReleaseBlocked("发布预检尚未通过，不能批准")
        return self.store.approve_release_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
            content_hash=candidate["content_hash"], environment="sandbox",
            entry_id=entry_id, version_id=version_id, approved_by=approved_by,
        )

    def publish_sandbox_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        entry_id: str, version_id: str,
    ) -> dict[str, Any]:
        checklist = self.release_checklist(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
            environment="sandbox", entry_id=entry_id, version_id=version_id,
        )
        if not checklist["ready"]:
            raise ReleaseBlocked("发布预检未全部通过，不能发布")
        return self.store.publish_sandbox_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
            entry_id=entry_id, version_id=version_id,
        )

    def get_sandbox_entry(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        value = self.store.sandbox_entry(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
        )
        if value is None:
            raise KeyError("未知沙盒入口")
        return value

    def list_sandbox_entries(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        entries = self.store.list_sandbox_entries(tenant_id=tenant_id, agent_id=agent_id)
        return [{
            "entry_id": entry["entry_id"], "version_id": entry["version_id"],
            "environment": entry["environment"], "knowledge_state": entry["knowledge_state"],
            "updated_at": entry["updated_at"],
        } for entry in entries]

    def resolve_sandbox_entry(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
    ) -> dict[str, Any]:
        value = self.get_sandbox_entry(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
        )
        if value.get("knowledge_state") != "ready":
            raise ReleaseBlocked("沙盒入口所绑版本待重新验收，不能运行")
        return value

    def create_knowledge_source(
        self, *, tenant_id: str, agent_id: str, kind: str, locator: str,
        display_name: str, authorization: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        if authorization not in {"owned", "licensed", "public_domain", "consented"}:
            raise ValueError("必须明确来源授权范围")
        if kind == "url":
            parsed = urlparse(locator)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("正式摄入 URL 仅接受有效 HTTPS 地址")
        elif kind == "faq":
            if not locator.strip():
                raise ValueError("FAQ 内容不能为空")
        elif kind == "file":
            if Path(locator).suffix.lower() not in KNOWLEDGE_FILE_SUFFIXES:
                raise ValueError("仅支持 TXT、MD、CSV、JSON、HTML、DOCX、XLSX、PDF、DOC 文件")
        else:
            raise ValueError("知识来源类型仅支持 FAQ、URL、文件")
        return self.store.create_knowledge_source(
            tenant_id=tenant_id, agent_id=agent_id,
            source_id=new_id("src"), kind=kind, locator=locator,
            display_name=display_name, authorization=authorization,
        )

    def ingest_knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any]:
        source = self.store.start_knowledge_ingestion(
            tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
        )
        content = None
        try:
            if source["kind"] == "faq":
                content = source["locator"]
            elif source["kind"] == "file":
                path = Path(source["locator"]).expanduser().resolve(strict=True)
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError("文件不存在、不是普通文件或超过 5 MB")
                with path.open("rb") as file:
                    data = file.read(MAX_FILE_BYTES + 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ValueError("文件超过 5 MB")
                content = extract_knowledge_file_text(path.name, data)
            else:
                content = fetch_https_text(source["locator"])
            if not content.strip():
                raise ValueError("来源内容为空")
            chunks = [piece.strip() for piece in re.split(r"\n\s*\n", content) if piece.strip()]
            return self.store.finish_knowledge_ingestion(
                tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
                content=content, chunks=chunks,
            )
        except KnowledgeFormatUnavailable as exc:
            return self.store.finish_knowledge_ingestion(
                tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
                error_code="format_unavailable", error_message=str(exc),
            )
        except (OSError, UnicodeError, ValueError) as exc:
            return self.store.finish_knowledge_ingestion(
                tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
                error_code="parse_failed", error_message=str(exc),
            )

    def retry_knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any]:
        source = self.store.knowledge_source(
            tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
        )
        if source is None:
            raise KeyError("未知知识来源")
        if source["state"] not in {"failed", "queued"}:
            raise ValueError("仅失败或排队中的来源可以重试")
        return self.ingest_knowledge_source(
            tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
        )

    def list_knowledge_sources(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        return self.store.list_knowledge_sources(tenant_id=tenant_id, agent_id=agent_id)

    def revoke_knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any]:
        self._scope(tenant_id, agent_id)
        result = self.store.revoke_knowledge_source(
            tenant_id=tenant_id, agent_id=agent_id, source_id=source_id,
        )
        result["affected_versions"] = self.store.mark_sandbox_versions_for_revalidation(
            tenant_id=tenant_id, agent_id=agent_id,
        )
        return result

    def search_ingested_knowledge(
        self, *, tenant_id: str, agent_id: str, query: str, limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("limit 必须在 1 到 50 之间")
        return self.store.search_knowledge_index(
            tenant_id=tenant_id, agent_id=agent_id, query=query, limit=limit,
        )

    @staticmethod
    def _scope(tenant_id: str, agent_id: str) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (tenant_id, agent_id)):
            raise ValueError("tenant_id 与 agent_id 必须是非空稳定 ID")


def _require_config_object(config: Any) -> None:
    if not isinstance(config, dict):
        raise ValueError("config 必须是 JSON 对象")


def _require_revision(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("expected_revision 必须是正整数")


def _parse_patch_path(path: str) -> list[str | int]:
    if not path.startswith("$."):
        raise ValueError("patch path 必须以 $. 开始")
    tokens: list[str | int] = []
    decoder = json.JSONDecoder()
    index = 1
    while index < len(path):
        marker = path[index]
        if marker == ".":
            index += 1
            start = index
            while index < len(path) and path[index] not in ".[":
                index += 1
            if start == index or "]" in path[start:index]:
                raise ValueError("无效 patch path")
            tokens.append(path[start:index])
            continue
        if marker == "[":
            index += 1
            if index >= len(path):
                raise ValueError("无效 patch path")
            if path[index] == '"':
                try:
                    key, end = decoder.raw_decode(path, index)
                except json.JSONDecodeError as exc:
                    raise ValueError("无效 patch path") from exc
                if not isinstance(key, str) or end >= len(path) or path[end] != "]":
                    raise ValueError("无效 patch path")
                tokens.append(key)
                index = end + 1
                continue
            start = index
            while index < len(path) and path[index].isdigit():
                index += 1
            if start == index or index >= len(path) or path[index] != "]":
                raise ValueError("patch path 仅支持 JSON 数组索引或双引号属性")
            tokens.append(int(path[start:index]))
            index += 1
            continue
        raise ValueError("无效 patch path")
    if not tokens:
        raise ValueError("无效 patch path")
    return tokens


def _set_json_path(root: dict[str, Any], path: str, value: Any) -> None:
    tokens = _parse_patch_path(path)
    current: Any = root
    for token in tokens[:-1]:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise ValueError(f"未知 patch path: {path}")
        elif not isinstance(current, dict) or token not in current:
            raise ValueError(f"未知 patch path: {path}")
        current = current[token]
    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(current, list) or last >= len(current):
            raise ValueError(f"未知 patch path: {path}")
    elif not isinstance(current, dict) or last not in current:
        raise ValueError(f"未知 patch path: {path}")
    current[last] = value


@dataclass(frozen=True)
class ConfigurationPrincipal:
    tenant_id: str
    actor_id: str
    role: str
    agent_ids: tuple[str, ...]
    schema_version: str = CONFIG_SCHEMA_VERSION


class ConfigurationApplication:
    """Server-enforced adapter contract shared by browser, CLI, and MCP."""

    def __init__(self, service: ConfigurationService) -> None:
        self.service = service

    def execute(
        self, *, principal: ConfigurationPrincipal, action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = self._execute(principal=principal, action=action, payload=payload)
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": True, "result": result}
        except RevisionConflict as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "revision_conflict", "current": exc.current}}
        except ConfigurationValidationError as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "validation_failed", "issues": exc.issues}}
        except PermissionError as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "forbidden", "message": str(exc)}}
        except KeyError as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "not_found", "message": str(exc)}}
        except ReleaseBlocked as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "release_blocked", "message": str(exc)}}
        except (TypeError, ValueError) as exc:
            return {"schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                    "error": {"code": "invalid_request", "message": str(exc)}}

    def _execute(
        self, *, principal: ConfigurationPrincipal, action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if principal.schema_version != CONFIG_SCHEMA_VERSION:
            raise ValueError("不支持的配置 Schema 版本")
        if principal.role not in _READ_ROLES:
            raise PermissionError("角色无配置读取权限")
        agent_id = payload.get("agent_id")
        if agent_id not in principal.agent_ids:
            raise PermissionError("专家不在当前授权范围")
        if "tenant_id" in payload and payload["tenant_id"] != principal.tenant_id:
            raise PermissionError("请求租户与可信身份不一致")
        payload = {key: value for key, value in payload.items() if key != "tenant_id"}
        if action.startswith("diagnostics."):
            # 白名单语义统一：外部 Agent 的诊断动作在此显式允许/拒绝，先于诊断
            # 分发表，避免 early return 绕过角色白名单（可审计、单一事实来源）。
            if (principal.role == "external_agent"
                    and action not in _EXTERNAL_AGENT_DIAGNOSTICS_ACTIONS):
                raise PermissionError("外部 Agent 只能读取或提交受限诊断证据与提案")
            return self._diagnostics(principal=principal, action=action, payload=payload)
        if action in {"draft.create", "draft.save", "draft.patch", "candidate.freeze"}:
            if principal.role not in _WRITE_ROLES | {"external_agent"}:
                raise PermissionError("角色无草稿写入权限")
        if action == "advisory.dismiss" and principal.role not in _WRITE_ROLES:
            raise PermissionError("闭集提示忽略留痕仅限 editor 或 owner")
        if action in {"release.approve", "release.publish"} and principal.role != "owner":
            raise PermissionError("批准和发布仅限授权 owner")
        knowledge_write_actions = {
            "knowledge.source.create", "knowledge.ingest", "knowledge.retry", "knowledge.revoke",
        }
        if action in knowledge_write_actions and principal.role not in _WRITE_ROLES:
            raise PermissionError("知识来源变更仅限 editor 或 owner")
        if principal.role == "external_agent" and action not in {
            "draft.get", "draft.create", "draft.patch", "candidate.freeze",
            "candidate.get", "candidate.list", "draft.validate", "stable.list",
            "stable.get", "configuration.compare", "release.checklist", "release.entry.list",
            "knowledge.source.list", "knowledge.search",
        }:
            raise PermissionError("外部 Agent 只能读取或创建受限草稿/候选")
        if action in {"run.status", "run.overlay", "run.diagnostics"} and principal.role not in {"owner", "editor"}:
            raise PermissionError("运行状态仅限 owner 或 editor 查询")

        tenant_id = principal.tenant_id
        if action == 'model.connection':
            _keys(payload, {'agent_id'})
            from .local_config import load_config
            try:
                connection = load_config()
            except (OSError, ValueError, RuntimeError, KeyError):
                return {'configured': False, 'model_id': None, 'status': 'invalid_local_configuration', 'tested': False}
            return {'configured': connection is not None,
                    'model_id': connection['model'] if connection else None,
                    'status': 'configured' if connection else 'not_configured', 'tested': False}
        if action == 'configuration.compare':
            _keys(payload, {'agent_id', 'before', 'after'})
            return self.service.compare_snapshots(
                tenant_id=tenant_id, agent_id=agent_id,
                before=payload['before'], after=payload['after'],
            )
        if action == "run.status":
            _keys(payload, {"agent_id", "run_id"})
            status = self.service.store.read_run_status(
                tenant_id=tenant_id, agent_id=agent_id, run_id=payload["run_id"],
            )
            if status is None:
                raise KeyError("未找到授权范围内的运行")
            return status
        if action == "run.diagnostics":
            allowed = {"agent_id", "run_id", "after_sequence", "limit"}
            unknown = set(payload) - allowed
            missing = {"agent_id", "run_id"} - set(payload)
            if unknown or missing:
                raise ValueError("run.diagnostics 请求字段不完整或包含未知字段")
            diagnostics = self.service.store.read_run_diagnostics(
                tenant_id=tenant_id, agent_id=agent_id, run_id=payload["run_id"],
                after_sequence=payload.get("after_sequence", -1), limit=payload.get("limit", 100),
            )
            if diagnostics is None:
                raise KeyError("未找到授权范围内的运行")
            return diagnostics
        if action == "advisory.dismiss":
            _keys(payload, {"agent_id", "expected_revision", "layer_path"})
            return self.service.dismiss_graph_advisory(
                tenant_id=tenant_id, agent_id=agent_id,
                expected_revision=payload["expected_revision"], layer_path=payload["layer_path"],
                actor_id=principal.actor_id,
            )
        if action == "run.overlay":
            allowed = {"agent_id", "version_id", "from", "to", "channel"}
            unknown = set(payload) - allowed
            missing = {"agent_id", "version_id", "from", "to"} - set(payload)
            if unknown or missing:
                raise ValueError("run.overlay 请求字段不完整或包含未知字段")
            channel = payload.get("channel")
            if channel is not None and channel not in {"text", "voice"}:
                raise ValueError("channel 必须是 text、voice 或省略")
            return self.service.store.read_graph_overlay(
                tenant_id=tenant_id, agent_id=agent_id,
                version_id=payload["version_id"], from_ts=payload["from"],
                to_ts=payload["to"], channel=channel,
            )
        if action == "draft.get":
            _keys(payload, {"agent_id"})
            draft = self.service.get_draft(tenant_id=tenant_id, agent_id=agent_id)
            draft["advisory_dismissals"] = self.service.store.list_config_advisory_dismissals(
                tenant_id=tenant_id, agent_id=agent_id, source_revision=draft["revision"],
            )
            return draft
        if action == "stable.list":
            _keys(payload, {"agent_id"})
            return {"items": self.service.list_stable_versions(
                tenant_id=tenant_id, agent_id=agent_id,
            )}
        if action == "stable.get":
            _keys(payload, {"agent_id", "version_id"})
            return self.service.get_stable_version(
                tenant_id=tenant_id, agent_id=agent_id,
                version_id=payload["version_id"],
            )
        if action == "draft.create":
            _keys(payload, {"agent_id", "base_version_id"})
            base_version_id = payload.get("base_version_id")
            if not base_version_id:
                raise ValueError("必须明确草稿基于哪个稳定版本")
            return self.service.create_draft_from_stable(
                tenant_id=tenant_id, agent_id=agent_id, base_version_id=base_version_id,
            )
        if action == "draft.save":
            _keys(payload, {"agent_id", "expected_revision", "config"})
            return self.service.save_draft(
                tenant_id=tenant_id, agent_id=agent_id,
                expected_revision=payload["expected_revision"], config=payload["config"],
            )
        if action == "draft.patch":
            _keys(payload, {"agent_id", "expected_revision", "changes"})
            allowed = _EXTERNAL_SAFE_PATHS if principal.role == "external_agent" else None
            return self.service.patch_draft(
                tenant_id=tenant_id, agent_id=agent_id,
                expected_revision=payload["expected_revision"], changes=payload["changes"],
                allowed_paths=allowed,
            )
        if action == "draft.validate":
            _keys(payload, {"agent_id", "expected_revision"})
            return self.service.validate_draft(
                tenant_id=tenant_id, agent_id=agent_id,
                expected_revision=payload.get("expected_revision"),
            )
        if action == "candidate.freeze":
            _keys(payload, {"agent_id", "expected_revision", "idempotency_key"})
            return self.service.freeze_candidate(
                tenant_id=tenant_id, agent_id=agent_id,
                expected_revision=payload["expected_revision"],
                idempotency_key=payload["idempotency_key"],
            )
        if action == "candidate.list":
            _keys(payload, {"agent_id"})
            return {"items": self.service.list_candidates(tenant_id=tenant_id, agent_id=agent_id)}
        if action == "candidate.get":
            _keys(payload, {"agent_id", "candidate_id"})
            return self.service.get_candidate(
                tenant_id=tenant_id, agent_id=agent_id, candidate_id=payload["candidate_id"],
            )
        if action == "release.checklist":
            allowed = {"agent_id", "candidate_id", "environment", "entry_id", "version_id"}
            unknown = set(payload) - allowed
            missing = {"agent_id", "candidate_id"} - set(payload)
            if unknown or missing:
                raise ValueError("release.checklist 请求字段不完整或包含未知字段")
            target = {key: payload[key] for key in ("environment", "entry_id", "version_id")
                      if payload.get(key) is not None}
            if target and set(target) != {"environment", "entry_id", "version_id"}:
                raise ValueError("environment、entry_id、version_id 必须同时提供")
            return self.service.release_checklist(
                tenant_id=tenant_id, agent_id=agent_id,
                candidate_id=payload["candidate_id"],
                **target,
            )
        if action == "release.approve":
            _keys(payload, {"agent_id", "candidate_id", "entry_id", "version_id"})
            return self.service.approve_sandbox_release(
                tenant_id=tenant_id, agent_id=agent_id,
                candidate_id=payload["candidate_id"], entry_id=payload["entry_id"],
                version_id=payload["version_id"], approved_by=principal.actor_id,
            )
        if action == "release.publish":
            _keys(payload, {"agent_id", "candidate_id", "entry_id", "version_id"})
            return self.service.publish_sandbox_candidate(
                tenant_id=tenant_id, agent_id=agent_id,
                candidate_id=payload["candidate_id"], entry_id=payload["entry_id"],
                version_id=payload["version_id"],
            )
        if action == "release.entry.get":
            _keys(payload, {"agent_id", "entry_id"})
            return self.service.get_sandbox_entry(
                tenant_id=tenant_id, agent_id=agent_id, entry_id=payload["entry_id"],
            )
        if action == "release.entry.list":
            _keys(payload, {"agent_id"})
            return {"items": self.service.list_sandbox_entries(
                tenant_id=tenant_id, agent_id=agent_id,
            )}
        if action == "release.entry.resolve":
            _keys(payload, {"agent_id", "entry_id"})
            return self.service.resolve_sandbox_entry(
                tenant_id=tenant_id, agent_id=agent_id, entry_id=payload["entry_id"],
            )
        if action == "knowledge.source.create":
            _keys(payload, {"agent_id", "kind", "locator", "display_name", "authorization"})
            return self.service.create_knowledge_source(
                tenant_id=tenant_id, agent_id=agent_id, kind=payload["kind"],
                locator=payload["locator"], display_name=payload["display_name"],
                authorization=payload["authorization"],
            )
        if action == "knowledge.source.list":
            _keys(payload, {"agent_id"})
            return {"items": self.service.list_knowledge_sources(
                tenant_id=tenant_id, agent_id=agent_id,
            )}
        if action in {"knowledge.ingest", "knowledge.retry", "knowledge.revoke"}:
            _keys(payload, {"agent_id", "source_id"})
            method = {
                "knowledge.ingest": self.service.ingest_knowledge_source,
                "knowledge.retry": self.service.retry_knowledge_source,
                "knowledge.revoke": self.service.revoke_knowledge_source,
            }[action]
            return method(
                tenant_id=tenant_id, agent_id=agent_id, source_id=payload["source_id"],
            )
        if action == "knowledge.search":
            unknown = set(payload) - {"agent_id", "query", "limit"}
            missing = {"agent_id", "query"} - set(payload)
            if unknown or missing:
                raise ValueError("knowledge.search 请求字段不完整或包含未知字段")
            return {"items": self.service.search_ingested_knowledge(
                tenant_id=tenant_id, agent_id=agent_id,
                query=payload["query"], limit=payload.get("limit", 10),
            )}
        raise ValueError("未知配置用例")

    def _diagnostics(self, *, principal: ConfigurationPrincipal, action: str,
                     payload: dict[str, Any]) -> dict[str, Any]:
        # 治理作业必须注入本地 Provider 并异步调用外部模型，仅本机 CLI 专用入口
        # 可用。应用服务在此显式登记并拒绝，使 HTTP/MCP 不暴露作业能力。
        if action in _GOVERNANCE_JOB_ACTIONS:
            raise PermissionError("治理作业仅本机 CLI 可用，HTTP/MCP 不暴露作业入口")
        from .diagnostics import DiagnosticsService

        service = DiagnosticsService(self.service.store)
        fields = {
            "diagnostics.permission.issue": ({"agent_id", "recipient_actor_id", "run_ids"},
                                              {"case_ids", "expires_in_seconds"}, service.issue),
            "diagnostics.permission.revoke": ({"agent_id", "permission_id"}, set(), service.revoke),
            "diagnostics.evidence": ({"agent_id", "permission_id"}, set(), service.read_evidence),
            "diagnostics.report.submit": ({"agent_id", "permission_id", "snapshot_id", "input_hash", "report"},
                                          set(), service.submit_report),
            "diagnostics.report.read": ({"agent_id", "report_id"}, set(), service.read_report),
        }
        if action not in fields:
            raise ValueError("未知诊断用例")
        required, optional, method = fields[action]
        if required - payload.keys() or payload.keys() - (required | optional):
            raise ValueError("诊断请求字段不完整或包含未知字段")
        return method(principal=principal, **payload)


def _keys(payload: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    missing = allowed - set(payload)
    if unknown:
        raise ValueError(f"未知请求字段: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"缺少请求字段: {', '.join(sorted(missing))}")


__all__ = [
    "CONFIG_SCHEMA_VERSION", "ConfigurationApplication", "ConfigurationPrincipal",
    "ConfigurationService", "ConfigurationValidationError", "ReleaseBlocked", "RevisionConflict",
    "StableVersionError", "field_diff",
]
