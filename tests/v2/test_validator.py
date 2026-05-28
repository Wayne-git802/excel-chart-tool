"""Tests for OpValidator."""

from core.v2.engine.validator import validate_op
from core.v2.ir.operations import FilterOp, SortOp, LimitOp, ChartPatchOp

COLS = ["年份", "销售额", "品类"]


class TestValidateFilterOp:
    def test_valid(self):
        ok, err = validate_op(FilterOp("column_range", "年份"), COLS)
        assert ok
        assert err is None

    def test_column_not_found(self):
        ok, err = validate_op(FilterOp("column_range", "不存在"), COLS)
        assert not ok
        assert "不存在" in err

    def test_no_column_always_ok(self):
        ok, _ = validate_op(FilterOp("expression"), COLS)
        assert ok


class TestValidateSortOp:
    def test_valid(self):
        ok, _ = validate_op(SortOp("销售额"), COLS)
        assert ok

    def test_column_not_found(self):
        ok, err = validate_op(SortOp("不存在"), COLS)
        assert not ok
        assert "不存在" in err


class TestValidateLimitOp:
    def test_valid(self):
        ok, _ = validate_op(LimitOp(10), COLS)
        assert ok

    def test_zero(self):
        ok, err = validate_op(LimitOp(0), COLS)
        assert not ok
        assert "0" in err

    def test_negative(self):
        ok, err = validate_op(LimitOp(-1), COLS)
        assert not ok
        assert "负数" in err


class TestValidateChartPatchOp:
    def test_valid(self):
        ok, _ = validate_op(ChartPatchOp(x_column="年份", y_columns=("销售额",)), COLS)
        assert ok

    def test_x_not_found(self):
        ok, err = validate_op(ChartPatchOp(x_column="不存在"), COLS)
        assert not ok
        assert "不存在" in err

    def test_y_not_found(self):
        ok, err = validate_op(ChartPatchOp(y_columns=("不存在",)), COLS)
        assert not ok

    def test_empty_chart_ok(self):
        ok, _ = validate_op(ChartPatchOp(), COLS)
        assert ok
