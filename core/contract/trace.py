"""ExecutionTrace — decision ledger for the Execution Contract Layer.

Records every validation step, repair attempt, and final verdict so every
chart execution decision is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# ── trace step ────────────────────────────────────────────────

@dataclass
class TraceStep:
    """A single validation or repair step in the contract pipeline."""

    step_id: str               # "contract_validation", "column_check", etc.
    validator: str             # "ColumnValidator", "TypeValidator", etc.
    input_summary: dict        # what was checked
    result: str                # "pass" | "fail" | "repaired" | "degraded"
    before: str = ""           # original value
    after: str = ""            # repaired value
    detail: str = ""           # human-readable explanation


# ── execution trace ───────────────────────────────────────────

@dataclass
class ExecutionTrace:
    """Full decision ledger for one chart request."""

    session_id: str = ""
    timestamp: str = ""               # ISO format
    user_message: str = ""
    chart_selector_output: str = ""
    contract_input: dict = field(default_factory=dict)
    steps: list[TraceStep] = field(default_factory=list)
    final_action: str = ""            # "executed" | "rejected" | "degraded"
    final_chart_type: str = ""
    warnings: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


# ── builder ───────────────────────────────────────────────────

class TraceBuilder:
    """Fluent builder for ExecutionTrace.

    Usage:
        builder = TraceBuilder("sess-1", "对比销售额趋势")
        builder.set_selector_output("line")
        builder.add_step(TraceStep(...))
        builder.set_final("executed", "line", ["minor repair"])
        trace = builder.build(latency_ms=42.3)
    """

    def __init__(self, session_id: str, user_message: str) -> None:
        self._trace = ExecutionTrace(
            session_id=session_id,
            user_message=user_message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def set_selector_output(self, chart_type: str) -> None:
        """Record the chart type chosen by the selector before validation."""
        self._trace.chart_selector_output = chart_type

    def add_step(self, step: TraceStep) -> None:
        """Append a validation/repair step to the ledger."""
        self._trace.steps.append(step)

    def set_final(
        self,
        action: str,
        chart_type: str,
        warnings: list[str] | None = None,
    ) -> None:
        """Record the final contract verdict."""
        self._trace.final_action = action
        self._trace.final_chart_type = chart_type
        if warnings:
            self._trace.warnings.extend(warnings)

    def build(self, latency_ms: float = 0.0) -> ExecutionTrace:
        """Return the completed ExecutionTrace."""
        self._trace.latency_ms = latency_ms
        return self._trace

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for SSE or logging."""
        return asdict(self._trace)


# ── helper ────────────────────────────────────────────────────

def trace_to_dict(trace: ExecutionTrace) -> dict[str, Any]:
    """Convert an ExecutionTrace to a JSON-serializable dict.

    Uses dataclasses.asdict() internally.
    """
    return asdict(trace)
