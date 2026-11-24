import unittest

from app.class_analysis import node_summary
from app.diagnosis.mastery import cumulative_capacity, mastered_min_responses, with_reachability
from app.rules import load_rules

MASTERY = load_rules()["mastery"]


class MasteryReachabilityTests(unittest.TestCase):
    def test_default_rules_need_five_full_scores(self):
        # 5% quantile of Beta(1+n, 1) is 0.05 ** (1 / (n + 1)): 0.549 for n=4, 0.607 for n=5.
        self.assertEqual(mastered_min_responses(MASTERY), 5)
        self.assertEqual(mastered_min_responses({**MASTERY, "mastered_lower": 0.5}), 4)
        self.assertIsNone(mastered_min_responses({**MASTERY, "mastered_lower": 1.0}, limit=50))

    def test_capacity_counts_the_same_nodes_as_the_index(self):
        scope = {"N1": {"I1": ["Q1", "Q2"], "I2": ["Q3"]}, "N2": {"I1": ["Q1"], "I2": []}}
        dates = {"N1": "2026-01-20", "N2": "2026-06-17"}
        self.assertEqual(cumulative_capacity("N1", scope, dates), {"I1": 2, "I2": 1})
        self.assertEqual(cumulative_capacity("N2", scope, dates), {"I1": 3, "I2": 1})
        self.assertEqual(cumulative_capacity("N2", scope, {"N1": "2026-01-20", "N2": None}), {"I1": 1, "I2": 0})
        result = with_reachability({}, 3, 5)
        self.assertEqual(result, {"response_capacity": 3, "mastered_min_responses": 5, "mastered_reachable": False})


def miss(cls, item, point, missed, scored):
    return {"kind": "common_miss", "class_id": cls, "item_id": item, "rubric_point_id": point,
            "criterion": "写出结果", "missed_students": missed, "scored_students": scored,
            "record_ids": [f"{cls}{item}{i}" for i in range(missed)], "summary": ""}


def klass(cls, score, maximum):
    return {"class_id": cls, "class_size": 10, "covered_students": 5, "valid_count": 5,
            "score_sum": score, "max_score_sum": maximum}


class NodeSummaryTests(unittest.TestCase):
    def test_gaps_and_shared_misses_are_recomputable(self):
        rows = [
            {"indicator_id": "I1", "comparison_status": "comparable", "item_ids": ["Q1", "Q2"],
             "classes": [klass("A", 6, 10), klass("B", 3, 10)],
             "findings": [miss("A", "Q1", "Q1P1", 2, 5), miss("B", "Q1", "Q1P1", 4, 4),
                          miss("A", "Q2", "Q2P1", 3, 5)]},
            {"indicator_id": "I2", "comparison_status": "comparable", "item_ids": ["Q3"],
             "classes": [klass("A", 5, 10), klass("B", 4, 10)],
             "findings": [miss("A", "Q3", "Q3P1", 3, 3), miss("B", "Q3", "Q3P1", 3, 3)]},
            {"indicator_id": "I3", "comparison_status": "not_assessed", "item_ids": [], "classes": [],
             "findings": []},
        ]
        summary = node_summary(rows)
        self.assertEqual([(g["indicator_id"], g["rate_gap"]) for g in summary["largest_gaps"]],
                         [("I1", 0.3), ("I2", 0.1)])
        # Q2P1 is a common miss only in class A, so it is not shared.
        self.assertEqual([(s["item_id"], s["missed_students"], s["scored_students"])
                          for s in summary["shared_misses"]], [("Q3", 6, 6), ("Q1", 6, 9)])
        self.assertEqual([c["record_ids"] for c in summary["shared_misses"][1]["classes"]],
                         [["AQ10", "AQ11"], ["BQ10", "BQ11", "BQ12", "BQ13"]])


if __name__ == "__main__":
    unittest.main()
