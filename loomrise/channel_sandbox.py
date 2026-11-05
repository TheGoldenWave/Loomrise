"""Deterministic Telegram/Email channel sandbox adapter.

It records authorization, revocation, dedupe and delivery facts without opening
network sockets. Real provider credentials and webhook verification remain a
separate deployment/evidence boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import json
from threading import RLock
from typing import Any
from datetime import datetime, timezone


@dataclass
class ChannelSandbox:
    channels: dict[tuple[str, str, str, str], dict[str, Any]] = field(default_factory=dict)
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    store: Any = None
    _lock: Any = field(default_factory=RLock, init=False, repr=False)

    def _auth(self, key: tuple[str, str, str, str], *, tenant_id: str, agent_id: str, channel: str, external_account: str):
        if self.store is not None:
            return self.store.channel_connection(tenant_id=tenant_id, agent_id=agent_id, channel=channel, external_account=external_account)
        return self.channels.get(key)

    @staticmethod
    def _scope(tenant_id: str, agent_id: str, channel: str, external_account: str) -> tuple[str, str, str, str]:
        if channel not in {'telegram', 'email'}:
            raise ValueError('仅支持 telegram 或 email 沙盒')
        if any(not isinstance(value, str) or not value.strip() for value in (tenant_id, agent_id, external_account)):
            raise ValueError('租户、Agent 与外部账号标识必须是非空字符串')
        return tenant_id, agent_id, channel, external_account

    def authorize(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str, mode: str = 'full') -> dict[str, Any]:
        key = self._scope(tenant_id, agent_id, channel, external_account)
        if mode not in {'full', 'notify_only'}:
            raise ValueError('mode 必须为 full 或 notify_only')
        with self._lock:
            if self.store is not None:
                value = self.store.channel_authorize(tenant_id=tenant_id, agent_id=agent_id, channel=channel,
                                                     external_account=external_account, mode=mode)
            else:
                value = {'environment': 'sandbox', 'tenant_id': tenant_id, 'agent_id': agent_id,
                         'channel': channel, 'external_account': external_account, 'mode': mode,
                         'state': 'authorized', 'revision': self.channels.get(key, {}).get('revision', 0) + 1,
                         'updated_at': datetime.now(timezone.utc).isoformat()}
                self.channels[key] = value
            self.events.append({'type': 'channel.authorized', **value})
            return dict(value)

    def revoke(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str) -> dict[str, Any]:
        key = self._scope(tenant_id, agent_id, channel, external_account)
        with self._lock:
            if self.store is not None:
                current = self.store.channel_revoke(tenant_id=tenant_id, agent_id=agent_id, channel=channel,
                                                    external_account=external_account)
            else:
                current = self.channels.get(key)
                if current is None:
                    raise KeyError('未知渠道授权')
                current = {**current, 'state': 'revoked', 'revision': current['revision'] + 1,
                           'updated_at': datetime.now(timezone.utc).isoformat()}
                self.channels[key] = current
            self.events.append({'type': 'channel.revoked', **current})
            return dict(current)

    def send(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str, message_id: str,
             thread_id: str, text: str, attachment_ids: list[str] | None = None) -> dict[str, Any]:
        return self._message(tenant_id=tenant_id, agent_id=agent_id, channel=channel, external_account=external_account,
                             message_id=message_id, thread_id=thread_id, text=text,
                             attachment_ids=attachment_ids, direction='outbound')

    def receive(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str, message_id: str,
                thread_id: str, text: str) -> dict[str, Any]:
        return self._message(tenant_id=tenant_id, agent_id=agent_id, channel=channel, external_account=external_account,
                             message_id=message_id, thread_id=thread_id, text=text,
                             attachment_ids=None, direction='inbound')

    def _message(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str, message_id: str,
                 thread_id: str, text: str, attachment_ids: list[str] | None, direction: str) -> dict[str, Any]:
        key = self._scope(tenant_id, agent_id, channel, external_account)
        if not isinstance(message_id, str) or not message_id.strip() or not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError('message_id 与 thread_id 必须是非空字符串')
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise ValueError('消息必须是 1 至 20000 字符')
        if attachment_ids is not None and (not isinstance(attachment_ids, list) or any(
                not isinstance(value, str) or not value.strip() for value in attachment_ids)):
            raise ValueError('attachment_ids 必须是非空字符串 ID 的列表')
        with self._lock:
            auth = self._auth(key, tenant_id=tenant_id, agent_id=agent_id, channel=channel, external_account=external_account)
            if auth is None or auth['state'] != 'authorized':
                raise PermissionError('渠道未授权或已撤销')
            if direction == 'outbound' and auth['mode'] != 'full':
                raise PermissionError('仅通知模式不能发送会话内容或附件')
            identity = (*key, direction, thread_id, message_id, auth['revision'])
            dedupe = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            record = {'environment': 'sandbox', 'tenant_id': tenant_id, 'agent_id': agent_id, 'direction': direction,
                      'channel': channel, 'external_account': external_account, 'message_id': message_id,
                      'thread_id': thread_id, 'text': text, 'attachment_ids': list(attachment_ids or []),
                      'delivery': 'simulated', 'duplicate': False}
            if self.store is not None:
                record = self.store.channel_record_message(dedupe_key=dedupe, value=record,
                                                           expected_revision=auth['revision'])
            else:
                existing = self.messages.get(dedupe)
                if existing is not None:
                    if existing['text'] != text or existing['attachment_ids'] != record['attachment_ids']:
                        raise ValueError('同一消息 ID 的内容与已记录内容不一致')
                    return deepcopy({**existing, 'duplicate': True})
                self.messages[dedupe] = deepcopy(record)
            if not record['duplicate']:
                event_type = 'channel.message_sent' if direction == 'outbound' else 'channel.message_received'
                self.events.append({'type': event_type, **deepcopy(record)})
            return deepcopy(record)
