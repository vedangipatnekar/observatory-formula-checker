import unittest
from evaluator import evaluate
from pdf_report import build_pdf


def ok(expr, vs=None):
    r = evaluate(expr, vs)
    assert r["ok"], r["error"]
    return r["result"]


def err(expr, vs=None):
    r = evaluate(expr, vs)
    assert not r["ok"]
    return r["error"]


class Valid(unittest.TestCase):
    def test_example(self):
        self.assertEqual(ok("-(a + b) * 2 + 30 / 5", {"a": 10, "b": 5}), "-24")

    def test_precedence_assoc(self):
        self.assertEqual(ok("2 + 3 * 4"), "14")
        self.assertEqual(ok("10 - 4 - 3"), "3")
        self.assertEqual(ok("100 / 10 / 5"), "2")
        self.assertEqual(ok("(2 + 3) * 4"), "20")

    def test_unary(self):
        self.assertEqual(ok("--3"), "3")
        self.assertEqual(ok("2 * -3"), "-6")
        self.assertEqual(ok("-2 * -3"), "6")
        self.assertEqual(ok("+5 - -5"), "10")
        self.assertEqual(ok("-(-(2))"), "2")

    def test_decimals_and_real_division(self):
        self.assertEqual(ok("0.1 + 0.2"), "0.3")
        self.assertEqual(ok("7 / 2"), "3.5")
        self.assertEqual(ok(".5 * 4"), "2")

    def test_unicode_ops(self):
        self.assertEqual(ok("6 × 3 ÷ 2 − 1"), "8")

    def test_unseen_demo(self):
        self.assertEqual(ok("-((x + y) * (z - -3)) / (y - 1.5)", {"x": -4.5, "y": 3, "z": 2}), "5")

    def test_negative_variable_values(self):
        self.assertEqual(ok("a * b", {"a": "-2.5", "b": -4}), "10")

    def test_trace_and_tree(self):
        r = evaluate("-(a + b) * 2 + 30 / 5", {"a": 10, "b": 5})
        self.assertEqual(r["postfix"], ["a", "b", "+", "neg", "2", "*", "30", "5", "/", "+"])
        subs = [s["subexpression"] for s in r["steps"] if s["type"] == "compute"]
        self.assertIn("(a + b)", subs)
        self.assertEqual(subs[-1], "(((-(a + b)) * 2) + (30 / 5))")
        self.assertTrue(r["tree"].splitlines()[0].startswith("+"))

    def test_token_limit(self):
        self.assertEqual(ok("+".join(["1"] * 1000)), "1000")  # 1999 tokens
        self.assertEqual(err("+".join(["1"] * 1001))["kind"], "too_long")

    def test_deep_nesting(self):
        self.assertEqual(ok("(" * 900 + "1" + ")" * 900), "1")


class Invalid(unittest.TestCase):
    def kind(self, e, vs=None):
        return err(e, vs)["kind"]

    def test_errors(self):
        self.assertEqual(self.kind("2 @ 3"), "invalid_token")
        self.assertEqual(self.kind("2 ^ 3"), "invalid_token")
        self.assertEqual(self.kind("(1 + 2"), "missing_bracket")
        self.assertEqual(self.kind("1 + 2)"), "unmatched_paren")
        self.assertEqual(self.kind("a + 1"), "undefined_variable")
        self.assertEqual(self.kind("5 / 0"), "division_by_zero")
        self.assertEqual(self.kind("5 / (a - 10)", {"a": 10}), "division_by_zero")
        self.assertEqual(self.kind(""), "empty")
        self.assertEqual(self.kind("()"), "empty_parentheses")
        self.assertEqual(self.kind("1 +"), "missing_operand")
        self.assertEqual(self.kind("* 3"), "missing_operand")
        self.assertEqual(self.kind("2 3"), "missing_operator")
        self.assertEqual(self.kind("2 (3)"), "missing_operator")
        self.assertEqual(self.kind("1 + * 2"), "missing_operand")
        self.assertEqual(self.kind("1", {"1x": 3}), "invalid_variable")
        self.assertEqual(self.kind("x", {"x": "abc"}), "invalid_variable")

    def test_messages_specific(self):
        self.assertIn("'@'", err("2 @ 3")["message"])
        self.assertIn("'q'", err("q * 2")["message"])
        self.assertIn("position 1", err("(1 + 2")["message"])


class PdfReport(unittest.TestCase):
    def test_build_pdf_is_valid_and_contains_scan(self):
        pdf = build_pdf([{
            "expression": "a + 2",
            "variables": {"a": 3},
            "ok": True,
            "result": "5",
            "steps": [{"type": "compute", "subexpression": "(a + 2)", "text": "3 + 2 = 5"}],
            "tree": "+ = 5\n├── a\n└── 2",
        }])
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", pdf)
        self.assertIn(b"OBSERVATORY FORMULA REPORT", pdf)
        self.assertIn(b"Expression: a + 2", pdf)
        self.assertIn(b"Result: 5", pdf)


if __name__ == "__main__":
    unittest.main()