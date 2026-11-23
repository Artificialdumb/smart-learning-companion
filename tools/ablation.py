"""Blinded three-condition comparison for teacher evaluation, and analysis of the returned ratings.

Conditions, built from the same batch so only the information shown differs:
  A  score-rate only: the indicator score rate and a material chosen by score rate alone;
  B  A plus rubric-point evidence: the system finding, cited record / rubric point / step,
     and the evidence-linked activity with its hints;
  C  B plus the follow-up questions (dimensions linked to the missed points) and the
     prerequisite learning path.

``packet`` writes, for a sample of student-node-indicator cases, a teacher packet in which
the three versions of each case appear in random order under neutral labels (甲/乙/丙),
an empty rating sheet, and a separate key file that teachers must not see.
``analyze`` joins returned rating sheets with the key and reports per-condition means,
paired sign tests and rater agreement. It reports what was observed; it does not turn
ratings into claims about diagnostic accuracy or teaching effect.

Usage:
  python -m tools.ablation packet --db outputs/study.sqlite3 --run-id <id> --out outputs/ablation [--per-kind 6] [--seed 1]
  python -m tools.ablation analyze --key outputs/ablation/key.json --ratings rater1.csv rater2.csv
"""

import argparse
import csv
import json
import random
from collections import defaultdict
from math import comb
from pathlib import Path

from app._analysis import index
from app.diagnosis.followup import followup_view
from app.diagnosis.paths import learning_paths
from app.recommendations import eligible_resource, resource_index
from app.storage import Store

CRITERIA = (
    ("evidence", "诊断依据是否充分、可核对（1–5）"),
    ("actionable", "建议是否具体、教师可直接执行（1–5）"),
    ("fit", "建议是否针对该生的实际错误（1–5）"),
)
SCORE_RATE_CUT = 0.6
LABELS = ("甲", "乙", "丙")


def _pct(value):
    return "—" if value is None else f"{value:.0%}"


def condition_a(summary, indicator, catalog, node):
    """Recommendation from the score rate alone, as a plain grade-book tool would do."""
    rate = summary["score_rate"]
    lines = [f"指标：{indicator['description']}", f"本指标得分率：{_pct(rate)}（有效作答 {summary['valid_count']} 题）"]
    if rate is None:
        lines.append("建议：暂无得分，无法判断。")
        return lines
    resources = resource_index(catalog)
    items = index(catalog["items"], "item_id")
    material = next((r for r in resources.values() if r["resource_type"] != "item"
                     and eligible_resource(r, indicator["indicator_id"], node, items)), None)
    material = material or next((r for r in resources.values()
                                 if eligible_resource(r, indicator["indicator_id"], node, items)), None)
    if rate < SCORE_RATE_CUT:
        target = f"使用 {material['resource_id']}（{material['title']}）" if material else "使用本指标材料"
        lines.append(f"建议：得分率低于 {SCORE_RATE_CUT:.0%}，{target}巩固该指标。")
    else:
        lines.append(f"建议：得分率不低于 {SCORE_RATE_CUT:.0%}，可继续后续学习。")
    return lines


def condition_b(summary, activity, records, catalog):
    items = index(catalog["items"], "item_id")
    lines = []
    for finding in summary["findings"]:
        lines.append(f"诊断发现：{finding['summary']}")
        for evidence in finding["evidence"]:
            record = records.get(evidence["record_id"], {})
            item = items.get(record.get("item_id"), {})
            steps = record.get("steps") or []
            cited = "；".join(f"第 {n} 步「{steps[n - 1]}」" for n in evidence.get("step_numbers", []) if n <= len(steps))
            lines.append(f"  证据：{evidence['record_id']}，题目「{item.get('prompt', '')}」，"
                         f"最终作答「{record.get('final_answer', '')}」，评分点 {'、'.join(evidence['rubric_point_ids']) or '—'}"
                         + (f"，{cited}" if cited else ""))
    if activity:
        lines.append(f"建议活动：{activity['reason']}（材料 {activity['resource_id']}）")
        lines += [f"  提示 {i}：{hint}" for i, hint in enumerate(activity["hints"], 1)]
        lines.append(f"  复查条件：{activity['recheck_condition']}")
    else:
        lines.append("建议活动：该指标本次不安排活动。")
    return lines


