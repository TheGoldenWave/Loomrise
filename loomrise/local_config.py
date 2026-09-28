"""Local-only Coding Plan credential, never included in scenario exports."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

# 放在仓库外：仓库里的文件再怎么 .gitignore，都挡不住 git add -f 或误提交。
CONFIG_PATH = Path.home() / ".config" / "loomrise" / "coding-plan.json"


def _validate(base_url: str, model: str, key: str) -> None:
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Base URL must be an HTTPS API root without credentials or query parameters")
    if not model or any(ch.isspace() for ch in model) or not key.strip():
        raise ValueError("Model and key are required")


def save_config(base_url: str, model: str, key: str, *, path: Path = CONFIG_PATH) -> None:
    _validate(base_url, model, key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Refusing to write credential through a symlink")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"base_url": base_url.rstrip("/"), "model": model, "key": key.strip()}, out)
            out.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load_config(path: Path = CONFIG_PATH) -> dict[str, str] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("Coding Plan credential must be a regular file readable only by its owner (chmod 600)")
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate(data["base_url"], data["model"], data["key"])
    return data


def configure() -> None:
    base_url = input("Coding Plan API root (HTTPS, ending in /v1): ").strip()
    model = input("Model [gpt-6-luna]: ").strip() or "gpt-6-luna"
    key = getpass.getpass("Coding Plan key (hidden): ")
    save_config(base_url, model, key)
    print(f"Credential stored at {CONFIG_PATH} (owner-only); no key was printed.")
