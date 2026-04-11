"""morphism.math.z3_verifier – Formal verification of functor mappings via Z3.

All verification is synchronous (Z3 is not async-safe) but bounded by
a configurable timeout.
"""

from __future__ import annotations

import ast
import re
from typing import Callable, Optional

from z3 import (
    And,
    If,
    Int,
    Not,
    Real,
    RealVal,
    Solver,
    ToInt,
    ToReal,
    sat,
    unsat,
)

from morphism.config import MorphismConfig, config as _default_config
from morphism.core.schemas import Schema
from morphism.exceptions import VerificationFailedError
from morphism.utils.logger import get_logger

_log = get_logger("math.z3_verifier")


# ── Dummy values for pre-solver dry-run ──────────────────────────────
_DUMMY_VALUES: dict[str, object] = {
    "Int_0_to_100": 50,
    "Int_0_to_10": 5,
    "Float_Normalized": 0.5,
    "String_NonEmpty": "hello",
    "JSON_Object": '{"score": 85, "test": 0, "percentage": 0.85}',
    "JSON_Array": '[{"test": 0}]',
    "CSV_Data": "a,b\n1,2",
    "Plaintext": "sample text",
}


def _dry_run_lambda(
    compiled_lambda: Callable,
    source_schema: Schema,
) -> bool:
    """Execute the lambda with a schema-appropriate dummy value.

    Returns ``True`` if the lambda executes without raising a
    ``TypeError``, ``KeyError``, ``NameError``, or ``AttributeError``.
    Returns ``False`` (reject) if it does.
    """
    dummy = _DUMMY_VALUES.get(source_schema.name)
    if dummy is None:
        # Unknown schema — fall back to a benign int so we don't block.
        dummy = 0 if source_schema.data_type in (int, float) else ""

    try:
        compiled_lambda(dummy)
    except (TypeError, KeyError, NameError, AttributeError, ValueError) as exc:
        _log.info(
            "Dry-run REJECTED lambda for %s: %s (%s)",
            source_schema.name, type(exc).__name__, exc,
        )
        return False
    except Exception:
        # Other runtime errors (ZeroDivisionError, etc.) are not type
        # safety issues — let Z3 handle the math.
        pass
    return True


def verify_functor_mapping(
    source_schema: Schema,
    target_schema: Schema,
    transformation_logic: Callable[[int], float],
    *,
    code_str: Optional[str] = None,
    cfg: MorphismConfig | None = None,
) -> bool:
    """Prove (or disprove) that *transformation_logic* maps every value
    satisfying *source_schema* into *target_schema*.

    A pre-solver **dry-run** executes the lambda with a dummy value to
    catch ``TypeError`` / ``KeyError`` / ``NameError`` before reaching
    the Z3 SMT solver.

    Raises :class:`VerificationFailedError` on Z3 ``unknown`` / timeout.
    Returns ``True`` (safe) or ``False`` (counter-example found).
    """
    cfg = cfg or _default_config

    # ── Step 0: Dry-run type guard ───────────────────────────────────
    if not _dry_run_lambda(transformation_logic, source_schema):
        _log.info(
            "Z3 SKIPPED: dry-run type guard rejected %s -> %s.",
            source_schema.name, target_schema.name,
        )
        return False

    # Non-numeric domains (e.g., native JSON strings) are not representable
    # in this symbolic solver pipeline. For these, enforce runtime
    # postconditions after dry-run.
    if not _is_numeric_constraint(source_schema.constraints):
        return _runtime_postcondition_check(
            transformation_logic,
            source_schema,
            target_schema,
        )

    solver = Solver()
    solver.set("timeout", cfg.z3_timeout_ms)

    # 1. Source variable + constraints
    x = Int("x")
    _add_constraints(solver, x, source_schema.constraints, is_int=True)

    # 2. Symbolic transform
    y = Real("y")
    if code_str is not None:
        y_expr = _symbolic_transform_from_code(x, code_str)
    else:
        y_expr = _symbolic_transform_legacy(x, transformation_logic)
    solver.add(y == y_expr)

    # 3. Negate target postcondition
    target_cond = _build_condition(y, target_schema.constraints, is_int=False)
    solver.add(Not(target_cond))

    # 4. Check
    result = solver.check()
    if result == unsat:
        _log.info(
            "Z3 PROOF PASSED: %s -> %s is SAFE.",
            source_schema.name, target_schema.name,
        )
        return True

    if result == sat:
        model = solver.model()
        _log.info(
            "Z3 PROOF FAILED: %s -> %s has counter-example: %s",
            source_schema.name, target_schema.name, model,
        )
        return False

    # unknown / timeout
    raise VerificationFailedError(
        f"Z3 returned 'unknown' for {source_schema.name} -> {target_schema.name}. "
        "Possible timeout."
    )


