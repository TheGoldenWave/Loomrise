"""Explicit, budgeted diagnosis jobs; no scheduler or online business authority."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import threading
import time
from typing import Any

from .configuration import ConfigurationPrincipal
from .contracts import new_id, now_iso
from .diagnostics import (
    DiagnosticsService, REPORT_JSON_SCHEMA,
    ALLOWED_PROVIDER_KINDS, PROVIDER_CONTRACT_HASH, PROVIDER_VERSIONS,
    PROVIDER_KIND_OFFLINE_SCRIPTED, PROVIDER_KIND_STRUCTURED,
)

DIAGNOSIS_TOOL = {"name": "diagnosis_evidence", "version": "v1", "input_schema": {
    "type": "object", "properties": {}, "additionalProperties": False}}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class GovernanceJobs:
    """Persist explicit diagnosis attempts; unknown provider work is never retried."""

    def __init__(self, diagnostics: DiagnosticsService, *, provider=None):
        self.diagnostics = diagnostics
        self.store = diagnostics.store
        self.provider = provider
        self._active: dict[tuple[str, int], tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}
        self._active_lock = threading.Lock()

    def _row(self, cur, *, principal, agent_id, job_id):
        self.diagnostics._principal(principal, agent_id)
        row = cur.execute(
            "SELECT * FROM governance_jobs WHERE job_id=? AND tenant_id=? AND agent_id=? AND actor_id=?",
            (job_id, principal.tenant_id, agent_id, principal.actor_id),
        ).fetchone()
        if row is None:
            raise PermissionError("无治理作业权限")
        result = dict(row)
        try:
            frozen = json.loads(result.pop("frozen_json"))
            if _hash(frozen) != result["frozen_hash"]:
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("治理作业快照损坏") from None
        if (not isinstance(frozen, dict) or frozen.get("purpose") != "diagnosis"
                or frozen.get("principal_actor_id") != principal.actor_id):
            raise ValueError("治理作业快照损坏")
        result["frozen"] = frozen
        return result

    @staticmethod
    def _editable(principal):
        if (not isinstance(principal, ConfigurationPrincipal)
                or principal.role not in {"owner", "editor"}):
            raise PermissionError("作业控制仅限 owner 或 editor")

    def _control(self, cur, *, principal, agent_id, job_id):
        self._editable(principal)
        return self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)

    def _permission_tx(self, cur, *, principal, agent_id, frozen):
        return self.diagnostics._permission_tx(
            cur, principal=principal, agent_id=agent_id, permission_id=frozen["permission_id"])

    def create(self, *, principal: ConfigurationPrincipal, agent_id: str, permission_id: str,
               idempotency_key: str, max_attempts: int = 1, total_seconds: int = 120,
               total_tokens: int = 16000, attempt_tokens: int = 8000,
               max_output_bytes: int = 16384) -> dict[str, Any]:
        self._editable(principal)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise ValueError("作业幂等键无效")
        for value, lower, upper in ((max_attempts, 1, 3), (total_seconds, 1, 300),
                                    (total_tokens, 1, 100000), (attempt_tokens, 1, total_tokens),
                                    (max_output_bytes, 256, 16384)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("作业预算无效")
        descriptor = getattr(self.provider, "descriptor", None)
        if (not isinstance(descriptor, dict) or not isinstance(descriptor.get("provider_id"), str)
                or not descriptor["provider_id"].strip()):
            raise ValueError("未配置可用治理 Provider")
        # 类别必须显式声明且属于服务端登记的非真实类别。禁止调用方自报 real，
        # 否则脚本替身会被当作真实 Provider 证据。
        kind = descriptor.get("provider_kind")
        if not isinstance(kind, str) or kind not in ALLOWED_PROVIDER_KINDS:
            raise ValueError("治理 Provider 类别缺失、自报真实类别或不受支持")
        # 版本必须与类别一致，防止替身贴用真实 harness 的版本号。
        if descriptor.get("version") != PROVIDER_VERSIONS.get(kind):
            raise ValueError("治理 Provider 版本与类别不一致")
        # 绑定当前合同 hash；旧版或错误合同的 Provider 不得被当作当前 Provider。
        if descriptor.get("contract_hash") != PROVIDER_CONTRACT_HASH:
            raise ValueError("治理 Provider 合同版本不匹配")
        try:
            descriptor = deepcopy(descriptor)
        except Exception:
            raise ValueError("治理 Provider 描述无效") from None
        snapshot = self.diagnostics.read_evidence(
            principal=principal, agent_id=agent_id, permission_id=permission_id)
        evidence_class = {
            PROVIDER_KIND_OFFLINE_SCRIPTED: "offline_scripted",
            PROVIDER_KIND_STRUCTURED: "offline_structured",
        }[kind]
        frozen = {
            "purpose": "diagnosis", "principal_actor_id": principal.actor_id,
            "permission_id": permission_id, "snapshot_id": snapshot["snapshot_id"],
            "input_hash": snapshot["snapshot_hash"], "provider": descriptor,
            "evidence_class": evidence_class,
            "tools": [deepcopy(DIAGNOSIS_TOOL)], "tool_hash": _hash([DIAGNOSIS_TOOL]),
            "report_schema_hash": _hash(REPORT_JSON_SCHEMA), "max_attempts": max_attempts,
            "total_seconds": total_seconds, "total_tokens": total_tokens,
            "attempt_tokens": attempt_tokens, "max_output_bytes": max_output_bytes,
        }
        try:
            frozen_json = _canonical(frozen)
            frozen_hash = _hash(frozen)
        except (TypeError, ValueError, RecursionError):
            raise ValueError("治理 Provider 描述无效") from None
        now = now_iso()
        with self.store._tx() as cur:
            self._permission_tx(cur, principal=principal, agent_id=agent_id, frozen=frozen)
            snapshot_row = cur.execute(
                "SELECT * FROM diagnosis_snapshots WHERE permission_id=? AND snapshot_id=?",
                (permission_id, frozen["snapshot_id"]),
            ).fetchone()
            try:
                persisted_snapshot = (self.diagnostics._load_snapshot(snapshot_row)
                                      if snapshot_row is not None else None)
            except (TypeError, ValueError):
                raise ValueError("治理作业输入已变化") from None
            if (persisted_snapshot is None or persisted_snapshot["snapshot_hash"] != frozen["input_hash"]):
                raise ValueError("治理作业输入已变化")
            existing = cur.execute(
                "SELECT job_id,frozen_hash FROM governance_jobs "
                "WHERE tenant_id=? AND agent_id=? AND actor_id=? AND idempotency_key=?",
                (principal.tenant_id, agent_id, principal.actor_id, idempotency_key),
            ).fetchone()
            if existing:
                if existing["frozen_hash"] != frozen_hash:
                    raise ValueError("幂等键已用于不同治理输入")
                return self._row(cur, principal=principal, agent_id=agent_id, job_id=existing["job_id"])
            job_id = new_id("gov")
            cur.execute(
                "INSERT INTO governance_jobs(job_id,tenant_id,agent_id,actor_id,idempotency_key,frozen_json,"
                "frozen_hash,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (job_id, principal.tenant_id, agent_id, principal.actor_id, idempotency_key,
                 frozen_json, frozen_hash, "queued", now, now),
            )
            return self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)

    def read(self, *, principal, agent_id, job_id):
        self.diagnostics._principal(principal, agent_id)
        with self.store._lock:
            cur = self.store._conn.cursor()
            try:
                result = self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
                result["history"] = [dict(row) for row in cur.execute(
                    "SELECT * FROM governance_attempts WHERE job_id=? ORDER BY generation", (job_id,))]
                return result
            finally:
                cur.close()

    def cancel(self, *, principal, agent_id, job_id):
        active_key = None
        with self.store._tx() as cur:
            row = self._control(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            if row["state"] == "queued":
                cur.execute(
                    "UPDATE governance_jobs SET state='cancelled',reason='cancelled_before_start',updated_at=? "
                    "WHERE job_id=? AND state='queued' AND generation=?",
                    (now_iso(), job_id, row["generation"]),
                )
                if cur.rowcount != 1:
                    raise ValueError("作业取消竞争：状态或代次已变化，请重新读取后重试")
            elif row["state"] == "running":
                cur.execute(
                    "UPDATE governance_jobs SET state='cancel_requested',reason='cancel_requested',updated_at=? "
                    "WHERE job_id=? AND state='running' AND generation=?",
                    (now_iso(), job_id, row["generation"]),
                )
                if cur.rowcount != 1:
                    raise ValueError("作业取消竞争：状态或代次已变化，请重新读取后重试")
                active_key = (job_id, row["generation"])
            elif row["state"] == "cancel_requested":
                active_key = (job_id, row["generation"])
            elif (row["state"] == "interrupted" and row["provider_state"] == "unknown"
                    and row["owner_id"] == self.store.owner_id):
                active_key = (job_id, row["generation"])
        if active_key is not None:
            with self._active_lock:
                active = self._active.get(active_key)
            if active is not None:
                loop, task = active
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass
        return self.read(principal=principal, agent_id=agent_id, job_id=job_id)

    def recover(self, *, principal, agent_id, job_id):
        """Explicit restart adjudication fences old output; it never resumes a call."""
        with self.store._tx() as cur:
            row = self._control(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            if row["state"] in {"running", "cancel_requested"} and row["owner_id"] != self.store.owner_id:
                cur.execute(
                    "UPDATE governance_jobs SET state='interrupted',provider_state='unknown',"
                    "generation=generation+1,reason='restart_interrupted',updated_at=? "
                    "WHERE job_id=? AND state=? AND generation=? AND owner_id<>?",
                    (now_iso(), job_id, row["state"], row["generation"], self.store.owner_id),
                )
                if cur.rowcount == 1:
                    cur.execute(
                        "UPDATE governance_attempts SET provider_state='unknown',reason='restart_interrupted' "
                        "WHERE job_id=? AND generation=?",
                        (job_id, row["generation"]),
                    )
            elif row["state"] in {"running", "cancel_requested"}:
                raise ValueError("当前进程作业不能按重启裁决")
        return self.read(principal=principal, agent_id=agent_id, job_id=job_id)

    def retry(self, *, principal, agent_id, job_id):
        exhausted = False
        with self.store._tx() as cur:
            row = self._control(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            frozen = row["frozen"]
            self._permission_tx(cur, principal=principal, agent_id=agent_id, frozen=frozen)
            if row["state"] not in {"failed", "interrupted", "cancelled"} or row["provider_state"] not in {
                    "not_started", "stopped"}:
                raise ValueError("Provider 未确认停止或作业不可重试")
            if (row["attempts"] >= frozen["max_attempts"]
                    or row["elapsed_ms"] >= frozen["total_seconds"] * 1000
                    or row["reserved_tokens"] + frozen["attempt_tokens"] > frozen["total_tokens"]):
                cur.execute(
                    "UPDATE governance_jobs SET state='exhausted',reason='budget_exhausted',updated_at=? "
                    "WHERE job_id=? AND state=? AND generation=?",
                    (now_iso(), job_id, row["state"], row["generation"]),
                )
                exhausted = True
            else:
                cur.execute(
                    "UPDATE governance_jobs SET state='queued',reason=NULL,updated_at=? "
                    "WHERE job_id=? AND state=? AND generation=?",
                    (now_iso(), job_id, row["state"], row["generation"]),
                )
                if cur.rowcount != 1:
                    raise ValueError("作业代次已变化")
        if exhausted:
            raise ValueError("治理作业预算已耗尽")
        return self.read(principal=principal, agent_id=agent_id, job_id=job_id)

    def _read_evidence_tx(self, cur, *, principal, agent_id, job_id, generation, frozen):
        live = self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
        if live["state"] != "running" or live["generation"] != generation:
            raise PermissionError("作业已取消或代次变化")
        permission = self._permission_tx(
            cur, principal=principal, agent_id=agent_id, frozen=frozen)
        row = cur.execute("SELECT * FROM diagnosis_snapshots WHERE permission_id=?",
                          (frozen["permission_id"],)).fetchone()
        if row is None:
            snapshot = self.diagnostics._snapshot_tx(cur, permission)
            cur.execute("INSERT INTO diagnosis_snapshots VALUES(?,?,?,?,?)",
                        (snapshot["snapshot_id"], frozen["permission_id"], snapshot["snapshot_hash"],
                         _canonical(snapshot), snapshot["created_at"]))
        else:
            snapshot = self.diagnostics._load_snapshot(row)
        if (snapshot["snapshot_id"] != frozen["snapshot_id"]
                or snapshot["snapshot_hash"] != frozen["input_hash"]):
            raise ValueError("治理作业输入已变化")
        return deepcopy(snapshot)

    def _mark_provider_invoked(self, *, principal, agent_id, job_id, generation, frozen):
        with self.store._tx() as cur:
            row = self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            if row["state"] != "running" or row["generation"] != generation:
                raise PermissionError("作业已取消或代次变化")
            self._permission_tx(cur, principal=principal, agent_id=agent_id, frozen=frozen)
            if (getattr(self.provider, "descriptor", None) != frozen["provider"]
                    or _hash([DIAGNOSIS_TOOL]) != frozen["tool_hash"]
                    or _hash(REPORT_JSON_SCHEMA) != frozen["report_schema_hash"]):
                raise ValueError("Provider 或工具合同已变化")
            cur.execute(
                "UPDATE governance_jobs SET provider_state='unknown',updated_at=? "
                "WHERE job_id=? AND state='running' AND generation=?",
                (now_iso(), job_id, generation),
            )
            if cur.rowcount != 1:
                raise PermissionError("作业已取消或代次变化")
            cur.execute(
                "UPDATE governance_attempts SET provider_state='unknown' WHERE job_id=? AND generation=?",
                (job_id, generation),
            )

    def _register_active(self, job_id, generation):
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        with self._active_lock:
            self._active[(job_id, generation)] = (loop, task)

    def _unregister_active(self, job_id, generation):
        with self._active_lock:
            self._active.pop((job_id, generation), None)

    def _timeout_fence(self, principal, agent_id, job_id, generation, frozen, started):
        """Persist the timeout fence even when the provider suppresses cancellation."""
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        try:
            with self.store._tx() as cur:
                live = self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
                if (live["generation"] != generation or live["frozen"] != frozen
                        or live["state"] != "running"):
                    return
                cur.execute(
                    "UPDATE governance_jobs SET state='interrupted',provider_state='unknown',"
                    "reason='provider_timeout',elapsed_ms=elapsed_ms+?,updated_at=? "
                    "WHERE job_id=? AND state='running' AND generation=?",
                    (elapsed_ms, now_iso(), job_id, generation),
                )
                if cur.rowcount == 1:
                    cur.execute(
                        "UPDATE governance_attempts SET provider_state='unknown',elapsed_ms=?,"
                        "reason='provider_timeout' WHERE job_id=? AND generation=?",
                        (elapsed_ms, job_id, generation),
                    )
        except Exception:
            # The awaiting task will attempt the same conservative transition when it resumes.
            return

    def _finalize(self, *, principal, agent_id, job_id, generation, frozen, state,
                  provider_state, reason, usage_json, report, deadline, elapsed_ms):
        with self.store._tx() as cur:
            live = self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            if live["generation"] != generation or live["frozen"] != frozen:
                return
            if live["state"] == "interrupted" and live["reason"] == "provider_timeout":
                if provider_state == "stopped":
                    cur.execute(
                        "UPDATE governance_jobs SET provider_state='stopped',updated_at=? "
                        "WHERE job_id=? AND generation=? AND state='interrupted' AND reason='provider_timeout'",
                        (now_iso(), job_id, generation),
                    )
                    cur.execute(
                        "UPDATE governance_attempts SET provider_state='stopped' "
                        "WHERE job_id=? AND generation=? AND reason='provider_timeout'",
                        (job_id, generation),
                    )
                return
            if live["state"] not in {"running", "cancel_requested"}:
                return
            if live["state"] == "cancel_requested":
                state, reason = "cancelled", "cancel_requested"
            elif state == "succeeded":
                if deadline is not None and time.monotonic() >= deadline:
                    state, reason = "interrupted", "provider_timeout"
                else:
                    try:
                        created = self.diagnostics._submit_report_tx(
                            cur, principal=principal, agent_id=agent_id,
                            permission_id=frozen["permission_id"], snapshot_id=frozen["snapshot_id"],
                            input_hash=frozen["input_hash"], report=report,
                        )
                    except PermissionError:
                        state, reason = "failed", "authority_revoked"
                    except (TypeError, ValueError):
                        state, reason = "failed", "provider_output_invalid"
                    else:
                        report_id = created["report_id"]
                        cur.execute(
                            "UPDATE governance_jobs SET state='succeeded',provider_state=?,report_id=?,reason=NULL,"
                            "elapsed_ms=elapsed_ms+?,updated_at=? WHERE job_id=? AND generation=? AND state='running'",
                            (provider_state, report_id, elapsed_ms, now_iso(), job_id, generation),
                        )
                        if cur.rowcount != 1:
                            raise ValueError("作业代次已变化")
                        cur.execute(
                            "UPDATE governance_attempts SET provider_state=?,usage_json=?,elapsed_ms=?,reason=NULL "
                            "WHERE job_id=? AND generation=?",
                            (provider_state, usage_json, elapsed_ms, job_id, generation),
                        )
                        return
            cur.execute(
                "UPDATE governance_jobs SET state=?,provider_state=?,report_id=NULL,reason=?,"
                "elapsed_ms=elapsed_ms+?,updated_at=? WHERE job_id=? AND generation=? "
                "AND state IN ('running','cancel_requested')",
                (state, provider_state, reason, elapsed_ms, now_iso(), job_id, generation),
            )
            if cur.rowcount == 1:
                cur.execute(
                    "UPDATE governance_attempts SET provider_state=?,usage_json=?,elapsed_ms=?,reason=? "
                    "WHERE job_id=? AND generation=?",
                    (provider_state, usage_json, elapsed_ms, reason, job_id, generation),
                )

    async def run(self, *, principal, agent_id, job_id):
        self._editable(principal)
        with self.store._tx() as cur:
            row = self._control(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            frozen = row["frozen"]
            if row["state"] != "queued":
                raise ValueError("作业不是待启动状态")
            self._permission_tx(cur, principal=principal, agent_id=agent_id, frozen=frozen)
            if (getattr(self.provider, "descriptor", None) != frozen["provider"]
                    or _hash([DIAGNOSIS_TOOL]) != frozen["tool_hash"]
                    or _hash(REPORT_JSON_SCHEMA) != frozen["report_schema_hash"]):
                raise ValueError("Provider 或工具合同已变化")
            if (row["attempts"] >= frozen["max_attempts"]
                    or row["elapsed_ms"] >= frozen["total_seconds"] * 1000
                    or row["reserved_tokens"] + frozen["attempt_tokens"] > frozen["total_tokens"]):
                cur.execute(
                    "UPDATE governance_jobs SET state='exhausted',reason='budget_exhausted',updated_at=? "
                    "WHERE job_id=? AND state='queued' AND generation=?",
                    (now_iso(), job_id, row["generation"]),
                )
                return self._row(cur, principal=principal, agent_id=agent_id, job_id=job_id)
            generation = row["generation"] + 1
            reserved = frozen["attempt_tokens"]
            cur.execute(
                "UPDATE governance_jobs SET state='running',generation=?,attempts=attempts+1,"
                "reserved_tokens=reserved_tokens+?,provider_state='not_started',report_id=NULL,"
                "owner_id=?,reason=NULL,updated_at=? WHERE job_id=? AND state='queued' AND generation=?",
                (generation, reserved, self.store.owner_id, now_iso(), job_id, row["generation"]),
            )
            if cur.rowcount != 1:
                raise ValueError("作业领取冲突")
            cur.execute(
                "INSERT INTO governance_attempts(job_id,generation,provider_state,reserved_tokens) "
                "VALUES(?,?,?,?)",
                (job_id, generation, "not_started", reserved),
            )

        remaining = frozen["total_seconds"] - row["elapsed_ms"] / 1000
        started = time.monotonic()
        deadline = started + remaining
        self._register_active(job_id, generation)
        result = None
        snapshot = None
        state, reason, provider_state = "failed", "provider_failed", "not_started"
        usage_json = None
        validated_report = None
        external_cancel = False
        finalization_error = None
        invocation_started = False
        timeout_context = None
        timeout_handle = None
        try:
            with self.store._tx() as cur:
                snapshot = self._read_evidence_tx(
                    cur, principal=principal, agent_id=agent_id, job_id=job_id,
                    generation=generation, frozen=frozen,
                )
            if time.monotonic() >= deadline:
                state, reason = "interrupted", "provider_timeout"
            else:
                self._mark_provider_invoked(
                    principal=principal, agent_id=agent_id, job_id=job_id,
                    generation=generation, frozen=frozen,
                )
                invocation_started = True

                def evidence():
                    with self.store._tx() as cur:
                        return self._read_evidence_tx(
                            cur, principal=principal, agent_id=agent_id, job_id=job_id,
                            generation=generation, frozen=frozen,
                        )

                timeout_context = asyncio.timeout(max(0, deadline - time.monotonic()))
                timeout_handle = asyncio.get_running_loop().call_later(
                    max(0, deadline - time.monotonic()), self._timeout_fence,
                    principal, agent_id, job_id, generation, frozen, started,
                )
                try:
                    async with timeout_context:
                        result = await self.provider.run(
                            snapshot=deepcopy(snapshot), read_evidence=evidence,
                            token_budget=frozen["attempt_tokens"],
                            max_output_bytes=frozen["max_output_bytes"],
                        )
                finally:
                    timeout_handle.cancel()
                result_shape_ok = isinstance(result, dict) and set(result) == {
                    "report", "usage", "provider_state"}
                if (result_shape_ok and result["provider_state"] in {"stopped", "unknown", "not_started"}):
                    provider_state = result["provider_state"]
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    state, reason = "interrupted", "caller_interrupted"
                elif time.monotonic() >= deadline or timeout_context.expired():
                    state, reason = "interrupted", "provider_timeout"
                elif not result_shape_ok:
                    state, reason, provider_state = "failed", "provider_result_invalid", "unknown"
                elif result["provider_state"] not in {"stopped", "unknown", "not_started"}:
                    state, reason, provider_state = "failed", "provider_state_invalid", "unknown"
                else:
                    provider_state = result["provider_state"]
                    if provider_state != "stopped":
                        state = "interrupted" if provider_state == "unknown" else "failed"
                        reason = "provider_execution_unknown" if provider_state == "unknown" else "provider_not_started"
                    else:
                        usage = result["usage"]
                        if (not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}
                                or any(type(n) is not int or not 0 <= n <= frozen["attempt_tokens"]
                                       for n in usage.values())):
                            state, reason = "failed", "provider_usage_invalid"
                        elif sum(usage.values()) > frozen["attempt_tokens"]:
                            state, reason = "exhausted", "provider_budget_exceeded"
                        else:
                            usage_json = _canonical(usage)
                            try:
                                if len(_canonical(result["report"]).encode("utf-8")) > frozen["max_output_bytes"]:
                                    raise ValueError
                                validated_report = self.diagnostics.validate_report(result["report"], snapshot)
                            except (TypeError, ValueError, RecursionError):
                                state, reason = "failed", "provider_output_invalid"
                            else:
                                state, reason = "succeeded", None
        except asyncio.CancelledError:
            state = "cancelled"
            reason = "cancel_requested"
            provider_state = "unknown" if invocation_started else "not_started"
            external_cancel = True
            state, reason = "interrupted", "caller_interrupted"
        except TimeoutError:
            state, reason = "interrupted", "provider_timeout"
            provider_state = "unknown" if invocation_started else "not_started"
        except PermissionError:
            state, reason = "failed", "authority_or_job_state_changed"
            provider_state = "unknown" if invocation_started else "not_started"
        except ValueError:
            state, reason = "failed", "authority_input_or_provider_changed"
            provider_state = "unknown" if invocation_started else "not_started"
        except Exception:
            # Provider exception messages can contain credentials or customer data.
            state, reason = "failed", "provider_failed"
            provider_state = "unknown" if invocation_started else "not_started"
        finally:
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            try:
                try:
                    self._finalize(
                        principal=principal, agent_id=agent_id, job_id=job_id,
                        generation=generation, frozen=frozen, state=state,
                        provider_state=provider_state, reason=reason, usage_json=usage_json,
                        report=validated_report, deadline=deadline if state == "succeeded" else None,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception as exc:
                    try:
                        self._finalize(
                            principal=principal, agent_id=agent_id, job_id=job_id,
                            generation=generation, frozen=frozen,
                            state="failed" if state == "succeeded" else state,
                            provider_state=provider_state,
                            reason="result_commit_failed" if state == "succeeded" else "finalization_failed",
                            usage_json=usage_json, report=None, deadline=None, elapsed_ms=elapsed_ms,
                        )
                    except Exception:
                        finalization_error = exc
            finally:
                self._unregister_active(job_id, generation)
        if external_cancel:
            raise asyncio.CancelledError
        if finalization_error is not None:
            raise finalization_error
        return self.read(principal=principal, agent_id=agent_id, job_id=job_id)


__all__ = ["GovernanceJobs", "DIAGNOSIS_TOOL"]
