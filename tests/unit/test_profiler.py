"""Phase 1 tests — DataProfiler, semantic inference, cardinality, distribution."""

import pandas as pd
import pytest

from core.ir.profile import DatasetProfile
from core.profiling.semantic_inference import infer_semantic_type
from core.profiling.cardinality import classify_cardinality
from core.profiling.distribution import detect_distribution
from core.profiling.profiler import DataProfiler


class TestSemanticInference:
    def test_temporal_by_dtype(self):
        assert infer_semantic_type({"name": "日期", "dtype": "datetime64", "dtype_cn": "日期"}) == "temporal"

    def test_numeric_by_dtype(self):
        assert infer_semantic_type({"name": "销售额", "dtype": "float64", "dtype_cn": "数值"}) == "numeric"

    def test_categorical_by_dtype_cn(self):
        assert infer_semantic_type({"name": "类别", "dtype": "object", "dtype_cn": "分类"}) == "categorical"

    def test_temporal_by_name_pattern(self):
        assert infer_semantic_type({"name": "创建时间", "dtype": "object", "dtype_cn": ""}) == "temporal"

    def test_categorical_by_name_pattern(self):
        assert infer_semantic_type({"name": "城市", "dtype": "object", "dtype_cn": ""}) == "categorical"

    def test_text_by_dtype(self):
        assert infer_semantic_type({"name": "备注", "dtype": "object", "dtype_cn": ""}) == "text"

    def test_unknown(self):
        assert infer_semantic_type({"name": "xyz", "dtype": "unknown_type", "dtype_cn": ""}) == "UNKNOWN"

    def test_temporal_name_not_numeric(self):
        """Column named with temporal patterns but dtype is numeric → stays numeric."""
        assert infer_semantic_type({"name": "年份", "dtype": "int64", "dtype_cn": "数值"}) == "numeric"


class TestCardinality:
    def test_low(self):
        assert classify_cardinality(5, 100) == "low"

    def test_medium(self):
        assert classify_cardinality(50, 1000) == "medium"

    def test_high(self):
        assert classify_cardinality(200, 1000) == "high"

    def test_small_dataset(self):
        assert classify_cardinality(9, 10) == "high"  # 9/10 = 0.9


class TestDistribution:
    def test_right_skewed(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        assert detect_distribution(vals) == "right_skewed"

    def test_left_skewed(self):
        vals = [100, 99, 98, 97, 96, 95, 94, 93, 92, 1]
        assert detect_distribution(vals) == "left_skewed"

    def test_insufficient_data(self):
        assert detect_distribution([1, 2]) is None
        assert detect_distribution([]) is None

    def test_constant(self):
        assert detect_distribution([5, 5, 5, 5]) is None


class TestDataProfiler:
    def test_enhance_basic(self):
        df = pd.DataFrame({
            "日期": pd.date_range("2025-01-01", periods=5),
            "销售额": [100.0, 200.0, 150.0, 300.0, 250.0],
            "类别": ["A", "B", "A", "C", "B"],
        })
        columns = [
            {"name": "日期", "dtype": "datetime64", "dtype_cn": "日期", "unique_count": 5, "null_pct": 0, "min": None, "max": None, "mean": None},
            {"name": "销售额", "dtype": "float64", "dtype_cn": "数值", "unique_count": 5, "null_pct": 0, "min": 100.0, "max": 300.0, "mean": 200.0},
            {"name": "类别", "dtype": "object", "dtype_cn": "分类", "unique_count": 3, "null_pct": 0, "min": None, "max": None, "mean": None},
        ]

        profile = DataProfiler.enhance(columns, df)
        assert isinstance(profile, DatasetProfile)
        assert profile.version == "1.0"
        assert len(profile.hash) == 12
        assert profile.row_count == 5
        assert profile.column_count == 3

        assert profile.temporal_cols == ["日期"]
        assert profile.numeric_cols == ["销售额"]
        assert profile.categorical_cols == ["类别"]

        assert profile.columns["销售额"].mean == 200.0
        assert profile.columns["销售额"].median is not None
        assert profile.columns["日期"].semantic_type == "temporal"

    def test_enhance_empty(self):
        df = pd.DataFrame()
        profile = DataProfiler.enhance([], df)
        assert profile.row_count == 0
        assert profile.temporal_cols == []

    def test_enhance_unknown_col(self):
        df = pd.DataFrame({"备注": ["hello", "world"]})
        columns = [
            {"name": "备注", "dtype": "object", "dtype_cn": "", "unique_count": 2, "null_pct": 0, "min": None, "max": None, "mean": None},
        ]
        profile = DataProfiler.enhance(columns, df)
        assert profile.columns["备注"].semantic_type == "text"

    def test_profile_to_dict_serializable(self):
        import json
        df = pd.DataFrame({"x": [1, 2, 3]})
        columns = [{"name": "x", "dtype": "int64", "dtype_cn": "数值", "unique_count": 3, "null_pct": 0, "min": 1, "max": 3, "mean": 2.0}]
        profile = DataProfiler.enhance(columns, df)
        d = profile.to_dict()
        assert json.dumps(d)  # must not raise
