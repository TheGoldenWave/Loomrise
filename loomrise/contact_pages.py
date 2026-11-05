"""Constrained Contact Page content shared by draft previews and released pages."""

from __future__ import annotations

from copy import deepcopy
import html
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, urlsplit

SCHEMA_VERSION = "contact-page-v1"
BLOCK_LABELS = {
    "text": "服务介绍", "chat": "客服入口", "social": "社交联系", "link": "联系外链",
    "portfolio": "作品", "media": "媒体", "services": "服务", "testimonials": "评价",
    "booking": "预约", "faq": "常见问题", "metrics": "指标", "menu": "菜单与商品",
    "hours": "营业时间", "location": "地点", "skills": "技能", "experience": "经历",
    "schedule": "日程", "jobs": "岗位", "community": "开发者与社区", "qr": "二维码",
    "contact": "联系信息",
}
_ITEM_FIELDS = {
    "social": {"label", "href"}, "link": {"label", "href", "description"},
    "portfolio": {"title", "description", "href", "src", "alt"},
    "media": {"title", "description", "src", "alt", "media_type"},
    "services": {"title", "description", "href"},
    "testimonials": {"quote", "author"}, "booking": {"label", "href", "description"},
    "faq": {"question", "answer"}, "metrics": {"label", "value"},
    "menu": {"title", "description", "price", "href", "src", "alt"},
    "hours": {"day", "hours"}, "location": {"label", "address", "href"},
    "skills": {"label", "description"}, "experience": {"title", "period", "description"},
    "schedule": {"title", "time", "description", "href"},
    "jobs": {"title", "location", "description", "href"},
    "community": {"label", "description", "href"}, "qr": {"label", "src", "alt", "href"},
    "contact": {"label", "value", "href"},
}
_REQUIRED_ITEM_FIELDS = {
    "social": {"label", "href"}, "link": {"label", "href"}, "portfolio": {"title"},
    "media": {"src", "alt", "media_type"}, "services": {"title"},
    "testimonials": {"quote", "author"}, "booking": {"label", "href"},
    "faq": {"question", "answer"}, "metrics": {"label", "value"}, "menu": {"title"},
    "hours": {"day", "hours"}, "location": {"label", "address"}, "skills": {"label"},
    "experience": {"title", "period"}, "schedule": {"title", "time"}, "jobs": {"title"},
    "community": {"label", "href"}, "qr": {"label", "src", "alt"},
    "contact": {"label", "value"},
}


def _text(value: Any, path: str, *, limit: int = 4000, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(f"联系页 {path} 必须是至多 {limit} 字符的文本")
    if required and not value.strip():
        raise ValueError(f"联系页 {path} 不能为空")
    return value


def _url(value: str, path: str, *, contact: bool = False) -> str:
    if len(value) > 2048 or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError(f"联系页 {path} 不是安全链接")
    parsed = urlsplit(value)
    if contact and parsed.scheme == "mailto" and re.fullmatch(r"[^@?&#/]+@[^@?&#/]+\.[^@?&#/]+", parsed.path):
        return value
    if contact and parsed.scheme == "tel" and re.fullmatch(r"\+?[0-9().-]{3,30}", parsed.path):
        return value
    try:
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None)
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"联系页 {path} 仅允许 HTTPS 链接" + ("、mailto 或 tel" if contact else ""))
    return value


