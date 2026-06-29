import json
import os
import sqlite3
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pathscout.artifacts import build_artifact, normalize_finding, render_markdown
from pathscout.cli import main
from pathscout.config import build_runtime_config, ensure_default_files, load_profile
from pathscout.db import init_db
from pathscout.doctor import validate_setup
from pathscout.runner import run_sources


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def profile_config() -> dict:
    return {
        "schema_version": 1,
        "target_name": "Startup role seeker",
        "target_roles": ["product lead", "general manager"],
        "stage_focus": ["Series B"],
        "include_domains": ["robotics"],
        "exclude_domains": [],
        "exclude_ownership": [],
        "preferred_locations": ["Remote"],
        "exception_locations": [],
        "travel_limit": "Low",
        "authority_requirements": ["reports to CEO"],
        "scoring": {
            "act_now_threshold": 70,
            "hidden_search_threshold": 50,
            "watch_threshold": 20,
            "positive_role_terms": ["product lead", "general manager"],
            "negative_role_terms": ["vp product"],
            "hidden_search_terms": ["series b"],
            "authority_terms": ["reports to ceo"],
            "remote_terms": ["remote"],
            "exception_location_terms": [],
            "travel_risk_terms": [],
        },
    }


def sources_config() -> dict:
    return {
        "schema_version": 1,
        "sources": [
            {
                "id": "manual",
                "type": "manual",
                "name": "Manual",
                "enabled": True,
                "config": {
                    "items": [
                        {
                            "company": "Test Robotics",
                            "title": "Chief Product Officer",
                            "text": "Series B robotics role reports to CEO.",
                            "evidence_type": "job",
                        }
                    ]
                },
            }
        ],
    }


def watchlist_config() -> dict:
    return {
        "schema_version": 1,
        "companies": [
            {
                "name": "Test Robotics",
                "status": "strong",
                "domains": ["robotics"],
                "urls": {"homepage": "https://example.com"},
            }
        ],
    }


