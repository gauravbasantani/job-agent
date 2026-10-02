import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_tracker.py"
SPEC = importlib.util.spec_from_file_location("build_tracker", SCRIPT)
build_tracker = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(build_tracker)


class BuildTrackerTests(unittest.TestCase):
    def test_initial_score_falls_back_to_legacy_score(self):
        self.assertEqual(
            build_tracker.display_value({"ats_score": "86"}, "initial_ats_score"),
            "86",
        )

    def test_new_score_wins_over_legacy_score(self):
        self.assertEqual(
            build_tracker.display_value(
                {"ats_score": "86", "initial_ats_score": "84"},
                "initial_ats_score",
            ),
            "84",
        )


if __name__ == "__main__":
    unittest.main()
