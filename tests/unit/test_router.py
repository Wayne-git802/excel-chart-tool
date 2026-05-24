"""Tests for ConversationRouter, RouteDecision, and MiniChartPlanner."""
import sys
sys.path.insert(0, r"C:\Users\admin\Desktop\excel-chart-tool")

import pytest
from services.router import RouteDecision, ConversationRouter
from services.router.mini_chart_planner import plan_chart
from services.router.conversation_router import TOOL_POLICY, ROUTE_MODE


@pytest.fixture
def sample_columns():
    return [
        {"name": "日期", "dtype_cn": "日期"},
        {"name": "销售额", "dtype_cn": "数值"},
        {"name": "利润", "dtype_cn": "数值"},
        {"name": "类别", "dtype_cn": "文本"},
    ]


@pytest.fixture
def router():
    return ConversationRouter()


# ═══════════════════════════════════════════════════════════════
# RouteDecision tests
# ═══════════════════════════════════════════════════════════════

class TestRouteDecision:
    """Test the RouteDecision dataclass."""

    def test_route_decision_fields(self):
        rd = RouteDecision(
            route="greeting",
            execution_mode="single_reply",
            confidence=1.0,
            entities={},
            tool_policy={},
        )
        assert rd.route == "greeting"
        assert rd.execution_mode == "single_reply"
        assert rd.confidence == 1.0
        assert rd.entities == {}
        assert rd.tool_policy == {}

    def test_route_decision_defaults(self):
        rd = RouteDecision(
            route="analysis",
            execution_mode="react",
            confidence=0.6,
            entities={},
            tool_policy={},
        )
        assert rd.route == "analysis"
        assert rd.execution_mode == "react"
        assert isinstance(rd.confidence, float)

    def test_route_decision_entities_populated(self):
        rd = RouteDecision(
            route="direct_visualization",
            execution_mode="direct_tool",
            confidence=0.95,
            entities={"chart_type": "bar"},
            tool_policy=TOOL_POLICY["direct_visualization"],
        )
        assert rd.entities["chart_type"] == "bar"


# ═══════════════════════════════════════════════════════════════
# ConversationRouter.route() tests
# ═══════════════════════════════════════════════════════════════

