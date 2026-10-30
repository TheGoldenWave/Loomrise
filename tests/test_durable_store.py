# -*- coding: utf-8 -*-
"""结构化存储自检：原子提交、幂等绑定、事件链、outbox。

不触网、不依赖模型：只验存储层承诺（矩阵 `M-A-01`、`M-A-03`、`M-A-16`）。
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loomrise.contracts import (  # noqa: E402
    Channel,
    Run,
    RunEvent,
    RunStatus,
    ServiceRequest,
    new_id,
)
from loomrise.contracts import GENESIS_HASH  # noqa: E402
from loomrise.durable_adapter import action_key  # noqa: E402
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore  # noqa: E402


def make_request(state: str = "queued") -> ServiceRequest:
    from loomrise.contracts import RequestState

    return ServiceRequest(
        request_id=new_id("req"),
        tenant_id="tenant_demo",
        agent_version="av_test",
        channel=Channel.TEXT,
        state=RequestState(state),
    )


def make_run(req: ServiceRequest, *, owner: str = "p1", generation: int = 1) -> Run:
    return Run(
        run_id=new_id("run"),
        request_id=req.request_id,
        tenant_id="tenant_demo",
        agent_version="av_test",
        owner_id=owner,
        occupancy_generation=generation,
    )


def make_event(run: Run, seq: int, etype: str, prev: str = "", **payload) -> RunEvent:
    return RunEvent(
        seq=seq,
        event_type=etype,
        request_id=run.request_id,
        run_id=run.run_id,
        tenant_id=run.tenant_id,
        agent_version=run.agent_version,
        channel="text",
        payload=payload,
    ).seal(prev)


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "loomrise.db")
        self.store = SqliteStore(self.path, owner_id="p1")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def new_run(self, **kw) -> tuple[ServiceRequest, Run]:
        req = make_request()
        run = make_run(req, **kw)
        self.store.begin_run(req, run, [])
        return req, run


class TestSchema(StoreCase):
    def test_migration_from_empty(self) -> None:
        row = self.store._conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'",
        ).fetchone()
        self.assertEqual(int(row["value"]), SCHEMA_VERSION)
        names = {
            r["name"] for r in self.store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            ).fetchall()
        }
        # 五张表都得在：只有事件表不够（M-A-16 明确"不是仅事件文件落盘"）
        self.assertTrue(
            {"requests", "runs", "events", "idempotency", "outbox"} <= names, names,
        )

    def test_v10_database_migrates_to_uploaded_knowledge_content(self) -> None:
        path = os.path.join(self.tmp.name, "legacy-v10.db")
        legacy = SqliteStore(path, owner_id="legacy")
        source = legacy.create_knowledge_source(
            tenant_id="tenant_demo", agent_id="expert-a", source_id="source-old",
            kind="faq", locator="FAQ 内容", display_name="FAQ", authorization="owned",
        )
        legacy.close()
        with sqlite3.connect(path) as connection:
            connection.execute("ALTER TABLE knowledge_sources DROP COLUMN uploaded_content")
            connection.execute("UPDATE meta SET value='10' WHERE key='schema_version'")

        migrated = SqliteStore(path, owner_id="migrated")
        try:
            columns = {
                row[1] for row in migrated._conn.execute("PRAGMA table_info(knowledge_sources)")
            }
            self.assertIn("uploaded_content", columns)
            restored = migrated.knowledge_source(
                tenant_id="tenant_demo", agent_id="expert-a", source_id=source["source_id"],
            )
            self.assertEqual(restored["locator"], "FAQ 内容")
            self.assertNotIn("uploaded_content", restored)
            self.assertEqual(int(migrated._conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'",
            ).fetchone()[0]), SCHEMA_VERSION)
        finally:
            migrated.close()

    def test_v9_material_metadata_is_snapshotted_during_v10_migration(self) -> None:
        path = os.path.join(self.tmp.name, "legacy-material.db")
        legacy = SqliteStore(path, owner_id="legacy")
        saved = legacy.save_material(
            tenant_id="tenant_demo", agent_id="expert-a", asset_id="asset-1",
            version_id="version-1", display_name="Legacy guide", filename="guide.txt",
            media_type="text/plain", authorization="licensed",
            expires_at="2099-01-01T00:00:00+00:00", content=b"guide",
        )
        legacy.close()
        with sqlite3.connect(path) as connection:
            connection.execute("ALTER TABLE material_versions RENAME TO material_versions_v10")
            connection.execute(
                "CREATE TABLE material_versions (version_id TEXT PRIMARY KEY,"
                "asset_id TEXT NOT NULL REFERENCES material_assets(asset_id),"
                "version INTEGER NOT NULL,content_hash TEXT NOT NULL,content BLOB NOT NULL,"
                "created_at TEXT NOT NULL,UNIQUE(asset_id,version))",
            )
            connection.execute(
                "INSERT INTO material_versions SELECT version_id,asset_id,version,content_hash,content,created_at "
                "FROM material_versions_v10",
            )
            connection.execute("DROP TABLE material_versions_v10")
            connection.execute("UPDATE meta SET value='9' WHERE key='schema_version'")

        migrated = SqliteStore(path, owner_id="migrated")
        try:
            result = migrated.material_version(
                tenant_id="tenant_demo", agent_id="expert-a", asset_id=saved["asset_id"],
            )
            self.assertEqual(result["version_display_name"], "Legacy guide")
            self.assertEqual(result["version_authorization"], "licensed")
            self.assertEqual(result["version_expires_at"], "2099-01-01T00:00:00+00:00")
            self.assertEqual(
                migrated._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()[0],
                str(SCHEMA_VERSION),
            )
        finally:
            migrated.close()

    def test_store_is_not_jsonl(self) -> None:
        req, _ = self.new_run()
        self.assertEqual(os.path.basename(self.path), "loomrise.db")
        self.assertIsNotNone(
            self.store._conn.execute("SELECT 1 FROM requests WHERE request_id=?",
                                     (req.request_id,)).fetchone(),
        )

    def test_online_backup_reopens_with_records_and_valid_event_chain(self) -> None:
        req, run = self.new_run()
        event = make_event(run, 0, "run.started")
        self.store.append_events([event])
        backup_path = os.path.join(self.tmp.name, "backup.db")

        self.store.backup_to(backup_path)
        backup = SqliteStore(backup_path, owner_id="backup-check")
        try:
            self.assertIsNotNone(backup.request_row(req.request_id))
            self.assertIsNotNone(backup.run_row(run.run_id))
            self.assertEqual(len(backup.load_events(run.run_id)), 1)
            self.assertTrue(backup.verify_chain(run.run_id))
        finally:
            backup.close()

    def test_backup_rejects_live_database_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "differ from the live database"):
            self.store.backup_to(self.path)

    def test_backup_does_not_overwrite_existing_file(self) -> None:
        backup_path = os.path.join(self.tmp.name, "existing-backup.db")
        with open(backup_path, "wb") as handle:
            handle.write(b"preserve me")

        with self.assertRaisesRegex(FileExistsError, "already exists"):
            self.store.backup_to(backup_path)
        with open(backup_path, "rb") as handle:
            self.assertEqual(handle.read(), b"preserve me")


class TestAtomicCommit(StoreCase):
    def test_partial_commit_is_rolled_back(self) -> None:
        """提交前故障：请求/运行/事件都不该留下，不能只留一半。"""
        req = make_request()
        run = make_run(req)
        evt = make_event(run, 0, "run.started")

        def boom() -> None:
            raise RuntimeError("模拟提交前崩溃")

        self.store.before_commit = boom
        with self.assertRaises(RuntimeError):
            self.store.begin_run(req, run, [evt])
        self.store.before_commit = None

        for table in ("requests", "runs", "events"):
            n = self.store._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            self.assertEqual(n, 0, f"{table} 留下了半提交数据")

    def test_event_hash_chain_verifies(self) -> None:
        _, run = self.new_run()
        e0 = make_event(run, 0, "run.started")
        self.store.append_events([e0])
        e1 = make_event(run, 1, "request.routed", e0.hash, skill_id="faq")
        self.store.append_events([e1])
        self.assertTrue(self.store.verify_chain())
        self.assertEqual([e.event_type for e in self.store.load_events(run.run_id)],
                         ["run.started", "request.routed"])

    def test_store_owns_the_persisted_chain(self) -> None:
        """落库链按**运行**封链，不采信调用方给的 prev_hash。

        内存账本是进程内一条链，重启后从 GENESIS 重新开始；若照抄它的 prev_hash，
        库里的链必然断。链尾是存储层的事实。
        """
        _, run = self.new_run()
        e0 = make_event(run, 0, "run.started", "f" * 64)  # 故意给错的前驱
        self.store.append_events([e0])
        self.assertEqual(e0.prev_hash, GENESIS_HASH)
        self.assertTrue(self.store.verify_chain(run.run_id))

    def test_tampered_event_fails_verification(self) -> None:
        _, run = self.new_run()
        e0 = make_event(run, 0, "run.started")
        self.store.append_events([e0])
        self.assertTrue(self.store.verify_chain())
        # event_json 是哈希的输入；payload_json 只是给 SQL 查询用的派生列。
        self.store._conn.execute(
            "UPDATE events SET event_json=REPLACE(event_json, 'run.started', 'run.poked')"
            " WHERE run_id=?",
            (run.run_id,),
        )
        self.assertFalse(self.store.verify_chain(), "改过内容还能验过，等于没校验")


class TestWriteCommit(StoreCase):
    def test_same_action_key_writes_once(self) -> None:
        _, run = self.new_run()
        key = action_key("create_booking", "k1")
        e0 = make_event(run, 0, "tool.outcome", "", tool="create_booking",
                        outcome="success", result_id="res_1", idempotency_key="k1")
        created, rid = self.store.commit_write(
            run.run_id, key=key, bare_key="k1", action="create_booking",
            result_id="res_1", event=e0,
        )
        self.assertTrue(created)
        self.assertEqual(rid, "res_1")

        e1 = make_event(run, 1, "tool.outcome", e0.hash, tool="create_booking",
                        outcome="success", result_id="res_2")
        created2, rid2 = self.store.commit_write(
            run.run_id, key=key, bare_key="k1", action="create_booking",
            result_id="res_2", event=e1,
        )
        # 第二次不产生新副作用，且必须把原来的 result_id 交回去
        self.assertFalse(created2)
        self.assertEqual(rid2, "res_1")
        n = self.store._conn.execute("SELECT COUNT(*) AS n FROM idempotency").fetchone()["n"]
        self.assertEqual(n, 1)

    def test_same_bare_key_on_different_action_is_distinct(self) -> None:
        """M-A-06：键绑定具体业务操作，不是绑请求。"""
        _, run = self.new_run()
        e0 = make_event(run, 0, "tool.outcome", "", tool="create_booking",
                        outcome="success", result_id="res_1")
        # 先落第一条再建第二条：存储层会给未封链的事件补链尾，
        # 提前用 e0.hash 造 e1 会拿到补链之前的旧哈希。
        e1 = None
        self.store.commit_write(run.run_id, key=action_key("create_booking", "k1"),
                                bare_key="k1", action="create_booking",
                                result_id="res_1", event=e0)
        e1 = make_event(run, 1, "tool.outcome", e0.hash, tool="refund",
                        outcome="success", result_id="res_2")
        created, rid = self.store.commit_write(
            run.run_id, key=action_key("refund", "k1"), bare_key="k1", action="refund",
            result_id="res_2", event=e1,
        )
        self.assertTrue(created)
        self.assertEqual(rid, "res_2")

    def test_write_emits_outbox_intent(self) -> None:
        _, run = self.new_run()
        e0 = make_event(run, 0, "tool.outcome", "", tool="create_booking",
                        outcome="success", result_id="res_1")
        self.store.commit_write(run.run_id, key=action_key("create_booking", "k1"),
                                bare_key="k1", action="create_booking",
                                result_id="res_1", event=e0)
        e1 = make_event(run, 1, "tool.outcome", e0.hash, tool="refund",
                        outcome="success", result_id="res_2")
        pending = self.store.pending_outbox()
        self.assertEqual(len(pending), 1)
        self.store.mark_outbox(pending[0]["id"])
        self.assertEqual(self.store.pending_outbox(), [])

    def test_finished_run_rejects_late_write(self) -> None:
        """旧代迟到写入必须被拒，不能靠调用方自觉（M-A-21 的 R1 部分）。"""
        req, run = self.new_run()
        e0 = make_event(run, 0, "run.finished", "", request_state="success")
        self.store.finish_run(run.run_id, status="succeeded",
                              request_state="success", event=e0)
        late = make_event(run, 1, "tool.outcome", e0.hash, tool="create_booking",
                          outcome="success", result_id="res_late")
        with self.assertRaises(RuntimeError):
            self.store.commit_write(run.run_id, key=action_key("create_booking", "k9"),
                                    bare_key="k9", action="create_booking",
                                    result_id="res_late", event=late)

    def test_finish_updates_request_and_run_together(self) -> None:
        req, run = self.new_run()
        e0 = make_event(run, 0, "run.finished", "", request_state="success")
        self.store.finish_run(run.run_id, status="succeeded",
                              request_state="success", event=e0, result_id="res_1")
        row = self.store.run_row(run.run_id)
        self.assertEqual(row["status"], "succeeded")
        req_row = self.store._conn.execute(
            "SELECT state, result_id FROM requests WHERE request_id=?", (req.request_id,),
        ).fetchone()
        self.assertEqual(req_row["state"], "success")
        self.assertEqual(req_row["result_id"], "res_1")


class TestRecover(StoreCase):
    def test_orphan_running_is_interrupted_not_resumed(self) -> None:
        req, run = self.new_run(owner="p1")
        e0 = make_event(run, 0, "run.started", "")
        self.store.append_events([e0])

        # 换一个 owner 打开同一个库，等价于进程重启
        other = SqliteStore(self.path, owner_id="p2")
        try:
            report = other.recover(owner_id="p2")
            self.assertEqual(report.interrupted, [run.run_id])
            self.assertEqual(report.adopted, [])
            row = other.run_row(run.run_id)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["finish_reason"], "restart_interrupted")
            types = [e.event_type for e in other.load_events(run.run_id)]
            self.assertEqual(types[-1], "run.interrupted")
            self.assertTrue(other.verify_chain(), "恢复写的中断事件破坏了哈希链")
        finally:
            other.close()

    def test_recover_is_idempotent(self) -> None:
        self.new_run(owner="p1")
        other = SqliteStore(self.path, owner_id="p2")
        try:
            first = other.recover(owner_id="p2")
            second = other.recover(owner_id="p2")
            self.assertEqual(len(first.interrupted), 1)
            self.assertEqual(second.interrupted, [], "同一中断不该被判两次")
        finally:
            other.close()

    def test_adopted_run_keeps_running(self) -> None:
        req, run = self.new_run(owner="p1")
        report = self.store.recover(owner_id="p1")
        self.assertEqual(report.adopted, [run.run_id])
        self.assertEqual(self.store.run_row(run.run_id)["status"], "running")

    def test_idempotent_index_survives_restart(self) -> None:
        req, run = self.new_run()
        e0 = make_event(run, 0, "tool.outcome", "", tool="create_booking",
                        outcome="success", result_id="res_1")
        self.store.commit_write(run.run_id, key=action_key("create_booking", "k1"),
                                bare_key="k1", action="create_booking",
                                result_id="res_1", event=e0)
        e1 = make_event(run, 1, "tool.outcome", e0.hash, tool="refund",
                        outcome="success", result_id="res_2")
        e1 = make_event(run, 1, "run.finished", e0.hash, request_state="success")
        self.store.finish_run(run.run_id, status="succeeded",
                              request_state="success", event=e1)

        other = SqliteStore(self.path, owner_id="p2")
        try:
            report = other.recover(owner_id="p2")
            # 裸键索引：规则层拿到的就是模型传来的那个键
            self.assertEqual(report.idempotent_keys.get("k1"), "res_1")
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
