import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.cli import build
from tools.ablation import CRITERIA, analyze, packet, sign_test

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


class AblationTests(unittest.TestCase):
    def test_packet_is_blinded_and_analysis_reads_ratings(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            db = folder / "study.sqlite3"
            run = build(FIXTURE, db)
            out, count = packet(db, run, folder / "packet", per_kind=5, seed=3)
            self.assertGreater(count, 0)
            document = (out / "评价材料.md").read_text(encoding="utf-8")
            key = json.loads((out / "key.json").read_text(encoding="utf-8"))
            # Teachers see neutral labels only; condition names stay in the key file.
            self.assertNotIn("仅按得分率", document)
            self.assertNotIn("condition", document)
            for case in key["cases"].values():
                self.assertEqual(sorted(case["labels"].values()), ["A", "B", "C"])
            # The S01 case carries the localized step only from condition B on.
            s01 = next(cid for cid, case in key["cases"].items() if case["student_id"] == "S01"
                       and case["indicator_id"] == "SK01")
            section = document.split(f"## 案例 {s01}")[1].split("## 案例")[0]
            self.assertEqual(section.count("第 2 步「"), 2)  # cited step: versions B and C only
            self.assertEqual(section.count("错因追问"), 1)

            with (out / "评分表.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                condition = key["cases"][row["case_id"]]["labels"][row["version"]]
                for name, _ in CRITERIA:
                    row[name] = {"A": 2, "B": 4, "C": 4}[condition]
                row["misleading(是/否)"] = "否"
            filled = folder / "rater1.csv"
            with filled.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            report = analyze(out / "key.json", [filled, filled])
            self.assertIn(f"{count}/0", report)
            self.assertIn("依据充分性", report)
            self.assertIn("4.00", report)

    def test_sign_test(self):
        self.assertAlmostEqual(sign_test(5, 0), 0.0625)
        self.assertEqual(sign_test(0, 0), None)
        self.assertEqual(sign_test(3, 3), 1.0)


if __name__ == "__main__":
    unittest.main()
