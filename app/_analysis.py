from collections.abc import Mapping


def index(rows, field):
    rows = rows.values() if isinstance(rows, Mapping) else rows
    indexed = {}
    for row in rows:
        key = row[field]
        if key in indexed:
            raise ValueError(f"重复的 {field}: {key}")
        indexed[key] = row
    return indexed


def assessment_scope(catalog):
    items = index(catalog["items"], "item_id")
    indicators = index(catalog["indicators"], "indicator_id")
    nodes = index(catalog["nodes"], "node_id")
    allowed = {node: set(data["item_ids"]) for node, data in nodes.items()}
    scope = {}
    for node, item_ids in allowed.items():
        by_indicator = {indicator: [] for indicator in sorted(indicators)}
        for item_id in sorted(item_ids):
            for indicator in set(items[item_id]["indicator_ids"]):
                by_indicator[indicator].append(item_id)
        scope[node] = by_indicator
    return items, allowed, scope


def cell(row):
    return row["student_id"], row["node_id"], row["item_id"]


def validate_latest_response(row, students, items, allowed):
    record_id, event_id, revision = (row[key] for key in ("record_id", "event_id", "revision"))
    student, node, item = cell(row)
    if (not isinstance(record_id, str) or not record_id.strip()
            or not isinstance(event_id, str) or not event_id.strip()
            or type(revision) is not int or revision < 1
            or any(not isinstance(value, str) for value in (student, node, item))):
        raise ValueError(f"作答身份或修订版本不符合契约: {record_id}")
    if (not isinstance(row["steps"], list) or any(not isinstance(step, str) for step in row["steps"])
            or (row["final_answer"] is not None and not isinstance(row["final_answer"], str))
            or not isinstance(row["rubric_scores"], dict)):
        raise ValueError(f"作答内容不符合契约: {record_id}")
    status = row["validation_status"]
    if status == "needs_review":
        return
    if (status != "valid" or row["scoring_status"] not in ("graded", "pending", "unanswered")
            or event_id != f"{student}-{node}-{item}"
            or student not in students or item not in allowed.get(node, ())
            or ("class_id" in row and row["class_id"] != students[student]["class_id"])):
        raise ValueError(f"有效作答的身份、范围或状态不符合契约: {record_id}")
    if type(row["max_score"]) is not int or row["max_score"] != items[item]["max_score"]:
        raise ValueError(f"作答满分与题目不一致: {record_id}")
    if row["scoring_status"] != "graded" and (row["score"] is not None or row["rubric_scores"]):
        raise ValueError(f"未评分作答不能带有成绩: {record_id}")


def usable_by_cell(responses, students, items, allowed):
    limits = {item: rubric_limits(meta) for item, meta in items.items()}
    valid = {}
    for row in index(responses, "record_id").values():
        student, node, item = cell(row)
        if student not in students or item not in allowed.get(node, ()):
            raise ValueError(f"有效作答的学生、节点或题号超出范围: {row['record_id']}")
        score, maximum = row["score"], row["max_score"]
        if (
            row["scoring_status"] != "graded"
            or row["validation_status"] != "valid"
            or type(score) is not int
            or type(maximum) is not int
            or not 0 <= score <= maximum
            or maximum <= 0
            or maximum != items[item]["max_score"]
        ):
            raise ValueError(f"有效作答的状态或分数不符合契约: {row['record_id']}")
        awards = row["rubric_scores"]
        if (
            awards.keys() != limits[item].keys()
            or any(type(value) is not int or not 0 <= value <= limits[item][p] for p, value in awards.items())
            or sum(awards.values()) != score
        ):
            raise ValueError(f"有效作答的评分点不符合契约: {row['record_id']}")
        key = (student, node, item)
        if key in valid:
            raise ValueError(f"同一学生在同节点同题存在多条有效作答: {key}")
        valid[key] = row
    return valid


def rubric_points(item):
    return index(item["rubric_points"], "rubric_point_id")


def rubric_limits(item):
    limits = {point: row["max_score"] for point, row in rubric_points(item).items()}
    maximum = item["max_score"]
    if (not limits or type(maximum) is not int or maximum <= 0
            or any(type(value) is not int or value <= 0 for value in limits.values())
            or sum(limits.values()) != maximum):
        raise ValueError(f"{item['item_id']}: 评分点分值与题目满分不一致或分值无效")
    return limits


def totals(rows):
    score_sum = sum(row["score"] for row in rows)
    max_score_sum = sum(row["max_score"] for row in rows)
    return {
        "valid_count": len(rows),
        "score_sum": score_sum,
        "max_score_sum": max_score_sum,
        "score_rate": score_sum / max_score_sum if max_score_sum else None,
    }
