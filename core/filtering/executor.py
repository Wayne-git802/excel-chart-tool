"""Filter executor — deterministic df filtering. No LLM involvement."""

from __future__ import annotations

import pandas as pd

from core.ir.contract import FilterSpec
from core.ir.failure import ExplicitFailure


def apply_filter(df: pd.DataFrame, fs: FilterSpec) -> pd.DataFrame | ExplicitFailure:
    """Apply FilterSpec to dataframe. Returns filtered df or ExplicitFailure.

    Returns ExplicitFailure if filter results in 0 rows.
    """
    if fs.is_empty():
        return df

    df_filtered = df.copy()

    for cond in fs.conditions:
        col = cond.column
        if col not in df_filtered.columns:
            return ExplicitFailure(
                code="invalid_filter_column",
                message=f"列 '{col}' 在数据中不存在",
                recoverable=True,
                stage="execution",
                details={"column": col, "available": list(df_filtered.columns)},
            )

        op = cond.operator
        val = cond.value

        try:
            if op == "eq":
                mask = df_filtered[col] == val
            elif op == "neq":
                mask = df_filtered[col] != val
            elif op == "gt":
                mask = df_filtered[col] > val
            elif op == "lt":
                mask = df_filtered[col] < val
            elif op == "gte":
                mask = df_filtered[col] >= val
            elif op == "lte":
                mask = df_filtered[col] <= val
            elif op == "in":
                mask = df_filtered[col].isin(val)
            elif op == "between":
                mask = (df_filtered[col] >= val[0]) & (df_filtered[col] <= val[1])
            else:
                return ExplicitFailure(
                    code="invalid_filter_operator",
                    message=f"不支持的过滤操作 '{op}'",
                    recoverable=False,
                    stage="execution",
                )
            df_filtered = df_filtered[mask]
        except Exception as e:
            return ExplicitFailure(
                code="filter_execution_error",
                message=f"过滤执行失败: {e}",
                recoverable=True,
                stage="execution",
                details={"error": str(e)},
            )

    if len(df_filtered) == 0:
        return ExplicitFailure(
            code="empty_data",
            message="筛选后无数据，请调整过滤条件",
            recoverable=True,
            stage="execution",
        )

    return df_filtered
