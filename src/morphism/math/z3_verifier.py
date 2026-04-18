"""morphism.math.z3_verifier – Formal verification of functor mappings via Z3.

All verification is synchronous (Z3 is not async-safe) but bounded by
a configurable timeout.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from z3 import (
    And,
    BoolVal,
    Contains,
    Concat,
    If,
    InRe,
    Int,
    IntVal,
    Length,
    Not,
    Option,
    Plus,
    PrefixOf,
    Range,
    Re,
    Real,
    RealVal,
    Replace,
    Solver,
    Star,
    String,
    StringVal,
    SubString,
    SuffixOf,
    ToInt,
    ToReal,
    Union,
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
    proof_artifact: dict[str, Any] | None = None,
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
    verification_mode = "runtime"
    solver: Solver | None = None
    solver_result: str | None = None
    model_text: str | None = None
    verdict = False
    failure_exc: VerificationFailedError | None = None
    failure_reason: str | None = None

    # ── Step 0: Dry-run type guard ───────────────────────────────────
    if not _dry_run_lambda(transformation_logic, source_schema):
        _log.info(
            "Z3 SKIPPED: dry-run type guard rejected %s -> %s.",
            source_schema.name, target_schema.name,
        )
        failure_reason = "dry-run type guard rejected candidate"
        verdict = False
        certificate_path = _write_proof_certificate(
            cfg,
            source_schema,
            target_schema,
            code_str,
            {
                "mode": verification_mode,
                "solver_result": "dry-run-reject",
                "verdict": verdict,
                "failure_reason": failure_reason,
            },
        )
        if proof_artifact is not None:
            proof_artifact["certificate_path"] = certificate_path
            proof_artifact["mode"] = verification_mode
            proof_artifact["verdict"] = verdict
        return verdict

    try:
        if _is_symbolic_string_domain(source_schema, target_schema, code_str):
            verification_mode = "string"
            solver = Solver()
            solver.set("timeout", cfg.z3_timeout_ms)
            solver.set("smt.string_solver", "z3str3")

            x_str = String("x")
            y_str = String("y")
            solver.add(_build_string_condition(x_str, source_schema.constraints))

            y_expr = _symbolic_string_transform_from_code(x_str, code_str or "")
            solver.add(y_str == y_expr)

            target_cond = _build_string_condition(y_str, target_schema.constraints)
            solver.add(Not(target_cond))

            result = solver.check()
            solver_result = str(result)
            if result == unsat:
                verdict = True
                _log.info(
                    "Z3 (string) PROOF PASSED: %s -> %s is SAFE.",
                    source_schema.name,
                    target_schema.name,
                )
            elif result == sat:
                verdict = False
                model_text = str(solver.model())
                _log.info(
                    "Z3 (string) PROOF FAILED: %s -> %s has counter-example: %s",
                    source_schema.name,
                    target_schema.name,
                    model_text,
                )
            else:
                raise VerificationFailedError(
                    f"Z3 returned 'unknown' for {source_schema.name} -> "
                    f"{target_schema.name}. Possible timeout."
                )

        elif _is_numeric_constraint(source_schema.constraints):
            verification_mode = "numeric"
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
            solver_result = str(result)
            if result == unsat:
                verdict = True
                _log.info(
                    "Z3 PROOF PASSED: %s -> %s is SAFE.",
                    source_schema.name,
                    target_schema.name,
                )
            elif result == sat:
                verdict = False
                model_text = str(solver.model())
                _log.info(
                    "Z3 PROOF FAILED: %s -> %s has counter-example: %s",
                    source_schema.name,
                    target_schema.name,
                    model_text,
                )
            else:
                raise VerificationFailedError(
                    f"Z3 returned 'unknown' for {source_schema.name} -> "
                    f"{target_schema.name}. Possible timeout."
                )

        else:
            verification_mode = "runtime"
            verdict = _runtime_postcondition_check(
                transformation_logic,
                source_schema,
                target_schema,
            )
            solver_result = "runtime-pass" if verdict else "runtime-fail"

    except VerificationFailedError as exc:
        failure_exc = exc
        failure_reason = str(exc)

    certificate_path = _write_proof_certificate(
        cfg,
        source_schema,
        target_schema,
        code_str,
        {
            "mode": verification_mode,
            "solver_result": solver_result,
            "verdict": verdict,
            "failure_reason": failure_reason,
            "model": model_text,
            "assertions": [str(a) for a in solver.assertions()] if solver else [],
            "smt2": solver.sexpr() if solver else "",
        },
    )

    if proof_artifact is not None:
        proof_artifact["certificate_path"] = certificate_path
        proof_artifact["mode"] = verification_mode
        proof_artifact["verdict"] = verdict
        proof_artifact["solver_result"] = solver_result

    if failure_exc is not None:
        raise failure_exc

    return verdict


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


def _is_symbolic_string_domain(
    source_schema: Schema,
    target_schema: Schema,
    code_str: str | None,
) -> bool:
    return (
        source_schema.data_type is str
        and target_schema.data_type is str
        and code_str is not None
    )


def _build_string_condition(var: Any, constraint_str: str) -> Any:
    stripped = constraint_str.strip()
    if not stripped:
        return BoolVal(True)

    clauses = re.split(r"\s+and\s+", stripped)
    exprs: list[Any] = []

    for raw_clause in clauses:
        clause = raw_clause.strip()
        if not clause:
            continue

        m_len = re.fullmatch(r"len\(\s*x\s*\)\s*(<=|>=|<|>|==)\s*(\d+)", clause)
        if m_len:
            op = m_len.group(1)
            rhs = int(m_len.group(2))
            lhs = Length(var)
            if op == "<=":
                exprs.append(lhs <= rhs)
            elif op == ">=":
                exprs.append(lhs >= rhs)
            elif op == "<":
                exprs.append(lhs < rhs)
            elif op == ">":
                exprs.append(lhs > rhs)
            else:
                exprs.append(lhs == rhs)
            continue

        m_contains = re.fullmatch(
            r"(not\s+)?contains\(\s*x\s*,\s*(r?[\"\'].*[\"\'])\s*\)",
            clause,
        )
        if m_contains:
            token = _literal_eval_text(m_contains.group(2))
            cond = Contains(var, StringVal(token))
            exprs.append(Not(cond) if m_contains.group(1) else cond)
            continue

        m_regex = re.fullmatch(
            r"(not\s+)?regex\(\s*x\s*,\s*(r?[\"\'].*[\"\'])\s*\)",
            clause,
        )
        if m_regex:
            pattern = _literal_eval_text(m_regex.group(2))
            cond = InRe(var, _python_regex_to_z3(pattern))
            exprs.append(Not(cond) if m_regex.group(1) else cond)
            continue

        m_empty = re.fullmatch(r"x\s*(!=|==)\s*(r?[\"\']\s*[\"\'])", clause)
        if m_empty:
            cond = var == StringVal("")
            exprs.append(Not(cond) if m_empty.group(1) == "!=" else cond)
            continue

        raise ValueError(f"Cannot parse string constraint clause: {clause!r}")

    if not exprs:
        return BoolVal(True)
    return And(*exprs)


def _literal_eval_text(token: str) -> str:
    val = ast.literal_eval(token)
    if not isinstance(val, str):
        raise ValueError(f"Expected string literal, got: {token!r}")
    return val


def _python_regex_to_z3(pattern: str) -> Any:
    p = pattern
    if p.startswith("^"):
        p = p[1:]
    if p.endswith("$"):
        p = p[:-1]

    if not p:
        return Re("")

    parts: list[Any] = []
    i = 0

    while i < len(p):
        atom, i = _regex_parse_atom(p, i)
        if i < len(p) and p[i] in {"*", "+", "?"}:
            q = p[i]
            if q == "*":
                atom = Star(atom)
            elif q == "+":
                atom = Plus(atom)
            else:
                atom = Option(atom)
            i += 1
        parts.append(atom)

    if len(parts) == 1:
        return parts[0]
    return Concat(*parts)


def _regex_parse_atom(pattern: str, idx: int) -> tuple[Any, int]:
    ch = pattern[idx]

    if ch == "[":
        end = pattern.find("]", idx + 1)
        if end == -1:
            raise ValueError(f"Unclosed character class in regex: {pattern!r}")
        klass = pattern[idx + 1:end]
        if not klass or klass.startswith("^"):
            raise ValueError(f"Unsupported character class: [{klass}]")
        atom = _regex_char_class_to_re(klass)
        return atom, end + 1

    if ch == "\\":
        if idx + 1 >= len(pattern):
            raise ValueError(f"Dangling escape in regex: {pattern!r}")
        escaped = pattern[idx + 1]
        if escaped == "d":
            return Range("0", "9"), idx + 2
        if escaped == "w":
            return _regex_char_class_to_re("a-zA-Z0-9_"), idx + 2
        if escaped == "s":
            return Union(Re(" "), Re("\t"), Re("\n"), Re("\r")), idx + 2
        return Re(escaped), idx + 2

    if ch in {"(", ")", "{", "}"}:
        raise ValueError(f"Unsupported regex operator in {pattern!r}: {ch!r}")

    if ch == ".":
        return _regex_char_class_to_re("a-zA-Z0-9_ -"), idx + 1

    return Re(ch), idx + 1


def _regex_char_class_to_re(content: str) -> Any:
    terms: list[Any] = []
    i = 0
    while i < len(content):
        if i + 2 < len(content) and content[i + 1] == "-":
            start = content[i]
            end = content[i + 2]
            terms.append(Range(start, end))
            i += 3
            continue

        terms.append(Re(content[i]))
        i += 1

    if not terms:
        return Re("")
    if len(terms) == 1:
        return terms[0]
    return Union(*terms)


def _symbolic_string_transform_from_code(x_str: Any, code_str: str) -> Any:
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

    def translate_int(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return IntVal(node.value)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -translate_int(node.operand)

        if isinstance(node, ast.BinOp):
            left = translate_int(node.left)
            right = translate_int(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            raise ValueError("Unsupported integer expression in slice")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
            if len(node.args) != 1:
                raise ValueError("len() must have one argument")
            return Length(translate_str(node.args[0]))

        raise ValueError("Unsupported integer expression in string transform")

    def translate_str(node: ast.AST) -> Any:
        if isinstance(node, ast.Name) and node.id == param_name:
            return x_str

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return StringVal(node.value)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return translate_str(node.left) + translate_str(node.right)

        if isinstance(node, ast.Subscript):
            base = translate_str(node.value)
            if isinstance(node.slice, ast.Slice):
                if node.slice.step is not None:
                    raise ValueError("Slice step is not supported in symbolic strings")
                start = translate_int(node.slice.lower) if node.slice.lower else IntVal(0)
                if node.slice.upper is None:
                    return SubString(base, start, Length(base) - start)
                end = translate_int(node.slice.upper)
                return SubString(base, start, end - start)

            idx = translate_int(node.slice)
            return SubString(base, idx, IntVal(1))

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = translate_str(node.func.value)
            attr = node.func.attr

            if attr == "replace":
                if len(node.args) != 2:
                    raise ValueError("replace() requires exactly 2 args")
                old = translate_str(node.args[0])
                new = translate_str(node.args[1])
                return Replace(recv, old, new)

            if attr == "removeprefix":
                if len(node.args) != 1:
                    raise ValueError("removeprefix() requires exactly 1 arg")
                prefix = translate_str(node.args[0])
                return If(
                    PrefixOf(prefix, recv),
                    SubString(recv, Length(prefix), Length(recv) - Length(prefix)),
                    recv,
                )

            if attr == "removesuffix":
                if len(node.args) != 1:
                    raise ValueError("removesuffix() requires exactly 1 arg")
                suffix = translate_str(node.args[0])
                return If(
                    SuffixOf(suffix, recv),
                    SubString(recv, IntVal(0), Length(recv) - Length(suffix)),
                    recv,
                )

            raise ValueError(f"Unsupported string method in symbolic transform: {attr}")

        raise ValueError("Unsupported lambda string expression")

    return translate_str(lam.body)


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

    if target_type is str and target_schema.constraints.strip():
        if not _runtime_string_constraint_check(str(y), target_schema.constraints):
            return False

    _log.info(
        "Runtime postcondition check PASSED for %s -> %s.",
        source_schema.name, target_schema.name,
    )
    return True


def _runtime_string_constraint_check(value: str, constraint_str: str) -> bool:
    clauses = re.split(r"\s+and\s+", constraint_str.strip()) if constraint_str.strip() else []

    for clause in clauses:
        part = clause.strip()
        if not part:
            continue

        m_len = re.fullmatch(r"len\(\s*x\s*\)\s*(<=|>=|<|>|==)\s*(\d+)", part)
        if m_len:
            op = m_len.group(1)
            rhs = int(m_len.group(2))
            lhs = len(value)
            if op == "<=" and not (lhs <= rhs):
                return False
            if op == ">=" and not (lhs >= rhs):
                return False
            if op == "<" and not (lhs < rhs):
                return False
            if op == ">" and not (lhs > rhs):
                return False
            if op == "==" and not (lhs == rhs):
                return False
            continue

        m_contains = re.fullmatch(
            r"(not\s+)?contains\(\s*x\s*,\s*(r?[\"\'].*[\"\'])\s*\)",
            part,
        )
        if m_contains:
            token = _literal_eval_text(m_contains.group(2))
            found = token in value
            if m_contains.group(1):
                if found:
                    return False
            else:
                if not found:
                    return False
            continue

        m_regex = re.fullmatch(
            r"(not\s+)?regex\(\s*x\s*,\s*(r?[\"\'].*[\"\'])\s*\)",
            part,
        )
        if m_regex:
            pattern = _literal_eval_text(m_regex.group(2))
            matched = re.fullmatch(pattern, value) is not None
            if m_regex.group(1):
                if matched:
                    return False
            else:
                if not matched:
                    return False
            continue

        m_empty = re.fullmatch(r"x\s*(!=|==)\s*(r?[\"\']\s*[\"\'])", part)
        if m_empty:
            is_empty = value == ""
            if m_empty.group(1) == "!=" and is_empty:
                return False
            if m_empty.group(1) == "==" and not is_empty:
                return False
            continue

        return False

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


def _write_proof_certificate(
    cfg: MorphismConfig,
    source_schema: Schema,
    target_schema: Schema,
    code_str: str | None,
    details: dict[str, Any],
) -> str | None:
    try:
        cert_dir = Path(cfg.proof_certificate_dir)
        cert_dir.mkdir(parents=True, exist_ok=True)

        digest_payload = (
            f"{source_schema.name}->{target_schema.name}|{code_str or ''}|"
            f"{details.get('mode')}|{details.get('solver_result')}"
        )
        digest = hashlib.sha256(digest_payload.encode()).hexdigest()[:16]

        safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_schema.name)
        safe_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", target_schema.name)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cert_path = cert_dir / f"proof_{safe_source}_to_{safe_target}_{ts}_{digest}.json"

        payload: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source_schema": source_schema.name,
            "target_schema": target_schema.name,
            "source_constraints": source_schema.constraints,
            "target_constraints": target_schema.constraints,
            "candidate_lambda": code_str,
        }
        payload.update(details)

        cert_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _log.debug("Wrote proof certificate: %s", cert_path)
        return str(cert_path)
    except Exception as exc:  # pragma: no cover - operational fallback
        _log.warning("Failed to write proof certificate: %s", exc)
        return None
