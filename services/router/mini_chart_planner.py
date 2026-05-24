"""MiniChartPlanner — infer chart args from user query + data schema."""


def plan_chart(query: str, columns: list[dict]) -> dict:
    """
    Infer chart args from query keywords and column types.
    Returns: {chart_type, x_column, y_columns, aggregation, title}

    Strategy: rule-first (column types + keywords), always succeeds.
    """
    col_names = [c.get("name", "") for c in columns]
    col_info = {c.get("name", ""): c.get("dtype_cn", "") for c in columns}

    # Step 1: infer chart_type from keywords
    chart_type = "bar"  # default
    if any(kw in query for kw in ["折线", "趋势", "走势", "变化", "增长", "下降", "波动"]):
        chart_type = "line"
    elif any(kw in query for kw in ["散点", "相关", "关联"]):
        chart_type = "scatter"
    elif any(kw in query for kw in ["饼图", "占比", "比例", "份额"]):
        chart_type = "pie"

    # Step 2: find x_column (prefer text/date for bar/line; prefer numeric for scatter)
    x_column = ""
    if chart_type == "scatter":
        for name, dtype in col_info.items():
            if dtype in ("数值", "整数分类"):
                x_column = name
                break
    if not x_column:
        for name, dtype in col_info.items():
            if dtype in ("文本", "日期", "分类"):
                x_column = name
                break
    if not x_column and col_names:
        x_column = col_names[0]

    # Step 3: find y_columns (numeric, excluding x_column)
    y_columns = []
    for name, dtype in col_info.items():
        if name != x_column and dtype in ("数值", "整数分类"):
            y_columns.append(name)
            if len(y_columns) >= 2:
                break
    if not y_columns and len(col_names) > 1:
        for name in col_names:
            if name != x_column:
                y_columns.append(name)
                break

    # Step 4: aggregation (sum for bar/line, none for scatter)
    aggregation = "sum" if chart_type in ("bar", "line", "pie") else None

    return {
        "chart_type": chart_type,
        "x_column": x_column,
        "y_columns": y_columns,
        "aggregation": aggregation,
        "title": "",
    }
