"""Tests for ColumnInfo + extract_columns."""

import pandas as pd
from core.v2.backends.pandas_backend import PandasBackend
from core.v2.ir.column_info import ColumnInfo, extract_columns


class TestColumnInfo:
    def test_creation(self):
        c = ColumnInfo("年份", "int64", "整数")
        assert c.name == "年份"
        assert c.dtype == "int64"
        assert c.dtype_cn == "整数"

    def test_frozen(self):
        import pytest
        c = ColumnInfo("x", "int64", "整数")
        with pytest.raises(Exception):
            c.name = "y"  # type: ignore


class TestExtractColumns:
    def test_mixed_types(self):
        df = pd.DataFrame({
            "年份": [2020, 2021],
            "名称": ["a", "b"],
            "金额": [100.5, 200.3],
        })
        be = PandasBackend()
        cols = extract_columns(df, be)
        assert len(cols) == 3
        # Check dtype_cn mapping
        names = {c.name: c.dtype_cn for c in cols}
        assert names["年份"] == "整数"
        assert names["名称"] == "文本"
        assert names["金额"] == "小数"
