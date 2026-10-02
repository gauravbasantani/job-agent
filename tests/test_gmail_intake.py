import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gmail_intake.py"
SPEC = importlib.util.spec_from_file_location("gmail_intake", SCRIPT)
intake = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(intake)

ME = "you@example.com"


def thread(message_id, sender, subject, body="ignored entirely"):
    return {
        "id": message_id,
        "messages": [{
            "id": message_id,
            "sender": sender,
            "subject": subject,
            "snippet": body,
            "body": body,
            "date": "2026-08-04T18:00:00Z",
        }],
    }


class GmailIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.queue = root / "command-queue.json"
        self.audit = root / "command-audit.jsonl"

    def run_intake(self, *threads, allow=(ME,)):
        return intake.intake(
            {"threads": list(threads)}, {a.lower() for a in allow}, self.queue, self.audit
        )

    def items(self):
        return json.loads(self.queue.read_text(encoding="utf-8"))["items"]

    def test_a_command_you_emailed_yourself_is_queued(self):
        result = self.run_intake(
            thread("m1", ME, "JOBAGENT: apply https://job-boards.greenhouse.io/acme/jobs/1")
        )
        self.assertEqual(len(result["enqueued"]), 1)
        item = self.items()[0]
        self.assertEqual(item["command"], "apply https://job-boards.greenhouse.io/acme/jobs/1")
        self.assertEqual(item["source"], "gmail")
        self.assertEqual(item["status"], "pending")

    def test_mail_from_anyone_else_is_ignored(self):
        # Anyone can email you; only you get to queue work on your machine.
        result = self.run_intake(thread("m1", "recruiter@spam.test", "JOBAGENT: apply https://evil.test/x"))
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(result["rejected"][0]["reason"], "sender not allowed")
        self.assertFalse(self.queue.exists() and self.items())

    def test_a_body_command_without_the_subject_gate_is_ignored(self):
        # The subject prefix is the gate. A forwarded message whose body
        # happens to contain a command cannot trigger anything.
        result = self.run_intake(
            thread("m1", ME, "Fwd: your application update",
                   body="submit acme-product-designer")
        )
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(result["rejected"][0]["reason"], "subject is not a JOBAGENT command")

    def test_the_body_supplies_the_command_when_the_subject_is_a_marker(self):
        # This is the real message that failed: subject carried only a token,
        # the actual instruction was in the body.
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME, "subject": "Jobagent: find apply",
             "body": "find Product Designer jobs from the past 24 hours and apply"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command_source"], "body")
        self.assertIn("past 24 hours", parsed["command"])

    def test_an_email_signature_is_stripped_from_the_command(self):
        # Gmail's snippet flattens the message, so the signature runs straight
        # into the instruction on one line.
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME, "subject": "JOBAGENT:",
             "snippet": "find Product Designer jobs and apply Best, the user "
                        "Portfolio | LinkedIn | GitHub (555) 123-4567"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command"], "find Product Designer jobs and apply")

    def test_quoted_reply_lines_are_skipped(self):
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME, "subject": "JOBAGENT:",
             "body": "> submit some-other-job\ncheck https://a.test/1"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command"], "check https://a.test/1")

    def test_the_subject_still_works_on_its_own(self):
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME, "subject": "JOBAGENT: apply https://a.test/1",
             "body": "Best, the user"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command_source"], "subject")
        self.assertEqual(parsed["command"], "apply https://a.test/1")

    def test_an_unsupported_verb_is_rejected_not_guessed(self):
        result = self.run_intake(thread("m1", ME, "JOBAGENT: delete everything"))
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(result["rejected"][0]["reason"], "unsupported command verb")

    def test_every_supported_verb_is_accepted(self):
        for index, command in enumerate([
            "check https://a.test/1",
            "apply https://a.test/1",
            "force tailor https://a.test/1",
            "continue acme-product-designer",
            "submit acme-product-designer",
            'find job_title:"Product Designer"',
        ]):
            parsed = intake.parse_message(
                {"id": f"m{index}", "sender": ME, "subject": f"JOBAGENT: {command}"}, {ME}
            )
            self.assertTrue(parsed["accepted"], command)
            self.assertEqual(parsed["command"], command)

    def test_polling_the_same_inbox_window_does_not_double_queue(self):
        # Overlapping polls are normal; the Gmail message id keeps them safe.
        message = thread("m1", ME, "JOBAGENT: apply https://a.test/1")
        first = self.run_intake(message)
        second = self.run_intake(message)
        third = self.run_intake(message)

        self.assertEqual(len(first["enqueued"]), 1)
        self.assertEqual(len(second["already_queued"]), 1)
        self.assertEqual(len(third["already_queued"]), 1)
        self.assertEqual(len(self.items()), 1)

    def test_two_different_commands_both_queue(self):
        result = self.run_intake(
            thread("m1", ME, "JOBAGENT: apply https://a.test/1"),
            thread("m2", ME, "JOBAGENT: check https://a.test/2"),
        )
        self.assertEqual(len(result["enqueued"]), 2)
        self.assertEqual(len(self.items()), 2)

    def test_a_pasted_subject_label_is_tolerated(self):
        # Real message: the runbook example is written as a mail header, so
        # "Subject:" got copied into the subject field along with the command.
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME,
             "subject": "Subject: JOBAGENT: apply https://a.test/1"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command"], "apply https://a.test/1")

    def test_reply_and_forward_prefixes_still_parse(self):
        parsed = intake.parse_message(
            {"id": "m1", "sender": ME, "subject": "Re: JOBAGENT: check https://a.test/1"}, {ME}
        )
        self.assertTrue(parsed["accepted"])
        self.assertEqual(parsed["command"], "check https://a.test/1")

    def test_sender_with_a_display_name_is_matched_on_address(self):
        parsed = intake.parse_message(
            {"id": "m1", "sender": f"Your Name <{ME}>", "subject": "JOBAGENT: check https://a.test/1"},
            {ME},
        )
        self.assertTrue(parsed["accepted"])

    def test_a_message_without_an_id_is_rejected(self):
        # No id means no idempotency key, which means it could queue forever.
        parsed = intake.parse_message({"sender": ME, "subject": "JOBAGENT: check https://a.test/1"}, {ME})
        self.assertFalse(parsed["accepted"])

    def test_queued_submit_carries_the_confirmation_note(self):
        self.run_intake(thread("m1", ME, "JOBAGENT: submit acme-product-designer"))
        self.assertIn("explicit confirmation", self.items()[0]["note"])

    def test_the_query_is_subject_scoped(self):
        query = intake.gmail_query()
        self.assertIn("subject:(JOBAGENT)", query)
        self.assertIn("newer_than:", query)


if __name__ == "__main__":
    unittest.main()
