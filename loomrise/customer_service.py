"""Minimum sandbox Widget/Inbox and human material delivery services."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import secrets
from pathlib import PurePath
from typing import Any

from .configuration import ConfigurationPrincipal, ConfigurationService, ReleaseBlocked, RevisionConflict
from .contact_pages import contact_paths, contact_schema, contact_templates, validate_contact, validate_generated_contact
from .channel_sandbox import ChannelSandbox
from .widget_configuration import public_faq_suggestions, public_widget_configuration
from .material_processing import make_candidate
from .material_derivatives import SOURCE_TYPES, process_media
from .contracts import new_id, now_iso
from .durable_store import SqliteStore
from .customer_reception import CustomerReception, validate_customer_input
from .customer_statistics import aggregate_reception_statistics
from .inbox_assistance import ASSISTANCE_MESSAGES, InboxAssistanceError, validate_assistance

_MATERIAL_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
}
_AUTHORIZATIONS = {"owned", "licensed", "public_domain", "consented"}
_MAX_MATERIAL_BYTES = 10 * 1024 * 1024


class ContactGenerationError(RuntimeError):
    """A fixed public code; provider errors may contain private connection data."""


class CustomerService:
    def __init__(self, store: SqliteStore, configuration: ConfigurationService, *, reception_provider: Any = None,
                 contact_generation_provider: Any = None) -> None:
        self.store = store
        self.configuration = configuration
        self.channels = ChannelSandbox(store=store)
        self.reception = CustomerReception(store, reception_provider)
        self.contact_generation_provider = contact_generation_provider

    def widget_configuration(self, *, principal: ConfigurationPrincipal, agent_id: str, entry_id: str,
                             contact_version_id: str | None = None, conversation_id: str | None = None,
                             visitor_token: str | None = None) -> dict[str, Any]:
        self._operator(principal, agent_id)
        if contact_version_id is not None and (not isinstance(contact_version_id, str) or not contact_version_id.strip()):
            raise ValueError('联系页版本必须是非空字符串')
        if conversation_id is not None or visitor_token is not None:
            if not isinstance(conversation_id, str) or not isinstance(visitor_token, str):
                raise ValueError('会话标识与凭据必须同时提供')
            entry = self.store.customer_conversation_configuration(
                tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id,
                conversation_id=conversation_id, visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest())
            config, version_id = entry['config'], entry['version_id']
        elif contact_version_id is not None:
            page = self.store.contact_page(tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id)
            if page is None or page['version_id'] != contact_version_id:
                raise ReleaseBlocked('联系页版本已改变或已停用')
            config, version_id = {'widget': page['widget']}, page['version_id']
        else:
            entry = self.configuration.resolve_sandbox_entry(tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id)
            config, version_id = entry['config'], entry['version_id']
        result = {'version_id': version_id, 'widget': public_widget_configuration(config)}
        if contact_version_id is None:
            result['faq_suggestions'] = public_faq_suggestions(config)
        return result

    def open_widget(self, *, tenant_id: str, agent_id: str, entry_id: str,
                    visitor_fields: dict[str, str] | None = None, expected_version_id: str | None = None) -> dict[str, Any]:
        entry = self.configuration.resolve_sandbox_entry(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
        )
        token = secrets.token_urlsafe(32)
        conversation = self.store.open_customer_conversation(
            tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id,
            conversation_id=new_id("conv"),
            visitor_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            visitor_fields=visitor_fields,
            expected_version_id=expected_version_id if expected_version_id is not None else entry['version_id'],
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "visitor_token": token,
            "version_id": entry["version_id"],
            "state": conversation["state"],
        }

    def channel_authorize(self, *, principal: ConfigurationPrincipal, agent_id: str,
                          channel: str, external_account: str, mode: str = 'full') -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if principal.role != 'owner':
            raise PermissionError('渠道授权仅限 owner')
        return self.channels.authorize(tenant_id=principal.tenant_id, agent_id=agent_id, channel=channel, external_account=external_account, mode=mode)

    def channel_revoke(self, *, principal: ConfigurationPrincipal, agent_id: str,
                       channel: str, external_account: str) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if principal.role != 'owner':
            raise PermissionError('渠道撤销仅限 owner')
        return self.channels.revoke(tenant_id=principal.tenant_id, agent_id=agent_id, channel=channel, external_account=external_account)

    def channel_send(self, *, principal: ConfigurationPrincipal, agent_id: str,
                     channel: str, external_account: str, message_id: str, thread_id: str,
                     text: str, attachment_ids: list[str] | None = None) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.channels.send(tenant_id=principal.tenant_id, agent_id=agent_id, channel=channel, external_account=external_account,
                                  message_id=message_id, thread_id=thread_id, text=text,
                                  attachment_ids=attachment_ids)

    def channel_receive(self, *, principal: ConfigurationPrincipal, agent_id: str,
                        channel: str, external_account: str, message_id: str, thread_id: str,
                        text: str) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.channels.receive(tenant_id=principal.tenant_id, agent_id=agent_id, channel=channel, external_account=external_account,
                                     message_id=message_id, thread_id=thread_id, text=text)

    def statistics(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
        from_ts: str | None = None, to_ts: str | None = None,
        channel: str | None = None, version_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        cumulative = self.store.customer_statistics(tenant_id=principal.tenant_id, agent_id=agent_id)
        read_reception = getattr(self.store, "customer_reception_statistics_rows", None)
        if not callable(read_reception):
            raise RuntimeError("客服接待统计来源暂不可用")
        rows = read_reception(tenant_id=principal.tenant_id, agent_id=agent_id)
        reception = aggregate_reception_statistics(
            rows, tenant_id=principal.tenant_id, agent_id=agent_id,
            from_ts=from_ts, to_ts=to_ts, channel=channel, version_id=version_id,
            as_of=now_iso(),
        )
        return {**cumulative, "reception": reception}

    def enable_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str, entry_id: str,
        expected_version_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if principal.role != "owner":
            raise PermissionError("联系页启用和停用仅限授权 owner")
        page = self.store.enable_contact_page(
            tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id,
            expected_version_id=expected_version_id,
        )
        return {
            "entry_id": entry_id, "version_id": page["version_id"],
            "state": page["state"], **contact_paths(agent_id, entry_id, page["version_id"]),
        }

    def get_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str, entry_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        try:
            page = self.store.contact_page(
                tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id,
            )
        except RuntimeError as exc:
            raise ReleaseBlocked(str(exc)) from exc
        if page is None:
            raise KeyError("联系页未启用")
        return {
            "entry_id": entry_id, "version_id": page["version_id"],
            "state": page["state"], "contact": page["contact"],
            **contact_paths(agent_id, entry_id, page["version_id"]),
            "content_hash": page["content_hash"],
        }

    def disable_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str, entry_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if principal.role != "owner":
            raise PermissionError("联系页启用和停用仅限授权 owner")
        page = self.store.disable_contact_page(
            tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id,
        )
        return {"entry_id": entry_id, "version_id": page["version_id"], "state": page["state"]}

    def preview_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        draft = self.configuration.get_draft(tenant_id=principal.tenant_id, agent_id=agent_id)
        return {"state": "draft", "revision": draft["revision"],
                "contact": validate_contact(draft["config"].get("contact", {}))}

    def save_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
        expected_revision: int, contact: dict[str, Any],
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        value = validate_contact(contact)
        current = self.configuration.get_draft(tenant_id=principal.tenant_id, agent_id=agent_id)
        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        config = deepcopy(current["config"])
        config["contact"] = value
        draft = self.configuration.save_draft(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            expected_revision=expected_revision, config=config,
        )
        return {"state": "draft", "revision": draft["revision"], "contact": value}

    async def generate_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
        expected_revision: int, brief: str, template_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('expected_revision 必须是非负整数')
        if not isinstance(brief, str) or not brief.strip() or len(brief) > 4000 or '\x00' in brief:
            raise ValueError('联系页素材必须是 1–4000 字符的非空文本')
        if template_id is not None and (not isinstance(template_id, str)
                or template_id not in {item['id'] for item in contact_templates()}):
            raise ValueError('联系页模板不受支持')
        current = self.configuration.get_draft(tenant_id=principal.tenant_id, agent_id=agent_id)
        if current['revision'] != expected_revision:
            raise RevisionConflict(current)
        provider = self.contact_generation_provider
        if provider is None or not callable(getattr(provider, 'generate_contact', None)):
            raise ContactGenerationError('generation_unavailable')
        try:
            provider = provider.for_run() if callable(getattr(provider, 'for_run', None)) else provider
            output = await provider.generate_contact(brief=brief, template_id=template_id)
        except Exception:
            raise ContactGenerationError('generation_failed') from None
        current = self.configuration.get_draft(tenant_id=principal.tenant_id, agent_id=agent_id)
        if current['revision'] != expected_revision:
            raise RevisionConflict(current)
        try:
            if not isinstance(output, dict) or set(output) != {'contact', 'model_evidence'}:
                raise ValueError('invalid generation result')
            contact = validate_generated_contact(output['contact'], template_id=template_id)
            evidence = output['model_evidence']
            if (not isinstance(evidence, dict) or set(evidence) != {
                    'model', 'response_id', 'usage', 'duration_ms', 'provider'}
                    or any(not isinstance(evidence[key], str) or not evidence[key].strip()
                           or len(evidence[key]) > 200 or '\x00' in evidence[key]
                           for key in ('model', 'response_id', 'provider'))
                    or type(evidence['duration_ms']) is not int or evidence['duration_ms'] < 0
                    or not isinstance(evidence['usage'], dict)
                    or set(evidence['usage']) - {'input_tokens', 'output_tokens', 'total_tokens'}
                    or any(type(count) is not int or count < 0 for count in evidence['usage'].values())):
                raise ValueError('invalid generation evidence')
        except Exception:
            raise ContactGenerationError('generation_failed') from None
        return {'state': 'proposal', 'base_revision': expected_revision,
                'contact': contact, 'model_evidence': evidence}

    def open_contact_page(
        self, *, principal: ConfigurationPrincipal, agent_id: str, entry_id: str, version_id: str,
        visitor_fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        if not isinstance(version_id, str) or not version_id.strip():
            raise ValueError("联系页版本必须是非空字符串")
        token = secrets.token_urlsafe(32)
        conversation = self.store.open_customer_conversation(
            tenant_id=principal.tenant_id, agent_id=agent_id, entry_id=entry_id,
            conversation_id=new_id("conv"), visitor_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            contact_version_id=version_id,
            visitor_fields=visitor_fields,
        )
        return {"conversation_id": conversation["conversation_id"], "visitor_token": token,
                "version_id": conversation["release_version"], "state": conversation["state"]}

    def visitor_send(
        self, *, conversation_id: str, visitor_token: str, text: str,
        request_human: bool = False,
    ) -> dict[str, Any]:
        validate_customer_input(text, visitor_token, request_human)
        token_hash = hashlib.sha256(visitor_token.encode()).hexdigest()
        messages = self.store.add_visitor_message(
            conversation_id=conversation_id, visitor_token_hash=token_hash,
            text=text, request_human=request_human,
        )
        return messages

    async def visitor_send_with_reception(self, *, conversation_id: str, visitor_token: str, text: str,
                                          request_human: bool = False, message_id: str | None = None) -> dict[str, Any]:
        return await self.reception.receive(conversation_id=conversation_id, visitor_token=visitor_token,
            text=text, request_human=request_human, message_id=message_id)

    def visitor_send_with_responder(self, *, conversation_id: str, visitor_token: str,
                                    text: str, request_human: bool = False,
                                    responder: Any = None) -> dict[str, Any]:
        visitor = self.visitor_send(conversation_id=conversation_id, visitor_token=visitor_token,
                                    text=text, request_human=request_human)
        if request_human or responder is None:
            return {'visitor': visitor, 'assistant': None, 'auto_reply': 'disabled' if responder is None else 'skipped_human'}
        if not callable(responder):
            raise ValueError('responder 必须是可调用对象')
        conversation = self.store.conversation_configuration_by_token(
            conversation_id=conversation_id, visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest())
        response = responder(text, conversation['config'])
        if not isinstance(response, str) or not response.strip():
            raise ValueError('responder 必须返回非空文本')
        assistant = self.store.add_assistant_message(conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(), text=response,
            version_id=conversation['version_id'])
        return {'visitor': visitor, 'assistant': assistant, 'auto_reply': 'simulated'}

    def visitor_messages(self, *, conversation_id: str, visitor_token: str) -> list[dict[str, Any]]:
        return self.store.customer_messages(
            conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(),
        )

    def visitor_download_material(
        self, *, conversation_id: str, visitor_token: str,
        asset_id: str, version_id: str, derivative_id: str | None = None,
    ) -> dict[str, Any]:
        if derivative_id is not None and (not isinstance(derivative_id, str) or not derivative_id.strip()):
            raise ValueError('derivative_id 必须是非空字符串')
        material = self.store.customer_attachment(
            conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(),
            asset_id=asset_id, asset_version_id=version_id, derivative_id=derivative_id,
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
            tenant_id=principal.tenant_id, agent_id=agent_id, actor_id=principal.actor_id,
        )
        return [{**item, "is_assigned_to_me": item["assigned_to"] == principal.actor_id}
                for item in items]

    def inbox_events(
        self, *, principal: ConfigurationPrincipal, agent_id: str,
        after_sequence: int, limit: int = 50,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        return self.store.list_customer_inbox_events(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            after_sequence=after_sequence, limit=limit,
        )

    def inbox_consumer_cursor(
        self, *, principal: ConfigurationPrincipal, agent_id: str, consumer_id: str,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        return self.store.get_or_create_customer_inbox_consumer_cursor(
            tenant_id=principal.tenant_id, agent_id=agent_id, actor_id=principal.actor_id,
            consumer_id=consumer_id,
        )

    def ack_inbox_consumer(
        self, *, principal: ConfigurationPrincipal, agent_id: str, consumer_id: str,
        through_sequence: int,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id)
        return self.store.ack_customer_inbox_consumer(
            tenant_id=principal.tenant_id, agent_id=agent_id, actor_id=principal.actor_id,
            consumer_id=consumer_id, through_sequence=through_sequence,
        )

    def mark_inbox_read(self, *, principal: ConfigurationPrincipal, agent_id: str,
                        conversation_id: str, through_sequence: int) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.store.mark_customer_read(tenant_id=principal.tenant_id, agent_id=agent_id,
            actor_id=principal.actor_id, conversation_id=conversation_id, through_sequence=through_sequence)

    def inbox_preferences(self, *, principal: ConfigurationPrincipal, agent_id: str) -> dict[str, bool]:
        self._operator(principal, agent_id)
        return {**self.store.inbox_preferences(tenant_id=principal.tenant_id, agent_id=agent_id,
            actor_id=principal.actor_id), 'can_edit': principal.role in {'owner', 'editor'}}

    def save_inbox_preferences(self, *, principal: ConfigurationPrincipal, agent_id: str,
                               new_messages: bool, handoff: bool) -> dict[str, bool]:
        self._operator(principal, agent_id, write=True)
        return {**self.store.save_inbox_preferences(tenant_id=principal.tenant_id, agent_id=agent_id,
            actor_id=principal.actor_id, new_messages=new_messages, handoff=handoff), 'can_edit': True}

    def inbox_messages(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
    ) -> list[dict[str, Any]]:
        self._operator(principal, agent_id)
        return self.store.customer_messages(
            conversation_id=conversation_id, tenant_id=principal.tenant_id, agent_id=agent_id,
        )

    def _assistance_snapshot(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int, through_sequence: int,
    ) -> dict[str, Any]:
        if not isinstance(agent_id, str):
            raise ValueError('专家标识无效')
        self._operator(principal, agent_id, write=True)
        return self.store.customer_assistance_snapshot(tenant_id=principal.tenant_id, agent_id=agent_id,
            conversation_id=conversation_id, actor_id=principal.actor_id,
            generation=generation, through_sequence=through_sequence)

    async def generate_inbox_assistance(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int, through_sequence: int,
    ) -> dict[str, Any]:
        scope = {'principal': principal, 'agent_id': agent_id, 'conversation_id': conversation_id,
                 'generation': generation, 'through_sequence': through_sequence}
        snapshot = self._assistance_snapshot(**scope)
        model_id = snapshot['config'].get('ai_reception', {}).get('model_id')
        provider = self.reception.provider
        if not model_id or not snapshot['sources'] or not callable(getattr(provider, 'assist', None)):
            raise InboxAssistanceError('assistance_unavailable')
        try:
            provider = provider.for_run() if callable(getattr(provider, 'for_run', None)) else provider
            if getattr(provider, 'model', None) != model_id or not callable(getattr(provider, 'assist', None)):
                raise InboxAssistanceError('assistance_unavailable')
            async with asyncio.timeout(65):
                generated = await provider.assist(persona=snapshot['persona'], sources=snapshot['sources'],
                                                  history=snapshot['history'])
        except asyncio.CancelledError:
            raise
        except InboxAssistanceError:
            raise
        except TimeoutError:
            raise InboxAssistanceError('assistance_timeout') from None
        except Exception as exc:
            # SDK/provider exception messages may contain credentials or connection URLs.
            code = 'assistance_failed'
            if type(exc).__name__ == 'ModelProviderError':
                code = {'model_request_timeout': 'assistance_timeout',
                        'invalid_model_assistance': 'assistance_invalid_response'}.get(str(exc), code)
            raise InboxAssistanceError(code) from None
        current = self._assistance_snapshot(**scope)
        if current['snapshot_hash'] != snapshot['snapshot_hash']:
            raise RuntimeError('会话或授权资料已变化，请重新生成辅助内容')
        try:
            proposal = validate_assistance(generated, current['sources'], model_id=model_id)
        except (KeyError, TypeError, ValueError):
            raise InboxAssistanceError('assistance_invalid_response') from None
        titles = {source['source_id']: source['title'] for source in current['sources']}
        return {'state': 'proposal', **proposal,
                'citations': [{**item, 'title': titles[item['source_id']]} for item in proposal['citations']],
                **{key: snapshot[key] for key in ('snapshot_hash', 'generation', 'through_sequence',
                                                  'version_id', 'release_id', 'config_hash')}}

    def check_inbox_assistance(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int, through_sequence: int, snapshot_hash: str,
    ) -> dict[str, Any]:
        if (not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64
                or any(char not in '0123456789abcdef' for char in snapshot_hash)):
            raise ValueError('辅助快照哈希无效')
        snapshot = self._assistance_snapshot(principal=principal, agent_id=agent_id,
            conversation_id=conversation_id, generation=generation, through_sequence=through_sequence)
        if not secrets.compare_digest(snapshot_hash, snapshot['snapshot_hash']):
            raise RuntimeError('会话或授权资料已变化，请重新生成辅助内容')
        return {'valid': True, **{key: snapshot[key] for key in (
            'snapshot_hash', 'generation', 'through_sequence', 'version_id', 'release_id', 'config_hash')}}

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

    def release(
        self, *, principal: ConfigurationPrincipal, agent_id: str, conversation_id: str,
        generation: int,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.store.release_customer_conversation(
            tenant_id=principal.tenant_id, agent_id=agent_id,
            conversation_id=conversation_id, actor_id=principal.actor_id, generation=generation,
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
        items = self.store.list_materials(tenant_id=principal.tenant_id, agent_id=agent_id)
        return [{**item, 'derivatives': self.store.material_derivatives(
            tenant_id=principal.tenant_id, agent_id=agent_id, asset_id=item['asset_id'])['items']} for item in items]

    def processing_candidate(self, *, principal: ConfigurationPrincipal, agent_id: str,
                             asset_id: str, version_id: str | None = None) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        material = self.store.material_version(tenant_id=principal.tenant_id, agent_id=agent_id,
                                                asset_id=asset_id, version_id=version_id)
        if material is None: raise KeyError('未知物料版本')
        self._assert_sendable(material)
        candidate = make_candidate(asset_id=asset_id, version_id=material['version_id'],
                                   filename=material['version_filename'], media_type=material['version_media_type'],
                                   content=bytes(material['content']))
        candidate_id = new_id('matcand')
        self.store.save_material_processing_candidate(candidate_id=candidate_id, tenant_id=principal.tenant_id,
            agent_id=agent_id, asset_id=asset_id, version_id=material['version_id'], kind=candidate.kind,
            status=candidate.status, summary=candidate.summary, source_hash=candidate.source_hash)
        derivation = None
        if material['version_media_type'] in SOURCE_TYPES:
            job = self.store.begin_material_derivation(tenant_id=principal.tenant_id, agent_id=agent_id,
                asset_id=asset_id, version_id=material['version_id'], source_hash=candidate.source_hash)
            processed = process_media(media_type=material['version_media_type'], content=bytes(material['content']))
            derivation = self.store.finish_material_derivation(tenant_id=principal.tenant_id, agent_id=agent_id,
                job_id=job['job_id'], status=processed.status, error_code=processed.reason, artifacts=processed.artifacts)
        return {'candidate_id': candidate_id, 'asset_id': asset_id, 'version_id': version_id or material['version_id'],
                'kind': candidate.kind, 'status': candidate.status, 'summary': candidate.summary,
                'source_hash': candidate.source_hash, 'review_state': candidate.review_state,
                'is_downloadable_derivative': False, 'derivation': derivation}

    def list_material_derivatives(self, *, principal: ConfigurationPrincipal, agent_id: str,
                                  asset_id: str) -> dict[str, Any]:
        self._operator(principal, agent_id)
        return self.store.material_derivatives(tenant_id=principal.tenant_id, agent_id=agent_id, asset_id=asset_id)

    def download_material_derivative(self, *, principal: ConfigurationPrincipal, agent_id: str,
                                     asset_id: str, derivative_id: str) -> dict[str, Any]:
        self._operator(principal, agent_id)
        if not isinstance(derivative_id, str) or not derivative_id.strip():
            raise ValueError('derivative_id 必须是非空字符串')
        artifact = self.store.material_derivative(tenant_id=principal.tenant_id, agent_id=agent_id,
            asset_id=asset_id, derivative_id=derivative_id)
        if artifact is None:
            raise KeyError('派生文件不存在或当前物料版本已失效')
        return {key: artifact[key] for key in ('derivative_id', 'version_id', 'filename', 'media_type', 'content_hash')} | {
            'content_base64': base64.b64encode(artifact['content']).decode('ascii')}

    def review_processing_candidate(self, *, principal: ConfigurationPrincipal, agent_id: str,
                                    candidate_id: str, review_state: str) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        return self.store.review_material_processing_candidate(tenant_id=principal.tenant_id, agent_id=agent_id,
                                                               candidate_id=candidate_id, review_state=review_state)

    def search_material_summaries(self, *, principal: ConfigurationPrincipal, agent_id: str,
                                 query: str, limit: int = 10) -> list[dict[str, Any]]:
        self._operator(principal, agent_id)
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError('检索词必须为 1 至 1000 字符')
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('检索数量须为 1 至 50 的整数')
        return self.store.search_material_summaries(
            tenant_id=principal.tenant_id, agent_id=agent_id, query=query, limit=limit,
        )

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
        generation: int, asset_id: str, version_id: str, text: str = "", derivative_id: str | None = None,
    ) -> dict[str, Any]:
        self._operator(principal, agent_id, write=True)
        if derivative_id is not None and (not isinstance(derivative_id, str) or not derivative_id.strip()):
            raise ValueError('derivative_id 必须是非空字符串')
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
            asset_id=asset_id, asset_version_id=version_id, derivative_id=derivative_id,
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

    async def execute_async(self, *, principal: ConfigurationPrincipal, action: str,
                            payload: dict[str, Any]) -> dict[str, Any]:
        if action not in {'widget.send', 'contact.generate', 'inbox.assistance.generate'}:
            return self.execute(principal=principal, action=action, payload=payload)
        try:
            if action == 'inbox.assistance.generate':
                _keys(payload, {'agent_id', 'conversation_id', 'generation', 'through_sequence'})
                result = await self.service.generate_inbox_assistance(principal=principal, **payload)
            elif action == 'contact.generate':
                _keys(payload, {'agent_id', 'expected_revision', 'brief'}, {'template_id'})
                if 'template_id' in payload and payload['template_id'] is None:
                    raise ValueError('联系页模板不受支持')
                result = await self.service.generate_contact_page(principal=principal, **payload)
            else:
                _keys(payload, {'conversation_id', 'visitor_token', 'text'}, {'request_human', 'message_id'})
                result = await self.service.visitor_send_with_reception(**payload)
            return {'schema_version': 'customer-service-v1', 'ok': True, 'result': result, 'error': None}
        except PermissionError as exc:
            return self._error('forbidden', str(exc))
        except KeyError as exc:
            return self._error('not_found', str(exc))
        except RevisionConflict as exc:
            return self._error('revision_conflict', str(exc))
        except ContactGenerationError as exc:
            if str(exc) == 'generation_unavailable':
                return self._error('generation_unavailable', '未配置联系页生成模型，可继续手动编辑。')
            return self._error('generation_failed', '联系页生成失败，未改动草稿。请检查连接或调整素材后重试。')
        except InboxAssistanceError as exc:
            code = str(exc) if str(exc) in ASSISTANCE_MESSAGES else 'assistance_failed'
            return self._error(code, ASSISTANCE_MESSAGES[code])
        except RuntimeError as exc:
            return self._error('state_conflict', str(exc))
        except (TypeError, ValueError) as exc:
            return self._error('invalid_request', str(exc))

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
        except RevisionConflict as exc:
            return self._error("revision_conflict", str(exc))
        except RuntimeError as exc:
            return self._error("state_conflict", str(exc))
        except (TypeError, ValueError) as exc:
            return self._error("invalid_request", str(exc))

    def _execute(
        self, principal: ConfigurationPrincipal, action: str, p: dict[str, Any],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if action == "widget.open":
            _keys(p, {"agent_id", "entry_id"}, {'visitor_fields', 'expected_version_id'})
            self.service._operator(principal, p['agent_id'])
            if 'expected_version_id' in p and (not isinstance(p['expected_version_id'], str) or not p['expected_version_id']):
                raise ValueError('expected_version_id 必须是非空版本标识')
            return self.service.open_widget(
                tenant_id=principal.tenant_id, agent_id=p["agent_id"], entry_id=p["entry_id"],
                visitor_fields=p.get('visitor_fields'), expected_version_id=p.get('expected_version_id'),
            )
        if action == 'channel.authorize':
            _keys(p, {'agent_id', 'channel', 'external_account'}, {'mode'})
            return self.service.channel_authorize(principal=principal, agent_id=p['agent_id'],
                channel=p['channel'], external_account=p['external_account'], mode=p.get('mode', 'full'))
        if action == 'channel.revoke':
            _keys(p, {'agent_id', 'channel', 'external_account'})
            return self.service.channel_revoke(principal=principal, agent_id=p['agent_id'],
                channel=p['channel'], external_account=p['external_account'])
        if action == 'channel.send':
            _keys(p, {'agent_id', 'channel', 'external_account', 'message_id', 'thread_id', 'text'}, {'attachment_ids'})
            return self.service.channel_send(principal=principal, agent_id=p['agent_id'],
                channel=p['channel'], external_account=p['external_account'], message_id=p['message_id'],
                thread_id=p['thread_id'], text=p['text'], attachment_ids=p.get('attachment_ids'))
        if action == 'channel.receive':
            _keys(p, {'agent_id', 'channel', 'external_account', 'message_id', 'thread_id', 'text'})
            return self.service.channel_receive(principal=principal, agent_id=p['agent_id'],
                channel=p['channel'], external_account=p['external_account'], message_id=p['message_id'],
                thread_id=p['thread_id'], text=p['text'])
        if action == 'customer.statistics':
            _keys(p, {'agent_id'}, {'from', 'to', 'channel', 'version_id'})
            if ('from' in p) != ('to' in p):
                raise ValueError('from 与 to 必须同时提供')
            for key in ('from', 'to'):
                if key in p and not isinstance(p[key], str):
                    raise ValueError(f'{key} 必须是带时区的 ISO 时间')
            if 'channel' in p and (not isinstance(p['channel'], str) or p['channel'] not in {'text', 'voice'}):
                raise ValueError('channel 必须是 text 或 voice')
            if 'version_id' in p and (not isinstance(p['version_id'], str) or not p['version_id'].strip()):
                raise ValueError('version_id 必须是非空版本标识')
            return self.service.statistics(
                principal=principal, agent_id=p['agent_id'],
                from_ts=p.get('from'), to_ts=p.get('to'), channel=p.get('channel'),
                version_id=p.get('version_id'),
            )
        if action == 'widget.configuration':
            _keys(p, {'agent_id', 'entry_id'}, {'contact_version_id', 'conversation_id', 'visitor_token'})
            return self.service.widget_configuration(principal=principal, agent_id=p['agent_id'], entry_id=p['entry_id'],
                contact_version_id=p.get('contact_version_id'), conversation_id=p.get('conversation_id'), visitor_token=p.get('visitor_token'))
        if action == "contact.enable":
            _keys(p, {"agent_id", "entry_id"}, {"expected_version_id"})
            if 'expected_version_id' in p and (not isinstance(p['expected_version_id'], str) or not p['expected_version_id'].strip()):
                raise ValueError('expected_version_id 必须是非空版本标识')
            return self.service.enable_contact_page(
                principal=principal, agent_id=p["agent_id"], entry_id=p["entry_id"],
                expected_version_id=p.get('expected_version_id'),
            )
        if action == "contact.get":
            _keys(p, {"agent_id", "entry_id"})
            return self.service.get_contact_page(
                principal=principal, agent_id=p["agent_id"], entry_id=p["entry_id"],
            )
        if action == "contact.disable":
            _keys(p, {"agent_id", "entry_id"})
            return self.service.disable_contact_page(
                principal=principal, agent_id=p["agent_id"], entry_id=p["entry_id"],
            )
        if action == "contact.templates":
            _keys(p, {"agent_id"})
            self.service._operator(principal, p["agent_id"])
            return {"items": contact_templates(), "schema": contact_schema()}
        if action == "contact.validate":
            _keys(p, {"agent_id", "contact"})
            self.service._operator(principal, p["agent_id"])
            return {"state": "proposal", "contact": validate_contact(p["contact"])}
        if action == "contact.preview":
            _keys(p, {"agent_id"})
            return self.service.preview_contact_page(principal=principal, agent_id=p["agent_id"])
        if action == "contact.save":
            _keys(p, {"agent_id", "expected_revision", "contact"})
            return self.service.save_contact_page(
                principal=principal, agent_id=p["agent_id"], expected_revision=p["expected_revision"],
                contact=p["contact"],
            )
        if action == "contact.open":
            _keys(p, {"agent_id", "entry_id", "version_id"}, {'visitor_fields'})
            return self.service.open_contact_page(
                principal=principal, agent_id=p["agent_id"], entry_id=p["entry_id"], version_id=p["version_id"],
                visitor_fields=p.get('visitor_fields'),
            )
        if action == "widget.send":
            _keys(p, {"conversation_id", "visitor_token", "text"}, {"request_human"})
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
            _keys(p, {"conversation_id", "visitor_token", "asset_id", "version_id"}, {'derivative_id'})
            return self.service.visitor_download_material(
                conversation_id=p["conversation_id"], visitor_token=p["visitor_token"],
                asset_id=p["asset_id"], version_id=p["version_id"], derivative_id=p.get('derivative_id'),
            )
        if action == "inbox.list":
            _keys(p, {"agent_id"})
            items = self.service.inbox_list(principal=principal, agent_id=p['agent_id'])
            scope = hashlib.sha256(repr((principal.tenant_id, p['agent_id'], principal.actor_id)).encode()).hexdigest()
            return {'items': items, 'can_mark_read': principal.role in {'owner', 'editor'}, 'notification_scope': scope}
        if action == 'inbox.events':
            _keys(p, {'agent_id', 'after_sequence'}, {'limit'})
            return self.service.inbox_events(principal=principal, agent_id=p['agent_id'],
                after_sequence=p['after_sequence'], limit=p.get('limit', 50))
        if action == 'inbox.consumer.cursor':
            _keys(p, {'agent_id', 'consumer_id'})
            return self.service.inbox_consumer_cursor(principal=principal, agent_id=p['agent_id'],
                consumer_id=p['consumer_id'])
        if action == 'inbox.consumer.ack':
            _keys(p, {'agent_id', 'consumer_id', 'through_sequence'})
            return self.service.ack_inbox_consumer(principal=principal, agent_id=p['agent_id'],
                consumer_id=p['consumer_id'], through_sequence=p['through_sequence'])
        if action == 'inbox.read':
            _keys(p, {'agent_id', 'conversation_id', 'through_sequence'})
            return self.service.mark_inbox_read(principal=principal, **p)
        if action == 'inbox.preferences':
            _keys(p, {'agent_id'})
            return self.service.inbox_preferences(principal=principal, **p)
        if action == 'inbox.preferences.save':
            _keys(p, {'agent_id', 'new_messages', 'handoff'})
            return self.service.save_inbox_preferences(principal=principal, **p)
        if action == "inbox.messages":
            _keys(p, {"agent_id", "conversation_id"})
            return {"items": self.service.inbox_messages(
                principal=principal, agent_id=p["agent_id"], conversation_id=p["conversation_id"],
            )}
        if action == 'inbox.assistance.check':
            _keys(p, {'agent_id', 'conversation_id', 'generation', 'through_sequence', 'snapshot_hash'})
            return self.service.check_inbox_assistance(principal=principal, **p)
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
        if action == 'inbox.release':
            _keys(p, {'agent_id', 'conversation_id', 'generation'})
            return self.service.release(principal=principal, agent_id=p['agent_id'],
                conversation_id=p['conversation_id'], generation=p['generation'])
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
        if action == 'material.search':
            _keys(p, {'agent_id', 'query'}, {'limit'})
            return {'items': self.service.search_material_summaries(principal=principal,
                agent_id=p['agent_id'], query=p['query'], limit=p.get('limit', 10))}
        if action == 'material.process':
            _keys(p, {'agent_id', 'asset_id'}, {'version_id'})
            return self.service.processing_candidate(principal=principal, agent_id=p['agent_id'],
                asset_id=p['asset_id'], version_id=p.get('version_id'))
        if action == 'material.derivatives':
            _keys(p, {'agent_id', 'asset_id'})
            return self.service.list_material_derivatives(principal=principal, agent_id=p['agent_id'], asset_id=p['asset_id'])
        if action == 'material.derivative.download':
            _keys(p, {'agent_id', 'asset_id', 'derivative_id'})
            return self.service.download_material_derivative(principal=principal, agent_id=p['agent_id'],
                asset_id=p['asset_id'], derivative_id=p['derivative_id'])
        if action == 'material.review_candidate':
            _keys(p, {'agent_id', 'candidate_id', 'review_state'})
            return self.service.review_processing_candidate(principal=principal, agent_id=p['agent_id'],
                candidate_id=p['candidate_id'], review_state=p['review_state'])
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
            _keys(p, {"agent_id", "conversation_id", "generation", "asset_id", "version_id"}, {"text", 'derivative_id'})
            return self.service.send_material(
                principal=principal, agent_id=p["agent_id"],
                conversation_id=p["conversation_id"], generation=p["generation"],
                asset_id=p["asset_id"], version_id=p["version_id"], text=p.get("text", ""), derivative_id=p.get('derivative_id'),
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
