"""Prepare local development input from the supplied contest CSV files."""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from app._analysis import index, rubric_points

TABLES = ("课程要求", "题目与材料", "模拟学生", "测验节点", "作答记录", "字段说明")
STATUS = {"已评分": "graded", "待评分": "pending", "未作答": "unanswered"}
RULES = "B-dev-fixture-v1.0"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"缺少表头或存在重复列: {path}")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"存在与表头不匹配的行: {path}")
        return rows


def make_catalog(course, materials, node_rows):
    topics, indicators, items, resources, nodes = {}, [], [], [], []
    for row in course:
        topic_id = row["主题编号"]
        topics[topic_id] = {"topic_id": topic_id, "title": row["主题"], "goal": row["主题目标"]}
        indicators.append({
            "indicator_id": row["指标编号"],
            "topic_id": topic_id,
            "description": row["观察指标"],
            "references": [{
                "resource_id": "课程标准_2022",
                "locator": row["课标文件页／正文页"],
            }],
        })
    resources.append({
        "resource_id": "课程标准_2022", "resource_type": "curriculum_standard",
        "title": "义务教育数学课程标准（2022年版）",
        "indicator_ids": [r["indicator_id"] for r in indicators],
        "source_locator": "5_课程标准及相关教学资源/课程标准_2022.pdf",
    })
    for row in materials:
        item_id = row["材料编号"]
        indicator_ids = row["指标编号"].split("、") if row["指标编号"] else []
        kind = row["材料类型"]
        resources.append({
            "resource_id": item_id,
            "resource_type": {"题目": "item", "学习卡": "learning_card", "教材": "textbook"}[kind],
            "title": row["题干或内容"],
            "indicator_ids": indicator_ids,
            "source_locator": row["来源或资料文件"],
        })
        if kind == "题目":
            points = []
            for line in row["评分点"].splitlines():
                point, content = line.split(maxsplit=1)
                criterion, maximum = content.rsplit(maxsplit=1)
                points.append({
                    "rubric_point_id": point, "criterion": criterion,
                    "max_score": int(maximum.removesuffix("分")),
                })
            item = {
                "item_id": item_id, "indicator_ids": indicator_ids, "topic_id": row["主题编号"],
                "item_type": row["题型"],
                "prompt": row["题干或内容"], "options": row["选项"].splitlines(),
                "max_score": int(row["满分"]), "rubric_points": points,
                "reference_answer": row["参考答案"], "reference_explanation": row["参考解析"],
            }
            if not points or sum(p["max_score"] for p in rubric_points(item).values()) != item["max_score"]:
                raise ValueError(f"题库评分点不一致: {item_id}")
            items.append(item)
    for row in node_rows:
        nodes.append({
            "node_id": row["节点编号"], "assessment_date": row["模拟测验日期"],
            "title": row["说明"], "item_ids": row["可用题目编号"].split("、"),
        })
    return {
        "topics": list(topics.values()), "indicators": indicators, "items": items,
        "resources": resources, "nodes": nodes, "learning_relations": [],
    }


def to_int(value):
    try:
        return int(value)
    except ValueError:
        return None


def parse_rubric(text):
    pairs = {}
    for pair in text.split("；") if text else []:
        point, _, value = pair.partition("=")
        if not point or to_int(value) is None or point in pairs:
            return None
        pairs[point] = int(value)
    return pairs


