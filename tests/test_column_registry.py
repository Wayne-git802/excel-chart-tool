"""Tests for ColumnRegistry — single source of truth for column type semantics."""

import pytest
import pandas as pd
from core.contract.registry import build_column_registry, ColumnMeta


class TestBuildColumnRegistry:

    def test_standard_columns(self):
        """int64 numeric, object categorical."""
        cols = [
            {"name": "category", "dtype": "object", "dtype_cn": "分类"},
            {"name": "value1", "dtype": "int64", "dtype_cn": "数值"},
            {"name": "value2", "dtype": "float64", "dtype_cn": "数值"},
        ]
        r = build_column_registry(cols)

        assert r["category"].is_categorical
        assert not r["category"].is_numeric
        assert not r["category"].is_temporal

        assert r["value1"].is_numeric
        assert r["value2"].is_numeric

    def test_integer_category_still_numeric(self):
        """dtype_cn='整数分类' should still detect numeric via raw dtype."""
        cols = [
            {"name": "身高（cm）", "dtype": "int64", "dtype_cn": "整数分类"},
            {"name": "体重（kg）", "dtype": "int64", "dtype_cn": "整数分类"},
        ]
        r = build_column_registry(cols)

        assert r["身高(cm)"].is_numeric, "int64 should be numeric regardless of dtype_cn"
        assert r["体重(kg)"].is_numeric
        assert r["身高(cm)"].is_categorical  # dtype_cn puts it in category too

    def test_temporal_detection(self):
        """datetime64 and time-pattern names."""
        cols = [
            {"name": "日期", "dtype": "datetime64", "dtype_cn": "日期"},
            {"name": "年月", "dtype": "object", "dtype_cn": "分类"},
        ]
        r = build_column_registry(cols)

        assert r["日期"].is_temporal, "datetime64 should be temporal"
        assert r["年月"].is_temporal, "name contains time pattern '年' or '月'"

    def test_empty_columns(self):
        """Empty input returns empty registry."""
        r = build_column_registry([])
        assert r == {}

    def test_missing_name(self):
        """Column with no 'name' key is skipped."""
        cols = [
            {"name": "", "dtype": "int64"},
            {"name": "valid", "dtype": "int64"},
        ]
        r = build_column_registry(cols)
        assert "valid" in r
        assert "" not in r

    def test_missing_dtype_defaults(self):
        """Missing dtype/dtype_cn should default to non-numeric, non-temporal."""
        cols = [{"name": "unknown"}]
        r = build_column_registry(cols)
        assert not r["unknown"].is_numeric
        assert not r["unknown"].is_temporal
        assert not r["unknown"].is_categorical

    def test_return_type(self):
        """Returns dict of ColumnMeta."""
        cols = [{"name": "a", "dtype": "int64"}]
        r = build_column_registry(cols)
        assert isinstance(r, dict)
        assert isinstance(r["a"], ColumnMeta)