class TestConversationRouterRoute:
    """Test ConversationRouter.route() intent detection."""

    # ── Greeting ──

    def test_route_greeting_hello(self, router):
        decision = router.route("你好")
        assert decision.route == "greeting"
        assert decision.execution_mode == "single_reply"

    def test_route_greeting_thanks(self, router):
        decision = router.route("谢谢")
        assert decision.route == "greeting"

    def test_route_greeting_english(self, router):
        decision = router.route("hello")
        assert decision.route == "greeting"

    def test_route_greeting_bye(self, router):
        decision = router.route("再见")
        assert decision.route == "greeting"

    # ── Direct Visualization (explicit chart type + verb) ──

    def test_route_direct_vis_bar(self, router):
        """'画个柱状图' → direct_visualization (chart type + verb)."""
        decision = router.route("画个柱状图")
        assert decision.route == "direct_visualization"
        assert decision.execution_mode == "direct_tool"

    def test_route_direct_vis_scatter(self, router):
        """'画散点图' → direct_visualization."""
        decision = router.route("画散点图")
        assert decision.route == "direct_visualization"

    def test_route_direct_vis_pie(self, router):
        """'画个饼图' → direct_visualization."""
        decision = router.route("画个饼图")
        assert decision.route == "direct_visualization"

    def test_route_direct_vis_line(self, router):
        """'用折线图展示' → direct_visualization (chart + verb)."""
        decision = router.route("用折线图展示")
        assert decision.route == "direct_visualization"

    def test_route_direct_vis_heatmap(self, router):
        """'生成热力图' → direct_visualization."""
        decision = router.route("生成热力图")
        assert decision.route == "direct_visualization"

    # ── Analysis (no explicit chart + verb, or analytic intent) ──

    def test_route_analysis_trend_keyword(self, router):
        """'分析数据趋势' → analysis (analytic intent, not chart command)."""
        decision = router.route("分析数据趋势")
        assert decision.route == "analysis"

    def test_route_analysis_compare(self, router):
        """'分析分类差异' → analysis."""
        decision = router.route("分析分类差异")
        assert decision.route == "analysis"

    def test_route_analysis_sales_trend(self, router):
        """'分析销售趋势' → analysis."""
        decision = router.route("分析销售趋势")
        assert decision.route == "analysis"

    def test_route_analysis_no_verb(self, router):
        """'柱状图对比' → analysis (has chart word but NO visualization verb)."""
        decision = router.route("柱状图对比")
        assert decision.route == "analysis"

    def test_route_analysis_vague(self, router):
        """'可视化一下' → analysis (no specific chart type)."""
        decision = router.route("可视化一下数据")
        assert decision.route == "analysis"

    def test_route_analysis_default(self, router):
        """'随便看看' → analysis."""
        decision = router.route("随便看看")
        assert decision.route == "analysis"
        assert decision.execution_mode == "react"

    # ── Data Quality ──

    def test_route_data_quality_missing(self, router):
        decision = router.route("检查缺失值")
        assert decision.route == "data_quality"

    def test_route_data_quality_null(self, router):
        decision = router.route("看看空值")
        assert decision.route == "data_quality"

    def test_route_data_quality_outlier(self, router):
        decision = router.route("有没有异常值")
        assert decision.route == "data_quality"

    # ── Priority ──

    def test_route_priority_greeting_over_chart(self, router):
        """Greeting checked before visualization."""
        decision = router.route("你好画个图")
        assert decision.route == "greeting"

    # ── Confidence ──

    def test_route_confidence_greeting(self, router):
        decision = router.route("你好")
        assert decision.confidence == 1.0

    def test_route_confidence_direct_vis(self, router):
        decision = router.route("画个柱状图")
        assert decision.confidence == 0.95

    def test_route_confidence_analysis(self, router):
        decision = router.route("随便看看")
        assert decision.confidence == 0.7


# ═══════════════════════════════════════════════════════════════
# Entities extraction tests
# ═══════════════════════════════════════════════════════════════

class TestEntitiesExtraction:
    """Test chart entity extraction from direct_visualization queries."""

    def test_extract_scatter(self, router):
        """'画散点图看看相关性' → entities['chart_type'] = 'scatter'."""
        decision = router.route("画散点图看看相关性")
        assert decision.route == "direct_visualization"
        assert decision.entities.get("chart_type") == "scatter"

    def test_extract_line(self, router):
        """'画折线图展示趋势' → entities['chart_type'] = 'line'."""
        decision = router.route("画折线图展示趋势")
        assert decision.route == "direct_visualization"
        assert decision.entities.get("chart_type") == "line"

    def test_extract_bar(self, router):
        """'生成柱状图' → entities['chart_type'] = 'bar'."""
        decision = router.route("生成柱状图")
        assert decision.route == "direct_visualization"
        assert decision.entities.get("chart_type") == "bar"

    def test_extract_pie(self, router):
        """'画饼图看占比' → entities['chart_type'] = 'pie'."""
        decision = router.route("画饼图看占比")
        assert decision.route == "direct_visualization"
        assert decision.entities.get("chart_type") == "pie"


# ═══════════════════════════════════════════════════════════════
# Tool policy tests
# ═══════════════════════════════════════════════════════════════