def make_responses(rows, catalog, students):
    roster = index(students, "student_id")
    nodes = index(catalog["nodes"], "node_id")
    items = index(catalog["items"], "item_id")
    events, originals, issues = defaultdict(list), {}, []

    def issue(raw, code, field=None, disposition="exclude"):
        issues.append({
            "record_id": raw["记录编号"], "event_id": raw["作答事件编号"],
            "code": code, "severity": "error" if disposition == "exclude" else "info",
            "disposition": disposition, "raw_value": raw[field] if field else None,
        })

    for raw in rows:
        record_id, event_id = raw["记录编号"], raw["作答事件编号"]
        revision = int(raw["修订版本"])
        if not record_id or not event_id or revision < 1:
            raise ValueError("记录编号、作答事件编号或修订版本不可用")
        if record_id in originals:
            if originals[record_id] != raw:
                raise ValueError(f"同一记录编号存在不同内容: {record_id}")
            issue(raw, "duplicate_import", disposition="deduplicate")
            continue
        originals[record_id] = raw
        events[event_id].append((revision, raw))

    latest, counts = [], Counter()
    for event_id, versions in sorted(events.items()):
        revision = max(v for v, _ in versions)
        candidates = {}
        for version, raw in sorted(versions, key=lambda pair: pair[1]["记录编号"]):
            if version < revision:
                issue(raw, "superseded_revision", "修订版本", "superseded")
                continue
            signature = tuple((key, value) for key, value in raw.items() if key != "记录编号")
            if signature in candidates:
                issue(raw, "duplicate_import", disposition="deduplicate")
            else:
                candidates[signature] = raw
        conflict = len(candidates) > 1
        statuses = {STATUS.get(raw["评分状态"], "unknown") for raw in candidates.values()}
        counts[next(iter(statuses)) if len(statuses) == 1 else "conflicting"] += 1
        for raw in candidates.values():
            student, node_id, item_id = (raw[k] for k in ("学生编号", "节点编号", "材料编号"))
            item, node = items.get(item_id), nodes.get(node_id)
            invalid = []

            def check(ok, code, field):
                if not ok:
                    invalid.append(code)
                    issue(raw, code, field)

            check(not conflict, "conflicting_latest_revision", "修订版本")
            check(student in roster, "unknown_student", "学生编号")
            check(node is not None, "unknown_node", "节点编号")
            check(item is not None, "unknown_item", "材料编号")
            check(event_id == f"{student}-{node_id}-{item_id}", "event_key_mismatch", "作答事件编号")
            if item is not None and node is not None:
                check(item_id in node["item_ids"], "item_outside_node", "材料编号")
                check(raw["主题编号"] == item["topic_id"], "topic_mismatch", "主题编号")
            try:
                date = datetime.fromisoformat(raw["模拟提交时间"]).date().isoformat()
            except ValueError:
                issue(raw, "invalid_submission_time", "模拟提交时间", "audit")
            else:
                if node and date != node["assessment_date"]:
                    issue(raw, "date_differs_from_assessment", "模拟提交时间", "audit")

            status = STATUS.get(raw["评分状态"], "unknown")
            score, maximum = to_int(raw["得分"]), to_int(raw["满分"])
            awards = parse_rubric(raw["评分点得分"])
            check(status != "unknown", "unknown_scoring_status", "评分状态")
            check(maximum is not None and maximum > 0 and (
                item is None or maximum == item["max_score"]
            ), "max_score_mismatch", "满分")
            if status == "graded":
                check(score is not None and maximum is not None and 0 <= score <= maximum,
                      "score_out_of_range", "得分")
                limits = {p: meta["max_score"] for p, meta in rubric_points(item).items()} if item else {}
                check(awards is not None and awards.keys() == limits.keys() and all(
                    0 <= value <= limits[p] for p, value in awards.items()
                ), "invalid_rubric_scores", "评分点得分")
                if score is not None and awards is not None:
                    check(sum(awards.values()) == score, "rubric_total_mismatch", "得分")
            elif status in ("pending", "unanswered"):
                check(not raw["得分"] and not raw["评分点得分"], "unexpected_ungraded_score", "得分")

            latest.append({
                "record_id": raw["记录编号"], "event_id": event_id, "revision": revision,
                "student_id": student, "node_id": node_id, "item_id": item_id,
                "scoring_status": status, "validation_status": "needs_review" if invalid else "valid",
                "score": score, "max_score": maximum, "final_answer": raw["学生最终作答"] or None,
                "steps": [
                    re.sub(r"^\d+[.．、]\s*", "", s.strip())
                    for s in raw["解答过程"].splitlines() if s.strip()
                ],
                "rubric_scores": awards or {},
            })
    usable_count = sum(r["scoring_status"] == "graded" and r["validation_status"] == "valid" for r in latest)
    quality = {
        "raw_rows": len(rows), "event_count": len(events),
        "latest_scoring_status_counts": {
            **dict.fromkeys(("graded", "pending", "unanswered"), 0), **counts,
        },
        "usable_count": usable_count, "issues": issues,
    }
    return latest, quality


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare(source, out):
    base = Path("4_赛题数据/模拟学情数据")
    paths = {name: base / f"{name}.csv" for name in TABLES}
    files = [
        {"path": path.as_posix(), "sha256": hashlib.sha256((source / path).read_bytes()).hexdigest()}
        for path in paths.values()
    ]
    catalog = make_catalog(*(read_csv(source / paths[key]) for key in ("课程要求", "题目与材料", "测验节点")))
    students = [
        {"student_id": r["学生编号"], "class_id": r["模拟班级编号"], "grade": int(r["年级"])}
        for r in read_csv(source / paths["模拟学生"])
    ]
    latest, quality = make_responses(read_csv(source / paths["作答记录"]), catalog, students)
    fingerprint = hashlib.sha256(json.dumps([RULES, files], ensure_ascii=False).encode()).hexdigest()
    run_id = f"dev-{fingerprint[:12]}"
    manifest = {
        "run_id": run_id, "schema_version": "1.0",
        "source_files": files, "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "rules_version": RULES,
    }
    out.mkdir()
    for name, value in (
        ("manifest", manifest), ("catalog", catalog), ("students", students),
        ("quality_report", {"run_id": run_id, **quality}),
    ):
        write_json(out / f"{name}.json", value)
    with (out / "responses.jsonl").open("w", encoding="utf-8") as stream:
        for row in latest:
            print(json.dumps(row, ensure_ascii=False, allow_nan=False), file=stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.out)
