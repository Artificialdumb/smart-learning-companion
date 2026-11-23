import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.cli import build
from app.diagnosis.probes import PROBE_VERSION, criterion_dimension
from app.web.main import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


class CriterionTests(unittest.TestCase):
    def test_criteria_map_to_dimensions(self):
        self.assertEqual(criterion_dimension("写出正确结果"), "calculation")
        self.assertEqual(criterion_dimension("正确去括号并合并"), "concept")
        self.assertEqual(criterion_dimension("正确表示数量关系"), "reading")
        self.assertIsNone(criterion_dimension("书写工整"))


class FollowupTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "study.sqlite3"
        self.run_id = build(FIXTURE, db)
        self.client = TestClient(create_app(db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.addCleanup(self.client.close)
        self.url = "/api/students/S01/followups/SK01"
        self.params = {"run_id": self.run_id, "node_id": "NX"}

    def test_questions_follow_the_missed_rubric_point_and_localized_step(self):
        view = self.client.get(self.url, params=self.params).json()
        self.assertEqual([p["rubric_point_id"] for p in view["linked_rubric_points"]], ["X01P2"])
        self.assertEqual(view["linked_rubric_points"][0]["dimension"], "calculation")

        questions = view["questions"]
        self.assertEqual(len(questions), 4)
        first, second = questions[0], questions[1]
        self.assertEqual((first["dimension"], first["focus"], first["rubric_point_ids"]),
                         ("consistency", True, ["X01P2"]))
        self.assertIn("「3m-n」", first["prompt"])
        self.assertIn("「3m+n」", first["prompt"])
        self.assertEqual((second["dimension"], second["focus"]), ("calculation", True))
        self.assertTrue(all(not q["focus"] for q in questions[2:]))
        self.assertTrue(all("answer_id" not in q and "explanation" not in q for q in questions))

    def test_wrong_targeted_answer_names_the_rubric_point(self):
        view = self.client.get(self.url, params=self.params).json()
        answers = {}
        for q in view["questions"]:
            if q["dimension"] == "consistency":
                answers[q["question_id"]] = next(o["option_id"] for o in q["options"] if o["text"] == "3m+n")
            else:
                answers[q["question_id"]] = "unsure"
        saved = self.client.put(self.url, params=self.params, json={
            "expected_version": 0, "probe_version": view["probe_version"], "answers": answers,
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        result = saved.json()["result"]
        self.assertEqual(result["suspected_causes"], ["consistency"])
        self.assertIn("X01P2", result["conclusion"])

        correct = {q["question_id"]: next(o["option_id"] for o in q["options"] if o["text"] == "3m-n")
                   for q in view["questions"] if q["dimension"] == "consistency"}
        self.assertEqual(len(correct), 1)

    def test_answer_count_and_old_probe_version_are_rejected(self):
        view = self.client.get(self.url, params=self.params).json()
        three = {q["question_id"]: "unsure" for q in view["questions"][:3]}
        short = self.client.put(self.url, params=self.params, json={
            "expected_version": 0, "probe_version": view["probe_version"], "answers": three})
        self.assertTrue(view["probe_version"].startswith(PROBE_VERSION + "+"))
        self.assertEqual(short.json()["error"]["code"], "invalid_answers")
        full = {q["question_id"]: "unsure" for q in view["questions"]}
        stale = self.client.put(self.url, params=self.params, json={
            "expected_version": 0, "probe_version": "screening-1.0", "answers": full})
        self.assertEqual(stale.status_code, 409)

    def test_indicator_without_loss_has_no_questions(self):
        view = self.client.get("/api/students/S03/followups/SK01", params=self.params).json()
        self.assertEqual((view["questions"], view["linked_rubric_points"]), ([], []))
        self.assertIsNotNone(view["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
