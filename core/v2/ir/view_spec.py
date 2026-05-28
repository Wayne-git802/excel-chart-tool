"""ViewSpec — declarative data view definition.

operations: tuple of Operation, stored in user action order (for undo + display).
canonical_order() in replay engine reorders for execution.
Storage order ≠ execution order — this is by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from .operations import OpClass, FilterOp, SortOp, LimitOp, ChartPatchOp, Operation


@dataclass(frozen=True)
class ViewSpec:
    """Immutable view specification. Apply/undo return new instances."""

    operations: tuple[Operation, ...] = ()

    # ── Mutation (returns new ViewSpec) ───────

    def apply(self, op: Operation) -> ViewSpec:
        """Append operation. canonical_order() handles 'only last REPLACE active' semantics.

        Design decision: apply() does NOT delete previous same-type ops.
        This preserves operation history for undo — undo can restore the
        previous SortOp/LimitOp/ChartPatchOp.
        Execution semantics (only last active) are handled by canonical_order
        and the query methods (active_sort/active_limit/chart_preference).
        """
        return ViewSpec(operations=self.operations + (op,))

    def undo(self) -> tuple[ViewSpec, Operation | None]:
        """Undo last operation. Returns (new ViewSpec, removed op)."""
        if not self.operations:
            return self, None

        last = self.operations[-1]

        if last.op_class == OpClass.APPEND:
            return ViewSpec(operations=self.operations[:-1]), last
        else:  # REPLACE
            op_type = type(last)
            prev = None
            for o in reversed(self.operations[:-1]):
                if isinstance(o, op_type):
                    prev = o
                    break
            rest = tuple(o for o in self.operations if not isinstance(o, op_type))
            if prev:
                return ViewSpec(operations=rest + (prev,)), last
            else:
                return ViewSpec(operations=rest), last

    # ── Query properties ──────────────────────

    @property
    def active_sort(self) -> SortOp | None:
        """Current active sort (last SortOp)."""
        for op in reversed(self.operations):
            if isinstance(op, SortOp):
                return op
        return None

    @property
    def active_limit(self) -> LimitOp | None:
        """Current active limit (last LimitOp)."""
        for op in reversed(self.operations):
            if isinstance(op, LimitOp):
                return op
        return None

    @property
    def chart_preference(self) -> ChartPatchOp | None:
        """User chart preference — NOT final chart. Resolved dynamically."""
        for op in reversed(self.operations):
            if isinstance(op, ChartPatchOp):
                return op
        return None

    @property
    def filters(self) -> tuple[FilterOp, ...]:
        """All active filters in user operation order."""
        return tuple(o for o in self.operations if isinstance(o, FilterOp))
