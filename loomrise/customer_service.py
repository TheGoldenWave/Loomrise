"""Minimum sandbox Widget/Inbox and human material delivery services."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import secrets
from pathlib import PurePath
from typing import Any

from .configuration import ConfigurationPrincipal, ConfigurationService, ReleaseBlocked
from .contracts import new_id, now_iso
from .durable_store import SqliteStore

_MATERIAL_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
}
_AUTHORIZATIONS = {"owned", "licensed", "public_domain", "consented"}
_MAX_MATERIAL_BYTES = 10 * 1024 * 1024


class CustomerService:
    def __init__(self, store: SqliteStore, configuration: ConfigurationService) -> None:
        self.store = store
        self.configuration = configuration

    def open_widget(self, *, tenant_id: str, agent_id: str, entry_id: str) -> dict[str, Any]:
        entry = self.configuration.resolve_sandbox_entry(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
        )
        token = secrets.token_urlsafe(32)
        conversation = self.store.open_customer_conversation(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
            conversation_id=new_id("conv"),
            visitor_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "visitor_token": token,
            "version_id": entry["version_id"],
            "state": conversation["state"],
        }

    def visitor_send(
        self, *, conversation_id: str, visitor_token: str, text: str,
        request_human: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise ValueError("消息必须是 1 至 20000 字符的文本")
        token_hash = hashlib.sha256(visitor_token.encode()).hexdigest()
        messages = self.store.add_visitor_message(
            conversation_id=conversation_id, visitor_token_hash=token_hash,
            text=text, request_human=request_human,
        )
        return messages

    def visitor_messages(self, *, conversation_id: str, visitor_token: str) -> list[dict[str, Any]]:
        return self.store.customer_messages(
            conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(),
        )

    def visitor_download_material(
        self, *, conversation_id: str, visitor_token: str,
        asset_id: str, version_id: str,
    ) -> dict[str, Any]:
        material = self.store.customer_attachment(
            conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(),
            asset_id=asset_id, asset_version_id=version_id,
        )
        if material is None:
            raise KeyError("附件不存在、未发送给当前访客、已撤回或已过期")
        return {
            "version_id": material["version_id"],
            "filename": material["filename"],
            "media_type": material["media_type"],
            "content_hash": material["content_hash"],
            "content_base64": base64.b64encode(material["content"]).decode("ascii"),
        }

    def inbox_list(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
    ) -> list[dict[str, Any]]:
        self._operator(principal, agent_id)
        items = self.store.list_customer_conversations(
            tenant_id=principal.tenant_id, agent_id=agent_id,
        )
        return [{**item, "is_assigned_to_me": item["assigned_to"] == principal.actor_id}
                for item in items]

    def inbox_messages(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
    ) -> list[dict[str, Any]]:
        self._operator(principal, agent_id)
        return self.store.customer_messages(
            conversation_id=conversation_id, tenant_id=principal.tenant_id, agent_id=agent_id,
        )

    def claim(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.store.claim_customer_conversation(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            conversation_id=conversation_id, actor_id=principal.actor_id,
        )

    def reply(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int, text: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise ValueError("消息必须是 1 至 20000 字符的文本")
        return self.store.add_operator_message(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            conversation_id=conversation_id, actor_id=principal.actor_id,
            generation=generation, text=text,
        )

    def create_material(
        self, *, principal: ConfigurationPrincipal, agent_id: str, filename: str,
        display_name: str, authorization: str, content_base64: str,
        expires_at: str | None = None, asset_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if authorization not in _AUTHORIZATIONS:
            raise ValueError("必须明确物料授权范围")
        safe_name = PurePath(filename).name
        extension = PurePath(safe_name).suffix.lower()
        media_type = _MATERIAL_TYPES.get(extension)
        if not safe_name or not display_name.strip() or media_type is None:
            raise ValueError("物料名称不能为空，且文件格式必须受支持")
        if not isinstance(content_base64, str) or len(content_base64) > ((_MAX_MATERIAL_BYTES + 2) // 3) * 4:
            raise ValueError("物料不能为空或超过 10 MiB")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("content_base64 必须是有效 Base64") from exc
        if not content or len(content) > _MAX_MATERIAL_BYTES:
            raise ValueError("物料不能为空或超过 10 MiB")
        _verify_material_signature(extension, content)
        expires = _expiry_to_utc(expires_at) if expires_at else None
        return self.store.save_material(
            tenant_id=principal.tenant_id, agent_id=agent_id, asset_id=asset_id or new_id("asset"),
            version_id=new_id("mv"), display_name=display_name.strip(), filename=safe_name,
            media_type=media_type, authorization=authorization, expires_at=expires,
            content=content,
        )

    def list_materials(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
    ) -> list[dict[str, Any]]:
        self._operator(principal, agent_id)
        return self.store.list_materials(tenant_id=principal.tenant_id, agent_id=agent_id)

    def download_material(
        self, *, principal: ConfigurationPrincipal, agent_id: str, asset_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        material = self.store.material_version(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            asset_id=asset_id, version_id=version_id,
        )
        if material is None:
            raise KeyError("未知物料版本")
        self._assert_sendable(material, current_only=False)
        return {
            "asset_id": asset_id, "version_id": material["version_id"],
            "display_name": material["version_display_name"],
            "filename": material["version_filename"],
            "media_type": material["version_media_type"],
            "authorization": material["version_authorization"],
            "expires_at": material["version_expires_at"],
            "content_hash": material["content_hash"],
            "content_base64": base64.b64encode(material["content"]).decode("ascii"),
        }

    def revoke_material(
        self, *, principal: ConfigurationPrincipal, agent_id: str, asset_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.store.revoke_material(
            tenant_id=principal.tenant_id, agent_id=agent_id, asset_id=asset_id,
        )

    def send_material(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int, asset_id: str, version_id: str, text: str = "",
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        material = self.store.material_version(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            asset_id=asset_id, version_id=version_id,
        )
        if material is None:
            raise KeyError("未知物料版本")
        self._assert_sendable(material)
        return self.store.add_operator_message(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            conversation_id=conversation_id, actor_id=principal.actor_id,
            generation=generation, text=text or f"发送附件：{material['version_display_name']}",
            asset_id=asset_id, asset_version_id=version_id,
        )

    @staticmethod
    def _assert_sendable(material: dict[str, Any], *, current_only: bool = True) -> None:
        if material["state"] != "active":
            raise ReleaseBlocked("物料已撤回")
        if current_only and material["version_id"] != material["current_version_id"]:
            raise ReleaseBlocked("物料版本已变化")
        if material["version_expires_at"] and material["version_expires_at"] <= now_iso():
            raise ReleaseBlocked("物料授权已过期")

    @staticmethod
    def _operator(
        principal: ConfigurationPrincipal, agent_id: str, *, write: bool = False,
    ) -> None:
        roles = {"owner", "editor"} if write else {"owner", "editor", "viewer"}
        if principal.schema_version != "config-api-v1" or principal.role not in roles:
            raise PermissionError("客服工作台权限不足")
        if agent_id not in principal.agent_ids:
            raise PermissionError("专家不在当前授权范围")


class CustomerServiceApplication:
    def __init__(self, service: CustomerService) -> None:
        self.service = service

    def execute(
        self, *, principal: ConfigurationPrincipal, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = self._execute(principal, action, payload)
            return {"schema_version": "customer-service-v1", "ok": True,
                    "result": result, "error": None}
        except PermissionError as exc:
            return self._error("forbidden", str(exc))
        except KeyError as exc:
            return self._error("not_found", str(exc))
        except ReleaseBlocked as exc:
            return self._error("release_blocked", str(exc))
        except RuntimeError as exc:
            return self._error("state_conflict", str(exc))
        except (TypeError, ValueError) as exc:
            return self._error("invalid_request", str(exc))

    def _execute(
        self, principal: ConfigurationPrincipal, action: str, p: dict[str, Any],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if action == "widget.open":
            _keys(p, {"agent_id", "entry_id"})
            return self.service.open_widget(
                tenant_id=principal.tenant_id, agent_id=p["agent_id"], entry_id=p["entry_id"],
            )
        if action == "widget.send":
            allowed = {"conversation_id", "visitor_token", "text", "request_human"}
            _keys(p, allowed, {"request_human"})
            if not isinstance(p.get("request_human", False), bool):
                raise ValueError("request_human 必须是布尔值")
            return self.service.visitor_send(
                conversation_id=p["conversation_id"], visitor_token=p["visitor_token"],
                text=p["text"], request_human=p.get("request_human", False),
            )
        if action == "widget.messages":
            _keys(p, {"conversation_id", "visitor_token"})
            return {"items": self.service.visitor_messages(
                conversation_id=p["conversation_id"], visitor_token=p["visitor_token"],
            )}
        if action == "widget.material.download":
            _keys(p, {"conversation_id", "visitor_token", "asset_id", "version_id"})
            return self.service.visitor_download_material(
                conversation_id=p["conversation_id"], visitor_token=p["visitor_token"],
                asset_id=p["asset_id"], version_id=p["version_id"],
            )
        if action == "inbox.list":
            _keys(p, {"agent_id"})
            return {"items": self.service.inbox_list(principal=principal, agent_id=p["agent_id"])}
        if action == "inbox.messages":
            _keys(p, {"agent_id", "conversation_id"})
            return {"items": self.service.inbox_messages(
                principal=principal, agent_id=p["agent_id"], conversation_id=p["conversation_id"],
            )}
        if action == "inbox.claim":
            _keys(p, {"agent_id", "conversation_id"})
            return self.service.claim(
                principal=principal, agent_id=p["agent_id"], conversation_id=p["conversation_id"],
            )
        if action == "inbox.reply":
            _keys(p, {"agent_id", "conversation_id", "generation", "text"})
            return self.service.reply(
                principal=principal, agent_id=p["agent_id"],
                conversation_id=p["conversation_id"], generation=p["generation"], text=p["text"],
            )
        if action == "material.create":
            required = {"agent_id", "filename", "display_name", "authorization", "content_base64"}
            _keys(p, required, {"expires_at", "asset_id"})
            return self.service.create_material(
                principal=principal, agent_id=p["agent_id"], filename=p["filename"],
                display_name=p["display_name"], authorization=p["authorization"],
                content_base64=p["content_base64"], expires_at=p.get("expires_at"),
                asset_id=p.get("asset_id"),
            )
        if action == "material.list":
            _keys(p, {"agent_id"})
            return {"items": self.service.list_materials(principal=principal, agent_id=p["agent_id"])}
        if action == "material.download":
            _keys(p, {"agent_id", "asset_id"}, {"version_id"})
            return self.service.download_material(
                principal=principal, agent_id=p["agent_id"], asset_id=p["asset_id"],
                version_id=p.get("version_id"),
            )
        if action == "material.revoke":
            _keys(p, {"agent_id", "asset_id"})
            return self.service.revoke_material(
                principal=principal, agent_id=p["agent_id"], asset_id=p["asset_id"],
            )
        if action == "inbox.send_material":
            _keys(p, {"agent_id", "conversation_id", "generation", "asset_id", "version_id"}, {"text"})
            return self.service.send_material(
                principal=principal, agent_id=p["agent_id"],
                conversation_id=p["conversation_id"], generation=p["generation"],
                asset_id=p["asset_id"], version_id=p["version_id"], text=p.get("text", ""),
            )
        raise ValueError("未知客服应用用例")

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"schema_version": "customer-service-v1", "ok": False,
                "result": None, "error": {"code": code, "message": message}}


def _keys(
    payload: dict[str, Any], required: set[str], optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    unknown = set(payload) - required - optional
    missing = required - set(payload)
    if unknown or missing:
        raise ValueError("请求字段不完整或包含未知字段")


def _expiry_to_utc(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("expires_at 必须是带时区的 ISO 日期时间") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at 必须包含时区")
    return parsed.astimezone(timezone.utc).isoformat()


def _verify_material_signature(extension: str, content: bytes) -> None:
    valid = {
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".webp": len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        ".mp4": len(content) >= 12 and content[4:8] == b"ftyp",
        ".webm": content.startswith(b"\x1a\x45\xdf\xa3"),
        ".pdf": content.startswith(b"%PDF-"),
        ".txt": _is_utf8_text(content),
        ".md": _is_utf8_text(content),
    }
    if not valid.get(extension, False):
        raise ValueError("文件内容与扩展名不匹配")


def _is_utf8_text(content: bytes) -> bool:
    try:
        content.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


__all__ = ["CustomerService", "CustomerServiceApplication"]
