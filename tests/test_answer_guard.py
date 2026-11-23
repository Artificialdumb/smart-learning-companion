import unittest

from app.recommendations.answer_guard import answer_form, states_answer

PROMPT = "化简 5m+3n-(2m+4n)。"


class EquivalentFormTests(unittest.TestCase):
    def assert_states(self, answer, texts, expected, prompt=""):
        form = answer_form(answer)
        for text in texts:
            with self.subTest(answer=answer, text=text):
                self.assertEqual(states_answer(text, form, prompt), expected)

    def test_polynomial_rewrites_are_detected(self):
        self.assert_states("3m-n", [
            "将化简式填写为 −n+3m", "-n + 3m", "3·m − n", "3m+(-n)", "m×3−n", "−1n+3m", "6m/2-n",
            "过程写成 5m+3n-2m-4n=3m-n。",
        ], True, PROMPT)

    def test_method_hints_and_question_quotes_pass(self):
        self.assert_states("3m-n", [
            "先标出括号前的符号，逐项检查去括号和合并。", "检查 3m 与 2m 是否同类项",
            "回看 5m+3n-(2m+4n) 中括号前的减号", "第 2 步", "3m+n 与题目是否一致？",
        ], False, PROMPT)

    def test_relations_and_chains(self):
        self.assert_states("x>3", ["解集写成 3<x", "2x>6", "x>3"], True)
        self.assert_states("x>3", ["x≥3 与 x>3 的区别在端点"], True)
        self.assert_states("x>3", ["注意 x≥3 包含端点", "x<3 时不成立", "x<3"], False)
        self.assert_states("1<x≤4", ["4≥x>1", "x>1，且 x≤4", "x≤4 且 x>1"], True)
        self.assert_states("1<x≤4", ["先看 x>1", "x≤4 是第二个条件"], False)

    def test_systems(self):
        self.assert_states("x=4,y=3", ["y=3，x=4", "x=4 且 y=3"], True)
        self.assert_states("x=4,y=3", ["先求 x=4"], False)

    def test_constants_and_lone_variables_are_left_to_literal_checks(self):
        self.assertIsNone(answer_form("4"))
        self.assertIsNone(answer_form("x"))
        self.assertIsNotNone(answer_form("4c"))
        self.assertIsNotNone(answer_form("a^2"))


if __name__ == "__main__":
    unittest.main()
