# -*- coding: utf-8 -*-
"""阿里云百炼流式语音适配：ASR 上行、TTS 下行，用 asyncio 队列桥接 SDK 线程。

**这个模块只做媒体传输，不做业务执行。** 识别出的文本回到浏览器后仍走
`POST /api/runs` → 同一个 `ExecutionService`。语音不是第二条执行路径。

三条纪律：

1. **凭据缺失就显式失败**（`VoiceUnavailable`），不回退到浏览器 `speechSynthesis`。
   回退会让验收记录里"服务端固定组合"变成假话。
2. **SDK 的阻塞调用一律进线程**：`Recognition.start()/stop()`、`streaming_*()`。
   `send_audio_frame()` 只是入队，可以在事件循环里直接调。
3. **每个句子一个 TTS 实例**。按句合成才能按句打断；一个长连接跨句合成，
   打断时说不清停在哪一句。
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: 上行与下行统一用 16 kHz / 单声道 / 16 bit 小端，避免两端各做一次重采样。
SAMPLE_RATE = 16_000
#: 100 ms 一帧。低于此值会放大 WS 开销，高于此值会让 ASR 首字延迟变钝。
FRAME_BYTES = 3_200
#: 上行积压上限（约 3 秒音频）。超过就丢帧并计数，不无限吃内存。
MAX_BACKLOG_BYTES = SAMPLE_RATE * 2 * 3

_INIT_LOCK = threading.Lock()


class VoiceUnavailable(RuntimeError):
    """语音依赖或凭据不可用。调用方应把这条链路标成"不可用"，不是"降级可用"。"""


def preflight() -> dict[str, Any]:
    """读取凭据并把 SDK 指到正确端点。返回配置字典（**不含密钥**）。"""
    try:
        import dashscope  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 环境问题，不是逻辑分支
        raise VoiceUnavailable("dashscope 未安装") from exc

    from ..voice_config import endpoints, load_config, resolve_api_key

    cfg = load_config()
    key = resolve_api_key(cfg)
    if not key:
        raise VoiceUnavailable(
            "未配置语音凭据：先运行 `python -m loomrise.cli configure-voice`，"
            "或设置环境变量 DASHSCOPE_API_KEY"
        )

    with _INIT_LOCK:
        # key 与 base url 是 SDK 的模块级全局量。设置与构造放进同一临界区，
        # 避免两个会话交错时把对方的端点顶掉。
        dashscope.api_key = key
        dashscope.base_websocket_api_url = endpoints(cfg["workspace"])["dashscope_ws"]
    return cfg


def public_config() -> dict[str, Any]:
    """给前端与证据文件用的公开配置（无密钥、无 workspace）。"""
    cfg = preflight()
    return {
        "asr_model": cfg["asr_model"],
        "tts_model": cfg["tts_model"],
        "tts_voice": cfg["tts_voice"],
        "sample_rate": SAMPLE_RATE,
    }


@dataclass
class AsrEvent:
    """一条识别事件。

    `final=True` 只代表**这一句**结束（服务端 VAD 判了句尾），不代表用户说完了。
    一句话里出现多个 final 是常态：中文逗号处的停顿就可能被判成句尾。
    "整轮是否结束"由上层按静音窗口判定，不由单条事件决定。
    """

    text: str
    final: bool
    begin_ms: int | None = None
    end_ms: int | None = None
    at: float = field(default_factory=time.monotonic)
    #: `finish()` 补发的结束信号，不是识别结果。
    synthetic: bool = False


class AsrStream:
    """一次识别会话。`events` 里出现 `final` 后即可调用 `close()`。"""

    def __init__(self) -> None:
        cfg = preflight()
        from dashscope.audio.asr import Recognition, RecognitionCallback

        self.model = cfg["asr_model"]
        self.events: asyncio.Queue[AsrEvent | None] = asyncio.Queue()
        self.dropped_bytes = 0
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._error: str | None = None

        outer = self

        class _Callback(RecognitionCallback):
            def on_open(self) -> None:
                return None

            def on_close(self) -> None:
                return None

            def on_complete(self) -> None:
                return None

            def on_error(self, result: Any) -> None:
                outer._error = str(result)[:300]

            def on_event(self, result: Any) -> None:
                sentence = result.get_sentence() or {}
                if not sentence:
                    return
                text = (sentence.get("text") or "").strip()
                if not text and not sentence.get("sentence_end"):
                    return
                outer._push(
                    AsrEvent(
                        text=text,
                        final=bool(sentence.get("sentence_end")),
                        begin_ms=sentence.get("begin_time"),
                        end_ms=sentence.get("end_time"),
                    )
                )

        self._rec = Recognition(
            model=self.model,
            callback=_Callback(),
            format="pcm",
            sample_rate=SAMPLE_RATE,
            workspace=cfg["workspace"],
            disfluency_removal_enabled=True,
            # 默认 800 ms 太短：中文逗号间的停顿就会被判成句尾，一句话被切成三四段。
            # 1500 ms 仍会在真实换人/长停顿时断句，但不至于切碎正常语流。
            max_sentence_silence=1500,
        )

    def _push(self, event: AsrEvent) -> None:
        self._loop.call_soon_threadsafe(self.events.put_nowait, event)

    async def open(self) -> None:
        await asyncio.to_thread(self._rec.start)

    def _backlog(self) -> int:
        """SDK 内部待发送队列的字节数。

        必须读真实队列，不能自己累加发送量：累计值只增不减，
        会把"已经发出去的数据"也算成积压，几秒后就开始永久丢帧——
        实测表现是识别在固定时间点截断，看起来像服务端判句尾，其实是自己把后半句扔了。
        """
        queue = getattr(self._rec, "_stream_data", None)
        try:
            return int(queue.qsize()) if queue is not None else 0
        except Exception:  # noqa: BLE001 - 取不到就不拦，交给 SDK 自己限流
            return 0

    async def feed(self, chunk: bytes) -> None:
        if self._closed or not chunk:
            return
        if self._backlog() > MAX_BACKLOG_BYTES:
            self.dropped_bytes += len(chunk)
            return
        try:
            # 入队不阻塞（SDK 内部是 Queue.put），但它会抛 InvalidParameter，必须接住。
            self._rec.send_audio_frame(chunk)
        except Exception as exc:  # noqa: BLE001 - SDK 异常类型不稳定
            self._error = f"{type(exc).__name__}: {exc}"[:300]
            self._closed = True
            self._push(AsrEvent(text="", final=True, synthetic=True))

    async def finish(self) -> None:
        """停止发送并等 SDK 收尾。收尾后推一条 `synthetic` 事件通知上层已无后续。"""
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.to_thread(self._rec.stop)
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            self._push(AsrEvent(text="", final=True, synthetic=True))

    @property
    def error(self) -> str | None:
        return self._error


@dataclass
class TtsTiming:
    """一句话的合成时序，全部是 `monotonic()` 秒，便于直接相减。"""

    request_at: float = 0.0
    first_pcm_at: float | None = None
    done_at: float | None = None
    cancel_at: float | None = None
    bytes: int = 0
    first_package_ms: float | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        def ms(a: float | None, b: float | None) -> float | None:
            return None if a is None or b is None else round((b - a) * 1000, 1)

        return {
            "first_pcm_ms": ms(self.request_at, self.first_pcm_at),
            "total_ms": ms(self.request_at, self.done_at),
            "cancel_ms": ms(self.request_at, self.cancel_at),
            "bytes": self.bytes,
            "sdk_first_package_ms": (
                round(self.first_package_ms, 1) if self.first_package_ms is not None else None
            ),
            "error": self.error,
        }


class TtsStream:
    """一句话的流式合成，按块吐出 PCM。"""

    def __init__(self, text: str) -> None:
        cfg = preflight()
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

        self.text = text
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.timing = TtsTiming(request_at=time.monotonic())
        self._loop = asyncio.get_running_loop()
        self._cancelled = False

        outer = self

        class _Callback(ResultCallback):
            def on_open(self) -> None:
                return None

            def on_close(self) -> None:
                return None

            def on_error(self, message: Any) -> None:
                outer.timing.error = str(message)[:300]

            def on_complete(self) -> None:
                return None

            def on_data(self, data: bytes) -> None:
                if not data or outer._cancelled:
                    return
                if outer.timing.first_pcm_at is None:
                    outer.timing.first_pcm_at = time.monotonic()
                outer.timing.bytes += len(data)
                outer._loop.call_soon_threadsafe(outer.chunks.put_nowait, data)

        self._syn = SpeechSynthesizer(
            model=cfg["tts_model"],
            voice=cfg["tts_voice"],
            format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            callback=_Callback(),
            workspace=cfg["workspace"],
        )
        self._syn_lock = threading.Lock()

    def _run_blocking(self) -> None:
        try:
            self._syn.streaming_call(self.text)
            self._syn.streaming_complete()
        except Exception as exc:  # noqa: BLE001
            self.timing.error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            try:
                self.timing.first_package_ms = self._syn.get_first_package_delay()
            except Exception:  # noqa: BLE001
                pass
            self.timing.done_at = time.monotonic()
            self._loop.call_soon_threadsafe(self.chunks.put_nowait, None)

    async def start(self) -> None:
        await asyncio.to_thread(self._run_blocking)

    def cancel(self) -> None:
        """打断：停合成、清队列。**不代表浏览器已经停声**——那是客户端回执的事。"""
        if self._cancelled:
            return
        self._cancelled = True
        self.timing.cancel_at = time.monotonic()
        try:
            self._syn.streaming_cancel()
        except Exception as exc:  # noqa: BLE001
            self.timing.error = f"{type(exc).__name__}: {exc}"[:300]
        while not self.chunks.empty():
            try:
                self.chunks.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover
                break
        # 唤醒下游取块循环，否则它会在空队列上永久等待。
        self.chunks.put_nowait(None)


__all__ = [
    "AsrStream",
    "AsrEvent",
    "TtsStream",
    "TtsTiming",
    "VoiceUnavailable",
    "preflight",
    "public_config",
    "SAMPLE_RATE",
    "FRAME_BYTES",
    "MAX_BACKLOG_BYTES",
]
