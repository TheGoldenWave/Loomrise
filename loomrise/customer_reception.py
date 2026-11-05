"""Version-bound, read-only model reception backed by the shared request ledger."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from .contracts import new_id
from .durable_store import SqliteStore


RECEPTION_MESSAGES = {
    'answered': 'AI 答复已保存，可查看资料引用。',
    'handoff': '已转交人工客服。',
    'disabled': 'AI 接待未启用，消息已保留在客服收件箱。',
    'outside_schedule': '当前由人工接待，消息已保留在客服收件箱。',
    'human_requested': '已请求人工客服，自动接待已停止。',
    'not_configured': 'AI 模型尚未配置，消息已保留，请等待人工客服。',
    'model_changed': '模型连接与已批准版本不一致，消息已保留，请等待人工客服。',
    'knowledge_unavailable': '授权资料暂不可用，消息已保留，请等待人工客服。',
    'provider_error': 'AI 服务暂时不可用，消息已保留，请等待人工客服。',
    'invalid_response': '本次 AI 答复无法核验，消息已保留，请等待人工客服。',
    'interrupted': '本次自动接待已中断，消息已保留，请等待人工客服。',
}
_HANDOFF_STATUSES = {'not_configured', 'model_changed', 'knowledge_unavailable', 'provider_error', 'invalid_response', 'interrupted'}
_FALLBACK = '暂时无法依据授权资料回答，已转交人工客服。'


def validate_customer_input(text: Any, visitor_token: Any, request_human: Any, message_id: Any = None) -> str:
    if (not isinstance(text, str) or not text.strip() or len(text) > 20_000
            or len(json.dumps(text, ensure_ascii=False).encode('utf-8')) > 24_002 or '\x00' in text):
        raise ValueError('消息必须是非空文本，且不超过 20000 字符或 24000 字节')
    if not isinstance(visitor_token, str) or not 1 <= len(visitor_token) <= 256:
        raise ValueError('访客凭据无效')
    if type(request_human) is not bool:
        raise ValueError('request_human 必须是布尔值')
    if message_id is not None and (not isinstance(message_id, str) or not message_id.strip()
                                    or len(message_id) > 128 or '\x00' in message_id):
        raise ValueError('message_id 必须是最多 128 字符的非空消息标识')
    return message_id or new_id('input')


def _truncate(text: str, byte_limit: int) -> str:
    value = text.encode('utf-8')[:byte_limit].decode('utf-8', errors='ignore')
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(value[:middle], ensure_ascii=False).encode()) <= byte_limit:
            low = middle
        else:
            high = middle - 1
    return value[:low]


def _context(turn: dict[str, Any], question: str) -> dict[str, Any]:
    persona = {key: _truncate(value, 1000) for key, value in turn['config'].get('persona', {}).items()
               if key in {'name', 'goal', 'audience', 'scope', 'fallback'} and isinstance(value, str)}
    sources, remaining = [], 24_000
    for source in turn['sources']:
        excerpt = _truncate(source['text'], min(4096, remaining))
        if not excerpt:
            break
        sources.append({**source, 'title': _truncate(source['title'], 300), 'text': excerpt})
        remaining -= len(json.dumps(excerpt, ensure_ascii=False).encode())
    history, remaining = [], 8_000
    for item in reversed(turn['history']):
        text = _truncate(item['text'], min(2000, remaining))
        if not text:
            break
        history.append({'role': 'user' if item['sender'] == 'visitor' else 'assistant', 'text': text})
        remaining -= len(json.dumps(text, ensure_ascii=False).encode())
    payload = {'text': question, 'persona': persona, 'sources': sources, 'history': list(reversed(history))}
    while len(json.dumps(payload, ensure_ascii=False).encode()) > 60_000:
        if payload['history']:
            payload['history'].pop(0)
        else:
            payload['sources'].pop()
    return payload


def _validated_answer(value: Any, sources: list[dict[str, str]], *, language: str = 'zh-CN') -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get('handoff')) is not bool:
        raise ValueError('invalid answer')
    text, citations = value.get('text'), value.get('citations')
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > 16_000 or '\x00' in text:
        raise ValueError('invalid answer text')
    if not isinstance(citations, list) or len(citations) > 16:
        raise ValueError('invalid citations')
    approved = {source['source_id']: source for source in sources}
    verified = []
    for citation in citations:
        if not isinstance(citation, dict) or set(citation) != {'source_id', 'content_hash', 'quote'}:
            raise ValueError('invalid citation')
        source = approved.get(citation['source_id'])
        quote = citation['quote']
        if (source is None or source['content_hash'] != citation['content_hash'] or not isinstance(quote, str)
                or not quote.strip() or len(quote.encode()) > 4000 or quote not in source['text']):
            raise ValueError('citation does not match the approved source excerpt')
        verified.append({**citation, 'title': source['title']})
    if not verified and not value['handoff']:
        raise ValueError('ungrounded answer')
    provider = {}
    for key in ('model', 'provider_response_id'):
        identifier = value.get(key)
        if isinstance(identifier, str) and 0 < len(identifier) <= 200:
            provider[key] = identifier
    usage = value.get('usage', {})
    if isinstance(usage, dict):
        provider['usage'] = {key: usage[key] for key in ('input_tokens', 'output_tokens')
                             if type(usage.get(key)) is int and 0 <= usage[key] <= 10_000_000}
    fallback = 'I cannot answer from the approved information. I have requested a human agent.' if language == 'en' else _FALLBACK
    return {'text': text if verified else fallback, 'citations': verified,
            'handoff': value['handoff'], 'provider': provider}


class CustomerReception:
    def __init__(self, store: SqliteStore, provider: Any = None) -> None:
        self.store = store
        self.provider = provider

    async def receive(self, *, conversation_id: str, visitor_token: str, text: str,
                      request_human: bool = False, message_id: str | None = None) -> dict[str, Any]:
        if not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 128:
            raise ValueError('会话标识无效')
        message_id = validate_customer_input(text, visitor_token, request_human, message_id)
        turn = self.store.begin_customer_reception(conversation_id=conversation_id,
            visitor_token_hash=hashlib.sha256(visitor_token.encode()).hexdigest(),
            text=text, request_human=request_human, message_id=message_id)
        if not turn['created']:
            return turn['result']
        status = turn['initial_status']
        answer = None
        failure = {}
        if status == 'generating':
            if self.provider is None:
                status = 'not_configured'
            else:
                payload = _context(turn, text)
                try:
                    provider = self.provider.for_run() if callable(getattr(self.provider, 'for_run', None)) else self.provider
                    if getattr(provider, 'model', None) != turn['config']['ai_reception']['model_id']:
                        return self.store.finish_customer_reception(run_id=turn['run_id'], status='model_changed',
                            message=RECEPTION_MESSAGES['model_changed'], handoff=True)
                    async with asyncio.timeout(65):
                        generated = await provider.answer(**payload)
                except asyncio.CancelledError:
                    self.store.finish_customer_reception(run_id=turn['run_id'], status='interrupted',
                        message=RECEPTION_MESSAGES['interrupted'], handoff=True)
                    raise
                except Exception as exc:
                    # Provider exception strings may contain credentials or endpoints.
                    status = 'provider_error'
                    code = str(exc)
                    if type(exc).__name__ == 'ModelProviderError' and re.fullmatch(r'model_[a-z0-9_]{1,64}', code):
                        failure['failure_code'] = code
                    else:
                        failure['failure_code'] = 'provider_timeout' if isinstance(exc, TimeoutError) else 'provider_failed'
                else:
                    try:
                        answer = _validated_answer(generated, payload['sources'],
                            language=turn['config'].get('widget', {}).get('language', 'zh-CN'))
                    except (TypeError, ValueError, KeyError):
                        status = 'invalid_response'
                    else:
                        status = 'handoff' if answer['handoff'] else 'answered'
        return self.store.finish_customer_reception(run_id=turn['run_id'], status=status,
            message=RECEPTION_MESSAGES[status], text=answer['text'] if answer else None,
            citations=answer['citations'] if answer else [], provider=answer['provider'] if answer else failure,
            handoff=(answer['handoff'] if answer else status in _HANDOFF_STATUSES))
