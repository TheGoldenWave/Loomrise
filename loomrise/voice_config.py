"""Local-only Aliyun voice credential and endpoint config.

与 `local_config.py` 同一套纪律：文件放仓库外、仅所有者可读、不覆盖已有密钥、
不跟随符号链接。区别只有两处——**另一家供应商、另一个用途**，所以另存一个文件：
混在 `coding-plan.json` 里会让"轮换一个 key"变成"重写整个模型配置"。

语音端点由 Workspace 推导，不单独存 URL：手写 URL 是拼错域名最常见的来源。
"""

from __future__ import annotations

import getpass
import json
import os
import re
from pathlib import Path

# 放在仓库外：仓库里的文件再怎么 .gitignore，都挡不住 git add -f 或误提交。
CONFIG_PATH = Path.home() / ".config" / "loomrise" / "aliyun-voice.json"

ENV_KEY = "DASHSCOPE_API_KEY"

# 华北2（北京）专属域名；实时 ASR 族只在该地域提供。
REGION = "cn-beijing"

DEFAULT_ASR_MODEL = "fun-asr-realtime-2026-02-28"
DEFAULT_TTS_MODEL = "qwen-audio-3.0-tts-flash"
DEFAULT_TTS_VOICE = "longanhuan_v3.6"

_WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")


def endpoints(workspace: str) -> dict[str, str]:
    """由 Workspace 推导三个入口。任一处改动都要先改这里，不要在调用点手写 URL。"""
    if not _WORKSPACE_RE.match(workspace):
        raise ValueError("Workspace ID looks malformed")
    host = f"{workspace}.{REGION}.maas.aliyuncs.com"
    return {
        "base_http": f"https://{host}/compatible-mode/v1",  # 对话模型（OpenAI 兼容）
        "dashscope_http": f"https://{host}/api/v1",  # DashScope SDK 的 HTTP 根
        "dashscope_ws": f"wss://{host}/api-ws/v1/inference",  # 流式 ASR / 流式 TTS
    }


def _validate(data: dict[str, str]) -> None:
    if not _WORKSPACE_RE.match(data.get("workspace", "")):
        raise ValueError("workspace is required and must look like a Model Studio workspace id")
    key = data.get("api_key", "")
    if not key.strip() or any(ch.isspace() for ch in key):
        raise ValueError("api_key is required and must not contain whitespace")
    for field in ("asr_model", "tts_model", "tts_voice"):
        value = data.get(field, "")
        if not value or any(ch.isspace() for ch in value):
            raise ValueError(f"{field} is required and must not contain whitespace")


def save_config(
    workspace: str,
    api_key: str,
    *,
    asr_model: str = DEFAULT_ASR_MODEL,
    tts_model: str = DEFAULT_TTS_MODEL,
    tts_voice: str = DEFAULT_TTS_VOICE,
    path: Path = CONFIG_PATH,
) -> dict[str, str]:
    data = {
        "workspace": workspace.strip(),
        "api_key": api_key.strip(),
        "asr_model": asr_model.strip(),
        "tts_model": tts_model.strip(),
        "tts_voice": tts_voice.strip(),
    }
    _validate(data)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing to write credential through a symlink")
    # O_EXCL：已存在就失败，绝不覆盖。改 key 请先手动删文件，留下一次意图。
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return data


def load_config(path: Path | None = None) -> dict[str, str] | None:
    # 默认值取运行时模块属性，不写成定义期绑定：否则测试无法把路径换到临时目录，
    # 断言"没有文件就返回 None"会意外依赖开发机上是否真的存过凭据。
    path = path or CONFIG_PATH
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("Voice credential must be a regular file readable only by its owner (chmod 600)")
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(data)
    return data


def resolve_api_key(data: dict[str, str] | None = None) -> str | None:
    """环境变量优先：容器与 CI 里不落盘；本地开发用配置文件。

    两者都没有时返回 None，由调用方**显式失败**——不允许静默回退到脚本或浏览器识别。
    """
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env
    if data is None:
        data = load_config()
    return data["api_key"] if data else None


def configure() -> None:
    workspace = input("Model Studio workspace id: ").strip()
    asr_model = input(f"ASR model [{DEFAULT_ASR_MODEL}]: ").strip() or DEFAULT_ASR_MODEL
    tts_model = input(f"TTS model [{DEFAULT_TTS_MODEL}]: ").strip() or DEFAULT_TTS_MODEL
    tts_voice = input(f"TTS voice [{DEFAULT_TTS_VOICE}]: ").strip() or DEFAULT_TTS_VOICE
    api_key = getpass.getpass("DashScope API key (hidden): ")
    data = save_config(workspace, api_key, asr_model=asr_model, tts_model=tts_model, tts_voice=tts_voice)
    ends = endpoints(data["workspace"])
    print(f"Credential stored at {CONFIG_PATH} (owner-only); no key was printed.")
    print(f"  ASR  {data['asr_model']}")
    print(f"  TTS  {data['tts_model']} / {data['tts_voice']}")
    print(f"  WS   {ends['dashscope_ws']}")
