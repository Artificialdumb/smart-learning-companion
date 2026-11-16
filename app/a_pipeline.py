import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app.catalog import build_catalog
from app.csv_input import DATA_PATH
from app.ingestion import ingest


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _write_jsonl(path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def load_csv_batch(source_dir, *, reviews_path=None):
    """Load the official CSV bundle with a manifest for each consumer."""
    source_dir = Path(source_dir)
    catalog = build_catalog(source_dir)
    data = ingest(source_dir, catalog, reviews_path=reviews_path)

    source_files = {DATA_PATH / name for name in (
        '课程要求.csv', '题目与材料.csv', '模拟学生.csv', '测验节点.csv', '作答记录.csv', '字段说明.csv',
    )}
    source_files.update(Path(resource['source_locator']['file']) for resource in catalog['resources']
                        if 'file' in resource['source_locator'])
    manifest = {
        'run_id': uuid4().hex, 'schema_version': '1.1', 'rules_version': 'a-2',
        'built_at': datetime.now(timezone.utc).isoformat(),
        'source_files': [
            {'path': path.as_posix(), 'sha256': data.quality_report['response_source_sha256']
             if path == DATA_PATH / '作答记录.csv' else hashlib.sha256((source_dir / path).read_bytes()).hexdigest()}
            for path in sorted(source_files) if (source_dir / path).is_file()
        ],
        'review_input': data.quality_report['review_input'],
    }
    return manifest, catalog, data


def build_snapshot(source_dir, output_dir, *, reviews_path=None):
    """Build A's complete exchange files before publishing the batch directory."""
    manifest, catalog, data = load_csv_batch(source_dir, reviews_path=reviews_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / manifest['run_id']
    with TemporaryDirectory(prefix='.building-', dir=output_dir) as temporary:
        staging = Path(temporary) / 'snapshot'
        staging.mkdir()
        _write_json(staging / 'manifest.json', manifest)
        _write_json(staging / 'catalog.json', catalog)
        _write_json(staging / 'students.json', data.students)
        _write_json(staging / 'quality_report.json', {'run_id': manifest['run_id'], **data.quality_report})
        _write_jsonl(staging / 'raw_responses.jsonl', data.raw_responses)
        _write_jsonl(staging / 'responses.jsonl', data.latest_responses)
        _write_jsonl(staging / 'usable_responses.jsonl', data.usable_responses)
        staging.rename(destination)
    return destination, data.quality_report


def main():
    parser = argparse.ArgumentParser(description='构建分工 A 的课程目录、有效作答和数据质量报告')
    parser.add_argument('--source', type=Path, default=Path('赛题资料包'), help='赛题资料包根目录')
    parser.add_argument('--out', type=Path, default=Path('outputs') / 'a_snapshots', help='快照输出目录')
    parser.add_argument('--reviews', type=Path, help='经人工确认的异常复核 JSON')
    args = parser.parse_args()
    try:
        path, report = build_snapshot(args.source, args.out, reviews_path=args.reviews)
    except (OSError, ValueError, KeyError, csv.Error) as error:
        parser.exit(1, f'构建失败：{error}\n')
    print(path.resolve())
    print(f"原始 {report['raw_rows']} 行，最新 {report['event_count']} 条，"
          f"有效 {report['usable_count']} 条，仍待复核 {report['unresolved_review_count']} 条。")


if __name__ == '__main__':
    main()
