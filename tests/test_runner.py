import sqlite3
import unittest

from pathscout.db import init_db
from pathscout.runner import run_sources


class RunnerTests(unittest.TestCase):
    def test_run_dedupes_repeated_manual_observations(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        config = {
            "profile": {"include_domains": ["robotics"], "exclude_domains": [], "exclude_ownership": []},
            "scoring": {
                "positive_role_terms": ["product lead"],
                "negative_role_terms": ["vp product"],
                "hidden_search_terms": ["series b"],
                "authority_terms": ["reports to ceo"],
                "remote_terms": [],
                "exception_location_terms": [],
                "travel_risk_terms": [],
            },
            "sources": [
                {
                    "id": "manual",
                    "type": "manual",
                    "name": "Manual",
                    "items": [
                        {
                            "company": "Test Robotics",
                            "title": "Product Lead",
                            "text": "Series B robotics role reports to CEO.",
                            "evidence_type": "job",
                        }
                    ],
                }
            ],
        }
        first = run_sources(conn, config)
        second = run_sources(conn, config)
        self.assertEqual(first.inserted_count, 1)
        self.assertEqual(second.skipped_count, 1)
        self.assertEqual(first.source_stats[0].fetched_count, 1)


if __name__ == "__main__":
    unittest.main()
