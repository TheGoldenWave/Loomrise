# -*- coding: utf-8 -*-
"""结构化持久化：请求 / 运行 / 事件 / 幂等 / outbox 同一个事务边界。

三条纪律（对应 `ARCHITECTURE` 的「提交后可见」与矩阵 `M-A-01`、`M-A-03`、`M-A-16`）：

1. **JSONL 不是账本**。事件先落本库，JSONL 只是导出与短时回放。
2. **提交点原子**：运行开始、业务写入、运行收尾各自是一个事务；请求状态、运行状态、
   幂等记录、outbox 意图与事件行要么一起可读，要么都不可读。
3. **单写者**：进程内 `RLock` + `BEGIN IMMEDIATE`。多进程安全不在本层承诺，
   由 R5a 的云阶段另验（`ARCHITECTURE` 选型约束）。
"""

from __future__ import annotations

import json
import hashlib
import os
import uuid
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .contracts import (
    GENESIS_HASH, Channel, RequestState, Run, RunAdmission, RunEvent, RunStatus,
    ServiceRequest, now_iso,
)

SCHEMA_VERSION = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
  request_id     TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL,
  agent_version  TEXT NOT NULL,
  channel        TEXT NOT NULL,
  state          TEXT NOT NULL,
  subject_id     TEXT,
  subject_scope  TEXT,
  trigger_kind   TEXT,
  trigger_ref    TEXT,
  result_id      TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id                TEXT PRIMARY KEY,
  request_id            TEXT NOT NULL,
  tenant_id             TEXT NOT NULL,
  agent_version         TEXT NOT NULL,
  status                TEXT NOT NULL,
  occupancy_generation  INTEGER NOT NULL,
  owner_id              TEXT NOT NULL,
  attempt_id            TEXT,
  lineage_parent        TEXT,
  started_at            TEXT NOT NULL,
  ended_at              TEXT,
  finish_reason         TEXT,
  snapshot_json         TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (request_id) REFERENCES requests(request_id)
);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS events (
  rid            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id         TEXT NOT NULL,
  seq            INTEGER NOT NULL,
  request_id     TEXT NOT NULL,
  event_type     TEXT NOT NULL,
  ts             TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  prev_hash      TEXT NOT NULL,
  hash           TEXT NOT NULL,
  event_json     TEXT NOT NULL,
  UNIQUE (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
CREATE TABLE IF NOT EXISTS idempotency (
  key        TEXT PRIMARY KEY,
  bare_key   TEXT NOT NULL,
  run_id     TEXT NOT NULL,
  action     TEXT NOT NULL,
  result_id  TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idem_bare ON idempotency(bare_key);
CREATE TABLE IF NOT EXISTS tool_attempts (
  attempt_key  TEXT PRIMARY KEY,
  run_id       TEXT NOT NULL,
  action       TEXT NOT NULL,
  args_hash    TEXT NOT NULL,
  state        TEXT NOT NULL,
  result_id    TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_tool_attempts_run ON tool_attempts(run_id, state);
CREATE TABLE IF NOT EXISTS outbox (
  id            TEXT PRIMARY KEY,
  run_id        TEXT NOT NULL,
  kind          TEXT NOT NULL,
  payload_json  TEXT NOT NULL,
  state         TEXT NOT NULL,
  attempts      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  delivered_at  TEXT
);
CREATE TABLE IF NOT EXISTS task_items (
  task_id              TEXT PRIMARY KEY,
  tenant_id            TEXT NOT NULL,
  agent_id             TEXT NOT NULL,
  subject_id           TEXT NOT NULL,
  service_cycle_id     TEXT NOT NULL,
  purpose              TEXT NOT NULL,
  source_agent_version TEXT NOT NULL,
  state                TEXT NOT NULL,
  revision             INTEGER NOT NULL,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_items_recovery
  ON task_items(tenant_id, state, created_at);
CREATE TABLE IF NOT EXISTS event_receipts (
  tenant_id TEXT NOT NULL,
  scenario_pack_id TEXT NOT NULL,
  trigger_kind TEXT NOT NULL,
  trigger_event_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  agent_version TEXT NOT NULL,
  request_id TEXT NOT NULL REFERENCES requests(request_id),
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  accepted_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, scenario_pack_id, trigger_kind, trigger_event_id)
);
CREATE TABLE IF NOT EXISTS event_admission_conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  payload_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS configuration_drafts (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  base_version_id TEXT,
  config_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id)
);
CREATE TABLE IF NOT EXISTS configuration_stable_versions (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  config_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, version_id)
);
CREATE TABLE IF NOT EXISTS change_proposals (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  source_revision INTEGER NOT NULL,
  base_version_id TEXT,
  config_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  diff_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, candidate_id),
  UNIQUE (tenant_id, agent_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS release_approvals (
  tenant_id    TEXT NOT NULL,
  agent_id     TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  environment  TEXT NOT NULL CHECK (environment='sandbox'),
  entry_id     TEXT NOT NULL,
  version_id   TEXT NOT NULL,
  approved_by  TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, candidate_id, content_hash, environment, entry_id, version_id)
);
CREATE TABLE IF NOT EXISTS sandbox_releases (
  release_id   TEXT PRIMARY KEY,
  tenant_id    TEXT NOT NULL,
  agent_id     TEXT NOT NULL,
  environment  TEXT NOT NULL CHECK (environment='sandbox'),
  candidate_id TEXT NOT NULL,
  version_id   TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  config_json  TEXT NOT NULL,
  knowledge_state TEXT NOT NULL DEFAULT 'ready' CHECK (knowledge_state IN ('ready','stale')),
  created_at   TEXT NOT NULL,
  UNIQUE (tenant_id, agent_id, environment, version_id)
);
CREATE TABLE IF NOT EXISTS sandbox_entries (
  tenant_id   TEXT NOT NULL,
  agent_id    TEXT NOT NULL,
  entry_id    TEXT NOT NULL,
  environment TEXT NOT NULL CHECK (environment='sandbox'),
  release_id  TEXT NOT NULL REFERENCES sandbox_releases(release_id),
  version_id  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, entry_id, environment)
);
CREATE INDEX IF NOT EXISTS idx_sandbox_release_candidate
  ON sandbox_releases(tenant_id, agent_id, candidate_id);
CREATE TABLE IF NOT EXISTS knowledge_sources (
  source_id       TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL,
  agent_id        TEXT NOT NULL,
  kind            TEXT NOT NULL CHECK (kind IN ('faq','url','file')),
  locator         TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  authorization   TEXT NOT NULL,
  state           TEXT NOT NULL CHECK (state IN ('queued','processing','ready','failed','revoked')),
  attempt_count   INTEGER NOT NULL DEFAULT 0,
  content_hash    TEXT,
  error_code      TEXT,
  error_message   TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  revoked_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_scope
  ON knowledge_sources(tenant_id,agent_id,state);
CREATE TABLE IF NOT EXISTS knowledge_documents (
  document_id  TEXT PRIMARY KEY,
  source_id    TEXT NOT NULL REFERENCES knowledge_sources(source_id),
  tenant_id    TEXT NOT NULL,
  agent_id     TEXT NOT NULL,
  content      TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_index (
  document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id),
  ordinal     INTEGER NOT NULL,
  text        TEXT NOT NULL,
  PRIMARY KEY(document_id,ordinal)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_index_text ON knowledge_index(text);
CREATE TABLE IF NOT EXISTS material_assets (
  asset_id       TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL,
  agent_id       TEXT NOT NULL,
  display_name   TEXT NOT NULL,
  filename       TEXT NOT NULL,
  media_type     TEXT NOT NULL,
  authorization  TEXT NOT NULL,
  expires_at     TEXT,
  state          TEXT NOT NULL CHECK (state IN ('active','revoked')),
  current_version_id TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_material_assets_scope
  ON material_assets(tenant_id,agent_id,state);
CREATE TABLE IF NOT EXISTS material_versions (
  version_id   TEXT PRIMARY KEY,
  asset_id     TEXT NOT NULL REFERENCES material_assets(asset_id),
  version      INTEGER NOT NULL,
  display_name TEXT NOT NULL,
  filename     TEXT NOT NULL,
  media_type   TEXT NOT NULL,
  authorization TEXT NOT NULL,
  expires_at   TEXT,
  content_hash TEXT NOT NULL,
  content      BLOB NOT NULL,
  created_at   TEXT NOT NULL,
  UNIQUE(asset_id,version)
);
CREATE TABLE IF NOT EXISTS customer_conversations (
  conversation_id TEXT PRIMARY KEY,
  tenant_id       TEXT NOT NULL,
  agent_id        TEXT NOT NULL,
  entry_id        TEXT NOT NULL,
  release_id      TEXT NOT NULL,
  release_version TEXT NOT NULL,
  visitor_token_hash TEXT NOT NULL UNIQUE,
  state           TEXT NOT NULL CHECK (state IN ('bot','human_requested','human')),
  occupancy_generation INTEGER NOT NULL DEFAULT 0,
  assigned_to     TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customer_conversations_inbox
  ON customer_conversations(tenant_id,agent_id,state,updated_at);
CREATE TABLE IF NOT EXISTS customer_messages (
  conversation_id TEXT NOT NULL REFERENCES customer_conversations(conversation_id),
  sequence        INTEGER NOT NULL,
  sender           TEXT NOT NULL CHECK (sender IN ('visitor','assistant','operator')),
  actor_id         TEXT,
  text             TEXT NOT NULL,
  asset_id         TEXT,
  asset_version_id TEXT,
  created_at       TEXT NOT NULL,
  PRIMARY KEY(conversation_id,sequence)
);
"""


@dataclass
class RecoveryReport:
    """启动时的恢复裁决结果。旧代不复活，中断事实必须留下。"""

    interrupted: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    idempotent_keys: dict[str, str] = field(default_factory=dict)
    # 旧 run 与其后继 run 的 lineage，用于证明"新尝试不是复活旧尝试"
    lineages: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interrupted": list(self.interrupted),
            "adopted": list(self.adopted),
            "idempotent_keys": dict(self.idempotent_keys),
            "lineages": dict(self.lineages),
        }


class SqliteStore:
    """单写者结构化存储。`owner_id` 用来判定"这条运行是不是本进程的"。"""

    def __init__(self, path: str, *, owner_id: str = "local") -> None:
        self.path = path
        self.owner_id = owner_id
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        # 测试用：允许在提交前注入故障，验证"不完整提交被拒"。
        # 必须在 migrate 之前就位——迁移也要走同一个事务包装。
        self.before_commit: Any = None
        self.migrate()

    # -- 基础 --------------------------------------------------------------
    def migrate(self) -> None:
        # 不用 executescript：它会先隐式 COMMIT，把迁移踢出事务。
        statements = [st.strip() for st in _SCHEMA.split(";") if st.strip()]
        with self._tx() as cur:
            for stmt in statements:
                cur.execute(stmt)
            row = cur.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            previous_version = int(row["value"]) if row is not None else 0
            if row is None:
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row["value"]) > SCHEMA_VERSION:
                raise RuntimeError(
                    f"store schema {row['value']} 比代码支持的 {SCHEMA_VERSION} 新，拒绝降级打开",
                )
            columns = {r["name"] for r in cur.execute("PRAGMA table_info(requests)")}
            if "trigger_event_id" not in columns:
                cur.execute("ALTER TABLE requests ADD COLUMN trigger_event_id TEXT")
            if "subject_scope" not in columns:
                cur.execute("ALTER TABLE requests ADD COLUMN subject_scope TEXT")
                cur.execute("UPDATE requests SET subject_id=NULL WHERE subject_id IS NOT NULL")
            elif previous_version < 4:
                # Only explicitly mapped identifiers are durable; legacy scope cannot prove that.
                cur.execute(
                    "UPDATE requests SET subject_id=NULL "
                    "WHERE subject_scope IS NULL OR subject_scope<>'mapped'",
                )
            version_columns = {r["name"] for r in cur.execute("PRAGMA table_info(material_versions)")}
            if "display_name" not in version_columns:
                cur.execute("ALTER TABLE material_versions ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
            if "filename" not in version_columns:
                cur.execute("ALTER TABLE material_versions ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
            if "media_type" not in version_columns:
                cur.execute("ALTER TABLE material_versions ADD COLUMN media_type TEXT NOT NULL DEFAULT 'application/octet-stream'")
            if "authorization" not in version_columns:
                cur.execute("ALTER TABLE material_versions ADD COLUMN authorization TEXT NOT NULL DEFAULT 'owned'")
            if "expires_at" not in version_columns:
                cur.execute("ALTER TABLE material_versions ADD COLUMN expires_at TEXT")
            if previous_version < 10:
                cur.execute(
                    "UPDATE material_versions SET "
                    "display_name=COALESCE(NULLIF(display_name,''),(SELECT display_name FROM material_assets WHERE asset_id=material_versions.asset_id)), "
                    "filename=COALESCE(NULLIF(filename,''),(SELECT filename FROM material_assets WHERE asset_id=material_versions.asset_id)), "
                    "media_type=CASE WHEN media_type='application/octet-stream' THEN "
                    "(SELECT media_type FROM material_assets WHERE asset_id=material_versions.asset_id) ELSE media_type END, "
                    "authorization=CASE WHEN authorization='owned' THEN "
                    "(SELECT authorization FROM material_assets WHERE asset_id=material_versions.asset_id) ELSE authorization END, "
                    "expires_at=COALESCE(expires_at,(SELECT expires_at FROM material_assets WHERE asset_id=material_versions.asset_id))"
                )
            cur.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
                if self.before_commit is not None:
                    self.before_commit()
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, path: str) -> None:
        """Create a transactionally consistent SQLite backup at ``path``."""
        if not isinstance(path, str) or not path.strip():
            raise ValueError("backup path must be a non-empty string")
        if os.path.realpath(path) == os.path.realpath(self.path):
            raise ValueError("backup path must differ from the live database")
        if os.path.exists(path):
            raise FileExistsError(f"backup path already exists: {path}")
        with self._lock:
            target = sqlite3.connect(path)
            try:
                self._conn.backup(target)
            finally:
                target.close()

    # -- 运行开始 ----------------------------------------------------------
    def begin_run(self, request: ServiceRequest, run: Run, events: list[RunEvent]) -> None:
        """请求行 + 运行行 + 首条事件同一事务。"""
        with self._tx() as cur:
            self._begin_run(cur, request, run, events)

    def begin_recovered_run(
        self,
        request: ServiceRequest,
        run: Run,
        events: list[RunEvent],
        *,
        previous_run_id: str,
        expected_request_state: str,
    ) -> None:
        """Fence concurrent recovery attempts and create the new Run atomically."""
        with self._tx() as cur:
            current = cur.execute(
                "SELECT q.state, (SELECT r.run_id FROM runs r WHERE r.request_id=q.request_id "
                "ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_run_id "
                "FROM requests q WHERE q.request_id=? AND q.tenant_id=?",
                (request.request_id, request.tenant_id),
            ).fetchone()
            if current is None:
                raise KeyError("未知请求")
            if current["state"] != expected_request_state or current["latest_run_id"] != previous_run_id:
                raise RuntimeError("请求已被其他恢复调用接管或状态已变化")
            previous = cur.execute(
                "SELECT status,finish_reason FROM runs WHERE run_id=? AND request_id=?",
                (previous_run_id, request.request_id),
            ).fetchone()
            if previous is None or previous["status"] != RunStatus.FAILED.value or previous["finish_reason"] != "restart_interrupted":
                raise RuntimeError("请求旧运行不是可恢复的重启中断")
            has_write = cur.execute(
                "SELECT 1 FROM idempotency i JOIN runs r ON r.run_id=i.run_id "
                "WHERE r.request_id=? LIMIT 1",
                (request.request_id,),
            ).fetchone()
            if has_write is not None:
                raise RuntimeError("请求已有持久副作用，不能自动恢复")
            self._begin_run(cur, request, run, events)

    def _begin_run(
        self, cur: sqlite3.Cursor, request: ServiceRequest, run: Run, events: list[RunEvent],
    ) -> None:
        existing = cur.execute(
            "SELECT tenant_id FROM requests WHERE request_id=?", (request.request_id,),
        ).fetchone()
        if existing is not None and existing["tenant_id"] != request.tenant_id:
            raise ValueError("request_id 不属于当前租户")
        cur.execute(
            "INSERT INTO requests(request_id, tenant_id, agent_version, channel, state,"
            " subject_id, subject_scope, trigger_kind, trigger_ref, created_at, updated_at, trigger_event_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
            " updated_at=excluded.updated_at",
            (
                request.request_id, request.tenant_id, request.agent_version,
                str(request.channel), str(request.state), request.persistent_subject,
                str(request.subject_scope), request.trigger_kind, request.trigger_ref,
                request.created_at, request.updated_at, request.trigger_event_id,
            ),
        )
        cur.execute(
            "INSERT INTO runs(run_id, request_id, tenant_id, agent_version, status,"
            " occupancy_generation, owner_id, attempt_id, lineage_parent, started_at,"
            " snapshot_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id, run.request_id, run.tenant_id, run.agent_version,
                run.status, run.occupancy_generation, run.owner_id, run.attempt_id,
                run.lineage_parent, run.started_at,
                json.dumps(run.snapshot, ensure_ascii=False),
            ),
        )
        self._append(cur, events)

    def admit_event(
        self, request: ServiceRequest, run: Run, *, scenario_pack_id: str,
        payload_hash: str, first_event: RunEvent,
    ) -> RunAdmission:
        """SQLite 写锁与唯一键裁决接纳；提交前不能进入执行体。"""
        identity = request.event_identity(scenario_pack_id)
        if identity is None:
            raise ValueError("事件接纳必须提供 trigger_event_id")
        with self._tx() as cur:
            receipt = cur.execute(
                "SELECT * FROM event_receipts WHERE tenant_id=? AND scenario_pack_id=?"
                " AND trigger_kind=? AND trigger_event_id=?", identity,
            ).fetchone()
            if receipt is not None:
                status = "duplicate" if receipt["payload_hash"] == payload_hash else "conflict"
                if status == "conflict":
                    cur.execute(
                        "INSERT INTO event_admission_conflicts(run_id,payload_hash,observed_at) VALUES(?,?,?)",
                        (receipt["run_id"], payload_hash, now_iso()),
                    )
                row = dict(cur.execute("SELECT * FROM runs WHERE run_id=?", (receipt["run_id"],)).fetchone())
                row.pop("finish_reason")
                row["snapshot"] = json.loads(row.pop("snapshot_json"))
                row["status"] = RunStatus(row["status"])
                original_run = Run(**row)
                req = dict(cur.execute("SELECT * FROM requests WHERE request_id=?", (receipt["request_id"],)).fetchone())
                # 请求可跨轮次；本次回执的版本/渠道以首次接纳的 Run 为准。
                started = self._row_to_event(cur.execute(
                    "SELECT * FROM events WHERE run_id=? ORDER BY seq LIMIT 1", (original_run.run_id,),
                ).fetchone())
                req.update(agent_version=original_run.agent_version, channel=Channel(started.channel),
                           state=RequestState(req["state"]), trigger_kind=identity[2],
                           trigger_event_id=identity[3])
                return RunAdmission(status, ServiceRequest(**req), original_run)
            self._begin_run(cur, request, run, [first_event])
            cur.execute(
                "INSERT INTO event_receipts VALUES(?,?,?,?,?,?,?,?,?)",
                (*identity, payload_hash, run.agent_version, request.request_id, run.run_id, now_iso()),
            )
            return RunAdmission("created", request, run, first_event)

    # -- 事件 --------------------------------------------------------------
    def append_events(self, events: list[RunEvent]) -> None:
        with self._tx() as cur:
            self._append(cur, events)

    def _append(self, cur: sqlite3.Cursor, events: list[RunEvent]) -> None:
        """按**运行**封链，不由调用方决定链尾。

        内存账本的链是"进程内一条链"，落库的链是"每个 run 一条链"：进程重启后
        账本从 GENESIS 重新开始，若沿用账本的 prev_hash，库里就会出现断链。
        持久化链的事实由存储层持有，因此这里用同一个 run 的上一条事件重封。
        """
        for e in events:
            tail = cur.execute(
                "SELECT hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                (e.run_id,),
            ).fetchone()
            expect_prev = tail["hash"] if tail else GENESIS_HASH
            if e.prev_hash != expect_prev:
                e.seal(expect_prev)
            cur.execute(
                "INSERT INTO events(run_id, seq, request_id, event_type, ts, payload_json,"
                " prev_hash, hash, event_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    e.run_id, e.seq, e.request_id, e.event_type, e.ts,
                    json.dumps(e.payload, ensure_ascii=False), e.prev_hash, e.hash,
                    json.dumps(e.to_dict(), ensure_ascii=False),
                ),
            )

    def last_event(self, run_id: str) -> RunEvent | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,),
            ).fetchone()
        return self._row_to_event(row) if row else None

    def load_events(self, run_id: str) -> list[RunEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def verify_chain(self, run_id: str | None = None) -> bool:
        """按运行校验哈希链；不传 `run_id` 则校验全部运行。"""
        sql = "SELECT * FROM events"
        args: tuple[Any, ...] = ()
        if run_id is not None:
            sql += " WHERE run_id=?"
            args = (run_id,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY run_id, rid", args).fetchall()
        tails: dict[str, str] = {}
        for r in rows:
            rid = r["run_id"]
            prev = tails.get(rid, GENESIS_HASH)
            evt = self._row_to_event(r)
            if evt.prev_hash != prev:
                return False
            expected = RunEvent(**{**evt.to_dict(), "hash": ""}).seal(prev).hash
            if expected != evt.hash:
                return False
            tails[rid] = evt.hash
        return True

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> RunEvent:
        # 必须用整条 JSON 重建：`seal()` 哈希覆盖所有字段（含 ts/channel/idempotency_key），
        # 少填一个字段就会让链校验假失败。
        return RunEvent(**json.loads(row["event_json"]))

    # -- 业务写入提交点 ----------------------------------------------------
    def commit_write(
        self,
        run_id: str,
        *,
        key: str,
        action: str,
        result_id: str,
        bare_key: str | None = None,
        event: RunEvent,
        outbox_kind: str = "business_write",
        outbox_payload: dict[str, Any] | None = None,
        outbox_id: str | None = None,
    ) -> tuple[bool, str]:
        """幂等记录 + 事件 + outbox 意图同一事务。

        返回 `(created, result_id)`：`created=False` 表示同一幂等键已有结果，
        调用方必须复用原 `result_id`，不得再写一次（`M-A-02`/`M-A-06`）。
        """
        with self._tx() as cur:
            run = cur.execute("SELECT status, occupancy_generation FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"未知 run {run_id}")
            if run["status"] != "running":
                raise RuntimeError(f"run {run_id} 状态为 {run['status']}，旧代不得继续写入")
            existing = cur.execute(
                "SELECT result_id FROM idempotency WHERE key=?", (key,),
            ).fetchone()
            if existing is not None:
                return False, existing["result_id"]
            cur.execute(
                "INSERT INTO idempotency(key, bare_key, run_id, action, result_id, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (key, bare_key or key, run_id, action, result_id, now_iso()),
            )
            cur.execute(
                "UPDATE tool_attempts SET state='succeeded',result_id=?,updated_at=? "
                "WHERE attempt_key=? AND run_id=? AND state IN ('intent','unknown','reconciling')",
                (result_id, now_iso(), key, run_id),
            )
            self._append(cur, [event])
            cur.execute(
                "INSERT INTO outbox(id, run_id, kind, payload_json, state, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (
                    outbox_id or f"ob_{key}", run_id, outbox_kind,
                    json.dumps(outbox_payload or {"key": key, "result_id": result_id},
                               ensure_ascii=False),
                    "pending", now_iso(),
                ),
            )
            return True, result_id

    def begin_tool_attempt(
        self, run_id: str, *, attempt_key: str, action: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the exact operation intent before entering a side-effecting adapter.

        Repeated calls return the existing state. An unknown/in-flight attempt is never
        permission to execute again; callers must reconcile it first.
        """
        if not all(isinstance(value, str) and value.strip()
                   for value in (attempt_key, action)):
            raise ValueError("attempt_key 与 action 必须是非空字符串")
        if not isinstance(arguments, dict):
            raise ValueError("arguments 必须是 JSON 对象")
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        args_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        timestamp = now_iso()
        with self._tx() as cur:
            run = cur.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"未知 run {run_id}")
            if run["status"] != "running":
                raise RuntimeError(f"run {run_id} 已停止，不能开始业务操作")
            row = cur.execute(
                "SELECT * FROM tool_attempts WHERE attempt_key=?", (attempt_key,),
            ).fetchone()
            if row is not None:
                if row["action"] != action or row["args_hash"] != args_hash:
                    raise ValueError("幂等操作键已绑定不同的动作或参数")
                if row["state"] == "succeeded":
                    return {**dict(row), "created": False}
                if row["state"] == "failed":
                    cur.execute(
                        "UPDATE tool_attempts SET run_id=?,state='intent',updated_at=? "
                        "WHERE attempt_key=? AND state='failed'",
                        (run_id, timestamp, attempt_key),
                    )
                    return {**dict(cur.execute(
                        "SELECT * FROM tool_attempts WHERE attempt_key=?", (attempt_key,),
                    ).fetchone()), "created": True}
                raise RuntimeError(
                    f"操作状态为 {row['state']}，必须先对账，不能再次执行",
                )
            cur.execute(
                "INSERT INTO tool_attempts(attempt_key,run_id,action,args_hash,state,created_at,updated_at)"
                " VALUES(?,?,?,?, 'intent', ?, ?)",
                (attempt_key, run_id, action, args_hash, timestamp, timestamp),
            )
            return {**dict(cur.execute(
                "SELECT * FROM tool_attempts WHERE attempt_key=?", (attempt_key,),
            ).fetchone()), "created": True}

    def tool_attempt(self, attempt_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tool_attempts WHERE attempt_key=?", (attempt_key,),
            ).fetchone()
        return dict(row) if row else None

    def mark_tool_attempt_unknown(self, attempt_key: str, *, run_id: str) -> bool:
        """Mark a timed-out operation unknown while its owning Run is still active."""
        with self._tx() as cur:
            run = cur.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"未知 run {run_id}")
            if run["status"] != "running":
                raise RuntimeError("旧代不得更新工具操作状态")
            updated = cur.execute(
                "UPDATE tool_attempts SET state='reconciling',updated_at=? "
                "WHERE attempt_key=? AND run_id=? AND state='intent'",
                (now_iso(), attempt_key, run_id),
            ).rowcount
            return bool(updated)

    def mark_tool_attempt_failed(self, attempt_key: str, *, run_id: str) -> bool:
        """Record a definite non-acceptance; a later explicit attempt may retry."""
        with self._tx() as cur:
            run = cur.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"未知 run {run_id}")
            if run["status"] != "running":
                raise RuntimeError("旧代不得更新工具操作状态")
            updated = cur.execute(
                "UPDATE tool_attempts SET state='failed',updated_at=? "
                "WHERE attempt_key=? AND run_id=? AND state='intent'",
                (now_iso(), attempt_key, run_id),
            ).rowcount
            return bool(updated)

    # -- 收尾 --------------------------------------------------------------
    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        request_state: str,
        event: RunEvent,
        result_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        with self._tx() as cur:
            row = cur.execute("SELECT request_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"未知 run {run_id}")
            cur.execute(
                "UPDATE runs SET status=?, ended_at=?, finish_reason=? WHERE run_id=?",
                (status, now_iso(), reason, run_id),
            )
            cur.execute(
                "UPDATE requests SET state=?, updated_at=?, result_id=COALESCE(?, result_id)"
                " WHERE request_id=?",
                (request_state, now_iso(), result_id, row["request_id"]),
            )
            cur.execute(
                "UPDATE tool_attempts SET state='reconciling',updated_at=? "
                "WHERE run_id=? AND state='intent'",
                (now_iso(), run_id),
            )
            self._append(cur, [event])

    def set_request_state(self, request_id: str, state: str) -> None:
        with self._tx() as cur:
            updated = cur.execute(
                "UPDATE requests SET state=?,updated_at=? WHERE request_id=?",
                (state, now_iso(), request_id),
            ).rowcount
            if not updated:
                raise KeyError(f"未知 request {request_id}")

    # -- 恢复 --------------------------------------------------------------
    def recover(
        self, *, reason: str = "restart_interrupted", owner_id: str | None = None,
    ) -> RecoveryReport:
        """启动恢复：把不属于本进程的 `running` 判为中断，并回填幂等索引。

        旧运行**只记为失败并保留中断事实**，不复活、不续跑（Task §7.1）。
        """
        me = owner_id or self.owner_id
        report = RecoveryReport()
        with self._lock:
            orphans = [
                dict(r) for r in self._conn.execute(
                    "SELECT * FROM runs WHERE status='running' AND owner_id<>?",
                    (me,),
                ).fetchall()
            ]
            adopted = [
                r["run_id"] for r in self._conn.execute(
                    "SELECT run_id FROM runs WHERE status='running' AND owner_id=?",
                    (me,),
                ).fetchall()
            ]
        report.adopted = adopted
        for row in orphans:
            tail = self.last_event(row["run_id"])
            evt = RunEvent(
                seq=self.next_seq(row["run_id"]),
                event_type="run.interrupted",
                request_id=row["request_id"],
                run_id=row["run_id"],
                tenant_id=row["tenant_id"],
                agent_version=row["agent_version"],
                channel="",
                payload={"reason": reason, "previous_owner": row["owner_id"],
                         "occupancy_generation": row["occupancy_generation"]},
                idempotency_key=None,
            ).seal(tail.hash if tail else GENESIS_HASH)
            with self._tx() as cur:
                cur.execute(
                    "UPDATE runs SET status='failed', ended_at=?, finish_reason=?"
                    " WHERE run_id=? AND status='running'",
                    (now_iso(), reason, row["run_id"]),
                )
                cur.execute(
                    "UPDATE requests SET state='failed',updated_at=?"
                    " WHERE request_id=? AND state='running'",
                    (now_iso(), row["request_id"]),
                )
                cur.execute(
                    "UPDATE tool_attempts SET state='reconciling',updated_at=? "
                    "WHERE run_id=? AND state='intent'",
                    (now_iso(), row["run_id"]),
                )
                self._append(cur, [evt])
            report.interrupted.append(row["run_id"])
        with self._lock:
            rows = self._conn.execute(
                "SELECT bare_key, result_id FROM idempotency ORDER BY created_at",
            ).fetchall()
        # 内存索引按**裸键**建：规则层拿到的就是模型传来的那个键。
        # 库内按 (action, bare_key) 唯一，两者不冲突，见 action_key()。
        report.idempotent_keys = {r["bare_key"]: r["result_id"] for r in rows}
        return report

    def next_seq(self, run_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM events WHERE run_id=?", (run_id,),
            ).fetchone()
        return int(row["n"])

    def is_running(self, run_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return bool(row and row["status"] == "running")

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def request_row(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT q.*,(SELECT r.run_id FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_run_id,"
                "(SELECT r.status FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_run_status,"
                "(SELECT r.occupancy_generation FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_generation"
                " FROM requests q WHERE q.request_id=?",
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def recoverable_requests(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = (
                "SELECT q.*,(SELECT r.run_id FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_run_id,"
                "(SELECT r.status FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_run_status,"
                "(SELECT r.occupancy_generation FROM runs r WHERE r.request_id=q.request_id"
                " ORDER BY r.started_at DESC,r.run_id DESC LIMIT 1) AS latest_generation"
                " FROM requests q WHERE q.state IN ('queued','waiting_confirm')"
            )
            params: tuple[str, ...] = ()
            if tenant_id is not None:
                query += " AND q.tenant_id=?"
                params = (tenant_id,)
            query += " ORDER BY q.created_at,q.request_id"
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def request_has_committed_write(self, request_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM idempotency i JOIN runs r ON r.run_id=i.run_id "
                "WHERE r.request_id=? LIMIT 1",
                (request_id,),
            ).fetchone()
        return row is not None

    def create_task_item(
        self,
        *,
        task_id: str,
        tenant_id: str,
        agent_id: str,
        subject_id: str,
        service_cycle_id: str,
        purpose: str,
        source_agent_version: str,
    ) -> dict[str, Any]:
        values = {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "subject_id": subject_id,
            "service_cycle_id": service_cycle_id,
            "purpose": purpose,
            "source_agent_version": source_agent_version,
        }
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise ValueError("TaskItem 身份、主体、周期、目的和来源版本必须非空")
        timestamp = now_iso()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO task_items(task_id,tenant_id,agent_id,subject_id,service_cycle_id,"
                "purpose,source_agent_version,state,revision,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,'scheduled',1,?,?)",
                (*values.values(), timestamp, timestamp),
            )
            row = cur.execute("SELECT * FROM task_items WHERE task_id=?", (task_id,)).fetchone()
        return dict(row)

    def cancel_task_item(self, task_id: str) -> dict[str, Any]:
        """Cancel an unclaimed item; terminal cancellation is durable and idempotent."""
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM task_items WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(f"未知 TaskItem {task_id}")
            if row["state"] == "cancelled":
                return dict(row)
            if row["state"] not in {"waiting_condition", "scheduled", "ready"}:
                raise RuntimeError(f"TaskItem {task_id} 需先完成执行停止裁决")
            cur.execute(
                "UPDATE task_items SET state='cancelled',revision=revision+1,updated_at=? "
                "WHERE task_id=? AND state=?",
                (now_iso(), task_id, row["state"]),
            )
            updated = cur.execute(
                "SELECT * FROM task_items WHERE task_id=?", (task_id,),
            ).fetchone()
        return dict(updated)

    def task_item(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM task_items WHERE task_id=?", (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def recoverable_task_items(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            query = (
                "SELECT * FROM task_items WHERE state IN "
                "('waiting_condition','scheduled','ready')"
            )
            params: tuple[str, ...] = ()
            if tenant_id is not None:
                query += " AND tenant_id=?"
                params = (tenant_id,)
            query += " ORDER BY created_at,task_id"
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def pending_outbox(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outbox WHERE state='pending' ORDER BY created_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def note_outbox_attempt(self, outbox_id: str) -> bool:
        """Count a delivery attempt while leaving the row retryable until ack."""
        with self._tx() as cur:
            row = cur.execute(
                "SELECT state FROM outbox WHERE id=?", (outbox_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"未知 outbox {outbox_id}")
            if row["state"] != "pending":
                return False
            cur.execute(
                "UPDATE outbox SET attempts=attempts+1 WHERE id=? AND state='pending'",
                (outbox_id,),
            )
            return True

    # -- 配置草稿、稳定快照与冻结候选 ------------------------------------
    @staticmethod
    def _config_json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _config_row(cls, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("config_json", "diff_json"):
            if key in result:
                result[key.removesuffix("_json")] = json.loads(result.pop(key))
        return result

    def register_stable_config(
        self, *, tenant_id: str, agent_id: str, version_id: str,
        config: dict[str, Any], content_hash: str,
    ) -> dict[str, Any]:
        """登记导入/现有的稳定快照；重复登记只接受完全相同内容。"""
        encoded = self._config_json(config)
        with self._tx() as cur:
            current = cur.execute(
                "SELECT * FROM configuration_stable_versions"
                " WHERE tenant_id=? AND agent_id=? AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
            if current is not None:
                if current["content_hash"] != content_hash or current["config_json"] != encoded:
                    raise ValueError("稳定版本标识已绑定其他内容")
                return self._config_row(current)
            cur.execute(
                "INSERT INTO configuration_stable_versions"
                " (tenant_id,agent_id,version_id,config_json,content_hash,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (tenant_id, agent_id, version_id, encoded, content_hash, now_iso()),
            )
            row = cur.execute(
                "SELECT * FROM configuration_stable_versions"
                " WHERE tenant_id=? AND agent_id=? AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
            return self._config_row(row)

    def get_stable_config(
        self, *, tenant_id: str, agent_id: str, version_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM configuration_stable_versions"
                " WHERE tenant_id=? AND agent_id=? AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
        return self._config_row(row) if row else None

    def list_stable_configs(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tenant_id,agent_id,version_id,content_hash,created_at"
                " FROM configuration_stable_versions"
                " WHERE tenant_id=? AND agent_id=? ORDER BY created_at,version_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_config_draft(
        self, *, tenant_id: str, agent_id: str, base_version_id: str | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        with self._tx() as cur:
            current = cur.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            if current is not None:
                if current["base_version_id"] != base_version_id:
                    raise ValueError("该专家已有基于其他稳定版本的草稿")
                return self._config_row(current)
            if base_version_id is not None:
                base = cur.execute(
                    "SELECT 1 FROM configuration_stable_versions"
                    " WHERE tenant_id=? AND agent_id=? AND version_id=?",
                    (tenant_id, agent_id, base_version_id),
                ).fetchone()
                if base is None:
                    raise KeyError("未知稳定版本")
            cur.execute(
                "INSERT INTO configuration_drafts"
                " (tenant_id,agent_id,revision,base_version_id,config_json,updated_at)"
                " VALUES(?,?,1,?,?,?)",
                (tenant_id, agent_id, base_version_id, self._config_json(config), now_iso()),
            )
            row = cur.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            return self._config_row(row)

    def get_config_draft(self, *, tenant_id: str, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
        return self._config_row(row) if row else None

    def save_config_draft(
        self, *, tenant_id: str, agent_id: str, expected_revision: int,
        config: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Compare-and-swap save; returns (saved, current-on-conflict)."""
        with self._tx() as cur:
            row = cur.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            if row is None:
                raise KeyError("未知配置草稿")
            if row["revision"] != expected_revision:
                return None, self._config_row(row)
            cur.execute(
                "UPDATE configuration_drafts SET revision=revision+1,config_json=?,updated_at=?"
                " WHERE tenant_id=? AND agent_id=? AND revision=?",
                (self._config_json(config), now_iso(), tenant_id, agent_id, expected_revision),
            )
            updated = cur.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            return self._config_row(updated), None

    def freeze_config_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        idempotency_key: str, expected_revision: int, content_hash: str,
        diff: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Freeze the exact current draft revision as an immutable proposal."""
        with self._tx() as cur:
            existing = cur.execute(
                "SELECT * FROM change_proposals WHERE tenant_id=? AND agent_id=? AND idempotency_key=?",
                (tenant_id, agent_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                proposal = self._config_row(existing)
                if (proposal["source_revision"] == expected_revision
                        and proposal["content_hash"] == content_hash):
                    return proposal, None
                raise ValueError("幂等键已用于其他候选内容")

            draft = cur.execute(
                "SELECT * FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            if draft is None:
                raise KeyError("未知配置草稿")
            if draft["revision"] != expected_revision:
                return None, self._config_row(draft)
            config_json = draft["config_json"]
            actual_hash = __import__("hashlib").sha256(config_json.encode("utf-8")).hexdigest()
            if actual_hash != content_hash:
                raise ValueError("候选内容与当前草稿不一致")
            cur.execute(
                "INSERT INTO change_proposals"
                " (tenant_id,agent_id,candidate_id,idempotency_key,source_revision,base_version_id,"
                "config_json,content_hash,diff_json,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,'frozen',?)",
                (tenant_id, agent_id, candidate_id, idempotency_key, expected_revision,
                 draft["base_version_id"], config_json, content_hash,
                 json.dumps(diff, ensure_ascii=False, sort_keys=True, separators=(",", ":")), now_iso()),
            )
            row = cur.execute(
                "SELECT * FROM change_proposals WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (tenant_id, agent_id, candidate_id),
            ).fetchone()
            return self._config_row(row), None

    def get_config_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM change_proposals"
                " WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (tenant_id, agent_id, candidate_id),
            ).fetchone()
        return self._config_row(row) if row else None

    def get_config_candidate_by_idempotency_key(
        self, *, tenant_id: str, agent_id: str, idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM change_proposals"
                " WHERE tenant_id=? AND agent_id=? AND idempotency_key=?",
                (tenant_id, agent_id, idempotency_key),
            ).fetchone()
        return self._config_row(row) if row else None

    def list_config_candidates(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM change_proposals WHERE tenant_id=? AND agent_id=? ORDER BY created_at,candidate_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [self._config_row(row) for row in rows]

    def approve_release_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        content_hash: str, environment: str, entry_id: str, version_id: str,
        approved_by: str,
    ) -> dict[str, Any]:
        """Record one immutable human approval bound to the frozen content hash."""
        if environment != "sandbox":
            raise ValueError("R2 仅支持 sandbox 环境")
        if not all(isinstance(value, str) and value.strip()
                   for value in (approved_by, entry_id, version_id, content_hash)):
            raise ValueError("批准人与发布目标必须是非空字符串")
        with self._tx() as cur:
            candidate = cur.execute(
                "SELECT content_hash,status FROM change_proposals "
                "WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (tenant_id, agent_id, candidate_id),
            ).fetchone()
            if candidate is None:
                raise KeyError("未知冻结候选")
            if candidate["status"] != "frozen":
                raise RuntimeError("只有 frozen 候选可以审批")
            if candidate["content_hash"] != content_hash:
                raise ValueError("审批内容哈希与冻结候选不一致")
            cur.execute(
                "INSERT OR IGNORE INTO release_approvals "
                "(tenant_id,agent_id,candidate_id,content_hash,environment,entry_id,version_id,approved_by,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (tenant_id, agent_id, candidate_id, content_hash, environment,
                 entry_id, version_id, approved_by, now_iso()),
            )
            row = cur.execute(
                "SELECT * FROM release_approvals WHERE tenant_id=? AND agent_id=? "
                "AND candidate_id=? AND content_hash=? AND environment=? AND entry_id=? AND version_id=?",
                (tenant_id, agent_id, candidate_id, content_hash, environment, entry_id, version_id),
            ).fetchone()
        return dict(row)

    def release_approval(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        content_hash: str, environment: str, entry_id: str, version_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM release_approvals WHERE tenant_id=? AND agent_id=? "
                "AND candidate_id=? AND content_hash=? AND environment=? AND entry_id=? AND version_id=?",
                (tenant_id, agent_id, candidate_id, content_hash, environment, entry_id, version_id),
            ).fetchone()
        return dict(row) if row else None

    def publish_sandbox_candidate(
        self, *, tenant_id: str, agent_id: str, candidate_id: str,
        entry_id: str, version_id: str,
    ) -> dict[str, Any]:
        """Atomically materialize a frozen approved candidate and bind its sandbox entry."""
        if not all(isinstance(value, str) and value.strip()
                   for value in (entry_id, version_id)):
            raise ValueError("entry_id 与 version_id 必须是非空字符串")
        with self._tx() as cur:
            candidate = cur.execute(
                "SELECT * FROM change_proposals WHERE tenant_id=? AND agent_id=? AND candidate_id=?",
                (tenant_id, agent_id, candidate_id),
            ).fetchone()
            if candidate is None:
                raise KeyError("未知冻结候选")
            if candidate["status"] != "frozen":
                raise RuntimeError("只有 frozen 候选可以发布")
            approval = cur.execute(
                "SELECT 1 FROM release_approvals WHERE tenant_id=? AND agent_id=? "
                "AND candidate_id=? AND content_hash=? AND environment='sandbox' "
                "AND entry_id=? AND version_id=?",
                (tenant_id, agent_id, candidate_id, candidate["content_hash"], entry_id, version_id),
            ).fetchone()
            if approval is None:
                raise PermissionError("候选尚未获得绑定当前内容的人工批准")
            config = candidate["config_json"]
            created_at = now_iso()
            existing = cur.execute(
                "SELECT * FROM sandbox_releases WHERE tenant_id=? AND agent_id=? "
                "AND environment='sandbox' AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
            if existing is not None and (
                existing["candidate_id"] != candidate_id
                or existing["content_hash"] != candidate["content_hash"]
            ):
                raise ValueError("沙盒版本 ID 已绑定不同内容")
            release_id = existing["release_id"] if existing else "rel_" + hashlib.sha256(
                f"{candidate_id}:{version_id}".encode("utf-8"),
            ).hexdigest()[:20]
            stable = cur.execute(
                "SELECT content_hash FROM configuration_stable_versions "
                "WHERE tenant_id=? AND agent_id=? AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
            if stable is not None and stable["content_hash"] != candidate["content_hash"]:
                raise ValueError("稳定版本 ID 已绑定不同内容")
            cur.execute(
                "INSERT OR IGNORE INTO configuration_stable_versions "
                "(tenant_id,agent_id,version_id,config_json,content_hash,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (tenant_id, agent_id, version_id, config, candidate["content_hash"], created_at),
            )
            cur.execute(
                "INSERT OR IGNORE INTO sandbox_releases "
                "(release_id,tenant_id,agent_id,environment,candidate_id,version_id,content_hash,config_json,created_at) "
                "VALUES(?,?,?,'sandbox',?,?,?,?,?)",
                (release_id, tenant_id, agent_id, candidate_id, version_id,
                 candidate["content_hash"], config, created_at),
            )
            cur.execute(
                "INSERT INTO sandbox_entries(tenant_id,agent_id,entry_id,environment,release_id,version_id,updated_at) "
                "VALUES(?,?,?,'sandbox',?,?,?) ON CONFLICT(tenant_id,agent_id,entry_id,environment) "
                "DO UPDATE SET release_id=excluded.release_id,version_id=excluded.version_id,updated_at=excluded.updated_at",
                (tenant_id, agent_id, entry_id, release_id, version_id, created_at),
            )
            row = cur.execute(
                "SELECT * FROM sandbox_entries WHERE tenant_id=? AND agent_id=? AND entry_id=? AND environment='sandbox'",
                (tenant_id, agent_id, entry_id),
            ).fetchone()
        return dict(row)

    def sandbox_entry(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT e.*,r.candidate_id,r.content_hash,r.config_json,r.knowledge_state "
                "FROM sandbox_entries e JOIN sandbox_releases r ON r.release_id=e.release_id "
                "WHERE e.tenant_id=? AND e.agent_id=? AND e.entry_id=? AND e.environment='sandbox'",
                (tenant_id, agent_id, entry_id),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        return value

    def mark_sandbox_versions_for_revalidation(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[str]:
        with self._tx() as cur:
            cur.execute(
                "UPDATE sandbox_releases SET knowledge_state='stale' "
                "WHERE tenant_id=? AND agent_id=? AND environment='sandbox'",
                (tenant_id, agent_id),
            )
            rows = cur.execute(
                "SELECT version_id FROM sandbox_releases WHERE tenant_id=? AND agent_id=? "
                "AND environment='sandbox' AND knowledge_state='stale' ORDER BY version_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [row["version_id"] for row in rows]

    def sandbox_release_knowledge_state(
        self, *, tenant_id: str, agent_id: str, version_id: str,
    ) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT knowledge_state FROM sandbox_releases WHERE tenant_id=? AND agent_id=? "
                "AND environment='sandbox' AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
        return row["knowledge_state"] if row else None

    def create_knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
        kind: str, locator: str, display_name: str, authorization: str,
    ) -> dict[str, Any]:
        if kind not in {"faq", "url", "file"}:
            raise ValueError("不支持的知识来源类型")
        if not all(isinstance(value, str) and value.strip() for value in
                   (tenant_id, agent_id, source_id, locator, display_name, authorization)):
            raise ValueError("知识来源身份、位置、授权与名称必须非空")
        timestamp = now_iso()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO knowledge_sources(source_id,tenant_id,agent_id,kind,locator,display_name,"
                "authorization,state,attempt_count,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'queued',0,?,?)",
                (source_id, tenant_id, agent_id, kind, locator, display_name,
                 authorization, timestamp, timestamp),
            )
            return dict(cur.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=?", (source_id,),
            ).fetchone())

    def knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?",
                (tenant_id, agent_id, source_id),
            ).fetchone()
        return dict(row) if row else None

    def list_knowledge_sources(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND agent_id=? "
                "ORDER BY created_at,source_id", (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_knowledge_source_processing_failed(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any] | None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE knowledge_sources SET state='failed',error_code='interrupted',"
                "error_message='摄入进程中断，需要显式重试',updated_at=? "
                "WHERE tenant_id=? AND agent_id=? AND source_id=? AND state='processing'",
                (now_iso(), tenant_id, agent_id, source_id),
            )
            row = cur.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?",
                (tenant_id, agent_id, source_id),
            ).fetchone()
        return dict(row) if row else None

    def start_knowledge_ingestion(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            row = cur.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?",
                (tenant_id, agent_id, source_id),
            ).fetchone()
            if row is None:
                raise KeyError("未知知识来源")
            if row["state"] == "revoked":
                raise RuntimeError("已撤回来源不能重新摄入")
            cur.execute(
                "UPDATE knowledge_sources SET state='processing',attempt_count=attempt_count+1,"
                "error_code=NULL,error_message=NULL,updated_at=? WHERE source_id=?",
                (now_iso(), source_id),
            )
            return dict(cur.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=?", (source_id,),
            ).fetchone())

    def finish_knowledge_ingestion(
        self, *, tenant_id: str, agent_id: str, source_id: str,
        content: str | None = None, chunks: list[str] | None = None,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any]:
        if (content is None) == (error_code is None):
            raise ValueError("摄入完成必须恰好提供内容或失败信息")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content is not None else None
        now = now_iso()
        with self._tx() as cur:
            row = cur.execute(
                "SELECT state FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?",
                (tenant_id, agent_id, source_id),
            ).fetchone()
            if row is None:
                raise KeyError("未知知识来源")
            if row["state"] != "processing":
                raise RuntimeError("知识来源不处于摄入状态")
            if error_code is not None:
                cur.execute(
                    "UPDATE knowledge_sources SET state='failed',error_code=?,error_message=?,updated_at=? "
                    "WHERE source_id=?",
                    (error_code, error_message or "摄入失败", now, source_id),
                )
            else:
                document_id = f"doc_{uuid.uuid4().hex}"
                cur.execute(
                    "INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?)",
                    (document_id, source_id, tenant_id, agent_id, content, digest, now),
                )
                pieces = chunks or [content]
                for ordinal, piece in enumerate(pieces):
                    if piece.strip():
                        cur.execute(
                            "INSERT INTO knowledge_index(document_id,ordinal,text) VALUES(?,?,?)",
                            (document_id, ordinal, piece),
                        )
                cur.execute(
                    "UPDATE knowledge_sources SET state='ready',content_hash=?,error_code=NULL,"
                    "error_message=NULL,updated_at=? WHERE source_id=?",
                    (digest, now, source_id),
                )
            return dict(cur.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=?", (source_id,),
            ).fetchone())

    def revoke_knowledge_source(
        self, *, tenant_id: str, agent_id: str, source_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            row = cur.execute(
                "SELECT * FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?",
                (tenant_id, agent_id, source_id),
            ).fetchone()
            if row is None:
                raise KeyError("未知知识来源")
            if row["state"] == "revoked":
                return dict(row)
            doc_ids = [r["document_id"] for r in cur.execute(
                "SELECT document_id FROM knowledge_documents WHERE source_id=?", (source_id,),
            ).fetchall()]
            for document_id in doc_ids:
                cur.execute("DELETE FROM knowledge_index WHERE document_id=?", (document_id,))
                cur.execute("DELETE FROM knowledge_documents WHERE document_id=?", (document_id,))
            now = now_iso()
            cur.execute(
                "UPDATE knowledge_sources SET state='revoked',revoked_at=?,updated_at=? WHERE source_id=?",
                (now, now, source_id),
            )
            return dict(cur.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=?", (source_id,),
            ).fetchone())

    def search_knowledge_index(
        self, *, tenant_id: str, agent_id: str, query: str, limit: int = 10,
    ) -> list[dict[str, Any]]:
        tokens = [token for token in query.lower().split() if token]
        if not tokens:
            return []
        clauses = " AND ".join("lower(i.text) LIKE ?" for _ in tokens)
        params: list[Any] = [f"%{token}%" for token in tokens]
        params.extend((tenant_id, agent_id, limit))
        sql = (
            "SELECT i.text,s.source_id,d.document_id FROM knowledge_index i "
            "JOIN knowledge_documents d ON d.document_id=i.document_id "
            "JOIN knowledge_sources s ON s.source_id=d.source_id "
            f"WHERE {clauses} AND s.tenant_id=? AND s.agent_id=? AND s.state='ready' "
            "ORDER BY s.source_id,i.ordinal LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def save_material(
        self, *, tenant_id: str, agent_id: str, asset_id: str, version_id: str,
        display_name: str, filename: str, media_type: str, authorization: str,
        expires_at: str | None, content: bytes,
    ) -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        timestamp = now_iso()
        with self._tx() as cur:
            asset = cur.execute(
                "SELECT * FROM material_assets WHERE tenant_id=? AND agent_id=? AND asset_id=?",
                (tenant_id, agent_id, asset_id),
            ).fetchone()
            if asset is None:
                version = 1
                cur.execute(
                    "INSERT INTO material_assets VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, tenant_id, agent_id, display_name, filename, media_type,
                     authorization, expires_at, "active", version_id, timestamp),
                )
            else:
                if asset["state"] != "active":
                    raise RuntimeError("已撤回物料不能追加新版本")
                version = cur.execute(
                    "SELECT COALESCE(MAX(version),0)+1 AS version FROM material_versions WHERE asset_id=?",
                    (asset_id,),
                ).fetchone()["version"]
                cur.execute(
                    "UPDATE material_assets SET display_name=?,filename=?,media_type=?,authorization=?,"
                    "expires_at=?,current_version_id=? WHERE asset_id=?",
                    (display_name, filename, media_type, authorization, expires_at,
                     version_id, asset_id),
                )
            cur.execute(
                "INSERT INTO material_versions "
                "(version_id,asset_id,version,display_name,filename,media_type,authorization,expires_at,content_hash,content,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (version_id, asset_id, version, display_name, filename, media_type,
                 authorization, expires_at, digest, sqlite3.Binary(content), timestamp),
            )
            row = cur.execute(
                "SELECT * FROM material_assets WHERE asset_id=?", (asset_id,),
            ).fetchone()
        return {**dict(row), "version": version, "content_hash": digest}

    def list_materials(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT a.*,v.version,v.version_id,v.content_hash,v.display_name AS version_display_name,"
                "v.filename AS version_filename,v.media_type AS version_media_type,"
                "v.authorization AS version_authorization,v.expires_at AS version_expires_at FROM material_assets a "
                "JOIN material_versions v ON v.version_id=a.current_version_id "
                "WHERE a.tenant_id=? AND a.agent_id=? ORDER BY a.created_at,a.asset_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def material_version(
        self, *, tenant_id: str, agent_id: str, asset_id: str, version_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT a.*,v.version,v.version_id,v.content_hash,v.content,"
                "v.display_name AS version_display_name,v.filename AS version_filename,"
                "v.media_type AS version_media_type,v.authorization AS version_authorization,"
                "v.expires_at AS version_expires_at FROM material_assets a "
                "JOIN material_versions v ON v.asset_id=a.asset_id "
                "WHERE a.tenant_id=? AND a.agent_id=? AND a.asset_id=? "
                "AND v.version_id=COALESCE(?,a.current_version_id)",
                (tenant_id, agent_id, asset_id, version_id),
            ).fetchone()
        return dict(row) if row else None

    def revoke_material(
        self, *, tenant_id: str, agent_id: str, asset_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            cur.execute(
                "UPDATE material_assets SET state='revoked' WHERE tenant_id=? AND agent_id=? AND asset_id=?",
                (tenant_id, agent_id, asset_id),
            )
            row = cur.execute(
                "SELECT * FROM material_assets WHERE tenant_id=? AND agent_id=? AND asset_id=?",
                (tenant_id, agent_id, asset_id),
            ).fetchone()
        if row is None:
            raise KeyError("未知物料")
        return dict(row)

    def open_customer_conversation(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
        conversation_id: str, visitor_token_hash: str,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            release = cur.execute(
                "SELECT e.release_id,e.version_id,r.knowledge_state FROM sandbox_entries e "
                "JOIN sandbox_releases r ON r.release_id=e.release_id "
                "WHERE e.tenant_id=? AND e.agent_id=? AND e.entry_id=? AND e.environment='sandbox'",
                (tenant_id, agent_id, entry_id),
            ).fetchone()
            if release is None:
                raise KeyError("未知沙盒入口")
            if release["knowledge_state"] != "ready":
                raise RuntimeError("沙盒入口所绑版本待重新验收，不能接待访客")
            cur.execute(
                "INSERT INTO customer_conversations VALUES(?,?,?,?,?,?,?,'bot',0,NULL,?,?)",
                (conversation_id, tenant_id, agent_id, entry_id, release["release_id"],
                 release["version_id"], visitor_token_hash, timestamp, timestamp),
            )
            return dict(cur.execute(
                "SELECT * FROM customer_conversations WHERE conversation_id=?", (conversation_id,),
            ).fetchone())

    def add_visitor_message(
        self, *, conversation_id: str, visitor_token_hash: str,
        text: str, request_human: bool = False,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            conversation = cur.execute(
                "SELECT * FROM customer_conversations WHERE conversation_id=? AND visitor_token_hash=?",
                (conversation_id, visitor_token_hash),
            ).fetchone()
            if conversation is None:
                raise KeyError("访客会话凭据无效")
            sequence = cur.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM customer_messages WHERE conversation_id=?",
                (conversation["conversation_id"],),
            ).fetchone()["sequence"]
            cur.execute(
                "INSERT INTO customer_messages(conversation_id,sequence,sender,text,created_at) VALUES(?,?, 'visitor',?,?)",
                (conversation["conversation_id"], sequence, text, timestamp),
            )
            state = "human_requested" if request_human else conversation["state"]
            cur.execute(
                "UPDATE customer_conversations SET state=?,updated_at=? WHERE conversation_id=?",
                (state, timestamp, conversation["conversation_id"]),
            )
            return dict(cur.execute(
                "SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?",
                (conversation["conversation_id"], sequence),
            ).fetchone())

    def list_customer_conversations(
        self, *, tenant_id: str, agent_id: str,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM customer_conversations WHERE tenant_id=? AND agent_id=? "
                "ORDER BY updated_at DESC,conversation_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def claim_customer_conversation(
        self, *, tenant_id: str, agent_id: str, conversation_id: str, actor_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            row = cur.execute(
                "SELECT * FROM customer_conversations WHERE tenant_id=? AND agent_id=? AND conversation_id=?",
                (tenant_id, agent_id, conversation_id),
            ).fetchone()
            if row is None:
                raise KeyError("未知会话")
            if row["state"] == "human":
                raise RuntimeError("会话已被人工接管")
            generation = row["occupancy_generation"] + 1
            cur.execute(
                "UPDATE customer_conversations SET state='human',assigned_to=?,occupancy_generation=?,updated_at=? "
                "WHERE conversation_id=? AND occupancy_generation=?",
                (actor_id, generation, now_iso(), conversation_id, row["occupancy_generation"]),
            )
            return dict(cur.execute(
                "SELECT * FROM customer_conversations WHERE conversation_id=?", (conversation_id,),
            ).fetchone())

    def add_operator_message(
        self, *, tenant_id: str, agent_id: str, conversation_id: str, actor_id: str,
        generation: int, text: str, asset_id: str | None = None,
        asset_version_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            conversation = cur.execute(
                "SELECT * FROM customer_conversations WHERE tenant_id=? AND agent_id=? AND conversation_id=?",
                (tenant_id, agent_id, conversation_id),
            ).fetchone()
            if conversation is None:
                raise KeyError("未知会话")
            if conversation["state"] != "human" or conversation["assigned_to"] != actor_id or conversation["occupancy_generation"] != generation:
                raise RuntimeError("客服会话占用已变化，拒绝发送")
            if asset_id is not None:
                material = cur.execute(
                    "SELECT a.current_version_id,a.state,a.expires_at,v.version_id "
                    "FROM material_assets a JOIN material_versions v ON v.asset_id=a.asset_id "
                    "WHERE a.tenant_id=? AND a.agent_id=? AND a.asset_id=? AND v.version_id=?",
                    (tenant_id, agent_id, asset_id, asset_version_id),
                ).fetchone()
                if material is None or material["state"] != "active" or material["current_version_id"] != asset_version_id:
                    raise RuntimeError("物料已撤回或版本已变化，拒绝发送")
                if material["expires_at"] and material["expires_at"] <= timestamp:
                    raise RuntimeError("物料授权已过期，拒绝发送")
            sequence = cur.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM customer_messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()["sequence"]
            cur.execute(
                "INSERT INTO customer_messages VALUES(?,?,?,?,?,?,?,?)",
                (conversation_id, sequence, "operator", actor_id, text, asset_id,
                 asset_version_id, timestamp),
            )
            cur.execute(
                "UPDATE customer_conversations SET updated_at=? WHERE conversation_id=?",
                (timestamp, conversation_id),
            )
            return dict(cur.execute(
                "SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?",
                (conversation_id, sequence),
            ).fetchone())

    def customer_messages(
        self, *, conversation_id: str, tenant_id: str | None = None,
        agent_id: str | None = None, visitor_token_hash: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conversation = self._conn.execute(
                "SELECT 1 FROM customer_conversations WHERE conversation_id=? "
                "AND (? IS NULL OR tenant_id=?) AND (? IS NULL OR agent_id=?) "
                "AND (? IS NULL OR visitor_token_hash=?)",
                (conversation_id, tenant_id, tenant_id, agent_id, agent_id,
                 visitor_token_hash, visitor_token_hash),
            ).fetchone()
            if conversation is None:
                raise KeyError("未知或无权访问会话")
            rows = self._conn.execute(
                "SELECT * FROM customer_messages WHERE conversation_id=? ORDER BY sequence",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def customer_attachment(
        self, *, conversation_id: str, visitor_token_hash: str,
        asset_id: str, asset_version_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT v.version_id,v.display_name,v.filename,v.media_type,v.authorization,"
                "v.expires_at,v.content_hash,v.content FROM customer_conversations c "
                "JOIN customer_messages m ON m.conversation_id=c.conversation_id "
                "JOIN material_assets a ON a.asset_id=m.asset_id "
                "JOIN material_versions v ON v.asset_id=a.asset_id AND v.version_id=m.asset_version_id "
                "WHERE c.conversation_id=? AND c.visitor_token_hash=? "
                "AND m.asset_id=? AND m.asset_version_id=? AND a.state='active' "
                "AND (v.expires_at IS NULL OR v.expires_at>?) "
                "ORDER BY m.sequence DESC LIMIT 1",
                (conversation_id, visitor_token_hash, asset_id, asset_version_id, now_iso()),
            ).fetchone()
        return dict(row) if row else None

    def mark_outbox(self, outbox_id: str, *, state: str = "delivered") -> None:
        if state != "delivered":
            raise ValueError("outbox 只允许在消费者成功后标记 delivered")
        with self._tx() as cur:
            row = cur.execute(
                "SELECT state FROM outbox WHERE id=?", (outbox_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"未知 outbox {outbox_id}")
            if row["state"] == "delivered":
                return
            cur.execute(
                "UPDATE outbox SET state='delivered', delivered_at=?"
                " WHERE id=? AND state='pending'",
                (now_iso(), outbox_id),
            )


__all__ = ["SqliteStore", "RecoveryReport", "SCHEMA_VERSION"]
