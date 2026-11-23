"""Synthetic boundary cases from the 2026-11-23 repair list (items 1–4).

Each test pins one reported defect so it stays fixed: catalog validation shared by
both input routes, per-batch frozen rules and probes, equivalent-answer leaks in
hints, and mastery evidence that does not depend on the score scale.
"""

import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from app.cli import build, export
from app.storage import Store
from app.web.main import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


def copy_fixture(folder, name="input"):
    target = Path(folder) / name
    shutil.copytree(FIXTURE, target)
    return target


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = self.folder / "study.sqlite3"

    def client(self):
        client = TestClient(create_app(self.db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.addCleanup(client.close)
        return client


class CatalogValidationTests(Workspace):
    """Item 1: normalized input must pass the same catalog checks as the CSV route."""

    def assert_rejected(self, change, message):
        good = build(FIXTURE, self.db)
        source = copy_fixture(self.folder, f"bad-{message}")
        edit_json(source / "catalog.json", change)
        with self.assertRaisesRegex(ValueError, message):
            build(source, self.db)
        # The previous batch stays active and readable.
        self.assertEqual(Store(self.db).current()["manifest"]["run_id"], good)
        response = self.client().get("/api/students/S01/diagnosis", params={"run_id": good, "node_id": "NX"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["indicators"][0]["valid_count"], 1)

    def test_item_without_indicator_is_rejected(self):
        def clear(catalog):
            catalog["items"][0]["indicator_ids"] = []
        self.assert_rejected(clear, "X01")

    def test_duplicate_indicator_on_item_is_rejected(self):
        def duplicate(catalog):
            catalog["items"][0]["indicator_ids"] = ["SK01", "SK01"]
        self.assert_rejected(duplicate, "X01")

    def test_node_with_unknown_or_repeated_item_is_rejected(self):
        def unknown(catalog):
            catalog["nodes"][0]["item_ids"].append("X99")
        self.assert_rejected(unknown, "NX")

    def test_empty_node_is_rejected(self):
        def empty(catalog):
            catalog["nodes"][0]["item_ids"] = []
        self.assert_rejected(empty, "NX")

    def test_item_topic_must_match_indicator_topic(self):
        def mismatch(catalog):
            catalog["topics"].append({"topic_id": "OT", "title": "其他", "goal": "其他"})
            catalog["items"][0]["topic_id"] = "OT"
        self.assert_rejected(mismatch, "X01")

    def test_rubric_total_must_equal_max_score(self):
        def bad_rubric(catalog):
            catalog["items"][0]["rubric_points"][0]["max_score"] = 2
        self.assert_rejected(bad_rubric, "X01")


class FrozenRulesTests(Workspace):
    """Item 2: a batch keeps the rules and probes it was built with."""

    def custom_rules(self):
        path = self.folder / "custom-rules.json"
        path.write_text(json.dumps({"mastery": {"min_evidence": 1, "mastered_lower": 0.05}}), encoding="utf-8")
        return path

    def test_export_carries_rules_and_rebuild_reproduces_levels(self):
        with mock.patch.dict(os.environ, {"STUDY_RULES": str(self.custom_rules())}):
            run = build(FIXTURE, self.db)
        original = Store(self.db).batch(run)
        level = original["diagnoses"]["S03"]["NX"]["indicators"][0]["mastery"]["level"]
        self.assertEqual(level, "mastered")

        out = self.folder / "export"
        export(self.db, run, out)
        packaged = json.loads((out / "rules.json").read_text(encoding="utf-8"))
        self.assertEqual(packaged["mastery"]["min_evidence"], 1)

        rebuilt = Store(self.db).batch(build(out, self.db))  # default environment
        self.assertEqual(rebuilt["manifest"]["rules_sha256"], original["manifest"]["rules_sha256"])
        self.assertEqual(rebuilt["diagnoses"]["S03"]["NX"]["indicators"][0]["mastery"]["level"], level)

    def test_conflicting_override_is_refused_for_packaged_rules(self):
        run = build(FIXTURE, self.db)
        out = self.folder / "export"
        export(self.db, run, out)
        with mock.patch.dict(os.environ, {"STUDY_RULES": str(self.custom_rules())}):
            with self.assertRaisesRegex(ValueError, "规则"):
                build(out, self.db)

    def test_tampered_packaged_rules_are_refused(self):
        run = build(FIXTURE, self.db)
        out = self.folder / "export"
        export(self.db, run, out)
        edit_json(out / "rules.json", lambda rules: rules["mastery"].update(min_evidence=99))
        with self.assertRaisesRegex(ValueError, "rules_sha256"):
            build(out, self.db)

    def test_followup_questions_stay_with_their_batch(self):
        run = build(FIXTURE, self.db)
        client = self.client()
        params = {"run_id": run, "node_id": "NX"}
        before = client.get("/api/students/S01/followups/SK01", params=params).json()

        changed = self.folder / "changed-rules.json"
        changed.write_text(json.dumps({"followup": {"profile_cues": [["quantity", ["去括号"]]]}}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"STUDY_RULES": str(changed)}):
            after = client.get("/api/students/S01/followups/SK01", params=params).json()
            newer = build(FIXTURE, self.db)
            fresh = client.get("/api/students/S01/followups/SK01", params={**params, "run_id": newer}).json()
        self.assertEqual(after["questions"], before["questions"])
        self.assertEqual(after["probe_version"], before["probe_version"])
        self.assertNotEqual(fresh["probe_version"], before["probe_version"])
        self.assertNotEqual([q["question_id"] for q in fresh["questions"]],
                            [q["question_id"] for q in before["questions"]])

        answers = {q["question_id"]: "unsure" for q in before["questions"]}
        saved = client.put("/api/students/S01/followups/SK01", params=params, json={
            "expected_version": 0, "probe_version": before["probe_version"], "answers": answers})
        self.assertEqual(saved.status_code, 200, saved.text)

    def test_batches_built_before_freezing_do_not_follow_current_settings(self):
        from app.diagnosis.followup import LEGACY_REASON, followup_view
        batch = Store(self.db).batch(build(FIXTURE, self.db))
        for key in ("rules", "probes"):
            batch.pop(key)
        view = followup_view(batch, "S01", "NX", "SK01")
        self.assertEqual((view["questions"], view["unavailable_reason"]), ([], LEGACY_REASON))


class HintLeakTests(Workspace):
    """Item 3: equivalent forms of the reference answer are blocked."""

    def setUp(self):
        super().setUp()
        self.run = build(FIXTURE, self.db)
        self.api = self.client()
        self.edit = json.loads((FIXTURE / "teacher_adjustment.json").read_bytes())
        self.url = "/api/plans/PLAN-S01-NX/teacher-adjustment"

    def save(self, hint):
        edit = json.loads(json.dumps(self.edit))
        for activity in edit["activities"]:
            if activity["resource_id"] == "X01" or activity is edit["activities"][0]:
                activity["resource_id"] = "X01"
                activity["hints"] = [hint]
                break
        return self.api.put(self.url, params={"run_id": self.run}, json=edit)

    def test_reordered_and_rewritten_answers_are_rejected(self):
        for hint in ("将化简式填写为 −n+3m", "最后写成 -n + 3m 即可", "化简后得到 3·m − n。",
                     "填 3m+(-n)", "结果等于 m×3−n", "写出 −1n+3m"):
            with self.subTest(hint=hint):
                response = self.save(hint)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["code"], "answer_in_hint")

    def test_method_hints_and_reviewed_templates_pass(self):
        templates = self.api.get("/api/hint-templates", params={"run_id": self.run}).json()["templates"]
        self.assertTrue(templates)
        for hint in ("先标出括号前的符号，逐项检查去括号和合并。", templates[0]["text"], "检查 3m 与 2m 是否同类项"):
            with self.subTest(hint=hint):
                self.assertEqual(self.save(hint).status_code, 200, hint)
                self.edit["expected_version"] += 1

    def test_custom_hints_are_marked_for_review(self):
        response = self.save("先把括号外的负号分配到每一项。")
        self.assertEqual(response.status_code, 200)
        activity = next(a for a in response.json()["effective_activities"] if a["resource_id"] == "X01")
        self.assertEqual(activity["hint_review"], "custom")


class MasteryEvidenceTests(unittest.TestCase):
    """Item 4: rescaling the same response must not change the evidence weight."""

    def test_scale_and_rubric_split_do_not_change_estimate(self):
        from app.diagnosis.mastery import estimate
        from app.rules import load_rules
        config = load_rules()["mastery"]
        base = estimate([{"record_id": "R", "node_id": "N", "score": 1, "max_score": 2}], config)
        scaled = estimate([{"record_id": "R", "node_id": "N", "score": 10, "max_score": 20}], config)
        self.assertEqual({k: base[k] for k in ("estimate", "interval", "level", "evidence_count")},
                         {k: scaled[k] for k in ("estimate", "interval", "level", "evidence_count")})
        self.assertEqual(base["evidence_count"], 1)
        self.assertEqual(base["level"], "insufficient_evidence")

    def test_output_is_labelled_as_an_index_not_a_probability(self):
        from app.diagnosis.mastery import estimate
        from app.rules import load_rules
        result = estimate([{"record_id": "R", "node_id": "N", "score": 1, "max_score": 2}], load_rules()["mastery"])
        self.assertEqual(result["interpretation"], "score_share_index")


if __name__ == "__main__":
    unittest.main()
