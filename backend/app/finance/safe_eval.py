"""Restricted arithmetic evaluator over Decimal values.

This is the "restricted sandbox" for calculations: formulas (including any formula an LLM planner
proposes) are parsed into a Python AST and only numeric literals, named variables bound to verified
facts, + - * /, unary minus and parentheses are allowed. No attribute access, calls, subscripts,
comprehensions or names outside the bound variables — so nothing arbitrary can execute.
"""

from __future__ import annotations

import ast
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext

getcontext().prec = 34

_ALLOWED_BINOPS = {ast.Add: Decimal.__add__, ast.Sub: Decimal.__sub__, ast.Mult: Decimal.__mul__, ast.Div: Decimal.__truediv__}


class FormulaError(ValueError):
    pass


def evaluate(formula: str, variables: dict[str, Decimal]) -> Decimal:
    if len(formula) > 500:
        raise FormulaError("formula too long")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"invalid formula: {exc.msg}") from exc

    def _eval(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise FormulaError(f"unknown variable '{node.id}'")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise FormulaError("division by zero")
            try:
                return _ALLOWED_BINOPS[type(node.op)](left, right)
            except (InvalidOperation, DivisionByZero) as exc:
                raise FormulaError(str(exc)) from exc
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = _eval(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        raise FormulaError(f"disallowed expression element: {type(node).__name__}")

    return _eval(tree)


def variables_in(formula: str) -> set[str]:
    tree = ast.parse(formula, mode="eval")
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
