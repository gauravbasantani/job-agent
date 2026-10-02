import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "command_queue.py"
SPEC = importlib.util.spec_from_file_location("command_queue", SCRIPT)
queue_mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(queue_mod)


class CommandQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.queue = root / "command-queue.json"
        self.audit = root / "command-audit.jsonl"

    def run_cmd(self, *args):
        return queue_mod.main([
            "--queue-file", str(self.queue),
            "--audit-file", str(self.audit),
            *args,
        ])

    def data(self):
        return json.loads(self.queue.read_text(encoding="utf-8"))

    def items(self):
        return self.data()["items"]

    def test_enqueue_stores_a_pending_command(self):
        self.assertEqual(self.run_cmd("enqueue", "apply https://jobs.lever.co/preql/abc"), 0)
        items = self.items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[0]["source"], "phone")
        # Queueing is never authorization to submit.
        self.assertIn("explicit confirmation", items[0]["note"])

    def test_repeated_send_of_the_same_command_enqueues_once(self):
        # A phone on a flaky connection retries; the queue must not fan out.
        for _ in range(4):
            self.run_cmd("enqueue", "apply https://jobs.lever.co/preql/abc")
        items = self.items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["duplicate_count"], 3)

    def test_whitespace_and_case_do_not_defeat_idempotency(self):
        self.run_cmd("enqueue", "Apply  https://EXAMPLE.com/job/1")
        self.run_cmd("enqueue", "apply https://example.com/job/1")
        self.assertEqual(len(self.items()), 1)

    def test_explicit_idempotency_key_wins(self):
        self.run_cmd("enqueue", "check https://a.test/1", "--idempotency-key", "phone-001")
        self.run_cmd("enqueue", "check https://b.test/2", "--idempotency-key", "phone-001")
        items = self.items()
        self.assertEqual(len(items), 1)
        # The original command is preserved; the retry does not overwrite it.
        self.assertIn("a.test", items[0]["command"])

    def test_different_commands_are_separate_items(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.run_cmd("enqueue", "apply https://a.test/1")
        self.assertEqual(len(self.items()), 2)

    def test_claim_takes_one_pending_item_at_a_time(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.run_cmd("enqueue", "check https://a.test/2")
        self.run_cmd("claim", "--worker", "mac-session")

        statuses = [item["status"] for item in self.items()]
        self.assertEqual(statuses.count("in_progress"), 1)
        self.assertEqual(statuses.count("pending"), 1)
        self.assertEqual(self.items()[0]["claimed_by"], "mac-session")

    def test_worker_label_is_saved_and_removed_from_command(self):
        self.run_cmd("enqueue", "check https://a.test/1 worker:codex")
        item = self.items()[0]
        self.assertEqual(item["command"], "check https://a.test/1")
        self.assertEqual(item["assigned_worker"], "codex")

    def test_claude_claim_skips_codex_work(self):
        self.run_cmd("enqueue", "check https://a.test/codex worker:codex")
        self.run_cmd("enqueue", "check https://a.test/claude")
        self.run_cmd("claim", "--worker", "claude-session", "--worker-type", "claude")

        items = self.items()
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[1]["status"], "in_progress")
        self.assertEqual(items[1]["claimed_by"], "claude-session")

    def test_codex_claim_takes_only_codex_work(self):
        self.run_cmd("enqueue", "check https://a.test/claude")
        self.run_cmd("enqueue", "check https://a.test/codex worker:codex")
        self.run_cmd("claim", "--worker", "codex-session", "--worker-type", "codex")

        items = self.items()
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[1]["status"], "in_progress")
        self.assertEqual(items[1]["claimed_by"], "codex-session")

    def test_legacy_colon_codex_suffix_routes_to_codex(self):
        self.run_cmd("enqueue", "find jobs and apply:codex")
        item = self.items()[0]
        self.assertEqual(item["command"], "find jobs and apply")
        self.assertEqual(item["assigned_worker"], "codex")

    def test_phone_autocorrect_after_worker_label_still_routes(self):
        self.run_cmd("enqueue", "find jobs on LinkedIn worker:codex's")
        item = self.items()[0]
        self.assertEqual(item["command"], "find jobs on LinkedIn")
        self.assertEqual(item["assigned_worker"], "codex")

    def test_legacy_mistyped_worker_suffix_is_cleaned_on_claim(self):
        queue = {"version": 1, "next_id": 2, "items": [{
            "id": 1,
            "command": "find jobs on LinkedIn worker:codex's",
            "assigned_worker": "",
            "status": "pending",
        }]}
        queue_mod.save_queue(self.queue, queue)

        self.run_cmd("claim", "--worker", "codex-session", "--worker-type", "codex")
        item = self.items()[0]
        self.assertEqual(item["status"], "in_progress")
        self.assertEqual(item["command"], "find jobs on LinkedIn")
        self.assertEqual(item["assigned_worker"], "codex")

    def test_enqueue_can_store_slack_notification_metadata(self):
        self.run_cmd(
            "enqueue", "check https://a.test/1",
            "--notify-team", "T1",
            "--notify-channel", "D1",
            "--notify-user", "U1",
            "--notify-thread-ts", "123.456",
        )
        notify = self.items()[0]["notify"]
        self.assertEqual(notify["type"], "slack")
        self.assertEqual(notify["team"], "T1")
        self.assertEqual(notify["channel"], "D1")
        self.assertEqual(notify["user"], "U1")
        self.assertEqual(notify["notified_status"], "")

    def test_terminal_slack_items_need_one_notification(self):
        notify = queue_mod.slack_notify_metadata(team="T1", channel="D1", user="U1")
        queue = {"version": 1, "next_id": 1, "items": []}
        result = queue_mod.enqueue(queue, "check https://a.test/1", "", "slack:U1", notify)
        item = result["item"]

        queue_mod.finish(queue, item["id"], "completed", "done")
        self.assertTrue(queue_mod.needs_notification(item))

        queue_mod.mark_notified(queue, item["id"], "completed")
        self.assertFalse(queue_mod.needs_notification(item))
        self.assertEqual(item["notify"]["notified_status"], "completed")

    def test_codex_terminal_item_waits_for_result_details_before_notification(self):
        notify = queue_mod.slack_notify_metadata(team="T1", channel="D1", user="U1")
        queue = {"version": 1, "next_id": 1, "items": []}
        result = queue_mod.enqueue(queue, "find jobs worker:codex", "", "slack:U1", notify)
        item = result["item"]

        queue_mod.claim(queue, "codex-session", "codex")
        queue_mod.finish(queue, item["id"], "completed", "short summary")
        self.assertFalse(queue_mod.needs_notification(item))

        queue_mod.attach_result(queue, item["id"], "full table result", renotify=True)
        self.assertTrue(queue_mod.needs_notification(item))
        self.assertEqual(item["result_details"], "full table result")

    def test_list_filters_by_assigned_worker(self):
        self.run_cmd("enqueue", "check https://a.test/claude")
        self.run_cmd("enqueue", "check https://a.test/codex worker:codex")
        self.assertEqual(self.run_cmd("list", "--status", "pending", "--assigned-worker", "codex"), 0)

    def test_claim_on_an_empty_queue_is_not_an_error(self):
        self.assertEqual(self.run_cmd("claim"), 0)

    def test_completing_twice_keeps_the_first_outcome(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.run_cmd("claim")
        self.run_cmd("complete", "--id", "1", "--result", "duplicate of prior application")
        first = self.items()[0]["finished_at"]

        self.run_cmd("fail", "--id", "1", "--result", "should not overwrite")
        item = self.items()[0]
        self.assertEqual(item["status"], "completed")
        self.assertEqual(item["finished_at"], first)
        self.assertIn("duplicate", item["result"])

    def test_release_returns_an_abandoned_claim_to_pending(self):
        self.run_cmd("enqueue", "apply https://a.test/1")
        self.run_cmd("claim")
        self.run_cmd("release", "--id", "1")
        item = self.items()[0]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["claimed_by"], "")

    def test_an_abandoned_claim_is_recovered(self):
        # A drain cycle killed mid-flight leaves the item claimed forever.
        # Without recovery it is never retried and looks like being ignored.
        self.run_cmd("enqueue", "apply https://a.test/1")
        self.run_cmd("claim")
        queue = queue_mod.load_queue(self.queue)
        queue["items"][0]["claimed_at"] = "2020-01-01T00:00:00+00:00"
        queue_mod.save_queue(self.queue, queue)

        self.assertEqual(self.run_cmd("release-stale", "--older-than-minutes", "30"), 0)
        item = self.items()[0]
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["claimed_by"], "")

    def test_a_fresh_claim_is_left_alone(self):
        self.run_cmd("enqueue", "apply https://a.test/1")
        self.run_cmd("claim")
        self.run_cmd("release-stale", "--older-than-minutes", "30")
        self.assertEqual(self.items()[0]["status"], "in_progress")

    def test_an_unparseable_claim_time_counts_as_stale(self):
        self.run_cmd("enqueue", "apply https://a.test/1")
        self.run_cmd("claim")
        queue = queue_mod.load_queue(self.queue)
        queue["items"][0]["claimed_at"] = ""
        queue_mod.save_queue(self.queue, queue)
        self.run_cmd("release-stale", "--older-than-minutes", "30")
        self.assertEqual(self.items()[0]["status"], "pending")


    def test_releasing_a_codex_claim_does_not_silence_the_item_forever(self):
        # result_details_expected belongs to the claim. If a codex claim is
        # released and re-claimed by claude, nobody attaches details, so the
        # item would sit terminal and never notify Slack at all.
        notify = queue_mod.slack_notify_metadata(team="T1", channel="D1", user="U1")
        queue = {"version": 1, "next_id": 1, "items": []}
        item = queue_mod.enqueue(queue, "find jobs worker:codex", "", "slack:U1", notify)["item"]

        queue_mod.claim(queue, "codex-session", "codex")
        self.assertTrue(item["result_details_expected"])

        queue_mod.release(queue, item["id"])
        self.assertFalse(item["result_details_expected"])

        queue_mod.finish(queue, item["id"], "completed", "done by claude instead")
        self.assertTrue(queue_mod.needs_notification(item))

    def test_release_stale_also_clears_the_expectation(self):
        notify = queue_mod.slack_notify_metadata(team="T1", channel="D1", user="U1")
        queue = {"version": 1, "next_id": 1, "items": []}
        item = queue_mod.enqueue(queue, "find jobs worker:codex", "", "slack:U1", notify)["item"]
        queue_mod.claim(queue, "codex-session", "codex")
        item["claimed_at"] = "2020-01-01T00:00:00+00:00"

        queue_mod.release_stale(queue, 30)
        self.assertFalse(item["result_details_expected"])

    def test_a_full_length_answer_survives_storage(self):
        # A scored job table plus tailoring notes runs past the old 6000 cap,
        # and the part the user needs most is written last.
        queue = {"version": 1, "next_id": 1, "items": []}
        item = queue_mod.enqueue(queue, "find jobs", "", "slack:U1", {})["item"]
        body = ("Scored job row.\n" * 900) + "STILL WAITING ON YOU: CAPTCHA on Eudia"
        self.assertGreater(len(body), 6000)

        queue_mod.attach_result(queue, item["id"], body)
        self.assertIn("STILL WAITING ON YOU", item["result_details"])

    def test_a_runaway_result_is_marked_not_silently_cut(self):
        queue = {"version": 1, "next_id": 1, "items": []}
        item = queue_mod.enqueue(queue, "find jobs", "", "slack:U1", {})["item"]
        queue_mod.attach_result(queue, item["id"], "z" * (queue_mod.RESULT_DETAILS_LIMIT + 500))
        self.assertIn("result truncated", item["result_details"])

    def test_attach_result_accepts_inline_text(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.assertEqual(
            self.run_cmd("attach-result", "--id", "1", "--result", "Initial ATS: 84% | Proceed"), 0
        )
        self.assertIn("Initial ATS: 84%", self.items()[0]["result_details"])

    def test_attach_result_needs_some_input(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.assertEqual(self.run_cmd("attach-result", "--id", "1"), 2)

    def test_finishing_an_unknown_id_fails_cleanly(self):
        self.assertEqual(self.run_cmd("complete", "--id", "99"), 2)

    def test_secrets_pasted_from_a_phone_are_scrubbed(self):
        self.run_cmd("enqueue", "continue eudia code: 481920 password hunter2")
        raw = self.queue.read_text(encoding="utf-8")
        self.assertNotIn("481920", raw)
        self.assertNotIn("hunter2", raw)
        self.assertIn("[redacted]", raw)

    def test_every_action_is_audited(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.run_cmd("claim")
        self.run_cmd("complete", "--id", "1")
        lines = [json.loads(line) for line in self.audit.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([line["action"] for line in lines], ["enqueue", "claim", "complete"])
        self.assertTrue(all(line["timestamp"] for line in lines))

    def test_empty_command_is_rejected(self):
        self.assertEqual(self.run_cmd("enqueue", "   "), 2)

    def test_list_filters_by_status(self):
        self.run_cmd("enqueue", "check https://a.test/1")
        self.run_cmd("enqueue", "check https://a.test/2")
        self.run_cmd("claim")
        self.assertEqual(self.run_cmd("list", "--status", "pending"), 0)


if __name__ == "__main__":
    unittest.main()
