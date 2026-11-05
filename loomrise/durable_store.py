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
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from .contracts import (
    GENESIS_HASH, Channel, RequestState, Run, RunAdmission, RunEvent, RunStatus,
    ServiceRequest, ServiceCycleBinding, new_id, now_iso,
)
from .contact_pages import contact_paths, validate_contact
from .service_cycles import cycle_config_hash
from .graph_runtime import GraphRuntime

SCHEMA_VERSION = 23


class StaleConfigurationRevision(RuntimeError):
    """Raised when a revision-scoped configuration write loses its compare-and-swap."""


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
CREATE TABLE IF NOT EXISTS service_cycles (
  cycle_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  matter_ref TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  agent_version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  -- 业务周期生命周期：一个主体/事项可有多个代次，但同一时刻最多一个 active。
  -- state 取 active/closed/cancelled；关闭/撤销为终态，旧代次不得再受理。
  generation INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL DEFAULT 'active',
  closed_at TEXT,
  predecessor_cycle_id TEXT
);
CREATE TABLE IF NOT EXISTS service_cycle_sources (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  authority_id TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  cycle_id TEXT NOT NULL REFERENCES service_cycles(cycle_id),
  registered_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,authority_id,source_event_id)
);
CREATE TABLE IF NOT EXISTS service_cycle_counters (
  cycle_id TEXT NOT NULL REFERENCES service_cycles(cycle_id),
  budget_key TEXT NOT NULL,
  count INTEGER NOT NULL CHECK(count>=0),
  PRIMARY KEY(cycle_id,budget_key)
);
-- 未完成事项跨周期显式迁移的不可变 lineage 审计；不复活已撤销/已迁移事项。
CREATE TABLE IF NOT EXISTS service_cycle_migrations (
  migration_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  source_cycle_id TEXT NOT NULL REFERENCES service_cycles(cycle_id),
  target_cycle_id TEXT NOT NULL REFERENCES service_cycles(cycle_id),
  source_task_id TEXT NOT NULL,
  target_task_id TEXT NOT NULL,
  root_task_id TEXT NOT NULL,
  authorized_by TEXT NOT NULL,
  migrated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_waits (
  wait_id       TEXT PRIMARY KEY,
  run_id        TEXT NOT NULL UNIQUE,
  request_id    TEXT NOT NULL,
  tenant_id     TEXT NOT NULL,
  agent_version TEXT NOT NULL,
  generation    INTEGER NOT NULL,
  waiting_on    TEXT NOT NULL,
  timeout_ms    INTEGER,
  timeout_to    TEXT,
  state         TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_run_waits_request ON run_waits(request_id, state);
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
  review_summary_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, candidate_id),
  UNIQUE (tenant_id, agent_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS configuration_advisory_dismissals (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  source_revision INTEGER NOT NULL,
  advisory_key TEXT NOT NULL,
  layer_path_json TEXT NOT NULL,
  closed_set_size INTEGER NOT NULL CHECK(closed_set_size > 0),
  actor_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,source_revision,advisory_key)
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
CREATE TABLE IF NOT EXISTS customer_contact_pages (
  tenant_id   TEXT NOT NULL,
  agent_id    TEXT NOT NULL,
  entry_id    TEXT NOT NULL,
  release_id  TEXT NOT NULL REFERENCES sandbox_releases(release_id),
  version_id  TEXT NOT NULL,
  state       TEXT NOT NULL CHECK (state IN ('active','disabled')),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  PRIMARY KEY (tenant_id, agent_id, entry_id)
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
CREATE TABLE IF NOT EXISTS material_processing_candidates (
  candidate_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  asset_id TEXT NOT NULL, version_id TEXT NOT NULL, kind TEXT NOT NULL,
  status TEXT NOT NULL, summary TEXT NOT NULL, source_hash TEXT NOT NULL,
  review_state TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS material_derivative_jobs (
  job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  asset_id TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES material_versions(version_id),
  source_hash TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT,
  created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS material_derivatives (
  derivative_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES material_derivative_jobs(job_id),
  kind TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
  content_hash TEXT NOT NULL, content BLOB NOT NULL, metadata_json TEXT NOT NULL,
  UNIQUE(job_id,kind)
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
CREATE TABLE IF NOT EXISTS customer_visitor_fields (
  conversation_id TEXT PRIMARY KEY REFERENCES customer_conversations(conversation_id),
  fields_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_connections (
  tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL, channel TEXT NOT NULL,
  external_account TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
  revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,channel,external_account)
);
CREATE TABLE IF NOT EXISTS channel_messages (
  dedupe_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  channel TEXT NOT NULL, external_account TEXT NOT NULL, direction TEXT NOT NULL,
  message_id TEXT NOT NULL, thread_id TEXT NOT NULL, text TEXT NOT NULL,
  attachment_ids_json TEXT NOT NULL, delivery TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  environment TEXT NOT NULL, event_type TEXT NOT NULL, event_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_messages (
  conversation_id TEXT NOT NULL REFERENCES customer_conversations(conversation_id),
  sequence        INTEGER NOT NULL,
  sender           TEXT NOT NULL CHECK (sender IN ('visitor','assistant','operator')),
  actor_id         TEXT,
  text             TEXT NOT NULL,
  asset_id         TEXT,
  asset_version_id TEXT,
  created_at       TEXT NOT NULL,
  derivative_id    TEXT REFERENCES material_derivatives(derivative_id),
  PRIMARY KEY(conversation_id,sequence)
);
CREATE TABLE IF NOT EXISTS customer_inbox_reads (
  tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL, actor_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL REFERENCES customer_conversations(conversation_id),
  read_sequence INTEGER NOT NULL CHECK (read_sequence >= 0),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,actor_id,conversation_id)
);
CREATE TABLE IF NOT EXISTS customer_inbox_preferences (
  tenant_id TEXT NOT NULL, agent_id TEXT NOT NULL, actor_id TEXT NOT NULL,
  new_messages INTEGER NOT NULL CHECK (new_messages IN (0,1)),
  handoff INTEGER NOT NULL CHECK (handoff IN (0,1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,actor_id)
);
CREATE TABLE IF NOT EXISTS customer_inbox_events (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  conversation_id TEXT NOT NULL REFERENCES customer_conversations(conversation_id),
  event_type TEXT NOT NULL CHECK (event_type IN (
    'visitor.message','assistant.response','handoff.requested','handoff.claimed','handoff.replied','handoff.released'
  )),
  message_sequence INTEGER,
  state TEXT NOT NULL CHECK (state IN ('bot','human_requested','human')),
  occupancy_generation INTEGER NOT NULL CHECK (occupancy_generation >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,sequence)
);
CREATE TABLE IF NOT EXISTS customer_inbox_consumers (
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  consumer_id TEXT NOT NULL,
  acknowledged_sequence INTEGER NOT NULL CHECK (acknowledged_sequence >= 0),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(tenant_id,agent_id,actor_id,consumer_id)
);
CREATE TABLE IF NOT EXISTS customer_reception_turns (
  conversation_id TEXT NOT NULL REFERENCES customer_conversations(conversation_id),
  input_sequence INTEGER NOT NULL,
  message_id TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  request_id TEXT NOT NULL REFERENCES requests(request_id),
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
  generation INTEGER NOT NULL,
  version_id TEXT NOT NULL,
  release_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  response_sequence INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(conversation_id,input_sequence),
  UNIQUE(conversation_id,message_id)
);
CREATE TABLE IF NOT EXISTS diagnosis_permissions (
  permission_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  recipient_actor_id TEXT NOT NULL,
  issued_by TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK(purpose='diagnosis'),
  selection_json TEXT NOT NULL,
  permission_hash TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS diagnosis_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  permission_id TEXT NOT NULL UNIQUE REFERENCES diagnosis_permissions(permission_id),
  input_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diagnosis_reports (
  report_id TEXT PRIMARY KEY,
  permission_id TEXT NOT NULL REFERENCES diagnosis_permissions(permission_id),
  snapshot_id TEXT NOT NULL REFERENCES diagnosis_snapshots(snapshot_id),
  input_hash TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS governance_jobs (
  job_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  frozen_json TEXT NOT NULL,
  frozen_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  generation INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  reserved_tokens INTEGER NOT NULL DEFAULT 0,
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  provider_state TEXT NOT NULL DEFAULT 'not_started',
  report_id TEXT,
  owner_id TEXT,
  reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tenant_id,agent_id,actor_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS governance_attempts (
  job_id TEXT NOT NULL REFERENCES governance_jobs(job_id),
  generation INTEGER NOT NULL,
  provider_state TEXT NOT NULL,
  reserved_tokens INTEGER NOT NULL,
  usage_json TEXT,
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  PRIMARY KEY(job_id,generation)
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
            if 'service_cycle_json' not in columns:
                cur.execute('ALTER TABLE requests ADD COLUMN service_cycle_json TEXT')
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
            message_columns = {r['name'] for r in cur.execute('PRAGMA table_info(customer_messages)')}
            if 'derivative_id' not in message_columns:
                cur.execute('ALTER TABLE customer_messages ADD COLUMN derivative_id TEXT REFERENCES material_derivatives(derivative_id)')
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
            proposal_columns = {r["name"] for r in cur.execute("PRAGMA table_info(change_proposals)")}
            if "review_summary_json" not in proposal_columns:
                cur.execute("ALTER TABLE change_proposals ADD COLUMN review_summary_json TEXT NOT NULL DEFAULT '[]'")
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
            # 增量补齐业务周期生命周期列；旧库既有内容保留，旧 active 行默认 active。
            cycle_columns = {r["name"] for r in cur.execute("PRAGMA table_info(service_cycles)")}
            if "generation" not in cycle_columns:
                cur.execute("ALTER TABLE service_cycles ADD COLUMN generation INTEGER NOT NULL DEFAULT 1")
            if "state" not in cycle_columns:
                cur.execute("ALTER TABLE service_cycles ADD COLUMN state TEXT NOT NULL DEFAULT 'active'")
            if "closed_at" not in cycle_columns:
                cur.execute("ALTER TABLE service_cycles ADD COLUMN closed_at TEXT")
            if "predecessor_cycle_id" not in cycle_columns:
                cur.execute("ALTER TABLE service_cycles ADD COLUMN predecessor_cycle_id TEXT")
            # 同一主体/事项同一时刻最多一个 active 周期；并发裁定由事务串行化兜底。
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_service_cycles_active_scope "
                "ON service_cycles(tenant_id,agent_id,subject_id,authority_id,matter_ref) "
                "WHERE state='active'"
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

    def channel_connection(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute('SELECT * FROM channel_connections WHERE tenant_id=? AND agent_id=? AND channel=? AND external_account=?',
                (tenant_id, agent_id, channel, external_account)).fetchone()
        return {'environment': 'sandbox', **dict(row)} if row else None

    def channel_authorize(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str, mode: str) -> dict[str, Any]:
        scope = (tenant_id, agent_id, channel, external_account)
        with self._tx() as cur:
            cur.execute('INSERT INTO channel_connections VALUES(?,?,?,?,?,?,?,?) '
                        'ON CONFLICT(tenant_id,agent_id,channel,external_account) DO UPDATE SET '
                        'mode=excluded.mode,state=excluded.state,revision=channel_connections.revision+1,updated_at=excluded.updated_at',
                        (*scope, mode, 'authorized', 1, now_iso()))
            value = {'environment': 'sandbox', **dict(cur.execute(
                'SELECT * FROM channel_connections WHERE tenant_id=? AND agent_id=? AND channel=? AND external_account=?', scope).fetchone())}
            event = {'type': 'channel.authorized', **value}
            cur.execute('INSERT INTO channel_events(tenant_id,agent_id,environment,event_type,event_json,created_at) VALUES(?,?,?,?,?,?)',
                        (tenant_id, agent_id, 'sandbox', event['type'], json.dumps(event, ensure_ascii=False), now_iso()))
        return value

    def channel_revoke(self, *, tenant_id: str, agent_id: str, channel: str, external_account: str) -> dict[str, Any]:
        scope = (tenant_id, agent_id, channel, external_account)
        with self._tx() as cur:
            cur.execute("UPDATE channel_connections SET state='revoked',revision=revision+1,updated_at=? "
                        'WHERE tenant_id=? AND agent_id=? AND channel=? AND external_account=?', (now_iso(), *scope))
            if cur.rowcount != 1:
                raise KeyError('未知渠道授权')
            value = {'environment': 'sandbox', **dict(cur.execute(
                'SELECT * FROM channel_connections WHERE tenant_id=? AND agent_id=? AND channel=? AND external_account=?', scope).fetchone())}
            event = {'type': 'channel.revoked', **value}
            cur.execute('INSERT INTO channel_events(tenant_id,agent_id,environment,event_type,event_json,created_at) VALUES(?,?,?,?,?,?)',
                        (tenant_id, agent_id, 'sandbox', event['type'], json.dumps(event, ensure_ascii=False), now_iso()))
        return value

    def channel_record_message(self, *, dedupe_key: str, value: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        with self._tx() as cur:
            connection = cur.execute('SELECT * FROM channel_connections WHERE tenant_id=? AND agent_id=? AND channel=? AND external_account=?',
                (value['tenant_id'], value['agent_id'], value['channel'], value['external_account'])).fetchone()
            if connection is None or connection['state'] != 'authorized' or connection['revision'] != expected_revision:
                raise PermissionError('渠道未授权、已撤销或授权版本已变化')
            if value['direction'] == 'outbound' and connection['mode'] != 'full':
                raise PermissionError('仅通知模式不能发送会话内容或附件')
            existing = cur.execute('SELECT * FROM channel_messages WHERE dedupe_key=?', (dedupe_key,)).fetchone()
            if existing is None:
                # Older sandbox keys were ambiguous; reuse only an exact scoped identity.
                legacy_identity = ':'.join(str(value[key]) for key in (
                    'tenant_id', 'agent_id', 'channel', 'external_account', 'direction', 'thread_id', 'message_id'))
                legacy_key = hashlib.sha256(f'{legacy_identity}:{expected_revision}'.encode()).hexdigest()
                existing = cur.execute(
                    'SELECT * FROM channel_messages WHERE dedupe_key=? AND tenant_id=? AND agent_id=? '
                    'AND channel=? AND external_account=? AND direction=? AND thread_id=? AND message_id=?',
                    (legacy_key, value['tenant_id'], value['agent_id'], value['channel'], value['external_account'],
                     value['direction'], value['thread_id'], value['message_id'])).fetchone()
            if existing is not None:
                result = self.channel_message_value(existing)
                if any(result[key] != value[key] for key in (
                        'tenant_id', 'agent_id', 'channel', 'external_account', 'direction',
                        'message_id', 'thread_id', 'text', 'attachment_ids')):
                    raise ValueError('同一消息 ID 的内容与已记录内容不一致')
                if existing['dedupe_key'] != dedupe_key:
                    cur.execute('UPDATE channel_messages SET dedupe_key=? WHERE dedupe_key=?', (dedupe_key, existing['dedupe_key']))
                return {**result, 'duplicate': True}
            cur.execute('INSERT INTO channel_messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (dedupe_key, value['tenant_id'], value['agent_id'], value['channel'], value['external_account'], value['direction'],
                 value['message_id'], value['thread_id'], value['text'], json.dumps(value['attachment_ids'], ensure_ascii=False),
                 'simulated', now_iso()))
            result = {**value, 'environment': 'sandbox', 'delivery': 'simulated', 'duplicate': False}
            event_type = 'channel.message_sent' if value['direction'] == 'outbound' else 'channel.message_received'
            event = {'type': event_type, **result}
            cur.execute('INSERT INTO channel_events(tenant_id,agent_id,environment,event_type,event_json,created_at) VALUES(?,?,?,?,?,?)',
                        (value['tenant_id'], value['agent_id'], 'sandbox', event_type, json.dumps(event, ensure_ascii=False), now_iso()))
        return result

    @staticmethod
    def channel_message_value(row: sqlite3.Row) -> dict[str, Any]:
        result = {key: row[key] for key in ('tenant_id', 'agent_id', 'channel', 'external_account', 'direction',
                                           'message_id', 'thread_id', 'text', 'delivery')}
        return {**result, 'attachment_ids': json.loads(row['attachment_ids_json']), 'environment': 'sandbox'}

    def channel_message(self, dedupe_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute('SELECT * FROM channel_messages WHERE dedupe_key=?', (dedupe_key,)).fetchone()
        return self.channel_message_value(row) if row is not None else None

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
    def register_service_cycle(self, *, tenant_id: str, agent_id: str, subject_id: str,
                               authority_id: str, matter_ref: str, source_event_id: str,
                               agent_version: str, config_hash: str) -> ServiceCycleBinding:
        """受信宿主登记来源；没有面向访客或模型的裸字符串创建入口。

        同一业务事件 ID 的重放是幂等的；新来源只能登记到 active 周期，
        周期关闭后必须经显式裁定开启新周期，不能静默复用旧周期。
        """
        values = dict(tenant_id=tenant_id, agent_id=agent_id, subject_id=subject_id,
                      authority_id=authority_id, matter_ref=matter_ref, source_event_id=source_event_id,
                      agent_version=agent_version, config_hash=config_hash)
        if any(not isinstance(value, str) or not value.strip() for value in values.values()):
            raise ValueError('trusted cycle source scope must be non-empty')
        scope = (tenant_id, agent_id, subject_id, authority_id, matter_ref)
        with self._tx() as cur:
            source = cur.execute(
                'SELECT c.* FROM service_cycle_sources s JOIN service_cycles c ON c.cycle_id=s.cycle_id '
                'WHERE s.tenant_id=? AND s.agent_id=? AND s.authority_id=? AND s.source_event_id=?',
                (tenant_id, agent_id, authority_id, source_event_id)).fetchone()
            if source is not None and (source['subject_id'] != subject_id or source['matter_ref'] != matter_ref):
                raise ValueError('trusted source event 已绑定另一主体或事项')
            if source is None:
                # 同一业务事件 ID 不能换到另一受信来源/租户/Agent 重新登记。
                any_source = cur.execute(
                    'SELECT tenant_id,agent_id,authority_id FROM service_cycle_sources WHERE source_event_id=?',
                    (source_event_id,)).fetchone()
                if any_source is not None and (any_source['tenant_id'] != tenant_id
                        or any_source['agent_id'] != agent_id or any_source['authority_id'] != authority_id):
                    raise ValueError('trusted source event 已绑定另一受信来源，不能换源')
            if source is not None:
                row = source
            else:
                row = cur.execute(
                    'SELECT * FROM service_cycles WHERE tenant_id=? AND agent_id=? AND subject_id=? '
                    "AND authority_id=? AND matter_ref=? AND state='active'", scope).fetchone()
                if row is None and cur.execute(
                        'SELECT 1 FROM service_cycles WHERE tenant_id=? AND agent_id=? AND subject_id=? '
                        'AND authority_id=? AND matter_ref=? LIMIT 1', scope).fetchone():
                    raise ValueError('该主体/事项的业务周期已关闭；开启新周期须显式裁定，不能复用旧周期')
            if row is not None:
                if row['agent_version'] != agent_version or row['config_hash'] != config_hash:
                    raise ValueError('service cycle version/config hash is pinned; migration is not available')
                binding = ServiceCycleBinding(**{key: row[key] for key in ServiceCycleBinding.__dataclass_fields__})
            else:
                binding = ServiceCycleBinding(cycle_id=new_id('cycle'), **values)
                cur.execute(
                    'INSERT INTO service_cycles (cycle_id,tenant_id,agent_id,subject_id,authority_id,'
                    'matter_ref,source_event_id,agent_version,config_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (*binding.to_dict().values(), now_iso()))
            cur.execute('INSERT INTO service_cycle_sources VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                        (tenant_id, agent_id, authority_id, source_event_id, binding.cycle_id, now_iso()))
        return binding

    def _cycle_row(self, cur: sqlite3.Cursor, binding: ServiceCycleBinding,
                   authority_id: str) -> sqlite3.Row:
        """按对象解析出的绑定读取周期行，并复核 scope 与受信来源身份。"""
        row = cur.execute('SELECT * FROM service_cycles WHERE cycle_id=?', (binding.cycle_id,)).fetchone()
        if row is None or any(row[key] != value for key, value in binding.to_dict().items()):
            raise ValueError('service cycle binding does not match registered source')
        if not isinstance(authority_id, str) or not authority_id.strip() or row['authority_id'] != authority_id:
            raise ValueError('cycle authority does not match the trusted source')
        return row

    def close_service_cycle(self, binding: ServiceCycleBinding, *, authority_id: str,
                            reason: str) -> dict[str, Any]:
        """把 active 周期置为终态；关闭/撤销后旧代次不得再静默复用。"""
        if reason not in ('completed', 'cancelled'):
            raise ValueError('cycle close reason must be completed or cancelled')
        state = 'closed' if reason == 'completed' else 'cancelled'
        with self._tx() as cur:
            row = self._cycle_row(cur, binding, authority_id)
            if row['state'] != 'active':
                raise ValueError('service cycle is already terminal and cannot be closed again')
            cur.execute("UPDATE service_cycles SET state=?,closed_at=? WHERE cycle_id=? AND state='active'",
                        (state, now_iso(), binding.cycle_id))
            if cur.rowcount != 1:
                raise RuntimeError('service cycle close lost a concurrent race')
            updated = cur.execute('SELECT * FROM service_cycles WHERE cycle_id=?', (binding.cycle_id,)).fetchone()
        return dict(updated)

    def adjudicate_new_service_cycle(self, binding: ServiceCycleBinding, *, authority_id: str,
                                     source_event_id: str) -> ServiceCycleBinding:
        """显式裁定新周期：仅 completed 关闭、且尚无后继的旧周期可开启新 generation。

        新周期沿用旧周期被冻结的 agent_version/config_hash，禁止借裁定换源或换版本。
        """
        if not isinstance(source_event_id, str) or not source_event_id.strip():
            raise ValueError('new cycle source event must be a non-empty string')
        with self._tx() as cur:
            row = self._cycle_row(cur, binding, authority_id)
            if row['state'] != 'closed':
                raise ValueError('only a completed-closed cycle can be adjudicated into a new generation')
            if cur.execute('SELECT 1 FROM service_cycles WHERE predecessor_cycle_id=?',
                           (binding.cycle_id,)).fetchone():
                raise ValueError('closed cycle already has a successor generation')
            if cur.execute(
                    "SELECT 1 FROM service_cycles WHERE tenant_id=? AND agent_id=? AND subject_id=? "
                    "AND authority_id=? AND matter_ref=? AND state='active'",
                    (row['tenant_id'], row['agent_id'], row['subject_id'],
                     row['authority_id'], row['matter_ref'])).fetchone():
                raise ValueError('scope already has an active cycle')
            if cur.execute('SELECT 1 FROM service_cycle_sources WHERE source_event_id=?',
                           (source_event_id,)).fetchone():
                raise ValueError('source event already registered; cannot reuse for a new cycle')
            new_binding = ServiceCycleBinding(
                cycle_id=new_id('cycle'), tenant_id=row['tenant_id'], agent_id=row['agent_id'],
                subject_id=row['subject_id'], authority_id=row['authority_id'],
                matter_ref=row['matter_ref'], source_event_id=source_event_id,
                agent_version=row['agent_version'], config_hash=row['config_hash'])
            try:
                cur.execute(
                    'INSERT INTO service_cycles (cycle_id,tenant_id,agent_id,subject_id,authority_id,'
                    'matter_ref,source_event_id,agent_version,config_hash,created_at,generation,state,predecessor_cycle_id) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (*new_binding.to_dict().values(), now_iso(), row['generation'] + 1, 'active', binding.cycle_id))
            except sqlite3.IntegrityError as exc:
                # 可能是并发下已有 active 周期，也可能是遗留库残留的表级 scope UNIQUE；
                # 两种都失败关闭，不静默复用旧周期。
                raise ValueError('new cycle insert was rejected by a service-cycle uniqueness constraint') from exc
            cur.execute('INSERT INTO service_cycle_sources VALUES(?,?,?,?,?,?)',
                        (row['tenant_id'], row['agent_id'], row['authority_id'], source_event_id,
                         new_binding.cycle_id, now_iso()))
        return new_binding

    def service_cycle_state(self, cycle_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute('SELECT * FROM service_cycles WHERE cycle_id=?', (cycle_id,)).fetchone()
        return dict(row) if row else None

    def migrate_task_item(self, *, task_id: str, source_binding: ServiceCycleBinding,
                          target_binding: ServiceCycleBinding, authority_id: str) -> dict[str, Any]:
        """经显式双 grant 授权把未完成事项迁移到直系新周期，保留 lineage。

        已取消/完成/已迁移事项不会被复活；源周期须为 completed 关闭且目标是其直系后继。
        """
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError('migration task id must be non-empty')
        with self._tx() as cur:
            source = self._cycle_row(cur, source_binding, authority_id)
            target = self._cycle_row(cur, target_binding, authority_id)
            if source_binding.cycle_id == target_binding.cycle_id:
                raise ValueError('migration requires distinct source and target cycles')
            if source['state'] != 'closed':
                raise ValueError('migration source cycle must be completed-closed, not active or cancelled')
            if target['state'] != 'active':
                raise ValueError('migration target cycle must be active')
            if (target['predecessor_cycle_id'] != source['cycle_id']
                    or target['generation'] != source['generation'] + 1):
                raise ValueError('migration requires direct successor lineage')
            for key in ('tenant_id', 'agent_id', 'subject_id', 'authority_id', 'matter_ref'):
                if source[key] != target[key]:
                    raise ValueError('migration cycles must share the same business scope')
            task = cur.execute('SELECT * FROM task_items WHERE task_id=?', (task_id,)).fetchone()
            if task is None:
                raise KeyError(f'未知 TaskItem {task_id}')
            if task['service_cycle_id'] != source['cycle_id']:
                raise ValueError('task item belongs to a different service cycle')
            if task['state'] in ('cancelled', 'done', 'migrated'):
                raise ValueError('terminal or cancelled task item cannot be migrated or resurrected')
            if task['state'] not in ('scheduled', 'waiting_condition', 'ready'):
                raise ValueError('task item state is not a migratable unfinished state')
            if cur.execute('SELECT 1 FROM service_cycle_migrations WHERE source_task_id=?',
                           (task_id,)).fetchone():
                raise ValueError('task item has already been migrated')
            root = task_id
            prior = cur.execute(
                'SELECT root_task_id FROM service_cycle_migrations WHERE target_task_id=?',
                (task_id,)).fetchone()
            if prior is not None:
                root = prior['root_task_id']
            new_task_id, timestamp = new_id('task'), now_iso()
            cur.execute(
                "INSERT INTO task_items (task_id,tenant_id,agent_id,subject_id,service_cycle_id,"
                "purpose,source_agent_version,state,revision,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,'scheduled',1,?,?)",
                (new_task_id, task['tenant_id'], task['agent_id'], task['subject_id'],
                 target_binding.cycle_id, task['purpose'], task['source_agent_version'], timestamp, timestamp))
            cur.execute(
                "UPDATE task_items SET state='migrated',revision=revision+1,updated_at=? "
                'WHERE task_id=? AND state=?', (timestamp, task_id, task['state']))
            if cur.rowcount != 1:
                raise RuntimeError('task item migration lost a concurrent race')
            cur.execute(
                'INSERT INTO service_cycle_migrations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (new_id('migration'), source['tenant_id'], source['agent_id'], source['subject_id'],
                 source['cycle_id'], target['cycle_id'], task_id, new_task_id, root,
                 authority_id, timestamp))
            migrated = cur.execute('SELECT * FROM task_items WHERE task_id=?', (new_task_id,)).fetchone()
        return dict(migrated)

    def service_cycle_migration_rows(self, *, source_cycle_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if source_cycle_id is None:
                rows = self._conn.execute(
                    'SELECT * FROM service_cycle_migrations ORDER BY migrated_at,migration_id').fetchall()
            else:
                rows = self._conn.execute(
                    'SELECT * FROM service_cycle_migrations WHERE source_cycle_id=? '
                    'ORDER BY migrated_at,migration_id', (source_cycle_id,)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _cycle_json(binding: ServiceCycleBinding | None) -> str | None:
        return json.dumps(binding.to_dict(), sort_keys=True, ensure_ascii=False) if binding else None

    def _validate_cycle(self, cur: sqlite3.Cursor, binding: ServiceCycleBinding,
                        request: ServiceRequest, run: Run) -> None:
        row = cur.execute('SELECT * FROM service_cycles WHERE cycle_id=?', (binding.cycle_id,)).fetchone()
        if row is None or any(row[key] != value for key, value in binding.to_dict().items()):
            raise ValueError('service cycle binding does not match registered source')
        # 关闭/撤销是终态：旧 generation 的绑定不得再受理新请求或预约计数。
        if row['state'] != 'active':
            raise ValueError('service cycle is closed or cancelled; old generation cannot be admitted')
        if (request.persistent_subject != binding.subject_id or request.tenant_id != binding.tenant_id
                or request.agent_version != binding.agent_version or run.tenant_id != binding.tenant_id
                or run.agent_version != binding.agent_version or run.request_id != request.request_id
                or run.snapshot.get('agent_id') != binding.agent_id
                or run.snapshot.get('service_cycle') != binding.to_dict()
                or run.snapshot.get('cycle_config_hash') != binding.config_hash
                or cycle_config_hash(run.snapshot.get('orchestration'), run.snapshot.get('unit_skill_bindings', {})) != binding.config_hash):
            raise ValueError('service cycle scope/version/config binding mismatch')

    def reserve_service_cycle(self, run_id: str, *, generation: int, binding: ServiceCycleBinding,
                              kind: str, layer: tuple[str, ...], identity: str, max_rounds: int,
                              event: RunEvent, minimum: int = 0) -> dict[str, Any]:
        """计数与审计同事务；消耗只增不减，不持锁跨任何模型调用。"""
        if (kind not in {'loop', 'fallback'} or not isinstance(identity, str) or not identity
                or type(max_rounds) is not int or max_rounds < 1
                or type(minimum) is not int or minimum < 0
                or not isinstance(layer, tuple) or any(not isinstance(part, str) or not part for part in layer)):
            raise ValueError('invalid service cycle reservation')
        key = json.dumps([kind, *layer, identity], ensure_ascii=False, separators=(',', ':'))
        with self._tx() as cur:
            row = cur.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if row is None or row['status'] != RunStatus.RUNNING.value or row['occupancy_generation'] != generation:
                raise RuntimeError('inactive or stale run generation cannot reserve service cycle')
            request_row = cur.execute('SELECT * FROM requests WHERE request_id=?', (row['request_id'],)).fetchone()
            request = ServiceRequest(request_id=row['request_id'], tenant_id=request_row['tenant_id'],
                agent_version=request_row['agent_version'], channel=Channel(request_row['channel']),
                state=RequestState(request_row['state']), subject_id=request_row['subject_id'],
                subject_scope=request_row['subject_scope'], service_cycle=binding)
            snapshot = json.loads(row['snapshot_json'])
            run = Run(run_id=run_id, request_id=row['request_id'], tenant_id=row['tenant_id'],
                      agent_version=row['agent_version'], owner_id=row['owner_id'], snapshot=snapshot)
            if (request_row['service_cycle_json'] != self._cycle_json(binding)
                    or request_row['state'] != RequestState.RUNNING.value):
                raise ValueError('request cycle binding/state changed')
            self._validate_cycle(cur, binding, request, run)
            limit, counter_field = GraphRuntime(snapshot['orchestration']).cycle_budget(kind, layer, identity)
            if limit != max_rounds:
                raise ValueError('reservation limit does not match pinned graph contract')
            if (event.run_id != run_id or event.request_id != run.request_id
                    or event.tenant_id != run.tenant_id or event.agent_version != run.agent_version):
                raise ValueError('reservation event scope mismatch')
            counter = cur.execute('SELECT count FROM service_cycle_counters WHERE cycle_id=? AND budget_key=?',
                                  (binding.cycle_id, key)).fetchone()
            previous = max(counter['count'] if counter else 0, minimum)
            allowed = previous < max_rounds
            count = previous + (1 if kind == 'loop' or allowed else 0)
            cur.execute('INSERT INTO service_cycle_counters VALUES(?,?,?) ON CONFLICT(cycle_id,budget_key) '
                        'DO UPDATE SET count=excluded.count', (binding.cycle_id, key, count))
            event.event_type = 'route.graph.cycle' if kind == 'loop' else 'route.graph.fallback_cycle'
            event.payload.update(service_cycle=binding.to_dict(), budget_key=key, budget_kind=kind,
                edge_id=identity if kind == 'loop' else None, target=identity if kind == 'fallback' else None,
                layer=list(layer), cycle_count=count, max_rounds=max_rounds, allowed=allowed,
                occupancy_generation=generation, reservation='durable')
            event.payload['counter'] = counter_field
            tail = cur.execute('SELECT seq FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1', (run_id,)).fetchone()
            event.seq = max(event.seq, tail['seq'] + 1 if tail else 0)
            self._append(cur, [event])
        return {'count': count, 'allowed': allowed, 'event': event}

    def service_cycle_counts(self, cycle_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute('SELECT budget_key,count FROM service_cycle_counters WHERE cycle_id=?',
                                      (cycle_id,)).fetchall()
        return {row['budget_key']: row['count'] for row in rows}

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
                "SELECT status,finish_reason,agent_version,tenant_id FROM runs WHERE run_id=? AND request_id=?",
                (previous_run_id, request.request_id),
            ).fetchone()
            if previous is None or previous["status"] != RunStatus.FAILED.value or previous["finish_reason"] not in {"restart_interrupted", "wake_superseded"}:
                raise RuntimeError("请求旧运行不是可恢复的重启中断")
            if previous["agent_version"] != run.agent_version or previous["tenant_id"] != run.tenant_id:
                raise RuntimeError("恢复运行的租户或 AgentVersion 与等待快照不匹配")
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
            "SELECT * FROM requests WHERE request_id=?", (request.request_id,),
        ).fetchone()
        if existing is not None and existing["tenant_id"] != request.tenant_id:
            raise ValueError("request_id 不属于当前租户")
        binding_json = self._cycle_json(request.service_cycle)
        if existing is not None and (existing['service_cycle_json'] is not None or binding_json is not None):
            if (existing['service_cycle_json'] != binding_json or existing['agent_version'] != request.agent_version
                    or existing['subject_id'] != request.persistent_subject
                    or existing['subject_scope'] != str(request.subject_scope)):
                raise ValueError('request service cycle binding is immutable')
        if request.service_cycle is not None:
            self._validate_cycle(cur, request.service_cycle, request, run)
            active = cur.execute("SELECT 1 FROM runs WHERE request_id=? AND status IN ('running','waiting') LIMIT 1",
                                 (request.request_id,)).fetchone()
            if active is not None:
                raise RuntimeError('bound request already has an active running/waiting generation')
        elif run.snapshot.get('service_cycle') is not None:
            raise ValueError('run cannot invent request service cycle binding')
        cur.execute(
            "INSERT INTO requests(request_id, tenant_id, agent_version, channel, state,"
            " subject_id, subject_scope, trigger_kind, trigger_ref, created_at, updated_at, trigger_event_id, service_cycle_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(request_id) DO UPDATE SET state=excluded.state,"
            " updated_at=excluded.updated_at",
            (
                request.request_id, request.tenant_id, request.agent_version,
                str(request.channel), str(request.state), request.persistent_subject,
                str(request.subject_scope), request.trigger_kind, request.trigger_ref,
                request.created_at, request.updated_at, request.trigger_event_id, binding_json,
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
                req['service_cycle'] = json.loads(req.pop('service_cycle_json') or 'null')
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

    def suspend_wait(
        self,
        run_id: str,
        *,
        request_state: str = "waiting",
        waiting_on: str,
        generation: int,
        timeout_ms: int | None = None,
        timeout_to: str | None = None,
        metadata: dict[str, Any] | None = None,
        event: RunEvent | None = None,
        events: list[RunEvent] | None = None,
    ) -> dict[str, Any]:
        """Atomically park a running run and record its wake contract."""
        if not waiting_on:
            raise ValueError("waiting_on must be non-empty")
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(f"未知 run {run_id}")
            if row["status"] != RunStatus.RUNNING.value:
                raise RuntimeError("只有 running run 可以进入 waiting")
            if int(row["occupancy_generation"]) != int(generation):
                raise RuntimeError("旧 generation 不得挂起运行")
            now = now_iso()
            cur.execute(
                "UPDATE runs SET status=? WHERE run_id=? AND status=?",
                (RunStatus.WAITING.value, run_id, RunStatus.RUNNING.value),
            )
            cur.execute(
                "UPDATE requests SET state=?,updated_at=? WHERE request_id=?",
                (request_state, now, row["request_id"]),
            )
            wait_id = f"wait_{uuid.uuid4().hex[:16]}"
            cur.execute(
                "INSERT INTO run_waits(wait_id,run_id,request_id,tenant_id,agent_version,generation,"
                "waiting_on,timeout_ms,timeout_to,state,metadata_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (wait_id, run_id, row["request_id"], row["tenant_id"], row["agent_version"],
                 generation, waiting_on, timeout_ms, timeout_to, "waiting",
                 json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            if event is not None:
                self._append(cur, [event])
            if events:
                self._append(cur, events)
            return {"wait_id": wait_id, "run_id": run_id, "request_id": row["request_id"],
                    "generation": generation, "waiting_on": waiting_on,
                    "timeout_ms": timeout_ms, "timeout_to": timeout_to,
                    "state": "waiting", "metadata": metadata or {}}

    def wait_row(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM run_waits WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = json.loads(data.pop("metadata_json"))
        return data

    def due_waits(self, *, now: str | None = None, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List parked waits whose declared timeout has elapsed; read-only."""
        moment = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        with self._lock:
            query = "SELECT * FROM run_waits WHERE state='waiting' AND timeout_ms IS NOT NULL"
            params: list[Any] = []
            if tenant_id is not None:
                query += " AND tenant_id=?"
                params.append(tenant_id)
            rows = self._conn.execute(query, params).fetchall()
        out = []
        for row in rows:
            deadline = datetime.fromisoformat(row["created_at"]) + timedelta(milliseconds=int(row["timeout_ms"]))
            if moment >= deadline:
                item = dict(row)
                item["deadline"] = deadline.isoformat()
                item["metadata"] = json.loads(item.pop("metadata_json"))
                out.append(item)
        return out

    def cancel_wait(self, run_id: str, *, tenant_id: str, reason: str, events: list[RunEvent]) -> None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM run_waits WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError("未知 waiting run")
            if row["tenant_id"] != tenant_id or row["state"] != "waiting":
                raise RuntimeError("waiting 不属于当前租户或已结束")
            now = now_iso()
            cur.execute("UPDATE run_waits SET state='cancelled',updated_at=? WHERE run_id=? AND state='waiting'", (now, run_id))
            cur.execute("UPDATE runs SET status='cancelled',ended_at=?,finish_reason=? WHERE run_id=? AND status='waiting'", (now, reason, run_id))
            cur.execute("UPDATE requests SET state='cancelled',updated_at=? WHERE request_id=?", (now, row["request_id"]))
            self._append(cur, events)

    def wake_wait(
        self,
        run_id: str,
        *,
        tenant_id: str,
        agent_version: str,
        generation: int,
        wake_kind: str,
        events: list[RunEvent] | None = None,
        wake_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consume a wait once and fence its parked generation."""
        with self._tx() as cur:
            row = cur.execute(
                "SELECT w.*,r.status FROM run_waits w JOIN runs r ON r.run_id=w.run_id "
                "WHERE w.run_id=?", (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("未知 waiting run")
            if row["state"] != "waiting" or row["status"] != RunStatus.WAITING.value:
                raise RuntimeError("waiting 已被唤醒或已结束")
            if row["tenant_id"] != tenant_id or row["agent_version"] != agent_version:
                raise RuntimeError("租户或 AgentVersion 不匹配")
            if int(row["generation"]) != int(generation):
                raise RuntimeError("wake generation 不匹配")
            if wake_kind == "timeout":
                if row["timeout_ms"] is None:
                    raise RuntimeError("该等待没有声明 timeoutMs")
                deadline = datetime.fromisoformat(row["created_at"]) + timedelta(milliseconds=int(row["timeout_ms"]))
                if datetime.now(timezone.utc) < deadline:
                    raise RuntimeError("等待尚未达到 timeoutMs")
            now = now_iso()
            metadata = json.loads(row["metadata_json"])
            if wake_state is not None:
                metadata["wake"] = {"kind": wake_kind, "routing_state": wake_state}
            cur.execute("UPDATE run_waits SET state='woken',metadata_json=?,updated_at=? WHERE run_id=? AND state='waiting'",
                        (json.dumps(metadata, ensure_ascii=False), now, run_id))
            cur.execute("UPDATE runs SET status='failed',ended_at=?,finish_reason=? WHERE run_id=? AND status=?",
                        (now, "wake_superseded", run_id, RunStatus.WAITING.value))
            cur.execute("UPDATE requests SET state='queued',updated_at=? WHERE request_id=?", (now, row["request_id"]))
            if events:
                self._append(cur, events)
            result = dict(row)
            result["wake_kind"] = wake_kind
            result.pop("metadata_json")
            result["metadata"] = metadata
            result["state"] = "woken"
            return result

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

    def update_run_snapshot(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError('snapshot patch must be an object')
        with self._tx() as cur:
            row = cur.execute('SELECT snapshot_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if row is None: raise KeyError('未知 run')
            snapshot = json.loads(row['snapshot_json'])
            if snapshot.get('service_cycle') is not None and any(
                key in patch and patch[key] != snapshot.get(key)
                for key in ('service_cycle', 'cycle_config_hash', 'agent_id', 'orchestration', 'unit_skill_bindings')
            ):
                raise ValueError('bound service cycle snapshot is immutable')
            snapshot.update(patch)
            cur.execute('UPDATE runs SET snapshot_json=? WHERE run_id=?',
                        (json.dumps(snapshot, ensure_ascii=False), run_id))
        return snapshot

    def read_run_status(
        self, *, tenant_id: str, agent_id: str, run_id: str,
    ) -> dict[str, Any] | None:
        """Return a redacted run summary with explicit persisted Agent attribution."""
        with self._lock:
            row = self._conn.execute(
                "SELECT r.run_id,r.request_id,r.agent_version,r.status AS run_status,"
                "r.started_at,r.ended_at,r.finish_reason,q.state AS request_state,"
                "COUNT(e.rid) AS event_count,MAX(e.ts) AS latest_event_at "
                "FROM runs r JOIN requests q ON q.request_id=r.request_id "
                "JOIN configuration_stable_versions v ON v.tenant_id=r.tenant_id "
                "AND v.agent_id=? AND v.version_id=r.agent_version "
                "LEFT JOIN events e ON e.run_id=r.run_id "
                "WHERE r.tenant_id=? AND r.run_id=? "
                "AND CASE WHEN json_valid(r.snapshot_json) "
                "THEN json_extract(r.snapshot_json,'$.agent_id') ELSE NULL END=? "
                "GROUP BY r.run_id,q.state",
                (agent_id, tenant_id, run_id, agent_id),
            ).fetchone()
        return dict(row) if row else None

    def read_run_diagnostics(
        self, *, tenant_id: str, agent_id: str, run_id: str,
        after_sequence: int = -1, limit: int = 100,
    ) -> dict[str, Any] | None:
        """Project persisted recall/context decisions without exposing source text."""
        if (not all(isinstance(value, str) and value.strip() for value in (tenant_id, agent_id, run_id))
                or type(after_sequence) is not int or after_sequence < -1 or after_sequence > (1 << 63) - 1
                or type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError("运行诊断范围或分页参数无效")
        with self._lock:
            run = self._conn.execute(
                "SELECT r.run_id,r.request_id,r.agent_version,r.status AS run_status,"
                "r.started_at,r.ended_at,r.finish_reason,q.state AS request_state "
                "FROM runs r JOIN requests q ON q.request_id=r.request_id "
                "JOIN configuration_stable_versions v ON v.tenant_id=r.tenant_id "
                "AND v.agent_id=? AND v.version_id=r.agent_version "
                "WHERE r.tenant_id=? AND r.run_id=? "
                "AND CASE WHEN json_valid(r.snapshot_json) "
                "THEN json_extract(r.snapshot_json,'$.agent_id') ELSE NULL END=?",
                (agent_id, tenant_id, run_id, agent_id),
            ).fetchone()
            if run is None:
                return None
            rows = self._conn.execute(
                "SELECT seq,event_type,ts,event_json FROM events "
                "WHERE run_id=? AND seq>? AND event_type IN ('recall.diagnostic','context.fragment') "
                "ORDER BY seq LIMIT ?",
                (run_id, after_sequence, limit + 1),
            ).fetchall()

        has_more = len(rows) > limit
        page = rows[:limit]
        diagnostics = []
        recall_codes = {
            "invalid_concurrent_limit", "invalid_load_scope", "before_load_scope",
            "excluded_current_unit", "unavailable_skill_context", "selector_failed",
            "no_eligible_candidates", "invalid_selection", "selected",
        }
        valid_scopes = {"global", "task", "skill", "evidence"}
        valid_stages = {"baseline", "task_local", "on_demand", "concurrent", "reply_generation"}
        valid_load_statuses = {"loaded", "skipped", "expired", "budget_capped"}

        def bounded_int(value: Any, maximum: int) -> int | None:
            return value if type(value) is int and 0 <= value <= maximum else None

        def safe_unit_id(value: Any) -> bool:
            return (isinstance(value, str) and bool(value.strip()) and len(value) <= 128
                    and all(character.isprintable() for character in value))

        for row in page:
            try:
                event = json.loads(row["event_json"])
                payload = event.get("payload") if isinstance(event, dict) else None
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            item: dict[str, Any] = {"sequence": row["seq"], "at": row["ts"]}
            if row["event_type"] == "recall.diagnostic":
                item["kind"] = "recall"
                if isinstance(payload.get("code"), str) and payload["code"] in recall_codes:
                    item["code"] = payload["code"]
                for key in ("candidate_count", "selected_count", "max_units"):
                    value = bounded_int(payload.get(key), 100_000)
                    if value is not None:
                        item[key] = value
                if safe_unit_id(payload.get("unit_id")):
                    item["unit_id"] = payload["unit_id"]
                selected = payload.get("selected_unit_ids")
                if isinstance(selected, list) and len(selected) <= 100 and all(safe_unit_id(value) for value in selected):
                    item["selected_unit_ids"] = selected
                provider = payload.get("provider")
                if isinstance(provider, str) and provider in {"injected", "deterministic-keyword-v1"}:
                    item["provider"] = provider
                if type(payload.get("diagnostic_only")) is bool:
                    item["diagnostic_only"] = payload["diagnostic_only"]
            else:
                item["kind"] = "context"
                if isinstance(payload.get("scope"), str) and payload["scope"] in valid_scopes:
                    item["scope"] = payload["scope"]
                if isinstance(payload.get("stage"), str) and payload["stage"] in valid_stages:
                    item["stage"] = payload["stage"]
                if isinstance(payload.get("load_status"), str) and payload["load_status"] in valid_load_statuses:
                    item["status"] = payload["load_status"]
                value = bounded_int(payload.get("token_estimate"), 1_000_000)
                if value is not None:
                    item["token_estimate"] = value
            diagnostics.append(item)

        return {
            "run": dict(run), "events": diagnostics,
            "next_cursor": page[-1]["seq"] if page else after_sequence,
            "has_more": has_more,
        }

    def read_graph_overlay(
        self, *, tenant_id: str, agent_id: str, version_id: str,
        from_ts: str, to_ts: str, channel: str | None = None,
    ) -> dict[str, Any]:
        """Read the run-overlay-v1 projection under a persisted agent scope.

        A version ID is only unique within an agent. Legacy Runs without an
        explicit, server-owned snapshot.agent_id cannot be attributed safely and
        are excluded; registering a matching version never grants access to them.
        See run_overlay for cohort, reach, missing-evidence and timing semantics.
        """
        from .run_overlay import aggregate_graph_events, timestamp

        if not all(isinstance(value, str) and value.strip() for value in (tenant_id, agent_id, version_id, from_ts, to_ts)):
            raise ValueError("租户、专家、版本和时间窗必须是非空字符串")
        if channel is not None and channel not in ("text", "voice"):
            raise ValueError("channel 必须是 text、voice 或省略")
        start, end = timestamp(from_ts), timestamp(to_ts)
        if start is None or end is None or end <= start:
            raise ValueError("时间窗必须带时区且结束时间晚于开始时间")
        with self._lock:
            stable = self._conn.execute(
                "SELECT 1 FROM configuration_stable_versions "
                "WHERE tenant_id=? AND agent_id=? AND version_id=?",
                (tenant_id, agent_id, version_id),
            ).fetchone()
            if stable is None:
                raise KeyError("未找到授权范围内的稳定版本")
            rows = self._conn.execute(
                "SELECT e.run_id,e.seq,e.event_type,e.ts,e.event_json,"
                "e.request_id AS event_request_id,r.request_id AS run_request_id "
                "FROM events e JOIN runs r ON r.run_id=e.run_id "
                "WHERE r.tenant_id=? AND r.agent_version=? "
                "AND CASE WHEN json_valid(r.snapshot_json) "
                "THEN json_extract(r.snapshot_json,'$.agent_id') ELSE NULL END=? "
                "AND e.event_type IN ('route.graph.started','route.graph.step','route.graph.finished') "
                "ORDER BY e.run_id,e.seq",
                (tenant_id, version_id, agent_id),
            ).fetchall()
        return aggregate_graph_events(
            rows, tenant_id=tenant_id, agent_id=agent_id, version_id=version_id,
            start=start, end=end, channel=channel,
        )

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

    def state_window_counts(self, *, tenant_id: str, agent_id: str, agent_version: str,
                            cycle_id: str | None = None, now: str | None = None) -> dict[str, dict[str, int]]:
        moment = datetime.fromisoformat(now.replace('Z', '+00:00')) if now else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            raise ValueError('state-window clock must include a timezone')
        moment = moment.astimezone(timezone.utc)
        cutoff = (moment - timedelta(hours=24)).isoformat()
        current = moment.isoformat()
        if not all(isinstance(value, str) and value.strip() for value in (tenant_id, agent_id, agent_version)):
            raise ValueError('state-window tenant, agent, and version must be non-empty strings')
        scope = ('r.tenant_id=? AND r.agent_version=? AND CASE WHEN json_valid(r.snapshot_json) '
                 "THEN json_extract(r.snapshot_json,'$.agent_id') ELSE NULL END=?")
        params: tuple[Any, ...] = (tenant_id, agent_version, agent_id)
        cycle_scope = ''
        cycle_params: tuple[Any, ...] = ()
        request_join = ''
        with self._lock:
            if cycle_id is not None:
                cycle = self._conn.execute(
                    'SELECT cycle_id FROM service_cycles WHERE cycle_id=? AND tenant_id=? AND agent_id=? AND agent_version=?',
                    (cycle_id, tenant_id, agent_id, agent_version),
                ).fetchone()
                if cycle is None:
                    raise ValueError('state-window service cycle is unavailable for this tenant, agent, and version')
                cycle_scope = " AND json_extract(q.service_cycle_json,'$.cycle_id')=?"
                cycle_params = (cycle_id,)
                request_join = ' JOIN requests q ON q.request_id=r.request_id'
            runs_24h = self._conn.execute(
                f'SELECT COUNT(*) AS n FROM runs r{request_join} WHERE {scope}'
                f'{cycle_scope} AND r.started_at>=? AND r.started_at<=?',
                (*params, *cycle_params, cutoff, current),
            ).fetchone()['n']
            runs_total = self._conn.execute(
                f'SELECT COUNT(*) AS n FROM runs r{request_join} WHERE {scope}{cycle_scope}',
                (*params, *cycle_params),
            ).fetchone()['n']
            attempts_24h = self._conn.execute(
                f'SELECT COUNT(*) AS n FROM tool_attempts t JOIN runs r ON r.run_id=t.run_id '
                f'{request_join} WHERE {scope}{cycle_scope} AND t.created_at>=? AND t.created_at<=?',
                (*params, *cycle_params, cutoff, current),
            ).fetchone()['n']
            attempts_total = self._conn.execute(
                f'SELECT COUNT(*) AS n FROM tool_attempts t JOIN runs r ON r.run_id=t.run_id'
                f'{request_join} WHERE {scope}{cycle_scope}', (*params, *cycle_params),
            ).fetchone()['n']
            counts = {
                'attempts': {'24h': int(attempts_24h), 'forever': int(attempts_total)},
                'runs': {'24h': int(runs_24h), 'forever': int(runs_total)},
            }
            if cycle_id is not None:
                counts['attempts']['cycle'] = int(attempts_total)
                counts['runs']['cycle'] = int(runs_total)
        return counts

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
        for key in ("config_json", "diff_json", "review_summary_json", "layer_path_json"):
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

    def list_config_advisory_dismissals(
        self, *, tenant_id: str, agent_id: str, source_revision: int,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM configuration_advisory_dismissals "
                "WHERE tenant_id=? AND agent_id=? AND source_revision=? ORDER BY advisory_key",
                (tenant_id, agent_id, source_revision),
            ).fetchall()
        return [self._config_row(row) for row in rows]

    def dismiss_config_advisory(
        self, *, tenant_id: str, agent_id: str, source_revision: int,
        advisory_key: str, layer_path: list[str], closed_set_size: int, actor_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            draft = cur.execute(
                "SELECT revision FROM configuration_drafts WHERE tenant_id=? AND agent_id=?",
                (tenant_id, agent_id),
            ).fetchone()
            if draft is None:
                raise KeyError("未知配置草稿")
            if draft["revision"] != source_revision:
                raise StaleConfigurationRevision("草稿 revision 已变化")
            frozen = cur.execute(
                "SELECT 1 FROM change_proposals WHERE tenant_id=? AND agent_id=? AND source_revision=? LIMIT 1",
                (tenant_id, agent_id, source_revision),
            ).fetchone()
            if frozen:
                raise ValueError("此草稿 revision 已冻结，不能再增加评审留痕")
            cur.execute(
                "INSERT OR IGNORE INTO configuration_advisory_dismissals "
                "(tenant_id,agent_id,source_revision,advisory_key,layer_path_json,closed_set_size,actor_id,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (tenant_id, agent_id, source_revision, advisory_key, self._config_json(layer_path),
                 closed_set_size, actor_id, now_iso()),
            )
            row = cur.execute(
                "SELECT * FROM configuration_advisory_dismissals "
                "WHERE tenant_id=? AND agent_id=? AND source_revision=? AND advisory_key=?",
                (tenant_id, agent_id, source_revision, advisory_key),
            ).fetchone()
            return self._config_row(row)

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
            dismissals = cur.execute(
                "SELECT * FROM configuration_advisory_dismissals "
                "WHERE tenant_id=? AND agent_id=? AND source_revision=? ORDER BY advisory_key",
                (tenant_id, agent_id, expected_revision),
            ).fetchall()
            review_summary = [{
                "advisory_key": item["advisory_key"],
                "layer_path": json.loads(item["layer_path_json"]),
                "closed_set_size": item["closed_set_size"],
                "actor_id": item["actor_id"],
                "created_at": item["created_at"],
                "source_revision": item["source_revision"],
            } for item in dismissals]
            cur.execute(
                "INSERT INTO change_proposals"
                " (tenant_id,agent_id,candidate_id,idempotency_key,source_revision,base_version_id,"
                "config_json,content_hash,diff_json,review_summary_json,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,'frozen',?)",
                (tenant_id, agent_id, candidate_id, idempotency_key, expected_revision,
                 draft["base_version_id"], config_json, content_hash,
                 json.dumps(diff, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                 json.dumps(review_summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")), now_iso()),
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

    def list_sandbox_entries(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT e.*,r.candidate_id,r.content_hash,r.knowledge_state "
                "FROM sandbox_entries e JOIN sandbox_releases r ON r.release_id=e.release_id "
                "WHERE e.tenant_id=? AND e.agent_id=? AND e.environment='sandbox' "
                "ORDER BY e.entry_id",
                (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

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

    def enable_contact_page(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
        expected_version_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            release = self._contact_release(cur, tenant_id=tenant_id, agent_id=agent_id,
                                            entry_id=entry_id, current_entry=True)
            if release is None:
                raise KeyError("未知或未经批准的沙盒入口")
            if expected_version_id is not None and release['version_id'] != expected_version_id:
                raise RuntimeError('入口版本已变化，请重新查看批准版本')
            cur.execute(
                "INSERT INTO customer_contact_pages "
                "(tenant_id,agent_id,entry_id,release_id,version_id,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'active',?,?) "
                "ON CONFLICT(tenant_id,agent_id,entry_id) DO UPDATE SET "
                "release_id=excluded.release_id,version_id=excluded.version_id,state='active',updated_at=excluded.updated_at",
                (tenant_id, agent_id, entry_id, release["release_id"], release["version_id"], timestamp, timestamp),
            )
            row = cur.execute(
                "SELECT * FROM customer_contact_pages WHERE tenant_id=? AND agent_id=? AND entry_id=?",
                (tenant_id, agent_id, entry_id),
            ).fetchone()
        return dict(row)

    @staticmethod
    def _contact_release(
        cur, *, tenant_id: str, agent_id: str, entry_id: str, current_entry: bool = False,
    ) -> dict[str, Any] | None:
        table = "sandbox_entries" if current_entry else "customer_contact_pages"
        state = "e.environment='sandbox'" if current_entry else "e.state='active'"
        row = cur.execute(
            "SELECT e.*,r.candidate_id,r.content_hash,r.config_json,r.knowledge_state "
            f"FROM {table} e JOIN sandbox_releases r ON r.release_id=e.release_id "
            "AND r.tenant_id=e.tenant_id AND r.agent_id=e.agent_id AND r.version_id=e.version_id "
            "JOIN release_approvals a ON a.tenant_id=r.tenant_id AND a.agent_id=r.agent_id "
            "AND a.candidate_id=r.candidate_id AND a.content_hash=r.content_hash "
            "AND a.version_id=r.version_id AND a.entry_id=e.entry_id AND a.environment=r.environment "
            f"WHERE e.tenant_id=? AND e.agent_id=? AND e.entry_id=? AND {state} AND r.environment='sandbox'",
            (tenant_id, agent_id, entry_id),
        ).fetchone()
        if row is None:
            return None
        value = dict(row)
        contact_paths(agent_id, entry_id, value["version_id"])
        if value["knowledge_state"] != "ready":
            raise RuntimeError("联系页所绑知识版本待重新验收")
        config = json.loads(value.pop("config_json"))
        if not isinstance(config, dict):
            raise ValueError("联系页配置损坏，请修复并重新批准版本")
        value["contact"] = validate_contact(config.get("contact", {}))
        value['widget'] = config.get('widget', {})
        return value

    def contact_page(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            return self._contact_release(self._conn, tenant_id=tenant_id,
                                         agent_id=agent_id, entry_id=entry_id)

    def disable_contact_page(
        self, *, tenant_id: str, agent_id: str, entry_id: str,
    ) -> dict[str, Any]:
        with self._tx() as cur:
            cur.execute(
                "UPDATE customer_contact_pages SET state='disabled',updated_at=? "
                "WHERE tenant_id=? AND agent_id=? AND entry_id=? AND state='active'",
                (now_iso(), tenant_id, agent_id, entry_id),
            )
            row = cur.execute(
                "SELECT * FROM customer_contact_pages WHERE tenant_id=? AND agent_id=? AND entry_id=?",
                (tenant_id, agent_id, entry_id),
            ).fetchone()
            if row is None:
                raise KeyError("联系页未启用")
        return dict(row)

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

    def begin_material_derivation(self, *, tenant_id: str, agent_id: str,
                                  asset_id: str, version_id: str, source_hash: str) -> dict[str, Any]:
        with self._tx() as cur:
            source = cur.execute(
                'SELECT a.state,v.expires_at,v.content_hash FROM material_assets a '
                'JOIN material_versions v ON v.version_id=a.current_version_id '
                'WHERE a.tenant_id=? AND a.agent_id=? AND a.asset_id=? AND v.version_id=?',
                (tenant_id, agent_id, asset_id, version_id),
            ).fetchone()
            if (source is None or source['state'] != 'active' or source['content_hash'] != source_hash
                    or (source['expires_at'] and source['expires_at'] <= now_iso())):
                raise RuntimeError('物料版本或授权已变化，拒绝处理')
            job_id = f'media_{uuid.uuid4().hex}'
            cur.execute('INSERT INTO material_derivative_jobs VALUES(?,?,?,?,?,?,?,NULL,?,NULL)',
                        (job_id, tenant_id, agent_id, asset_id, version_id, source_hash, 'processing', now_iso()))
            return dict(cur.execute('SELECT * FROM material_derivative_jobs WHERE job_id=?', (job_id,)).fetchone())

    def finish_material_derivation(self, *, tenant_id: str, agent_id: str, job_id: str,
                                   status: str, error_code: str, artifacts: list[Any]) -> dict[str, Any]:
        if status not in {'ready', 'failed', 'unavailable'} or (status == 'ready') != bool(artifacts):
            raise ValueError('处理状态与实际文件不一致')
        with self._tx() as cur:
            job = cur.execute('SELECT * FROM material_derivative_jobs WHERE job_id=? AND tenant_id=? AND agent_id=?',
                              (job_id, tenant_id, agent_id)).fetchone()
            if job is None:
                raise KeyError('未知处理作业')
            if job['status'] != 'processing':
                raise RuntimeError('处理作业已结束')
            source = cur.execute(
                'SELECT a.state,v.expires_at,v.content_hash FROM material_assets a '
                'JOIN material_versions v ON v.version_id=a.current_version_id '
                'WHERE a.tenant_id=? AND a.agent_id=? AND a.asset_id=? AND v.version_id=?',
                (tenant_id, agent_id, job['asset_id'], job['version_id']),
            ).fetchone()
            if (source is None or source['state'] != 'active' or source['content_hash'] != job['source_hash']
                    or (source['expires_at'] and source['expires_at'] <= now_iso())):
                status, error_code, artifacts = 'discarded', 'source_changed', []
            items = []
            for artifact in artifacts:
                digest = hashlib.sha256(artifact.content).hexdigest()
                if (not artifact.content or len(artifact.content) >= 10 * 1024 * 1024
                        or artifact.metadata.get('source_hash') != job['source_hash']
                        or artifact.metadata.get('content_hash') != digest):
                    raise ValueError('派生文件字节与处理证据不一致')
                derivative_id = f'derivative_{uuid.uuid4().hex}'
                cur.execute('INSERT INTO material_derivatives VALUES(?,?,?,?,?,?,?,?)',
                    (derivative_id, job_id, artifact.kind, artifact.filename, artifact.media_type, digest,
                     sqlite3.Binary(artifact.content), json.dumps(artifact.metadata, ensure_ascii=False)))
                items.append({'derivative_id': derivative_id, 'asset_id': job['asset_id'],
                    'version_id': job['version_id'], 'kind': artifact.kind, 'filename': artifact.filename,
                    'media_type': artifact.media_type, 'content_hash': digest, 'metadata': artifact.metadata})
            cur.execute('UPDATE material_derivative_jobs SET status=?,error_code=?,finished_at=? WHERE job_id=?',
                        (status, error_code or None, now_iso(), job_id))
            finished = dict(cur.execute('SELECT * FROM material_derivative_jobs WHERE job_id=?', (job_id,)).fetchone())
            return {'job': finished, 'items': items}

    def material_derivatives(self, *, tenant_id: str, agent_id: str, asset_id: str) -> dict[str, Any]:
        with self._lock:
            jobs = self._conn.execute(
                'SELECT * FROM material_derivative_jobs WHERE tenant_id=? AND agent_id=? AND asset_id=? ORDER BY created_at',
                (tenant_id, agent_id, asset_id),
            ).fetchall()
            rows = self._conn.execute(
                'SELECT d.derivative_id,d.kind,d.filename,d.media_type,d.content_hash,d.metadata_json,j.asset_id,j.version_id '
                'FROM material_derivatives d JOIN material_derivative_jobs j ON j.job_id=d.job_id '
                'JOIN material_assets a ON a.asset_id=j.asset_id AND a.current_version_id=j.version_id '
                'JOIN material_versions v ON v.version_id=j.version_id '
                "WHERE j.tenant_id=? AND j.agent_id=? AND j.asset_id=? AND j.status='ready' AND a.state='active' "
                'AND (v.expires_at IS NULL OR v.expires_at>?) ORDER BY j.created_at,d.kind',
                (tenant_id, agent_id, asset_id, now_iso()),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['metadata'] = json.loads(item.pop('metadata_json'))
            items.append(item)
        return {'jobs': [dict(job) for job in jobs], 'items': items}

    def material_derivative(self, *, tenant_id: str, agent_id: str,
                            asset_id: str, derivative_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                'SELECT d.*,j.asset_id,j.version_id FROM material_derivatives d '
                'JOIN material_derivative_jobs j ON j.job_id=d.job_id '
                'JOIN material_assets a ON a.asset_id=j.asset_id AND a.current_version_id=j.version_id '
                'JOIN material_versions v ON v.version_id=j.version_id '
                "WHERE j.tenant_id=? AND j.agent_id=? AND j.asset_id=? AND d.derivative_id=? AND j.status='ready' "
                "AND a.state='active' AND (v.expires_at IS NULL OR v.expires_at>?)",
                (tenant_id, agent_id, asset_id, derivative_id, now_iso()),
            ).fetchone()
        return dict(row) if row else None

    def save_material_processing_candidate(self, *, candidate_id: str, tenant_id: str, agent_id: str,
                                           asset_id: str, version_id: str, kind: str, status: str,
                                           summary: str, source_hash: str, review_state: str = 'pending') -> dict[str, Any]:
        with self._tx() as cur:
            timestamp = now_iso()
            cur.execute('INSERT OR REPLACE INTO material_processing_candidates '
                        '(candidate_id,tenant_id,agent_id,asset_id,version_id,kind,status,summary,source_hash,review_state,created_at,reviewed_at) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT created_at FROM material_processing_candidates WHERE candidate_id=?),?),NULL)',
                        (candidate_id, tenant_id, agent_id, asset_id, version_id, kind, status, summary,
                         source_hash, review_state, candidate_id, timestamp))
            row = cur.execute('SELECT * FROM material_processing_candidates WHERE candidate_id=?', (candidate_id,)).fetchone()
        return dict(row)

    def material_processing_candidate(self, *, tenant_id: str, agent_id: str, candidate_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute('SELECT * FROM material_processing_candidates WHERE tenant_id=? AND agent_id=? AND candidate_id=?',
                                     (tenant_id, agent_id, candidate_id)).fetchone()
        return dict(row) if row else None

    def review_material_processing_candidate(self, *, tenant_id: str, agent_id: str, candidate_id: str,
                                             review_state: str) -> dict[str, Any]:
        if review_state not in {'approved', 'rejected'}:
            raise ValueError('review_state 必须为 approved 或 rejected')
        with self._tx() as cur:
            candidate = cur.execute(
                'SELECT * FROM material_processing_candidates WHERE tenant_id=? AND agent_id=? AND candidate_id=?',
                (tenant_id, agent_id, candidate_id),
            ).fetchone()
            if candidate is None:
                raise KeyError('未知简介候选')
            if review_state == 'approved':
                material = cur.execute(
                    'SELECT a.state,v.content_hash,v.expires_at FROM material_assets a '
                    'JOIN material_versions v ON v.version_id=a.current_version_id '
                    'WHERE a.tenant_id=? AND a.agent_id=? AND a.asset_id=? AND v.version_id=?',
                    (tenant_id, agent_id, candidate['asset_id'], candidate['version_id']),
                ).fetchone()
                if (candidate['status'] != 'ready' or not candidate['summary'].strip()
                        or material is None or material['state'] != 'active'
                        or material['content_hash'] != candidate['source_hash']
                        or (material['expires_at'] and material['expires_at'] <= now_iso())):
                    raise RuntimeError('候选未就绪或来源已失效，请按当前物料重新处理')
            if candidate['review_state'] == review_state:
                return dict(candidate)
            updated = cur.execute('UPDATE material_processing_candidates SET review_state=?,reviewed_at=? WHERE tenant_id=? AND agent_id=? AND candidate_id=?',
                                  (review_state, now_iso(), tenant_id, agent_id, candidate_id)).rowcount
            if not updated: raise KeyError('未知简介候选')
            return dict(cur.execute('SELECT * FROM material_processing_candidates WHERE candidate_id=?', (candidate_id,)).fetchone())

    def search_material_summaries(self, *, tenant_id: str, agent_id: str, query: str,
                                 limit: int = 10) -> list[dict[str, Any]]:
        tokens = query.lower().split()
        if not tokens:
            return []
        clauses = ' AND '.join("instr(lower(c.summary || ' ' || v.display_name), ?) > 0" for _ in tokens)
        with self._lock:
            rows = self._conn.execute(
                'SELECT c.candidate_id,c.asset_id,c.version_id,c.summary,c.source_hash,c.reviewed_at,'
                'v.display_name,v.media_type FROM material_processing_candidates c '
                'JOIN material_assets a ON a.asset_id=c.asset_id AND a.tenant_id=c.tenant_id AND a.agent_id=c.agent_id '
                'JOIN material_versions v ON v.version_id=c.version_id AND v.asset_id=a.asset_id '
                "WHERE c.tenant_id=? AND c.agent_id=? AND c.review_state='approved' AND c.status='ready' "
                "AND a.state='active' AND a.current_version_id=c.version_id AND v.content_hash=c.source_hash "
                "AND v.authorization IN ('owned','licensed','public_domain','consented') "
                'AND (v.expires_at IS NULL OR v.expires_at>?) '
                'AND NOT EXISTS (SELECT 1 FROM material_processing_candidates later '
                'WHERE later.tenant_id=c.tenant_id AND later.agent_id=c.agent_id AND later.version_id=c.version_id '
                'AND (later.reviewed_at>c.reviewed_at OR (later.reviewed_at=c.reviewed_at AND later.candidate_id>c.candidate_id))) '
                f'AND {clauses} ORDER BY c.reviewed_at DESC,c.candidate_id LIMIT ?',
                (tenant_id, agent_id, now_iso(), *tokens, limit),
            ).fetchall()
        return [{**dict(row), 'purpose': 'material_selection', 'grants_send_permission': False} for row in rows]

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
        conversation_id: str, visitor_token_hash: str, contact_version_id: str | None = None,
        visitor_fields: dict[str, str] | None = None, expected_version_id: str | None = None,
    ) -> dict[str, Any]:
        from .widget_configuration import public_widget_configuration, validate_visitor_fields
        timestamp = now_iso()
        with self._tx() as cur:
            if contact_version_id is not None:
                if not isinstance(contact_version_id, str) or not contact_version_id.strip():
                    raise ValueError("联系页版本必须是非空字符串")
                release = self._contact_release(cur, tenant_id=tenant_id, agent_id=agent_id, entry_id=entry_id)
                if release is not None and release["version_id"] != contact_version_id:
                    raise RuntimeError("联系页已换版，请刷新后重新咨询")
            else:
                release = cur.execute(
                    "SELECT e.release_id,e.version_id,r.knowledge_state,r.config_json FROM sandbox_entries e "
                    "JOIN sandbox_releases r ON r.release_id=e.release_id "
                    "WHERE e.tenant_id=? AND e.agent_id=? AND e.entry_id=? AND e.environment='sandbox'",
                    (tenant_id, agent_id, entry_id),
                ).fetchone()
            if release is None:
                raise KeyError("未知沙盒入口")
            if release["knowledge_state"] != "ready":
                raise RuntimeError("沙盒入口所绑版本待重新验收，不能接待访客")
            if expected_version_id is not None and release['version_id'] != expected_version_id:
                raise RuntimeError('入口版本已改变，请刷新后重新开始')
            config = {'widget': release['widget']} if contact_version_id is not None else json.loads(release['config_json'])
            widget = public_widget_configuration(config)
            if not widget['enabled']:
                raise RuntimeError('客服入口已停用')
            fields = validate_visitor_fields(widget, visitor_fields if visitor_fields is not None else {})
            cur.execute(
                "INSERT INTO customer_conversations VALUES(?,?,?,?,?,?,?,'bot',0,NULL,?,?)",
                (conversation_id, tenant_id, agent_id, entry_id, release["release_id"],
                 release["version_id"], visitor_token_hash, timestamp, timestamp),
            )
            cur.execute('INSERT INTO customer_visitor_fields VALUES(?,?,?)',
                        (conversation_id, json.dumps(fields, ensure_ascii=False), timestamp))
            return dict(cur.execute(
                "SELECT * FROM customer_conversations WHERE conversation_id=?", (conversation_id,),
            ).fetchone())

    @staticmethod
    def _reception_sources(cur: sqlite3.Cursor, conversation: Any, sources: list[dict[str, str]]) -> list[dict[str, str]]:
        """Only the approved allowlist can supply content to the read-only receiver."""
        loaded = []
        for source in sources:
            row = cur.execute(
                'SELECT s.display_name,d.content,d.content_hash FROM knowledge_sources s '
                'JOIN knowledge_documents d ON d.source_id=s.source_id AND d.content_hash=s.content_hash '
                "WHERE s.tenant_id=? AND s.agent_id=? AND s.source_id=? AND s.state='ready' "
                "AND s.authorization IN ('owned','licensed','public_domain','consented') AND s.content_hash=? "
                'ORDER BY d.created_at DESC LIMIT 1',
                (conversation['tenant_id'], conversation['agent_id'], source['source_id'], source['content_hash']),
            ).fetchone()
            if row is None or hashlib.sha256(row['content'].encode('utf-8')).hexdigest() != source['content_hash']:
                raise RuntimeError('接待知识来源已撤回、内容变化或授权无效')
            loaded.append({**source, 'title': row['display_name'], 'text': row['content']})
        return loaded

    def begin_customer_reception(self, *, conversation_id: str, visitor_token_hash: str,
                                 text: str, request_human: bool, message_id: str) -> dict[str, Any]:
        from .widget_configuration import public_widget_configuration, validate_ai_reception_configuration
        input_hash = hashlib.sha256(json.dumps([text, request_human], ensure_ascii=False).encode()).hexdigest()
        timestamp = now_iso()
        with self._tx() as cur:
            conversation = cur.execute(
                'SELECT c.*,r.config_json,r.content_hash,r.knowledge_state FROM customer_conversations c '
                'JOIN sandbox_releases r ON r.release_id=c.release_id '
                'WHERE c.conversation_id=? AND c.visitor_token_hash=?',
                (conversation_id, visitor_token_hash),
            ).fetchone()
            if conversation is None:
                raise KeyError('访客会话凭据无效')
            prior = cur.execute('SELECT * FROM customer_reception_turns WHERE conversation_id=? AND message_id=?',
                                (conversation_id, message_id)).fetchone()
            if prior is not None:
                if prior['input_hash'] != input_hash:
                    raise RuntimeError('同一消息标识已绑定不同内容')
                return {'created': False, 'result': self._customer_reception_result(cur, prior)}
            config = json.loads(conversation['config_json'])
            policy = validate_ai_reception_configuration(config.get('ai_reception', {}))
            folded_text = text.casefold()
            handoff_requested = conversation['state'] == 'bot' and (request_human or any(
                phrase.casefold() in folded_text for phrase in policy['handoff_phrases']))
            widget = public_widget_configuration(config)
            status, sources = 'generating', []
            if handoff_requested or conversation['state'] != 'bot':
                status = 'human_requested'
            elif not policy['enabled'] or not widget['enabled']:
                status = 'disabled'
            elif policy['mode'] == 'offline' and widget['availability'] == 'open':
                status = 'outside_schedule'
            elif conversation['knowledge_state'] != 'ready' or not policy['sources']:
                status = 'knowledge_unavailable'
            else:
                try:
                    sources = self._reception_sources(cur, conversation, policy['sources'])
                except RuntimeError:
                    status = 'knowledge_unavailable'
            sequence = cur.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM customer_messages WHERE conversation_id=?',
                                   (conversation_id,)).fetchone()[0]
            cur.execute("INSERT INTO customer_messages(conversation_id,sequence,sender,text,created_at) VALUES(?,?,'visitor',?,?)",
                        (conversation_id, sequence, text, timestamp))
            state = 'human_requested' if handoff_requested else conversation['state']
            cur.execute('UPDATE customer_conversations SET state=?,updated_at=? WHERE conversation_id=?',
                        (state, timestamp, conversation_id))
            self._append_customer_inbox_event(cur, conversation, 'visitor.message', message_sequence=sequence,
                state=state)
            if state == 'human_requested' and conversation['state'] != 'human_requested':
                self._append_customer_inbox_event(cur, conversation, 'handoff.requested',
                    message_sequence=sequence, state=state)
            request = ServiceRequest(request_id=new_id('req'), tenant_id=conversation['tenant_id'],
                agent_version=conversation['release_version'], channel=Channel.TEXT, state=RequestState.RUNNING,
                trigger_kind='customer_message', trigger_ref=conversation_id,
                trigger_event_id=f'{conversation_id}:{sequence}')
            run = Run(run_id=new_id('run'), request_id=request.request_id, tenant_id=request.tenant_id,
                agent_version=request.agent_version, owner_id=self.owner_id,
                occupancy_generation=conversation['occupancy_generation'],
                snapshot={'kind': 'customer_reception', 'agent_id': conversation['agent_id'],
                          'model_id': policy['model_id'],
                          'conversation_id': conversation_id, 'input_sequence': sequence})
            event = RunEvent(seq=1, event_type='customer.reception.started', request_id=request.request_id,
                run_id=run.run_id, tenant_id=request.tenant_id, agent_version=request.agent_version, channel='text',
                payload={'conversation_id': conversation_id, 'input_sequence': sequence,
                         'generation': run.occupancy_generation, 'sources': policy['sources'], 'model_id': policy['model_id'],
                         'read_only': True, 'handoff_requested': handoff_requested})
            self._begin_run(cur, request, run, [event])
            cur.execute('INSERT INTO customer_reception_turns '
                '(conversation_id,input_sequence,message_id,input_hash,request_id,run_id,generation,version_id,release_hash,status,sources_json,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (conversation_id, sequence, message_id, input_hash, request.request_id, run.run_id,
                 run.occupancy_generation, request.agent_version, conversation['content_hash'], 'generating',
                 json.dumps(policy['sources']), timestamp, timestamp))
            history = [dict(row) for row in cur.execute(
                'SELECT sender,text FROM customer_messages WHERE conversation_id=? AND sequence<? ORDER BY sequence DESC LIMIT 12',
                (conversation_id, sequence)).fetchall()][::-1]
            return {'created': True, 'run_id': run.run_id, 'initial_status': status,
                    'config': config, 'sources': sources, 'history': history}

    @staticmethod
    def _customer_reception_result(cur: sqlite3.Cursor, turn: Any) -> dict[str, Any]:
        details = json.loads(turn['details_json'])
        reception = {key: turn[key] for key in ('request_id', 'run_id', 'version_id', 'status')}
        reception['message'] = details.get('message', '正在生成答复')
        if details.get('provider', {}).get('failure_code'):
            reception['failure_code'] = details['provider']['failure_code']
        visitor = dict(cur.execute('SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?',
                                  (turn['conversation_id'], turn['input_sequence'])).fetchone())
        visitor['reception'] = reception
        visitor['message_id'] = turn['message_id']
        assistant = None
        if turn['response_sequence'] is not None:
            assistant = dict(cur.execute('SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?',
                                        (turn['conversation_id'], turn['response_sequence'])).fetchone())
            assistant.update(citations=details.get('citations', []), reception=reception)
        return {'visitor': visitor, 'assistant': assistant, 'reception': reception}

    def finish_customer_reception(self, *, run_id: str, status: str, message: str,
                                  text: str | None = None, citations: list[dict[str, str]] | None = None,
                                  provider: dict[str, Any] | None = None, handoff: bool = False) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            turn = cur.execute('SELECT * FROM customer_reception_turns WHERE run_id=?', (run_id,)).fetchone()
            if turn is None:
                raise KeyError('未知接待运行')
            if turn['status'] != 'generating':
                return self._customer_reception_result(cur, turn)
            run = cur.execute('SELECT status FROM runs WHERE run_id=?', (run_id,)).fetchone()
            conversation = cur.execute(
                'SELECT c.*,r.content_hash,r.knowledge_state FROM customer_conversations c '
                'JOIN sandbox_releases r ON r.release_id=c.release_id WHERE c.conversation_id=?',
                (turn['conversation_id'],),
            ).fetchone()
            latest_input = cur.execute("SELECT MAX(sequence) FROM customer_messages WHERE conversation_id=? AND sender='visitor'",
                                       (turn['conversation_id'],)).fetchone()[0]
            started = cur.execute("SELECT payload_json FROM events WHERE run_id=? AND event_type='customer.reception.started' "
                                  'ORDER BY seq LIMIT 1', (run_id,)).fetchone()
            start_payload = json.loads(started['payload_json']) if started else {}
            visitor_requested_handoff = type(start_payload.get('handoff_requested')) is bool and start_payload['handoff_requested']
            last_event = cur.execute('SELECT MAX(seq) FROM events WHERE run_id=?', (run_id,)).fetchone()[0]
            events = []
            def event(kind, payload):
                return RunEvent(seq=last_event + len(events) + 1, event_type=kind,
                    request_id=turn['request_id'], run_id=run_id, tenant_id=conversation['tenant_id'],
                    agent_version=turn['version_id'], channel='text', payload=payload)
            if text is not None:
                events.append(event('customer.reception.generated', {'text_hash': hashlib.sha256(text.encode()).hexdigest(),
                    'provider': provider or {}, 'citations': citations or [], 'delivery': 'not_sent'}))
            if run['status'] != 'running':
                status, message, text, handoff = 'interrupted', '本次自动接待已中断，消息已保留，请等待人工客服。', None, True
            elif (conversation['release_version'] != turn['version_id'] or conversation['content_hash'] != turn['release_hash']
                    or conversation['occupancy_generation'] != turn['generation'] or latest_input != turn['input_sequence']
                    or (conversation['state'] != 'bot' and status != 'human_requested')):
                status, message, text, handoff = 'superseded', '人工已接管或收到新消息，本次自动答复已停止。', None, False
            elif text is not None:
                try:
                    if conversation['knowledge_state'] != 'ready':
                        raise RuntimeError('知识版本失效')
                    self._reception_sources(cur, conversation, json.loads(turn['sources_json']))
                except RuntimeError:
                    status, message, text, handoff = 'knowledge_unavailable', '授权资料已变化，消息已保留，请等待人工客服。', None, True
            sequence = None
            if text is not None:
                sequence = cur.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM customer_messages WHERE conversation_id=?',
                                       (turn['conversation_id'],)).fetchone()[0]
                cur.execute("INSERT INTO customer_messages(conversation_id,sequence,sender,text,created_at) VALUES(?,?,'assistant',?,?)",
                            (turn['conversation_id'], sequence, text, timestamp))
                self._append_customer_inbox_event(cur, conversation, 'assistant.response', message_sequence=sequence)
                events.append(event('customer.reception.published', {'conversation_id': turn['conversation_id'],
                    'input_sequence': turn['input_sequence'], 'response_sequence': sequence,
                    'delivery': 'stored_for_visitor', 'problem_resolved': False}))
            if handoff and conversation['state'] == 'bot':
                cur.execute("UPDATE customer_conversations SET state='human_requested',occupancy_generation=occupancy_generation+1,updated_at=? WHERE conversation_id=?",
                            (timestamp, turn['conversation_id']))
                self._append_customer_inbox_event(cur, conversation, 'handoff.requested',
                    message_sequence=turn['input_sequence'], state='human_requested',
                    occupancy_generation=conversation['occupancy_generation'] + 1)
            else:
                cur.execute('UPDATE customer_conversations SET updated_at=? WHERE conversation_id=?', (timestamp, turn['conversation_id']))
            details = {'message': message, 'citations': citations if text is not None else [], 'provider': provider or {}}
            cur.execute('UPDATE customer_reception_turns SET status=?,details_json=?,response_sequence=?,updated_at=? WHERE run_id=?',
                        (status, json.dumps(details, ensure_ascii=False), sequence, timestamp, run_id))
            events.append(event('customer.reception.finished', {'status': status, 'read_only': True,
                'input_sequence': turn['input_sequence'], 'response_sequence': sequence, 'problem_resolved': False,
                'handoff_requested': bool(handoff or visitor_requested_handoff), 'handoff_tracking_version': 1}))
            self._append(cur, events)
            run_status = 'succeeded' if status in {'answered', 'handoff', 'disabled', 'outside_schedule', 'human_requested'} else 'failed'
            # Successful text generation cannot establish a completed business request.
            cur.execute("UPDATE runs SET status=?,ended_at=?,finish_reason=? WHERE run_id=? AND status='running'", (run_status, timestamp, status, run_id))
            cur.execute("UPDATE requests SET state='waiting',updated_at=? WHERE request_id=? AND state='running'", (timestamp, turn['request_id']))
            return self._customer_reception_result(cur, cur.execute('SELECT * FROM customer_reception_turns WHERE run_id=?', (run_id,)).fetchone())

    def recover_customer_receptions(self) -> None:
        """A new single-writer HTTP process records orphaned turns; it never resends."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT t.run_id FROM customer_reception_turns t JOIN runs r ON r.run_id=t.run_id "
                "WHERE t.status='generating' AND r.owner_id<>?", (self.owner_id,),
            ).fetchall()
        for row in rows:
            self.finish_customer_reception(run_id=row['run_id'], status='interrupted',
                message='本次自动接待已中断，消息已保留，请等待人工客服。', handoff=True)

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
            self._append_customer_inbox_event(cur, conversation, 'visitor.message', message_sequence=sequence,
                state=state)
            if state == 'human_requested' and conversation['state'] != 'human_requested':
                self._append_customer_inbox_event(cur, conversation, 'handoff.requested',
                    message_sequence=sequence, state=state)
            return dict(cur.execute(
                "SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?",
                (conversation["conversation_id"], sequence),
            ).fetchone())

    def add_assistant_message(self, *, conversation_id: str, visitor_token_hash: str,
                              text: str, version_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            conversation = cur.execute(
                'SELECT * FROM customer_conversations WHERE conversation_id=? AND visitor_token_hash=? AND release_version=?',
                (conversation_id, visitor_token_hash, version_id),
            ).fetchone()
            if conversation is None:
                raise KeyError('访客会话凭据无效或版本已变化')
            if conversation['state'] != 'bot':
                raise RuntimeError('当前会话已请求人工，不能自动追加答复')
            sequence = cur.execute(
                'SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM customer_messages WHERE conversation_id=?',
                (conversation_id,),
            ).fetchone()['sequence']
            cur.execute(
                'INSERT INTO customer_messages(conversation_id,sequence,sender,text,created_at) VALUES(?,?,\'assistant\',?,?)',
                (conversation_id, sequence, text, timestamp),
            )
            cur.execute('UPDATE customer_conversations SET updated_at=? WHERE conversation_id=?', (timestamp, conversation_id))
            self._append_customer_inbox_event(cur, conversation, 'assistant.response', message_sequence=sequence)
            return dict(cur.execute('SELECT * FROM customer_messages WHERE conversation_id=? AND sequence=?',
                                    (conversation_id, sequence)).fetchone())

    def list_customer_conversations(
        self, *, tenant_id: str, agent_id: str, actor_id: str = '',
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.*,p.fields_json,COALESCE(r.read_sequence,0) AS read_sequence,"
                "COALESCE(MAX(m.sequence),0) AS latest_sequence,"
                "COALESCE(MAX(CASE WHEN m.sender='visitor' THEN m.sequence ELSE 0 END),0) AS last_visitor_sequence,"
                "SUM(CASE WHEN m.sender='visitor' AND m.sequence>COALESCE(r.read_sequence,0) THEN 1 ELSE 0 END) AS unread_count "
                "FROM customer_conversations c "
                "LEFT JOIN customer_visitor_fields p ON p.conversation_id=c.conversation_id "
                "LEFT JOIN customer_inbox_reads r ON r.conversation_id=c.conversation_id "
                "AND r.tenant_id=c.tenant_id AND r.agent_id=c.agent_id AND r.actor_id=? "
                "LEFT JOIN customer_messages m ON m.conversation_id=c.conversation_id "
                "WHERE c.tenant_id=? AND c.agent_id=? GROUP BY c.conversation_id "
                "ORDER BY c.updated_at DESC,c.conversation_id",
                (actor_id, tenant_id, agent_id),
            ).fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value['visitor_fields'] = json.loads(value.pop('fields_json') or '{}')
            values.append(value)
        return values

    def mark_customer_read(self, *, tenant_id: str, agent_id: str, actor_id: str,
                           conversation_id: str, through_sequence: int) -> dict[str, Any]:
        if type(through_sequence) is not int or through_sequence < 0:
            raise ValueError('已读位置必须是非负整数')
        with self._tx() as cur:
            conversation = cur.execute(
                'SELECT 1 FROM customer_conversations WHERE tenant_id=? AND agent_id=? AND conversation_id=?',
                (tenant_id, agent_id, conversation_id)).fetchone()
            if conversation is None:
                raise KeyError('未知会话')
            latest = cur.execute('SELECT COALESCE(MAX(sequence),0) FROM customer_messages WHERE conversation_id=?',
                                 (conversation_id,)).fetchone()[0]
            if through_sequence > latest:
                raise ValueError('已读位置不能超过当前消息')
            cur.execute('INSERT INTO customer_inbox_reads VALUES(?,?,?,?,?,?) '
                        'ON CONFLICT(tenant_id,agent_id,actor_id,conversation_id) DO UPDATE SET '
                        'read_sequence=MAX(read_sequence,excluded.read_sequence),updated_at=excluded.updated_at',
                        (tenant_id, agent_id, actor_id, conversation_id, through_sequence, now_iso()))
            position = cur.execute('SELECT read_sequence FROM customer_inbox_reads '
                                   'WHERE tenant_id=? AND agent_id=? AND actor_id=? AND conversation_id=?',
                                   (tenant_id, agent_id, actor_id, conversation_id)).fetchone()[0]
        return {'conversation_id': conversation_id, 'read_sequence': position}

    @staticmethod
    def _append_customer_inbox_event(
        cur: sqlite3.Cursor, conversation: Any, event_type: str, *, message_sequence: int | None = None,
        state: str | None = None, occupancy_generation: int | None = None,
    ) -> int:
        """Append redacted, tenant/agent-ordered Inbox metadata in the caller's transaction."""
        if event_type not in {'visitor.message', 'assistant.response', 'handoff.requested',
                              'handoff.claimed', 'handoff.replied', 'handoff.released'}:
            raise ValueError('unsupported inbox event type')
        sequence = cur.execute(
            'SELECT COALESCE(MAX(sequence),0)+1 FROM customer_inbox_events WHERE tenant_id=? AND agent_id=?',
            (conversation['tenant_id'], conversation['agent_id']),
        ).fetchone()[0]
        cur.execute('INSERT INTO customer_inbox_events VALUES(?,?,?,?,?,?,?,?,?)',
            (conversation['tenant_id'], conversation['agent_id'], sequence,
             conversation['conversation_id'], event_type, message_sequence,
             state if state is not None else conversation['state'],
             occupancy_generation if occupancy_generation is not None else conversation['occupancy_generation'],
             now_iso()))
        return sequence

    def list_customer_inbox_events(self, *, tenant_id: str, agent_id: str,
                                   after_sequence: int, limit: int = 50) -> dict[str, Any]:
        if type(after_sequence) is not int or after_sequence < 0:
            raise ValueError('Inbox 事件游标必须是非负整数')
        if after_sequence > 2**63 - 1:
            raise ValueError('Inbox 事件游标超出存储范围')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Inbox 事件分页上限必须是 1 至 100 的整数')
        with self._lock:
            latest = self._conn.execute(
                'SELECT COALESCE(MAX(sequence),0) FROM customer_inbox_events WHERE tenant_id=? AND agent_id=?',
                (tenant_id, agent_id),
            ).fetchone()[0]
            if after_sequence > latest:
                raise ValueError('Inbox 事件游标不能超过当前流位置')
            rows = self._conn.execute(
                'SELECT sequence,event_type,conversation_id,message_sequence,state,occupancy_generation '
                'FROM customer_inbox_events WHERE tenant_id=? AND agent_id=? AND sequence>? '
                'ORDER BY sequence LIMIT ?', (tenant_id, agent_id, after_sequence, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        events = [dict(row) for row in rows[:limit]]
        return {'events': events, 'next_cursor': events[-1]['sequence'] if events else after_sequence,
                'has_more': has_more}

    @staticmethod
    def _validate_inbox_consumer_id(consumer_id: str) -> None:
        if (not isinstance(consumer_id, str) or not 1 <= len(consumer_id) <= 128
                or not consumer_id.isascii()
                or any(not (character.isalnum() or character in '-_') for character in consumer_id)):
            raise ValueError('Inbox consumer ID 必须是 1 至 128 位 ASCII 标识')

    def get_or_create_customer_inbox_consumer_cursor(
        self, *, tenant_id: str, agent_id: str, actor_id: str, consumer_id: str,
    ) -> dict[str, Any]:
        self._validate_inbox_consumer_id(consumer_id)
        scope = (tenant_id, agent_id, actor_id, consumer_id)
        with self._tx() as cur:
            latest = cur.execute(
                'SELECT COALESCE(MAX(sequence),0) FROM customer_inbox_events WHERE tenant_id=? AND agent_id=?',
                (tenant_id, agent_id),
            ).fetchone()[0]
            cur.execute(
                'INSERT OR IGNORE INTO customer_inbox_consumers '
                '(tenant_id,agent_id,actor_id,consumer_id,acknowledged_sequence,updated_at) VALUES(?,?,?,?,?,?)',
                (*scope, latest, now_iso()),
            )
            row = cur.execute(
                'SELECT acknowledged_sequence FROM customer_inbox_consumers '
                'WHERE tenant_id=? AND agent_id=? AND actor_id=? AND consumer_id=?', scope,
            ).fetchone()
        return {'consumer_id': consumer_id, 'cursor': row['acknowledged_sequence']}

    def ack_customer_inbox_consumer(
        self, *, tenant_id: str, agent_id: str, actor_id: str, consumer_id: str,
        through_sequence: int,
    ) -> dict[str, Any]:
        self._validate_inbox_consumer_id(consumer_id)
        if type(through_sequence) is not int or not 0 <= through_sequence <= 2**63 - 1:
            raise ValueError('Inbox 事件 ack 必须是存储范围内的非负整数')
        scope = (tenant_id, agent_id, actor_id, consumer_id)
        with self._tx() as cur:
            latest = cur.execute(
                'SELECT COALESCE(MAX(sequence),0) FROM customer_inbox_events WHERE tenant_id=? AND agent_id=?',
                (tenant_id, agent_id),
            ).fetchone()[0]
            if through_sequence > latest:
                raise ValueError('Inbox 事件 ack 不能超过当前流位置')
            # Only the cursor-read action silently baselines a new consumer at the tail.
            cur.execute(
                'INSERT OR IGNORE INTO customer_inbox_consumers '
                '(tenant_id,agent_id,actor_id,consumer_id,acknowledged_sequence,updated_at) VALUES(?,?,?,?,?,?)',
                (*scope, 0, now_iso()),
            )
            cur.execute(
                'UPDATE customer_inbox_consumers SET acknowledged_sequence=MAX(acknowledged_sequence,?),updated_at=? '
                'WHERE tenant_id=? AND agent_id=? AND actor_id=? AND consumer_id=?',
                (through_sequence, now_iso(), *scope),
            )
            row = cur.execute(
                'SELECT acknowledged_sequence FROM customer_inbox_consumers '
                'WHERE tenant_id=? AND agent_id=? AND actor_id=? AND consumer_id=?', scope,
            ).fetchone()
        return {'consumer_id': consumer_id, 'cursor': row['acknowledged_sequence']}

    def inbox_preferences(self, *, tenant_id: str, agent_id: str, actor_id: str) -> dict[str, bool]:
        with self._lock:
            row = self._conn.execute('SELECT new_messages,handoff FROM customer_inbox_preferences '
                                     'WHERE tenant_id=? AND agent_id=? AND actor_id=?',
                                     (tenant_id, agent_id, actor_id)).fetchone()
        return {key: bool(row[key]) if row else False for key in ('new_messages', 'handoff')}

    def save_inbox_preferences(self, *, tenant_id: str, agent_id: str, actor_id: str,
                               new_messages: bool, handoff: bool) -> dict[str, bool]:
        if type(new_messages) is not bool or type(handoff) is not bool:
            raise ValueError('通知偏好必须是布尔值')
        with self._tx() as cur:
            cur.execute('INSERT INTO customer_inbox_preferences VALUES(?,?,?,?,?,?) '
                        'ON CONFLICT(tenant_id,agent_id,actor_id) DO UPDATE SET '
                        'new_messages=excluded.new_messages,handoff=excluded.handoff,updated_at=excluded.updated_at',
                        (tenant_id, agent_id, actor_id, int(new_messages), int(handoff), now_iso()))
        return {'new_messages': new_messages, 'handoff': handoff}

    def customer_statistics(self, *, tenant_id: str, agent_id: str) -> dict[str, Any]:
        with self._lock:
            conversations = self._conn.execute('SELECT state,release_version FROM customer_conversations WHERE tenant_id=? AND agent_id=?',
                                               (tenant_id, agent_id)).fetchall()
            messages = self._conn.execute('SELECT sender FROM customer_messages WHERE conversation_id IN '
                                          '(SELECT conversation_id FROM customer_conversations WHERE tenant_id=? AND agent_id=?)',
                                          (tenant_id, agent_id)).fetchall()
            channels = self._conn.execute('SELECT channel,COUNT(*) AS n FROM channel_messages WHERE tenant_id=? AND agent_id=? GROUP BY channel',
                                          (tenant_id, agent_id)).fetchall()
        result = {'conversation_count': len(conversations),
                  'states': {state: sum(row['state'] == state for row in conversations) for state in {'bot', 'human_requested', 'human'}},
                  'message_count': len(messages),
                  'messages_by_sender': {sender: sum(row['sender'] == sender for row in messages) for sender in {'visitor', 'assistant', 'operator'}},
                  'channel_messages': {row['channel']: row['n'] for row in channels},
                  'response_latency_ms': None,
                  'delivery': 'channel sandbox records only; provider delivery remains unknown'}
        return result

    def customer_reception_statistics_rows(self, *, tenant_id: str, agent_id: str) -> list[dict[str, Any]]:
        """Read retained reception events with their independently joined scope facts."""
        with self._lock:
            rows = self._conn.execute(
                'SELECT c.tenant_id AS scope_tenant_id,c.agent_id AS scope_agent_id,'
                'c.conversation_id,c.entry_id,c.release_version,'
                't.input_sequence AS turn_input_sequence,t.request_id AS turn_request_id,'
                't.run_id AS turn_run_id,t.version_id AS turn_version_id,'
                'r.request_id AS run_request_id,r.tenant_id AS run_tenant_id,'
                'r.agent_version AS run_version_id,r.snapshot_json AS run_snapshot_json,'
                'q.tenant_id AS request_tenant_id,q.agent_version AS request_version_id,'
                'COALESCE(e.run_id,t.run_id) AS run_id,e.seq,'
                'COALESCE(e.request_id,t.request_id) AS request_id,e.rid,e.event_type,e.ts,'
                'e.payload_json,e.prev_hash,e.hash,e.event_json '
                'FROM customer_reception_turns t '
                'JOIN customer_conversations c ON c.conversation_id=t.conversation_id '
                'JOIN runs r ON r.run_id=t.run_id '
                'JOIN requests q ON q.request_id=t.request_id '
                "LEFT JOIN events e ON e.run_id=t.run_id AND e.event_type IN "
                "('customer.reception.started','customer.reception.generated',"
                "'customer.reception.published','customer.reception.finished',"
                "'customer.handoff.claimed','customer.handoff.replied','customer.handoff.released') "
                'WHERE c.tenant_id=? AND c.agent_id=? '
                'ORDER BY t.run_id,e.seq,e.rid',
                (tenant_id, agent_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def customer_conversation_configuration(self, *, tenant_id: str, agent_id: str, entry_id: str,
                                           conversation_id: str, visitor_token_hash: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                'SELECT c.release_version,r.config_json,r.knowledge_state FROM customer_conversations c '
                'JOIN sandbox_releases r ON r.release_id=c.release_id AND r.tenant_id=c.tenant_id AND r.agent_id=c.agent_id '
                'WHERE c.tenant_id=? AND c.agent_id=? AND c.entry_id=? AND c.conversation_id=? AND c.visitor_token_hash=?',
                (tenant_id, agent_id, entry_id, conversation_id, visitor_token_hash),
            ).fetchone()
        if row is None:
            raise KeyError('访客会话不存在或凭据无效')
        if row['knowledge_state'] != 'ready':
            raise RuntimeError('会话所绑版本待重新验收')
        return {'version_id': row['release_version'], 'config': json.loads(row['config_json'])}

    def conversation_configuration_by_token(self, *, conversation_id: str, visitor_token_hash: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                'SELECT c.release_version,r.config_json,r.knowledge_state FROM customer_conversations c '
                'JOIN sandbox_releases r ON r.release_id=c.release_id '
                'WHERE c.conversation_id=? AND c.visitor_token_hash=?',
                (conversation_id, visitor_token_hash),
            ).fetchone()
        if row is None:
            raise KeyError('访客会话不存在或凭据无效')
        if row['knowledge_state'] != 'ready':
            raise RuntimeError('会话所绑版本待重新验收')
        return {'version_id': row['release_version'], 'config': json.loads(row['config_json'])}

    def customer_assistance_snapshot(
        self, *, tenant_id: str, agent_id: str, conversation_id: str, actor_id: str,
        generation: int, through_sequence: int,
    ) -> dict[str, Any]:
        """Read and fingerprint assistance authority in one transaction without mutations."""
        from .customer_reception import _context
        from .widget_configuration import validate_ai_reception_configuration

        if any(not isinstance(value, str) or not value.strip() or len(value) > 128 or '\x00' in value
               for value in (tenant_id, agent_id, conversation_id, actor_id)):
            raise ValueError('辅助请求的身份或会话标识无效')
        if (type(generation) is not int or not 1 <= generation <= 2**63 - 1
                or type(through_sequence) is not int or not 1 <= through_sequence <= 2**63 - 1):
            raise ValueError('辅助请求的占用代次与消息序号必须是正整数')
        with self._tx() as cur:
            row = cur.execute(
                'SELECT c.*,r.config_json,r.content_hash,r.knowledge_state,r.candidate_id '
                'FROM customer_conversations c JOIN sandbox_releases r '
                'ON r.release_id=c.release_id AND r.tenant_id=c.tenant_id AND r.agent_id=c.agent_id '
                "AND r.version_id=c.release_version AND r.environment='sandbox' "
                'WHERE c.tenant_id=? AND c.agent_id=? AND c.conversation_id=?',
                (tenant_id, agent_id, conversation_id),
            ).fetchone()
            if row is None:
                raise KeyError('会话不存在或无权访问')
            if (row['state'] != 'human' or row['assigned_to'] != actor_id
                    or row['occupancy_generation'] != generation):
                raise RuntimeError('客服会话占用已变化，请重新生成辅助内容')
            latest = cur.execute('SELECT COALESCE(MAX(sequence),0) FROM customer_messages WHERE conversation_id=?',
                                 (conversation_id,)).fetchone()[0]
            if latest != through_sequence:
                raise RuntimeError('会话消息已变化，请重新生成辅助内容')
            if (row['knowledge_state'] != 'ready'
                    or hashlib.sha256(row['config_json'].encode()).hexdigest() != row['content_hash']):
                raise RuntimeError('会话所绑版本或授权资料已变化，请重新生成辅助内容')
            try:
                config = json.loads(row['config_json'])
                if not isinstance(config, dict):
                    raise ValueError('invalid frozen configuration')
                policy = validate_ai_reception_configuration(config.get('ai_reception', {}))
                sources = self._reception_sources(cur, row, policy['sources'])
            except (KeyError, TypeError, ValueError, RuntimeError):
                raise RuntimeError('会话所绑版本或授权资料已变化，请重新生成辅助内容') from None
            history = [dict(item) for item in cur.execute(
                'SELECT sequence,sender,text FROM customer_messages WHERE conversation_id=? '
                'ORDER BY sequence DESC LIMIT 20', (conversation_id,),
            ).fetchall()][::-1]
            digest = hashlib.sha256()
            identity = {'schema_version': 'inbox-assistance-v1', 'tenant_id': tenant_id,
                        'agent_id': agent_id, 'conversation_id': conversation_id, 'actor_id': actor_id,
                        'release_id': row['release_id'], 'version_id': row['release_version'],
                        'candidate_id': row['candidate_id'], 'config_hash': row['content_hash'],
                        'generation': generation, 'through_sequence': through_sequence, 'config': config}
            digest.update(json.dumps(identity, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
            # Hash every retained message; only the latest bounded history enters the model.
            for item in cur.execute('SELECT * FROM customer_messages WHERE conversation_id=? ORDER BY sequence',
                                    (conversation_id,)):
                digest.update(json.dumps(dict(item), ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
            for source in sources:
                authority = cur.execute(
                    'SELECT source_id,authorization,state,content_hash,updated_at,revoked_at '
                    'FROM knowledge_sources WHERE tenant_id=? AND agent_id=? AND source_id=?',
                    (tenant_id, agent_id, source['source_id']),
                ).fetchone()
                digest.update(json.dumps({'source': source, 'authority': dict(authority)},
                                         ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
            bounded = _context({'config': config, 'sources': sources, 'history': history}, '')
            return {'config': config, 'sources': bounded['sources'], 'persona': bounded['persona'],
                    'history': bounded['history'], 'snapshot_hash': digest.hexdigest(),
                    'generation': generation, 'through_sequence': through_sequence,
                    'version_id': row['release_version'], 'release_id': row['release_id'],
                    'config_hash': row['content_hash']}

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
            self._append_customer_handoff_event(cur, row, 'customer.handoff.claimed', actor_id=actor_id,
                occupancy_generation=generation)
            return dict(cur.execute(
                "SELECT * FROM customer_conversations WHERE conversation_id=?", (conversation_id,),
            ).fetchone())

    def release_customer_conversation(
        self, *, tenant_id: str, agent_id: str, conversation_id: str, actor_id: str, generation: int,
    ) -> dict[str, Any]:
        if type(generation) is not int:
            raise ValueError('占用代次必须是整数')
        with self._tx() as cur:
            row = cur.execute(
                'SELECT * FROM customer_conversations WHERE tenant_id=? AND agent_id=? AND conversation_id=?',
                (tenant_id, agent_id, conversation_id),
            ).fetchone()
            if row is None:
                raise KeyError('未知会话')
            if (row['state'] != 'human' or row['assigned_to'] != actor_id
                    or row['occupancy_generation'] != generation):
                raise RuntimeError('客服会话占用已变化，拒绝释放')
            next_generation = generation + 1
            cur.execute(
                "UPDATE customer_conversations SET state='bot',assigned_to=NULL,occupancy_generation=?,updated_at=? "
                'WHERE conversation_id=? AND occupancy_generation=?',
                (next_generation, now_iso(), conversation_id, generation),
            )
            self._append_customer_handoff_event(cur, row, 'customer.handoff.released', actor_id=actor_id,
                occupancy_generation=next_generation)
            return dict(cur.execute(
                'SELECT * FROM customer_conversations WHERE conversation_id=?', (conversation_id,),
            ).fetchone())

    def _append_customer_handoff_event(
        self, cur: sqlite3.Cursor, conversation: Any, event_type: str, *, actor_id: str,
        occupancy_generation: int, message_sequence: int | None = None,
    ) -> None:
        latest_visitor = cur.execute(
            "SELECT MAX(sequence) FROM customer_messages WHERE conversation_id=? AND sender='visitor'",
            (conversation['conversation_id'],),
        ).fetchone()[0]
        turn = cur.execute(
            'SELECT * FROM customer_reception_turns WHERE conversation_id=? ORDER BY input_sequence DESC LIMIT 1',
            (conversation['conversation_id'],),
        ).fetchone()
        feed_type = {'customer.handoff.claimed': 'handoff.claimed',
                     'customer.handoff.replied': 'handoff.replied',
                     'customer.handoff.released': 'handoff.released'}.get(event_type)
        if feed_type is not None:
            feed_state = {'handoff.claimed': 'human', 'handoff.replied': 'human',
                          'handoff.released': 'bot'}[feed_type]
            self._append_customer_inbox_event(cur, conversation, feed_type,
                message_sequence=message_sequence, state=feed_state,
                occupancy_generation=occupancy_generation)
        if turn is None or turn['input_sequence'] != latest_visitor:
            request = ServiceRequest(request_id=new_id('req'), tenant_id=conversation['tenant_id'],
                agent_version=conversation['release_version'], channel=Channel.TEXT, state=RequestState.RUNNING,
                trigger_kind='customer_handoff_transition', trigger_ref=conversation['conversation_id'],
                trigger_event_id=new_id('handoff'))
            run = Run(run_id=new_id('run'), request_id=request.request_id, tenant_id=request.tenant_id,
                agent_version=request.agent_version, owner_id=self.owner_id,
                occupancy_generation=occupancy_generation,
                snapshot={'kind': 'customer_handoff_audit', 'agent_id': conversation['agent_id'],
                          'conversation_id': conversation['conversation_id']})
            self._begin_run(cur, request, run, [RunEvent(seq=1, event_type='customer.handoff.audit_started',
                request_id=request.request_id, run_id=run.run_id, tenant_id=request.tenant_id,
                agent_version=request.agent_version, channel='text',
                payload={'conversation_id': conversation['conversation_id'], 'read_only': True})])
            cur.execute("UPDATE runs SET status='succeeded',ended_at=?,finish_reason='handoff_transition' WHERE run_id=?",
                        (now_iso(), run.run_id))
            cur.execute("UPDATE requests SET state='waiting',updated_at=? WHERE request_id=?",
                        (now_iso(), request.request_id))
            tail = cur.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?', (run.run_id,)).fetchone()[0]
            payload = {'conversation_id': conversation['conversation_id'], 'actor_id': actor_id,
                       'occupancy_generation': occupancy_generation}
            if message_sequence is not None:
                payload['message_sequence'] = message_sequence
            self._append(cur, [RunEvent(seq=tail + 1, event_type=event_type, request_id=request.request_id,
                run_id=run.run_id, tenant_id=request.tenant_id, agent_version=request.agent_version,
                channel='text', payload=payload)])
            return
        run = cur.execute('SELECT request_id,tenant_id,agent_version FROM runs WHERE run_id=?',
                          (turn['run_id'],)).fetchone()
        if (run is None or run['request_id'] != turn['request_id']
                or run['tenant_id'] != conversation['tenant_id']
                or run['agent_version'] != turn['version_id']):
            raise RuntimeError('客服接待事件关联不一致')
        tail = cur.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE run_id=?', (turn['run_id'],)).fetchone()[0]
        payload = {'conversation_id': conversation['conversation_id'], 'actor_id': actor_id,
                   'occupancy_generation': occupancy_generation}
        if message_sequence is not None:
            payload['message_sequence'] = message_sequence
        self._append(cur, [RunEvent(seq=tail + 1, event_type=event_type, request_id=turn['request_id'],
            run_id=turn['run_id'], tenant_id=run['tenant_id'], agent_version=run['agent_version'],
            channel='text', payload=payload)])

    def add_operator_message(
        self, *, tenant_id: str, agent_id: str, conversation_id: str, actor_id: str,
        generation: int, text: str, asset_id: str | None = None,
        asset_version_id: str | None = None, derivative_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now_iso()
        with self._tx() as cur:
            if derivative_id is not None and asset_id is None:
                raise ValueError('派生文件必须关联物料与原件版本')
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
                if derivative_id is not None:
                    derivative = cur.execute(
                        'SELECT d.derivative_id FROM material_derivatives d '
                        'JOIN material_derivative_jobs j ON j.job_id=d.job_id '
                        "WHERE d.derivative_id=? AND j.tenant_id=? AND j.agent_id=? AND j.asset_id=? AND j.version_id=? AND j.status='ready'",
                        (derivative_id, tenant_id, agent_id, asset_id, asset_version_id),
                    ).fetchone()
                    if derivative is None:
                        raise RuntimeError('派生文件与所选物料版本不匹配')
            sequence = cur.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM customer_messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()["sequence"]
            cur.execute(
                'INSERT INTO customer_messages(conversation_id,sequence,sender,actor_id,text,asset_id,asset_version_id,created_at,derivative_id) VALUES(?,?,?,?,?,?,?,?,?)',
                (conversation_id, sequence, "operator", actor_id, text, asset_id,
                 asset_version_id, timestamp, derivative_id),
            )
            cur.execute(
                "UPDATE customer_conversations SET updated_at=? WHERE conversation_id=?",
                (timestamp, conversation_id),
            )
            self._append_customer_handoff_event(cur, conversation, 'customer.handoff.replied', actor_id=actor_id,
                occupancy_generation=generation, message_sequence=sequence)
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
            turns = self._conn.execute('SELECT * FROM customer_reception_turns WHERE conversation_id=?',
                                       (conversation_id,)).fetchall()
        values = {row['sequence']: dict(row) for row in rows}
        for turn in turns:
            details = json.loads(turn['details_json'])
            reception = {key: turn[key] for key in ('request_id', 'run_id', 'version_id', 'status')}
            reception['message'] = details.get('message', '正在生成答复')
            values[turn['input_sequence']]['reception'] = reception
            values[turn['input_sequence']]['message_id'] = turn['message_id']
            if turn['response_sequence'] is not None:
                values[turn['response_sequence']].update(reception=reception, citations=details.get('citations', []))
        return list(values.values())

    def customer_attachment(
        self, *, conversation_id: str, visitor_token_hash: str,
        asset_id: str, asset_version_id: str, derivative_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            if derivative_id is not None:
                row = self._conn.execute(
                    'SELECT j.version_id,d.filename,d.media_type,d.content_hash,d.content,d.derivative_id '
                    'FROM customer_conversations c JOIN customer_messages m ON m.conversation_id=c.conversation_id '
                    'JOIN material_assets a ON a.asset_id=m.asset_id AND a.tenant_id=c.tenant_id AND a.agent_id=c.agent_id '
                    'JOIN material_versions v ON v.asset_id=a.asset_id AND v.version_id=m.asset_version_id '
                    'JOIN material_derivatives d ON d.derivative_id=m.derivative_id '
                    'JOIN material_derivative_jobs j ON j.job_id=d.job_id AND j.asset_id=a.asset_id AND j.version_id=v.version_id '
                    'WHERE c.conversation_id=? AND c.visitor_token_hash=? AND m.asset_id=? AND m.asset_version_id=? '
                    "AND m.derivative_id=? AND a.state='active' AND j.status='ready' "
                    'AND (v.expires_at IS NULL OR v.expires_at>?) ORDER BY m.sequence DESC LIMIT 1',
                    (conversation_id, visitor_token_hash, asset_id, asset_version_id, derivative_id, now_iso()),
                ).fetchone()
                return dict(row) if row else None
            row = self._conn.execute(
                "SELECT v.version_id,v.display_name,v.filename,v.media_type,v.authorization,"
                "v.expires_at,v.content_hash,v.content FROM customer_conversations c "
                "JOIN customer_messages m ON m.conversation_id=c.conversation_id "
                "JOIN material_assets a ON a.asset_id=m.asset_id "
                "JOIN material_versions v ON v.asset_id=a.asset_id AND v.version_id=m.asset_version_id "
                "WHERE c.conversation_id=? AND c.visitor_token_hash=? "
                "AND m.asset_id=? AND m.asset_version_id=? AND m.derivative_id IS NULL AND a.state='active' "
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
