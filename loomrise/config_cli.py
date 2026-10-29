"""R1 configuration CLI backed by the shared application service.

The principal is provisioned in a local, owner-managed file. Tenant and role
are intentionally absent from command arguments so a caller cannot self-assign
scope or permissions for an operation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, TextIO

from .configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationApplication,
    ConfigurationService,
)
from .durable_store import SqliteStore
from .config_auth import (
    DEFAULT_DATABASE_FILE, DEFAULT_PRINCIPAL_FILE, load_configuration_principal,
)

_EXIT_OK = 0
_EXIT_OPERATION_FAILED = 2
_EXIT_REVISION_CONFLICT = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loomrise-config",
        description="读取和修改 Loomrise 配置草稿；候选不会自动获批或发布。",
    )
    groups = parser.add_subparsers(dest="resource", required=True)
    serve = groups.add_parser("serve", help="启动仅本机可访问的配置 HTTP API")
    serve.add_argument("--port", type=int, default=8766)
    groups.add_parser("mcp", help="启动绑定本机可信身份的 stdio MCP 服务")

    draft = groups.add_parser("draft", help="配置草稿")
    draft_actions = draft.add_subparsers(dest="action", required=True)

    read = draft_actions.add_parser("read", help="读取当前草稿与 revision")
    read.add_argument("--agent-id", required=True)
    _add_json_flag(read)

    create = draft_actions.add_parser("create", help="基于稳定版本创建草稿")
    create.add_argument("--agent-id", required=True)
    create.add_argument("--base-version-id", required=True)
    _add_json_flag(create)

    patch = draft_actions.add_parser("patch", help="按预期 revision 修改字段")
    patch.add_argument("--agent-id", required=True)
    patch.add_argument("--revision", required=True, type=int)
    patch.add_argument(
        "--changes", required=True,
        help="JSON 数组，或 @path 指向包含 JSON 数组的 UTF-8 文件",
    )
    _add_json_flag(patch)

    validate = draft_actions.add_parser("validate", help="校验当前草稿")
    validate.add_argument("--agent-id", required=True)
    validate.add_argument("--revision", type=int)
    _add_json_flag(validate)

    candidate = groups.add_parser("candidate", help="冻结候选及字段差异")
    candidate_actions = candidate.add_subparsers(dest="action", required=True)

    listing = candidate_actions.add_parser("list", help="列出冻结候选")
    listing.add_argument("--agent-id", required=True)
    _add_json_flag(listing)

    candidate_read = candidate_actions.add_parser("read", help="读取候选详情")
    candidate_read.add_argument("--agent-id", required=True)
    candidate_read.add_argument("--candidate-id", required=True)
    _add_json_flag(candidate_read)

    freeze = candidate_actions.add_parser("freeze", help="冻结当前草稿 revision 为候选")
    freeze.add_argument("--agent-id", required=True)
    freeze.add_argument("--revision", required=True, type=int)
    freeze.add_argument("--idempotency-key", required=True)
    _add_json_flag(freeze)

    stable = groups.add_parser("stable", help="查看或导入已确认的稳定快照")
    stable_actions = stable.add_subparsers(dest="action", required=True)
    stable_list = stable_actions.add_parser("list", help="列出可信范围内的稳定版本")
    stable_list.add_argument("--agent-id", required=True)
    _add_json_flag(stable_list)
    stable_read = stable_actions.add_parser("read", help="读取不可变稳定版本详情")
    stable_read.add_argument("--agent-id", required=True)
    stable_read.add_argument("--version-id", required=True)
    _add_json_flag(stable_read)
    stable_import = stable_actions.add_parser("import", help="导入现有稳定快照；不执行审批或发布")
    stable_import.add_argument("--agent-id", required=True)
    stable_import.add_argument("--version-id", required=True)
    stable_import.add_argument("--config", required=True, help="JSON 对象文件路径")
    _add_json_flag(stable_import)

    release = groups.add_parser("release", help="发布前检查（只读，不执行发布）")
    release_actions = release.add_subparsers(dest="action", required=True)
    checklist = release_actions.add_parser("checklist", help="运行十项发布预检")
    checklist.add_argument("--agent-id", required=True)
    checklist.add_argument("--candidate-id", required=True)
    _add_json_flag(checklist)

    return parser


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    # Output remains JSON even without this flag; it is explicit for scripts and
    # matches the --json convention of the existing Loomrise CLI.
    parser.add_argument("--json", action="store_true", help="输出标准配置 API JSON envelope")


def _load_changes(raw: str) -> list[dict[str, Any]]:
    if raw == "-":
        source = sys.stdin.read()
    elif raw.startswith("@"):
        source = Path(raw[1:]).read_text(encoding="utf-8")
    else:
        source = raw
    try:
        changes = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"changes 不是有效 JSON：{exc.msg}") from exc
    if not isinstance(changes, list) or any(not isinstance(item, dict) for item in changes):
        raise ValueError("changes 必须是 JSON 对象数组")
    return changes


def _load_json_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("配置文件必须是有效 UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("配置文件根节点必须是 JSON 对象")
    return value


def _request(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    agent_id = args.agent_id
    resource, action = args.resource, args.action
    if resource == "draft":
        if action == "read":
            return "draft.get", {"agent_id": agent_id}
        if action == "create":
            return "draft.create", {
                "agent_id": agent_id, "base_version_id": args.base_version_id,
            }
        if action == "patch":
            return "draft.patch", {
                "agent_id": agent_id, "expected_revision": args.revision,
                "changes": _load_changes(args.changes),
            }
        if action == "validate":
            payload: dict[str, Any] = {"agent_id": agent_id}
            if args.revision is not None:
                payload["expected_revision"] = args.revision
            return "draft.validate", payload
    if resource == "candidate":
        if action == "list":
            return "candidate.list", {"agent_id": agent_id}
        if action == "read":
            return "candidate.get", {
                "agent_id": agent_id, "candidate_id": args.candidate_id,
            }
        if action == "freeze":
            return "candidate.freeze", {
                "agent_id": agent_id, "expected_revision": args.revision,
                "idempotency_key": args.idempotency_key,
            }
    if resource == "stable":
        if action == "list":
            return "stable.list", {"agent_id": agent_id}
        if action == "read":
            return "stable.get", {"agent_id": agent_id, "version_id": args.version_id}
    if resource == "release" and action == "checklist":
        return "release.checklist", {
            "agent_id": agent_id, "candidate_id": args.candidate_id,
        }
    raise ValueError("未知配置命令")


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def main(
    argv: list[str] | None = None,
    *,
    principal_path: Path | None = None,
    database_path: Path | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Run the configuration CLI; injectable paths/stream are for local tests."""
    out = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    trusted_path = principal_path or Path(
        os.environ.get("LOOMRISE_PRINCIPAL_FILE", DEFAULT_PRINCIPAL_FILE),
    )
    db_path = database_path or Path(
        os.environ.get("LOOMRISE_CONFIGURATION_DB", DEFAULT_DATABASE_FILE),
    )
    if args.resource == "serve":
        from .config_http import serve_configuration_http
        serve_configuration_http(
            port=args.port, principal_path=trusted_path, database_path=db_path,
        )
        return _EXIT_OK
    if args.resource == "mcp":
        from .adapters.mcp import run_configuration_mcp
        principal = load_configuration_principal(trusted_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SqliteStore(str(db_path))
        try:
            run_configuration_mcp(
                ConfigurationApplication(ConfigurationService(store)),
                principal=principal,
            )
        finally:
            store.close()
        return _EXIT_OK
    try:
        principal = load_configuration_principal(trusted_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = SqliteStore(str(db_path))
        try:
            service = ConfigurationService(store)
            if args.resource == "stable" and args.action == "import":
                if principal.role != "owner" or args.agent_id not in principal.agent_ids:
                    response = _failure("forbidden", "稳定快照导入仅限授权 owner")
                else:
                    record = service.register_stable_version(
                        tenant_id=principal.tenant_id,
                        agent_id=args.agent_id,
                        version_id=args.version_id,
                        config=_load_json_object(args.config),
                    )
                    response = {
                        "schema_version": CONFIG_SCHEMA_VERSION, "ok": True,
                        "result": record, "error": None,
                    }
            else:
                action, payload = _request(args)
                response = ConfigurationApplication(service).execute(
                    principal=principal, action=action, payload=payload,
                )
        finally:
            store.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        response = _failure("configuration_error", str(exc))
    response = {
        "schema_version": response.get("schema_version", CONFIG_SCHEMA_VERSION),
        "ok": response.get("ok", False),
        "result": response.get("result"),
        "error": response.get("error"),
    }
    out.write(json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n")
    if response["ok"]:
        return _EXIT_OK
    if response.get("error", {}).get("code") == "revision_conflict":
        return _EXIT_REVISION_CONFLICT
    return _EXIT_OPERATION_FAILED


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_DATABASE_FILE", "DEFAULT_PRINCIPAL_FILE", "build_parser", "main"]
