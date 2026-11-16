import re
import unicodedata
from collections import defaultdict

from .._analysis import assessment_scope, cell, index, rubric_points, totals, usable_by_cell


def diagnose_students(catalog, students, latest_responses, usable_responses):
    """Return diagnostics indexed by student_id and then by node_id."""
    roster = index(students, "student_id")
    items, allowed, scope = assessment_scope(catalog)
    usable = usable_by_cell(usable_responses, roster, items, allowed)
    latest = defaultdict(list)
    for row in index(latest_responses, "record_id").values():
        student, node, item = cell(row)
        if student in roster and item in allowed.get(node, ()):
            latest[student, node, item].append(row)

    statuses = {}
    for key in latest.keys() | usable.keys():
        versions = latest.get(key, [])
        needs_review = any(r["validation_status"] == "needs_review" for r in versions)
        if needs_review:
            statuses[key] = "review_count"
        elif len(versions) != 1:
            raise ValueError(f"最新作答缺失或未归并: {key}")
        else:
            row = versions[0]
            if row["validation_status"] != "valid":
                raise ValueError(f"未知校验状态: {row['record_id']}")
            statuses[key] = {
                "graded": "valid_count",
                "pending": "pending_count",
                "unanswered": "unanswered_count",
            }[row["scoring_status"]]
        if (statuses[key] == "valid_count") != (key in usable):
            raise ValueError(f"最新作答与有效视图的状态不一致: {key}")
        if key in usable:
            fields = ("record_id", "event_id", "revision", "score", "max_score",
                      "final_answer", "steps", "rubric_scores")
            if any(usable[key][name] != versions[0][name] for name in fields):
                raise ValueError(f"最新作答与有效视图的内容不一致: {key}")

    result = {}
    for student in sorted(roster):
        result[student] = {}
        for node, indicators in sorted(scope.items()):
            summaries = []
            for indicator, item_ids in indicators.items():
                coverage = dict.fromkeys(
                    ("valid_count", "pending_count", "unanswered_count",
                     "review_count", "missing_record_count"),
                    0,
                )
                rows = []
                for item_id in item_ids:
                    key = (student, node, item_id)
                    coverage[statuses.get(key, "missing_record_count")] += 1
                    if key in usable:
                        rows.append(usable[key])
                findings = evidence_findings(rows, items, coverage, len(item_ids))
                for i, finding in enumerate(findings, 1):
                    finding["finding_id"] = f"F-{student}-{node}-{indicator}-{i:02d}"
                summaries.append({
                    "indicator_id": indicator,
                    "eligible_item_count": len(item_ids),
                    "eligible_item_ids": item_ids,
                    **coverage,
                    **totals(rows),
                    "evidence_status": (
                        "supported" if rows else "insufficient" if item_ids else "not_assessed"
                    ),
                    "findings": findings,
                })
            result[student][node] = {"student_id": student, "node_id": node, "indicators": summaries}
    return result


def evidence_findings(rows, items, coverage, eligible_count):
    if not eligible_count:
        return []
    if not rows:
        return [{
            "kind": "observe_more",
            "summary": (
                f"已测但无有效作答。范围内 {eligible_count} 题中"
                f"待评分 {coverage['pending_count']} 题、未作答 {coverage['unanswered_count']} 题、"
                f"待复核 {coverage['review_count']} 题、无记录 {coverage['missing_record_count']} 题。"
                "现有记录不足以判断表现。"
            ),
            "evidence": [],
        }]

    findings, strengths, strength_evidence = [], [], []
    for row in rows:
        item = items[row["item_id"]]
        points = rubric_points(item)
        awards = row["rubric_scores"]
        passed = [p for p, meta in points.items() if awards.get(p) == meta["max_score"]]
        missed = [p for p, meta in points.items() if p in awards and awards[p] < meta["max_score"]]
        score_text = f"{row['item_id']} 得 {row['score']}/{row['max_score']} 分"
        if row["score"] < row["max_score"]:
            evidence = {"record_id": row["record_id"], "rubric_point_ids": missed}
            summary = score_text + "。"
            mismatch = result_sign_mismatch(row, item, points, missed, passed)
            if mismatch:
                line, final = mismatch
                summary += f"化简过程最后一行写为 {line}，最终填写为 {final}，两处符号不一致。"
                evidence["step_numbers"] = [len(row["steps"])]
            if missed:
                details = "、".join(
                    f"{points[p]['criterion']}（{awards[p]}/{points[p]['max_score']}）"
                    for p in missed
                )
                summary += f"本次失分评分点为{details}。"
            findings.append({"kind": "practice_needed", "summary": summary, "evidence": [evidence]})

        if row["score"] == row["max_score"] or passed:
            observations = "、".join(points[p]["criterion"] for p in passed)
            strengths.append(score_text + (f"（评分记录支持{observations}）" if observations else ""))
            strength_evidence.append({"record_id": row["record_id"], "rubric_point_ids": passed})

    if strengths:
        prefix = f"在 {len(strengths)} 道有效作答中，" if len(strengths) > 1 else "本次作答中，"
        findings.append({
            "kind": "strength",
            "summary": prefix + "；".join(strengths) + "。",
            "evidence": strength_evidence,
        })
    return findings


def result_sign_mismatch(row, item, points, missed, passed):
    # shortcut: 仅对有评分点佐证的简单单字母整式比较逐项符号，扩展题型前增加等价性测试。
    steps = row["steps"]
    if len(missed) != 1 or not steps or not passed:
        return None
    if len(passed) != len(points) - 1 or "结果" not in points[missed[0]]["criterion"]:
        return None

    def normalize(value):
        value = unicodedata.normalize("NFKC", value or "").replace("−", "-")
        return re.sub(r"\s+", "", value).strip("。.")

    last = normalize(re.sub(r"^\s*\d+[.．、]\s*", "", steps[-1]))
    final = normalize(row["final_answer"]).removeprefix("+")
    model = r"[+-]?\d*[A-Za-z](?:[+-]\d*[A-Za-z])+"
    if not last.startswith("="):
        return None
    line = last[1:].removeprefix("+")
    if line != normalize(item.get("reference_answer")).removeprefix("+"):
        return None
    if not all(re.fullmatch(model, value) for value in (line, final)):
        return None
    if line != final and re.split(r"[+-]", line.lstrip("+-")) == re.split(r"[+-]", final.lstrip("+-")):
        return line, final
    return None