def validate_contact(value: Any) -> dict[str, Any]:
    """Validate model/manual content; unknown fields and executable markup are never interpreted."""
    allowed = {"schema_version", "template_id", "title", "description", "blocks"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("联系页必须是受约束的页面对象，不能包含未知字段")
    if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError("联系页 Schema 版本不受支持")
    contact = {
        "schema_version": SCHEMA_VERSION,
        "title": _text(value.get("title", "联系页"), "title", limit=200, required=True),
        "description": _text(value.get("description", ""), "description"),
        "blocks": [],
    }
    if "template_id" in value:
        contact["template_id"] = _text(value["template_id"], "template_id", limit=80)
    blocks = value.get("blocks", [])
    if not isinstance(blocks, list) or len(blocks) > 64:
        raise ValueError("联系页 blocks 必须是最多 64 个内容块的数组")
    seen = set()
    for i, block in enumerate(blocks):
        path = f"blocks[{i}]"
        if not isinstance(block, dict) or set(block) - {"id", "type", "title", "body", "items"}:
            raise ValueError(f"联系页 {path} 必须是受约束的内容块")
        kind = block.get("type")
        if not isinstance(kind, str) or kind not in BLOCK_LABELS:
            raise ValueError(f"联系页 {path}.type 不受支持")
        identifier = _text(block.get("id"), f"{path}.id", limit=80, required=True)
        if identifier in seen:
            raise ValueError(f"联系页 {path}.id 重复")
        seen.add(identifier)
        normalized = {"id": identifier, "type": kind,
                      "title": _text(block.get("title", BLOCK_LABELS[kind]), f"{path}.title", limit=200),
                      "body": _text(block.get("body", ""), f"{path}.body")}
        items = block.get("items", [])
        if not isinstance(items, list) or len(items) > 50:
            raise ValueError(f"联系页 {path}.items 必须是最多 50 项的数组")
        if items and kind not in _ITEM_FIELDS:
            raise ValueError(f"联系页 {path} 不支持列表内容")
        normalized["items"] = []
        for j, item in enumerate(items):
            item_path = f"{path}.items[{j}]"
            if not isinstance(item, dict) or set(item) - _ITEM_FIELDS[kind]:
                raise ValueError(f"联系页 {item_path} 包含不支持的字段")
            for key in _REQUIRED_ITEM_FIELDS[kind]:
                _text(item.get(key), f"{item_path}.{key}", required=True)
            for key, text in item.items():
                _text(text, f"{item_path}.{key}")
                if key in {"href", "src"}:
                    _url(text, f"{item_path}.{key}", contact=key == "href" and kind == "contact")
            if "src" in item and not item.get("alt", "").strip():
                raise ValueError(f"联系页 {item_path}.alt 不能为空")
            if kind == "media" and item["media_type"] not in {"image", "video", "audio"}:
                raise ValueError(f"联系页 {item_path}.media_type 不受支持")
            normalized["items"].append(deepcopy(item))
        contact["blocks"].append(normalized)
    return contact


def contact_schema() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "max_blocks": 64, "max_items": 50,
            "block_types": [{"type": kind, "label": label,
                             "item_fields": sorted(_ITEM_FIELDS.get(kind, set())),
                             "required_item_fields": sorted(_REQUIRED_ITEM_FIELDS.get(kind, set()))}
                            for kind, label in BLOCK_LABELS.items()]}


def contact_generation_schema(template_id: str | None = None) -> dict[str, Any]:
    """Strict generation opens required item fields; manual editing keeps optional fields."""
    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}

    text = {'type': 'string', 'maxLength': 4000}
    variants = []
    for kind in BLOCK_LABELS:
        fields = {key: {**text, 'minLength': 1} for key in sorted(_REQUIRED_ITEM_FIELDS.get(kind, set()))}
        for key in {'href', 'src'} & fields.keys():
            fields[key]['maxLength'] = 2048
        if kind == 'media':
            fields['media_type'] = {'type': 'string', 'enum': ['image', 'video', 'audio']}
        variants.append(obj({
            'id': {'type': 'string', 'minLength': 1, 'maxLength': 80},
            'type': {'type': 'string', 'enum': [kind]},
            'title': {'type': 'string', 'maxLength': 200}, 'body': text,
            'items': {'type': 'array', 'items': obj(fields) if fields else {'type': 'string'},
                      'maxItems': 50 if fields else 0},
        }))
    return obj({
        'schema_version': {'type': 'string', 'enum': [SCHEMA_VERSION]},
        'template_id': {'type': 'string', 'enum': [template_id] if template_id is not None
                        else [item['id'] for item in contact_templates()]},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 200}, 'description': text,
        'blocks': {'type': 'array', 'items': {'anyOf': variants}, 'maxItems': 64},
    })


