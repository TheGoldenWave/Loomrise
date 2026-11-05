"""Signed sandbox callback boundary; this does not verify a real provider protocol."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable


class ChannelWebhookAdapter:
    def __init__(self, *, channel: str, secret: str, deliver: Callable[[dict[str, Any]], Any] | None = None):
        if channel not in {'telegram', 'email'} or not isinstance(secret, str) or not secret:
            raise ValueError('channel 与 webhook secret 无效')
        self.channel = channel
        self.secret = secret.encode()
        self.deliver = deliver

    def verify(self, body: bytes, signature: str) -> bool:
        if not isinstance(body, bytes) or not isinstance(signature, str) or not signature.isascii():
            return False
        expected = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse(self, body: bytes, signature: str) -> dict[str, Any]:
        if not self.verify(body, signature):
            raise PermissionError('Webhook 签名无效')
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('Webhook body 不是有效 JSON') from exc
        if not isinstance(payload, dict):
            raise ValueError('Webhook payload 必须是对象')
        required = {'message_id', 'thread_id', 'text', 'external_account'}
        if set(payload) != required or any(not isinstance(payload[key], str) or not payload[key].strip() for key in required):
            raise ValueError('Webhook payload 字段不完整')
        if len(payload['text']) > 20000:
            raise ValueError('消息必须是 1 至 20000 字符')
        return {'environment': 'sandbox', 'channel': self.channel, 'direction': 'inbound', **payload}

    def receive(self, body: bytes, signature: str) -> dict[str, Any]:
        event = self.parse(body, signature)
        if self.deliver is None:
            raise RuntimeError('渠道沙盒尚未配置 deliver adapter')
        result = self.deliver(event)
        return {'event': event, 'result': result, 'evidence': 'sandbox_callback_adapter'}
