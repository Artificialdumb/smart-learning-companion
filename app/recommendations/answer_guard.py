"""Find hint text that states the reference answer, including rewritten but equivalent forms.

Covers the answer shapes of the current items: polynomial expressions (reordered terms,
explicit multiplication, ``+(-n)``, ``-1n``), single relations and chains such as
``1<x≤4`` or ``3<x`` for ``x>3`` (also scaled, ``2x>6``), and systems such as
``x=4,y=3``. Constant-only answers stay with the literal checks in ``checked_text``
because short numbers occur in ordinary prose ("第 2 步").
"""

import re
import unicodedata
from fractions import Fraction

_SUPERSCRIPTS = {"²": "^2", "³": "^3"}
_MATH_RUN = re.compile(r"[0-9a-z.+\-*/^()≤≥≠<>=]+")
_RELATION = re.compile(r"(≤|≥|≠|<|>|=)")
_FLIP = {"<": ">", "≤": "≥"}


def clean(text):
    for symbol, replacement in _SUPERSCRIPTS.items():
        text = text.replace(symbol, replacement)
    text = unicodedata.normalize("NFKC", text or "").lower()
    for symbol in "×·⋅∙":
        text = text.replace(symbol, "*")
    text = text.replace("−", "-").replace("÷", "/").replace("<=", "≤").replace(">=", "≥")
    return re.sub(r"\s+", "", text)


class _Parser:
    """Recursive-descent parser for integer/decimal polynomials with implicit multiplication."""

    def __init__(self, text):
        self.tokens = re.findall(r"\d+(?:\.\d+)?|[a-z]|[-+*/^()]", text)
        if "".join(self.tokens) != text:
            raise ValueError(text)
        self.at = 0

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.at += 1
        return token

    def parse(self):
        value = self.expr()
        if self.peek() is not None:
            raise ValueError("trailing")
        return value

    def expr(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            sign = self.take()
            value = _add(value, self.term(), -1 if sign == "-" else 1)
        return value

    def term(self):
        value = self.factor()
        while True:
            token = self.peek()
            if token == "*":
                self.take()
                value = _mul(value, self.factor())
            elif token == "/":
                self.take()
                divisor = self.factor()
                if set(divisor) - {()} or not divisor.get(()):
                    raise ValueError("non-constant divisor")
                value = {k: v / divisor[()] for k, v in value.items()}
            elif token is not None and (token[0].isdigit() or token.isalpha() or token == "("):
                value = _mul(value, self.factor())
            else:
                return value

    def factor(self):
        token = self.peek()
        if token in ("+", "-"):
            self.take()
            value = self.factor()
            return value if token == "+" else {k: -v for k, v in value.items()}
        value = self.primary()
        if self.peek() == "^":
            self.take()
            exponent = self.take()
            if exponent is None or not exponent.isdigit() or not 0 <= int(exponent) <= 4:
                raise ValueError("exponent")
            result = {(): Fraction(1)}
            for _ in range(int(exponent)):
                result = _mul(result, value)
            value = result
        return value

    def primary(self):
        token = self.take()
        if token is None:
            raise ValueError("end")
        if token == "(":
            value = self.expr()
            if self.take() != ")":
                raise ValueError("paren")
            return value
        if token[0].isdigit():
            return {(): Fraction(token)}
        if token.isalpha():
            return {((token, 1),): Fraction(1)}
        raise ValueError(token)


def _add(left, right, sign=1):
    result = dict(left)
    for key, value in right.items():
        result[key] = result.get(key, 0) + sign * value
    return {k: v for k, v in result.items() if v}


def _mul(left, right):
    result = {}
    for k1, v1 in left.items():
        for k2, v2 in right.items():
            powers = {}
            for var, exp in (*k1, *k2):
                powers[var] = powers.get(var, 0) + exp
            key = tuple(sorted(powers.items()))
            result[key] = result.get(key, 0) + v1 * v2
    return {k: v for k, v in result.items() if v}


def polynomial(text):
    try:
        return _Parser(text).parse() if text else None
    except (ValueError, ZeroDivisionError):
        return None


def _atom(difference, op):
    if op in _FLIP:
        difference, op = {k: -v for k, v in difference.items()}, _FLIP[op]
    variable_terms = sorted(k for k in difference if k)
    if not variable_terms:
        return None  # constant comparison such as 8=8 says nothing about the answer
    lead = difference[variable_terms[0]]
    scale = abs(lead) if op in (">", "≥") else lead
    return op, tuple(sorted((k, v / scale) for k, v in difference.items()))


def relations(text):
    """Canonical atoms of a relation chain such as ``1<x≤4``; None when not a relation."""
    parts = _RELATION.split(text)
    if len(parts) < 3:
        return None
    sides = [polynomial(part) for part in parts[0::2]]
    if any(side is None for side in sides):
        return None
    atoms = set()
    for left, op, right in zip(sides, parts[1::2], sides[1:]):
        atom = _atom(_add(left, right, -1), op)
        if atom:
            atoms.add(atom)
    return atoms or None


def _informative(poly):
    """Answers worth matching by value: more than a bare constant or a lone variable."""
    if not poly or set(poly) == {()}:
        return False
    if len(poly) > 1:
        return True
    (key, coefficient), = poly.items()
    return coefficient != 1 or sum(exp for _, exp in key) > 1


def answer_form(reference_answer):
    """('poly', p) or ('relations', atoms) for answers this guard can compare, else None."""
    text = clean(reference_answer).strip("。.!！")
    atoms = set()
    for run in re.split(r"[,，;；、]|且|和", text):
        found = relations(run)
        if found:
            atoms |= found
    if atoms:
        return "relations", frozenset(atoms)
    poly = polynomial(text)
    return ("poly", poly) if _informative(poly) else None


def states_answer(text, form, prompt=""):
    """True when ``text`` writes the answer, in any equivalent form the guard understands."""
    if form is None:
        return False
    quoted = clean(prompt)
    kind, target = form
    seen = set()
    for run in _MATH_RUN.findall(clean(text)):
        run = run.strip(".=")
        if not run or (len(run) > 2 and run in quoted):
            continue  # restating the question's own expression is not the answer
        if kind == "poly":
            if any(polynomial(side) == target for side in _RELATION.split(run)[0::2]):
                return True
        else:
            seen |= relations(run) or set()
            if target <= seen:
                return True
    return False
