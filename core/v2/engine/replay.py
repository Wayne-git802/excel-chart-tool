"""Replay engine — deterministic execution of operations against base data.

canonical_order: reorders operations for correct semantics (filter→sort→limit).
replay: pure function, runs operations through Backend, returns current view.
"""

from __future__ import annotations

from ..ir.view_spec import ViewSpec
from ..ir.operations import FilterOp, SortOp, LimitOp


def canonical_order(view_spec: ViewSpec) -> tuple:
    """
    Reorder operations for correct execution semantics.

    User action history may be:
      FilterOp(A) → LimitOp(3) → SortOp(desc) → FilterOp(B)

    Normalized to:
      FilterOp(A) → FilterOp(B) → SortOp(desc) → LimitOp(3)

    Rules:
      1. FilterOp: keep user order (all active)
      2. SortOp: only the last one
      3. LimitOp: only the last one, always after Sort
      4. ChartPatchOp: not included (doesn't affect data)

    ViewSpec.operations preserves user action history for undo.
    canonical_order is only called during replay.
    """
    result = list(view_spec.filters)

    sort = view_spec.active_sort
    if sort:
        result.append(sort)

    limit = view_spec.active_limit
    if limit:
        result.append(limit)

    return tuple(result)


def replay(base_data, view_spec: ViewSpec, backend) -> "Any":
    """
    Execute all operations from base_data through backend.

    Pure function: no mutation of base_data, no global state, no caching.
    Full replay every call — no incremental materialize in Phase 1.
    Does NOT import pandas — all data ops go through backend.
    """
    data = backend.copy(base_data)
    ops = canonical_order(view_spec)

    for op in ops:
        if isinstance(op, FilterOp):
            data = backend.filter(data, op)
        elif isinstance(op, SortOp):
            data = backend.sort(data, op)
        elif isinstance(op, LimitOp):
            data = backend.limit(data, op)
        # ChartPatchOp: does not affect data

    return data
