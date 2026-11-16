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


def usable_by_cell(responses, students, items, allowed):
    limits = {
        item: {p: v["max_score"] for p, v in rubric_points(meta).items()}
        for item, meta in items.items()
    }
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


def totals(rows):
    score_sum = sum(row["score"] for row in rows)
    max_score_sum = sum(row["max_score"] for row in rows)
    return {
        "valid_count": len(rows),
        "score_sum": score_sum,
        "max_score_sum": max_score_sum,
        "score_rate": score_sum / max_score_sum if max_score_sum else None,
    }
