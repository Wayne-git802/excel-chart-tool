"""
Integration tests for /api/insights endpoint.
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


def test_insights_returns_valid_structure(test_context):
    """Response has 'insights', 'top_insights', 'raw_count', 'should_push'."""
    resp = _post_form("/api/insights", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "mode": "analyze",
    })
    assert resp.get("_status", 200) == 200, f"Expected 200, got {resp}"
    for key in ("insights", "top_insights", "raw_count", "should_push"):
        assert key in resp, f"Missing key '{key}' in response: {list(resp.keys())}"

    assert isinstance(resp["insights"], list), "insights should be a list"
    assert isinstance(resp["top_insights"], list), "top_insights should be a list"
    assert isinstance(resp["raw_count"], int), "raw_count should be int"


def test_insight_fields_complete(test_context):
    """Each insight has type, title, description, score, columns, chart_hint."""
    resp = _post_form("/api/insights", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "mode": "analyze",
    })
    assert resp.get("_status", 200) == 200

    insights = resp.get("insights", [])
    assert len(insights) > 0, "Expected at least 1 insight"

    for insight in insights:
        assert "type" in insight, f"Missing 'type': {insight}"
        assert "title" in insight, f"Missing 'title': {insight}"
        assert "description" in insight, f"Missing 'description': {insight}"
        assert "score" in insight, f"Missing 'score': {insight}"
        assert "columns" in insight, f"Missing 'columns': {insight}"
        assert "chart_hint" in insight, f"Missing 'chart_hint': {insight}"

        assert isinstance(insight["score"], (int, float)), f"score should be numeric: {insight['score']}"
        assert isinstance(insight["columns"], list), f"columns should be list: {insight['columns']}"
        assert isinstance(insight["chart_hint"], dict), f"chart_hint should be dict: {insight['chart_hint']}"


def test_mode_explore_does_not_crash(test_context):
    """mode='explore' returns 200."""
    resp = _post_form("/api/insights", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "mode": "explore",
    })
    assert resp.get("_status", 200) == 200, f"explore mode failed: {resp}"


def test_mode_analyze(test_context):
    """mode='analyze' returns 200."""
    resp = _post_form("/api/insights", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "mode": "analyze",
    })
    assert resp.get("_status", 200) == 200, f"analyze mode failed: {resp}"


def test_insights_sorted_by_score(test_context):
    """top_insights[0].score >= top_insights[-1].score."""
    resp = _post_form("/api/insights", {
        "file_path": test_context["file_path"],
        "sheet_name": test_context["sheet_name"],
        "mode": "analyze",
    })
    assert resp.get("_status", 200) == 200

    top = resp.get("top_insights", [])
    if len(top) >= 2:
        scores = [ins["score"] for ins in top]
        assert scores == sorted(scores, reverse=True), \
            f"top_insights not sorted by score desc: {scores}"

    # Also check 'insights' list is sorted
    insights = resp.get("insights", [])
    if len(insights) >= 2:
        ins_scores = [ins["score"] for ins in insights]
        assert ins_scores == sorted(ins_scores, reverse=True), \
            f"insights not sorted by score desc: {ins_scores}"
