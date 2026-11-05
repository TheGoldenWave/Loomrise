"""Public, version-bound Widget presentation and visitor-form rules."""
from datetime import datetime, timezone
import re
from typing import Any, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_ai_reception_configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {'enabled', 'mode', 'model_id', 'sources', 'faq_suggestions', 'handoff_phrases'}:
        raise ValueError('AI 接待仅支持 enabled/mode/model_id/sources/faq_suggestions/handoff_phrases 配置；模型凭据只由服务端读取')
    enabled, mode, sources = value.get('enabled', False), value.get('mode', 'always'), value.get('sources', [])
    if type(enabled) is not bool or mode not in ('always', 'offline'):
        raise ValueError('AI 接待开关必须是布尔值，模式须为 always 或 offline')
    model_id = value.get('model_id', '')
    if (not isinstance(model_id, str) or len(model_id) > 128 or any(char.isspace() for char in model_id)
            or (enabled and not model_id)):
        raise ValueError('启用 AI 接待必须固定有效的模型 ID')
    if not isinstance(sources, list) or len(sources) > 16:
        raise ValueError('AI 接待最多使用 16 个已授权的固定知识来源')
    seen = set()
    approved_sources = set()
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != {'source_id', 'content_hash'}:
            raise ValueError('接待来源必须固定 source_id 与 content_hash')
        identifier = source['source_id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier) or identifier in seen:
            raise ValueError('接待来源标识无效或重复')
        if not isinstance(source['content_hash'], str) or not re.fullmatch(r'[a-f0-9]{64}', source['content_hash']):
            raise ValueError('接待来源必须绑定有效 SHA-256 内容哈希')
        seen.add(identifier)
        approved_sources.add((identifier, source['content_hash']))
    faq_suggestions = value.get('faq_suggestions', [])
    if not isinstance(faq_suggestions, list) or len(faq_suggestions) > 8:
        raise ValueError('FAQ 问题建议最多 8 项')
    validated_suggestions = []
    seen_questions = set()
    for suggestion in faq_suggestions:
        if not isinstance(suggestion, Mapping) or set(suggestion) != {'question', 'source_id', 'content_hash'}:
            raise ValueError('FAQ 问题建议需要 question/source_id/content_hash')
        question = suggestion['question']
        if not isinstance(question, str) or len(question) > 160 or '\x00' in question or not question.strip():
            raise ValueError('FAQ 问题必须为非空且不超过 160 字符文本')
        question = question.strip()
        if (not isinstance(suggestion['source_id'], str)
                or not isinstance(suggestion['content_hash'], str)
                or (suggestion['source_id'], suggestion['content_hash']) not in approved_sources):
            raise ValueError('FAQ 建议必须引用本版本 ai_reception 的精确来源版本')
        question_key = question.casefold()
        if question_key in seen_questions:
            raise ValueError('FAQ 问题不能重复')
        seen_questions.add(question_key)
        validated_suggestions.append({
            'question': question,
            'source_id': suggestion['source_id'],
            'content_hash': suggestion['content_hash'],
        })
    phrases = value.get('handoff_phrases', [])
    if not isinstance(phrases, list) or len(phrases) > 20:
        raise ValueError('转人工短语必须是最多 20 项的数组')
    normalized_phrases, seen_phrases = [], set()
    for phrase in phrases:
        if not isinstance(phrase, str) or '\x00' in phrase or not 1 <= len(phrase.strip()) <= 100:
            raise ValueError('转人工短语必须为非空且不超过 100 字符的文本')
        phrase = phrase.strip()
        key = phrase.casefold()
        if key in seen_phrases:
            raise ValueError('转人工短语不能重复')
        seen_phrases.add(key)
        normalized_phrases.append(phrase)
    return {'enabled': enabled, 'mode': mode, 'model_id': model_id,
            'sources': [dict(source) for source in sources], 'faq_suggestions': validated_suggestions,
            'handoff_phrases': normalized_phrases}


def _text(value: Any, label: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError(f'{label} 必须是至多 {limit} 字符的文本')
    return value


def validate_widget_configuration(value: Any) -> dict[str, Any]:
    allowed = {'schema_version', 'title', 'greeting', 'color', 'language', 'timezone',
               'hours', 'offline_message', 'enabled', 'fields', 'logo_url', 'booking_url'}
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ValueError('Widget 必须是受支持的配置对象')
    if value.get('schema_version', 'widget-v1') != 'widget-v1':
        raise ValueError('Widget Schema 不受支持')
    result = {'schema_version': 'widget-v1',
              'title': _text(value.get('title', '在线咨询'), '标题', 100),
              'greeting': _text(value.get('greeting', ''), '欢迎语'),
              'offline_message': _text(value.get('offline_message', '当前不在接待时段，您可以留言。'), '离线文案'),
              'color': value.get('color', '#176b55'), 'language': value.get('language', 'zh-CN'),
              'timezone': value.get('timezone', 'UTC'), 'enabled': value.get('enabled', True), 'fields': []}
    if not isinstance(result['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', result['color']):
        raise ValueError('主题色必须是六位十六进制颜色')
    if result['language'] not in ('zh-CN', 'en') or type(result['enabled']) is not bool:
        raise ValueError('Widget 语言或启用开关无效')
    try:
        ZoneInfo(result['timezone'])
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError('请选择有效的 IANA 时区') from exc
    for key in ('logo_url', 'booking_url'):
        url = value.get(key, '')
        _text(url, key, 2048)
        if url:
            try:
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url):
                    raise ValueError()
                parsed.port
            except ValueError as exc:
                raise ValueError(f'{key} 仅接受有效 HTTPS 地址') from exc
        result[key] = url
    hours = value.get('hours')
    if hours is not None:
        if not isinstance(hours, list) or len(hours) > 28:
            raise ValueError('接待时段必须是最多 28 条的数组，或 null（全天）')
        for slot in hours:
            if not isinstance(slot, Mapping) or set(slot) != {'days', 'start', 'end'}:
                raise ValueError('时段需要 days/start/end')
            if (not isinstance(slot['days'], list) or not slot['days']
                    or any(type(day) is not int or day < 0 or day > 6 for day in slot['days'])
                    or len(slot['days']) != len(set(slot['days']))):
                raise ValueError('days 使用不重复的 0–6，星期一为 0')
            for key in ('start', 'end'):
                if not isinstance(slot[key], str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', slot[key]):
                    raise ValueError('时段使用 HH:MM')
            if slot['start'] == slot['end']:
                raise ValueError('时段起止不能相同；全天请使用 null')
    result['hours'] = hours
    fields = value.get('fields', [])
    if not isinstance(fields, list) or len(fields) > 20:
        raise ValueError('访客字段最多 20 项')
    seen = set()
    for item in fields:
        if not isinstance(item, Mapping) or set(item) != {'id', 'label', 'type', 'required'}:
            raise ValueError('访客字段需要 id/label/type/required')
        identifier = item['id']
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', identifier) or identifier in seen:
            raise ValueError('访客字段标识无效或重复')
        if item['type'] not in ('text', 'email', 'tel') or type(item['required']) is not bool:
            raise ValueError('访客字段类型或必填开关无效')
        _text(item['label'], '字段名称', 100)
        if not item['label'].strip():
            raise ValueError('字段名称不能为空')
        seen.add(identifier)
        result['fields'].append(dict(item))
    return result


def public_widget_configuration(config: Mapping[str, Any], *, at: datetime | None = None) -> dict[str, Any]:
    widget = validate_widget_configuration(config['widget'] if 'widget' in config else {})
    moment = at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError('时段判断需要带时区的时间')
    local = moment.astimezone(ZoneInfo(widget['timezone']))
    minute = local.hour * 60 + local.minute
    weekday = local.weekday()
    opened = widget['hours'] is None
    for slot in widget['hours'] or []:
        start, end = (int(slot[key][:2]) * 60 + int(slot[key][3:]) for key in ('start', 'end'))
        opened |= (weekday in slot['days'] and start <= minute < end) if start < end else (
            weekday in slot['days'] and minute >= start or (weekday - 1) % 7 in slot['days'] and minute < end)
    widget['availability'] = 'open' if opened and widget['enabled'] else 'closed'
    return widget


def public_faq_suggestions(config: Mapping[str, Any]) -> list[str]:
    if not isinstance(config, Mapping):
        raise ValueError('客服版本必须是配置对象')
    policy = validate_ai_reception_configuration(config.get('ai_reception', {}))
    if not policy['enabled']:
        return []
    return [item['question'] for item in policy['faq_suggestions']]


def validate_visitor_fields(widget: Mapping[str, Any], values: Any) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise ValueError('访客信息必须是对象')
    fields = {item['id']: item for item in widget['fields']}
    if set(values) - set(fields):
        raise ValueError('访客信息包含未声明字段')
    result = {}
    for identifier, field in fields.items():
        value = _text(values.get(identifier, ''), field['label'], 500).strip()
        if field['required'] and not value:
            raise ValueError(f'请填写{field["label"]}')
        if value and field['type'] == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError(f'{field["label"]}格式不正确')
        if value:
            result[identifier] = value
    return result
