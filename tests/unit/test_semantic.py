"""Semantic analyzer tests — feasible_analyses from DatasetProfile."""

import pytest
from core.ir.profile import DatasetProfile, ColumnProfile
from core.semantic.analyzer import feasible_analyses


def _profile(temporal=None, categorical=None, numeric=None):
    cols = {}
    for name, st in (temporal or []):
        cols[name] = ColumnProfile(name=name, semantic_type="temporal", raw_dtype="datetime64",
                                   null_rate=0, unique_count=10, cardinality="medium")
    for name, st in (categorical or []):
        cols[name] = ColumnProfile(name=name, semantic_type="categorical", raw_dtype="object",
                                   null_rate=0, unique_count=5, cardinality="low")
    for name, st in (numeric or []):
        cols[name] = ColumnProfile(name=name, semantic_type="numeric", raw_dtype="float64",
                                   null_rate=0, unique_count=50, cardinality="high")
    return DatasetProfile(
        version="1.0", hash="abc", row_count=100, column_count=len(cols), columns=cols,
        temporal_cols=[n for n, _ in (temporal or [])],
        categorical_cols=[n for n, _ in (categorical or [])],
        numeric_cols=[n for n, _ in (numeric or [])],
    )


class TestFeasibleAnalyses:
    def test_trend_when_temporal_numeric(self):
        p = _profile(temporal=[("日期", "temporal")], numeric=[("销售额", "numeric")])
        candidates = feasible_analyses(p)
        types = [c["type"] for c in candidates]
        assert "trend" in types

    def test_comparison_when_categorical_numeric(self):
        p = _profile(categorical=[("类别", "categorical")], numeric=[("销售额", "numeric")])
        candidates = feasible_analyses(p)
        types = [c["type"] for c in candidates]
        assert "comparison" in types

    def test_correlation_when_two_numeric(self):
        p = _profile(numeric=[("身高", "numeric"), ("体重", "numeric")])
        candidates = feasible_analyses(p)
        types = [c["type"] for c in candidates]
        assert "correlation" in types

    def test_distribution_for_single_numeric(self):
        p = _profile(numeric=[("销售额", "numeric")])
        candidates = feasible_analyses(p)
        types = [c["type"] for c in candidates]
        assert "distribution" in types

    def test_empty_when_no_columns(self):
        p = _profile()
        candidates = feasible_analyses(p)
        assert candidates == []

    def test_multiple_candidates_sorted(self):
        p = _profile(
            temporal=[("日期", "temporal")],
            categorical=[("类别", "categorical")],
            numeric=[("销售额", "numeric"), ("利润", "numeric")],
        )
        candidates = feasible_analyses(p)
        # Sorted by confidence descending
        for i in range(len(candidates) - 1):
            assert candidates[i]["confidence"] >= candidates[i + 1]["confidence"]
        # Should have trend, comparison, correlation, distribution
        assert len(candidates) >= 4
