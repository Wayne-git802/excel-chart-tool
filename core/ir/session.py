"""Core IR — Session / Ledger types."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionStep:
    """A single step in the decision chain."""

    stage: str  # "filter" | "column_select" | "chart_type"
    rule_applied: str  # because field from DSL rule
    input_summary: dict[str, Any] = field(default_factory=dict)
    output: Any = None

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "rule_applied": self.rule_applied,
            "input_summary": self.input_summary,
            "output": self.output,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionStep":
        return cls(
            stage=d["stage"],
            rule_applied=d["rule_applied"],
            input_summary=d.get("input_summary", {}),
            output=d.get("output"),
        )


@dataclass
class DecisionLedger:
    """Full decision trace for a single chart generation."""

    profile_hash: str
    contextual_hash: str = ""
    steps: list[DecisionStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_hash": self.profile_hash,
            "contextual_hash": self.contextual_hash,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionLedger":
        return cls(
            profile_hash=d["profile_hash"],
            contextual_hash=d.get("contextual_hash", ""),
            steps=[DecisionStep.from_dict(s) for s in d.get("steps", [])],
        )


@dataclass
class FilterContext:
    """Session-level filter state. Managed by deterministic state machine, never by LLM."""

    sticky_filter: Any | None = None  # FilterSpec — cross-turn inheritance
    one_shot_filter: Any | None = None  # FilterSpec — current turn only

    def active_filter(self) -> Any | None:
        """Current effective filter: one_shot wins, then sticky."""
        return self.one_shot_filter or self.sticky_filter

    def apply_new(self, fs: Any) -> None:
        """Deterministic state transition."""
        if fs.persist:
            self.sticky_filter = fs
            self.one_shot_filter = None
        else:
            self.one_shot_filter = fs

    def clear(self) -> None:
        self.sticky_filter = None
        self.one_shot_filter = None

    def to_dict(self) -> dict:
        return {
            "sticky_filter": self.sticky_filter.to_dict() if self.sticky_filter else None,
            "one_shot_filter": self.one_shot_filter.to_dict() if self.one_shot_filter else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FilterContext":
        from core.ir.contract import FilterSpec
        sticky = FilterSpec.from_dict(d["sticky_filter"]) if d.get("sticky_filter") else None
        one_shot = FilterSpec.from_dict(d["one_shot_filter"]) if d.get("one_shot_filter") else None
        return cls(sticky_filter=sticky, one_shot_filter=one_shot)
