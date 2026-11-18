import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.catalog import RELATIONS, STANDARD_PAGES, TEXTBOOKS
from app.catalog.locations import STANDARD_CLAUSES, TEXTBOOK_LOCATIONS
from app.cli import build
from app.rules import load_rules, rules_digest
from app.storage import Store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


def has_comment_keys(value):
    if isinstance(value, dict):
        return any(k.startswith("_") or has_comment_keys(v) for k, v in value.items())
    if isinstance(value, list):
        return any(has_comment_keys(v) for v in value)
    return False


class DefaultRulesTests(unittest.TestCase):
    def test_sections_are_loaded_without_comments(self):
        rules = load_rules()
        self.assertEqual(set(rules), {"mastery", "diagnosis", "followup", "recommendations", "export"})
        self.assertFalse(has_comment_keys(rules))
        self.assertEqual([c["kind"] for c in rules["export"]["case_examples"]],
                         ["practice_needed", "strength", "observe_more"])

    def test_curriculum_keeps_its_original_shape(self):
        indicators = {f"T0{t}I{i}" for t in (1, 2, 3) for i in (1, 2, 3)}
        self.assertEqual(set(TEXTBOOK_LOCATIONS), indicators)
        self.assertEqual(set(STANDARD_CLAUSES), indicators)
        self.assertEqual(TEXTBOOKS, {"T01": "B05", "T02": "B06", "T03": "B02"})
        self.assertEqual((STANDARD_PAGES["T01"], STANDARD_PAGES["default"]), ([62, 55], [63, 56]))
        self.assertEqual(TEXTBOOK_LOCATIONS["T01I2"], (("4.2 整式的加法与减法", (28, 33), (95, 100)),))
        self.assertEqual(STANDARD_CLAUSES["T02I3"], ("方程与方程组", "①", "⑧"))
        for entries in TEXTBOOK_LOCATIONS.values():
            for _, pdf_pages, printed_pages in entries:
                self.assertTrue(pdf_pages[0] <= pdf_pages[1] and printed_pages[0] <= printed_pages[1])
        self.assertEqual(len(RELATIONS), 5)
        self.assertTrue(all({start, end} <= indicators for start, end, _, _ in RELATIONS))


class OverrideTests(unittest.TestCase):
    def test_override_file_changes_thresholds_and_manifest_digest(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            db = folder / "study.sqlite3"
            default_run = build(FIXTURE, db)
            default_manifest = Store(db).batch(default_run)
            sk01 = default_manifest["diagnoses"]["S01"]["NX"]["indicators"][0]["mastery"]
            self.assertEqual((sk01["level"], sk01["estimate"]), ("insufficient_evidence", 0.5))

            override = folder / "rules.json"
            override.write_text(json.dumps({"mastery": {"min_points": 1}}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"STUDY_RULES": str(override)}):
                self.assertEqual(load_rules()["mastery"]["min_points"], 1)
                self.assertEqual(load_rules()["mastery"]["prior"], [1, 1])
                custom_run = build(FIXTURE, db)
            custom = Store(db).batch(custom_run)
            sk01 = custom["diagnoses"]["S01"]["NX"]["indicators"][0]["mastery"]
            self.assertEqual(sk01["level"], "developing")
            self.assertNotEqual(custom["manifest"]["rules_sha256"], default_manifest["manifest"]["rules_sha256"])
            self.assertEqual(default_manifest["manifest"]["rules_sha256"], rules_digest())


if __name__ == "__main__":
    unittest.main()
