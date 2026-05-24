"""
Integration test fixtures for excel-chart-tool.

Creates a temp CSV with 50 rows of mixed-type data, uploads it,
analyzes it, and provides file_path / sheet_name for downstream tests.
"""
import os
import sys
import json
import tempfile
import csv
import random
import urllib.request
import urllib.parse

import pytest

BASE_URL = "http://127.0.0.1:8800"


def _make_sample_csv(path: str):
    """Write a 50-row CSV with mixed data types."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Header
        writer.writerow(["日期", "销售额", "利润", "订单数", "类别", "区域"])
        for i in range(50):
            date = f"2025-{1 + (i % 12):02d}-{1 + (i % 28):02d}"
            sales = round(random.uniform(5000, 50000), 2)
            profit = round(sales * random.uniform(0.05, 0.35), 2)
            orders = random.randint(10, 200)
            cat = random.choice(["电子产品", "服装", "食品", "家居", "办公"])
            region = random.choice(["华北", "华东", "华南", "西部"])
            writer.writerow([date, sales, profit, orders, cat, region])


def _post_form(endpoint: str, data: dict) -> dict:
    """POST form-urlencoded data using urllib (no curl, avoids git-bash encoding issues)."""
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _upload_file(file_path: str) -> dict:
    """Upload a file via multipart/form-data."""
    import email.generator
    import io

    boundary = "----TestBoundary2024"
    body = io.BytesIO()
    # file field
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(file_path)}"\r\n'.encode("utf-8"))
    body.write(b"Content-Type: application/octet-stream\r\n\r\n")
    with open(file_path, "rb") as f:
        body.write(f.read())
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode("utf-8"))

    url = f"{BASE_URL}/api/upload"
    req = urllib.request.Request(url, data=body.getvalue(), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


@pytest.fixture(scope="session")
def test_context():
    """Upload a sample CSV, analyze it, return {file_path, sheet_name, columns}."""
    # Create temp CSV
    tmpdir = tempfile.mkdtemp(prefix="test_excel_chart_")
    csv_path = os.path.join(tmpdir, "test_data.csv")
    _make_sample_csv(csv_path)

    # Upload
    upload_resp = _upload_file(csv_path)
    assert "file_path" in upload_resp, f"Upload failed: {upload_resp}"
    file_path = upload_resp["file_path"]
    sheet_name = upload_resp.get("sheets", ["Sheet1"])[0]

    # Analyze
    analyze_resp = _post_form("/api/analyze", {
        "file_path": file_path,
        "sheet_name": sheet_name,
    })
    assert "columns" in analyze_resp, f"Analyze failed: {analyze_resp}"
    columns = analyze_resp["columns"]
    # columns is a list of {name, dtype, ...}
    col_names = [c["name"] for c in columns]

    yield {
        "file_path": file_path,
        "sheet_name": sheet_name,
        "columns": columns,
        "col_names": col_names,
        "csv_path": csv_path,
    }

    # Cleanup
    try:
        os.remove(csv_path)
        os.rmdir(tmpdir)
    except OSError:
        pass


@pytest.fixture
def post_form():
    """Helper fixture: POST form data."""
    return _post_form
