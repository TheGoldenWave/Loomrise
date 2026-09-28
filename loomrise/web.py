"""Loopback-only S1 browser entry: AG-UI SSE over the shared ExecutionService."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import web

from .adapters.projection import AguiProjector
from .adapters.voice import VoiceSession, make_voice_emitter
from .cli import DEFAULT_CASES, DEFAULT_PACK
from .contracts import Case, Channel, new_id
from .local_config import load_config
from .service import ExecutionService
from .contracts import ScenarioPack


class BrowserApp:
    def __init__(self, *, scripted: bool = False, pack_path: Path = DEFAULT_PACK) -> None:
        self.service = ExecutionService(ScenarioPack.load(str(pack_path)))
        self.scripted = scripted
        self.running: dict[str, asyncio.Task[Any]] = {}
        self.pending: dict[str, tuple[asyncio.Future[list[bool]], int]] = {}
        self.results: dict[str, Any] = {}
        self.voice: dict[str, VoiceSession] = {}

    @staticmethod
    @web.middleware
    async def local_only(request: web.Request, handler):
        host = request.headers.get("Host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            raise web.HTTPForbidden()
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != f"http://{request.headers['Host']}":
                raise web.HTTPForbidden()
            if request.content_type != "application/json":
                raise web.HTTPUnsupportedMediaType()
        return await handler(request)

    def application(self) -> web.Application:
        app = web.Application(middlewares=[self.local_only], client_max_size=32_768)
        app.router.add_get("/", self.index)
        app.router.add_get("/api/status", self.status)
        app.router.add_post("/api/runs", self.run)
        app.router.add_post("/api/confirm", self.confirm)
        app.router.add_post("/api/cancel", self.cancel)
        app.router.add_post("/api/playback", self.playback)
        return app

    async def index(self, _: web.Request) -> web.Response:
        return web.Response(
            text=(Path(__file__).with_name("web.html")).read_text(encoding="utf-8"),
            content_type="text/html", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def status(self, _: web.Request) -> web.Response:
        return web.json_response({"configured": self.scripted or bool(load_config()),
                                  "scripted": self.scripted, "version": self.service.pack.agent_version.version_id})

    async def run(self, http: web.Request) -> web.StreamResponse:
        data = await http.json()
        text = data.get("text")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 2000:
            raise web.HTTPBadRequest(text="text must be 1-2000 characters")
        try:
            channel = Channel(data.get("channel", "text"))
        except ValueError:
            raise web.HTTPBadRequest(text="unknown channel") from None
        if not (self.scripted or load_config()):
            raise web.HTTPServiceUnavailable(text="Run configure-model first")
        request_id = data.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise web.HTTPBadRequest(text="invalid request_id")
        if request_id and request_id not in self.service.requests:
            raise web.HTTPNotFound(text="unknown request_id")
        if request_id and request_id in self.running:
            raise web.HTTPConflict(text="request already running")
        req = self.service.requests[request_id] if request_id else self.service._new_request(channel, text)
        offset = len(self.service.ledger.events)
        media_id = new_id("media") if channel is Channel.VOICE else None

        async def ask(calls: list[Any]) -> list[bool]:
            future: asyncio.Future[list[bool]] = asyncio.get_running_loop().create_future()
            self.pending[req.request_id] = (future, len(calls))
            try:
                return await asyncio.wait_for(future, timeout=120)
            except TimeoutError:
                return [False] * len(calls)
            finally:
                self.pending.pop(req.request_id, None)

        script = None
        if self.scripted:
            name = "c2_booking_confirmed.json" if "预约" in text or "报名" in text else "c1_consult_success.json"
            script = Case.load(str(DEFAULT_CASES / name)).script
            for step in script:
                if step.get("tool") == "create_booking":
                    step["args"]["idempotency_key"] = f"idem-{req.request_id}"
        kwargs: dict[str, Any] = {"request": req, "ask_confirm": ask, "script": script}
        if media_id:
            kwargs["media_session_id"] = media_id
        fn = self.service.handle_utterance if media_id else self.service.handle_text
        task = asyncio.create_task(fn(text.strip(), **kwargs))
        self.running[req.request_id] = task
        response = web.StreamResponse(status=200, headers={
            "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff",
        })
        await response.prepare(http)
        projector = AguiProjector()
        run_id = None
        try:
            while True:
                for event in self.service.ledger.events[offset:]:
                    offset = event.seq + 1
                    if event.request_id != req.request_id:
                        continue
                    if event.event_type == "run.started":
                        run_id = event.run_id
                    if run_id != event.run_id:
                        continue
                    for projected in projector.project(event):
                        await self._send(response, projected)
                if task.done():
                    try:
                        result = task.result()
                    except Exception:
                        await self._send(response, {"type": "RUN_ERROR", "message": "Model or service request failed; check local server logs"})
                    else:
                        self.results[result.run_id] = result
                        if media_id:
                            self.voice[result.run_id] = VoiceSession(
                                session_id=media_id, request_id=req.request_id, run_id=result.run_id,
                                emit=make_voice_emitter(self.service.ledger, request_id=req.request_id,
                                    run_id=result.run_id, tenant_id=self.service.tenant_id,
                                    agent_version=req.agent_version, media_session_id=media_id),
                            )
                        await self._send(response, {"type": "CUSTOM", "name": "loomrise.summary", "value": {
                            "request_id": req.request_id, "run_id": result.run_id,
                            "version": req.agent_version, "state": req.state.value,
                            "text": result.text, "result_id": req.result_id,
                            "channel": channel.value,
                        }})
                    break
                await asyncio.sleep(.04)
        except (ConnectionResetError, asyncio.CancelledError):
            if run_id and not task.done():
                self.service.cancel(req.request_id, run_id=run_id, reason="client_disconnected")
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self.running.pop(req.request_id, None)
        return response

    @staticmethod
    async def _send(response: web.StreamResponse, event: dict[str, Any]) -> None:
        await response.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())

    async def confirm(self, http: web.Request) -> web.Response:
        data = await http.json()
        pending = self.pending.get(data.get("request_id"))
        if not pending or type(data.get("confirmed")) is not bool:
            raise web.HTTPConflict(text="no matching pending confirmation")
        future, count = pending
        if future.done():
            raise web.HTTPConflict(text="confirmation already answered")
        future.set_result([data["confirmed"]] * count)
        return web.json_response({"accepted": True})

    async def cancel(self, http: web.Request) -> web.Response:
        data = await http.json()
        req_id, run_id = data.get("request_id"), data.get("run_id")
        if not isinstance(req_id, str) or not isinstance(run_id, str):
            raise web.HTTPBadRequest()
        return web.json_response({"cancel_requested": self.service.cancel(req_id, run_id=run_id)})

    async def playback(self, http: web.Request) -> web.Response:
        data = await http.json()
        run_id = data.get("run_id")
        session = self.voice.get(run_id) if isinstance(run_id, str) else None
        result = self.results.get(run_id)
        if not session or data.get("request_id") != session.request_id:
            raise web.HTTPNotFound()
        action = data.get("action")
        if action == "started" and result.text and data.get("text") == result.text:
            return web.json_response({"fragment_id": session.start_fragment(result.text)})
        fragment_id = data.get("fragment_id")
        if action == "finished" and isinstance(fragment_id, str):
            ok = session.ack_playback(fragment_id)
        elif action == "interrupted" and isinstance(fragment_id, str):
            ok = session.mark_unknown(fragment_id, note="浏览器打断，未确认播出")
        else:
            raise web.HTTPBadRequest()
        if not ok:
            raise web.HTTPConflict(text="invalid playback transition")
        return web.json_response({"accepted": True})


def serve(port: int, *, scripted: bool = False) -> int:
    if not 0 < port < 65536:
        raise ValueError("Invalid port")
    app = BrowserApp(scripted=scripted)
    print(f"Loomrise local trial: http://127.0.0.1:{port} ({'scripted' if scripted else 'Coding Plan'})")
    web.run_app(app.application(), host="127.0.0.1", port=port, print=None)
    return 0
