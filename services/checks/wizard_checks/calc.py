"""Safe arithmetic over named numbers: + - * / ** %, parentheses and a few functions. No names beyond the variables given,
no attribute access, no calls other than the allowlist, bounded size and exponent."""
from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

MAX_EXPRESSION = 500
MAX_NODES = 200

BINARY: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
UNARY: dict[type, Callable[[float], float]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _avg(*values: float) -> float:
    return sum(values) / len(values)


FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs, "min": min, "max": max, "sum": lambda *v: sum(v), "avg": _avg, "sqrt": math.sqrt,
    "round": lambda value, digits=0: round(value, int(digits)),
}


class CalcError(ValueError):
    pass


def evaluate(expression: str, variables: dict[str, float] | None = None) -> float:
    variables = variables or {}
    if len(expression) > MAX_EXPRESSION:
        raise CalcError(f"Expression longer than {MAX_EXPRESSION} characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise CalcError(f"Invalid expression: {error.msg}.") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalcError("Expression is too complex.")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise CalcError(f"Unknown name '{node.id}'. Provide it in variables.")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise CalcError("Exponent is limited to 10.")
            if isinstance(node.op, ast.Div | ast.Mod) and right == 0:
                raise CalcError("Division by zero.")
            return BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
            return UNARY[type(node.op)](visit(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            args = [visit(a) for a in node.args]
            if not args:
                raise CalcError(f"{node.func.id}() needs at least one value.")
            return float(FUNCTIONS[node.func.id](*args))
        raise CalcError(f"Unsupported syntax: {type(node).__name__}.")

    result = visit(tree)
    if math.isnan(result) or math.isinf(result):
        raise CalcError("The result is not a finite number.")
    return result
