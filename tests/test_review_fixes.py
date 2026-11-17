"""Regression tests for issues found in the 2026-11 code review."""

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from app.cli import build, case_examples, export
from app.storage import Store
from app.web.main import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = self.folder / "study.sqlite3"
        self.run = build(FIXTURE, self.db)

    def test_rebuild_from_export_drops_export_only_manifest_keys(self):
        client = TestClient(create_app(self.db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.addCleanup(client.close)
        edit = json.loads((FIXTURE / "teacher_adjustment.json").read_bytes())
        response = client.put("/api/plans/PLAN-S01-NX/teacher-adjustment", params={"run_id": self.run}, json=edit)
        self.assertEqual(response.status_code, 200)

        out = self.folder / "export"
        export(self.db, self.run, out)
        exported = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(exported["adjustment_versions"]["PLAN-S01-NX"], 1)

        rebuilt = Store(self.db).batch(build(out, self.db))["manifest"]
        self.assertNotIn("exported_at", rebuilt)
        self.assertNotIn("adjustment_versions", rebuilt)
        self.assertEqual(rebuilt["input_run_id"], self.run)

    def test_hidden_and_missing_records_are_indistinguishable(self):
        digest = hashlib.sha256(b"secret").hexdigest()
        accounts = self.folder / "accounts.json"
        accounts.write_text(json.dumps({
            "s01": {"role": "student", "student_id": "S01", "token_sha256": digest},
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, {"STUDY_ACCESS_FILE": str(accounts)}):
            client = TestClient(create_app(self.db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
        self.addCleanup(client.close)
        params, auth = {"run_id": self.run}, ("s01", "secret")

        own = client.get("/api/records/X-R01", params=params, auth=auth)
        hidden = client.get("/api/records/X-R03", params=params, auth=auth)
        absent = client.get("/api/records/NOPE", params=params, auth=auth)
        self.assertEqual(own.status_code, 200)
        self.assertEqual((hidden.status_code, absent.status_code), (404, 404))
        self.assertEqual(hidden.json()["error"]["code"], absent.json()["error"]["code"])
        # Per-student endpoints still answer 403 for students outside the account.
        self.assertEqual(client.get("/api/students/S03/diagnosis", params={**params, "node_id": "NX"},
                                    auth=auth).status_code, 403)

    def test_case_examples_reports_missing_diagnosis_as_value_error(self):
        plans = [{"plan_id": "P", "student_id": "S", "node_id": "N", "run_id": "r", "adjustment_version": 0,
                  "effective_activities": [{"kind": "practice_needed", "indicator_id": "I"}]}]
        with self.assertRaisesRegex(ValueError, "找不到对应诊断"):
            case_examples({"S": {"N": {"indicators": []}}}, plans)


if __name__ == "__main__":
    unittest.main()
