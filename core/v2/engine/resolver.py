"""ChartResolver — dynamically compute final chart config.

Chart is NOT stored in ConversationState. It's derived from
ViewSpec (chart_preference) + current_df (materialized data).

Priority:
  1. chart_preference (if valid against current data)
  2. v10 contract fallback
  3. Safe default
"""

from __future__ import annotations

from ..ir.view_spec import ViewSpec
from ..ir.column_info import ColumnInfo


def resolve_chart(
    current_df,
    view_spec: ViewSpec,
    columns_info: list[ColumnInfo],
) -> dict:
    """
    Dynamically compute final chart configuration.

    Returns:
        {
            "chart_type": str,
            "x_column": str | None,
            "y_columns": list[str],
            "title": str,
            "source": "preference" | "v10_fallback" | "fallback",
            "degraded": bool,  # True if preference was rejected
        }
    """
    preference = view_spec.chart_preference

    if preference and preference.chart_type:
        x = preference.x_column
        y = list(preference.y_columns) if preference.y_columns else []

        # Auto-fill missing
        df_cols = list(current_df.columns)
        if not x and len(df_cols) > 0:
            x = df_cols[0]
        if not y and len(df_cols) > 1:
            y = [df_cols[1]]

        # Validate
        if x and x in df_cols and y and all(c in df_cols for c in y):
            return {
                "chart_type": preference.chart_type,
                "x_column": x,
                "y_columns": y,
                "title": preference.title or "",
                "source": "preference",
                "degraded": False,
            }

        # Preference invalid → degrade
        return _v10_fallback(current_df, columns_info, degraded=True)

    # No preference → v10 contract
    return _v10_fallback(current_df, columns_info, degraded=False)


def _v10_fallback(current_df, columns_info: list[ColumnInfo], degraded: bool) -> dict:
    """
    Phase 1: simple heuristic (first 2 columns → bar).
    Phase 2: integrate v10 contract for proper type inference.
    """
    cols = list(current_df.columns)
    if len(cols) >= 2:
        return {
            "chart_type": "bar",
            "x_column": cols[0],
            "y_columns": [cols[1]],
            "title": "",
            "source": "v10_fallback",
            "degraded": degraded,
        }
    return {
        "chart_type": "table",
        "x_column": None,
        "y_columns": [],
        "title": "",
        "source": "fallback",
        "degraded": degraded,
    }
