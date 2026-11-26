"""Observatory expression evaluator: tokenizer, shunting-yard parser, tree, traced evaluation.
No eval()/exec(). Supports + - * / (and × ÷ −), parentheses, unary +/-, named variables."""
import re, sys, argparse

MAX_TOKENS = 2000
OPS = {"+": (1, "L"), "-": (1, "L"), "*": (2, "L"), "/": (2, "L"), "neg": (3, "R"), "pos": (3, "R")}
ALIASES = {"×": "*", "÷": "/", "−": "-", "–": "-"}
TOKEN_RE = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|([A-Za-z_][A-Za-z0-9_]*)|(.))")
NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ExpressionError(Exception):
    def __init__(self, kind, message, position=None):
        super().__init__(message)
        self.kind, self.message, self.position = kind, message, position

    def to_dict(self):
        return {"kind": self.kind, "message": self.message, "position": self.position}


def fmt(x):
    s = "%.12g" % x
    return "0" if s in ("-0", "-0.0") else s


def tokenize(expr):
    tokens, i = [], 0
    while i < len(expr):
        m = TOKEN_RE.match(expr, i)
        if not m or m.end() == i:
            break
        i = m.end()
        num, name, other = m.groups()
        if num is not None:
            tokens.append({"type": "num", "text": num, "pos": m.start(1)})
        elif name is not None:
            tokens.append({"type": "var", "text": name, "pos": m.start(2)})
        else:
            ch = ALIASES.get(other, other)
            pos = m.start(3)
            if ch in "+-*/":
                tokens.append({"type": "op", "text": ch, "pos": pos})
            elif ch == "(":
                tokens.append({"type": "lparen", "text": ch, "pos": pos})
            elif ch == ")":
                tokens.append({"type": "rparen", "text": ch, "pos": pos})
            else:
                raise ExpressionError("invalid_token", f"Invalid token '{other}' at position {pos + 1}", pos)
        if len(tokens) > MAX_TOKENS:
            raise ExpressionError("too_long", f"Expression exceeds the limit of {MAX_TOKENS} tokens")
    return tokens


def to_postfix(tokens, parse_trace):
    """Shunting-yard with explicit unary handling and bracket validation."""
    out, stack, expect_operand, prev = [], [], True, None
    show = lambda: [s["text"] if s["type"] != "unary" else s["op"] for s in stack]

    def log(tok, action):
        parse_trace.append({"token": tok["text"], "action": action,
                            "output": [o["label"] for o in out], "stack": show()})

    def pop_op(s):
        out.append({"type": "op", "op": s["op"], "label": s["op"], "pos": s["pos"]})

    for t in tokens:
        ty = t["type"]
        if ty in ("num", "var"):
            if not expect_operand:
                raise ExpressionError("missing_operator", f"Missing operator before '{t['text']}' at position {t['pos'] + 1}", t["pos"])
            out.append({"type": ty, "text": t["text"], "label": t["text"], "pos": t["pos"]})
            log(t, "operand → output")
            expect_operand = False
        elif ty == "lparen":
            if not expect_operand:
                raise ExpressionError("missing_operator", f"Missing operator before '(' at position {t['pos'] + 1}", t["pos"])
            stack.append({"type": "lparen", "text": "(", "pos": t["pos"]})
            log(t, "push '('")
        elif ty == "rparen":
            if expect_operand:
                if prev and prev["type"] == "lparen":
                    raise ExpressionError("empty_parentheses", f"Empty parentheses at position {prev['pos'] + 1}", prev["pos"])
                raise ExpressionError("missing_operand", f"Missing operand before ')' at position {t['pos'] + 1}", t["pos"])
            while stack and stack[-1]["type"] != "lparen":
                pop_op(stack.pop())
            if not stack:
                raise ExpressionError("unmatched_paren", f"Unmatched closing bracket ')' at position {t['pos'] + 1}", t["pos"])
            stack.pop()
            log(t, "pop to '(' and discard brackets")
        else:  # operator
            op = t["text"]
            if expect_operand:
                if op in "+-":
                    name = "neg" if op == "-" else "pos"
                    stack.append({"type": "unary", "op": name, "text": op, "pos": t["pos"]})
                    log(t, f"unary '{op}' → push as {name}")
                    prev = t
                    continue
                raise ExpressionError("missing_operand", f"Operator '{op}' at position {t['pos'] + 1} has no left operand", t["pos"])
            prec, _ = OPS[op]
            while stack and stack[-1]["type"] in ("op", "unary"):
                top = stack[-1]
                tp, _ = OPS[top["op"]]
                if tp > prec or tp == prec:  # all binary ops are left-associative
                    pop_op(stack.pop())
                else:
                    break
            stack.append({"type": "op", "op": op, "text": op, "pos": t["pos"]})
            log(t, f"push '{op}' (after popping higher/equal precedence)")
            expect_operand = True
        prev = t
    if not tokens:
        raise ExpressionError("empty", "Expression is empty")
    if expect_operand:
        raise ExpressionError("missing_operand", f"Expression ends after '{prev['text']}' at position {prev['pos'] + 1}: a value is missing", prev["pos"])
    while stack:
        s = stack.pop()
        if s["type"] == "lparen":
            raise ExpressionError("missing_bracket", f"Missing closing bracket for '(' opened at position {s['pos'] + 1}", s["pos"])
        pop_op(s)
    parse_trace.append({"token": "(end)", "action": "pop remaining operators",
                        "output": [o["label"] for o in out], "stack": []})
    return out


