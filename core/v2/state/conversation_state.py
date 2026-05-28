"""ConversationState — session-level state management.

Holds ViewSpec (declarative operation log), NOT current_df or chart.
current_df = replay(base_data, view_spec, backend) — derived on demand.
chart = resolve_chart(current_df, view_spec, columns_info) — derived on demand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ..ir.view_spec import ViewSpec
from ..ir.operations import Operation
from ..ir.column_info import ColumnInfo, extract_columns


@dataclass
class ConversationState:
    """Mutable session state. Only view_spec changes — replaced on apply/undo.

    No current_df or chart_spec fields — those are derived dynamically.
    """

    session_id: str
    file_key: str
    view_spec: ViewSpec = field(default_factory=ViewSpec)

    def materialize(self, base_data, backend):
        """Pure replay — for internal testing/debugging."""
        from ..engine.replay import replay
        return replay(base_data, self.view_spec, backend)

    # ── Orchestrators ─────────────────────────

    def apply_operation(
        self,
        op: Operation,
        base_data,
        columns_info: list[ColumnInfo],
        backend,
    ) -> dict:
        """Full flow: validate → apply → replay → resolve → render."""
        from ..engine.validator import validate_op
        from ..renderers.op_renderer import render_op

        col_names = [c.name for c in columns_info]
        ok, error = validate_op(op, col_names)
        if not ok:
            return {"ok": False, "error": error, "state": None}

        self.view_spec = self.view_spec.apply(op)

        state = self.to_frontend_state(base_data, columns_info, backend)
        state["last_action"] = render_op(op)
        state["ok"] = True
        return state

    def undo_operation(
        self,
        base_data,
        columns_info: list[ColumnInfo],
        backend,
    ) -> dict:
        """Undo last operation."""
        from ..renderers.op_renderer import render_op

        if not self.view_spec.operations:
            return {
                "ok": False,
                "removed": None,
                "error": "没有可撤销的操作",
                "state": None,
            }

        new_spec, removed = self.view_spec.undo()
        self.view_spec = new_spec

        state = self.to_frontend_state(base_data, columns_info, backend)
        state["removed"] = render_op(removed) if removed else None
        state["ok"] = True
        return state

    # ── Frontend serialization ────────────────

    def to_frontend_state(
        self,
        base_data,
        columns_info: list[ColumnInfo],
        backend,
    ) -> dict:
        """Convert current state to frontend-consumable JSON.

        Does NOT read dtype from df — uses columns_info (backend-agnostic).
        """
        from ..engine.replay import replay
        from ..engine.resolver import resolve_chart
        from ..renderers.summary_renderer import render_summary
        from ..renderers.op_renderer import render_op

        df = replay(base_data, self.view_spec, backend)
        chart = resolve_chart(df, self.view_spec, columns_info)

        return {
            "session_id": self.session_id,
            "row_count": backend.row_count(df),
            "total_rows": backend.row_count(base_data),
            "columns": [
                {"name": c.name, "dtype": c.dtype, "dtype_cn": c.dtype_cn}
                for c in columns_info
            ],
            "active_filters": [
                {
                    "op_id": f.op_id,
                    "type": f.filter_type,
                    "column": f.column,
                    "params": f.params,
                    "label": render_op(f),
                }
                for f in self.view_spec.filters
            ],
            "operations": [
                {
                    "op_id": op.op_id,
                    "type": type(op).__name__,
                    "label": render_op(op),
                }
                for op in self.view_spec.operations
            ],
            "sort": {
                "column": s.column,
                "direction": s.direction,
            } if (s := self.view_spec.active_sort) else None,
            "limit": (
                self.view_spec.active_limit.n
                if self.view_spec.active_limit
                else None
            ),
            "chart": chart,
            "view_summary": render_summary(self.view_spec),
            "can_undo": len(self.view_spec.operations) > 0,
        }


def create_session(file_key: str, base_data, backend) -> dict:
    """Initialize a new conversation session after file upload.

    Returns session metadata (caller stores state separately).
    """
    state = ConversationState(
        session_id=uuid.uuid4().hex[:16],
        file_key=file_key,
        view_spec=ViewSpec(),
    )
    columns = extract_columns(base_data, backend)

    return {
        "session_id": state.session_id,
        "columns": [
            {"name": c.name, "dtype": c.dtype, "dtype_cn": c.dtype_cn}
            for c in columns
        ],
        "total_rows": backend.row_count(base_data),
    }
