"""schemas.py – Category-theoretic Schema primitives for the Morphism engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type


@dataclass(frozen=True, eq=True)
class Schema:
    """A Schema object represents a typed domain with mathematical constraints.

    Attributes:
        name:        Human-readable identifier (e.g. ``Int_0_to_100``).
        data_type:   The Python type that values in this domain inhabit.
        constraints: A string encoding mathematical bounds, consumed later by
                     the Z3 verifier (e.g. ``"0 <= x <= 100"``).
    """

    name: str
    data_type: Type
    constraints: str

    # ------------------------------------------------------------------
    # Equality is structural: two schemas match iff every field matches.
    # frozen=True + eq=True on the dataclass already provides __eq__
    # and __hash__ via all fields.
    # ------------------------------------------------------------------

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
