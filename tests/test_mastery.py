import unittest

from app.diagnosis.mastery import beta_cdf, beta_quantile, cumulative_rows, estimate
from app.rules import load_rules
from tools.mastery_calibration import simulate

MASTERY = load_rules()["mastery"]


def row(record_id, node_id, score, max_score):
    return {"record_id": record_id, "node_id": node_id, "score": score, "max_score": max_score}


def responses(*scores, maximum=2):
    return [row(f"R{i}", "N", score, maximum) for i, score in enumerate(scores)]


class BetaTests(unittest.TestCase):
    def test_quantiles_match_closed_forms(self):
        # Beta(2,1) has CDF x^2; Beta(1,b) has CDF 1-(1-x)^b; Beta(a,1) has CDF x^a.
        self.assertAlmostEqual(beta_quantile(0.25, 2, 1), 0.5, places=6)
        self.assertAlmostEqual(beta_quantile(0.5, 2, 2), 0.5, places=6)
        self.assertAlmostEqual(beta_cdf(0.3, 1, 4), 1 - 0.7 ** 4, places=9)
        self.assertAlmostEqual(beta_quantile(0.05, 11, 1), 0.05 ** (1 / 11), places=6)


class EstimateTests(unittest.TestCase):
    def test_levels_follow_thresholds(self):
        self.assertEqual(estimate(responses(*[2] * 6), MASTERY)["level"], "mastered")
        self.assertEqual(estimate(responses(2, 1, 1, 2), MASTERY)["level"], "developing")
        self.assertEqual(estimate(responses(0, 0, 1), MASTERY)["level"], "needs_support")
        few = estimate(responses(2, 2), MASTERY)
        self.assertEqual((few["level"], few["evidence_count"]), ("insufficient_evidence", 2))

    def test_interval_narrows_only_with_more_responses(self):
        few, many = estimate(responses(2, 1), MASTERY), estimate(responses(*[2, 1] * 10), MASTERY)
        self.assertLess(many["interval"][1] - many["interval"][0], few["interval"][1] - few["interval"][0])
        rescaled = estimate(responses(20, 10, maximum=20), MASTERY)
        self.assertEqual(rescaled["interval"], few["interval"])

    def test_no_evidence_has_no_estimate(self):
        empty = estimate([], MASTERY)
        self.assertEqual((empty["estimate"], empty["interval"], empty["level"]), (None, None, "insufficient_evidence"))


class CalibrationTests(unittest.TestCase):
    """Counting correlated rubric points as independent trials makes intervals overconfident."""

    def test_per_response_intervals_keep_nominal_coverage(self):
        for count, points in ((3, 4), (6, 10)):
            with self.subTest(responses=count, points=points):
                result = simulate(students=1500, responses=count, points=points, seed=11)
                per_point, per_response = result["per_point"][0], result["per_response"][0]
                self.assertGreaterEqual(per_response, 0.85)
                self.assertLess(per_point, per_response)
        self.assertLess(simulate(students=1500, responses=6, points=10, seed=11)["per_point"][0], 0.75)


class CumulativeTests(unittest.TestCase):
    def test_only_current_and_earlier_nodes_count(self):
        scope = {"N1": {"I": ["Q1"]}, "N2": {"I": ["Q2"]}, "N3": {"I": ["Q3"]}}
        dates = {"N1": "2026-01-01", "N2": "2026-02-01", "N3": "2026-03-01"}
        usable = {("S", node, item): row(f"R-{node}", node, 1, 2)
                  for node, item in (("N1", "Q1"), ("N2", "Q2"), ("N3", "Q3"))}
        rows = cumulative_rows(usable, "S", "N2", scope, dates)["I"]
        self.assertEqual(sorted(r["record_id"] for r in rows), ["R-N1", "R-N2"])
        self.assertEqual(len(cumulative_rows(usable, "S", "N2", scope, {})["I"]), 1)


if __name__ == "__main__":
    unittest.main()
