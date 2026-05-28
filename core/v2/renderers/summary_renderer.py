"""Summary renderer — produces human-readable view summary for frontend status bar.

IR doesn't know UI. All display logic lives here.
"""

from __future__ import annotations

from ..ir.view_spec import ViewSpec
from .op_renderer import render_op


def render_summary(view_spec: ViewSpec, locale: str = "zh") -> str:
    """Render a one-line summary of the current view state.

    Example: '年份: 2010 ~ 2015 → 按 销售额 降序 → 仅显示前 10 条'
    """
    parts = []
    for f in view_spec.filters:
        parts.append(render_op(f, locale))
    if view_spec.active_sort:
        parts.append(render_op(view_spec.active_sort, locale))
    if view_spec.active_limit:
        parts.append(render_op(view_spec.active_limit, locale))
    if view_spec.chart_preference:
        parts.append(render_op(view_spec.chart_preference, locale))
    return " → ".join(parts) if parts else "原始数据"
