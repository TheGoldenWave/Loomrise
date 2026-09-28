# -*- coding: utf-8 -*-
"""网页语音适配（Pipecat 1.12.0）。

复用的部分：轮次与打断由 Pipecat 负责，Loomrise 用 observer 挂观测，不改上游。
必须自建的部分：**"已确认播出"**。Pipecat 的 `BotStoppedSpeakingFrame` 只代表
服务端口径的播放边界，没有客户端设备级回执 → S1 的四态
`generated / sent / confirmed / unknown` 由本模块维护，未知不是成功。

Pipecat 不导入也可运行：帧按类名映射（duck typing），真实部署时
`make_observer()` 会挂到 `PipelineTask.add_observer()`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..contracts import Channel, PlaybackState


def make_voice_emitter(
    ledger,
    *,
    request_id: str,
    run_id: str,
    tenant_id: str,
    agent_version: str,
    media_session_id: str,
):
    """把语音事件绑定到某个 request/run 的账本写入器。"""

    def emit(event_type: str, **payload: Any):
        return ledger.emit(
            event_type,
            request_id=request_id,
            run_id=run_id,
            tenant_id=tenant_id,
            agent_version=agent_version,
            channel=Channel.VOICE.value,
            media_session_id=media_session_id,
            **payload,
        )

    return emit

# 帧类名 → 本模块的语义动作
_FRAME_ACTIONS = {
    "TTSTextFrame": "generated",
    "LLMTextFrame": "generated",
    "TTSStartedFrame": "tts_started",
    "TTSStoppedFrame": "tts_finished",
    "BotStartedSpeakingFrame": "speaking_started",
    "BotStoppedSpeakingFrame": "speaking_stopped",
    "InterruptionFrame": "interrupted",
    "StartInterruptionFrame": "interrupted",
    "UserStartedSpeakingFrame": "user_started",
    "UserStoppedSpeakingFrame": "user_stopped",
}


@dataclass
class PlaybackRecord:
    fragment_id: str
    text: str = ""
    state: PlaybackState = PlaybackState.GENERATED
    ack_at: str | None = None
    note: str = ""


@dataclass
class VoiceSession:
    """一次媒体会话的播放账本。业务请求仍走 ExecutionService。"""

    session_id: str
    emit: Callable[..., Any]
    request_id: str | None = None
    run_id: str | None = None
    records: list[PlaybackRecord] = field(default_factory=list)
    interruptions: int = 0
    _seq: int = 0

    # -- 帧事件 ------------------------------------------------------------
    def on_frame(self, frame: Any) -> str | None:
        action = _FRAME_ACTIONS.get(type(frame).__name__)
        if action is None:
            return None
        return getattr(self, f"_on_{action}")(frame)

    def _on_generated(self, frame: Any) -> str:
        self._seq += 1
        rec = PlaybackRecord(
            fragment_id=f"{self.session_id}_frag_{self._seq}",
            text=getattr(frame, "text", "") or "",
            state=PlaybackState.GENERATED,
        )
        self.records.append(rec)
        self._emit_playback(rec, "生成了待播片段")
        return rec.fragment_id

    def _on_tts_started(self, frame: Any) -> str:
        self.emit(
            "voice.tts_started",
        )
        return "tts_started"

    def _on_tts_finished(self, frame: Any) -> str:
        self.emit(
            "voice.tts_finished",
        )
        return "tts_finished"

    def _on_speaking_started(self, frame: Any) -> str:
        self.emit(
            "voice.speaking_started",
        )
        return "speaking_started"

    def _on_speaking_stopped(self, frame: Any) -> str:
        """服务端口径的播放结束 = `sent`，**不是** `confirmed`。"""
        for rec in reversed(self.records):
            if rec.state in (PlaybackState.GENERATED, PlaybackState.SENT):
                rec.state = PlaybackState.SENT
                rec.note = "服务端播放结束，等待客户端设备级回执"
                self._emit_playback(rec, rec.note)
                break
        return "speaking_stopped"

    def _on_interrupted(self, frame: Any) -> str:
        self.interruptions += 1
        invalidated = [
            r.fragment_id
            for r in self.records
            if r.state in (PlaybackState.GENERATED, PlaybackState.SENT)
        ]
        for r in self.records:
            if r.fragment_id in invalidated:
                r.state = PlaybackState.UNKNOWN
                r.note = "被用户打断，未确认播出（不得记为用户已听见）"
        self.emit(
            "voice.interrupted",
            invalidated_fragments=invalidated,
        )
        return "interrupted"

    def _on_user_started(self, frame: Any) -> str:
        self.emit("voice.user_started")
        return "user_started"

    def _on_user_stopped(self, frame: Any) -> str:
        self.emit("voice.user_stopped")
        return "user_stopped"

    # -- 客户端回执（Loomrise 自建） --------------------------------------
    def ack_playback(self, fragment_id: str, *, at: str = "") -> bool:
        for rec in self.records:
            if rec.fragment_id == fragment_id and rec.state == PlaybackState.SENT:
                rec.state = PlaybackState.CONFIRMED
                rec.ack_at = at or "(runtime)"
                rec.note = "客户端确认播出"
                self._emit_playback(rec, rec.note)
                return True
        return False

    def mark_sent(self, fragment_id: str) -> bool:
        for rec in self.records:
            if rec.fragment_id == fragment_id and rec.state == PlaybackState.GENERATED:
                rec.state = PlaybackState.SENT
                self._emit_playback(rec, "浏览器报告开始播出")
                return True
        return False

    def start_fragment(self, text: str) -> str:
        """Browser speech synthesis started; audio is real but delivery is not yet confirmed."""
        self._seq += 1
        rec = PlaybackRecord(fragment_id=f"{self.session_id}_frag_{self._seq}", text=text)
        self.records.append(rec)
        self._emit_playback(rec, "浏览器开始合成播报")
        self.mark_sent(rec.fragment_id)
        return rec.fragment_id

    def mark_unknown(self, fragment_id: str, *, note: str = "超时未取得播出回执") -> bool:
        for rec in self.records:
            if rec.fragment_id == fragment_id:
                rec.state = PlaybackState.UNKNOWN
                rec.note = note
                self._emit_playback(rec, note)
                return True
        return False

    # -- 查询 --------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "interruptions": self.interruptions,
            "records": [
                {"fragment_id": r.fragment_id, "state": r.state.value, "note": r.note}
                for r in self.records
            ],
            "confirmed": [
                r.fragment_id
                for r in self.records
                if r.state == PlaybackState.CONFIRMED
            ],
            "unknown": [
                r.fragment_id for r in self.records if r.state == PlaybackState.UNKNOWN
            ],
        }

    def _emit_playback(self, rec: PlaybackRecord, note: str) -> None:
        # request_id / run_id / media_session_id 由绑定的 emit 注入，避免重复传参
        self.emit(
            "voice.playback",
            fragment_id=rec.fragment_id,
            playback_state=rec.state.value,
            note=note,
        )


def make_observer(session: VoiceSession):
    """挂到 `PipelineTask.add_observer()`。Pipecat 未安装时返回 None。"""
    try:
        from pipecat.observers.base_observer import BaseObserver, FramePushed
    except Exception:
        return None

    class LoomriseVoiceObserver(BaseObserver):
        async def on_push_frame(self, data: "FramePushed") -> None:
            session.on_frame(data.frame)

    return LoomriseVoiceObserver()


class FakeFrame:
    """测试用：按 Pipecat 帧类名构造，无需安装 Pipecat 即可回归播放状态机。"""

    def __init__(self, name: str, **attrs: Any) -> None:
        self.__class__ = type(name, (FakeFrame,), {})
        for k, v in attrs.items():
            setattr(self, k, v)


def simulate_session(
    session: VoiceSession,
    frames: list[str],
    *,
    ack_all: bool = True,
) -> dict[str, Any]:
    """用帧类名序列驱动一次媒体会话（无音频设备也能回归）。"""
    for name in frames:
        session.on_frame(FakeFrame(name, text="（合成语音）"))
    if ack_all:
        for rec in session.records:
            if rec.state == PlaybackState.SENT:
                session.ack_playback(rec.fragment_id)
    return session.snapshot()


__all__ = ["VoiceSession", "PlaybackRecord", "make_observer", "simulate_session", "FakeFrame"]
