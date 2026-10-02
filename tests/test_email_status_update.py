"""Tests for scripts/email_status_update.py.

The regression that matters most is the first one: "we have decided to move
forward with other candidates" is a REJECTION, and an earlier version of the
classifier read it as an interview invite because both contain "move forward".
That bug would have written the wrong outcome into the tracker.
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import email_status_update as esu  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_move_forward_with_other_candidates_is_a_rejection(self):
        text = ("Thank you for your interest. After careful review, we have "
                "decided to move forward with other candidates for this role.")
        self.assertEqual(esu.classify(text), "rejected")

    def test_move_forward_alone_is_an_interview(self):
        self.assertEqual(
            esu.classify("We'd like to move forward with the next stage."),
            "interview")

    def test_plain_rejections(self):
        for text in [
            "Unfortunately we will not be moving forward with your application.",
            "You were not selected for this position.",
            "The position has been filled.",
            "We will keep your resume on file.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(esu.classify(text), "rejected")

    def test_interview_invites(self):
        for text in [
            "Can we set up some time this week?",
            "We would love to chat about the role.",
            "Let's schedule a call with the hiring manager.",
            "We'd like to invite you to interview.",
        ]:
            with self.subTest(text=text):
                self.assertEqual(esu.classify(text), "interview")

    def test_assessment(self):
        self.assertEqual(esu.classify("Please complete the take-home design exercise."),
                         "assessment")

    def test_offer_beats_everything(self):
        text = ("We are pleased to offer you the role. We will schedule a call "
                "to walk through the details.")
        self.assertEqual(esu.classify(text), "offer")

    def test_acknowledgement_is_not_a_state_change(self):
        self.assertEqual(esu.classify("Thank you for applying to Acme."), "acknowledged")
        self.assertIsNone(esu.STATUS_FOR["acknowledged"])

    def test_unknown_returns_none(self):
        self.assertIsNone(esu.classify("Here is the parking information for Tuesday."))


class TestSplit(unittest.TestCase):
    def test_splits_on_dashes_and_from_headers(self):
        blob = "From: a@x.com\nSubject: one\nbody\n---\nFrom: b@y.com\nSubject: two\nbody"
        self.assertEqual(len(esu.split_messages(blob)), 2)

    def test_single_message_stays_whole(self):
        self.assertEqual(len(esu.split_messages("Subject: only\nbody text")), 1)


class TestSubject(unittest.TestCase):
    def test_reads_subject_header(self):
        self.assertEqual(esu.subject_of("From: a@b.c\nSubject: Your application\nbody"),
                         "Your application")

    def test_falls_back_to_first_line(self):
        self.assertEqual(esu.subject_of("no headers here\nsecond line"), "no headers here")


class TestNoDowngrade(unittest.TestCase):
    def test_terminal_statuses_outrank_rejection(self):
        self.assertGreater(esu.RANK["Offer"], esu.RANK["Rejected"])
        self.assertGreater(esu.RANK["Interviewing"], esu.RANK["Rejected"])
        for s in ("Rejected", "Offer", "Interviewing", "Assessment requested"):
            self.assertIn(s, esu.TERMINAL)


class TestMatching(unittest.TestCase):
    """Company matching must respect word boundaries.

    'Fort' inside 'effort' and 'sable' inside 'reusable' have both produced
    false positives in this repo before.
    """
    APPS = [(pathlib.Path("/tmp/x/application.md"), "Fort", "Founding Designer", "Applied")]

    def test_substring_does_not_match(self):
        self.assertEqual(esu.find_matches("it took real effort to apply", self.APPS, None), [])

    def test_whole_word_matches(self):
        self.assertEqual(len(esu.find_matches("Your application to Fort", self.APPS, None)), 1)


if __name__ == "__main__":
    unittest.main()
