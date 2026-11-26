"""Small, local assistant for scan explanations and suggested fixes."""

import datetime


def diagnose(rec):
    error = rec.get("error") or {}
    kind = error.get("kind")
    if kind == "undefined_variable":
        name = None
        message = error.get("message", "")
        if "'" in message:
            name = message.split("'", 2)[1]
        return {
            "summary": "A variable in the formula has not been given a value.",
            "fixes": ([{"label": f"Set {name}", "add_variable": name}] if name else []),
        }
    if kind == "division_by_zero":
        return {
            "summary": "The formula tries to divide by zero.",
            "fixes": [{"label": "Change the divisor", "expression": rec.get("expression", "")}],
        }
    if kind in ("missing_bracket", "unmatched_paren", "empty_parentheses"):
        return {
            "summary": "The parentheses are incomplete or incorrectly matched.",
            "fixes": [{"label": "Review parentheses", "expression": rec.get("expression", "")}],
        }
    if kind in ("missing_operand", "missing_operator"):
        return {
            "summary": "The expression is missing a value or operator.",
            "fixes": [],
        }
    if kind == "invalid_variable":
        return {
            "summary": "A variable name or value is not valid.",
            "fixes": [],
        }
    return {"summary": "Review the formula and try again.", "fixes": []}


def answer(question, rec, history=None):
    """Answer common questions from the saved scan; no network or API key required."""
    q = question.lower().strip()
    expression = rec.get("expression", "")
    error = rec.get("error")

    if not rec.get("ok"):
        kind = (error or {}).get("kind", "unknown")
        message = (error or {}).get("message", "The expression could not be evaluated.")
        if any(word in q for word in ("why", "failed", "error", "wrong")):
            return (f"This scan failed with {kind.replace('_', ' ')}: {message}", "Local scan diagnostics")
        if "fix" in q:
            suggestion = diagnose(rec)
            return (suggestion["summary"], "Local scan diagnostics")

    if rec.get("ok"):
        if any(word in q for word in ("result", "answer", "how", "worked")):
            steps = rec.get("steps", [])
            computations = [s["subexpression"] for s in steps if s.get("type") == "compute"]
            detail = f" The calculation steps are: {'; '.join(computations)}." if computations else ""
            return (
                f"The result of {expression} is {rec.get('result')}.{detail}",
                "Saved evaluation trace",
            )

    if any(word in q for word in ("order", "precedence", "operator")):
        return (
            "Operators follow standard precedence: parentheses, unary signs, multiplication/division, then addition/subtraction.",
            "Evaluator rules",
        )
    if "variable" in q:
        variables = rec.get("variables", {})
        if variables:
            values = ", ".join(f"{name} = {value}" for name, value in variables.items())
            return (f"The variables used were: {values}.", "Saved variables")
        return ("No variables were used in this scan.", "Saved variables")
    return (
        f"The saved expression is {expression}. "
        + (f"It evaluates to {rec.get('result')}." if rec.get("ok") else f"It failed: {(error or {}).get('message', 'unknown error')}."),
        "Saved scan",
    )
