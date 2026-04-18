"""test_phase2.py – Phase 2: Z3 formal verification of functor mappings."""

from __future__ import annotations

from pathlib import Path

from morphism.core.schemas import (
    Int_0_to_100,
    Float_Normalized,
    JSON_Object,
    Schema,
    String_NonEmpty,
)
from morphism.config import MorphismConfig
from morphism.math.z3_verifier import verify_functor_mapping, _dry_run_lambda


def test_valid_functor_mapping() -> None:
    result = verify_functor_mapping(
        source_schema=Int_0_to_100,
        target_schema=Float_Normalized,
        transformation_logic=lambda x: x / 100.0,
    )
    assert result is True


def test_invalid_functor_mapping() -> None:
    result = verify_functor_mapping(
        source_schema=Int_0_to_100,
        target_schema=Float_Normalized,
        transformation_logic=lambda x: x / 50.0,
    )
    assert result is False


# ======================================================================
# Dry-run type guard tests (Stage 13)
# ======================================================================

def test_dry_run_rejects_subscript_on_string() -> None:
    """A lambda that tries x['key'] on a raw JSON string must be rejected."""
    bad_lambda = lambda x: x["score"] / 100.0  # noqa: E731
    assert _dry_run_lambda(bad_lambda, JSON_Object) is False


def test_dry_run_accepts_json_loads_lambda() -> None:
    """A lambda that parses JSON properly must pass the dry-run."""
    import json
    good_lambda = lambda x: float(json.loads(x).get("test", 0)) / 100.0  # noqa: E731
    assert _dry_run_lambda(good_lambda, JSON_Object) is True


def test_dry_run_rejects_attribute_on_string() -> None:
    """A lambda that calls .items() on a raw string must be rejected."""
    bad_lambda = lambda x: dict(x.items())  # noqa: E731
    assert _dry_run_lambda(bad_lambda, JSON_Object) is False


def test_dry_run_passes_numeric_lambda() -> None:
    """Standard numeric lambdas must pass dry-run on Int schemas."""
    good_lambda = lambda x: x / 100.0  # noqa: E731
    assert _dry_run_lambda(good_lambda, Int_0_to_100) is True


def test_verifier_rejects_bad_lambda_via_dry_run() -> None:
    """The full verify_functor_mapping must return False for type-unsafe lambdas."""
    bad_lambda = lambda x: x["score"] / 100.0  # noqa: E731
    result = verify_functor_mapping(
        source_schema=JSON_Object,
        target_schema=Float_Normalized,
        transformation_logic=bad_lambda,
    )
    assert result is False


def test_verifier_accepts_json_loads_score_lambda() -> None:
    """A properly parsed JSON lambda should pass verification for normalized float."""
    import json

    good_lambda = lambda x: float(json.loads(x)["score"]) / 100.0  # noqa: E731
    result = verify_functor_mapping(
        source_schema=JSON_Object,
        target_schema=Float_Normalized,
        transformation_logic=good_lambda,
    )
    assert result is True


def test_string_solver_proves_truncation_and_regex(tmp_path) -> None:
    src = Schema(
        name="AnyString_Unbounded",
        data_type=str,
        constraints="len(x) >= 0",
    )
    tgt = Schema(
        name="AnyString_Max5",
        data_type=str,
        constraints="len(x) <= 5",
    )

    cfg = MorphismConfig(proof_certificate_dir=str(tmp_path), z3_timeout_ms=20000)
    proof_artifact: dict[str, object] = {}

    result = verify_functor_mapping(
        source_schema=src,
        target_schema=tgt,
        transformation_logic=lambda x: x[:5],
        code_str="lambda x: x[:5]",
        cfg=cfg,
        proof_artifact=proof_artifact,
    )

    assert result is True
    assert proof_artifact.get("mode") == "string"
    cert_path = proof_artifact.get("certificate_path")
    assert isinstance(cert_path, str)
    assert tmp_path in Path(cert_path).parents


def test_string_solver_proves_prefix_token_stripping(tmp_path) -> None:
    src = Schema(
        name="PrefixedToken",
        data_type=str,
        constraints="len(x) >= 0",
    )
    tgt = Schema(
        name="TokenStripped",
        data_type=str,
        constraints="not contains(x, 'TMP_')",
    )

    cfg = MorphismConfig(proof_certificate_dir=str(tmp_path), z3_timeout_ms=10000)
    result = verify_functor_mapping(
        source_schema=src,
        target_schema=tgt,
        transformation_logic=lambda x: "",
        code_str="lambda x: ''",
        cfg=cfg,
    )

    assert result is True


def test_string_solver_proves_regex_boundary_identity(tmp_path) -> None:
    src = Schema(
        name="SlugText",
        data_type=str,
        constraints="regex(x, r'^[a-z0-9_]*$')",
    )
    tgt = Schema(
        name="SlugTextOut",
        data_type=str,
        constraints="regex(x, r'^[a-z0-9_]*$')",
    )

    cfg = MorphismConfig(proof_certificate_dir=str(tmp_path), z3_timeout_ms=10000)
    result = verify_functor_mapping(
        source_schema=src,
        target_schema=tgt,
        transformation_logic=lambda x: x,
        code_str="lambda x: x",
        cfg=cfg,
    )

    assert result is True
