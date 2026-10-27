"""Loopback HTTP adapter for the shared R1 configuration application."""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from typing import Any, Iterable

from aiohttp import web

from .config_auth import DEFAULT_DATABASE_FILE, DEFAULT_PRINCIPAL_FILE, load_configuration_principal
from .configuration import (
    CONFIG_SCHEMA_VERSION, ConfigurationApplication, ConfigurationPrincipal,
    ConfigurationService,
)
from .durable_store import SqliteStore

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DEFAULT_ALLOWED_ORIGINS = frozenset({
    "http://127.0.0.1:8765", "http://localhost:8765",
})
STORE_KEY = web.AppKey("configuration_store", SqliteStore)
APPLICATION_KEY = web.AppKey("configuration_application", ConfigurationApplication)
PRINCIPAL_KEY = web.AppKey("configuration_principal", ConfigurationPrincipal)


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
    }.get(code, 500)


def create_configuration_http_app(
    *, principal_path=DEFAULT_PRINCIPAL_FILE, database_path=DEFAULT_DATABASE_FILE,
    allowed_origins: Iterable[str] | None = None,
) -> web.Application:
    """Build an HTTP adapter bound to one trusted local principal.

    No user, tenant, or role can be supplied by a browser request. The same
    application contract is used by the CLI and stdio MCP adapters.
    """
    principal = load_configuration_principal(principal_path)
    origin_allowlist = _allowed_origins(allowed_origins)
    store = SqliteStore(str(database_path))
    application = ConfigurationApplication(ConfigurationService(store))
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app[STORE_KEY] = store
    app[APPLICATION_KEY] = application
    app[PRINCIPAL_KEY] = principal

    async def local_only(request: web.Request, handler):
        host = request.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        if host not in _LOOPBACK_HOSTS:
            raise web.HTTPForbidden(text="configuration service is loopback-only")
        origin = request.headers.get("Origin")
        normalized_origin = _normalize_local_origin(origin) if origin else None
        if origin and normalized_origin not in origin_allowlist:
            raise web.HTTPForbidden(text="cross-origin access is limited to configured workbench origins")
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            if request.method == "POST" and request.content_type != "application/json":
                raise web.HTTPUnsupportedMediaType()
            response = await handler(request)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = normalized_origin
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
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

    app.router.add_get("/api/configuration/health", health)
    app.router.add_post("/api/configuration", execute)
    app.router.add_options("/api/configuration", execute)

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
    web.run_app(app, host="127.0.0.1", port=port, print=None)


__all__ = [
    "APPLICATION_KEY", "create_configuration_http_app", "serve_configuration_http",
]
