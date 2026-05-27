"""InputGate — data feasibility + information density gate.

Does NOT judge intent (that's Router's job).
Only checks: is there data? is the input meaningful?
"""

from __future__ import annotations
import re


# ── keyword lists ────────────────────────────────────────────

_METRIC_WORDS = [
    "趋势", "对比", "分布", "异常", "相关性", "统计",
    "变化", "规律", "分析", "检查", "增长", "下降",
    "趋势", "走向", "波动", "差异",
    # Chart type names are also direction signals
    "折线图", "柱状图", "散点图", "饼图", "直方图", "箱线图",
    "热力图", "面积图", "雷达图", "气泡图", "漏斗图",
    "折线", "柱状", "散点", "热力",
]

_COMPARISON_WORDS = [
    "对比", "比较", "vs", "差异", "区别", "哪个",
    "和", "与", "之间",
]

_TREND_WORDS = [
    "趋势", "变化", "增长", "下降", "走向", "波动",
]

_DIRECTION_WORDS = _METRIC_WORDS + _COMPARISON_WORDS + _TREND_WORDS

_SPECIFICITY_PATTERNS = [
    r".+(vs|对比|比较|和|与).+",
    r"(哪个|哪些|什么).+",
    r"为什么",
    r"(分组|分类|按).+",
]


# ── gibberish detection ──────────────────────────────────────

def _is_gibberish(query: str) -> bool:
    """Detect keyboard mashing and meaningless input."""
    if len(query.strip()) < 2:
        return True
    # Count CJK + ASCII letters
    meaningful = len(re.findall(r"[\u4e00-\u9fff\w]", query))
    if len(query) > 0 and meaningful / len(query) < 0.2:
        return True
    # Same char repeated >10 times
    if re.search(r"(.)\1{10,}", query):
        return True
    return False


# ── scoring helpers ──────────────────────────────────────────

def _column_ref(query: str, columns: list[dict]) -> bool:
    """Check if query mentions any column name."""
    for c in columns:
        name = c.get("name", "")
        if name and name in query:
            return True
    return False


def _has_metric_word(query: str) -> bool:
    return any(w in query for w in _METRIC_WORDS)


def _has_comparison_word(query: str) -> bool:
    return any(w in query for w in _COMPARISON_WORDS)


def _has_trend_word(query: str) -> bool:
    return any(w in query for w in _TREND_WORDS)


def _has_specificity(query: str) -> bool:
    return any(re.search(p, query) for p in _SPECIFICITY_PATTERNS)


def _has_direction(query: str) -> bool:
    return _has_metric_word(query) or _has_comparison_word(query) or _has_trend_word(query)


# ── InputGate ────────────────────────────────────────────────

class InputGate:
    """Validate whether input is worth entering analysis."""

    def validate(self, query: str, df, columns: list[dict] | None = None) -> dict:
        """Returns {pass: bool, reason: str, need_clarify: bool}."""
        columns = columns or []

        # Hard reject: gibberish
        if _is_gibberish(query):
            return {
                "pass": False,
                "reason": "输入无意义，请描述你想分析什么",
                "need_clarify": False,
            }

        # No data → block
        if df is None or (hasattr(df, "empty") and df.empty):
            return {
                "pass": False,
                "reason": "请先上传一个 Excel 或 CSV 文件",
                "need_clarify": False,
            }

        # Compute scores
        score = 0
        if df is not None and not (hasattr(df, "empty") and df.empty):
            score += 2
        if _column_ref(query, columns):
            score += 2
        if _has_metric_word(query):
            score += 1
        if _has_specificity(query):
            score += 2

        direction_score = 0
        if _has_metric_word(query):
            direction_score += 1
        if _has_comparison_word(query):
            direction_score += 1
        if _has_trend_word(query):
            direction_score += 1

        # Pass: enough info + direction
        if score >= 2 and direction_score >= 1:
            return {"pass": True, "reason": "", "need_clarify": False}

        # Has data but no direction
        if score >= 2 and direction_score == 0:
            return {
                "pass": False,
                "reason": "请具体说明分析方向，例如：分析销售趋势、对比各类别差异",
                "need_clarify": True,
            }

        # Not enough info
        return {
            "pass": False,
            "reason": "我需要更具体的数据分析问题，例如：分析销售趋势、对比各类别差异",
            "need_clarify": True,
        }
