import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "job_command.py"
SPEC = importlib.util.spec_from_file_location("job_command", SCRIPT)
job_command = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(job_command)


class JobCommandTests(unittest.TestCase):
    def test_structured_direct_search(self):
        parsed = job_command.parse_command(
            'find job_title:"Product Designer" jobboard:"Workday,Greenhouse" '
            'company_page:true not_on_linkedin:true'
        )
        self.assertEqual(parsed["intent"], "find")
        self.assertEqual(parsed["job_title"], "Product Designer")
        self.assertEqual(parsed["jobboards"], ["workday", "greenhouse"])
        self.assertTrue(parsed["company_page"])
        self.assertTrue(parsed["not_on_linkedin"])

    def test_empty_board_means_all_direct_sources(self):
        parsed = job_command.parse_command('find job_title:"UX Designer" jobboard:""')
        self.assertIn("workday", parsed["jobboards"])
        self.assertIn("icims", parsed["jobboards"])
        self.assertNotIn("linkedin", parsed["jobboards"])

    def test_force_tailor_and_url(self):
        parsed = job_command.parse_command(
            "force tailor https://example.com/jobs/123?source=linkedin"
        )
        self.assertEqual(parsed["intent"], "force_tailor")
        self.assertEqual(parsed["url"], "https://example.com/jobs/123?source=linkedin")

    def test_every_supported_command_is_recognized(self):
        cases = {
            "check https://a.test/1": "check",
            "apply https://a.test/1": "apply",
            "force tailor https://a.test/1": "force_tailor",
            "continue eudia-product-designer": "continue",
            "submit eudia-product-designer": "submit",
            'find job_title:"Product Designer"': "find",
        }
        for text, intent in cases.items():
            self.assertEqual(job_command.parse_command(text)["intent"], intent, text)

    def test_continue_and_submit_extract_the_job_key(self):
        self.assertEqual(
            job_command.parse_command("continue eudia-product-designer")["job_key"],
            "eudia-product-designer",
        )
        self.assertEqual(
            job_command.parse_command("submit eudia-product-designer")["job_key"],
            "eudia-product-designer",
        )

    def test_a_spoken_job_reference_slugifies_to_the_same_key(self):
        # The tab map, application folder and tracker all key off this slug, so
        # "submit Eudia Product Designer" must resolve like the slug form.
        parsed = job_command.parse_command("submit the Eudia Product Designer application")
        self.assertEqual(parsed["job_key"], "eudia-product-designer")

    def test_job_key_is_empty_for_url_commands(self):
        parsed = job_command.parse_command("apply https://jobs.lever.co/preql/abc")
        self.assertEqual(parsed["job_key"], "")

    def test_not_on_linkedin_in_natural_language(self):
        parsed = job_command.parse_command("find Product Designer roles not on LinkedIn")
        self.assertTrue(parsed["not_on_linkedin"])
        self.assertNotIn("linkedin", parsed["jobboards"])

    def test_search_queries_cover_requested_boards(self):
        parsed = job_command.parse_command(
            'find job_title:"Product Designer" jobboard:"workday"'
        )
        queries = job_command.search_queries(parsed)
        self.assertIn('"Product Designer" site:myworkdayjobs.com', queries)

    def test_unknown_board_is_reported_not_silently_dropped(self):
        parsed = job_command.parse_command('find job_title:"UX" jobboard:"Taleo"')
        self.assertEqual(parsed["unknown_jobboards"], ["Taleo"])


if __name__ == "__main__":
    unittest.main()