class TestToolPolicy:
    """Test tool_policy generation per route."""

    def test_tool_policy_greeting_empty(self, router):
        decision = router.route("你好")
        assert decision.tool_policy == {}

    def test_tool_policy_direct_vis(self, router):
        """Direct visualization: chart_builder only, max_calls=1."""
        decision = router.route("画个柱状图")
        assert "chart_builder" in decision.tool_policy
        assert decision.tool_policy["chart_builder"]["enabled"] is True
        assert decision.tool_policy["chart_builder"]["max_calls"] == 1
        assert decision.tool_policy["chart_builder"]["allow_fallback"] is False

    def test_tool_policy_data_quality(self, router):
        decision = router.route("检查缺失值")
        assert "data_query" in decision.tool_policy
        assert decision.tool_policy["data_query"]["enabled"] is True
        assert decision.tool_policy["data_query"]["max_calls"] == 1
        assert "chart_builder" not in decision.tool_policy

    def test_tool_policy_analysis(self, router):
        decision = router.route("随便看看")
        assert "data_query" in decision.tool_policy
        assert "chart_builder" in decision.tool_policy
        assert "hypothesis_test" in decision.tool_policy
        assert decision.tool_policy["data_query"]["allow_fallback"] is True
        assert decision.tool_policy["chart_builder"]["allow_fallback"] is True

    def test_tool_policy_disabled_by_default(self, router):
        decision = router.route("你好")
        assert "chart_builder" not in decision.tool_policy
        assert "data_query" not in decision.tool_policy
        assert "hypothesis_test" not in decision.tool_policy
        assert "annotation_engine" not in decision.tool_policy
        assert "story_graph" not in decision.tool_policy


# ═══════════════════════════════════════════════════════════════
# MiniChartPlanner tests
# ═══════════════════════════════════════════════════════════════

class TestMiniChartPlanner:
    """Test plan_chart() column inference."""

    def test_plan_chart_trend(self, sample_columns):
        result = plan_chart("画趋势图", sample_columns)
        assert result["chart_type"] == "line"
        assert result["x_column"] == "日期"
        assert "销售额" in result["y_columns"] or "利润" in result["y_columns"]
        assert result["aggregation"] == "sum"

    def test_plan_chart_scatter(self, sample_columns):
        result = plan_chart("散点图", sample_columns)
        assert result["chart_type"] == "scatter"
        assert result["x_column"] in ("销售额", "利润")
        assert len(result["y_columns"]) >= 1
        assert result["aggregation"] is None

    def test_plan_chart_pie(self, sample_columns):
        result = plan_chart("饼图占比", sample_columns)
        assert result["chart_type"] == "pie"
        assert result["x_column"] in ("日期", "类别")

    def test_plan_chart_fallback_bar(self, sample_columns):
        result = plan_chart("画个图", sample_columns)
        assert result["chart_type"] == "bar"

    def test_plan_chart_bar_with_comparison(self, sample_columns):
        result = plan_chart("对比一下", sample_columns)
        assert result["chart_type"] == "bar"
        assert result["x_column"] in ("日期", "类别")

    def test_plan_chart_returns_all_fields(self, sample_columns):
        result = plan_chart("画个柱状图", sample_columns)
        assert "chart_type" in result
        assert "x_column" in result
        assert "y_columns" in result
        assert "aggregation" in result
        assert "title" in result
        assert result["title"] == ""

    def test_plan_chart_fallback_with_minimal_columns(self):
        columns = [
            {"name": "A", "dtype_cn": "数值"},
            {"name": "B", "dtype_cn": "数值"},
        ]
        result = plan_chart("画个图", columns)
        assert result["chart_type"] == "bar"
        assert result["x_column"] != ""
        assert len(result["y_columns"]) >= 1

    def test_plan_chart_single_column(self):
        columns = [{"name": "A", "dtype_cn": "数值"}]
        result = plan_chart("画个图", columns)
        assert result["x_column"] == "A"
        assert result["y_columns"] == []

    def test_plan_chart_no_columns(self):
        result = plan_chart("画个图", [])
        assert result["chart_type"] == "bar"
        assert result["x_column"] == ""
        assert result["y_columns"] == []
