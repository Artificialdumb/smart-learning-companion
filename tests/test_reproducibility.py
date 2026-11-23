"""Claims made in the design document and slides about reproducing a batch."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.cli import build, export
from app.storage import Store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"
ANALYSIS = ("diagnoses", "comparisons", "plans", "rules", "probes", "catalog", "students", "records")


class ReproducibilityTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = self.folder / "study.sqlite3"
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("STUDY_MODEL", None)  # the optional local model is the one non-deterministic part

    def test_same_input_gives_identical_analysis(self):
        store = Store(self.db)
        first, second = (store.batch(build(FIXTURE, self.db)) for _ in range(2))
        for key in ANALYSIS:
            with self.subTest(part=key):
                self.assertEqual(first[key], second[key])
        # Only identifiers and timestamps differ between two builds.
        self.assertNotEqual(first["manifest"]["run_id"], second["manifest"]["run_id"])
        same = {k for k in first["manifest"] if first["manifest"][k] == second["manifest"].get(k)}
        self.assertLessEqual(set(first["manifest"]) - same, {"run_id", "built_at"})

    def test_rebuild_from_package_reproduces_initial_analysis(self):
        store = Store(self.db)
        original = store.batch(build(FIXTURE, self.db))
        out = self.folder / "package"
        export(self.db, original["manifest"]["run_id"], out)
        rebuilt = store.batch(build(out, self.db))
        for key in ("diagnoses", "comparisons", "plans", "rules", "probes"):
            with self.subTest(part=key):
                self.assertEqual(rebuilt[key], original[key])


if __name__ == "__main__":
    unittest.main()
