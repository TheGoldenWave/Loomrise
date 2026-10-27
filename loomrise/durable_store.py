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
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .contracts import (
    GENESIS_HASH, Channel, RequestState, Run, RunAdmission, RunEvent, RunStatus,
    ServiceRequest, now_iso,
)

SCHEMA_VERSION = 4

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

    # -- 运行开始 ----------------------------------------------------------
    def begin_run(self, request: ServiceRequest, run: Run, events: list[RunEvent]) -> None:
        """请求行 + 运行行 + 首条事件同一事务。"""
        with self._tx() as cur:
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
            updated = cur.execute(
                "UPDATE runs SET status=?, ended_at=?, finish_reason=?"
                " WHERE run_id=? AND status='running'",
                (status, now_iso(), reason, run_id),
            ).rowcount
            if updated != 1:
                raise RuntimeError(f"run {run_id} 已结束，旧代不得再次完成")
            cur.execute(
                "UPDATE requests SET state=?, updated_at=?, result_id=COALESCE(?, result_id)"
                " WHERE request_id=?",
                (request_state, now_iso(), result_id, row["request_id"]),
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
        with self._tx() as cur:
            orphans = [
                dict(r) for r in cur.execute(
                    "SELECT * FROM runs WHERE status='running' AND owner_id<>?",
                    (me,),
                ).fetchall()
            ]
            report.adopted = [
                r["run_id"] for r in cur.execute(
                    "SELECT run_id FROM runs WHERE status='running' AND owner_id=?",
                    (me,),
                ).fetchall()
            ]
            for row in orphans:
                updated = cur.execute(
                    "UPDATE runs SET status='failed', ended_at=?, finish_reason=?"
                    " WHERE run_id=? AND status='running'",
                    (now_iso(), reason, row["run_id"]),
                ).rowcount
                if updated != 1:
                    continue
                cur.execute(
                    "UPDATE requests SET state='failed',updated_at=?"
                    " WHERE request_id=? AND state='running'",
                    (now_iso(), row["request_id"]),
                )
                tail = cur.execute(
                    "SELECT seq, hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1",
                    (row["run_id"],),
                ).fetchone()
                evt = RunEvent(
                    seq=(int(tail["seq"]) + 1) if tail else 0,
                    event_type="run.interrupted",
                    request_id=row["request_id"],
                    run_id=row["run_id"],
                    tenant_id=row["tenant_id"],
                    agent_version=row["agent_version"],
                    channel="",
                    payload={"reason": reason, "previous_owner": row["owner_id"],
                             "occupancy_generation": row["occupancy_generation"]},
                    idempotency_key=None,
                ).seal(tail["hash"] if tail else GENESIS_HASH)
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
