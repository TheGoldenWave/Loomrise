"""Authorization, provenance, redaction and transactional diagnostic boundaries."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from loomrise.configuration import ConfigurationPrincipal
from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest, new_id
from loomrise.diagnostics import (
    DiagnosticIntegrityError, DiagnosticsService, EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_HASH, MAX_EVENTS_PER_RUN, MAX_REPORT_BYTES, MAX_SNAPSHOT_BYTES, ORIGINAL_CASE_REGISTRY,
    REPORT_CATEGORIES, REPORT_JSON_SCHEMA, REPORT_SCHEMA_VERSION, TrustedDiagnosticCase,
)
from loomrise.durable_store import SCHEMA_VERSION, SqliteStore


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class DiagnosticsCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "diagnosis.db")
        self.store = SqliteStore(self.path)
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.service = DiagnosticsService(self.store, clock=lambda: self.now)
        self.owner = ConfigurationPrincipal("tenant-a", "owner-a", "owner", ("expert-a", "expert-b"))
        self.recipient = ConfigurationPrincipal("tenant-a", "diagnostician", "external_agent", ("expert-a",))
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: self.store.close())

    def seed(self, *, tenant="tenant-a", agent="expert-a", version="v1", attributed=True):
        self.store.register_stable_config(tenant_id=tenant, agent_id=agent, version_id=version,
            config={"persona": {"goal": "CONFIGURATION_SECRET"}}, content_hash="a" * 64)
        request = ServiceRequest(new_id("req"), tenant, version, Channel.TEXT, RequestState.QUEUED)
        run = Run(new_id("run"), request.request_id, tenant, version,
                  snapshot={"agent_id": agent} if attributed else {})
        self.store.begin_run(request, run, [])
        return run

    def events(self, run, rows):
        seq = self.store.next_seq(run.run_id)
        events = [RunEvent(seq + i, kind, run.request_id, run.run_id, run.tenant_id,
                          run.agent_version, "text", payload=payload) for i, (kind, payload) in enumerate(rows)]
        self.store.append_events(events)
        return events

    def permit(self, run=None, **kwargs):
        run_ids = [run.run_id] if run else []
        return self.service.issue(principal=self.owner, agent_id="expert-a",
                                  recipient_actor_id=self.recipient.actor_id, run_ids=run_ids, **kwargs)

    def evidence(self, permission):
        return self.service.read_evidence(principal=self.recipient, agent_id="expert-a",
                                          permission_id=permission["permission_id"])

    @staticmethod
    def report(snapshot, **updates):
        item = (snapshot["runs"] or snapshot["cases"])[0]
        finding = {
            "category": "loading", "summary": "需要检查加载决策。", "recommendation": "增加针对性回放后由人审阅。",
            "evidence_ids": [item["evidence_id"]],
        }
        result = {"schema_version": REPORT_SCHEMA_VERSION, "status": "proposal", "findings": [finding],
                  "insufficient_categories": [category for category in REPORT_CATEGORIES if category != "loading"],
                  "limitations": snapshot["limitations"].copy()}
        result.update(updates)
        return result

    def submit(self, permission, snapshot, report=None):
        return self.service.submit_report(principal=self.recipient, agent_id="expert-a",
            permission_id=permission["permission_id"], snapshot_id=snapshot["snapshot_id"],
            input_hash=snapshot["snapshot_hash"], report=report if report is not None else self.report(snapshot))


class TestDiagnosticPermission(DiagnosticsCase):
    def test_only_owner_can_issue_for_explicit_owned_sources_and_bounded_time(self):
        run = self.seed()
        for principal in (self.recipient, replace(self.owner, role="editor"),
                          replace(self.owner, tenant_id="tenant-b"), replace(self.owner, agent_ids=("expert-b",))):
            with self.subTest(principal=principal), self.assertRaises(PermissionError):
                self.service.issue(principal=principal, agent_id="expert-a", recipient_actor_id="diagnostician",
                                   run_ids=[run.run_id])
        for arguments in ({"run_ids": []}, {"run_ids": [run.run_id] * 2},
                          {"run_ids": [str(i) for i in range(11)]},
                          {"run_ids": [run.run_id], "expires_in_seconds": True},
                          {"run_ids": [run.run_id], "expires_in_seconds": 3601},
                          {"run_ids": [run.run_id], "expires_in_seconds": 0}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.service.issue(principal=self.owner, agent_id="expert-a", recipient_actor_id="diagnostician", **arguments)
        with self.assertRaises(PermissionError):
            self.service.issue(principal={"role": "owner"}, agent_id="expert-a", recipient_actor_id="diagnostician",
                               run_ids=[run.run_id])
        permission = self.permit(run)
        self.assertEqual(permission["recipient_actor_id"], "diagnostician")
        self.assertEqual(permission["purpose"], "diagnosis")

    def test_permission_persists_contract_version_and_hash_and_rejects_stale_contract(self):
        permission = self.permit(self.seed())
        stored = self.store._conn.execute("SELECT selection_json FROM diagnosis_permissions WHERE permission_id=?",
                                          (permission["permission_id"],)).fetchone()
        selection = json.loads(stored["selection_json"])
        self.assertEqual(selection["evidence_contract"], {
            "schema_version": EVIDENCE_SCHEMA_VERSION, "schema_hash": EVIDENCE_SCHEMA_HASH,
        })
        self.assertEqual(self.service.read_permission(principal=self.recipient, agent_id="expert-a",
                                                      permission_id=permission["permission_id"])["selection"], selection)
        selection["evidence_contract"]["schema_hash"] = "0" * 64
        with self.store._tx() as cur:
            row = cur.execute("SELECT * FROM diagnosis_permissions WHERE permission_id=?",
                              (permission["permission_id"],)).fetchone()
            value = {key: row[key] for key in ("permission_id", "tenant_id", "agent_id", "recipient_actor_id",
                                               "issued_by", "purpose", "issued_at", "expires_at")}
            value["selection"] = selection
            stale_hash = hashlib.sha256(canonical(value).encode()).hexdigest()
            cur.execute("UPDATE diagnosis_permissions SET selection_json=?,permission_hash=? WHERE permission_id=?",
                        (canonical(selection), stale_hash, permission["permission_id"]))
        # 两条路径显式分离（本轮合同）：
        #   (A) 普通读取仍拒绝旧证据合同 hash（读路径，下面第一条负向断言）；
        #   (B) 撤权是安全动作，不受证据合同/来源完整性影响，始终可执行。
        # 原断言曾期望 revoke 同样抛 DiagnosticIntegrityError，与 (B) 冲突，
        # 故在此改写为「读拒绝 / 撤权成功 / 撤权后读取仍拒绝」三段显式断言，
        # 明确区分两条路径，而不是删掉旧断言绕过。
        with self.assertRaises(DiagnosticIntegrityError):
            self.service.read_permission(principal=self.recipient, agent_id="expert-a",
                                         permission_id=permission["permission_id"])
        revoked = self.service.revoke(principal=self.owner, agent_id="expert-a",
                                      permission_id=permission["permission_id"])
        self.assertIsNotNone(revoked["revoked_at"])
        self.assertEqual(self.store._conn.execute(
            "SELECT revoked_at FROM diagnosis_permissions WHERE permission_id=?",
            (permission["permission_id"],)).fetchone()[0], revoked["revoked_at"])
        # 撤权后普通读取仍被拒：撤权成功绝不意味着放行读取（旧合同 hash 与
        # 撤销状态任一都会挡住）。这条负向断言把 (A)(B) 两条路径明确分开。
        with self.assertRaises(DiagnosticIntegrityError):
            self.service.read_evidence(principal=self.recipient, agent_id="expert-a",
                                       permission_id=permission["permission_id"])

    def test_shared_version_is_not_run_ownership_and_legacy_attribution_is_rejected(self):
        others = [self.seed(tenant="tenant-b"), self.seed(agent="expert-b"), self.seed(attributed=False)]
        for run in others:
            with self.subTest(run=run), self.assertRaises(PermissionError):
                self.permit(run)
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_permissions").fetchone()[0], 0)

    def test_tenant_agent_and_exact_recipient_are_checked_on_every_operation(self):
        permission = self.permit(self.seed())
        snapshot = self.evidence(permission)
        report = self.submit(permission, snapshot)
        for principal, agent in ((replace(self.recipient, tenant_id="tenant-b"), "expert-a"),
                                 (replace(self.recipient, agent_ids=("expert-a", "expert-b")), "expert-b"),
                                 (replace(self.recipient, actor_id="other-actor"), "expert-a"),
                                 (self.owner, "expert-a")):
            for action in ("evidence", "submit", "report"):
                with self.subTest(principal=principal, agent=agent, action=action), self.assertRaises(PermissionError):
                    if action == "evidence":
                        self.service.read_evidence(principal=principal, agent_id=agent,
                                                   permission_id=permission["permission_id"])
                    elif action == "submit":
                        self.service.submit_report(principal=principal, agent_id=agent,
                            permission_id=permission["permission_id"], snapshot_id=snapshot["snapshot_id"],
                            input_hash=snapshot["snapshot_hash"], report=self.report(snapshot))
                    else:
                        self.service.read_report(principal=principal, agent_id=agent, report_id=report["report_id"])

    def test_existing_snapshot_does_not_bypass_changed_run_attribution(self):
        run = self.seed()
        permission = self.permit(run)
        snapshot = self.evidence(permission)
        report = self.submit(permission, snapshot)
        self.store.update_run_snapshot(run.run_id, {"agent_id": "expert-b"})
        for operation in (lambda: self.evidence(permission), lambda: self.submit(permission, snapshot),
                          lambda: self.service.read_report(principal=self.recipient, agent_id="expert-a",
                                                           report_id=report["report_id"])):
            with self.assertRaises(PermissionError):
                operation()

    def test_expiry_and_revocation_prevent_evidence_report_submit_and_report_read(self):
        for end in ("expiry", "revoke"):
            permission = self.permit(self.seed(version=end), expires_in_seconds=30)
            self.now -= timedelta(seconds=1)
            with self.assertRaises(PermissionError):
                self.evidence(permission)
            self.now += timedelta(seconds=1)
            snapshot = self.evidence(permission)
            report = self.submit(permission, snapshot)
            if end == "expiry":
                self.now += timedelta(seconds=30)
            else:
                with self.assertRaises(PermissionError):
                    self.service.revoke(principal=self.recipient, agent_id="expert-a", permission_id=permission["permission_id"])
                self.service.revoke(principal=self.owner, agent_id="expert-a", permission_id=permission["permission_id"])
            for action in (lambda: self.evidence(permission), lambda: self.submit(permission, snapshot),
                           lambda: self.service.read_report(principal=self.recipient, agent_id="expert-a", report_id=report["report_id"])):
                with self.subTest(end=end), self.assertRaises(PermissionError):
                    action()

    def test_revoke_succeeds_under_stale_contract_changed_sources_and_expiry(self):
        run = self.seed()
        permission = self.permit(run, expires_in_seconds=30)
        pid = permission["permission_id"]
        # 冻结成旧证据合同（重算 permission_hash 保持记录自洽，模拟合同升级），
        # 并把到期时间改到过去。
        with self.store._tx() as cur:
            row = cur.execute("SELECT * FROM diagnosis_permissions WHERE permission_id=?", (pid,)).fetchone()
            selection = json.loads(row["selection_json"])
            selection["evidence_contract"]["schema_hash"] = "0" * 64
            value = {key: row[key] for key in ("permission_id", "tenant_id", "agent_id",
                "recipient_actor_id", "issued_by", "purpose", "issued_at", "expires_at")}
            value["selection"] = selection
            stale = hashlib.sha256(canonical(value).encode()).hexdigest()
            cur.execute("UPDATE diagnosis_permissions SET selection_json=?,permission_hash=?,expires_at=? "
                        "WHERE permission_id=?",
                        (canonical(selection), stale, "2000-01-01T00:00:00+00:00", pid))
        # 再让来源失效：改掉 run 归属，使 _verify_sources_tx 也会失败。
        self.store.update_run_snapshot(run.run_id, {"agent_id": "expert-b"})
        # 旧合同 hash、过期、来源变化三者叠加，撤销仍必须始终可执行。
        revoked = self.service.revoke(principal=self.owner, agent_id="expert-a", permission_id=pid)
        self.assertIsNotNone(revoked["revoked_at"])
        self.assertEqual(self.store._conn.execute(
            "SELECT revoked_at FROM diagnosis_permissions WHERE permission_id=?", (pid,)).fetchone()[0],
            revoked["revoked_at"])
        # 非 owner 仍不能撤销（身份校验没有被放宽）。
        with self.assertRaises(PermissionError):
            self.service.revoke(principal=self.recipient, agent_id="expert-a", permission_id=pid)


class TestDiagnosticEvidence(DiagnosticsCase):
    def test_waiting_contract_and_real_permission_decision_use_fixed_values(self):
        run = self.seed()
        self.events(run, [("permission.decision", {"verdict": "pass", "authorized": True,
                                                    "reason": "SECRET", "tool": "SECRET"})])
        with self.store._tx() as cur:
            cur.execute("UPDATE requests SET state='waiting_confirm' WHERE request_id=?", (run.request_id,))
        snapshot = self.evidence(self.permit(run))
        self.assertEqual(snapshot["runs"][0]["request_state"], "waiting_confirm")
        self.assertEqual(snapshot["runs"][0]["events"][0]["data"], {"verdict": "pass", "authorized": True})
        self.assertNotIn("SECRET", canonical(snapshot))

    def test_snapshot_hash_exact_evidence_ids_immutable_and_no_customer_or_configuration_text(self):
        run = self.seed()
        events = self.events(run, [
            ("run.started", {"input": "CUSTOMER_SECRET"}),
            ("recall.diagnostic", {"code": "selected", "candidate_count": 2, "selected_count": 1,
                                   "unit_id": "UNIT_SECRET", "reason": "FREE_ERROR_SECRET"}),
            ("tool.outcome", {"outcome": "success", "duration_ms": 15, "result_id": "RESULT_SECRET",
                              "arguments": {"token": "CREDENTIAL_SECRET"}, "result": "TOOL_SECRET"}),
            ("reply.text", {"text": "REPLY_SECRET"}),
        ])
        permission = self.permit(run)
        snapshot = self.evidence(permission)
        wire = canonical(snapshot)
        for secret in ("CUSTOMER_SECRET", "CONFIGURATION_SECRET", "UNIT_SECRET", "FREE_ERROR_SECRET",
                       "RESULT_SECRET", "CREDENTIAL_SECRET", "TOOL_SECRET", "REPLY_SECRET", run.run_id, run.request_id):
            self.assertNotIn(secret, wire)
        self.assertEqual(snapshot["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(self.service.read_permission(principal=self.recipient, agent_id="expert-a",
            permission_id=permission["permission_id"])["selection"]["evidence_contract"]["schema_hash"], EVIDENCE_SCHEMA_HASH)
        expected_hash = hashlib.sha256(canonical({k: v for k, v in snapshot.items() if k != "snapshot_hash"}).encode()).hexdigest()
        self.assertEqual(snapshot["snapshot_hash"], expected_hash)
        projected = snapshot["runs"][0]
        self.assertEqual(projected["gaps"]["included_event_count"], 3)
        self.assertEqual(projected["gaps"]["omitted_event_count"], 1)
        self.assertEqual(projected["events"][1]["source_hash"], events[1].hash)
        self.assertEqual(projected["events"][1]["data"], {"code": "selected", "candidate_count": 2, "selected_count": 1})
        self.events(run, [("run.finished", {"write_count": 0})])
        self.assertEqual(self.evidence(permission), snapshot)
        snapshot["runs"][0]["run_status"] = "FORGED"
        self.assertNotEqual(self.evidence(permission), snapshot)

    def test_whitelist_checks_values_not_just_keys_and_rejects_arbitrary_reason_and_unit(self):
        run = self.seed()
        secret = "sensitive-token-DO-NOT-EXPOSE"
        self.events(run, [
            ("recall.diagnostic", {"code": secret, "candidate_count": True, "selected_count": -1,
                                   "max_units": 100_001, "unit_id": secret, "provider": secret, "reason": secret}),
            ("context.fragment", {"scope": secret, "stage": secret, "load_status": secret,
                                  "token_estimate": 1_000_001, "activation_reason": secret, "skip_reason": secret}),
            ("tool.outcome", {"outcome": secret, "duration_ms": float("inf"), "no_result": "true", "error": secret}),
            ("rule.evaluated", {"verdict": secret, "reason": secret}),
            ("request.routed", {"unit": secret, "reason": secret}),
        ])
        snapshot = self.evidence(self.permit(run))
        self.assertNotIn(secret, canonical(snapshot))
        self.assertTrue(all(event["data"] == {} for event in snapshot["runs"][0]["events"]))

    def test_event_count_and_snapshot_bytes_caps_have_explicit_omission_gaps(self):
        runs = []
        for i in range(10):
            run = self.seed(version=f"bounded-{i}")
            self.events(run, [("context.fragment", {"scope": "task", "stage": "on_demand", "load_status": "loaded",
                                                     "token_estimate": 1_000_000}) for _ in range(105)])
            runs.append(run)
        permission = self.service.issue(principal=self.owner, agent_id="expert-a", recipient_actor_id="diagnostician",
                                        run_ids=[run.run_id for run in runs])
        snapshot = self.evidence(permission)
        self.assertLessEqual(len(canonical(snapshot).encode()), MAX_SNAPSHOT_BYTES)
        self.assertEqual(len(snapshot["runs"]), 10)
        for item in snapshot["runs"]:
            self.assertLessEqual(len(item["events"]), MAX_EVENTS_PER_RUN)
            self.assertTrue(item["gaps"]["truncated"])
            self.assertEqual(item["gaps"]["included_event_count"] + item["gaps"]["omitted_event_count"], 105)
            self.assertIn("event_limit", item["gaps"]["reasons"])
        self.assertIn("events_truncated", snapshot["limitations"])
        self.assertTrue(any("snapshot_budget" in item["gaps"]["reasons"] for item in snapshot["runs"]))

    def test_unknown_unconsumed_blind_and_self_declared_review_are_rejected(self):
        with self.assertRaises(PermissionError):
            self.permit(case_ids=["unknown-reviewed"])
        source = ORIGINAL_CASE_REGISTRY["c1_consult_success"]
        for replacement in (replace(source, blind_status="unconsumed"), replace(source, purpose="release_gate"),
                            replace(source, status="unreviewed")):
            self.service = DiagnosticsService(self.store, clock=lambda: self.now, case_registry={source.case_id: replacement})
            with self.subTest(source=replacement), self.assertRaises(PermissionError):
                self.permit(case_ids=[source.case_id])
        with self.assertRaises(TypeError):
            self.service.issue(principal=self.owner, agent_id="expert-a", recipient_actor_id="diagnostician",
                               run_ids=[], case_ids=[source.case_id], reviewed=True, blind=False)

    def test_registered_original_case_hash_and_id_rechecked_after_permission_and_snapshot(self):
        source = ORIGINAL_CASE_REGISTRY["c1_consult_success"]
        with self.subTest("builtin"):
            snapshot = self.evidence(self.permit(case_ids=[source.case_id]))
            self.assertEqual(snapshot["cases"][0]["source_hash"], source.content_hash)
            self.assertEqual(snapshot["cases"][0]["data"]["status"], "reviewed_original")
            self.assertNotIn("turns", canonical(snapshot))
        path = Path(self.temp.name) / "registered-case.json"
        path.write_bytes(Path(source.path).read_bytes())
        registry = {source.case_id: replace(source, path=path)}
        self.service = DiagnosticsService(self.store, clock=lambda: self.now, case_registry=registry)
        permission = self.permit(case_ids=[source.case_id])
        self.evidence(permission)
        path.write_text(canonical({"case_id": source.case_id, "reviewed": True, "blind": False, "turns": ["INJECTED"]}))
        with self.assertRaises(DiagnosticIntegrityError):
            self.evidence(permission)
        # Even a trusted hash registration cannot alias a different original ID.
        wrong_id = replace(source, path=path, content_hash=hashlib.sha256(path.read_bytes()).hexdigest(), case_id="different-id")
        self.service = DiagnosticsService(self.store, clock=lambda: self.now, case_registry={"different-id": wrong_id})
        with self.assertRaises(DiagnosticIntegrityError):
            self.permit(case_ids=["different-id"])

    def test_current_case_registry_state_cannot_be_bypassed_by_frozen_evidence_or_report(self):
        source = ORIGINAL_CASE_REGISTRY["c7_timeout_unknown"]
        permission = self.permit(case_ids=[source.case_id])
        snapshot = self.evidence(permission)
        self.assertEqual(snapshot["cases"][0]["data"]["tool_failure_mode"], "timeout_unknown")
        report = self.submit(permission, snapshot)
        self.service = DiagnosticsService(self.store, clock=lambda: self.now,
            case_registry={source.case_id: replace(source, blind_status="unconsumed")})
        for operation in (lambda: self.evidence(permission), lambda: self.submit(permission, snapshot),
                          lambda: self.service.read_report(principal=self.recipient, agent_id="expert-a",
                                                           report_id=report["report_id"])):
            with self.assertRaises(PermissionError):
                operation()

    def test_corrupt_event_or_frozen_snapshot_does_not_escape_integrity_boundary(self):
        run = self.seed()
        self.events(run, [("tool.outcome", {"outcome": "success"})])
        with self.store._tx() as cur:
            cur.execute("UPDATE events SET event_json='{}' WHERE run_id=?", (run.run_id,))
        permission = self.permit(run)
        snapshot = self.evidence(permission)
        self.assertEqual(snapshot["runs"][0]["events"], [])
        self.assertIn("invalid_events_omitted", snapshot["runs"][0]["gaps"]["reasons"])
        corrupted = deepcopy(snapshot)
        corrupted["runs"][0]["run_status"] = "forged"
        with self.store._tx() as cur:
            cur.execute("UPDATE diagnosis_snapshots SET snapshot_json=? WHERE snapshot_id=?",
                        (canonical(corrupted), snapshot["snapshot_id"]))
        with self.assertRaises(DiagnosticIntegrityError):
            self.evidence(permission)
        with self.assertRaises(DiagnosticIntegrityError):
            self.submit(permission, snapshot)


class TestDiagnosticReportsAndStorage(DiagnosticsCase):
    def test_reports_are_six_bounded_proposal_categories_with_exact_snapshot_local_references(self):
        permission = self.permit(self.seed())
        snapshot = self.evidence(permission)
        good = self.report(snapshot)
        self.assertEqual(REPORT_JSON_SCHEMA["properties"]["findings"]["maxItems"], 6)
        self.assertEqual(REPORT_JSON_SCHEMA["properties"]["status"]["const"], "proposal")
        self.assertEqual(REPORT_JSON_SCHEMA["properties"]["insufficient_categories"]["items"]["enum"],
                         list(REPORT_CATEGORIES))
        result = self.submit(permission, snapshot, good)
        self.assertEqual(self.service.read_report(principal=self.recipient, agent_id="expert-a", report_id=result["report_id"]), result)
        for category in REPORT_CATEGORIES:
            report = deepcopy(good)
            report["findings"][0]["category"] = category
            report["insufficient_categories"] = [item for item in REPORT_CATEGORIES if item != category]
            self.submit(permission, snapshot, report)
        mutations = []
        for key, value in (("status", "adopted"), ("config", {}), ("limitations", []),
                           ("insufficient_categories", []),
                           ("limitations", ["limited_sample"])):
            report = deepcopy(good)
            report[key] = value
            mutations.append(report)
        for key, value in (("evidence_ids", []), ("evidence_ids", ["ev_" + "f" * 24]),
                           ("evidence_ids", [good["findings"][0]["evidence_ids"][0]] * 2),
                           ("summary", "x" * 513), ("category", "change_truth"), ("patch", {})):
            report = deepcopy(good)
            report["findings"][0][key] = value
            mutations.append(report)
        report = deepcopy(good)
        report["findings"] *= 7
        mutations.append(report)
        report = deepcopy(good)
        report["insufficient_categories"].append("loading")
        mutations.append(report)
        report = deepcopy(good)
        report["insufficient_categories"].remove("tool")
        mutations.append(report)
        report = deepcopy(good)
        del report["insufficient_categories"]
        mutations.append(report)
        for report in mutations:
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.submit(permission, snapshot, report)
        other = self.evidence(self.permit(self.seed(version="other-snapshot")))
        stale = deepcopy(good)
        stale["findings"][0]["evidence_ids"] = [other["runs"][0]["evidence_id"]]
        with self.assertRaises(ValueError):
            self.submit(permission, snapshot, stale)
        with self.assertRaises(DiagnosticIntegrityError):
            self.service.submit_report(principal=self.recipient, agent_id="expert-a", permission_id=permission["permission_id"],
                snapshot_id=snapshot["snapshot_id"], input_hash="0" * 64, report=good)

    def test_utf8_report_size_is_bounded_even_when_character_lengths_are_valid(self):
        permission = self.permit(self.seed())
        snapshot = self.evidence(permission)
        report = self.report(snapshot)
        template = report["findings"][0]
        report["findings"] = [{**template, "category": category, "summary": "字" * 512, "recommendation": "字" * 512}
                               for category in REPORT_CATEGORIES]
        report["insufficient_categories"] = []
        self.assertGreater(len(canonical(report).encode()), MAX_REPORT_BYTES)
        with self.assertRaises(ValueError):
            self.submit(permission, snapshot, report)

    def test_diagnostic_workflow_performs_no_business_table_dml(self):
        run = self.seed()
        self.events(run, [("tool.outcome", {"outcome": "unknown", "duration_ms": 30})])
        writes = []
        def authorizer(action, table, column, database, trigger):
            if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
                writes.append(table)
                return sqlite3.SQLITE_OK if table.startswith("diagnosis_") else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        self.store._conn.set_authorizer(authorizer)
        try:
            permission = self.permit(run)
            snapshot = self.evidence(permission)
            self.evidence(permission)
            self.service.read_permission(principal=self.recipient, agent_id="expert-a", permission_id=permission["permission_id"])
            report = self.submit(permission, snapshot)
            self.service.read_report(principal=self.recipient, agent_id="expert-a", report_id=report["report_id"])
            self.service.revoke(principal=self.owner, agent_id="expert-a", permission_id=permission["permission_id"])
        finally:
            self.store._conn.set_authorizer(None)
        self.assertEqual(set(writes), {"diagnosis_permissions", "diagnosis_snapshots", "diagnosis_reports"})

    def test_report_and_worker_cas_share_transaction_and_rollback_on_cas_or_commit_failure(self):
        permission = self.permit(self.seed())
        snapshot = self.evidence(permission)
        def report_count():
            return self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0]
        cursor = self.store._conn.cursor()
        try:
            with self.assertRaisesRegex(RuntimeError, "同一存储事务"):
                self.service._submit_report_tx(cursor, principal=self.recipient, agent_id="expert-a",
                    permission_id=permission["permission_id"], snapshot_id=snapshot["snapshot_id"],
                    input_hash=snapshot["snapshot_hash"], report=self.report(snapshot))
        finally:
            cursor.close()
        # Simulates the trusted Worker integration: insert and CAS use one cursor.
        with self.assertRaisesRegex(RuntimeError, "lost worker CAS"):
            with self.store._tx() as cur:
                self.service._submit_report_tx(cur, principal=self.recipient, agent_id="expert-a",
                    permission_id=permission["permission_id"], snapshot_id=snapshot["snapshot_id"],
                    input_hash=snapshot["snapshot_hash"], report=self.report(snapshot))
                raise RuntimeError("lost worker CAS")
        self.assertEqual(report_count(), 0)
        def fail():
            raise RuntimeError("commit failure")
        self.store.before_commit = fail
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            self.submit(permission, snapshot)
        self.store.before_commit = None
        self.assertEqual(report_count(), 0)
        self.service.revoke(principal=self.owner, agent_id="expert-a", permission_id=permission["permission_id"])
        with self.assertRaises(PermissionError):
            self.submit(permission, snapshot)
        self.assertEqual(report_count(), 0)

    def test_permission_and_snapshot_insert_roll_back_when_commit_fails(self):
        run = self.seed()
        def fail():
            raise RuntimeError("commit failure")
        self.store.before_commit = fail
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            self.permit(run)
        self.store.before_commit = None
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_permissions").fetchone()[0], 0)
        permission = self.permit(run)
        self.store.before_commit = fail
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            self.evidence(permission)
        self.store.before_commit = None
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_snapshots").fetchone()[0], 0)
        self.assertEqual(self.evidence(permission)["purpose"], "diagnosis")

    def test_v20_migration_reopen_and_migration_failure_roll_back_governance_tables(self):
        run = self.seed()
        permission = self.permit(run)
        snapshot = self.evidence(permission)
        report = self.submit(permission, snapshot)
        self.store.close()
        self.store = SqliteStore(self.path)
        self.service = DiagnosticsService(self.store, clock=lambda: self.now)
        self.assertEqual(self.evidence(permission), snapshot)
        self.assertEqual(self.service.read_report(principal=self.recipient, agent_id="expert-a", report_id=report["report_id"]), report)
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))
        with self.store._tx() as cur:
            cur.execute("DROP TABLE diagnosis_reports")
            cur.execute("DROP TABLE diagnosis_snapshots")
            cur.execute("DROP TABLE diagnosis_permissions")
            cur.execute("UPDATE meta SET value='20' WHERE key='schema_version'")
        def fail():
            raise RuntimeError("migration failed")
        self.store.before_commit = fail
        with self.assertRaisesRegex(RuntimeError, "migration failed"):
            self.store.migrate()
        self.store.before_commit = None
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "20")
        self.assertIsNone(self.store._conn.execute("SELECT name FROM sqlite_master WHERE name='diagnosis_permissions'").fetchone())
        self.assertIsNotNone(self.store.run_row(run.run_id))
        self.store.migrate()
        self.assertEqual(self.store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))
        self.assertEqual(self.store._conn.execute("SELECT COUNT(*) FROM diagnosis_reports").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
