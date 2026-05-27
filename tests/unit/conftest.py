"""Shared fixtures for unit tests."""
import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def sample_df():
    """DataFrame with mixed types: int, float, category, datetime, bool."""
    n = 50
    np.random.seed(42)

    df = pd.DataFrame({
        "int_col": np.random.randint(1, 16, n),              # ≤20 uniques → integer category
        "float_col": np.random.uniform(10.0, 100.0, n),       # >20 uniques → numeric
        "cat_col": np.random.choice(["A", "B", "C", "D", "E"], n),  # str ≤20 → category
        "text_col": [f"text_{i}" for i in range(n)],           # str >20 uniques → text
        "date_col": pd.date_range("2024-01-01", periods=n, freq="D"),
        "bool_col": np.random.choice([True, False], n),
        "empty_col": [np.nan] * n,
    })
    return df


@pytest.fixture
def chart_builder():
    """Return a ChartBuilder instance."""
    from core.chart.builder import ChartBuilder
    return ChartBuilder()


@pytest.fixture
def chart_df():
    """Simple DataFrame for chart tests."""
    return pd.DataFrame({
        "category": ["苹果", "香蕉", "橙子", "葡萄", "西瓜"],
        "sales": [120, 200, 150, 80, 230],
        "profit": [30, 55, 40, 20, 70],
        "x": [1.0, 2.5, 3.0, 4.5, 5.0],
        "y": [2.1, 4.2, 5.8, 8.1, 10.5],
    })
