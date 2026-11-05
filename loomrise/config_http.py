"""Loopback HTTP adapter for the shared R1 configuration application."""

from __future__ import annotations

import json
import asyncio
import html
import os
import time
from pathlib import Path
import re
from urllib.parse import urlsplit
from typing import Any, Iterable

from aiohttp import web

from .config_auth import DEFAULT_DATABASE_FILE, DEFAULT_PRINCIPAL_FILE, load_configuration_principal
from .configuration import (
    CONFIG_SCHEMA_VERSION, ConfigurationApplication, ConfigurationPrincipal,
    ConfigurationService,
)
from .customer_service import CustomerService, CustomerServiceApplication
from .contact_pages import render_contact_page
from .durable_store import SqliteStore
from .contracts import new_id

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_ALLOWED_ORIGINS = frozenset({
    "http://127.0.0.1:8765", "http://localhost:8765",
})
_SSE_KEEPALIVE_SECONDS = 15
_SSE_POLL_SECONDS = 0.5
_PUBLIC_INSTANCE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
STORE_KEY = web.AppKey("configuration_store", SqliteStore)
APPLICATION_KEY = web.AppKey("configuration_application", ConfigurationApplication)
PRINCIPAL_KEY = web.AppKey("configuration_principal", ConfigurationPrincipal)
CUSTOMER_APPLICATION_KEY = web.AppKey("customer_service_application", CustomerServiceApplication)
_LOCAL_RECEPTION_PROVIDER = object()
_LOCAL_CONTACT_GENERATION_PROVIDER = object()


def _normalize_local_origin(origin: str) -> str | None:
    try:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in _LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port
        default_port = 80 if parsed.scheme == "http" else 443
        host = parsed.hostname.lower()
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != default_port:
            authority = f"{authority}:{port}"
        return f"{parsed.scheme.lower()}://{authority}"
    except ValueError:
        return None


def _allowed_origins(origins: Iterable[str] | None) -> frozenset[str]:
    if origins is None:
        configured = os.environ.get("LOOMRISE_CONFIG_ALLOWED_ORIGINS")
        values = (
            [item.strip() for item in configured.split(",") if item.strip()]
            if configured is not None else list(_DEFAULT_ALLOWED_ORIGINS)
        )
    else:
        values = list(origins)
    normalized = [_normalize_local_origin(origin) for origin in values]
    if any(origin is None for origin in normalized):
        raise ValueError("allowed origins must be exact loopback origins without a path")
    return frozenset(origin for origin in normalized if origin is not None)


def _http_status(response: dict[str, Any]) -> int:
    if response.get("ok"):
        return 200
    code = response.get("error", {}).get("code")
    return {
        "invalid_request": 400,
        "forbidden": 403,
        "not_found": 404,
        "revision_conflict": 409,
        "validation_failed": 422,
        "state_conflict": 409,
        "release_blocked": 409,
    }.get(code, 500)


