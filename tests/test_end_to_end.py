import json
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.cli import build, export
from app.web.main import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


class BatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = self.folder / "study.sqlite3"
        self.client = TestClient(create_app(self.db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.addCleanup(self.client.close)
        self.get_plan = "/api/students/S01/recommendations"
        self.adjust = "/api/plans/PLAN-S01-NX/teacher-adjustment"
        self.edit = json.loads((FIXTURE / "teacher_adjustment.json").read_bytes())

    def test_build_evidence_adjustment_snapshot_and_batch_isolation(self):
        self.assertEqual(self.client.get("/api/context").status_code, 503)
        run = build(FIXTURE, self.db)
        params = {"run_id": run, "node_id": "NX"}
        self.assertEqual(self.client.get("/api/context").json()["run_id"], run)
        self.assertIn("个人诊断", self.client.get("/").text)
        self.assertEqual(self.client.get("/static/main.js").status_code, 200)
        self.assertEqual(self.client.get("/api/catalog", params=params).status_code, 200)

        diagnostic = self.client.get("/api/students/S01/diagnosis", params=params).json()
        evidence = diagnostic["indicators"][0]["findings"][0]["evidence"][0]
        row = self.client.get(f"/api/records/{evidence['record_id']}", params=params).json()
        self.assertEqual((row["revision"], row["score"], row["steps"][1]), (1, 1, "=3m-n。"))
        self.assertEqual(row["rubric_points"][1]["awarded"], 0)
        resource = self.client.get("/api/resources/X01", params=params).json()
        self.assertIn("prompt", resource)
        self.assertNotIn("reference_answer", resource)
        classes = self.client.get("/api/classes/compare", params=params).json()
        self.assertEqual(classes["comparison_item_ids"], ["X01"])

        initial = self.client.get(self.get_plan, params=params).json()
        self.assertEqual(initial["original_activities"], initial["effective_activities"])
        self.edit["activities"][0]["sequence"] = 2
        self.edit["activities"][1]["sequence"] = 1
        saved = self.client.put(self.adjust, params=params, json=self.edit)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["effective_activities"][1]["resource_id"], "X-L01")
        self.assertEqual(saved.json()["original_activities"], initial["original_activities"])
        self.assertEqual(self.client.get(self.get_plan, params=params).json(), saved.json())
        self.assertEqual(self.client.put(self.adjust, params=params, json=self.edit).status_code, 409)

        new_run = build(FIXTURE, self.db)
        self.assertEqual(self.client.get("/api/context").json()["run_id"], new_run)
        self.assertEqual(self.client.get(self.get_plan, params={**params, "run_id": new_run}).json()["adjustment_version"], 0)
        self.assertEqual(self.client.get(self.get_plan, params=params).json()["adjustment_version"], 1)
        self.assertEqual(self.client.get("/api/records/X-R01", params=params).json(), row)

        report_dir = export(self.db, run, self.folder / "export")
        manifest = json.loads((report_dir / "manifest.json").read_bytes())
        self.assertEqual(manifest["adjustment_versions"]["PLAN-S01-NX"], 1)
        plans = json.loads((report_dir / "recommendations.json").read_bytes())
        self.assertIn(saved.json(), plans)
        self.assertTrue((report_dir / "contracts.md").exists())
        rebuilt = build(report_dir, self.db)
        self.assertNotEqual(rebuilt, run)

    def test_invalid_edits_and_failed_build_do_not_change_active_state(self):
        run = build(FIXTURE, self.db)
        params = {"run_id": run, "node_id": "NX"}
        self.assertEqual(self.client.get(self.get_plan, params={"node_id": "NX"}).status_code, 422)
        self.assertEqual(self.client.get(self.get_plan, params={**params, "node_id": "missing"}).status_code, 404)
        self.edit["activities"][0]["resource_id"] = "missing"
        self.assertEqual(self.client.put(self.adjust, params=params, json=self.edit).status_code, 404)
        self.edit["activities"][0]["resource_id"] = "X02"
        self.assertEqual(self.client.put(self.adjust, params=params, json=self.edit).status_code, 422)
        self.edit["activities"][0]["resource_id"] = "X01"
        self.edit["activities"][0]["hints"] = ["答案是 3m-n。"]
        self.assertEqual(self.client.put(self.adjust, params=params, json=self.edit).json()["error"]["code"],
                         "answer_in_hint")
        self.assertEqual(self.client.get(self.get_plan, params=params).json()["adjustment_version"], 0)
        broken = shutil.copytree(FIXTURE, self.folder / "broken")
        (broken / "catalog.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(KeyError):
            build(broken, self.db)
        self.assertEqual(self.client.get("/api/context").json()["run_id"], run)

    def test_concurrent_saves_of_the_same_version_have_exactly_one_winner(self):
        run = build(FIXTURE, self.db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: self.client.put(self.adjust, params={"run_id": run}, json=self.edit).status_code,
                range(2),
            ))
        self.assertEqual(sorted(results), [200, 409])
