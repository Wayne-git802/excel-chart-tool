"""OpValidator — validate operations against current schema.

Phase 1: column existence + parameter sanity checks.
Phase 2: dependency integrity / structural barriers / chart compatibility.
"""

from __future__ import annotations

from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp, Operation


def validate_op(op: Operation, columns: list[str]) -> tuple[bool, str | None]:
    """
    Validate an operation against available columns.

    Returns:
        (True, None) — valid
        (False, error_msg) — rejected, msg is user-displayable in Chinese

    Phase 1 checks:
    - FilterOp/SortOp/ChartPatchOp: column exists
    - LimitOp: n > 0
    """
    if isinstance(op, FilterOp):
        if op.column and op.column not in columns:
            return False, (
                f"列 '{op.column}' 不存在。"
                f"可用: {', '.join(columns[:10])}"
                f"{' ...' if len(columns) > 10 else ''}"
            )

    elif isinstance(op, SortOp):
        if op.column not in columns:
            return False, f"无法按 '{op.column}' 排序，该列不存在。"

    elif isinstance(op, LimitOp):
        if op.n < 0:
            return False, f"行数不能为负数: {op.n}"
        if op.n == 0:
            return False, "行数不能为 0"

    elif isinstance(op, ChartPatchOp):
        if op.x_column and op.x_column not in columns:
            return False, f"X 轴列 '{op.x_column}' 不存在"
        if op.y_columns:
            missing = [c for c in op.y_columns if c not in columns]
            if missing:
                return False, f"Y 轴列 {missing} 不存在"

    return True, None
