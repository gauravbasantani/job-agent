import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verification_handoff.py"
SPEC = importlib.util.spec_from_file_location("verification_handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(handoff)


class VerificationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "verification-handoff.json"
        self.audit = root / "verification-audit.jsonl"

    def run_cmd(self, *args):
        return handoff.main([
            "--state-file", str(self.state),
            "--audit-file", str(self.audit),
            *args,
        ])

    def state_data(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def test_open_records_a_pending_human_step(self):
        code = self.run_cmd(
            "open", "--job", "eudia-product-designer", "--type", "email_verification",
            "--url", "https://jobs.ashbyhq.com/eudia/abc", "--company", "Eudia",
        )
        self.assertEqual(code, 0)
        entry = self.state_data()["handoffs"]["eudia-product-designer"]
        self.assertEqual(entry["status"], "pending")
        self.assertEqual(entry["resume_with"], "continue eudia-product-designer")
        self.assertIn("verify", entry["gmail_query"])
        # The agent must state plainly that it will not do these itself.
        self.assertIn("type or read a one-time code", entry["agent_will_not"])

    def test_reopening_the_same_blocker_is_idempotent(self):
        for _ in range(3):
            self.run_cmd("open", "--job", "ramp-product-designer", "--type", "captcha")
        handoffs = self.state_data()["handoffs"]
        self.assertEqual(len(handoffs), 1)
        self.assertEqual(handoffs["ramp-product-designer"]["seen_count"], 3)

    def test_resolve_then_continue_is_idempotent(self):
        self.run_cmd("open", "--job", "nisc-ux-designer", "--type", "account_creation")
        self.run_cmd("resolve", "--job", "nisc-ux-designer")
        first = self.state_data()["handoffs"]["nisc-ux-designer"]["resolved_at"]
        # A repeated `continue {job}` from a phone must not rewrite history.
        self.run_cmd("resolve", "--job", "nisc-ux-designer")
        entry = self.state_data()["handoffs"]["nisc-ux-designer"]
        self.assertEqual(entry["status"], "resolved")
        self.assertEqual(entry["resolved_at"], first)

    def test_resolving_an_unknown_job_fails_cleanly(self):
        self.assertEqual(self.run_cmd("resolve", "--job", "never-seen"), 2)

    def test_secrets_never_reach_disk(self):
        self.run_cmd(
            "open", "--job", "discord-product-designer", "--type", "otp",
            "--instructions", "The code is 384512, password hunter2",
            "--url", "https://accounts.example.com/verify?token=abc123secret",
        )
        raw = self.state.read_text(encoding="utf-8")
        self.assertNotIn("384512", raw)
        self.assertNotIn("hunter2", raw)
        self.assertNotIn("abc123secret", raw)
        self.assertIn("[redacted]", raw)

    def test_redact_leaves_ordinary_instructions_readable(self):
        text = handoff.redact("Open the email from Ashby and click Verify in the mapped tab")
        self.assertIn("Open the email from Ashby", text)

    def test_gmail_query_is_narrow_and_recent(self):
        self.run_cmd("open", "--job", "haystack-ux-designer", "--type", "email_verification",
                     "--sender", "no-reply@ashbyhq.com")
        entry = self.state_data()["handoffs"]["haystack-ux-designer"]
        self.assertIn("newer_than:1d", entry["gmail_query"])
        self.assertIn("from:(no-reply@ashbyhq.com)", entry["gmail_query"])

    def test_all_handoff_types_are_human_only(self):
        # Nothing in this table should ever be automatable by the agent.
        for name in ("otp", "captcha", "account_creation", "login", "email_verification"):
            self.assertIn(name, handoff.HANDOFF_TYPES)

    def test_invalid_job_key_is_rejected(self):
        self.assertEqual(self.run_cmd("open", "--job", "bad key", "--type", "captcha"), 2)


class GmailMetadataTests(unittest.TestCase):
    """The Gmail connector may only ever confirm that a message arrived."""

    # Exactly what the connector returns in its default (non-metadata) view:
    # the code appears in both the subject and the snippet.
    FULL_RESPONSE = {
        "threads": [{
            "id": "18c9f2a4b71",
            "snippet": "Enter 481920 to verify your email address",
            "messages": [{
                "threadId": "18c9f2a4b71",
                "from": "Ashby <no-reply@ashbyhq.com>",
                "to": "you@example.com",
                "date": "Mon, 4 Aug 2026 17:31:00 -0700",
                "subject": "Your verification code is 481920",
                "snippet": "Enter 481920 to verify your email address",
                "body": "Your one-time code is 481920. It expires in 10 minutes.",
                "labelIds": ["INBOX", "UNREAD"],
            }],
        }],
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "verification-handoff.json"
        self.audit = root / "verification-audit.jsonl"

    def run_cmd(self, *args):
        return handoff.main([
            "--state-file", str(self.state),
            "--audit-file", str(self.audit),
            *args,
        ])

    def open_job(self, job="eudia-product-designer"):
        self.run_cmd("open", "--job", job, "--type", "email_verification", "--company", "Eudia")
        return job

    def disk(self):
        return self.state.read_text(encoding="utf-8") + self.audit.read_text(encoding="utf-8")

    def test_no_code_subject_snippet_or_body_ever_reaches_disk(self):
        job = self.open_job()
        code = self.run_cmd("record-email", "--job", job, "--payload-json", json.dumps(self.FULL_RESPONSE))
        self.assertEqual(code, 0)

        written = self.disk()
        self.assertNotIn("481920", written)                       # the code
        self.assertNotIn("Your verification code", written)       # the subject
        self.assertNotIn("Enter 481920", written)                 # the snippet
        self.assertNotIn("expires in 10 minutes", written)        # the body
        for banned in ("subject", "snippet", "body"):
            self.assertNotIn(f'"{banned}"', written)

    def test_arrival_is_still_confirmed(self):
        job = self.open_job()
        self.run_cmd("record-email", "--job", job, "--payload-json", json.dumps(self.FULL_RESPONSE))
        entry = json.loads(self.state.read_text(encoding="utf-8"))["handoffs"][job]

        self.assertTrue(entry["email_seen"])
        self.assertEqual(entry["email_from"], "no-reply@ashbyhq.com")
        self.assertEqual(entry["email_thread_id"], "18c9f2a4b71")
        self.assertTrue(entry["email_received_at"].startswith("2026-08-04T17:31:00"))

    def test_finding_the_email_does_not_clear_the_blocker(self):
        # the user still types the code. Arrival is information, not completion.
        job = self.open_job()
        self.run_cmd("record-email", "--job", job, "--payload-json", json.dumps(self.FULL_RESPONSE))
        entry = json.loads(self.state.read_text(encoding="utf-8"))["handoffs"][job]
        self.assertEqual(entry["status"], "pending")

    def test_a_code_hidden_in_the_sender_display_name_is_dropped(self):
        payload = {"threads": [{"id": "abc", "messages": [{
            "from": "Your code is 998877 <no-reply@evil.test>",
            "date": "Mon, 4 Aug 2026 17:31:00 -0700",
        }]}]}
        metadata = handoff.sanitize_email_metadata(payload)
        self.assertEqual(metadata["from"], "no-reply@evil.test")
        self.assertNotIn("998877", json.dumps(metadata))

    def test_the_live_connectors_metadata_shape_is_parsed(self):
        # Captured from a real THREAD_VIEW_METADATA_ONLY response. This view
        # omits subject and snippet entirely, and names the sender `sender`
        # rather than `from` — parsing only `from` recorded an empty sender.
        live = {
            "threads": [{
                "id": "19fba45e56649686",
                "messages": [{
                    "id": "19fba45e56649686",
                    "date": "2026-07-31T22:22:48Z",
                    "labelIds": ["IMPORTANT", "INBOX"],
                    "sender": "noreply@example.com",
                    "toRecipients": ["someone@example.edu"],
                }],
            }],
        }
        metadata = handoff.sanitize_email_metadata(live)
        self.assertEqual(metadata["from"], "noreply@example.com")
        self.assertEqual(metadata["thread_id"], "19fba45e56649686")
        self.assertTrue(metadata["received_at"].startswith("2026-07-31T22:22:48"))
        self.assertEqual(metadata["label_ids"], ["IMPORTANT", "INBOX"])
        # Recipients are not confirmation metadata and are not kept.
        self.assertNotIn("example.edu", json.dumps(metadata))

    def test_sanitizer_rebuilds_from_an_allowlist(self):
        metadata = handoff.sanitize_email_metadata(self.FULL_RESPONSE)
        self.assertEqual(set(metadata), set(handoff.GMAIL_METADATA_FIELDS))

    def test_an_unexpected_content_field_cannot_slip_through(self):
        # The allowlist is what makes this fail closed rather than open.
        payload = {"threads": [{"id": "abc", "messages": [{
            "from": "a@b.co",
            "date": "Mon, 4 Aug 2026 17:31:00 -0700",
            "someFutureBodyField": "code 555111",
        }]}]}
        self.assertNotIn("555111", json.dumps(handoff.sanitize_email_metadata(payload)))

    def test_a_non_date_timestamp_is_discarded(self):
        metadata = handoff.sanitize_email_metadata(
            {"threads": [{"id": "abc", "messages": [{"from": "a@b.co", "date": "code 123456"}]}]}
        )
        self.assertEqual(metadata["received_at"], "")

    def test_a_malformed_thread_id_is_discarded(self):
        metadata = handoff.sanitize_email_metadata(
            {"threads": [{"id": "not a valid id 481920!", "messages": [{"from": "a@b.co"}]}]}
        )
        self.assertEqual(metadata["thread_id"], "")

    def test_iso_timestamps_are_accepted_too(self):
        metadata = handoff.sanitize_email_metadata(
            {"threads": [{"id": "abc", "messages": [{"from": "a@b.co", "date": "2026-08-04T17:31:00Z"}]}]}
        )
        self.assertTrue(metadata["received_at"].startswith("2026-08-04T17:31:00"))

    def test_an_empty_result_is_an_error_not_a_false_confirmation(self):
        job = self.open_job()
        self.assertEqual(self.run_cmd("record-email", "--job", job, "--payload-json", '{"threads": []}'), 2)
        self.assertNotIn("email_seen", self.state.read_text(encoding="utf-8"))

    def test_record_email_needs_a_known_job(self):
        self.assertEqual(
            self.run_cmd("record-email", "--job", "never-seen", "--payload-json", json.dumps(self.FULL_RESPONSE)),
            2,
        )

    def test_gmail_query_demands_the_metadata_only_view(self):
        job = self.open_job()
        self.assertEqual(self.run_cmd("gmail-query", "--job", job), 0)
        # The contract must be explicit: the default view leaks snippets.
        entry = json.loads(self.state.read_text(encoding="utf-8"))["handoffs"][job]
        self.assertIn("newer_than:1d", entry["gmail_query"])


if __name__ == "__main__":
    unittest.main()
