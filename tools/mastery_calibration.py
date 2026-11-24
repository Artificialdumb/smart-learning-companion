"""Simulate how the evidence unit affects mastery-interval coverage.

Generative model used in this simulation:
- each student has a true score share p ~ Uniform(0.05, 0.95) on one indicator;
- each response is one item with k rubric points; the item is "understood" with
  probability p, and then each point is earned with probability 1 - slip, otherwise
  each point is earned with probability guess. Points within an item are therefore
  correlated through the shared item outcome, as in real rubrics.
- the target is the student's expected score share on such items:
  p * (1 - slip) + (1 - p) * guess.

For each weighting we report how often the 90% interval contains the target and the
mean interval width. Scale invariance (1/2 vs 10/20) is checked separately in the tests.

Usage: python -m tools.mastery_calibration [--students 4000] [--seed 7]
"""

import argparse
import random

from app.diagnosis.mastery import beta_quantile

SLIP, GUESS = 0.1, 0.15


def interval(successes, trials, level=0.9):
    a, b = 1 + successes, 1 + trials - successes
    tail = (1 - level) / 2
    return beta_quantile(tail, a, b), beta_quantile(1 - tail, a, b)


def simulate(students, responses, points, seed):
    rng = random.Random(seed)
    stats = {"per_point": [0, 0.0], "per_response": [0, 0.0]}
    for _ in range(students):
        p = rng.uniform(0.05, 0.95)
        target = p * (1 - SLIP) + (1 - p) * GUESS
        earned_points, shares = 0, 0.0
        for _ in range(responses):
            chance = (1 - SLIP) if rng.random() < p else GUESS
            earned = sum(rng.random() < chance for _ in range(points))
            earned_points += earned
            shares += earned / points
        for name, (successes, trials) in {
            "per_point": (earned_points, responses * points),
            "per_response": (shares, responses),
        }.items():
            low, high = interval(successes, trials)
            stats[name][0] += low <= target <= high
            stats[name][1] += high - low
    return {name: (hits / students, width / students) for name, (hits, width) in stats.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--students", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    print("| 每生作答数 | 每题评分点 | 按评分点计：覆盖率 / 平均宽度 | 按作答计：覆盖率 / 平均宽度 |")
    print("|---|---|---|---|")
    for responses in (1, 3, 6):
        for points in (2, 4, 10):
            result = simulate(args.students, responses, points, args.seed)
            cells = [f"{cover:.1%} / {width:.2f}" for cover, width in (result["per_point"], result["per_response"])]
            print(f"| {responses} | {points} | {cells[0]} | {cells[1]} |")


if __name__ == "__main__":
    main()
