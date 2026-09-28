"""Build and hash a platform-specific, fully offline core wheelhouse."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "_reference" / "agentscope"
WHEELS = ROOT / ".build" / "offline" / "wheels"
LOCK = ROOT / "requirements-offline-macos-arm64-py313.txt"
PIN = "a38821287f35e9e45ed193d9d864cb46f263c946"


def main() -> None:
    import platform
    if (sys.version_info[:2], sys.platform, platform.machine()) != ((3, 13), "darwin", "arm64"):
        raise SystemExit("This lock targets macOS arm64 / Python 3.13 only")
    actual = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if actual != PIN:
        raise SystemExit("Reference AgentScope commit differs from requirements.txt")
    direct = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    pin_line = next((line for line in direct if line.startswith("agentscope @")), None)
    if pin_line is None or PIN not in pin_line:
        raise SystemExit("AgentScope VCS pin missing or changed")
    args = [str(SOURCE) if line == pin_line else line for line in direct]
    WHEELS.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--wheel-dir", str(WHEELS), *args], check=True)
    entries = {}
    for wheel in WHEELS.glob("*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            metadata_path = next((n for n in archive.namelist() if n.endswith(".dist-info/METADATA")), None)
            if not metadata_path:
                raise SystemExit(f"Missing wheel metadata: {wheel.name}")
            meta = BytesParser().parsebytes(archive.read(metadata_path))
        name, version = meta["Name"], meta["Version"]
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in entries:
            raise SystemExit(f"Multiple wheels for {normalized}; 手动删除 {WHEELS} 后重建")
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        entries[normalized] = f"{name}=={version} --hash=sha256:{digest}"
    if "agentscope" not in entries:
        raise SystemExit("AgentScope wheel missing")
    LOCK.write_text(
        "# macOS arm64 / CPython 3.13\n"
        f"# agentscope built from: {pin_line}\n"
        + "# Loomrise 核心依赖的传递依赖一并入锁；语音依赖见 voice-requirements.txt\n"
        + "# Install: pip install --no-index --find-links=.build/offline/wheels --require-hashes -r requirements-offline-macos-arm64-py313.txt\n"
        + "--only-binary=:all:\n" + "\n".join(entries[k] for k in sorted(entries)) + "\n",
        encoding="utf-8",
    )
    print(f"Locked {len(entries)} wheels with SHA-256: {LOCK}")


if __name__ == "__main__":
    main()
