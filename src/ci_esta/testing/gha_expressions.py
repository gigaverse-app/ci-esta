"""
Tiny evaluator for the GitHub Actions ``if:`` expression subset our
workflows use.

Workflow `if:` conditions are decision logic. Asserting their exact *string*
makes tests fragile: any behavior-preserving rewrite (reordering an `||`,
adding a guard, reformatting) breaks the test without any change in what the
workflow actually does. Instead, evaluate the expression against synthetic
event payloads and assert the *decision* — "does this job run when a PR is
synchronized while carrying a perf label?" — which is the real invariant.

Supports only what the workflows use: string literals, `true`/`false`, context
paths (incl. the ``labels.*.name`` object-filter), ``==`` ``!=`` ``&&`` ``||``,
parentheses, and ``contains(seq, item)``. Missing context paths resolve to
``None`` (GitHub's ``null``).
"""

from __future__ import annotations

import json
import re
from typing import Any

Context = dict[str, Any]

_TOKEN = re.compile(
    r"""
      \s+                         # whitespace (skipped)
    | (?P<str>'(?:[^']*)')        # 'single-quoted string'
    | (?P<op>==|!=|&&|\|\|)       # binary operators
    | (?P<number>-?\d+(?:\.\d+)?) # decimal literals
    | (?P<punc>[(),])             # parens / comma
    | (?P<name>[A-Za-z_][\w.*\-]*)  # path / function / true / false
    """,
    re.VERBOSE,
)

_MISSING = object()


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise ValueError(f"cannot tokenize at {expr[pos:]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind is None:  # whitespace
            continue
        tokens.append((kind, m.group()))
    tokens.append(("end", ""))
    return tokens


def _resolve(path: str, ctx: Context) -> object:
    """Walk a dotted context path; ``*`` maps the rest over a list."""

    def walk(parts: list[str], val: object) -> object:
        if not parts:
            return val
        head, rest = parts[0], parts[1:]
        if head == "*":
            if not isinstance(val, list):
                return None
            return [walk(rest, item) for item in val]
        if isinstance(val, dict):
            return walk(rest, val.get(head, _MISSING) if head in val else None)
        return None

    return walk(path.split("."), ctx)


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0
        self.ctx: Context = {}

    def peek(self) -> tuple[str, str]:
        return self.tokens[self.i]

    def next(self) -> tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, value: str) -> None:
        _kind, text = self.next()
        if text != value:
            raise ValueError(f"expected {value!r}, got {text!r}")

    # or := and ('||' and)*
    #
    # GitHub's `&&`/`||` return the OPERAND, not a boolean — which is what
    # makes `cond && 'a' || 'b'` the ternary every `environment:` mapping is
    # written with. Coercing to bool here would collapse those to True/False
    # and make value-producing expressions unevaluable; `evaluate()` still
    # coerces at the end, so boolean `if:` callers are unaffected. Both sides
    # are evaluated rather than short-circuited (the grammar has no calls with
    # side effects, and the parser must consume the tokens either way).
    def parse_or(self) -> object:
        val = self.parse_and()
        while self.peek()[1] == "||":
            self.next()
            rhs = self.parse_and()
            val = val if bool(val) else rhs
        return val

    # and := cmp ('&&' cmp)*
    def parse_and(self) -> object:
        val = self.parse_cmp()
        while self.peek()[1] == "&&":
            self.next()
            rhs = self.parse_cmp()
            val = rhs if bool(val) else val
        return val

    # cmp := primary (('==' | '!=') primary)?
    def parse_cmp(self) -> object:
        lhs = self.parse_primary()
        if self.peek()[1] in ("==", "!="):
            op = self.next()[1]
            rhs = self.parse_primary()
            return (lhs == rhs) if op == "==" else (lhs != rhs)
        return lhs

    def parse_primary(self) -> object:
        kind, text = self.next()
        if text == "(":
            val = self.parse_or()
            self.expect(")")
            return val
        if kind == "str":
            return text[1:-1]
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "name":
            if text == "true":
                return True
            if text == "false":
                return False
            if text in {"toJSON", "fromJSON"} and self.peek()[1] == "(":
                self.expect("(")
                value = self.parse_or()
                self.expect(")")
                return json.dumps(value) if text == "toJSON" else json.loads(value)
            if text == "contains" and self.peek()[1] == "(":
                self.expect("(")
                seq = self.parse_or()
                self.expect(",")
                item = self.parse_or()
                self.expect(")")
                if isinstance(seq, str):
                    assert isinstance(item, str)
                    return item in seq
                if isinstance(seq, list):
                    return item in seq
                return False
            return _resolve(text, self.ctx)
        raise ValueError(f"unexpected token {text!r}")

    def run(self, ctx: Context) -> object:
        self.ctx = ctx
        val = self.parse_or()
        if self.peek()[0] != "end":
            raise ValueError(f"trailing tokens from {self.peek()!r}")
        return val


def evaluate(expr: str, context: Context) -> bool:
    """
    Evaluate a GitHub Actions ``if:`` expression to a bool for
    ``context``."""
    return bool(evaluate_value(expr, context))


def evaluate_value(expr: str, context: Context) -> object:
    """
    Evaluate an expression to its VALUE, for the keys that produce strings
    rather than decisions (``environment:``, ``concurrency.group``, …).

    Accepts the ``${{ … }}`` wrapper those keys are written with; ``if:``
    omits it, so ``evaluate`` sees the bare expression either way.
    """
    expr = expr.strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2]
    return _Parser(_tokenize(expr)).run(context)


def pull_request_event(
    action: str,
    *,
    label: str | None = None,
    labels: list[str] | None = None,
    db_mode: str | None = None,
) -> Context:
    """Build a `github` + `steps` context for a pull_request event scenario."""
    return {
        "github": {
            "event_name": "pull_request",
            "event": {
                "action": action,
                "label": {"name": label} if label is not None else None,
                "pull_request": {
                    "number": "3177",
                    "labels": [{"name": n} for n in (labels or [])],
                },
            },
        },
        "steps": {"pr": {"outputs": {"db_mode": db_mode}}},
    }


def workflow_dispatch_event(*, db_mode: str | None = None, inputs: dict[str, str] | None = None) -> Context:
    return {
        "github": {"event_name": "workflow_dispatch", "event": {}},
        "inputs": inputs or {},
        "steps": {"pr": {"outputs": {"db_mode": db_mode}}},
    }


def schedule_event() -> Context:
    """A cron trigger: `inputs` is empty, so every `inputs.*` read is null."""
    return {
        "github": {"event_name": "schedule", "event": {}},
        "inputs": {},
        "steps": {"pr": {"outputs": {"db_mode": None}}},
    }
