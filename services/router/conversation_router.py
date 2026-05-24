from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RouteDecision:
    route: str              # greeting | direct_visualization | data_quality | analysis
    execution_mode: str     # "single_reply" | "direct_tool" | "react"
    confidence: float       # 0.0-1.0
    entities: dict          # {chart_type, x_column, y_columns, aggregation, ...}
    tool_policy: dict       # {tool_name: {enabled: bool, max_calls: int, allow_fallback: bool}}


# ---------------------------------------------------------------------------
# Capability Matrix — tool_policy templates per route
# ---------------------------------------------------------------------------
TOOL_POLICY = {
    "greeting": {},
    "direct_visualization": {
        "chart_builder": {"enabled": True, "max_calls": 1, "allow_fallback": False},
    },
    "data_quality": {
        "data_query": {"enabled": True, "max_calls": 1, "allow_fallback": False},
    },
    "analysis": {
        "data_query":       {"enabled": True, "max_calls": 3, "allow_fallback": True},
        "chart_builder":    {"enabled": True, "max_calls": 3, "allow_fallback": True},
        "hypothesis_test":  {"enabled": True, "max_calls": 2, "allow_fallback": True},
    },
}


# ---------------------------------------------------------------------------
# Route → execution_mode mapping
# ---------------------------------------------------------------------------
ROUTE_MODE = {
    "greeting":                "single_reply",
    "direct_visualization":    "direct_tool",
    "data_quality":            "direct_tool",
    "analysis":                "react",
}


# ===========================================================================
# Explicit chart command detection
# ===========================================================================
# Only trigger direct_visualization when user explicitly specifies BOTH:
#   (a) a chart type word
#   (b) a visualization verb
# Otherwise → analysis (analytic intent, need LLM to decide)

_CHART_TYPE_WORDS = [
    "柱状图", "柱形图", "条形图",
    "折线图", "曲线图",
    "饼图", "环形图",
    "散点图", "气泡图",
    "热力图",
    "箱线图", "箱形图",
    "面积图",
    "雷达图",
    "漏斗图",
    "仪表盘",
    "直方图",
    "堆叠图",
    "树图",
]

_VIS_VERBS = [
    "画", "画个", "画一张",
    "生成", "生成一个",
    "用", "用一个", "用...展示",
    "展示", "给我看",
    "绘制", "作图",
    "plot", "visualize", "draw",
    "做个", "做个图",
]


def _has_explicit_chart_command(message: str) -> bool:
    """User explicitly specified chart type AND visualization verb."""
    has_chart = any(w in message for w in _CHART_TYPE_WORDS)
    has_verb = any(v in message for v in _VIS_VERBS)
    return has_chart and has_verb


# ---------------------------------------------------------------------------
# Keyword routing rules — ordered by priority, first match wins
# ---------------------------------------------------------------------------
_GREETING_KW = ["你好", "谢谢", "hello", "thanks", "hi", "hey", "很棒", "不错", "厉害", "再见", "bye"]

_DATA_QUALITY_KW = [
    "缺失值", "缺失", "空值", "null", "残缺",
    "异常值", "outlier", "离群",
    "检查数据", "数据类型", "有几列", "数据质量", "数据完整性",
]


def _match_greeting(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _GREETING_KW)


def _match_data_quality(message: str) -> bool:
    return any(kw in message for kw in _DATA_QUALITY_KW)


# ---------------------------------------------------------------------------
# Entity extraction helpers for direct_visualization
# ---------------------------------------------------------------------------
_CHART_TYPE_KW = {
    "scatter": ["散点", "气泡"],
    "line":    ["折线", "曲线", "走势", "趋势"],
    "bar":     ["柱状", "柱形", "条形", "对比", "比较", "排名"],
    "pie":     ["饼图", "环形", "占比", "比例", "份额", "百分比"],
    "heatmap": ["热力"],
    "boxplot": ["箱线", "箱形"],
}


# ---------------------------------------------------------------------------
# ConversationRouter
# ---------------------------------------------------------------------------
class ConversationRouter:
    """Route a user query to the correct execution pipeline.

    Rules (priority order):
    1. greeting        — social / small talk
    2. data_quality    — schema inspection / null check
    3. direct_visualization — user explicitly specified chart type + verb
    4. analysis        — everything else (analytic intent → need LLM)
    """

    def __init__(self):
        self._chart_type_kw = _CHART_TYPE_KW

    def route(self, message: str) -> RouteDecision:
        """Determine intent and execution policy for a user message."""
        # Step 1: greeting
        if _match_greeting(message):
            return self._build_decision("greeting", 1.0, message)

        # Step 2: data quality
        if _match_data_quality(message):
            return self._build_decision("data_quality", 0.95, message)

        # Step 3: direct visualization (explicit chart command)
        if _has_explicit_chart_command(message):
            return self._build_decision("direct_visualization", 0.95, message)

        # Step 4: fallback — analysis (analytic intent)
        return self._build_decision("analysis", 0.7, message)

    def _build_decision(self, route: str, confidence: float, message: str) -> RouteDecision:
        """Assemble RouteDecision from route template."""
        entities = {}
        if route == "direct_visualization":
            entities = self._extract_chart_entities(message)

        return RouteDecision(
            route=route,
            execution_mode=ROUTE_MODE.get(route, "react"),
            confidence=confidence,
            entities=entities,
            tool_policy=dict(TOOL_POLICY.get(route, TOOL_POLICY["analysis"])),
        )

    def _extract_chart_entities(self, message: str) -> dict:
        """Extract chart_type from explicit chart command."""
        entities = {}
        for chart_type, keywords in self._chart_type_kw.items():
            for kw in keywords:
                if kw in message:
                    entities["chart_type"] = chart_type
                    break
            if "chart_type" in entities:
                break
        return entities
