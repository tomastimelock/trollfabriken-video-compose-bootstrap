from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")


class ConditionEvaluator:
    """Evaluates condition expressions against a variable namespace.

    Expressions use {{var}} syntax for variable substitution. After
    substitution, the expression is evaluated with Python eval() using
    a restricted namespace (no builtins, no module access).

    Examples:
        "{{score}} > 5"
        "{{product_type}} == 'premium'"
        "{{show_intro}} == True"
        "{{item_index}} < 3"
    """

    def __init__(self, variables: dict) -> None:
        self._vars = variables

    def evaluate(self, condition: str | None) -> bool:
        """Return True if the condition is truthy (or if condition is None)."""
        if condition is None:
            return True
        try:
            expr = _substitute(condition, self._vars)
            result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
            return bool(result)
        except Exception as exc:
            logger.warning("condition %r evaluation failed: %s — treating as True", condition, exc)
            return True

    def with_extra(self, extra: dict) -> "ConditionEvaluator":
        """Return a new evaluator with additional variables merged in."""
        merged = {**self._vars, **extra}
        return ConditionEvaluator(merged)


def _substitute(expr: str, variables: dict) -> str:
    """Replace {{key}} tokens in expr with their string-repr from variables."""
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        val = variables.get(key)
        if val is None:
            return "None"
        if isinstance(val, str):
            escaped = val.replace("'", "\\'")
            return f"'{escaped}'"
        if isinstance(val, bool):
            return "True" if val else "False"
        return str(val)

    return _VAR_RE.sub(replacer, expr)