class ConfigArtifactTests(unittest.TestCase):
    def test_init_creates_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                self.assertEqual(main(["init", "--no-input"]), 0)
                for path in [
                    "config/profile.json",
                    "config/background.json",
                    "config/sources.json",
                    "config/watchlist.json",
                    "config/suppressions.json",
                    "config/portfolio.json",
                ]:
                    self.assertTrue(Path(path).exists(), path)
            finally:
                os.chdir(cwd)

    def test_init_stores_onboarding_answers_in_order(self):
        prompts = []

        def fake_input(prompt):
            prompts.append(prompt)
            if "environment" in prompt:
                return "Remote AI startups"
            return "Founding Product Lead"

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=fake_input):
                    self.assertEqual(main(["init"]), 0)
                profile = json.loads(Path("config/profile.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(cwd)

        self.assertEqual(
            prompts,
            [
                "What is the right environment for you? ",
                "What is the right role for you? ",
            ],
        )
        self.assertEqual(profile["environment_preferences"], ["Remote AI startups"])
        self.assertEqual(profile["role_preferences"], ["Founding Product Lead"])
        self.assertEqual(profile["target_roles"][0], "Founding Product Lead")

    def test_init_accepts_non_interactive_onboarding_answers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                self.assertEqual(
                    main(
                        [
                            "init",
                            "--environment",
                            "Seed-stage marketplaces",
                            "--role",
                            "Growth Lead",
                        ]
                    ),
                    0,
                )
                profile = json.loads(Path("config/profile.json").read_text(encoding="utf-8"))
            finally:
                os.chdir(cwd)

        self.assertEqual(profile["environment_preferences"], ["Seed-stage marketplaces"])
        self.assertEqual(profile["role_preferences"], ["Growth Lead"])

    def test_standalone_profile_is_preferred_over_legacy_embedded_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profile_path = root / "profile.json"
            sources_path = root / "sources.json"
            write_json(profile_path, profile_config())
            legacy = sources_config()
            legacy["profile"] = {"target_name": "Legacy"}
            write_json(sources_path, legacy)
            profile = load_profile(profile_path, legacy)
        self.assertEqual(profile["target_name"], "Startup role seeker")

    def test_legacy_embedded_profile_still_loads_with_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources_path = root / "sources.json"
            watchlist_path = root / "watchlist.json"
            suppressions_path = root / "suppressions.json"
            legacy = sources_config()
            legacy.pop("schema_version")
            legacy["profile"] = profile_config()
            write_json(sources_path, legacy)
            write_json(watchlist_path, watchlist_config())
            write_json(suppressions_path, {"schema_version": 1, "suppressions": []})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", DeprecationWarning)
                config = build_runtime_config(sources_path, root / "missing-profile.json", watchlist_path, suppressions_path)
        self.assertEqual(config["profile"]["target_name"], "Startup role seeker")
        self.assertTrue(any("deprecated" in str(warning.message) for warning in caught))

    def test_doctor_flags_missing_schema_and_duplicate_source_ids(self):
        config = sources_config()
        config.pop("schema_version")
        config["profile"] = profile_config()
        config["watchlist"] = watchlist_config()
        config["suppressions"] = {"schema_version": 1, "suppressions": []}
        config["_legacy_sources"] = True
        config["sources"].append(dict(config["sources"][0]))
        warnings_found, errors = validate_setup(config, Path("config/watchlist.json"), sources_path=Path("config/sources.json"))
        self.assertTrue(any("duplicate source id" in error for error in errors))
        self.assertTrue(any("legacy config shape" in warning for warning in warnings_found))

    def test_suppressed_findings_appear_in_json_and_group_in_markdown(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        config = {
            **sources_config(),
            "profile": profile_config(),
            "scoring": profile_config()["scoring"],
            "watchlist": watchlist_config(),
            "suppressions": {"schema_version": 1, "suppressions": []},
        }
        result = run_sources(conn, config)
        artifact = build_artifact(conn, config, result, 7, False, {"command": "run", "digest_window_days": 7})
        finding_id = artifact["findings"][0]["id"]
        config["suppressions"] = {
            "schema_version": 1,
            "suppressions": [{"id": finding_id, "scope": "finding", "reason": "Not a fit", "created_at": "2026-01-01"}],
        }
        artifact = build_artifact(conn, config, result, 7, False, {"command": "run", "digest_window_days": 7})
        markdown = render_markdown(artifact)
        self.assertTrue(artifact["findings"][0]["suppressed"])
        self.assertIn("## Suppressed", markdown)
        self.assertNotIn("### Chief Product Officer", markdown)

    def test_cli_format_options_write_expected_artifacts(self):
        for output_format, expected_json, expected_md in [
            ("json", True, False),
            ("markdown", False, True),
            ("both", True, True),
        ]:
            with self.subTest(output_format=output_format), tempfile.TemporaryDirectory() as tmpdir:
                cwd = os.getcwd()
                os.chdir(tmpdir)
                try:
                    write_json(Path("config/profile.json"), profile_config())
                    write_json(Path("config/sources.json"), sources_config())
                    write_json(Path("config/watchlist.json"), watchlist_config())
                    write_json(Path("config/suppressions.json"), {"schema_version": 1, "suppressions": []})
                    rc = main(["run", "--dry-run", "--format", output_format])
                    self.assertEqual(rc, 0)
                    self.assertEqual(Path("outputs/latest.json").exists(), expected_json)
                    self.assertEqual(Path("outputs/latest.md").exists(), expected_md)
                finally:
                    os.chdir(cwd)

    def test_review_prints_findings_from_json_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "latest.json"
            write_json(
                artifact_path,
                {
                    "schema_version": 1,
                    "findings": [
                        {
                            "id": "abcdef123456",
                            "tier": "Act Now",
                            "score": 90,
                            "company": "Test Robotics",
                            "title": "Product Lead",
                            "url": "https://example.com/job",
                            "suppressed": False,
                        }
                    ],
                },
            )
            output = StringIO()
            with redirect_stdout(output):
                rc = main(["review", "--json", str(artifact_path)])
        self.assertEqual(rc, 0)
        self.assertIn("abcdef123456", output.getvalue())
        self.assertIn("Product Lead", output.getvalue())

    def test_explain_prints_finding_evidence_and_related_notes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_path = root / "latest.json"
            notes_path = root / "notes.json"
            write_json(
                artifact_path,
                {
                    "schema_version": 1,
                    "findings": [
                        {
                            "id": "abcdef123456",
                            "content_hash": "abcdef123456",
                            "tier": "Act Now",
                            "score": 90,
                            "company": "Test Robotics",
                            "title": "Product Lead",
                            "url": "https://example.com/job",
                            "source_name": "Manual",
                            "source_type": "manual",
                            "evidence_type": "job",
                            "evidence_strength": "strong",
                            "evidence_warnings": [],
                            "observed_at": "2026-06-29T12:00:00+00:00",
                            "reasons": ["target role title signal: product lead", "domain fit: robotics"],
                            "flags": [],
                            "suppressed": False,
                            "text": "Series B robotics role reports to CEO.",
                        }
                    ],
                },
            )
            write_json(
                notes_path,
                {
                    "schema_version": 1,
                    "notes": [
                        {
                            "id": "note_1",
                            "finding_id": "abcdef123456",
                            "company": "",
                            "body": "Ask whether the product team reports to the founder.",
                            "created_at": "2026-06-29T12:01:00+00:00",
                        }
                    ],
                },
            )
            output = StringIO()
            with redirect_stdout(output):
                rc = main(["explain", "abcdef", "--json", str(artifact_path), "--notes", str(notes_path)])
        self.assertEqual(rc, 0)
        self.assertIn("Strength: strong", output.getvalue())
        self.assertIn("Ask whether", output.getvalue())

    def test_notes_adds_and_lists_company_notes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            notes_path = Path(tmpdir) / "notes.json"
            output = StringIO()
            with redirect_stdout(output):
                add_rc = main(["notes", "--company", "Test Robotics", "--add", "Check warm intro path.", "--notes", str(notes_path)])
                list_rc = main(["notes", "--company", "Test Robotics", "--notes", str(notes_path)])
            data = json.loads(notes_path.read_text(encoding="utf-8"))
        self.assertEqual(add_rc, 0)
        self.assertEqual(list_rc, 0)
        self.assertEqual(data["notes"][0]["company"], "Test Robotics")
        self.assertIn("Check warm intro path.", output.getvalue())

    def test_thesis_writes_role_thesis_without_job_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_path = root / "latest.json"
            profile_path = root / "profile.json"
            background_path = root / "background.json"
            notes_path = root / "notes.json"
            out_dir = root / "theses"
            write_json(
                artifact_path,
                {
                    "schema_version": 1,
                    "findings": [
                        {
                            "id": "abcdef123456",
                            "content_hash": "abcdef123456",
                            "tier": "Hidden Search Hypothesis",
                            "score": 72,
                            "company": "Test Robotics",
                            "title": "Strong watchlist company",
                            "url": "https://example.com",
                            "source_name": "Watchlist",
                            "source_type": "watchlist",
                            "evidence_type": "hidden_search",
                            "evidence_strength": "medium",
                            "evidence_warnings": [],
                            "observed_at": "2026-06-29T12:00:00+00:00",
                            "reasons": ["hidden-search company signal: series b", "domain fit: robotics"],
                            "flags": [],
                            "suppressed": False,
                            "text": "Series B robotics company scaling deployments.",
                        }
                    ],
                },
            )
            write_json(profile_path, profile_config())
            write_json(
                background_path,
                {
                    "schema_version": 1,
                    "summary": "Product and operations lead.",
                    "strengths": ["Turns ambiguous deployment problems into operating plans."],
                    "proof_points": ["Launched a product motion with first customer deployments."],
                    "best_environments": ["Early-stage robotics teams."],
                    "avoid_environments": [],
                    "constraints": [],
                    "network_context": [],
                },
            )
            write_json(
                notes_path,
                {
                    "schema_version": 1,
                    "notes": [
                        {
                            "id": "note_1",
                            "finding_id": "abcdef123456",
                            "company": "",
                            "body": "Verify deployment expansion.",
                            "created_at": "2026-06-29T12:01:00+00:00",
                        }
                    ],
                },
            )
            output = StringIO()
            with redirect_stdout(output):
                rc = main(
                    [
                        "thesis",
                        "abcdef",
                        "--json",
                        str(artifact_path),
                        "--profile",
                        str(profile_path),
                        "--background",
                        str(background_path),
                        "--notes",
                        str(notes_path),
                        "--out-dir",
                        str(out_dir),
                    ]
                )
            thesis_path = out_dir / "test-robotics-abcdef123456.md"
            thesis = thesis_path.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertIn("Wrote", output.getvalue())
        self.assertIn("## Proposed Function", thesis)
        self.assertIn("## Evidence To Verify", thesis)
        self.assertIn("Verify deployment expansion.", thesis)
        self.assertNotIn("## Job Description", thesis)

    def test_suppress_adds_structured_suppression(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            suppressions_path = Path(tmpdir) / "suppressions.json"
            output = StringIO()
            with redirect_stdout(output):
                rc = main(
                    [
                        "suppress",
                        "finding-123",
                        "--reason",
                        "Not a fit",
                        "--expires",
                        "2026-12-31",
                        "--suppressions",
                        str(suppressions_path),
                    ]
                )
            data = json.loads(suppressions_path.read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(data["suppressions"][0]["id"], "finding-123")
        self.assertEqual(data["suppressions"][0]["reason"], "Not a fit")

    def test_markdown_and_json_share_unsuppressed_finding_set(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        config = {
            **sources_config(),
            "profile": profile_config(),
            "scoring": profile_config()["scoring"],
            "watchlist": watchlist_config(),
            "suppressions": {"schema_version": 1, "suppressions": []},
        }
        result = run_sources(conn, config)
        artifact = build_artifact(conn, config, result, 7, False, {"command": "run", "digest_window_days": 7})
        markdown = render_markdown(artifact)
        unsuppressed = [finding for finding in artifact["findings"] if not finding["suppressed"]]
        for finding in unsuppressed:
            self.assertIn(finding["title"], markdown)

    def test_evidence_strength_marks_careers_fallback_weaker_than_role_finding(self):
        base = {
            "source_id": "careers",
            "source_name": "Careers",
            "source_type": "watchlist_careers",
            "company": "Test Robotics",
            "url": "https://example.com/careers",
            "text": "Careers open roles product commercial",
            "content_hash": "hash",
            "observed_at": "2026-06-29T12:00:00+00:00",
            "score": 50,
            "tier": "Watch Signal",
            "reasons": [],
            "flags": [],
        }
        role = normalize_finding({**base, "title": "Product Lead", "evidence_type": "job"}, {"schema_version": 1, "suppressions": []})
        fallback = normalize_finding({**base, "title": "Careers", "evidence_type": "job_page"}, {"schema_version": 1, "suppressions": []})
        self.assertEqual(role["evidence_strength"], "strong")
        self.assertEqual(fallback["evidence_strength"], "weak")
        self.assertIn("page_level_fallback", fallback["evidence_warnings"])

    def test_public_samples_do_not_include_private_names(self):
        sample_text = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in [
                "config/profile.json",
                "config/sources.json",
                "config/watchlist.json",
                "config/suppressions.json",
                "config/portfolio.json",
            ]
        )
        for term in ["CK", "Radar", "Sonar"]:
            self.assertNotIn(term, sample_text)


if __name__ == "__main__":
    unittest.main()
