import unittest
from dataclasses import dataclass

from pathscout.config import build_runtime_config
from pathscout.scoring import score_item


@dataclass
class Item:
    company: str
    title: str
    text: str
    evidence_type: str


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = build_runtime_config()

    def test_hidden_search_note_does_not_become_act_now_from_role_context(self):
        item = Item(
            company="Example Robotics Co",
            title="Series B company scaling deployments without visible product lead",
            text="Series B robotics company with enterprise deployments and a likely need for commercialization and business-line ownership.",
            evidence_type="hidden_search",
        )
        result = score_item(item, self.config)
        self.assertEqual(result.tier, "Hidden Search Hypothesis")

    def test_explicit_product_lead_role_with_fit_is_act_now(self):
        item = Item(
            company="Example Robotics Co",
            title="Product Lead",
            text="AI robotics company. Leadership team role, remote with Denver travel.",
            evidence_type="job",
        )
        result = score_item(item, self.config)
        self.assertEqual(result.tier, "Act Now")

    def test_special_projects_is_not_high_priority(self):
        item = Item(
            company="Example Robotics Co",
            title="Special Projects Lead",
            text="Series B robotics company hiring for special projects.",
            evidence_type="job",
        )
        result = score_item(item, self.config)
        self.assertNotEqual(result.tier, "Act Now")

    def test_strong_watchlist_match_boosts_hidden_search(self):
        config = dict(self.config)
        config["watchlist"] = {
            "schema_version": 1,
            "companies": [
                {
                    "name": "Hidden Robotics",
                    "status": "strong",
                    "domains": ["robotics"],
                }
            ],
        }
        item = Item(
            company="Hidden Robotics",
            title="Scaling deployments after Series B",
            text="Series B robotics company scaling enterprise deployments and commercialization.",
            evidence_type="hidden_search",
        )
        result = score_item(item, config)
        self.assertEqual(result.tier, "Hidden Search Hypothesis")

    def test_short_role_terms_do_not_match_inside_words(self):
        item = Item(
            company="Program Robotics",
            title="Scaling program leadership",
            text="Series B robotics company with program leadership needs and commercialization work.",
            evidence_type="hidden_search",
        )
        result = score_item(item, self.config)
        self.assertFalse(any(" gm" in reason or reason.endswith("gm") for reason in result.reasons))

    def test_portfolio_relationship_is_scored_as_hidden_hypothesis(self):
        item = Item(
            company="Portfolio AI",
            title="Portfolio relationship: Portfolio AI",
            text="Portfolio relationship signal Series A AI marketplace hiring new GM role",
            evidence_type="portfolio",
        )
        result = score_item(item, self.config)
        self.assertEqual(result.tier, "Hidden Search Hypothesis")
        self.assertTrue(any("portfolio/company relationship" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
