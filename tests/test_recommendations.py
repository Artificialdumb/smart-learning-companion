import unittest
from pathlib import Path

from app.catalog.validation import validate_catalog
from app.cli import normalized_batch
from app.contracts import ContractError
from app.diagnosis import diagnose_students
from app.recommendations import checked_text, generate_plans


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        _, catalog, self.roster, self.rows, _ = normalized_batch(FIXTURE)
        self.catalog = validate_catalog(catalog)

    def plans(self, selector=None):
        usable = [r for r in self.rows if r["scoring_status"] == "graded"]
        diagnosis = diagnose_students(self.catalog, self.roster, self.rows, usable)
        return generate_plans(self.catalog, diagnosis, usable, select_resource=selector)

    def test_practice_and_observation_remain_linked_to_different_evidence(self):
        plan = self.plans()["S01"]["NX"]
        practice, observe = plan["activities"]
        self.assertEqual((practice["kind"], practice["evidence_record_ids"]), ("practice_needed", ["X-R01"]))
        self.assertEqual((observe["kind"], observe["indicator_id"]), ("observe_more", "SK02"))
        self.assertTrue(observe["finding_ids"])
        self.assertFalse(observe["evidence_record_ids"])
        self.assertNotIn("SK03", {row["indicator_id"] for row in plan["activities"]})
        self.assertNotIn("strength", {row["kind"] for row in self.plans()["S03"]["NX"]["activities"]})

    def test_independent_full_marks_allow_an_unattempted_variant_and_invalid_model_falls_back(self):
        item = self.catalog["items"][0]
        for n in (4, 5):
            item_id = f"X0{n}"
            self.catalog["items"].append({
                **item, "item_id": item_id, "prompt": f"化简 {n}m+(3n-2m)。",
            })
            self.catalog["nodes"][0]["item_ids"].append(item_id)
        self.rows.append({
            **self.rows[2], "record_id": "X-R06", "event_id": "S03-NX-X04", "item_id": "X04",
        })
        default, = self.plans()["S03"]["NX"]["activities"]
        invalid, = self.plans(lambda *args: "other-batch-id")["S03"]["NX"]["activities"]
        model, = self.plans(lambda kind, indicator, ids: "X-L01")["S03"]["NX"]["activities"]
        self.assertEqual((default["kind"], default["resource_id"]), ("strength", "X05"))
        self.assertEqual(default["evidence_record_ids"], ["X-R03", "X-R06"])
        self.assertEqual(default, invalid)
        self.assertEqual(model["resource_id"], "X-L01")

    def test_direct_answers_and_malformed_hint_lists_are_rejected(self):
        items = {row["item_id"]: row for row in self.catalog["items"]}
        for hint in ("直接填 3m-n", "核对以后写出 ３ｍ－ｎ。", "答案是正确的那个选项"):
            with self.subTest(hint=hint), self.assertRaises(ContractError):
                checked_text("X01", [hint], "核对每步。", items)
        with self.assertRaises(ContractError):
            checked_text("X01", [], "核对每步。", items)
