"""Core IR — Failure types."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExplicitFailure:
    """Business-level failure — NOT an exception. Used when system cannot proceed but
    this is an expected path (unsupported capability, invalid filter, empty data, etc.)."""

    code: str  # machine-readable: "unsupported_capability" | "invalid_filter" | "empty_data" | ...
    message: str  # human-readable
    recoverable: bool  # True → user can fix (bad filter), False → permanent (unsupported)
    stage: str  # which layer: "capability_gate" | "filter_validation" | "contract" | "execution"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "stage": self.stage,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExplicitFailure":
        return cls(
            code=d["code"],
            message=d["message"],
            recoverable=d["recoverable"],
            stage=d["stage"],
            details=d.get("details", {}),
        )