def condition_c(batch, student, node_id, summary, indicator, reports):
    lines = []
    if any(f["kind"] == "practice_needed" for f in summary["findings"]):
        view = followup_view(batch, student, node_id, indicator["indicator_id"])
        if view["questions"]:
            linked = "；".join(f"{p['rubric_point_id']} {p['criterion']}" for p in view["linked_rubric_points"])
            lines.append(f"错因追问（{len(view['questions'])} 题，优先核查与失分评分点相关的维度：{linked or '—'}）：")
            lines += [f"  {q['dimension_label']}{'（关联失分点）' if q['focus'] else ''}：{q['prompt']}"
                      for q in view["questions"]]
        else:
            lines.append(f"错因追问：{view['unavailable_reason']}")
    path = next((p for p in learning_paths(batch["catalog"], reports, node_id)["paths"]
                 if p["target_indicator_id"] == indicator["indicator_id"]), None)
    if path:
        names = index(batch["catalog"]["indicators"], "indicator_id")
        steps = " → ".join(f"{names[s['indicator_id']]['description']}（{s['action']}）" for s in path["steps"])
        lines.append(f"补学路径：{steps}。{path['note'] or ''}")
    return lines


def cases(batch, plans):
    """Every student-node-indicator with an activity, tagged by activity kind."""
    plan_by_id = {plan["plan_id"]: plan for plan in plans}
    for student, reports in sorted(batch["diagnoses"].items()):
        for node_id, report in sorted(reports.items()):
            plan = plan_by_id.get(f"PLAN-{student}-{node_id}")
            activities = {a["indicator_id"]: a for a in (plan["original_activities"] if plan else [])}
            for summary in report["indicators"]:
                activity = activities.get(summary["indicator_id"])
                if activity:
                    yield activity["kind"], student, node_id, summary, activity, reports


