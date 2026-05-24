"""BudgetController — deterministic chart budget policy.

Sole source of truth for how many charts an analysis run may produce.
No LLM calls. Pure heuristic based on data shape.
"""

from __future__ import annotations
import pandas as pd


class BudgetController:
    """Determines chart budget from data characteristics."""

    def get_budget(self, df, columns: list[dict]) -> int:
        """Returns chart budget: 1 (default) or 2 (rich data).

        Args:
            df: pandas DataFrame
            columns: list of dicts with keys name, dtype, dtype_cn
        """
        if df is None or (hasattr(df, "empty") and df.empty):
            return 1
        if not columns:
            return 1

        numeric_dtypes = {"float64", "int64", "int32", "float32"}
        numeric_cn = {"数值", "整数", "浮点"}

        numeric_cols = [
            c for c in columns
            if c.get("dtype") in numeric_dtypes
            or c.get("dtype_cn", "") in numeric_cn
        ]
        n_numeric = len(numeric_cols)

        # Time column detection
        time_patterns = {"日期", "时间", "date", "time", "年", "月", "日"}
        has_time = any(
            c.get("dtype") == "datetime64"
            or any(p in (c.get("name", "") or "").lower() for p in time_patterns)
            for c in columns
        )

        # Rule 1: 3+ numeric columns → budget 2
        if n_numeric >= 3:
            return 2

        # Rule 2: time column + 2+ numeric → budget 2
        if has_time and n_numeric >= 2:
            return 2

        # Rule 3: high cardinality categorical + 2+ numeric → budget 2
        if df is not None and n_numeric >= 2:
            for c in columns:
                dtype = c.get("dtype", "")
                if dtype in ("object", "category", "string"):
                    col_name = c.get("name", "")
                    if col_name and col_name in df.columns:
                        try:
                            n_unique = df[col_name].nunique()
                            if n_unique > 10:
                                return 2
                        except Exception:
                            pass

        # Default
        return 1
