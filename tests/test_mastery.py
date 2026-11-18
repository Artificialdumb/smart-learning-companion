import unittest

from app.diagnosis.mastery import beta_cdf, beta_quantile, cumulative_rows, estimate
from app.rules import load_rules

MASTERY_DEFAULTS = load_rules()["mastery"]


def row(record_id, node_id, score, max_score):
    return {"record_id": record_id, "node_id": node_id, "score": score, "max_score": max_score}


class BetaTests(unittest.TestCase):
    def test_quantiles_match_closed_forms(self):
        # Beta(2,1) has CDF x^2; Beta(1,b) has CDF 1-(1-x)^b; Beta(a,1) has CDF x^a.
        self.assertAlmostEqual(beta_quantile(0.25, 2, 1), 0.5, places=6)
        self.assertAlmostEqual(beta_quantile(0.5, 2, 2), 0.5, places=6)
        self.assertAlmostEqual(beta_cdf(0.3, 1, 4), 1 - 0.7 ** 4, places=9)
        self.assertAlmostEqual(beta_quantile(0.05, 11, 1), 0.05 ** (1 / 11), places=6)


class EstimateTests(unittest.TestCase):
    def level(self, earned, possible):
        return estimate([row("R", "N", earned, possible)], MASTERY_DEFAULTS)

    def test_levels_follow_thresholds(self):
        self.assertEqual(self.level(10, 10)["level"], "mastered")
        self.assertEqual(self.level(6, 10)["level"], "developing")
        self.assertEqual(self.level(1, 10)["level"], "needs_support")
        small = self.level(2, 2)
        self.assertEqual(small["level"], "insufficient_evidence")
        self.assertEqual(small["estimate"], 0.75)

    def test_interval_narrows_with_more_evidence(self):
        few, many = self.level(3, 4), self.level(30, 40)
        self.assertLess(many["interval"][1] - many["interval"][0], few["interval"][1] - few["interval"][0])

    def test_no_evidence_has_no_estimate(self):
        empty = estimate([], MASTERY_DEFAULTS)
        self.assertEqual((empty["estimate"], empty["interval"], empty["level"]), (None, None, "insufficient_evidence"))


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
