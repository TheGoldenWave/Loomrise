from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from loomrise.context import ContextLedger
from loomrise.contracts import ContextFragment, ContextScope, LoadStatus, SubjectScope


def fragment(fragment_id: str, **overrides) -> ContextFragment:
    values = {
        "fragment_id": fragment_id,
        "scope": ContextScope.GLOBAL,
        "title": fragment_id,
        "content": "授权资料内容",
        "source_ref": "fixture:source",
        "source_version": "v1",
    }
    values.update(overrides)
    return ContextFragment(**values)


class ContextValidityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = []
        self.ledger = ContextLedger(
            emit=lambda event_type, **payload: self.events.append((event_type, payload)),
            run_id="run-a", request_id="request-a",
        )

    def test_valid_timezone_and_no_expiry_can_load(self) -> None:
        self.ledger.register_many([
            fragment("no-expiry"),
            fragment("future", valid_until=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
        ])

        loaded = self.ledger.stage_baseline()

        self.assertEqual({item.fragment_id for item in loaded}, {"no-expiry", "future"})

    def test_invalid_or_timezone_free_expiry_fails_closed(self) -> None:
        self.ledger.register_many([
            fragment("date-only", valid_until="2030-01-01"),
            fragment("malformed", valid_until="not-a-timestamp"),
            fragment("non-rfc3339", valid_until="2030-1-1T00:00:00+00:00"),
            fragment("empty", valid_until=""),
        ])

        self.assertEqual(self.ledger.stage_baseline(), [])
        self.assertTrue(all(payload["load_status"] == str(LoadStatus.SKIPPED)
                            for _, payload in self.events))
        self.assertTrue(all("时区" in payload["skip_reason"] or "格式" in payload["skip_reason"]
                            for _, payload in self.events))

    def test_expired_and_revoked_fragments_do_not_load(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.ledger.register_many([
            fragment("expired", valid_until=past),
            fragment("revoked", revoked_at=past),
            fragment("not-yet-revoked", revoked_at=future),
            fragment("bad-revocation", revoked_at="2027-01-01T00:00:00"),
        ])

        loaded = self.ledger.stage_baseline()

        self.assertEqual([item.fragment_id for item in loaded], ["not-yet-revoked"])
        reasons = {payload["fragment_id"]: payload["skip_reason"] for _, payload in self.events}
        self.assertIn("已过期", reasons["expired"])
        self.assertIn("已撤销", reasons["revoked"])
        self.assertIn("撤销时间", reasons["bad-revocation"])

    def test_subject_bound_fragments_require_matching_id_and_scope(self) -> None:
        self.ledger.subject_id = "subject-2"
        self.ledger.subject_scope = SubjectScope.MAPPED
        self.ledger.register_many([
            fragment("other-subject", subject_id="subject-1", subject_scope="mapped"),
            fragment("matching-subject", subject_id="subject-2", subject_scope="mapped"),
            fragment("other-scope", subject_id="subject-2", subject_scope="ephemeral"),
            fragment("unscoped-business-source"),
        ])

        loaded = self.ledger.stage_baseline()

        self.assertEqual(
            {item.fragment_id for item in loaded},
            {"matching-subject", "unscoped-business-source"},
        )
        reasons = {payload["fragment_id"]: payload["skip_reason"] for _, payload in self.events}
        self.assertIn("主体 ID", reasons["other-subject"])
        self.assertIn("作用域", reasons["other-scope"])

    def test_subject_bound_fragments_do_not_load_without_request_identity(self) -> None:
        self.ledger.subject_scope = SubjectScope.EPHEMERAL
        self.ledger.register(fragment(
            "session-subject", subject_id="session-1", subject_scope=SubjectScope.EPHEMERAL,
        ))

        self.assertEqual(self.ledger.stage_baseline(), [])
        self.assertIn("主体 ID", self.events[0][1]["skip_reason"])

    def test_context_fragment_rejects_partial_subject_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "同时声明 subject_scope"):
            fragment("missing-scope", subject_id="subject-1")
        with self.assertRaisesRegex(ValueError, "必须提供 subject_id"):
            fragment("missing-id", subject_scope=SubjectScope.MAPPED)


if __name__ == "__main__":
    unittest.main()
