import csv
import json
import os
import unittest
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.a_pipeline import build_snapshot
from app.catalog import build_catalog
from app.cli import build
from app.csv_input import DATA_PATH
from app.ingestion import ingest
from app.web.main import create_app


SOURCE = Path(os.environ.get('STUDY_CONTEST_SOURCE', Path(__file__).resolve().parents[1] / 'data' / '赛题资料包'))


def by_record(rows, record_id):
    return next(row for row in rows if row['record_id'] == record_id)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'STUDY_CONTEST_SOURCE' not in os.environ and not SOURCE.is_dir():
            raise unittest.SkipTest('需本地赛题资料，设置 STUDY_CONTEST_SOURCE 后运行')
        cls.catalog = build_catalog(SOURCE)
        cls.baseline = ingest(SOURCE, cls.catalog)

    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.work = Path(scratch.name)

    def review_file(self, *decisions, digest=None):
        path = self.work / 'reviews.json'
        path.write_text(json.dumps({
            'source_sha256': digest or self.baseline.quality_report['response_source_sha256'],
            'decisions': list(decisions),
        }, ensure_ascii=False), encoding='utf-8')
        return path

    def source_with_extra_responses(self, *rows):
        data_dir = self.work / DATA_PATH
        data_dir.mkdir(exist_ok=True, parents=True)
        copy2(SOURCE / DATA_PATH / '模拟学生.csv', data_dir)
        with (data_dir / '作答记录.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.baseline.raw_responses[0]))
            writer.writeheader()
            writer.writerows([*self.baseline.raw_responses, *rows])
        return self.work

    def test_published_data_counts_and_zero_scores(self):
        report = self.baseline.quality_report
        self.assertEqual((report['raw_rows'], report['event_count'], report['usable_count']), (806, 799, 785))
        self.assertEqual(report['latest_scoring_status_counts'], {'graded': 790, 'pending': 4, 'unanswered': 5, 'unknown': 0})
        self.assertEqual(report['superseded_records'], 7)
        self.assertTrue(any(row['score'] == 0 for row in self.baseline.usable_responses))
        self.assertEqual(by_record(self.baseline.usable_responses, 'DR0001')['rubric_scores']['Q015P3'], 0)
        excluded = {row['record_id'] for row in self.baseline.latest_responses if row['validation_status'] == 'needs_review'}
        self.assertEqual(excluded, {'DR0081', 'DR0133', 'DR0361', 'DR0515', 'DR0535'})
        self.assertIsNone(by_record(self.baseline.latest_responses, 'DR0361')['score'])

    def test_pending_revision_and_exact_duplicate(self):
        old = self.baseline.raw_responses[0]
        revised = dict(old, 记录编号='PENDING-REV', 修订版本='2', 评分状态='待评分', 得分='', 评分点得分='')
        data = ingest(self.source_with_extra_responses(revised, revised.copy()), self.catalog)
        current = by_record(data.latest_responses, 'PENDING-REV')
        self.assertEqual(current['scoring_status'], 'pending')
        self.assertIsNone(current['score'])
        self.assertNotIn(old['作答事件编号'], {row['event_id'] for row in data.usable_responses})
        self.assertEqual(data.quality_report['issue_counts']['duplicate_row'], 1)

    def test_conflicting_latest_versions_exclude_entire_event(self):
        old = self.baseline.raw_responses[0]
        new = dict(old, 记录编号='REV-A', 修订版本='2')
        other = dict(new, 记录编号='REV-B', 得分='1')
        data = ingest(self.source_with_extra_responses(new, other), self.catalog)
        self.assertEqual(by_record(data.latest_responses, 'REV-A')['validation_status'], 'needs_review')
        self.assertNotIn(old['作答事件编号'], {row['event_id'] for row in data.usable_responses})
        issue = next(row for row in data.quality_report['issues'] if row['code'] == 'ambiguous_latest_revision')
        self.assertEqual(issue['values']['candidate_record_ids'], ['REV-A', 'REV-B'])

    def test_review_creates_reproducible_new_batch_with_audit(self):
        reviews = self.review_file(
            {'record_id': 'DR0081', 'revision': 1, 'action': 'correct', 'reason': '测试确认题库主题', 'changes': {'主题编号': 'T01'}},
            {'record_id': 'DR0133', 'revision': 1, 'action': 'exclude', 'reason': '测试确认仍无法判定分数'},
        )
        first, report = build_snapshot(SOURCE, self.work, reviews_path=reviews)
        second, _ = build_snapshot(SOURCE, self.work, reviews_path=reviews)
        self.assertNotEqual(first, second)
        for name in ('raw_responses.jsonl', 'responses.jsonl', 'usable_responses.jsonl'):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        self.assertEqual((report['usable_count'], report['unresolved_review_count']), (786, 3))
        self.assertEqual(report['reviews'][0]['changes']['主题编号'], {'before': 'T02', 'after': 'T01'})
        self.assertEqual(report['review_input']['sha256'], sha256(reviews.read_bytes()).hexdigest())
        raw = [json.loads(line) for line in (first / 'raw_responses.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(next(row for row in raw if row['记录编号'] == 'DR0081')['主题编号'], 'T02')

    def test_invalid_review_never_publishes_a_batch(self):
        decision = {'record_id': 'DR0361', 'revision': 1, 'action': 'correct',
                    'reason': '测试不完整的更正', 'changes': {'得分': '2'}}
        with self.assertRaisesRegex(ValueError, '更正后仍有异常'):
            build_snapshot(SOURCE, self.work / 'output', reviews_path=self.review_file(decision))
        self.assertFalse((self.work / 'output').exists())
        with self.assertRaisesRegex(ValueError, 'source_sha256'):
            ingest(SOURCE, self.catalog, reviews_path=self.review_file(decision, digest='invalid'))
        with self.assertRaisesRegex(ValueError, '当前最新版本'):
            ingest(SOURCE, self.catalog, reviews_path=self.review_file(dict(decision, revision=2)))

    def test_score_correction_uses_rubric_and_preserves_raw_score(self):
        decision = {'record_id': 'DR0361', 'revision': 1, 'action': 'correct',
                    'reason': '测试按已核对的评分点修正总分', 'changes': {'得分': '1'}}
        data = ingest(SOURCE, self.catalog, reviews_path=self.review_file(decision))
        effective = by_record(data.usable_responses, 'DR0361')
        self.assertEqual((effective['score'], effective['max_score']), (1, 1))
        self.assertEqual(data.quality_report['reviews'][0]['changes']['得分'], {'before': '10', 'after': '1'})
        raw = next(row for row in data.raw_responses if row['记录编号'] == 'DR0361')
        self.assertEqual(raw['得分'], '10')

    def test_unified_build_accepts_csv_reviews_and_a_snapshot(self):
        reviews = self.review_file({'record_id': 'DR0361', 'revision': 1, 'action': 'correct',
                                    'reason': '测试按评分点修正总分', 'changes': {'得分': '1'}})
        snapshot, _ = build_snapshot(SOURCE, self.work / 'snapshots', reviews_path=reviews)
        db = self.work / 'study.sqlite3'
        direct_run = build(SOURCE, db, reviews_path=reviews)
        imported_run = build(snapshot, db)
        with TestClient(create_app(db), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            for run in (direct_run, imported_run):
                params = {'run_id': run}
                evidence = client.get('/api/records/DR0361', params=params)
                self.assertEqual(evidence.status_code, 200)
                self.assertEqual(evidence.json()['score'], 1)
                diagnosis = client.get('/api/students/D01/diagnosis', params={**params, 'node_id': 'N01'})
                self.assertEqual(diagnosis.status_code, 200)
                self.assertTrue(any(e['record_id'] == 'DR0001' for row in diagnosis.json()['indicators']
                                    for finding in row['findings'] for e in finding['evidence']))
                catalog = client.get('/api/catalog', params=params).json()
                indicator = next(i for i in catalog['indicators'] if i['indicator_id'] == 'T01I2')
                self.assertIn('整式的加法与减法', indicator['references'][1]['locator'])
