import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.cli import build

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"


@unittest.skipUnless(importlib.util.find_spec("fitz"), "需安装 docs 依赖（PyMuPDF）")
class DesignDocTests(unittest.TestCase):
    def test_pdf_has_required_sections_within_page_limit(self):
        import fitz

        from tools.design_doc import MAX_PAGES, generate
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            db = folder / "study.sqlite3"
            run = build(FIXTURE, db)
            out = folder / "design.pdf"
            pages = generate(db, run, out, "合成数据", tests=(53, 0, 2), students=200)
            self.assertLessEqual(pages, MAX_PAGES)
            with fitz.open(out) as document:
                text = "".join(page.get_text() for page in document)
        for heading in ("需求与分析范围", "数据与质量控制", "方法", "三名学生案例", "两班分析", "验证", "成果包字段", "复算说明"):
            self.assertIn(heading, text)
        self.assertIn("共 53 个，失败 0 个，跳过 2 个", text)
        self.assertIn("经平滑的得分比例", text)
        self.assertIn("教师评分安排在下一阶段", text)
        self.assertIn("只找到 2 类代表案例", text)  # the synthetic batch has no strength case
        self.assertIn("X-R01", text)
        self.assertNotIn(run, text)


if __name__ == "__main__":
    unittest.main()
