"""Unit tests for services.analyzer — _column_info, build_analysis, build_preview."""
import pytest
import pandas as pd
import numpy as np
import math

from services.analyzer import _column_info, build_analysis, build_preview


class TestColumnInfo:
    """Tests for _column_info()."""

    def test_bool_column_not_numeric(self):
        s = pd.Series([True, False, True, False, True], dtype=bool)
        info = _column_info("flag", s)
        assert info["dtype_cn"] in ("二值", "binary")
        assert info["unique_count"] == 2

    def test_integer_category_detected(self):
        s = pd.Series([1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 1, 2, 3, 4])
        info = _column_info("rating", s)
        assert info["dtype_cn"] == "整数分类"

    def test_numeric_detected(self):
        s = pd.Series(np.random.uniform(0, 100, 50))
        info = _column_info("score", s)
        assert info["dtype_cn"] == "数值"

    def test_category_detected(self):
        s = pd.Series(["A", "B", "C", "A", "B"])
        info = _column_info("grade", s)
        assert info["dtype_cn"] == "分类"

    def test_text_detected(self):
        s = pd.Series([f"text_{i}" for i in range(50)])
        info = _column_info("desc", s)
        assert info["dtype_cn"] == "文本"

    def test_datetime_detected(self):
        s = pd.Series(pd.date_range("2024-01-01", periods=30, freq="D"))
        info = _column_info("date", s)
        assert info["dtype_cn"] == "日期"

    def test_empty_column(self):
        s = pd.Series([np.nan] * 10, dtype=float)
        info = _column_info("void", s)
        assert info["dtype_cn"] == "空"
        assert info["unique_count"] == 0
        assert info["null_pct"] == 100.0

    def test_nan_in_stats(self):
        s = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0])
        info = _column_info("mixed", s)
        # stats computed on non-null only (4 values: 1,2,4,5)
        assert info["min"] == 1.0
        assert info["max"] == 5.0
        assert info["mean"] == 3.0
        assert info["null_pct"] == 20.0


class TestBuildAnalysis:
    """Tests for build_analysis()."""

    def test_no_nan_in_correlations(self):
        df = pd.DataFrame({
            "a": [1, 2, 3, 4, 5],
            "b": [2, 4, 6, 8, 10],
            "c": [5, 4, 3, 2, 1],
        })
        result = build_analysis(df)
        assert "top_correlations" in result
        for pair, val in result["top_correlations"].items():
            assert not math.isnan(val), f"NaN found in correlation pair: {pair}"


class TestBuildPreview:
    """Tests for build_preview()."""

    def test_nan_to_none(self):
        df = pd.DataFrame({
            "x": [1.0, np.nan, 3.0],
            "y": ["a", "b", "c"],
        })
        preview = build_preview(df)
        assert preview["preview_n"] == 3
        for i, row in enumerate(preview["rows"]):
            for val in row:
                assert val is None or not (isinstance(val, float) and math.isnan(val)), \
                    f"NaN found in preview row {i}: {row}"
        # Specifically check row 1 (index 1), col 0 is None
        assert preview["rows"][1][0] is None, f"Expected None, got {preview['rows'][1][0]}"
