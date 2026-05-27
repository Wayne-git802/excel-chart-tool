from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RouteDecision:
    route: str              # greeting | direct_visualization | data_quality | analysis | fact_query | clear_filter
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
    "fact_query": {
        "data_query": {"enabled": True, "max_calls": 1, "allow_fallback": False},
    },
    "clear_filter": {},
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
    "fact_query":              "single_reply",
    "clear_filter":            "single_reply",
    "analysis":                "react",
}


# ===========================================================================
# Intent scoring — replaces lexical AND-gate
# ===========================================================================
# Chart type is detected by keyword presence.
# Intent (direct command vs question vs comparison) is scored by heuristics.
# Score ≥ 3 → direct_visualization. Score ≥ 1 → analysis. Score 0 → fallback.

_CHART_TYPE_WORDS = [
    "柱状图", "柱形图", "条形图", "柱状", "条形",
    "折线图", "曲线图", "折线", "曲线",
    "饼图", "环形图", "饼图", "环形",
    "散点图", "气泡图", "散点", "气泡",
    "热力图", "热力",
    "箱线图", "箱形图", "箱线", "箱形",
    "面积图",
    "雷达图",
    "漏斗图",
    "仪表盘",
    "直方图", "直方",
    "堆叠图",
    "树图",
]

_QUESTION_PATTERNS = ["吗", "什么", "为什么", "如何", "怎么", "哪个", "哪种", "能不能", "?"]
_COMPARISON_PATTERNS = ["比较", "对比", " vs ", "还是", "哪个好", "哪种好", "更好"]
_CONTEXT_PATTERNS = ["刚才", "那个", "之前的", "上一个", "刚刚的"]


def _has_chart_word(message: str) -> bool:
    return any(w in message for w in _CHART_TYPE_WORDS)


def _is_question(message: str) -> bool:
    return any(p in message for p in _QUESTION_PATTERNS)


def _is_comparison(message: str) -> bool:
    return any(p in message.lower() for p in _COMPARISON_PATTERNS)


def _is_context_reference(message: str) -> bool:
    return any(p in message for p in _CONTEXT_PATTERNS)


def _score_direct_viz(message: str) -> int:
    """Intent score: has_chart=+2, question=-2, comparison=-1, context=-1. ≥2→direct."""
    score = 0
    if _has_chart_word(message):
        score += 2
    if _is_question(message):
        score -= 2
    if _is_comparison(message):
        score -= 1
    if _is_context_reference(message):
        score -= 1
    return score


# ---------------------------------------------------------------------------
# Keyword routing rules — ordered by priority, first match wins
# ---------------------------------------------------------------------------
_GREETING_KW = ["你好", "谢谢", "hello", "thanks", "hi", "hey", "很棒", "不错", "厉害", "再见", "bye"]

_DATA_QUALITY_KW = [
    "缺失值", "缺失", "空值", "null", "残缺",
    "异常值", "outlier", "离群",
    "检查数据", "数据类型", "有几列", "数据质量", "数据完整性",
]


_CLEAR_FILTER_KW = ["算了", "看全部", "清除", "清空", "清除筛选", "取消筛选", "不看筛选", "全部数据"]

_FACT_QUERY_KW = [
    "几行", "多少行", "多少条", "有几个", "多少列", "几列",
    "最高", "最低", "最大值", "最小值", "均值", "平均", "中位数",
    "总和", "总计", "一共",
]


def _match_clear_filter(message: str) -> bool:
    return any(kw in message for kw in _CLEAR_FILTER_KW)


def _match_fact_query(message: str) -> bool:
    return any(kw in message for kw in _FACT_QUERY_KW)


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
        # Step 0: clear filter
        if _match_clear_filter(message):
            return self._build_decision("clear_filter", 1.0, message)

        # Step 0.5: fact query (shortcut — no chart needed)
        if _match_fact_query(message):
            return self._build_decision("fact_query", 0.95, message)

        # Step 1: greeting
        if _match_greeting(message):
            return self._build_decision("greeting", 1.0, message)

        # Step 2: data quality
        if _match_data_quality(message):
            return self._build_decision("data_quality", 0.95, message)

        # Step 3: intent scoring — chart word + context signals
        score = _score_direct_viz(message)
        if score >= 2:
            return self._build_decision("direct_visualization", min(0.5 + score * 0.15, 0.95), message)

        # Step 4: analysis (has chart intent or general fallback)
        conf = 0.7 if score >= 1 else 0.5
        return self._build_decision("analysis", conf, message)

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
