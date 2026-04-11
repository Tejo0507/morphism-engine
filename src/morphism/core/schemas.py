"""morphism.core.schemas – Category-theoretic Schema primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type


@dataclass(frozen=True, eq=True)
class Schema:
    """A typed domain with mathematical constraints.

    Attributes
    ----------
    name:
        Human-readable identifier (e.g. ``Int_0_to_100``).
    data_type:
        The Python type that values in this domain inhabit.
    constraints:
        A string encoding mathematical bounds, consumed by the Z3
        verifier (e.g. ``"0 <= x <= 100"``).
    """

    name: str
    data_type: Type
    constraints: str

    def __repr__(self) -> str:
        return f"Schema({self.name!r}, {self.data_type.__name__}, {self.constraints!r})"


# ======================================================================
# MVP Schema Instances
# ======================================================================

Int_0_to_100: Schema = Schema(
    name="Int_0_to_100",
    data_type=int,
    constraints="0 <= x <= 100",
)

Float_Normalized: Schema = Schema(
    name="Float_Normalized",
    data_type=float,
    constraints="0.0 <= x <= 1.0",
)

String_NonEmpty: Schema = Schema(
    name="String_NonEmpty",
    data_type=str,
    constraints="len(x) > 0",
)

Int_0_to_10: Schema = Schema(
    name="Int_0_to_10",
    data_type=int,
    constraints="0 <= x <= 10",
)

# ======================================================================
# Native-command Schema Instances (Phase 8)
# ======================================================================

JSON_Object: Schema = Schema(
    name="JSON_Object",
    data_type=str,
    constraints="len(x) > 0",
)

CSV_Data: Schema = Schema(
    name="CSV_Data",
    data_type=str,
    constraints="len(x) > 0",
)

Plaintext: Schema = Schema(
    name="Plaintext",
    data_type=str,
    constraints="",
)

Pending: Schema = Schema(
    name="Pending",
    data_type=str,
    constraints="",
)
