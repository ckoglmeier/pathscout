import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pathscout.fetchers import fetch_portfolio, fetch_radar_portfolio, fetch_watchlist_careers
from pathscout.sources import career_candidates


class SourceTests(unittest.TestCase):
    def test_career_candidates_include_explicit_then_common_paths(self):
        candidates = career_candidates("https://example.com", ["https://jobs.example.com"])
        self.assertEqual(candidates[0], "https://jobs.example.com")
        self.assertIn("https://example.com/careers", candidates)
        self.assertIn("https://example.com/jobs", candidates)

    def test_career_candidates_accept_custom_paths(self):
        candidates = career_candidates("https://example.com", candidate_paths=["company/careers"])
        self.assertEqual(candidates, ["https://example.com/company/careers"])

    def test_watchlist_careers_fetch_skips_failures_and_returns_first_careers_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watchlist.json"
            path.write_text(
                json.dumps(
                    {
                        "companies": [
                            {
                                "name": "Test Robotics",
                                "status": "strong",
                                "urls": {"homepage": "https://example.com"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            def fake_get(url, timeout=8):
                if url.endswith("/careers"):
                    return "<html><title>Careers</title><body>Careers open roles Chief Product Officer product commercial</body></html>"
                raise RuntimeError("not found")

            with patch("pathscout.fetchers.http_get", side_effect=fake_get):
                items = fetch_watchlist_careers(
                    {
                        "id": "careers",
                        "name": "Careers",
                        "type": "watchlist_careers",
                        "path": str(path),
                    }
                )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].company, "Test Robotics")
        self.assertEqual(items[0].evidence_type, "job")

    def test_watchlist_careers_timeout_on_one_company_does_not_abort_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watchlist.json"
            path.write_text(
                json.dumps(
                    {
                        "companies": [
                            {
                                "name": "Slow Robotics",
                                "status": "strong",
                                "urls": {"homepage": "https://slow.example.com"},
                            },
                            {
                                "name": "Fast Robotics",
                                "status": "strong",
                                "urls": {"homepage": "https://fast.example.com"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            def fake_get(url, timeout=8):
                if "slow" in url:
                    raise TimeoutError("timed out")
                return "<html><title>Careers</title><body>Careers open positions General Manager product commercial</body></html>"

            with patch("pathscout.fetchers.http_get", side_effect=fake_get):
                items = fetch_watchlist_careers(
                    {
                        "id": "careers",
                        "name": "Careers",
                        "type": "watchlist_careers",
                        "path": str(path),
                    }
                )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].company, "Fast Robotics")

    def test_watchlist_careers_extracts_multiple_role_titles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watchlist.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "companies": [
                            {
                                "name": "Role Robotics",
                                "status": "strong",
                                "urls": {"homepage": "https://roles.example.com"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            def fake_get(url, timeout=8):
                return """
                <html>
                  <title>Careers</title>
                  <body>
                    <h1>Careers</h1>
                    <p>Open roles</p>
                    <a href="/jobs/1">Product Lead</a>
                    <a href="/jobs/2">Strategy and Operations Manager</a>
                    <a href="/jobs/3">Privacy Policy</a>
                  </body>
                </html>
                """

            with patch("pathscout.fetchers.http_get", side_effect=fake_get):
                items = fetch_watchlist_careers(
                    {
                        "id": "careers",
                        "name": "Careers",
                        "type": "watchlist_careers",
                        "config": {"path": str(path)},
                    }
                )

        self.assertEqual([item.title for item in items], ["Product Lead", "Strategy and Operations Manager"])
        self.assertTrue(all(item.evidence_type == "job" for item in items))

    def test_portfolio_source_returns_relationship_companies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "companies": [
                            {
                                "name": "Portfolio AI",
                                "status": "invested",
                                "stage": "Series A",
                                "domains": ["AI", "marketplace"],
                                "relationship": "Investor",
                                "urls": {"homepage": "https://portfolio.example.com"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            items = fetch_portfolio(
                {
                    "id": "portfolio",
                    "name": "Portfolio",
                    "type": "portfolio",
                    "config": {"path": str(path)},
                }
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "portfolio")
        self.assertEqual(items[0].evidence_type, "portfolio")

    def test_radar_portfolio_alias_still_returns_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "companies": [
                            {
                                "name": "Portfolio AI",
                                "status": "invested",
                                "stage": "Series A",
                                "domains": ["AI", "marketplace"],
                                "relationship": "Investor",
                                "urls": {"homepage": "https://portfolio.example.com"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            items = fetch_radar_portfolio(
                {
                    "id": "legacy",
                    "name": "Legacy Portfolio",
                    "type": "radar_portfolio",
                    "config": {"path": str(path)},
                }
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "radar_portfolio")
        self.assertEqual(items[0].evidence_type, "radar_portfolio")


if __name__ == "__main__":
    unittest.main()
