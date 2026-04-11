"""z3_verifier.py – Formal verification of functor mappings via Z3."""

from __future__ import annotations

from typing import Callable, Optional

from z3 import Int, Real, Solver, sat, unsat, And, If, Not, RealVal, ToInt, ToReal

from morphism_engine.schemas import Schema


def verify_functor_mapping(
    source_schema: Schema,
    target_schema: Schema,
    transformation_logic: Callable[[int], float],
    *,
    code_str: Optional[str] = None,
) -> bool:
    """Prove (or disprove) that *transformation_logic* maps every value
    satisfying *source_schema* constraints into the *target_schema* domain.

    Strategy
    --------
    We negate the target postcondition and ask Z3 whether a
    counter-example exists.  If the negation is **unsat**, the mapping
    is universally valid → return ``True``.  Otherwise return ``False``.

    MVP scope
    ---------
    Currently handles the ``Int_0_to_100 → Float_Normalized`` mapping
    pattern.  The constraint strings are parsed via simple pattern
    matching; a future version can use a proper DSL parser.
    """
    solver = Solver()

    # ------------------------------------------------------------------
    # 1. Declare source variable and add source constraints
    # ------------------------------------------------------------------
    x = Int("x")
    _add_constraints(solver, x, source_schema.constraints, is_int=True)

    # ------------------------------------------------------------------
    # 2. Apply transformation symbolically
    # ------------------------------------------------------------------
    y = Real("y")
    # Build a symbolic expression for the transformation.
    #
    # IMPORTANT: The previous MVP implementation inferred a divisor by
    # probing the callable at one point, which is UNSOUND for many
    # expressions (e.g. affine transforms). We now prefer parsing the
    # original lambda string (when available) into a Z3 expression.
    if code_str is not None:
        y_expr = _symbolic_transform_from_code(x, code_str)
    else:
        y_expr = _symbolic_transform_legacy(x, transformation_logic)
    solver.add(y == y_expr)

    # ------------------------------------------------------------------
    # 3. Negate the target postcondition
    # ------------------------------------------------------------------
    target_cond = _build_condition(y, target_schema.constraints, is_int=False)
    solver.add(Not(target_cond))

    # ------------------------------------------------------------------
    # 4. Check satisfiability of the negation
    # ------------------------------------------------------------------
    result = solver.check()
    if result == unsat:
        # No counter-example exists ⟹ mapping is universally safe.
        print(f"[Z3] PROOF PASSED: {source_schema.name} -> {target_schema.name} is SAFE.")
        return True
    else:
        model = solver.model() if result == sat else None
        print(
            f"[Z3] PROOF FAILED: {source_schema.name} -> {target_schema.name} "
            f"has counter-example: {model}"
        )
        return False


# ======================================================================
# Internal helpers
# ======================================================================

def _add_constraints(solver: Solver, var, constraint_str: str, *, is_int: bool) -> None:  # type: ignore[type-arg]
    """Parse a simple constraint string and add it to *solver*."""
    cond = _build_condition(var, constraint_str, is_int=is_int)
    solver.add(cond)


def _build_condition(var, constraint_str: str, *, is_int: bool):  # type: ignore[type-arg]
    """Return a Z3 boolean expression for *constraint_str*.

    Supported patterns (MVP):
        ``"A <= x <= B"``   →  And(A <= var, var <= B)
        ``"A.A <= x <= B.B"`` → same, with reals
    """
    import re

    # Pattern: "A <= x <= B"  or  "A.A <= x <= B.B"
    m = re.match(
        r"(-?[\d.]+)\s*<=\s*x\s*<=\s*(-?[\d.]+)",
        constraint_str.strip(),
    )
    if m:
        lo_str, hi_str = m.group(1), m.group(2)
        if is_int:
            lo, hi = int(float(lo_str)), int(float(hi_str))
            return And(lo <= var, var <= hi)
        else:
            lo_r = RealVal(lo_str)
            hi_r = RealVal(hi_str)
            return And(lo_r <= var, var <= hi_r)

    raise ValueError(f"Cannot parse constraint string: {constraint_str!r}")


def _symbolic_transform_legacy(x_int, transformation_logic: Callable) -> "z3.ArithRef":  # type: ignore[name-defined]
    """Legacy MVP transform inference (UNSOUND).

    Kept only as a fallback when the original lambda string is not
    available. Prefer :func:`_symbolic_transform_from_code`.
    """
    probe_val = 100
    probe_result = transformation_logic(probe_val)
    if probe_result == 0.0:
        return RealVal(0)
    divisor = probe_val / probe_result
    return ToReal(x_int) / RealVal(str(divisor))


def _symbolic_transform_from_code(x_int, code_str: str) -> "z3.ArithRef":  # type: ignore[name-defined]
    """Translate a Python ``lambda`` string into a Z3 arithmetic expression.

    Supported (MVP) expression forms:
      - numeric constants
      - the lambda parameter
      - +, -, *, /, unary -
      - float(<expr>), int(<expr>)

    Any other syntax raises ``ValueError``.
    """
    import ast

    try:
        tree = ast.parse(code_str, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid lambda syntax: {code_str!r}") from exc

    if not isinstance(tree, ast.Expression) or not isinstance(tree.body, ast.Lambda):
        raise ValueError(f"Expected a lambda expression, got: {code_str!r}")

    lam = tree.body
    if len(lam.args.args) != 1:
        raise ValueError("Only single-argument lambdas are supported")

    param_name = lam.args.args[0].arg

    def to_real(z):
        return ToReal(z) if str(z.sort()) == "Int" else z

    def translate(node):
        if isinstance(node, ast.Name) and node.id == param_name:
            return ToReal(x_int)

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return RealVal(str(node.value))

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -translate(node.operand)

        if isinstance(node, ast.BinOp):
            left = translate(node.left)
            right = translate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise ValueError("Unsupported binary operator")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords:
                raise ValueError("Keyword arguments are not supported")

            # Casts
            if node.func.id in {"float", "int"}:
                if len(node.args) != 1:
                    raise ValueError("Only single-argument casts are supported")
                inner = translate(node.args[0])
                if node.func.id == "float":
                    return inner
                # int() truncates; model as ToInt then cast back to Real
                return ToReal(ToInt(inner))

            # Clamps
            if node.func.id in {"min", "max"}:
                if len(node.args) != 2:
                    raise ValueError("min/max must have exactly 2 arguments")
                a = translate(node.args[0])
                b = translate(node.args[1])
                if node.func.id == "min":
                    return If(a <= b, a, b)
                return If(a >= b, a, b)

            raise ValueError("Unsupported function call")

        raise ValueError("Unsupported lambda expression")

    return translate(lam.body)