def create_configuration_http_app(
    *, principal_path=DEFAULT_PRINCIPAL_FILE, database_path=DEFAULT_DATABASE_FILE,
    allowed_origins: Iterable[str] | None = None,
    reception_provider: Any = _LOCAL_RECEPTION_PROVIDER,
    contact_generation_provider: Any = _LOCAL_CONTACT_GENERATION_PROVIDER,
) -> web.Application:
    """Build an HTTP adapter bound to one trusted local principal.

    No user, tenant, or role can be supplied by a browser request. The same
    application contract is used by the CLI and stdio MCP adapters.
    """
    principal = load_configuration_principal(principal_path)
    origin_allowlist = _allowed_origins(allowed_origins)
    store = SqliteStore(str(database_path), owner_id=new_id('config_http'))
    store.recover_customer_receptions()
    configuration = ConfigurationService(store)
    application = ConfigurationApplication(configuration)
    if reception_provider is _LOCAL_RECEPTION_PROVIDER:
        from .model_provider import LocalModelProvider
        try:
            reception_provider = LocalModelProvider.from_local_config()
        except (OSError, ValueError, RuntimeError, KeyError):
            reception_provider = None
    if contact_generation_provider is _LOCAL_CONTACT_GENERATION_PROVIDER:
        contact_generation_provider = reception_provider
    customer_application = CustomerServiceApplication(CustomerService(
        store, configuration, reception_provider=reception_provider,
        contact_generation_provider=contact_generation_provider))
    app = web.Application(client_max_size=14 * 1024 * 1024,
                          handler_args={'handler_cancellation': True})
    app[STORE_KEY] = store
    app[APPLICATION_KEY] = application
    app[PRINCIPAL_KEY] = principal
    app[CUSTOMER_APPLICATION_KEY] = customer_application

    async def local_only(request: web.Request, handler):
        host = request.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        if host not in _LOOPBACK_HOSTS:
            raise web.HTTPForbidden(text="configuration service is loopback-only")
        origin = request.headers.get("Origin")
        normalized_origin = _normalize_local_origin(origin) if origin else None
        same_origin = _normalize_local_origin(f"{request.scheme}://{request.host}")
        if origin and normalized_origin != same_origin and normalized_origin not in origin_allowlist:
            raise web.HTTPForbidden(text="cross-origin access is limited to configured workbench origins")
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            if request.method == "POST" and request.content_type != "application/json":
                raise web.HTTPUnsupportedMediaType()
            response = await handler(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = normalized_origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Last-Event-ID"
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.middlewares.append(web.middleware(local_only))

    async def execute(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, web.HTTPBadRequest):
            body = None
        if not isinstance(body, dict) or set(body) != {"action", "payload"}:
            result = {
                "schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                "error": {"code": "invalid_request", "message": "请求必须包含 action 与 payload"},
            }
            return web.json_response(result, status=400)
        action, payload = body["action"], body["payload"]
        if not isinstance(action, str) or not isinstance(payload, dict):
            result = {
                "schema_version": CONFIG_SCHEMA_VERSION, "ok": False,
                "error": {"code": "invalid_request", "message": "action 必须是字符串，payload 必须是对象"},
            }
            return web.json_response(result, status=400)
        result = request.app[APPLICATION_KEY].execute(
            principal=request.app[PRINCIPAL_KEY],
            action=action,
            payload=payload,
        )
        result = {
            "schema_version": result.get("schema_version", CONFIG_SCHEMA_VERSION),
            "ok": result.get("ok", False),
            "result": result.get("result"),
            "error": result.get("error"),
        }
        return web.json_response(result, status=_http_status(result))

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True, "schema_version": CONFIG_SCHEMA_VERSION})

    async def widget_page(request: web.Request) -> web.Response:
        template = Path(__file__).with_name("customer_widget.html").read_text(encoding="utf-8")
        page = template.replace("__AGENT_ID__", html.escape(request.match_info["agent_id"], quote=True))
        page = page.replace("__ENTRY_ID__", html.escape(request.match_info["entry_id"], quote=True))
        page = page.replace("__CONTACT_VERSION__", "")
        frame_ancestors = " ".join(("'self'", *sorted(origin_allowlist)))
        return web.Response(text=page, content_type="text/html", charset="utf-8", headers={
            "Content-Security-Policy": f"frame-ancestors {frame_ancestors}",
        })

    async def widget_loader(request: web.Request) -> web.Response:
        if (set(request.query) != {"agent_id", "entry_id"}
                or len(request.query.getall("agent_id", [])) != 1
                or len(request.query.getall("entry_id", [])) != 1):
            raise web.HTTPBadRequest(text="widget loader requires one agent_id and entry_id")
        agent_id = request.query["agent_id"]
        entry_id = request.query["entry_id"]
        if not _PUBLIC_INSTANCE_ID.fullmatch(agent_id) or not _PUBLIC_INSTANCE_ID.fullmatch(entry_id):
            raise web.HTTPBadRequest(text="invalid public widget identifier")

        result = request.app[CUSTOMER_APPLICATION_KEY].execute(
            principal=request.app[PRINCIPAL_KEY], action="widget.configuration",
            payload={"agent_id": agent_id, "entry_id": entry_id},
        )
        if not result["ok"]:
            code = result["error"]["code"]
            status = {"not_found": 404, "forbidden": 403, "release_blocked": 409,
                      "invalid_request": 400}.get(code, 500)
            return web.Response(status=status, text="Widget instance is unavailable")

        template = Path(__file__).with_name("widget_loader.js").read_text(encoding="utf-8")
        script = template.replace("__AGENT_ID__", json.dumps(agent_id))
        script = script.replace("__ENTRY_ID__", json.dumps(entry_id))
        script = script.replace("__ALLOWED_ORIGINS__", json.dumps(sorted(origin_allowlist)))
        return web.Response(text=script, content_type="application/javascript", charset="utf-8",
                            headers={"Cache-Control": "no-store"})

    async def inbox_page(request: web.Request) -> web.Response:
        template = Path(__file__).with_name("customer_inbox.html").read_text(encoding="utf-8")
        page = template.replace("__AGENT_ID__", html.escape(request.match_info["agent_id"], quote=True))
        return web.Response(text=page, content_type="text/html", charset="utf-8")

    async def contact_page(request: web.Request) -> web.Response:
        result = request.app[CUSTOMER_APPLICATION_KEY].execute(
            principal=request.app[PRINCIPAL_KEY], action="contact.get",
            payload={"agent_id": request.match_info["agent_id"], "entry_id": request.match_info["entry_id"]},
        )
        return contact_response(result)

    def contact_response(result: dict[str, Any], *, preview: bool = False) -> web.Response:
        if not result["ok"]:
            code = result["error"]["code"]
            status = {"not_found": 404, "forbidden": 403, "release_blocked": 409,
                      "state_conflict": 409, "invalid_request": 400}.get(code, 400)
            return web.Response(status=status, text="联系页不可用，请联系管理员检查配置或重新验收版本。")
        page = render_contact_page(result["result"], preview=preview)
        return web.Response(text=page, content_type="text/html", charset="utf-8", headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; media-src https:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
        })

    async def contact_preview(request: web.Request) -> web.Response:
        result = request.app[CUSTOMER_APPLICATION_KEY].execute(
            principal=request.app[PRINCIPAL_KEY], action="contact.preview",
            payload={"agent_id": request.match_info["agent_id"]},
        )
        return contact_response(result, preview=True)

    async def contact_chat(request: web.Request) -> web.Response:
        agent_id, entry_id, version_id = (request.match_info[name] for name in ("agent_id", "entry_id", "version_id"))
        result = request.app[CUSTOMER_APPLICATION_KEY].execute(
            principal=request.app[PRINCIPAL_KEY], action="contact.get",
            payload={"agent_id": agent_id, "entry_id": entry_id},
        )
        if not result["ok"]:
            return contact_response(result)
        if result["result"]["version_id"] != version_id:
            return web.Response(status=409, text="联系页已换版，请返回联系页重新咨询。")
        template = Path(__file__).with_name("customer_widget.html").read_text(encoding="utf-8")
        values = {"AGENT_ID": agent_id, "ENTRY_ID": entry_id, "CONTACT_VERSION": version_id}
        import re
        page = re.sub(r"__(AGENT_ID|ENTRY_ID|CONTACT_VERSION)__", lambda match: html.escape(values[match[1]], quote=True), template)
        return web.Response(text=page, content_type="text/html", charset="utf-8")

    async def customer_execute(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, web.HTTPBadRequest):
            body = None
        if not isinstance(body, dict) or set(body) != {"action", "payload"} \
                or not isinstance(body["action"], str) or not isinstance(body["payload"], dict):
            return web.json_response({
                "schema_version": "customer-service-v1", "ok": False,
                "result": None,
                "error": {"code": "invalid_request", "message": "请求必须包含 action 与 payload 对象"},
            }, status=400)
        if body['action'] in {'widget.send', 'contact.generate', 'inbox.assistance.generate'}:
            result = await request.app[CUSTOMER_APPLICATION_KEY].execute_async(
                principal=request.app[PRINCIPAL_KEY], action=body['action'], payload=body['payload'])
        elif body['action'] == 'material.process':
            result = await asyncio.to_thread(request.app[CUSTOMER_APPLICATION_KEY].execute,
                principal=request.app[PRINCIPAL_KEY], action=body['action'], payload=body['payload'])
        else:
            result = request.app[CUSTOMER_APPLICATION_KEY].execute(
                principal=request.app[PRINCIPAL_KEY],
                action=body["action"], payload=body["payload"],
            )
        code = result.get("error", {}).get("code") if not result.get("ok") else None
        status = {"invalid_request": 400, "forbidden": 403, "not_found": 404,
                  "state_conflict": 409, "release_blocked": 409, "revision_conflict": 409,
                  "generation_unavailable": 503, "generation_failed": 502,
                  "assistance_unavailable": 503, "assistance_failed": 502,
                  "assistance_timeout": 504, "assistance_invalid_response": 502}.get(code, 200)
        return web.json_response(result, status=status)

    async def inbox_events_stream(request: web.Request) -> web.StreamResponse:
        """Replay the durable, redacted Inbox event log over a resumable SSE stream.

        Reconnects start from the consumer's durable application ack.  The SSE
        Last-Event-ID header records transport delivery only and is ignored;
        this stream does not claim OS push delivery or message read state.
        """
        unknown_query = set(request.query) - {"agent_id", "consumer_id"}
        if unknown_query:
            raise web.HTTPBadRequest(text="仅支持 agent_id 与 consumer_id 参数")
        if any(len(request.query.getall(name, [])) != 1 for name in request.query):
            raise web.HTTPBadRequest(text="每个查询参数只能出现一次")
        agent_id = request.query.get("agent_id")
        consumer_id = request.query.get("consumer_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise web.HTTPBadRequest(text="agent_id must be a non-empty string")
        if not isinstance(consumer_id, str) or not consumer_id:
            raise web.HTTPBadRequest(text="consumer_id must be a non-empty string")
        customer = request.app[CUSTOMER_APPLICATION_KEY]
        principal = request.app[PRINCIPAL_KEY]
        try:
            receipt = customer.service.inbox_consumer_cursor(
                principal=principal, agent_id=agent_id, consumer_id=consumer_id,
            )
            # Validate scope before committing to a long-lived response so
            # failures remain ordinary HTTP statuses.
            customer.service.inbox_events(
                principal=principal, agent_id=agent_id, after_sequence=receipt['cursor'], limit=100,
            )
        except PermissionError as exc:
            raise web.HTTPForbidden(text=str(exc)) from None
        except (KeyError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from None

        delivery_cursor = receipt['cursor']

        response = web.StreamResponse(status=200, headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-store, no-transform",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
            "Connection": "keep-alive",
        })
        origin = request.headers.get("Origin")
        if origin:
            normalized_origin = _normalize_local_origin(origin)
            if normalized_origin is not None:
                response.headers["Access-Control-Allow-Origin"] = normalized_origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Last-Event-ID"
                response.headers["Vary"] = "Origin"
        await response.prepare(request)
        last_heartbeat = time.monotonic()
        try:
            while True:
                page = customer.service.inbox_events(
                    principal=principal, agent_id=agent_id,
                    after_sequence=delivery_cursor, limit=100,
                )
                for event in page["events"]:
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    await response.write(
                        f"id: {event['sequence']}\nevent: inbox\ndata: {payload}\n\n".encode("utf-8")
                    )
                    # This cursor only avoids duplicates within this connection.
                    # A reconnect rereads the durable application ack above.
                    delivery_cursor = event["sequence"]
                if page["has_more"]:
                    continue
                now = time.monotonic()
                if now - last_heartbeat >= _SSE_KEEPALIVE_SECONDS:
                    await response.write(b": keep-alive\n\n")
                    last_heartbeat = now
                await asyncio.sleep(_SSE_POLL_SECONDS)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            response.force_close()
        return response

    app.router.add_get("/api/configuration/health", health)
    app.router.add_post("/api/configuration", execute)
    app.router.add_options("/api/configuration", execute)
    app.router.add_post("/api/customer-service", customer_execute)
    app.router.add_options("/api/customer-service", customer_execute)
    app.router.add_get("/api/customer-service/inbox/events", inbox_events_stream, allow_head=False)
    app.router.add_options("/api/customer-service/inbox/events", inbox_events_stream)
    app.router.add_get("/widget.js", widget_loader, allow_head=False)
    app.router.add_get("/widget/{agent_id}/{entry_id}", widget_page)
    app.router.add_get("/inbox/{agent_id}", inbox_page)
    app.router.add_get("/contact/{agent_id}/{entry_id}", contact_page)
    app.router.add_get("/contact/{agent_id}/{entry_id}/chat/{version_id}", contact_chat)
    app.router.add_get("/contact-preview/{agent_id}", contact_preview)

    async def close_store(_: web.Application) -> None:
        store.close()

    app.on_cleanup.append(close_store)
    return app


def serve_configuration_http(
    *, port: int = 8766, principal_path=DEFAULT_PRINCIPAL_FILE,
    database_path=DEFAULT_DATABASE_FILE, allowed_origins: Iterable[str] | None = None,
) -> None:
    if not 0 < port < 65536:
        raise ValueError("Invalid port")
    app = create_configuration_http_app(
        principal_path=principal_path, database_path=database_path,
        allowed_origins=allowed_origins,
    )
    print(f"Loomrise configuration API: http://127.0.0.1:{port}")
    web.run_app(app, host="127.0.0.1", port=port, print=None, handler_cancellation=True)


__all__ = [
    "APPLICATION_KEY", "CUSTOMER_APPLICATION_KEY", "create_configuration_http_app",
    "serve_configuration_http",
]
