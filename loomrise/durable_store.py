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

from .contracts import GENESIS_HASH, Run, RunEvent, ServiceRequest, now_iso

SCHEMA_VERSION = 1

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
            if row is None:
                cur.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row["value"]) > SCHEMA_VERSION:
                raise RuntimeError(
                    f"store schema {row['value']} 比代码支持的 {SCHEMA_VERSION} 新，拒绝降级打开",
                )

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
            cur.execute(
                "INSERT INTO requests(request_id, tenant_id, agent_version, channel, state,"
                " subject_id, subject_scope, trigger_kind, trigger_ref, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
                " updated_at=excluded.updated_at",
                (
                    request.request_id, request.tenant_id, request.agent_version,
                    str(request.channel), str(request.state), request.subject_id,
                    str(request.subject_scope), request.trigger_kind, request.trigger_ref,
                    request.created_at, request.updated_at,
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
            cur.execute(
                "UPDATE runs SET status=?, ended_at=?, finish_reason=? WHERE run_id=?",
                (status, now_iso(), reason, run_id),
            )
            cur.execute(
                "UPDATE requests SET state=?, updated_at=?, result_id=COALESCE(?, result_id)"
                " WHERE request_id=?",
                (request_state, now_iso(), result_id, row["request_id"]),
            )
            self._append(cur, [event])

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

    def pending_outbox(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM outbox WHERE state='pending' ORDER BY created_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_outbox(self, outbox_id: str, *, state: str = "delivered") -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE outbox SET state=?, attempts=attempts+1, delivered_at=? WHERE id=?",
                (state, now_iso(), outbox_id),
            )


__all__ = ["SqliteStore", "RecoveryReport", "SCHEMA_VERSION"]