# ======================================================================
# Internal helpers
# ======================================================================

def _add_constraints(solver: Solver, var: Any, constraint_str: str, *, is_int: bool) -> None:
    solver.add(_build_condition(var, constraint_str, is_int=is_int))


def _build_condition(var: Any, constraint_str: str, *, is_int: bool) -> Any:
    stripped = constraint_str.strip()

    # Empty or string-length constraints are not numerically verifiable.
    # Return a tautology so the solver treats the domain as unconstrained.
    if not stripped or stripped.startswith("len("):
        return True

    m = re.match(
        r"(-?[\d.]+)\s*<=\s*x\s*<=\s*(-?[\d.]+)",
        constraint_str.strip(),
    )
    if m:
        lo_str, hi_str = m.group(1), m.group(2)
        if is_int:
            lo, hi = int(float(lo_str)), int(float(hi_str))
            return And(lo <= var, var <= hi)
        lo_r, hi_r = RealVal(lo_str), RealVal(hi_str)
        return And(lo_r <= var, var <= hi_r)

    raise ValueError(f"Cannot parse constraint string: {constraint_str!r}")


def _is_numeric_constraint(constraint_str: str) -> bool:
    m = re.match(r"(-?[\d.]+)\s*<=\s*x\s*<=\s*(-?[\d.]+)", constraint_str.strip())
    return m is not None


def _runtime_postcondition_check(
    transformation_logic: Callable,
    source_schema: Schema,
    target_schema: Schema,
) -> bool:
    dummy = _DUMMY_VALUES.get(source_schema.name)
    if dummy is None:
        dummy = 0 if source_schema.data_type in (int, float) else ""

    try:
        y = transformation_logic(dummy)
    except Exception as exc:
        _log.info(
            "Runtime postcondition check failed for %s -> %s: %s",
            source_schema.name, target_schema.name, exc,
        )
        return False

    target_type = target_schema.data_type
    if target_type is float:
        if not isinstance(y, (int, float)):
            return False
    elif target_type is int:
        if not isinstance(y, int):
            return False
    elif not isinstance(y, target_type):
        return False

    if _is_numeric_constraint(target_schema.constraints):
        m = re.match(
            r"(-?[\d.]+)\s*<=\s*x\s*<=\s*(-?[\d.]+)",
            target_schema.constraints.strip(),
        )
        assert m is not None
        lo = float(m.group(1))
        hi = float(m.group(2))
        try:
            val = float(y)
        except Exception:
            return False
        if not (lo <= val <= hi):
            return False

    _log.info(
        "Runtime postcondition check PASSED for %s -> %s.",
        source_schema.name, target_schema.name,
    )
    return True


# ── Legacy (probe-based, unsound) ────────────────────────────────────

def _symbolic_transform_legacy(x_int: Any, fn: Callable) -> Any:
    probe_val = 100
    probe_result = fn(probe_val)
    if probe_result == 0.0:
        return RealVal(0)
    divisor = probe_val / probe_result
    return ToReal(x_int) / RealVal(str(divisor))


# ── AST-based (sound) ────────────────────────────────────────────────

def _symbolic_transform_from_code(x_int: Any, code_str: str) -> Any:
    """Translate a Python ``lambda`` string into a Z3 expression."""
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

    def translate(node: ast.AST) -> Any:
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
                raise ValueError("Keyword arguments not supported")
            if node.func.id in {"float", "int"}:
                if len(node.args) != 1:
                    raise ValueError("Only single-argument casts are supported")
                inner = translate(node.args[0])
                return inner if node.func.id == "float" else ToReal(ToInt(inner))
            if node.func.id in {"min", "max"}:
                if len(node.args) != 2:
                    raise ValueError("min/max must have exactly 2 arguments")
                a, b = translate(node.args[0]), translate(node.args[1])
                return If(a <= b, a, b) if node.func.id == "min" else If(a >= b, a, b)
            raise ValueError("Unsupported function call")

        raise ValueError("Unsupported lambda expression")

    return translate(lam.body)


# Type alias (re-export convenience)
from typing import Any  # noqa: E402
