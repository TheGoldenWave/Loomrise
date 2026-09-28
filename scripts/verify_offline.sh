#!/usr/bin/env bash
# S1 离线依赖验收（macOS arm64 / CPython 3.13）：
#   构建 wheelhouse → 干净环境离线安装（--no-index + --require-hashes）→ 回放与自检
#   → 导出带 wheelhouse 的交付包 → 另一个干净环境离线恢复并回放
# 用法： bash scripts/verify_offline.sh [工作目录，默认 /tmp/loomrise-offline-verify]
set -euo pipefail

PY="${PYTHON:-python3}"
WORK="${1:-/tmp/loomrise-offline-$(date +%Y%m%d-%H%M%S)}"  # 每次新目录，避免删旧产物
cd "$(dirname "$0")/.."
LOCK="requirements-offline-macos-arm64-py313.txt"
WHEELS=".build/offline/wheels"

rm -rf "$WORK"
mkdir -p "$WORK"
"$PY" scripts/build_offline.py

"$PY" -m venv "$WORK/core"
"$WORK/core/bin/pip" install --no-index --find-links="$WHEELS" --require-hashes -r "$LOCK"
"$WORK/core/bin/pip" check
"$WORK/core/bin/pip" freeze | sort > "$WORK/core-freeze.txt"
PYTHONPATH=. "$WORK/core/bin/python" -m loomrise.cli replay --out "$WORK/replay-core.json"
PYTHONPATH=. "$WORK/core/bin/python" tests/test_s1.py

"$WORK/core/bin/python" -m loomrise.cli export --offline --out "$WORK/export"
"$PY" -m venv "$WORK/restore"
"$WORK/restore/bin/pip" install --no-index --find-links="$WORK/export/wheels" \
  --require-hashes -r "$WORK/export/$LOCK"
"$WORK/restore/bin/pip" check
cd "$WORK/export"
"$WORK/restore/bin/python" -m loomrise.cli replay --out "$WORK/replay-restore.json"

echo "离线验收完成：核心回放 → $WORK/replay-core.json；导出恢复回放 → $WORK/replay-restore.json"
