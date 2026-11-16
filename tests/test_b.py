import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.class_analysis import compare_classes
from app.diagnosis import diagnose_students
from tools.build_b import build
from tools.prepare_fixture import make_responses

ROOT = Path(__file__).resolve().parents[1]


def by_indicator(report, indicator):
    return next(row for row in report["indicators"] if row["indicator_id"] == indicator)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        items = [{
            "item_id": f"Q{i}", "indicator_ids": indicators, "max_score": 1,
            "rubric_points": [{"rubric_point_id": f"Q{i}P1", "max_score": 1, "criterion": "正确作答"}],
            "topic_id": "T1",
        } for i, indicators in enumerate((
            ["I1", "I2"], ["I1"], ["I1"], ["I1"], ["I1"], ["I3"], ["I1"],
        ), 1)]
        self.catalog = {
            "items": items,
            "nodes": [{
                "node_id": "N", "item_ids": [r["item_id"] for r in items],
                "assessment_date": "2026-01-01",
            }],
            "indicators": [{"indicator_id": f"I{i}"} for i in range(1, 5)],
        }
        self.students = [{"student_id": s, "class_id": cls} for s, cls in (
            ("A1", "A"), ("A2", "A"), ("A3", "A"), ("B1", "B"), ("B2", "B"),
        )]

    def raw(self, student, item, record, *, revision=1, status="已评分", score="1"):
        return {
            "记录编号": record, "学生编号": student, "材料编号": item, "节点编号": "N", "主题编号": "T1",
            "作答事件编号": f"{student}-N-{item}", "修订版本": str(revision),
            "模拟提交时间": "2026-01-01T11:00:00+08:00", "评分状态": status,
            "得分": score, "满分": "1", "学生最终作答": "x" if status != "未作答" else "",
            "解答过程": "", "评分点得分": f"{item}P1={score}" if score else "",
        }

    def test_shared_items_coverage_and_highest_pending(self):
        rows = [
            self.raw("A1", "Q1", "R1", score="0"), self.raw("B1", "Q1", "R2"),
            self.raw("A1", "Q2", "R3"),
            self.raw("A1", "Q3", "R4"), self.raw("B1", "Q3", "R5"),
            self.raw("A1", "Q3", "R6", revision=2, status="待评分", score=""),
            self.raw("A1", "Q4", "R7", status="未作答", score=""),
            self.raw("A1", "Q5", "R8", score="2"),
            self.raw("A2", "Q6", "R9"),
        ]
        latest, quality = make_responses(rows, self.catalog, self.students)
        self.assertEqual((quality["raw_rows"], quality["event_count"], quality["usable_count"]), (9, 8, 5))
        usable = [r for r in latest if r["scoring_status"] == "graded" and r["validation_status"] == "valid"]
        self.assertFalse({"R4", "R6", "R7", "R8"} & {r["record_id"] for r in usable})
        student = diagnose_students(self.catalog, self.students, latest, usable)["A1"]["N"]
        summary = by_indicator(student, "I1")
        fields = ("valid_count", "pending_count", "unanswered_count", "review_count", "missing_record_count")
        self.assertEqual(tuple(summary[key] for key in fields), (2, 1, 1, 1, 1))
        self.assertEqual(summary["eligible_item_count"], 6)
        self.assertEqual(summary["score_rate"], 0.5)
        self.assertEqual(by_indicator(student, "I2")["score_rate"], 0.0)
        self.assertEqual(by_indicator(student, "I3")["evidence_status"], "insufficient")
        self.assertIsNone(by_indicator(student, "I3")["score_rate"])
        self.assertEqual(by_indicator(student, "I4")["findings"], [])

        report = compare_classes(self.catalog, self.students, usable)["N"]
        shared = by_indicator(report, "I1")
        self.assertEqual(report["comparison_item_ids"], ["Q1"])
        self.assertEqual(by_indicator(report, "I2")["item_ids"], ["Q1"])
        self.assertEqual(by_indicator(report, "I3")["comparison_status"], "no_common_items")
        self.assertEqual(by_indicator(report, "I4")["comparison_status"], "not_assessed")
        self.assertIsNone(by_indicator(report, "I3")["classes"][0]["score_rate"])
        self.assertEqual(
            [(r["class_size"], r["covered_students"], r["valid_count"], r["score_sum"], r["max_score_sum"])
             for r in shared["classes"]],
            [(3, 1, 1, 0, 1), (2, 1, 1, 1, 1)],
        )

    def test_conflicting_latest_is_one_review_cell(self):
        rows = [
            self.raw("A1", "Q1", "R1"),
            self.raw("A1", "Q1", "R2", revision=2),
            self.raw("A1", "Q1", "R3", revision=2, status="待评分", score=""),
            self.raw("A1", "Q1", "R4", revision=2),
        ]
        latest, quality = make_responses(rows, self.catalog, self.students)
        self.assertEqual([r["record_id"] for r in latest], ["R2", "R3"])
        self.assertEqual(quality["usable_count"], 0)
        self.assertIn("duplicate_import", {x["code"] for x in quality["issues"]})
        result = diagnose_students(self.catalog, self.students, latest, [])["A1"]["N"]
        summary = by_indicator(result, "I1")
        self.assertEqual((summary["review_count"], summary["pending_count"], summary["valid_count"]), (1, 0, 0))

    def test_rejects_two_usable_rows_for_one_cell(self):
        latest, _ = make_responses([self.raw("A1", "Q1", "R1")], self.catalog, self.students)
        with self.assertRaisesRegex(ValueError, "多条有效作答"):
            compare_classes(self.catalog, self.students, [latest[0], {**latest[0], "record_id": "R2"}])


class SyntheticBatchTests(unittest.TestCase):
    def test_build_and_read_both_outputs(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "results"
            build(ROOT / "fixtures" / "synthetic", out)
            personal = json.loads((out / "diagnosis.json").read_text(encoding="utf-8"))
            grouped = json.loads((out / "class_comparison.json").read_text(encoding="utf-8"))

        self.assertEqual(len(personal), 4)
        self.assertTrue(all(p["run_id"] == "synthetic-v1" for p in personal))
        student = next(p for p in personal if p["student_id"] == "S01")
        item = by_indicator(student, "SK01")
        self.assertEqual((item["score_sum"], item["max_score_sum"]), (1, 2))
        finding = item["findings"][0]
        self.assertIn("3m-n", finding["summary"])
        self.assertIn("3m+n", finding["summary"])
        self.assertEqual(finding["evidence"], [{
            "record_id": "X-R01", "rubric_point_ids": ["X01P2"], "step_numbers": [2],
        }])
        self.assertEqual(by_indicator(student, "SK03")["evidence_status"], "not_assessed")

        report, = grouped
        self.assertEqual((report["run_id"], report["comparison_item_ids"]), ("synthetic-v1", ["X01"]))
        shared = by_indicator(report, "SK01")
        self.assertEqual(
            [(c["class_size"], c["covered_students"], c["score_rate"]) for c in shared["classes"]],
            [(2, 1, 0.5), (2, 1, 1.0)],
        )
        self.assertEqual(by_indicator(report, "SK02")["comparison_status"], "no_common_items")


if __name__ == "__main__":
    unittest.main()
