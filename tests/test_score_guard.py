import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_guard.py"
SPEC = importlib.util.spec_from_file_location("score_guard", SCRIPT)
score_guard = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(score_guard)


def scores(**overrides):
    base = {
        "role_title_alignment": 17,
        "must_have_skills": 20,
        "evidence_strength": 17,
        "seniority": 7,
        "domain_product_relevance": 8,
        "location_work_comp_authorization": 8,
        "application_feasibility_freshness": 4,
    }
    base.update(overrides)
    return base


class ScoreGuardTests(unittest.TestCase):
    def test_valid_tailoring_delta(self):
        result = score_guard.validate(
            {
                "initial": scores(),
                "tailored": scores(
                    role_title_alignment=19,
                    must_have_skills=23,
                    evidence_strength=18,
                ),
                "changes": [
                    {"dimension": "role_title_alignment", "resume_line": "headline", "reason": "honest title"},
                    {"dimension": "must_have_skills", "resume_line": "skills", "reason": "supported terms"},
                    {"dimension": "evidence_strength", "resume_line": "first bullet", "reason": "stronger proof"},
                ],
            }
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["score_delta"], 6)

    def test_locked_dimension_cannot_increase(self):
        result = score_guard.validate(
            {
                "initial": scores(),
                "tailored": scores(seniority=9),
                "changes": [],
            }
        )
        self.assertFalse(result["valid"])
        self.assertIn("locked dimension changed: seniority", result["errors"][0])

    def test_undocumented_increase_is_rejected(self):
        result = score_guard.validate(
            {
                "initial": scores(),
                "tailored": scores(must_have_skills=22),
                "changes": [],
            }
        )
        self.assertFalse(result["valid"])
        self.assertIn("lacks a changed resume_line", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
