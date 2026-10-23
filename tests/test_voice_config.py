# -*- coding: utf-8 -*-
"""语音凭据存储自检：不依赖 pytest，直接 `python tests/test_voice_config.py`。

每条断言对应一条凭据纪律，失败即纪律被破坏。全部使用临时目录，不触碰真实凭据。
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loomrise import voice_config as vc  # noqa: E402

WS = "llm-aaaaaaaaaaaaaaaa"  # 虚构 workspace：真实 ID 属账号标识，不入仓库


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="voice-cfg-")) / "aliyun-voice.json"


def test_roundtrip_and_permissions() -> None:
    path = _tmp()
    saved = vc.save_config(WS, "sk-test-123", path=path)
    assert saved["asr_model"] == vc.DEFAULT_ASR_MODEL
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)
    parent = stat.S_IMODE(path.parent.stat().st_mode)
    assert parent == 0o700, oct(parent)
    loaded = vc.load_config(path)
    assert loaded is not None and loaded["workspace"] == WS and loaded["api_key"] == "sk-test-123"
    print("  ok   凭据落盘 600、目录 700、可回读")


def test_no_overwrite() -> None:
    path = _tmp()
    vc.save_config(WS, "sk-first", path=path)
    try:
        vc.save_config(WS, "sk-second", path=path)
    except FileExistsError:
        print("  ok   已有凭据不被静默覆盖")
    else:
        raise AssertionError("第二次写入本应失败")
    assert vc.load_config(path)["api_key"] == "sk-first"


def test_refuse_symlink() -> None:
    target = _tmp()
    vc.save_config(WS, "sk-real", path=target)
    link = target.parent / "link.json"
    os.symlink(target, link)
    try:
        vc.save_config(WS, "sk-evil", path=link)
    except ValueError:
        print("  ok   拒绝通过符号链接写入")
    else:
        raise AssertionError("符号链接应被拒绝")
    assert vc.load_config(target)["api_key"] == "sk-real"


def test_reject_loose_permissions() -> None:
    path = _tmp()
    vc.save_config(WS, "sk-perm", path=path)
    os.chmod(path, 0o644)
    try:
        vc.load_config(path)
    except RuntimeError:
        print("  ok   非 600 的凭据文件被拒绝读取")
    else:
        raise AssertionError("0644 应被拒绝")


def test_reject_bad_fields() -> None:
    path = _tmp()
    for kwargs in (
        {"workspace": "no/slash", "api_key": "sk-x"},
        {"workspace": WS, "api_key": "  "},
        {"workspace": WS, "api_key": "sk-x", "tts_voice": "bad voice"},
    ):
        try:
            vc.save_config(path=path, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝：{kwargs}")
    assert not path.exists()
    print("  ok   畸形 workspace / 空 key / 含空格值均被拒绝")


def test_endpoints() -> None:
    ends = vc.endpoints(WS)
    assert ends["base_http"] == f"https://{WS}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert ends["dashscope_ws"] == f"wss://{WS}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    assert ends["dashscope_http"].endswith("/api/v1")
    try:
        vc.endpoints("bad workspace")
    except ValueError:
        print("  ok   端点由 workspace 推导，畸形输入被拒绝")
    else:
        raise AssertionError("畸形 workspace 应被拒绝")


def test_env_wins_and_absent_returns_none() -> None:
    path = _tmp()
    vc.save_config(WS, "sk-file", path=path)
    data = vc.load_config(path)
    old = os.environ.pop(vc.ENV_KEY, None)
    try:
        assert vc.resolve_api_key(data) == "sk-file"
        os.environ[vc.ENV_KEY] = "sk-env"
        assert vc.resolve_api_key(data) == "sk-env", "环境变量应优先"
        os.environ.pop(vc.ENV_KEY)
        # 把默认路径指到不存在的临时文件：这条断言验的是"没有就可能返回 None"，
        # 不能因为开发机上恰好存过真实凭据而通过或失败。
        with patch.object(vc, "CONFIG_PATH", _tmp()):
            assert vc.resolve_api_key(None) is None, "目录下无文件时应返回 None 而不是编造"
    finally:
        os.environ.pop(vc.ENV_KEY, None)
        if old is not None:
            os.environ[vc.ENV_KEY] = old
    print("  ok   环境变量优先；都没有时返回 None（不静默回退）")


def test_no_key_in_export_dirs() -> None:
    """凭据文件必须在仓库外：默认路径的父目录不能落在项目根之下。"""
    assert ROOT not in vc.CONFIG_PATH.parents, vc.CONFIG_PATH
    print("  ok   默认凭据路径在仓库之外")


def test_json_is_plain() -> None:
    path = _tmp()
    vc.save_config(WS, "sk-json", path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"workspace", "api_key", "asr_model", "tts_model", "tts_voice"}
    print("  ok   落盘字段固定，无多余项")


def main() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {fn.__name__}: {type(exc).__name__}: {exc}")
    print("全部通过" if not failed else f"{failed} 项失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
