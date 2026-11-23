"""Score-share mastery index with a Beta-smoothed interval.

Evidence unit: one valid response. A response with score s of maximum m adds s/m
to the "earned" side and 1 - s/m to the "missed" side of a Beta prior, so the
weight of a response does not depend on how many points the rubric splits it into
(1/2 and 10/20 are the same evidence). Score units and rubric points within one
response are strongly correlated, and counting them as independent trials made
intervals too narrow (see docs/掌握度证据权重说明.md and tools/mastery_calibration.py).

The result is an index of the observed score share, smoothed toward the prior. It is
not a calibrated probability that the student has mastered the indicator: nothing in
the data links the index to an external mastery criterion.
"""

import math

MODEL = "beta_score_share_per_response"
INTERPRETATION = "score_share_index"


def _beta_cf(a, b, x):
    # Continued fraction for the regularized incomplete beta (modified Lentz).
    tiny, c, d = 1e-30, 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        for numerator in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            d = 1.0 + numerator * d
            d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + numerator / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < 1e-12:
            break
    return h


def beta_cdf(x, a, b):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    log_front = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                 + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return math.exp(log_front) * _beta_cf(a, b, x) / a
    return 1.0 - math.exp(log_front) * _beta_cf(b, a, 1 - x) / b


def beta_quantile(p, a, b):
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if beta_cdf(mid, a, b) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def estimate(rows, config):
    """Summarize usable responses into a score-share index, interval and evidence level."""
    alpha, beta = config["prior"]
    shares = [row["score"] / row["max_score"] for row in rows]
    level_width = config["interval_level"]
    result = {
        "model": MODEL,
        "interpretation": INTERPRETATION,
        "prior": [alpha, beta],
        "evidence_unit": "response",
        "evidence_count": len(rows),
        "score_share_sum": round(sum(shares), 3),
        "earned_points": sum(row["score"] for row in rows),
        "possible_points": sum(row["max_score"] for row in rows),
        "record_ids": sorted(row["record_id"] for row in rows),
        "node_ids": sorted({row["node_id"] for row in rows}),
        "interval_level": level_width,
        "estimate": None,
        "interval": None,
        "level": "insufficient_evidence",
    }
    if not rows:
        return result
    a, b = alpha + sum(shares), beta + len(shares) - sum(shares)
    tail = (1 - level_width) / 2
    mean = a / (a + b)
    lower, upper = beta_quantile(tail, a, b), beta_quantile(1 - tail, a, b)
    result.update(estimate=round(mean, 3), interval=[round(lower, 3), round(upper, 3)])
    if len(rows) < config["min_evidence"]:
        level = "insufficient_evidence"
    elif lower >= config["mastered_lower"]:
        level = "mastered"
    elif mean >= config["developing_mean"]:
        level = "developing"
    else:
        level = "needs_support"
    result["level"] = level
    return result


def cumulative_rows(usable, student, node, scope, node_dates):
    """Usable rows per indicator from this node and every node assessed no later than it."""
    date = node_dates.get(node)
    nodes = [node] if not date else sorted(
        other for other, other_date in node_dates.items()
        if other == node or (other_date and other_date <= date)
    )
    by_indicator = {}
    for other in nodes:
        for indicator, item_ids in scope[other].items():
            rows = by_indicator.setdefault(indicator, [])
            rows.extend(usable[student, other, item] for item in item_ids if (student, other, item) in usable)
    return by_indicator
