"""Generate B outputs from one batch of normalized A inputs."""
import argparse
import json
from pathlib import Path

from app.class_analysis import compare_classes
from app.contracts import usable_rows
from app.diagnosis import diagnose_students


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def build(source, out):
    run_id = read_json(source / "manifest.json")["run_id"]
    catalog = read_json(source / "catalog.json")
    roster = read_json(source / "students.json")
    with (source / "responses.jsonl").open(encoding="utf-8") as stream:
        latest = [json.loads(line) for line in stream if line.strip()]
    usable_file = source / "usable_responses.jsonl"
    usable = usable_rows(latest, usable_file.read_bytes() if usable_file.is_file() else None)
    diagnostics = diagnose_students(catalog, roster, latest, usable)
    comparisons = compare_classes(catalog, roster, usable)
    outputs = {
        "diagnosis.json": [
            {"run_id": run_id, **report}
            for nodes in diagnostics.values() for report in nodes.values()
        ],
        "class_comparison.json": [{"run_id": run_id, **report} for report in comparisons.values()],
    }
    out.mkdir(parents=True)
    for name, rows in outputs.items():
        (out / name).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.input, args.out)