def build_tree(postfix):
    """Returns (root, nodes_in_postfix_order). Iterative, so deep nesting is safe."""
    st, order = [], []
    for p in postfix:
        if p["type"] == "op":
            if p["op"] in ("neg", "pos"):
                node = {"kind": "unary", "op": p["op"], "children": [st.pop()]}
            else:
                r, l = st.pop(), st.pop()
                node = {"kind": "binary", "op": p["op"], "children": [l, r], "pos": p["pos"]}
        else:
            node = {"kind": p["type"], "text": p["text"], "children": [], "pos": p["pos"]}
        st.append(node)
        order.append(node)
    return st[0], order


def evaluate_nodes(order, variables, steps):
    for n in order:
        k = n["kind"]
        if k == "num":
            n["value"], n["expr"] = float(n["text"]), n["text"]
            steps.append({"type": "push", "text": f"push {n['text']}"})
        elif k == "var":
            n["value"], n["expr"] = variables[n["text"]], n["text"]
            steps.append({"type": "push", "text": f"{n['text']} → {fmt(n['value'])}"})
        elif k == "unary":
            c = n["children"][0]
            n["value"] = -c["value"] if n["op"] == "neg" else c["value"]
            sign = "-" if n["op"] == "neg" else "+"
            n["expr"] = f"({sign}{c['expr']})"
            steps.append({"type": "compute", "text": f"{sign}{fmt(c['value'])} = {fmt(n['value'])}",
                          "subexpression": n["expr"], "result": fmt(n["value"])})
        else:
            l, r = n["children"]
            n["expr"] = f"({l['expr']} {n['op']} {r['expr']})"
            if n["op"] == "/" and r["value"] == 0:
                raise ExpressionError("division_by_zero",
                                      f"Division by zero in {n['expr']}: divisor evaluates to 0 (operator at position {n['pos'] + 1})", n["pos"])
            a, b = l["value"], r["value"]
            n["value"] = {"+": a + b, "-": a - b, "*": a * b, "/": (a / b if b else 0)}[n["op"]]
            steps.append({"type": "compute", "text": f"{fmt(a)} {n['op']} {fmt(b)} = {fmt(n['value'])}",
                          "subexpression": n["expr"], "result": fmt(n["value"])})


def render_tree(root):
    """Text tree, iterative. Leaf/operator labels carry computed values when known."""
    def label(n):
        base = {"num": n.get("text"), "var": n.get("text"), "unary": "neg" if n.get("op") == "neg" else "pos"}.get(n["kind"], n.get("op"))
        if n["kind"] == "binary":
            base = {"*": "×", "/": "÷"}.get(base, base)
        if n["kind"] == "unary":
            base = "−(unary)" if n["op"] == "neg" else "+(unary)"
        return base + (f"  = {fmt(n['value'])}" if "value" in n and n["kind"] != "num" else "")
    lines, stack = [], [(root, "", "", True)]
    while stack:
        n, pre, child_pre, _ = stack.pop()
        lines.append(pre + label(n))
        kids = n["children"]
        for i in range(len(kids) - 1, -1, -1):
            last = i == len(kids) - 1
            stack.append((kids[i], child_pre + ("└── " if last else "├── "),
                          child_pre + ("    " if last else "│   "), last))
    return "\n".join(lines)


def parse_variables(variables):
    clean = {}
    for name, val in (variables or {}).items():
        name = str(name).strip()
        if not NAME_RE.match(name):
            raise ExpressionError("invalid_variable", f"Invalid variable name '{name}': use letters, digits and underscores, not starting with a digit")
        s = str(val).strip().replace("−", "-")
        if not NUM_RE.match(s):
            raise ExpressionError("invalid_variable", f"Variable '{name}' has a non-numeric value '{val}'")
        clean[name] = float(s)
    return clean


def evaluate(expression, variables=None):
    """Full pipeline. Always returns a dict; on failure ok=False with partial trace."""
    res = {"ok": False, "expression": expression, "tokens": [], "postfix": [], "parse_trace": [],
           "steps": [], "tree": "", "result": None, "error": None}
    try:
        vars_ = parse_variables(variables)
        toks = tokenize(expression)
        res["tokens"] = [{"type": t["type"], "text": t["text"]} for t in toks]
        try:
            postfix = to_postfix(toks, res["parse_trace"])
        finally:
            pass
        res["postfix"] = [p["label"] for p in postfix]
        for p in postfix:
            if p["type"] == "var" and p["text"] not in vars_:
                raise ExpressionError("undefined_variable", f"Undefined variable '{p['text']}' at position {p['pos'] + 1}", p["pos"])
        root, order = build_tree(postfix)
        try:
            evaluate_nodes(order, vars_, res["steps"])
        finally:
            res["tree"] = render_tree(root)
        res["result"] = fmt(root["value"])
        res["ok"] = True
    except ExpressionError as e:
        res["error"] = e.to_dict()
    return res


def main():
    ap = argparse.ArgumentParser(description="Observatory expression evaluator")
    ap.add_argument("expression", nargs="?")
    ap.add_argument("--var", "-v", action="append", default=[], help="name=value (repeatable)")
    a = ap.parse_args()
    vs = {}
    for item in a.var:
        k, _, v = item.partition("=")
        vs[k] = v

    def run(e):
        r = evaluate(e, vs)
        print("Postfix:", " ".join(r["postfix"]))
        for s in r["steps"]:
            if s["type"] == "compute":
                print(f"  {s['subexpression']:<30} {s['text']}")
        if r["tree"]:
            print("Tree:\n" + r["tree"])
        print("Result:", r["result"]) if r["ok"] else print("Error:", r["error"]["message"])

    if a.expression:
        run(a.expression)
    else:
        print("Enter expressions (blank to quit). Set variables with: name = value")
        while True:
            line = input("> ").strip()
            if not line:
                break
            m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", line)
            if m:
                vs[m.group(1)] = m.group(2)
            else:
                run(line)


if __name__ == "__main__":
    main()