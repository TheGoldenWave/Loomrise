"""Loopback-only S1 browser entry: AG-UI SSE over the shared ExecutionService."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from .adapters import aliyun_voice
from .adapters.projection import AguiProjector
from .adapters.voice import VoiceSession, make_voice_emitter
from .cli import DEFAULT_CASES, DEFAULT_PACK
from .contracts import Case, Channel, new_id
from .local_config import load_config
from .service import ExecutionService
from .contracts import ScenarioPack


class BrowserApp:
    def __init__(
        self,
        *,
        scripted: bool = False,
        pack_path: Path = DEFAULT_PACK,
        voice_trace_dir: Path | None = None,
    ) -> None:
        self.service = ExecutionService(ScenarioPack.load(str(pack_path)))
        self.scripted = scripted
        self.running: dict[str, asyncio.Task[Any]] = {}
        self.pending: dict[str, tuple[asyncio.Future[list[bool]], int]] = {}
        self.results: dict[str, Any] = {}
        self.voice: dict[str, VoiceSession] = {}
        # 只有显式开启时才落盘：默认路径不写文件，跑测时才要原始件。
        self.voice_trace_dir = voice_trace_dir

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
        app.router.add_get("/ws/voice", self.voice_ws)
        return app

    async def index(self, _: web.Request) -> web.Response:
        return web.Response(
            text=(Path(__file__).with_name("web.html")).read_text(encoding="utf-8"),
            content_type="text/html", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    async def status(self, _: web.Request) -> web.Response:
        voice: dict[str, Any] = {"available": False}
        try:
            voice = {"available": True, **aliyun_voice.public_config()}
        except aliyun_voice.VoiceUnavailable as exc:
            voice["reason"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - 状态页不该因语音配置崩掉
            voice["reason"] = f"{type(exc).__name__}: {exc}"[:200]
        return web.json_response({"configured": self.scripted or bool(load_config()),
                                  "scripted": self.scripted, "version": self.service.pack.agent_version.version_id,
                                  "voice": voice})

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

    async def voice_ws(self, http: web.Request) -> web.WebSocketResponse:
        """媒体通道：上行麦克风 PCM，下行合成 PCM。

        **协议边界（改了要同步文档）**

        上行（浏览器 → 服务端）
        - 二进制帧：PCM16LE / 16 kHz / 单声道，建议 100 ms 一帧（3200 字节）
        - `{"type":"asr.start"}` 开一轮识别
        - `{"type":"asr.stop"}` 结束发送，等服务端给 `asr.final`
        - `{"type":"tts.speak","text":"...","run_id":"..."}`
        - `{"type":"tts.cancel","reason":"barge_in"}`
        - `{"type":"metric","name":"playback.first_audio","value":{...}}` 只入证据，不回执
        - `{"type":"close"}`

        下行（服务端 → 浏览器）
        - 二进制帧：PCM16LE / 16 kHz / 单声道
        - `ready` / `asr.ready` / `asr.partial` / `asr.final` /
          `tts.started` / `tts.first_audio` / `tts.done` / `tts.cancelled` / `error`

        **这里不承载业务执行。** 识别出的文本由浏览器照旧 `POST /api/runs`，
        走同一个 `ExecutionService`；语音只替换"声音怎么进出浏览器"。
        第二条执行路径会立刻产生第二套状态。
        """
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4 * 1024 * 1024, compress=False)
        await ws.prepare(http)

        try:
            info = aliyun_voice.public_config()
        except aliyun_voice.VoiceUnavailable as exc:
            await ws.send_json({"type": "error", "code": "voice_unavailable", "message": str(exc)})
            await ws.close(code=1013, message=b"voice unavailable")
            return ws
        except Exception as exc:  # noqa: BLE001
            await ws.send_json({"type": "error", "code": "voice_init_failed",
                                "message": f"{type(exc).__name__}: {exc}"[:200]})
            await ws.close(code=1011, message=b"voice init failed")
            return ws

        session_id = new_id("vsess")
        t0 = time.monotonic()
        trace: list[dict[str, Any]] = []

        def mark(kind: str, **fields: Any) -> None:
            trace.append({"t_ms": round((time.monotonic() - t0) * 1000, 1), "kind": kind, **fields})

        write_lock = asyncio.Lock()

        async def send_json(payload: dict[str, Any]) -> None:
            async with write_lock:
                if not ws.closed:
                    await ws.send_json(payload)

        async def send_bytes(data: bytes) -> None:
            async with write_lock:
                if not ws.closed:
                    await ws.send_bytes(data)

        asr: aliyun_voice.AsrStream | None = None
        asr_pump: asyncio.Task[Any] | None = None
        tts: aliyun_voice.TtsStream | None = None
        tts_tasks: list[asyncio.Task[Any]] = []
        asr_sentences = 0

        async def pump_asr(stream: aliyun_voice.AsrStream) -> None:
            """转发每一句的结果。

            `final` 是**句尾**不是**轮次结束**：一句话被切成多段是常态，
            所以这里不带"只发一次"的去重——那会把用户后半句吞掉。
            真正的轮次结束由 `asr.closed` 表示，由 `asr.stop` 触发。
            """
            nonlocal asr_sentences
            while True:
                event = await stream.events.get()
                if event.synthetic:
                    mark("asr.closed", sentences=asr_sentences,
                         dropped_bytes=stream.dropped_bytes, error=stream.error)
                    await send_json({"type": "asr.closed", "sentences": asr_sentences,
                                     "dropped_bytes": stream.dropped_bytes,
                                     "error": stream.error})
                    return
                if event.final:
                    if not event.text:
                        continue  # 纯静音句尾，不转发，会话继续
                    asr_sentences += 1
                    mark("asr.final", text=event.text, begin_ms=event.begin_ms,
                         end_ms=event.end_ms, index=asr_sentences)
                    await send_json({"type": "asr.final", "text": event.text,
                                     "begin_ms": event.begin_ms, "end_ms": event.end_ms,
                                     "index": asr_sentences})
                    continue
                if event.text:
                    mark("asr.partial", text=event.text)
                    await send_json({"type": "asr.partial", "text": event.text,
                                     "begin_ms": event.begin_ms})

        async def pump_tts(stream: aliyun_voice.TtsStream, run_id: Any) -> None:
            first = True
            while True:
                chunk = await stream.chunks.get()
                if chunk is None:
                    break
                if first:
                    first = False
                    timing = stream.timing.public()
                    mark("tts.first_audio", run_id=run_id, **timing)
                    await send_json({"type": "tts.first_audio", "run_id": run_id, "timing": timing})
                await send_bytes(chunk)
            timing = stream.timing.public()
            mark("tts.done", run_id=run_id, **timing)
            await send_json({"type": "tts.done", "run_id": run_id, "timing": timing})

        def stop_tts() -> None:
            nonlocal tts
            if tts is not None:
                tts.cancel()
                tts = None

        await send_json({"type": "ready", "session_id": session_id, **info})
        mark("session.ready", session_id=session_id, **info)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    if asr is not None:
                        await asr.feed(msg.data)
                    else:
                        mark("audio.dropped", reason="no_asr_session", bytes=len(msg.data))
                    continue
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except (json.JSONDecodeError, TypeError):
                    await send_json({"type": "error", "code": "bad_json"})
                    continue
                if not isinstance(data, dict):
                    await send_json({"type": "error", "code": "bad_message"})
                    continue
                kind = data.get("type")

                if kind == "asr.start":
                    stop_tts()
                    asr_sentences = 0
                    if asr is not None:
                        await asr.finish()
                    asr = aliyun_voice.AsrStream()
                    await asr.open()
                    mark("asr.open", model=asr.model)
                    asr_pump = asyncio.create_task(pump_asr(asr))
                    await send_json({"type": "asr.ready", "model": asr.model,
                                     "sample_rate": aliyun_voice.SAMPLE_RATE})

                elif kind == "asr.stop":
                    mark("asr.stop", dropped_bytes=asr.dropped_bytes if asr else 0)
                    if asr is not None:
                        await asr.finish()

                elif kind == "tts.speak":
                    text = data.get("text")
                    if not isinstance(text, str) or not 0 < len(text.strip()) <= 2000:
                        await send_json({"type": "error", "code": "bad_text"})
                        continue
                    stop_tts()
                    tts = aliyun_voice.TtsStream(text.strip())
                    run_id = data.get("run_id")
                    mark("tts.request", run_id=run_id, chars=len(text.strip()))
                    tts_tasks.append(asyncio.create_task(tts.start()))
                    tts_tasks.append(asyncio.create_task(pump_tts(tts, run_id)))
                    await send_json({"type": "tts.started", "run_id": run_id,
                                     "chars": len(text.strip())})

                elif kind == "tts.cancel":
                    reason = data.get("reason")
                    mark("tts.cancel", reason=reason, had_stream=tts is not None)
                    stop_tts()
                    await send_json({"type": "tts.cancelled"})

                elif kind == "metric":
                    # 浏览器侧时序只进证据文件，不改服务端状态。
                    mark("client." + str(data.get("name"))[:40], value=data.get("value"))

                elif kind == "close":
                    break

                else:
                    await send_json({"type": "error", "code": "unknown_type",
                                     "message": str(kind)[:40]})
        except (ConnectionResetError, asyncio.CancelledError):
            mark("session.aborted")
        finally:
            stop_tts()
            for task in tts_tasks:
                task.cancel()
            if asr is not None:
                try:
                    await asr.finish()
                except Exception:  # noqa: BLE001
                    pass
            if asr_pump is not None:
                asr_pump.cancel()
            mark("session.closed")
            self._write_trace(session_id, trace)
            await ws.close()
        return ws

    def _write_trace(self, session_id: str, rows: list[dict[str, Any]]) -> None:
        """原始件写 `runs/<版本>/voice/`（该目录不入库），摘要人工搬进证据文档。"""
        if self.voice_trace_dir is None or not rows:
            return
        try:
            self.voice_trace_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = self.voice_trace_dir / f"ws-{stamp}-{session_id}.jsonl"
            path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[voice-trace] 写入失败：{exc}；会话已结束，改用日志可见", flush=True)

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


def serve(port: int, *, scripted: bool = False, voice_trace_dir: Path | None = None) -> int:
    if not 0 < port < 65536:
        raise ValueError("Invalid port")
    app = BrowserApp(scripted=scripted, voice_trace_dir=voice_trace_dir)
    print(f"Loomrise local trial: http://127.0.0.1:{port} ({'scripted' if scripted else 'Coding Plan'})")
    if voice_trace_dir is not None:
        print(f"Voice trace -> {voice_trace_dir}")
    web.run_app(app.application(), host="127.0.0.1", port=port, print=None)
    return 0