def validate_generated_contact(value: Any, *, template_id: str | None = None) -> dict[str, Any]:
    contact = validate_contact(value)
    templates = {item['id'] for item in contact_templates()}
    if (set(value) != {'schema_version', 'template_id', 'title', 'description', 'blocks'}
            or contact != value or contact['template_id'] not in templates
            or (template_id is not None and contact['template_id'] != template_id)
            or any(set(item) != _REQUIRED_ITEM_FIELDS[block['type']]
                   for block in contact['blocks'] for item in block['items'])):
        raise ValueError('联系页生成内容不符合受约束格式')
    return contact


def contact_templates() -> list[dict[str, Any]]:
    templates = (("support", "客服联系", ("text", "chat", "faq", "hours", "contact")),
                 ("services", "服务展示", ("services", "portfolio", "testimonials", "booking", "location")),
                 ("profile", "个人与社区", ("skills", "experience", "social", "community", "qr")))
    return [{"id": template_id, "name": name,
             "contact": validate_contact({"template_id": template_id, "title": name,
                                          "blocks": [{"id": f"{kind}-{i}", "type": kind}
                                                     for i, kind in enumerate(kinds)]})}
            for template_id, name, kinds in templates]


def contact_paths(agent_id: str, entry_id: str, version_id: str) -> dict[str, str]:
    for value in (agent_id, entry_id, version_id):
        if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("联系页路径标识不能为空、点路径或包含控制字符")
    path = f"/contact/{quote(agent_id, safe='')}/{quote(entry_id, safe='')}"
    return {"share_path": path, "chat_path": f"{path}/chat/{quote(version_id, safe='')}"}


def _item_html(kind: str, item: dict[str, str]) -> str:
    esc = html.escape
    if kind == "faq":
        return f'<details><summary>{esc(item["question"])}</summary><p>{esc(item["answer"])}</p></details>'
    if kind == "testimonials":
        return f'<blockquote><p>{esc(item["quote"])}</p><cite>{esc(item["author"])}</cite></blockquote>'
    title = item.get("title", item.get("label", item.get("day", "")))
    result = f'<h3>{esc(title)}</h3>' if title else ""
    for key in ("value", "price", "period", "time", "hours", "address", "location", "description"):
        if item.get(key):
            result += f'<p>{esc(item[key])}</p>'
    if item.get("src"):
        source, alt = esc(item["src"], quote=True), esc(item["alt"], quote=True)
        media_type = item.get("media_type", "image")
        if media_type == "image":
            result += f'<img src="{source}" alt="{alt}" loading="lazy" referrerpolicy="no-referrer">'
        else:
            result += f'<{media_type} controls preload="none" src="{source}" aria-label="{alt}"></{media_type}>'
    if item.get("href"):
        result += f'<a href="{esc(item["href"], quote=True)}" target="_blank" rel="noopener noreferrer">{esc(title or "查看详情")}</a>'
    if kind == "booking":
        result += '<p class="hint">前往外部预约页面；打开链接不代表预约成功。</p>'
    return f'<div class="item">{result}</div>'


def render_contact_page(page: dict[str, Any], *, preview: bool = False) -> str:
    contact = validate_contact(page["contact"])
    blocks = []
    for block in contact["blocks"]:
        kind = block["type"]
        body = f'<h2>{html.escape(block["title"])}</h2>'
        if block["body"]:
            body += f'<p>{html.escape(block["body"])}</p>'
        if kind == "chat":
            if preview:
                body += '<p class="hint">预览中不会创建访客会话；批准并启用后可咨询。</p>'
            else:
                body += f'<a class="chat" href="{html.escape(page["chat_path"], quote=True)}">开始咨询</a>'
        body += "".join(_item_html(kind, item) for item in block["items"])
        if kind != "chat" and not block["items"] and not block["body"]:
            body += '<p class="hint">暂无内容</p>'
        blocks.append(f'<section class="block" data-block-type="{kind}">{body}</section>')
    values = {
        "TITLE": html.escape(contact["title"]),
        "DESCRIPTION": html.escape(contact["description"]),
        "BLOCKS": "".join(blocks),
        "META": "草稿预览 · 尚未公开" if preview else f'已批准沙盒版本 · {html.escape(page["version_id"])}',
    }
    template = Path(__file__).with_name("customer_contact.html").read_text(encoding="utf-8")
    return re.sub(r"__(TITLE|DESCRIPTION|BLOCKS|META)__", lambda match: values[match[1]], template)
