"""Unit tests for services.chart_builder — ChartBuilder.build_spec()."""
import pytest
import pandas as pd
import numpy as np

from services.chart_builder import ChartBuilder


class TestBuildSpec:
    """Tests for ChartBuilder.build_spec().

    build_spec() returns:
      - Raw ECharts option dict (for pyecharts types: bar, line, scatter, etc.)
      - {"_html": ..., "_type": ..., "_note": ...} (for plotly types: heatmap, scatter_matrix)
      - {"_error": ..., "_html": ...} (on regex extraction failure)
    """

    def test_spec_has_echarts_option_keys(self, chart_builder, chart_df):
        """build_spec returns the ECharts option with standard keys."""
        spec = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales"],
            "Test Bar", "business", "light", "clean",
        )
        # Spec should have core ECharts option keys
        assert "xAxis" in spec, f"Missing xAxis in spec keys: {list(spec.keys())}"
        assert "yAxis" in spec, f"Missing yAxis in spec keys: {list(spec.keys())}"
        assert "series" in spec, f"Missing series in spec keys: {list(spec.keys())}"

    def test_bar_spec_structure(self, chart_builder, chart_df):
        spec = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales"],
            "Test Bar", "business", "light", "clean",
        )
        assert "xAxis" in spec
        assert "yAxis" in spec
        assert "series" in spec
        assert len(spec["series"]) == 1

    def test_scatter_spec_itemstyle_has_color(self, chart_builder, chart_df):
        spec = chart_builder.build_spec(
            chart_df, "scatter", "x", ["y"],
            "Test Scatter", "business", "light", "clean",
        )
        series = spec.get("series", [])
        assert len(series) > 0, "No series in scatter spec"
        item_style = series[0].get("itemStyle", {})
        assert item_style is not None, "itemStyle is None/missing"
        assert "color" in item_style, f"itemStyle has no color: {item_style}"
        assert item_style["color"] is not None, "itemStyle.color is None"

    def test_dual_axis_spec_has_right_position(self, chart_builder, chart_df):
        """3 y_columns triggers dual-axis: first on left, 2 on right."""
        spec = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales", "profit", "x"],
            "Dual Axis", "business", "light", "clean",
        )
        y_axis = spec.get("yAxis", [])
        assert len(y_axis) >= 2, f"Expected >=2 yAxis entries, got {len(y_axis)}"
        assert y_axis[1].get("position") == "right", \
            f"yAxis[1].position={y_axis[1].get('position')}, expected 'right'"

    def test_all_chart_types_have_spec(self, chart_builder, chart_df):
        """Every chart type in CHART_TYPES should produce a result without error."""
        # Map each chart type to appropriate (x, y) for chart_df
        type_params = {
            "bar": ("category", ["sales"]),
            "line": ("category", ["sales"]),
            "pie": ("category", ["sales"]),
            "scatter": ("x", ["y"]),
            "stacked_bar": ("category", ["sales", "profit"]),
            "grouped_bar": ("category", ["sales", "profit"]),
            "boxplot": ("category", ["sales", "profit"]),
            "histogram": ("category", ["sales"]),
            "heatmap": ("category", ["sales"]),
            "scatter_matrix": ("category", ["sales"]),
            "bubble": ("x", ["y", "sales"]),
            "funnel": ("category", ["sales"]),
            "treemap": ("category", ["sales"]),
            "area": ("category", ["sales"]),
            "radar": ("category", ["sales"]),
            "gauge": ("category", ["sales"]),
        }

        failed = {}
        for ctype, (x_col, y_cols) in type_params.items():
            try:
                spec = chart_builder.build_spec(
                    chart_df, ctype, x_col, y_cols,
                    f"Test {ctype}", "business", "light", "clean",
                )
                # Spec must be a dict (even heatmap/scatter_matrix return dicts)
                assert isinstance(spec, dict), f"Expected dict, got {type(spec)}"
            except Exception as e:
                failed[ctype] = str(e)

        if failed:
            pytest.fail(f"Chart types with errors: {failed}")

    def test_spec_dark_theme(self, chart_builder, chart_df):
        """Dark theme sets background color to '#0f172a'."""
        spec = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales"],
            "Dark Bar", "business", "dark", "clean",
        )
        bg = spec.get("backgroundColor", "")
        assert bg == "#0f172a", f"Expected bg '#0f172a', got '{bg}'"

    def test_spec_style_template(self, chart_builder, chart_df):
        """style_template='minimal' produces valid spec (different styles are applied at render level)."""
        spec_clean = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales"],
            "Styled Bar", "business", "light", "clean",
        )
        spec_minimal = chart_builder.build_spec(
            chart_df, "bar", "category", ["sales"],
            "Styled Bar", "business", "light", "minimal",
        )

        # Both should be valid ECharts option dicts
        for name, spec in [("clean", spec_clean), ("minimal", spec_minimal)]:
            assert "series" in spec, f"{name} spec missing series"
            assert "xAxis" in spec, f"{name} spec missing xAxis"
            assert "yAxis" in spec, f"{name} spec missing yAxis"

        # Some style properties do differ (e.g., backgroundColor comes from _global_opts)
        # At minimum, both specs should be structurally valid with same keys
        assert set(spec_clean.keys()) == set(spec_minimal.keys()), (
            f"Key mismatch: clean={set(spec_clean.keys()) - set(spec_minimal.keys())}, "
            f"minimal={set(spec_minimal.keys()) - set(spec_clean.keys())}"
        )
