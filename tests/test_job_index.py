import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "job_index.py"
SPEC = importlib.util.spec_from_file_location("job_index", SCRIPT)
job_index = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(job_index)


class JobIndexTests(unittest.TestCase):
    def test_canonicalize_url_removes_tracking(self):
        value = "https://www.linkedin.com/jobs/view/4449039598/?utm_source=x&ref=feed"
        self.assertEqual(
            job_index.canonicalize_url(value),
            "https://linkedin.com/jobs/view/4449039598",
        )

    def test_requisition_keys(self):
        self.assertEqual(
            job_index.requisition_key("https://job-boards.greenhouse.io/eudia/jobs/4323222009"),
            "greenhouse:eudia:4323222009",
        )
        self.assertEqual(
            job_index.requisition_key("https://jobs.ashbyhq.com/ramp/eca54d0e-232a"),
            "ashby:ramp:eca54d0e-232a",
        )

    def test_build_and_exact_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            applications = root / "applications"
            folder = applications / "2026-08-04-eudia-product-designer"
            folder.mkdir(parents=True)
            (folder / "application.md").write_text(
                """---
company: Eudia
title: Product Designer
link: https://job-boards.greenhouse.io/eudia/jobs/4323222009
ats_score: 86
status: Submitted
---

## Job Description
Design enterprise AI workflows and conduct usability research in Figma.
""",
                encoding="utf-8",
            )
            (folder / "resume-used.md").write_text("resume", encoding="utf-8")
            output = root / "index.json"
            payload = job_index.build_index(applications, output)
            result = job_index.lookup(
                payload,
                "https://job-boards.greenhouse.io/eudia/jobs/4323222009?utm_source=test",
                "",
                "",
                "",
                0.55,
                3,
            )
            self.assertEqual(result["match_type"], "exact")
            self.assertEqual(result["matches"][0]["initial_ats_score"], "86")
            self.assertTrue(result["matches"][0]["terminal"])
            self.assertTrue(output.is_file())
            json.loads(output.read_text(encoding="utf-8"))

    def test_similar_resume_candidate(self):
        entry = {
            "application": "applications/old/application.md",
            "folder": "applications/old",
            "company": "Acme",
            "title": "Product Designer",
            "company_words": job_index.normalized_words("Acme"),
            "title_words": job_index.normalized_words("Product Designer"),
            "jd_words": job_index.normalized_words(
                "enterprise product design usability research prototypes Figma"
            ),
            "status": "Submitted",
            "terminal": True,
            "has_resume": True,
            "urls": [],
            "requisition_keys": [],
        }
        result = job_index.lookup(
            {"entries": [entry]},
            "",
            "Acme",
            "Product Designer",
            "enterprise product design usability research prototypes in Figma",
            0.55,
            3,
        )
        self.assertEqual(result["match_type"], "similar")
        self.assertGreaterEqual(result["matches"][0]["similarity"], 0.55)


if __name__ == "__main__":
    unittest.main()
