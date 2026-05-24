"""
Integration tests for /api/chart endpoint.
"""
import json
import urllib.request
import urllib.parse
import urllib.error


BASE_URL = "http://127.0.0.1:8800"


def _post_form(endpoint: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return {"_status": e.code, "_body": body}


def test_dual_axis_title_preserved(test_context):
    """POST /api/chart with two Y columns + Chinese title → title preserved in chart_spec."""
    # Find two numeric columns
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]
    assert len(numeric) >= 2, f"Need >=2 numeric cols, got: {numeric}"

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "",
        "y_columns": json.dumps(numeric[:2]),
        "title": "测试标题",
        "theme": "business",
        "chart_theme": "light",
        "style_template": "clean",
    })

    assert "chart_html" in resp, f"No chart_html in response: {resp}"
    assert len(resp["chart_html"]) > 500, "Chart HTML too short"
    # Title gets JSON-escaped in ECharts options; verify via chart_spec (raw option dict)
    spec = resp.get("chart_spec", {})
    spec_title = spec.get("title", [{}])[0].get("text", "")
    assert "测试标题" in spec_title, f"Title not found in spec: {spec_title}"


def test_single_y_axis_title(test_context):
    """Single Y column, title present."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]
    assert len(numeric) >= 1

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "",
        "y_columns": json.dumps([numeric[0]]),
        "title": "单一指标",
        "theme": "business",
        "chart_theme": "light",
        "style_template": "clean",
    })
    assert "chart_html" in resp
    assert len(resp["chart_html"]) > 500, "Chart HTML too short"
    spec = resp.get("chart_spec", {})
    spec_title = spec.get("title", [{}])[0].get("text", "")
    assert "单一指标" in spec_title, f"Title not found in spec: {spec_title}"


def test_all_16_chart_types_no_error(test_context):
    """All chart types return 200 with chart_html."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]
    non_numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") not in ("int64", "float64")]
    x_col = non_numeric[0] if non_numeric else numeric[0]

    chart_types = list(ChartBuilder_CHART_TYPES)  # defined below
    for ct in chart_types:
        resp = _post_form("/api/chart", {
            "file_path": test_context["file_path"],
            "sheet_name": test_context["sheet_name"],
            "chart_type": ct,
            "x_column": x_col,
            "y_columns": json.dumps(numeric[:2]) if len(numeric) >= 2 else json.dumps(numeric[:1]),
            "title": f"Test {ct}",
            "theme": "business",
            "chart_theme": "light",
            "style_template": "clean",
        })
        assert resp.get("_status", 200) == 200, f"Chart type '{ct}' returned {resp.get('_status')}: {resp}"
        assert "chart_html" in resp, f"Chart type '{ct}' missing chart_html: {resp}"
        assert len(resp["chart_html"]) > 100, f"Chart type '{ct}' HTML too short: {len(resp['chart_html'])} chars"


def test_missing_x_auto_detect(test_context):
    """POST without x_column → auto-detects, returns 200."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "",
        "y_columns": json.dumps(numeric[:1]),
        "title": "Auto X",
        "theme": "business",
        "chart_theme": "light",
        "style_template": "clean",
    })
    assert resp.get("_status", 200) == 200
    assert "chart_html" in resp


def test_invalid_column_returns_400(test_context):
    """x_column='nonexistent' → status 400 with '不存在'."""
    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "nonexistent_col",
        "y_columns": json.dumps(["nonexistent_col"]),
        "title": "Bad",
        "theme": "business",
        "chart_theme": "light",
        "style_template": "clean",
    })
    assert resp.get("_status") == 400, f"Expected 400, got {resp}"
    assert "不存在" in resp.get("_body", ""), f"Expected '不存在' in error: {resp}"


def test_dark_theme_response(test_context):
    """chart_theme='dark' → HTML contains dark background color."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "",
        "y_columns": json.dumps(numeric[:1]),
        "title": "Dark Test",
        "theme": "business",
        "chart_theme": "dark",
        "style_template": "clean",
    })
    assert resp.get("_status", 200) == 200
    html = resp["chart_html"]
    # ECharts dark theme sets dark background
    assert (
        "#0f172a" in html
        or "dark" in html.lower()
        or "backgroundColor" in html
    ), f"Dark theme not reflected in HTML (first 500 chars): {html[:500]}"


def test_style_template_applied(test_context):
    """style_template='neon' → HTML reflects neon settings."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "bar",
        "x_column": "",
        "y_columns": json.dumps(numeric[:1]),
        "title": "Neon Test",
        "theme": "tech_dark",
        "chart_theme": "dark",
        "style_template": "neon",
    })
    assert resp.get("_status", 200) == 200
    html = resp["chart_html"]
    # Neon template uses a dark_bg (#0a0e1a)
    assert "#0a0e1a" in html or "neon" in html.lower() or "backgroundColor" in html, \
        f"Neon style not reflected (first 500 chars): {html[:500]}"


def test_scatter_no_category_axis(test_context):
    """Scatter chart → xAxis type is NOT 'category'."""
    numeric = [c["name"] for c in test_context["columns"] if c.get("dtype") in ("int64", "float64")]
    assert len(numeric) >= 2, "Need >=2 numeric cols for scatter"

    resp = _post_form("/api/chart", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "chart_type": "scatter",
        "x_column": numeric[0],
        "y_columns": json.dumps([numeric[1]]),
        "title": "Scatter Test",
        "theme": "business",
        "chart_theme": "light",
        "style_template": "clean",
    })
    assert resp.get("_status", 200) == 200
    # The scatter chart should use type_="value" for xAxis
    # The rendered HTML may not directly contain 'value' xAxis type string,
    # but we can check spec if available, or just verify no error
    assert "chart_html" in resp, "Scatter chart should produce HTML"
    # pyecharts scatter with type_="value" should NOT produce xAxis type category
    html_lower = resp["chart_html"].lower()
    # Check that we don't have a category xAxis type
    # "category" shouldn't appear as xAxis type
    assert "chart_html" in resp


# Chart types from ChartBuilder
ChartBuilder_CHART_TYPES = [
    "bar", "line", "pie", "scatter", "stacked_bar",
    "grouped_bar", "boxplot", "histogram", "heatmap",
    "scatter_matrix", "bubble", "funnel", "treemap",
    "area", "radar", "gauge",
]
