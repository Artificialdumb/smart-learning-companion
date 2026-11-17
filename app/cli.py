"""Build a batch from contest CSV or normalized inputs, or export a saved batch."""

import argparse
import csv
import hashlib
import json
import sysconfig
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app._analysis import index
from app.a_pipeline import load_csv_batch
from app.class_analysis import compare_classes
from app.contracts import encode_json, usable_rows, with_run
from app.diagnosis import diagnose_students
from app.diagnosis.paths import learning_paths, prerequisite_graph
from app.diagnosis.probes import PROBE_VERSION
from app.recommendations import generate_plans, resource_index
from app.recommendations.local_model import local_selector
from app.storage import Store

DEFAULT_DB = Path("outputs/study.sqlite3")
ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATION_RULES = "recommendations-1.0"
# Keys that only describe an exported package; a rebuild must not inherit them.
EXPORT_ONLY_KEYS = ("exported_at", "adjustment_versions")


def normalized_batch(source):
    required = ("manifest.json", "catalog.json", "students.json", "responses.jsonl")
    names = [*required, *(name for name in ("quality_report.json", "usable_responses.jsonl")
                          if (source / name).is_file())]
    files = {name: (source / name).read_bytes() for name in names}
    manifest, catalog, students = (json.loads(files[name]) for name in required[:3])
    latest = [json.loads(line) for line in files["responses.jsonl"].splitlines() if line.strip()]
    if "usable_responses.jsonl" in files:
        usable_rows(latest, files["usable_responses.jsonl"])
    quality = json.loads(files["quality_report.json"]) if "quality_report.json" in files else None
    manifest = {
        **{key: value for key, value in manifest.items() if key not in EXPORT_ONLY_KEYS},
        "upstream_source_files": manifest["source_files"],
        "source_files": [{"path": name, "sha256": hashlib.sha256(content).hexdigest()}
                         for name, content in files.items()],
    }
    if quality is not None and quality.get("run_id", manifest["run_id"]) != manifest["run_id"]:
        raise ValueError("质量报告的批次编号与输入清单不一致。")
    return manifest, catalog, students, latest, quality


def quality_for_latest(rows, usable):
    # Normalized input may omit historical records entirely.
    events = {}
    for row in rows:
        events.setdefault(row["event_id"], set()).add(row["scoring_status"])
    counts = Counter(next(iter(status)) if len(status) == 1 else "conflicting"
                     for status in events.values())
    return {
        "raw_rows": None, "event_count": len(events),
        "latest_scoring_status_counts": {**dict.fromkeys(("graded", "pending", "unanswered"), 0), **counts},
        "usable_count": len(usable), "issues": None,
        "note": "输入仅含最新作答，未提供原始行数和质量问题明细。",
    }


def validate_catalog(catalog):
    topics = index(catalog["topics"], "topic_id")
    indicators = index(catalog["indicators"], "indicator_id")
    items = index(catalog["items"], "item_id")
    nodes = index(catalog["nodes"], "node_id")
    resources = resource_index(catalog)
    if not topics or not indicators or not items or not nodes:
        raise ValueError("目录须包含主题、指标、题目和测验节点。")
    for indicator in indicators.values():
        if indicator["topic_id"] not in topics or any(
            ref["resource_id"] not in resources for ref in indicator.get("references", [])
        ):
            raise ValueError(f"指标引用的主题或出处无法定位: {indicator['indicator_id']}")
    for row in [*items.values(), *resources.values()]:
        if not set(row["indicator_ids"]) <= indicators.keys():
            raise ValueError(f"题目或资源引用了未知指标: {row}")
    for resource_id, resource in resources.items():
        if (resource["resource_type"] == "item") != (resource_id in items):
            raise ValueError(f"题目与材料索引不一致: {resource_id}")
    for relation in catalog.get("learning_relations", []):
        if not {relation["from_indicator_id"], relation["to_indicator_id"]} <= indicators.keys():
            raise ValueError("学习关系引用了未知指标。")
    prerequisite_graph(catalog)
    return {**catalog, "resources": list(resources.values())}


def build(source, db, *, reviews_path=None):
    if (source / "manifest.json").is_file():
        if reviews_path is not None:
            raise ValueError("复核文件须与原始赛题资料包一起使用。")
        input_manifest, catalog, students, rows, quality = normalized_batch(source)
        usable = usable_rows(rows)
    else:
        input_manifest, catalog, imported = load_csv_batch(source, reviews_path=reviews_path)
        students, rows = imported.students, imported.latest_responses
        usable, quality = imported.usable_responses, imported.quality_report
    catalog = validate_catalog(catalog)
    records = index(rows, "record_id")
    if quality is None:
        quality = quality_for_latest(rows, usable)
    if quality["usable_count"] != len(usable):
        raise ValueError("质量报告与有效作答数量不一致。")

    diagnoses = diagnose_students(catalog, students, rows, usable)
    comparisons = compare_classes(catalog, students, usable)
    selector = local_selector()
    by_student = generate_plans(catalog, diagnoses, records, select_resource=selector)
    plans = index((plan for nodes in by_student.values() for plan in nodes.values()), "plan_id")

    run_id = uuid4().hex
    manifest = with_run(run_id, {
        **input_manifest, "input_run_id": input_manifest["run_id"],
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recommendation_rules_version": RECOMMENDATION_RULES,
        "followup_probe_version": PROBE_VERSION,
        "recommendation_mode": "local_model_with_rule_fallback" if selector else "rules",
    })
    Store(db).publish({
        "manifest": manifest, "catalog": catalog, "students": index(students, "student_id"),
        "records": records, "quality_report": with_run(run_id, quality),
        "diagnoses": diagnoses, "comparisons": comparisons, "plans": plans,
    })
    return run_id


