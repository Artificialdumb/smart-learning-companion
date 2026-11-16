import os
import unittest
from pathlib import Path

from app.catalog import build_catalog


class CatalogTests(unittest.TestCase):
    def test_verified_indicator_locations(self):
        source = Path(os.environ.get('STUDY_CONTEST_SOURCE', Path(__file__).resolve().parents[1] / 'data' / '赛题资料包'))
        if 'STUDY_CONTEST_SOURCE' not in os.environ and not source.is_dir():
            self.skipTest('需本地赛题资料，设置 STUDY_CONTEST_SOURCE 后运行')
        catalog = build_catalog(source)
        indicators = {row['indicator_id']: row for row in catalog['indicators']}
        self.assertEqual(len(indicators), 9)
        for indicator in indicators.values():
            refs = indicator['references']
            self.assertTrue(refs[0]['clauses'])
            self.assertTrue(all(ref['section'] and ref['pdf_page'] > 0 for ref in refs[1:]))
        self.assertEqual(indicators['T01I2']['references'][1]['pdf_pages'], [28, 33])
        self.assertEqual([ref['pdf_page'] for ref in indicators['T02I2']['references'][1:]], [44, 48])
        self.assertTrue(all(relation['references'] for relation in catalog['learning_relations']))
