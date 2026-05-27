"""Phase 5 tests — Router extension, FilterContext, debug endpoints."""

import pytest

from core.ir.contract import FilterSpec, FilterCondition
from core.ir.session import FilterContext
from core.routing.router import ConversationRouter, RouteDecision


class TestRouterExtension:
    def setup_method(self):
        self.router = ConversationRouter()

    def test_clear_filter_detected(self):
        for msg in ["算了", "看全部", "清除筛选", "取消筛选", "不看筛选了"]:
            decision = self.router.route(msg)
            assert decision.route == "clear_filter", f"'{msg}' should route to clear_filter"

    def test_fact_query_detected(self):
        for msg in ["有几行数据", "多少条记录", "最高销售额", "均值是多少", "一共有几列"]:
            decision = self.router.route(msg)
            assert decision.route == "fact_query", f"'{msg}' should route to fact_query"

    def test_greeting_still_works(self):
        decision = self.router.route("你好")
        assert decision.route == "greeting"

    def test_analysis_still_works(self):
        decision = self.router.route("帮我分析销售趋势")
        assert decision.route in ("analysis", "direct_visualization")

    def test_clear_filter_before_greeting(self):
        """'算了' is clear_filter, not greeting."""
        decision = self.router.route("算了")
        assert decision.route == "clear_filter"


class TestFilterContextIntegration:
    def test_full_lifecycle(self):
        ctx = FilterContext()
        assert ctx.active_filter() is None

        # Set sticky
        fs = FilterSpec(conditions=[FilterCondition("姓名", "in", ["张三"])], persist=True)
        ctx.apply_new(fs)
        assert ctx.active_filter() == fs
        assert ctx.sticky_filter == fs

        # One-shot doesn't clear sticky
        fs2 = FilterSpec(conditions=[FilterCondition("类别", "eq", "A")], persist=False)
        ctx.apply_new(fs2)
        assert ctx.active_filter() == fs2  # one-shot wins
        assert ctx.sticky_filter == fs  # sticky preserved

        # Clear resets everything
        ctx.clear()
        assert ctx.active_filter() is None
        assert ctx.sticky_filter is None

    def test_persist_replaces_sticky(self):
        ctx = FilterContext()
        fs1 = FilterSpec(conditions=[FilterCondition("a", "eq", 1)], persist=True)
        fs2 = FilterSpec(conditions=[FilterCondition("b", "eq", 2)], persist=True)
        ctx.apply_new(fs1)
        ctx.apply_new(fs2)
        assert ctx.active_filter().conditions[0].column == "b"  # fs2 replaces fs1