def case_examples(diagnoses, plans):
    cases = []
    for kind, preferred, focus in (
        ("practice_needed", ("D01", "N01"), "T01I2"),
        ("strength", ("D14", "N02"), "T03I2"),
        ("observe_more", ("D17", "N02"), "T03I2"),
    ):
        chosen = next((
            (plan, activity) for plan in plans
            if (plan["student_id"], plan["node_id"]) == preferred
            for activity in plan["effective_activities"]
            if activity["kind"] == kind and activity["indicator_id"] == focus
        ), None)
        if chosen is None:
            chosen = next(((plan, a) for plan in plans for a in plan["effective_activities"]
                           if a["kind"] == kind), None)
        if chosen is None:
            continue
        plan, activity = chosen
        student, node_id = plan["student_id"], plan["node_id"]
        report = diagnoses.get(student, {}).get(node_id, {"indicators": []})
        diagnosis = next((i for i in report["indicators"] if i["indicator_id"] == activity["indicator_id"]), None)
        if diagnosis is None:
            raise ValueError(f"案例活动找不到对应诊断: {plan['plan_id']} {activity['indicator_id']}")
        cases.append(with_run(plan["run_id"], {
            "student_id": student, "node_id": node_id, "kind": kind,
            "diagnosis": diagnosis,
            "activity": activity, "adjustment_version": plan["adjustment_version"],
        }))
    return cases


def export(db, run_id, out):
    batch, plans = Store(db).snapshot(run_id)
    if out.exists():
        raise FileExistsError(f"导出目录已存在: {out}")
    catalog = batch["catalog"]
    diagnoses = batch["diagnoses"]
    manifest = {
        **batch["manifest"],
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "adjustment_versions": {p["plan_id"]: p["adjustment_version"] for p in plans},
    }
    outputs = {
        "manifest.json": manifest,
        "catalog.json": catalog,
        "learning_requirements.json": with_run(run_id, {
            "topics": catalog["topics"], "indicators": catalog["indicators"],
            "learning_relations": catalog.get("learning_relations", []),
        }),
        "students.json": list(batch["students"].values()),
        "quality_report.json": batch["quality_report"],
        "diagnosis.json": [with_run(run_id, report) for nodes in diagnoses.values() for report in nodes.values()],
        "class_comparison.json": [with_run(run_id, report) for report in batch["comparisons"].values()],
        "recommendations.json": plans,
        "followups.json": batch["followups"],
        "learning_paths.json": [
            with_run(run_id, learning_paths(catalog, reports, node_id))
            for reports in diagnoses.values() for node_id in reports
        ],
        "cases.json": case_examples(diagnoses, plans),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    docs = ROOT / "docs"
    if not (docs / "contracts.md").is_file():
        docs = Path(sysconfig.get_path("data")) / "share" / "smart-learning-companion"
    with TemporaryDirectory(dir=out.parent) as tmp:
        staging = Path(tmp) / "batch"
        staging.mkdir()
        for filename, data in outputs.items():
            (staging / filename).write_text(encode_json(data, indent=2) + "\n", encoding="utf-8")
        with (staging / "responses.jsonl").open("w", encoding="utf-8") as stream:
            for row in batch["records"].values():
                print(encode_json(row), file=stream)
        for name in ("contracts.md", "integration.md"):
            (staging / name).write_bytes((docs / name).read_bytes())
        (staging / "README.md").write_text(
            "# 智慧学伴成果包\n\n"
            "manifest.json 标识批次与教师调整版本。cases.json 汇集可用的代表性案例。\n"
            "按 record_id 在 responses.jsonl 回查作答，按题号或材料编号在 catalog.json 回查出处。\n"
            "contracts.md 提供字段说明，integration.md 提供构建、复核和展示步骤。\n"
            "用 python -m app.cli build --source <成果包目录> 可从标准化输入复算初始分析。"
            "教师调整的快照保存在 recommendations.json。"
            "followups.json 保存各指标最近一次追问及反馈，learning_paths.json 保存前置知识补学路径。"
            "重建只复算初始分析，不导入教师调整和补充追问。\n",
            encoding="utf-8",
        )
        staging.rename(out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    build_command = subcommands.add_parser("build")
    build_command.add_argument("--source", required=True, type=Path)
    build_command.add_argument("--reviews", type=Path, help="应用于原始作答 CSV 的复核决定 JSON")
    export_command = subcommands.add_parser("export")
    export_command.add_argument("--run-id", required=True)
    export_command.add_argument("--out", required=True, type=Path)
    for command in (build_command, export_command):
        command.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build(args.source, args.db, reviews_path=args.reviews))
        else:
            print(export(args.db, args.run_id, args.out))
    except (OSError, KeyError, TypeError, ValueError, csv.Error) as error:
        parser.exit(1, f"操作失败：{error}\n")


if __name__ == "__main__":
    main()
