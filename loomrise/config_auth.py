"""Trusted local principal loading shared by configuration entry points."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from .configuration import ConfigurationPrincipal

DEFAULT_PRINCIPAL_FILE = Path.home() / ".config" / "loomrise" / "configuration-principal.json"
DEFAULT_DATABASE_FILE = Path.home() / ".local" / "share" / "loomrise" / "configuration.db"
_PRINCIPAL_KEYS = {"tenant_id", "actor_id", "role", "agent_ids"}
_VALID_ROLES = {"viewer", "editor", "owner", "external_agent"}


def load_configuration_principal(path: Path) -> ConfigurationPrincipal:
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError(f"无法读取本地 principal 配置：{path}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("principal 配置必须是普通文件")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("principal 配置文件权限必须为 0600；请移除组和其他用户权限")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("principal 配置必须是有效 UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != _PRINCIPAL_KEYS:
        raise ValueError("principal 配置字段必须且仅包含 tenant_id、actor_id、role、agent_ids")
    if any(not isinstance(value.get(key), str) or not value[key].strip()
           for key in ("tenant_id", "actor_id", "role")):
        raise ValueError("principal 的 tenant_id、actor_id 与 role 必须为非空字符串")
    if value["role"] not in _VALID_ROLES:
        raise ValueError("principal role 不受支持")
    agent_ids = value["agent_ids"]
    if (not isinstance(agent_ids, list) or not agent_ids
            or any(not isinstance(item, str) or not item.strip() for item in agent_ids)
            or len(set(agent_ids)) != len(agent_ids)):
        raise ValueError("principal agent_ids 必须是非空、无重复的字符串数组")
    return ConfigurationPrincipal(
        tenant_id=value["tenant_id"], actor_id=value["actor_id"],
        role=value["role"], agent_ids=tuple(agent_ids),
    )


__all__ = [
    "DEFAULT_DATABASE_FILE", "DEFAULT_PRINCIPAL_FILE", "load_configuration_principal",
]
