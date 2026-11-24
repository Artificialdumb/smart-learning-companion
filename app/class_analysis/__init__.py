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
            "summary": node_summary(summaries),
        }
    return result


def node_summary(summaries, gap_limit=3, miss_limit=5):
    """Group-level digest of one node: largest score-rate gaps and misses shared by both classes.

    Gaps compare the two classes on the same common items; each entry keeps both
    fractions so the difference can be recomputed. A shared miss is a rubric point that
    is a common miss (>= 2 students) in both classes; entries are ranked by the pooled
    miss share, then by the number of students who missed it.
    """
    gaps = []
    for row in summaries:
        if row["comparison_status"] != "comparable":
            continue
        a, b = row["classes"]
        if not (a["max_score_sum"] and b["max_score_sum"]):
            continue
        gap = a["score_sum"] / a["max_score_sum"] - b["score_sum"] / b["max_score_sum"]
        gaps.append({
            "indicator_id": row["indicator_id"],
            "item_count": len(row["item_ids"]),
            "classes": [{key: c[key] for key in ("class_id", "score_sum", "max_score_sum", "covered_students",
                                                 "class_size", "valid_count")} for c in (a, b)],
            "rate_gap": round(gap, 4),
        })
    gaps.sort(key=lambda g: (-abs(g["rate_gap"]), g["indicator_id"]))

    shared = []
    for row in summaries:
        by_point = defaultdict(dict)
        for finding in row["findings"]:
            if finding["kind"] == "common_miss":
                by_point[finding["item_id"], finding["rubric_point_id"]][finding["class_id"]] = finding
        for (item_id, point), per_class in by_point.items():
            if len(per_class) != 2:
                continue
            missed = sum(f["missed_students"] for f in per_class.values())
            scored = sum(f["scored_students"] for f in per_class.values())
            shared.append({
                "indicator_id": row["indicator_id"],
                "item_id": item_id,
                "rubric_point_id": point,
                "criterion": next(iter(per_class.values()))["criterion"],
                "classes": [{"class_id": cls, "missed_students": f["missed_students"],
                             "scored_students": f["scored_students"], "record_ids": f["record_ids"]}
                            for cls, f in sorted(per_class.items())],
                "missed_students": missed,
                "scored_students": scored,
            })
    shared.sort(key=lambda s: (-s["missed_students"] / s["scored_students"], -s["missed_students"],
                               s["item_id"], s["rubric_point_id"]))
    return {"largest_gaps": gaps[:gap_limit], "shared_misses": shared[:miss_limit]}


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
                "criterion": meta["criterion"],
                "missed_students": len(missed),
                "scored_students": len(scored),
                "record_ids": missed,
                "summary": (
                    f"{class_id} 在 {item['item_id']} 的“{meta['criterion']}”评分点，"
                    f"{len(scored)} 名有该评分点成绩的学生中有 {len(missed)} 人失分。"
                ),
            })
    return findings