def packet(db, run_id, out, per_kind, seed):
    batch, plans = Store(db).snapshot(run_id)
    catalog = batch["catalog"]
    indicators = index(catalog["indicators"], "indicator_id")
    nodes = index(catalog["nodes"], "node_id")
    rng = random.Random(seed)
    grouped = defaultdict(list)
    for row in cases(batch, plans):
        grouped[row[0]].append(row)
    chosen = [row for kind in sorted(grouped) for row in rng.sample(grouped[kind], min(per_kind, len(grouped[kind])))]
    rng.shuffle(chosen)

    out.mkdir(parents=True, exist_ok=False)
    key, document = {"run_id": run_id, "seed": seed, "cases": {}}, [
        "# 学习建议对照评价材料\n",
        "每个案例给出同一学生、同一测验、同一指标的三种呈现（甲、乙、丙，顺序随机）。",
        "请独立阅读并在评分表中为每个版本打分，不与其他老师讨论，也不要尝试推测哪一版来自哪种方法。\n",
        "评分项：" + "；".join(text for _, text in CRITERIA) + "；另请标注是否存在错误或误导，并可写备注。\n",
    ]
    sheet = [["case_id", "version", *(name for name, _ in CRITERIA), "misleading(是/否)", "note"]]
    for number, (kind, student, node_id, summary, activity, reports) in enumerate(chosen, 1):
        case_id = f"C{number:02d}"
        indicator = indicators[summary["indicator_id"]]
        b = condition_b(summary, activity, batch["records"], catalog)
        versions = {
            "A": condition_a(summary, indicator, catalog, nodes[node_id]),
            "B": [f"指标：{indicator['description']}", *b],
            "C": [f"指标：{indicator['description']}", *b,
                  *condition_c(batch, student, node_id, summary, indicator, reports)],
        }
        order = list(versions)
        rng.shuffle(order)
        key["cases"][case_id] = {"student_id": student, "node_id": node_id, "indicator_id": indicator["indicator_id"],
                                 "kind": kind, "labels": dict(zip(LABELS, order))}
        document.append(f"## 案例 {case_id}（学生 {student} · 测验 {node_id}）\n")
        for label, condition in zip(LABELS, order):
            document.append(f"### 版本{label}\n")
            document += [f"- {line}" if not line.startswith("  ") else f"  - {line.strip()}" for line in versions[condition]]
            document.append("")
            sheet.append([case_id, label, "", "", "", "", ""])
    (out / "评价材料.md").write_text("\n".join(document) + "\n", encoding="utf-8")
    with (out / "评分表.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        csv.writer(stream).writerows(sheet)
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out, len(chosen)


def sign_test(wins, losses):
    """Two-sided exact sign test p-value; ties are dropped."""
    n = wins + losses
    if not n:
        return None
    tail = sum(comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def analyze(key_path, rating_paths):
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    scores = defaultdict(dict)  # (rater, case, criterion) -> {condition: score}
    misleading = defaultdict(lambda: [0, 0])
    for rater, path in enumerate(rating_paths, 1):
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                condition = key["cases"][row["case_id"]]["labels"][row["version"]]
                for name, _ in CRITERIA:
                    if row[name].strip():
                        scores[rater, row["case_id"], name][condition] = int(row[name])
                flag = row["misleading(是/否)"].strip()
                if flag:
                    misleading[condition][0] += flag == "是"
                    misleading[condition][1] += 1
    lines = [f"评分人数 {len(rating_paths)}，案例 {len(key['cases'])} 个。", "",
             "| 评分项 | A 仅得分率 | B +评分点依据 | C +追问与补学 | B 对 A（胜/负，符号检验 p） | C 对 B（胜/负，p） |",
             "|---|---|---|---|---|---|"]
    for name, text in CRITERIA:
        by_condition = defaultdict(list)
        per_case = defaultdict(lambda: defaultdict(list))  # case -> condition -> scores from all raters
        for (_, case, criterion), values in scores.items():
            if criterion != name:
                continue
            for condition, value in values.items():
                by_condition[condition].append(value)
                per_case[case][condition].append(value)
        # The case is the unit of the paired test: raters are averaged within a case, so two
        # teachers rating the same five cases still give five pairs, not ten.
        pairs = {("B", "A"): [0, 0], ("C", "B"): [0, 0]}
        for conditions in per_case.values():
            means = {c: sum(v) / len(v) for c, v in conditions.items()}
            for (high, low), tally in pairs.items():
                if high in means and low in means and means[high] != means[low]:
                    tally[means[high] < means[low]] += 1
        means = [f"{sum(v) / len(v):.2f}（n={len(v)}）" if (v := by_condition[c]) else "—" for c in "ABC"]
        tests = [f"{w}/{l}，p={p:.3f}" if (p := sign_test(w, l)) is not None else "—"
                 for w, l in pairs.values()]
        lines.append(f"| {text} | {' | '.join(means)} | {' | '.join(tests)} |")
    lines.append("")
    lines.append("误导标注比例：" + "；".join(
        f"{c} {m}/{n}" for c in "ABC" for m, n in [misleading.get(c, [0, 0])]))
    if len(rating_paths) > 1:
        agree = total = 0
        for (rater, case, name), values in scores.items():
            if rater != 1:
                continue
            for other in range(2, len(rating_paths) + 1):
                for condition, value in values.items():
                    peer = scores.get((other, case, name), {}).get(condition)
                    if peer is not None:
                        total += 1
                        agree += abs(peer - value) <= 1
        lines.append(f"评分一致性：评分人 1 与其他评分人相差不超过 1 分的比例 {agree}/{total}。")
    lines.append("")
    lines.append("说明：评分反映教师对依据和建议的主观评价，不等于诊断准确率或教学效果。"
                 "样本量小时 p 值不稳定，应同时报告胜负计数。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("packet")
    make.add_argument("--db", type=Path, default=Path("outputs/study.sqlite3"))
    make.add_argument("--run-id", required=True)
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--per-kind", type=int, default=6)
    make.add_argument("--seed", type=int, default=1)
    read = sub.add_parser("analyze")
    read.add_argument("--key", type=Path, required=True)
    read.add_argument("--ratings", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    if args.command == "packet":
        out, count = packet(args.db, args.run_id, args.out, args.per_kind, args.seed)
        print(f"{out}（{count} 个案例）")
    else:
        print(analyze(args.key, args.ratings))


if __name__ == "__main__":
    main()
