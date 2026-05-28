"""Operation renderer — display logic for Operations.

IR knows NOTHING about UI. All human-readable rendering lives here.
"""

from __future__ import annotations

from ..ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp, Operation


def render_op(op: Operation, locale: str = "zh") -> str:
    """Render an Operation as a human-readable string.

    locale reserved for Phase 2 i18n support.
    """
    if isinstance(op, FilterOp):
        return _render_filter(op)
    if isinstance(op, SortOp):
        direction = "升序" if op.direction == "asc" else "降序"
        return f"按 {op.column} {direction}"
    if isinstance(op, LimitOp):
        return f"仅显示前 {op.n} 条"
    if isinstance(op, ChartPatchOp):
        parts = []
        if op.chart_type:
            parts.append(f"图表: {op.chart_type}")
        if op.x_column:
            parts.append(f"X: {op.x_column}")
        if op.y_columns:
            parts.append(f"Y: {', '.join(op.y_columns)}")
        return " / ".join(parts) if parts else "图表配置变更"
    return str(op)


def _render_filter(op: FilterOp) -> str:
    if op.filter_type == "column_range":
        mn = op.params.get("min", "")
        mx = op.params.get("max", "")
        return f"{op.column}: {mn} ~ {mx}"
    if op.filter_type == "value_match":
        return f"{op.column} 包含 '{op.params.get('value', '')}'"
    if op.filter_type == "expression":
        return f"{op.column} {op.params.get('op', '')} {op.params.get('value', '')}"
    return ""
