"""ChartSelector v4.1 — intent-preserving chart authority.

Four-stage decision:
  1. Intent Parser:     query → {primary, secondary, confidence}
  2. Hard Feasibility:  can this chart type render for these columns?
  3. Intent-Preserving Resolver: intent wins when drawable; schema only for fallback
  4. Schema Scorer:     soft scores for no-intent fallback only

Core principle: data suitability constrains expression, never overrides intent.
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════════
# Stage 1: Intent Parser
# ═══════════════════════════════════════════════════════════════

_INTENT_MAP: list[tuple[str, list[str]]] = [
    ("line",      ["趋势", "变化", "增长", "下降", "走势", "走向", "波动", "折线", "曲线"]),
    ("bar",       ["对比", "比较", "排名", "差异", "柱状", "条形"]),
    ("scatter",   ["相关", "关联", "散点", "关系"]),
    ("histogram", ["分布", "直方", "频率"]),
    ("pie",       ["占比", "比例", "份额", "饼图", "构成"]),
    ("boxplot",   ["异常", "离群", "箱线"]),
]


def _parse_intent(query: str) -> dict:
    """Extract multi-label chart intent from query.

    Returns {primary: str, secondary: list[str], confidence: float}
    """
    if not query:
        return {"primary": "", "secondary": [], "confidence": 0.0}

    hits: list[str] = []
    for chart_type, keywords in _INTENT_MAP:
        if any(kw in query for kw in keywords):
            hits.append(chart_type)

    if not hits:
        return {"primary": "", "secondary": [], "confidence": 0.0}

    return {
        "primary": hits[0],
        "secondary": hits[1:],
        "confidence": min(len(hits) / len(_INTENT_MAP), 1.0),
    }


# ═══════════════════════════════════════════════════════════════
# Stage 2: Column analysis helpers
# ═══════════════════════════════════════════════════════════════

_NUMERIC_DTYPES = {"float64", "int64", "int32", "float32"}
_NUMERIC_CN = {"数值", "整数"}
_CATEGORY_CN = {"分类", "二值", "整数分类"}
_TIME_PATTERNS = {"日期", "时间", "date", "time", "年", "月", "日"}


def _classify(columns: list[dict]) -> dict:
    """Extract column classification from raw column dicts.

    Returns {n_numeric, has_time, has_category}
    """
    n_numeric = 0
    has_time = False
    has_category = False

    for c in columns:
        dtype = c.get("dtype", "")
        dtype_cn = c.get("dtype_cn", "")
        name = (c.get("name", "") or "").lower()

        if dtype in _NUMERIC_DTYPES or dtype_cn in _NUMERIC_CN:
            n_numeric += 1

        if dtype_cn in _CATEGORY_CN:
            has_category = True

        if dtype == "datetime64" or any(p in name for p in _TIME_PATTERNS):
            has_time = True

    return {"n_numeric": n_numeric, "has_time": has_time, "has_category": has_category}


# ═══════════════════════════════════════════════════════════════
# Stage 3: Hard Feasibility — can this chart render?
# ═══════════════════════════════════════════════════════════════

_FEASIBILITY: dict[str, str] = {
    "line":      "n_numeric >= 1",
    "bar":       "n_numeric >= 1",
    "scatter":   "n_numeric >= 2",
    "histogram": "n_numeric >= 1",
    "pie":       "has_category and n_numeric >= 1",
    "boxplot":   "n_numeric >= 1",
}


def _hard_feasible(chart_type: str, ctx: dict) -> bool:
    """Return True if chart_type can be rendered with these columns."""
    if chart_type not in _FEASIBILITY:
        return False
    expr = _FEASIBILITY[chart_type]
    try:
        return bool(eval(expr, {"__builtins__": {}}, ctx))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# Stage 4: Semantic Suitability — how well does data fit intent?
# ═══════════════════════════════════════════════════════════════

def _semantic_score(chart_type: str, ctx: dict) -> int:
    """Score 0–2: how semantically natural this chart is for the data.

    Used to inform chart annotation, NOT to override intent.
    """
    if chart_type == "line":
        if ctx["has_time"]:
            return 2   # natural time-series
        if ctx["n_numeric"] >= 1:
            return 1   # index-based trend, acceptable
        return 0

    if chart_type == "scatter":
        if ctx["n_numeric"] >= 2:
            return 2   # natural correlation
        return 0

    if chart_type == "bar":
        if ctx["has_category"] and ctx["n_numeric"] >= 1:
            return 2   # natural category comparison
        if ctx["n_numeric"] >= 1:
            return 1   # bare numeric bars
        return 0

    if chart_type == "pie":
        if ctx["has_category"] and ctx["n_numeric"] == 1:
            return 2   # perfect pie shape
        if ctx["has_category"] and ctx["n_numeric"] >= 1:
            return 1   # ok but maybe too many values
        return 0

    if chart_type == "histogram":
        if ctx["n_numeric"] >= 3:
            return 2   # rich distribution
        if ctx["n_numeric"] >= 1:
            return 1   # sparse but valid
        return 0

    if chart_type == "boxplot":
        if ctx["n_numeric"] >= 2:
            return 2   # multi-variable comparison
        if ctx["n_numeric"] >= 1:
            return 1   # single variable
        return 0

    return 1  # unknown types are at least feasible


# ═══════════════════════════════════════════════════════════════
# Stage 5: Schema Scorer — data-driven scores (no-intent fallback)
# ═══════════════════════════════════════════════════════════════

def _resolve_schema(columns: list[dict]) -> dict[str, float]:
    """Score chart types by data structure fit. Used only when no intent."""
    scores: dict[str, float] = {
        "line": 0.0, "bar": 0.0, "scatter": 0.0,
        "histogram": 0.0, "pie": 0.0, "boxplot": 0.0,
    }

    if not columns:
        scores["bar"] = 0.3
        return scores

    ctx = _classify(columns)
    n = ctx["n_numeric"]

    if ctx["has_time"] and n >= 1:
        scores["line"] += 0.9
    if n == 2:
        scores["scatter"] += 0.8
    if ctx["has_category"] and n >= 1:
        scores["bar"] += 0.6
        scores["pie"] += 0.5
    if n >= 3:
        scores["histogram"] += 0.5
    scores["bar"] = max(scores["bar"], 0.3)  # universal fallback

    return scores


# ═══════════════════════════════════════════════════════════════
# Stage 6: Intent-Preserving Resolver
# ═══════════════════════════════════════════════════════════════

def _resolve(primary: str, secondary: list[str], columns: list[dict]) -> str:
    """Intent-preserving arbitration.

    Rules (priority order):
      1. primary intent + drawable → primary (always)
      2. secondary intent + drawable → secondary
      3. schema fallback
    """
    if not columns:
        return "bar"

    ctx = _classify(columns)

    # Intent preservation: schema cannot override user intent
    if primary and _hard_feasible(primary, ctx):
        return primary

    for t in secondary:
        if _hard_feasible(t, ctx):
            return t

    schema = _resolve_schema(columns)
    return max(schema, key=schema.get)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def select_chart_type(columns: list[dict], query: str = "") -> str:
    """Return chart type — sole authority, deterministic.

    Args:
        columns: list of {name, dtype, dtype_cn, ...} dicts
        query: user message for intent extraction

    Returns:
        chart_type string: line | bar | scatter | histogram | pie | boxplot
    """
    intent = _parse_intent(query)
    return _resolve(intent["primary"], intent["secondary"], columns)


def select_chart_type_with_context(columns: list[dict], query: str = "") -> dict:
    """Return chart type + semantic context for LLM prompt enrichment.

    Returns {chart_type, semantic_score, feasibility_note}
    """
    intent = _parse_intent(query)
    chart_type = _resolve(intent["primary"], intent["secondary"], columns)

    ctx = _classify(columns) if columns else {"n_numeric": 0, "has_time": False, "has_category": False}
    score = _semantic_score(chart_type, ctx)

    note = ""
    if chart_type == "line" and not ctx["has_time"]:
        note = "index_as_time"
    elif chart_type == "scatter" and ctx["n_numeric"] < 2:
        note = "forced"
    elif chart_type == "pie" and ctx["n_numeric"] > 1:
        note = "multi_value"

    return {
        "chart_type": chart_type,
        "semantic_score": score,
        "feasibility_note": note,
    }
