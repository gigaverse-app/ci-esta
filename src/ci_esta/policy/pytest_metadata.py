"""Python-specific boolean marker filtering; no pytest import or collection side effects.

Extracted from AI. Supports names, and/or/not, parentheses and boolean constants.
Keyword argument expressions are deliberately unsupported and raise.
"""

import ast


def marker_expr_matches(markers: frozenset[str], marker_expr: str) -> bool:
    """
    Evaluate the subset of pytest ``-m`` expressions the selector supports.

    Pytest marker expressions are Python-like boolean expressions over marker names
    (``ci_integration and not quarantine``). The selector needs the same filtering
    before per-test resource grouping so manual marker overrides do not get treated
    as a literal marker named ``custom``.
    """
    tree = ast.parse(marker_expr, mode="eval")

    def evaluate(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.Name):
            return node.id in markers
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        raise ValueError(f"unsupported pytest marker expression: {marker_expr!r}")

    return evaluate(tree)
