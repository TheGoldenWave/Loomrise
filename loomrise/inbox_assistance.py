"""Validation for bounded, read-only Inbox assistance proposals."""

from __future__ import annotations

from typing import Any

from .customer_reception import _validated_answer


ASSISTANCE_MESSAGES = {
    'assistance_unavailable': '未配置可用的辅助模型，请继续人工回复。',
    'assistance_failed': '辅助生成失败，请稍后重试或继续人工回复。',
    'assistance_timeout': '辅助生成超时，请重试或继续人工回复。',
    'assistance_invalid_response': '本次辅助内容无法核验，请重试或继续人工回复。',
}


class InboxAssistanceError(RuntimeError):
    """Only fixed public codes cross the provider boundary."""


def assistance_schema() -> dict[str, Any]:
    citation = {'type': 'object', 'properties': {
        'source_id': {'type': 'string', 'maxLength': 128},
        'content_hash': {'type': 'string', 'maxLength': 64},
        'quote': {'type': 'string', 'maxLength': 4000}},
        'required': ['source_id', 'content_hash', 'quote'], 'additionalProperties': False}
    return {'type': 'object', 'properties': {
        'summary': {'type': 'string', 'maxLength': 2000},
        'reply': {'type': 'string', 'maxLength': 5000},
        'citations': {'type': 'array', 'items': citation, 'minItems': 1, 'maxItems': 16}},
        'required': ['summary', 'reply', 'citations'], 'additionalProperties': False}


def validate_assistance(value: Any, sources: list[dict[str, Any]], *, model_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {'summary', 'reply', 'citations', 'model_evidence'}:
        raise ValueError('invalid assistance shape')
    summary = value['summary']
    if (not isinstance(summary, str) or not summary.strip() or len(summary) > 2000 or len(summary.encode()) > 6000
            or '\x00' in summary):
        raise ValueError('invalid assistance summary')
    if not isinstance(value['reply'], str) or len(value['reply']) > 5000:
        raise ValueError('invalid assistance reply')
    answer = _validated_answer({'text': value['reply'], 'citations': value['citations'], 'handoff': False}, sources)
    evidence = value['model_evidence']
    if (not isinstance(evidence, dict) or set(evidence) != {
            'model', 'response_id', 'provider', 'usage', 'duration_ms'}
            or any(not isinstance(evidence[key], str) or not evidence[key].strip()
                   or len(evidence[key]) > 200 or '\x00' in evidence[key]
                   for key in ('model', 'response_id', 'provider'))
            or evidence['model'] != model_id
            or type(evidence['duration_ms']) is not int or not 0 <= evidence['duration_ms'] <= 120_000
            or not isinstance(evidence['usage'], dict)
            or set(evidence['usage']) - {'input_tokens', 'output_tokens', 'total_tokens'}
            or any(type(count) is not int or not 0 <= count <= 10_000_000
                   for count in evidence['usage'].values())):
        raise ValueError('invalid assistance evidence')
    return {'summary': summary, 'reply': answer['text'],
            'citations': [{key: item[key] for key in ('source_id', 'content_hash', 'quote')}
                          for item in answer['citations']], 'model_evidence': evidence}
