from collections import Counter, defaultdict

from .._analysis import assessment_scope, index, rubric_points, totals, usable_by_cell


def compare_classes(catalog, students, usable_responses):
    """Return two-class comparisons indexed by node_id."""
    roster = index(students, "student_id")
    sizes = Counter(row["class_id"] for row in roster.values())
    class_ids = sorted(sizes)
    if len(class_ids) != 2:
        raise ValueError("两班比较要求完整名册包含恰好两个班级。")
    items, allowed, scope = assessment_scope(catalog)
    usable = usable_by_cell(usable_responses, roster, items, allowed)
    by_item = defaultdict(list)
    for (student, node, item), row in usable.items():
        by_item[node, roster[student]["class_id"], item].append(row)

    result = {}
    for node, indicators in sorted(scope.items()):
        summaries = []
        for indicator, eligible in indicators.items():
            shared = [
                item for item in eligible
                if all((node, cls, item) in by_item for cls in class_ids)
            ]
            classes, findings = [], []
            for cls in class_ids:
                rows = [r for item in shared for r in by_item[node, cls, item]]
                covered = len({r["student_id"] for r in rows})
                classes.append({
                    "class_id": cls,
                    "class_size": sizes[cls],
                    "covered_students": covered,
                    "coverage_rate": covered / sizes[cls],
                    **totals(rows),
                })
                for item_id in shared:
                    findings.extend(common_misses(cls, items[item_id], by_item[node, cls, item_id]))
            if shared:
                status = "comparable"
                a, b = classes
                # Cross-multiply so a displayed difference never depends on float rounding.
                if a["score_sum"] * b["max_score_sum"] != b["score_sum"] * a["max_score_sum"]:
                    scores = "，".join(
                        f"{c['class_id']} 得 {c['score_sum']}/{c['max_score_sum']} 分"
                        f"（覆盖 {c['covered_students']}/{c['class_size']} 人，{c['valid_count']} 条作答）"
                        for c in classes
                    )
                    findings.insert(0, {"kind": "observed_difference", "summary": f"在共同有效题范围内，{scores}。"})
            else:
                status = "no_common_items" if eligible else "not_assessed"
                reason = "两班在该指标下无共同有效题，无法比较得分。" if eligible else "本节点未测该指标。"
                findings.append({"kind": "not_comparable", "summary": reason})
            summaries.append({
                "indicator_id": indicator,
                "eligible_item_ids": eligible,
                "item_ids": shared,
                "comparison_status": status,
                "classes": classes,
                "findings": findings,
            })
        result[node] = {
            "node_id": node,
            "comparison_item_ids": sorted({q for row in summaries for q in row["item_ids"]}),
            "indicators": summaries,
        }
    return result


def common_misses(class_id, item, rows):
    findings = []
    for point, meta in rubric_points(item).items():
        scored = [row for row in rows if point in row["rubric_scores"]]
        missed = sorted(
            row["record_id"] for row in scored if row["rubric_scores"][point] < meta["max_score"]
        )
        if len(missed) >= 2:
            findings.append({
                "kind": "common_miss",
                "class_id": class_id,
                "item_id": item["item_id"],
                "rubric_point_id": point,
                "missed_students": len(missed),
                "scored_students": len(scored),
                "record_ids": missed,
                "summary": (
                    f"{class_id} 在 {item['item_id']} 的“{meta['criterion']}”评分点，"
                    f"{len(scored)} 名有该评分点成绩的学生中有 {len(missed)} 人失分。"
                ),
            })
    return findings
