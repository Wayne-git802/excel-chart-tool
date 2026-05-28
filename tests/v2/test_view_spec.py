"""Tests for ViewSpec — apply, undo, query, immutability."""

import pytest
from core.v2.ir.view_spec import ViewSpec
from core.v2.ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp


class TestApply:
    def test_append_filter(self):
        vs = ViewSpec()
        vs2 = vs.apply(FilterOp("column_range", "x"))
        vs3 = vs2.apply(FilterOp("value_match", "y", {"value": "a"}))
        assert len(vs3.filters) == 2
        assert vs3.operations[-1].filter_type == "value_match"

    def test_replace_sort(self):
        vs = ViewSpec().apply(SortOp("a", "asc")).apply(SortOp("b", "desc"))
        # Both SortOps stored in history for undo, but active_sort is the last one
        assert vs.active_sort.column == "b"
        assert vs.active_sort.direction == "desc"

    def test_replace_limit(self):
        vs = ViewSpec().apply(LimitOp(10)).apply(LimitOp(5))
        assert vs.active_limit.n == 5

    def test_replace_chart(self):
        vs = ViewSpec().apply(ChartPatchOp(chart_type="bar")).apply(
            ChartPatchOp(chart_type="pie"))
        assert vs.chart_preference.chart_type == "pie"

    def test_mixed_append_replace(self):
        vs = (ViewSpec()
              .apply(FilterOp("value_match", "a"))
              .apply(SortOp("b", "desc"))
              .apply(FilterOp("column_range", "c"))
              .apply(SortOp("d", "asc")))
        assert len(vs.filters) == 2
        assert vs.active_sort.column == "d"


class TestUndo:
    def test_undo_last_filter(self):
        vs = ViewSpec().apply(FilterOp("value_match", "a")).apply(
            FilterOp("value_match", "b"))
        vs2, removed = vs.undo()
        assert removed.filter_type == "value_match"
        assert removed.column == "b"
        assert len(vs2.filters) == 1

    def test_undo_sort_with_prev(self):
        vs = ViewSpec().apply(SortOp("a", "asc")).apply(SortOp("b", "desc"))
        vs2, removed = vs.undo()
        assert removed.column == "b"
        assert vs2.active_sort.column == "a"
        assert vs2.active_sort.direction == "asc"

    def test_undo_sort_no_prev(self):
        vs = ViewSpec().apply(SortOp("a", "asc"))
        vs2, removed = vs.undo()
        assert removed.column == "a"
        assert vs2.active_sort is None

    def test_undo_limit(self):
        vs = ViewSpec().apply(LimitOp(10))
        vs2, removed = vs.undo()
        assert removed.n == 10
        assert vs2.active_limit is None

    def test_undo_empty(self):
        vs = ViewSpec()
        vs2, removed = vs.undo()
        assert removed is None
        assert vs2.operations == ()

    def test_undo_chart_preference(self):
        vs = ViewSpec().apply(ChartPatchOp(chart_type="pie"))
        vs2, removed = vs.undo()
        assert removed.chart_type == "pie"
        assert vs2.chart_preference is None


class TestImmutability:
    def test_apply_returns_new(self):
        vs = ViewSpec()
        vs2 = vs.apply(FilterOp("value_match"))
        assert vs is not vs2
        assert vs.operations == ()

    def test_undo_returns_new(self):
        vs = ViewSpec().apply(FilterOp("value_match"))
        vs2, _ = vs.undo()
        assert vs is not vs2


class TestQueries:
    def test_active_sort_none(self):
        assert ViewSpec().active_sort is None

    def test_active_limit_none(self):
        assert ViewSpec().active_limit is None

    def test_chart_preference_none(self):
        assert ViewSpec().chart_preference is None

    def test_filters_empty(self):
        assert ViewSpec().filters == ()
