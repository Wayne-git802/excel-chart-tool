"""Tests for ConversationState — orchestrators + frontend state."""

import pytest
import pandas as pd
from core.v2.ir.operations import FilterOp, SortOp
from core.v2.ir.column_info import extract_columns
from core.v2.backends.pandas_backend import PandasBackend
from core.v2.state.conversation_state import ConversationState, create_session


@pytest.fixture
def df():
    return pd.DataFrame({
        "年份": [2020, 2021, 2019],
        "品类": ["手机", "电脑", "手机"],
        "销售额": [100, 300, 200],
    })


@pytest.fixture
def be():
    return PandasBackend()


@pytest.fixture
def cols_info(df, be):
    return extract_columns(df, be)


class TestCreateSession:
    def test_returns_metadata(self, df, be):
        meta = create_session("test.xlsx", df, be)
        assert "session_id" in meta
        assert len(meta["session_id"]) == 16
        assert len(meta["columns"]) == 3
        assert meta["total_rows"] == 3


class TestApplyOperation:
    def test_success(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        result = state.apply_operation(
            FilterOp("column_range", "年份", {"min": 2020}), df, cols_info, be
        )
        assert result["ok"]
        assert result["row_count"] == 2
        assert "last_action" in result
        assert result["can_undo"]

    def test_validation_fails_state_unchanged(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        result = state.apply_operation(
            FilterOp("column_range", "不存在"), df, cols_info, be
        )
        assert not result["ok"]
        assert result["error"] is not None
        assert result["state"] is None
        assert len(state.view_spec.operations) == 0  # unchanged

    def test_sort_updates_state(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        state.apply_operation(SortOp("销售额", "desc"), df, cols_info, be)
        assert state.view_spec.active_sort.column == "销售额"


class TestUndoOperation:
    def test_success(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        state.apply_operation(FilterOp("column_range", "年份", {"min": 2020}),
                              df, cols_info, be)
        result = state.undo_operation(df, cols_info, be)
        assert result["ok"]
        assert result["row_count"] == 3  # back to all rows
        assert "removed" in result

    def test_empty_ops(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        result = state.undo_operation(df, cols_info, be)
        assert not result["ok"]
        assert "没有可撤销" in result["error"]


class TestToFrontendState:
    def test_fields_present(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        state.apply_operation(SortOp("销售额", "asc"), df, cols_info, be)
        fs = state.to_frontend_state(df, cols_info, be)
        assert "session_id" in fs
        assert "row_count" in fs
        assert "total_rows" in fs
        assert "columns" in fs
        assert "active_filters" in fs
        assert "operations" in fs
        assert "sort" in fs
        assert "chart" in fs
        assert "view_summary" in fs
        assert "can_undo" in fs

    def test_no_pandas_dtype_leak(self, df, be, cols_info):
        state = ConversationState(session_id="test", file_key="test.xlsx")
        fs = state.to_frontend_state(df, cols_info, be)
        # columns should come from cols_info, not df internals
        col_names = [c["name"] for c in fs["columns"]]
        assert col_names == ["年份", "品类", "销售额"]
