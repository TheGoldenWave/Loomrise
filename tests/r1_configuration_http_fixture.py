"""Run a disposable loopback configuration service for browser acceptance."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile

from aiohttp import web

from loomrise.config_http import create_configuration_http_app
from loomrise.configuration import ConfigurationService
from loomrise.durable_store import SqliteStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--allowed-origin", action="append")
    args = parser.parse_args()

    if args.data_dir:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        context = nullcontext(str(args.data_dir))
    else:
        context = tempfile.TemporaryDirectory(prefix="loomrise-r1-config-")
    with context as directory:
        root = Path(directory)
        principal_path = root / "principal.json"
        principal_path.write_text(json.dumps({
            "tenant_id": "r1-browser-test-tenant",
            "actor_id": "r1-browser-test-owner",
            "role": "owner",
            "agent_ids": ["course-demo"],
        }), encoding="utf-8")
        os.chmod(principal_path, 0o600)

        database_path = root / "configuration.db"
        store = SqliteStore(str(database_path))
        service = ConfigurationService(store)
        config = {
            "persona": {
                "name": "课程咨询客服",
                "goal": "依据授权资料回答课程问题。",
                "audience": "网站访客",
                "greeting": "你好，有什么可以帮你？",
                "scope": "仅回答有效授权资料中的信息。",
                "fallback": "资料不足时转交人工。",
                "fields": {},
                "entry_unit_ids": [],
            },
            "units": [],
            "g0_gates": [],
            "hard_rules": [],
            "task_blueprints": [],
            "legacy_local_fields": {
                "tone": "中性",
                "knowledge_source_count": 3,
            },
        }
        service.register_stable_version(
            tenant_id="r1-browser-test-tenant", agent_id="course-demo",
            version_id="r1-fixture-v1", config=config,
        )
        service.create_draft_from_stable(
            tenant_id="r1-browser-test-tenant", agent_id="course-demo",
            base_version_id="r1-fixture-v1",
        )
        store.close()

        app = create_configuration_http_app(
            principal_path=principal_path, database_path=database_path,
            allowed_origins=args.allowed_origin,
        )
        print(f"R1 fixture data: {root}", flush=True)
        print(f"R1 fixture principal: {principal_path}", flush=True)
        print(f"R1 fixture database: {database_path}", flush=True)
        web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
