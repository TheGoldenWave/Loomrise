"""R1 configuration lifecycle shared by HTTP, CLI, and MCP adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable

from .config_validation import validate_configuration
from .durable_store import SqliteStore

CONFIG_SCHEMA_VERSION = "config-api-v1"
_WRITE_ROLES = frozenset({"editor", "owner"})
_READ_ROLES = frozenset({"viewer", "editor", "owner", "external_agent"})
_EXTERNAL_SAFE_PATHS = frozenset({
    "persona.name", "persona.goal", "persona.audience", "persona.greeting",
    "persona.scope", "persona.fallback",
})
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
        return {**saved, "diff": diff}

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
            return previous
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
        return candidate

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
        return row

    def check_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
    ) -> dict[str, Any]:
        """Return a deterministic readiness diagnostic without changing state."""
        candidate = self.get_candidate(
            tenant_id=tenant_id, agent_id=agent_id, candidate_id=candidate_id,
        )
        config = candidate["config"]
        issues = _issues(config, submitting=True)
        frozen = candidate["status"] == "frozen"
        hash_matches = candidate["content_hash"] == _hash(config)

        frozen_reasons: list[str] = []
        frozen_paths = ["$.status", "$.content_hash", "$.config"]
        if not frozen:
            frozen_reasons.append("候选状态不是 frozen")
        if not hash_matches:
            frozen_reasons.append("候选内容哈希与冻结配置不一致")
        if issues:
            frozen_reasons.append("冻结配置未通过提交校验")
        configuration_valid = not frozen_reasons
        validation_paths = sorted({issue["path"] for issue in issues})
        frozen_evidence = [{
            "reference": f"candidate:{candidate_id}",
            "json_paths": frozen_paths,
        }, {
            "reference": "configuration_validation",
            "json_paths": validation_paths,
        }]
        checks = [{
            "id": "frozen_configuration",
            "status": "pass" if configuration_valid else "fail",
            "blocking": not configuration_valid,
            "reason": (
                "冻结状态、内容哈希与提交校验均通过"
                if configuration_valid else "；".join(frozen_reasons)
            ),
            "evidence": frozen_evidence,
        }, {
            "id": "source_authorization",
            "status": "not_assessable",
            "blocking": True,
            "reason": "R1 没有服务端来源登记表或授权证据",
            "evidence": [],
        }, {
            "id": "candidate_business_permissions",
            "status": "not_assessable",
            "blocking": True,
            "reason": "R1 没有候选绑定的业务权限证据",
            "evidence": [],
        }, {
            "id": "fixed_samples",
            "status": "not_assessable",
            "blocking": True,
            "reason": "R1 没有固定样例集及候选绑定的运行器",
            "evidence": [],
        }]
        return {
            "candidate_id": candidate_id,
            "readiness": "ready" if all(not check["blocking"] for check in checks) else "blocked",
            "interpretation": "readiness_diagnostic_only_not_publish_authorization",
            "checks": checks,
        }

    def list_candidates(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        self._scope(tenant_id, agent_id)
        return self.store.list_config_candidates(tenant_id=tenant_id, agent_id=agent_id)

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
        if action in {"draft.create", "draft.save", "draft.patch", "candidate.freeze"}:
            if principal.role not in _WRITE_ROLES | {"external_agent"}:
                raise PermissionError("角色无草稿写入权限")
        if principal.role == "external_agent" and action not in {
            "draft.get", "draft.create", "draft.patch", "candidate.freeze",
            "candidate.get", "candidate.list", "candidate.checklist",
            "draft.validate", "stable.list", "stable.get",
        }:
            raise PermissionError("外部 Agent 只能读取或创建受限草稿/候选")

        tenant_id = principal.tenant_id
        if action == "draft.get":
            _keys(payload, {"agent_id"})
            return self.service.get_draft(tenant_id=tenant_id, agent_id=agent_id)
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
        if action == "candidate.checklist":
            _keys(payload, {"agent_id", "candidate_id"})
            return self.service.check_candidate(
                tenant_id=tenant_id, agent_id=agent_id, candidate_id=payload["candidate_id"],
            )
        raise ValueError("未知配置用例")


def _keys(payload: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    missing = allowed - set(payload)
    if unknown:
        raise ValueError(f"未知请求字段: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"缺少请求字段: {', '.join(sorted(missing))}")


__all__ = [
    "CONFIG_SCHEMA_VERSION", "ConfigurationApplication", "ConfigurationPrincipal",
    "ConfigurationService", "ConfigurationValidationError", "RevisionConflict",
    "StableVersionError", "field_diff",
]
