"""图表生成服务 - pyecharts 为主，plotly 补统计图
支持 Light/Dark 主题切换 + 6+2 套配色 + 视觉美化"""
import os
import json
import re
import pandas as pd
import numpy as np
from pyecharts import options as opts
from pyecharts.charts import Bar, Line, Pie, Scatter, Boxplot
from pyecharts.charts import Funnel, Radar, Gauge, TreeMap, HeatMap
from pyecharts.commons.utils import JsCode
from pyecharts.globals import ThemeType, CurrentConfig
import plotly.graph_objects as go
import plotly.express as px

# Use local echarts.js for QQ browser compatibility (no CDN)
CurrentConfig.ONLINE_HOST = "/static/js/"


class ChartBuilder:
    """生成各种类型的图表"""

    CHART_TYPES = {
        "bar": "柱状图", "line": "折线图", "pie": "饼图",
        "scatter": "散点图", "stacked_bar": "堆叠柱状图",
        "grouped_bar": "分组柱状图", "boxplot": "箱线图",
        "histogram": "直方图", "heatmap": "热力图",
        "scatter_matrix": "散点矩阵", "bubble": "气泡图",
        "funnel": "漏斗图", "treemap": "矩形树图",
        "area": "面积图", "radar": "雷达图", "gauge": "仪表盘",
    }

    # ====== 配色方案 ======
    THEMES = {
        "business": {
            "name": "商务蓝",
            "colors": ["#1F4E79", "#2B7FC9", "#5BA0D9", "#93C5EA", "#BDD7F5", "#D6E4F0"],
            "bg_color": "#F8FAFC", "title_color": "#1E3A5F",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "finance": {
            "name": "财务绿",
            "colors": ["#0F5B3D", "#1B8A4A", "#34B367", "#67D48E", "#93E5AB", "#BEF2CC"],
            "bg_color": "#F5FAF7", "title_color": "#0A3A26",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "vibrant": {
            "name": "活力橙",
            "colors": ["#E85D04", "#F48C06", "#FAA307", "#FFBA08", "#FFD166", "#FFF3B0"],
            "bg_color": "#FFFAF5", "title_color": "#8B3A00",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "elegant": {
            "name": "雅致灰",
            "colors": ["#2D3748", "#4A5568", "#718096", "#A0AEC0", "#CBD5E0", "#E2E8F0"],
            "bg_color": "#F7FAFC", "title_color": "#1A202C",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "purple": {
            "name": "渐变紫",
            "colors": ["#553C9A", "#6B46C1", "#805AD5", "#9F7AEA", "#B794F4", "#D6BCFA"],
            "bg_color": "#FAF5FF", "title_color": "#322659",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "monochrome": {
            "name": "极简黑白",
            "colors": ["#1A1A2E", "#333333", "#5C5C5C", "#999999", "#CCCCCC", "#EEEEEE"],
            "bg_color": "#FFFFFF", "title_color": "#000000",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        # === 新增 ===
        "presentation": {
            "name": "PPT商务",
            "colors": ["#0F2B5B", "#D4A843", "#2E86AB", "#A23B72", "#F18F01", "#3A7D44"],
            "bg_color": "#FCFCFA", "title_color": "#0A1F3F",
            "bg_dark": "#0f172a", "title_dark": "#e2e8f0",
        },
        "tech_dark": {
            "name": "科技暗色",
            "colors": ["#06B6D4", "#8B5CF6", "#10B981", "#F59E0B", "#EC4899", "#3B82F6"],
            "bg_color": "#0F172A", "title_color": "#67E8F9",
            "bg_dark": "#0f172a", "title_dark": "#67E8F9",
        },
    }

    # 暗色公用色
    DARK = {
        "bg": "#0f172a",
        "text": "#e2e8f0",
        "text2": "#94a3b8",
        "text3": "#64748b",
        "grid": "rgba(148,163,184,0.08)",
        "axis_line": "rgba(148,163,184,0.15)",
        "split_line": "rgba(148,163,184,0.06)",
        "tooltip_bg": "rgba(15,23,42,0.95)",
        "tooltip_border": "rgba(148,163,184,0.2)",
    }

    STYLE_TEMPLATES = {
        "clean": {
            "name": "商务简约",
            "bar_radius": [6, 6, 0, 0],
            "line_width": 2.5,
            "line_smooth": True,
            "symbol_size": 8,
            "area_opacity": 0.08,
            "pie_radius": ["45%", "78%"],
            "font_family": "Segoe UI, Microsoft YaHei, sans-serif",
            "title_size": 16,
            "grid_top": 60,
        },
        "neon": {
            "name": "暗色科技",
            "bar_radius": [4, 4, 0, 0],
            "line_width": 3,
            "line_smooth": True,
            "symbol_size": 10,
            "area_opacity": 0.15,
            "pie_radius": ["40%", "75%"],
            "font_family": "Segoe UI, Microsoft YaHei, sans-serif",
            "title_size": 18,
            "grid_top": 70,
            "dark_bg": "#0a0e1a",
            "glow": True,
        },
        "gradient": {
            "name": "渐变立体",
            "bar_radius": [8, 8, 2, 2],
            "line_width": 3.5,
            "line_smooth": True,
            "symbol_size": 12,
            "area_opacity": 0.2,
            "pie_radius": ["40%", "80%"],
            "font_family": "Segoe UI, Microsoft YaHei, sans-serif",
            "title_size": 17,
            "grid_top": 65,
            "shadow": True,
        },
        "minimal": {
            "name": "极简线条",
            "bar_radius": [2, 2, 0, 0],
            "line_width": 1.5,
            "line_smooth": False,
            "symbol_size": 6,
            "area_opacity": 0.05,
            "pie_radius": ["50%", "75%"],
            "font_family": "Georgia, serif",
            "title_size": 14,
            "grid_top": 50,
            "thin_grid": True,
        },
        "vivid": {
            "name": "清新活力",
            "bar_radius": [10, 10, 4, 4],
            "line_width": 2.5,
            "line_smooth": True,
            "symbol_size": 10,
            "area_opacity": 0.12,
            "pie_radius": ["35%", "72%"],
            "font_family": "Segoe UI, Microsoft YaHei, sans-serif",
            "title_size": 16,
            "grid_top": 60,
            "rounded_caps": True,
        },
        "magazine": {
            "name": "杂志风",
            "bar_radius": [3, 3, 3, 3],
            "line_width": 2,
            "line_smooth": True,
            "symbol_size": 8,
            "area_opacity": 0.1,
            "pie_radius": ["42%", "80%"],
            "font_family": "Georgia, 'Noto Serif SC', serif",
            "title_size": 20,
            "grid_top": 80,
            "spacious": True,
        },
    }

    def get_style_template(self, name: str) -> dict:
        return self.STYLE_TEMPLATES.get(name, self.STYLE_TEMPLATES["clean"])

    def get_themes(self) -> dict:
        return {
            key: {"name": v["name"], "preview_colors": v["colors"][:4]}
            for key, v in self.THEMES.items()
        }

    def _get_theme_data(self, theme_name: str, dark: bool) -> dict:
        """获取配色，注入暗色模式覆写"""
        t = self.THEMES.get(theme_name, self.THEMES["business"]).copy()
        if dark:
            t["bg_color"] = t.get("bg_dark", self.DARK["bg"])
            t["title_color"] = t.get("title_dark", self.DARK["text"])
        return t

    def _global_opts(self, title: str, theme_data: dict, dark: bool, **kwargs) -> opts.InitOpts:
        st = kwargs.get("_style", {})
        bg = st.get("dark_bg", theme_data["bg_color"]) if st.get("dark_bg") else theme_data["bg_color"]
        return opts.InitOpts(
            theme=ThemeType.LIGHT if not st.get("dark_bg") else ThemeType.DARK,
            bg_color=bg,
            width=kwargs.get("width", "900px"),
            height=kwargs.get("height", "520px"),
        )

    def _title(self, title: str, color: str, **kwargs) -> opts.TitleOpts:
        st = kwargs.get("_style", {})
        return opts.TitleOpts(
            title=title,
            title_textstyle_opts=opts.TextStyleOpts(
                color=color, font_size=st.get("title_size", 18), font_weight="bold",
                font_family=st.get("font_family", "Segoe UI, Microsoft YaHei, sans-serif"),
            ),
            pos_left="center",
            pos_top=f"{st.get('grid_top', 60) - 52}px",
        )

    def _legend(self, dark: bool, **kwargs) -> opts.LegendOpts:
        st = kwargs.get("_style", {})
        c = self.DARK["text2"] if dark else "#64748b"
        return opts.LegendOpts(
            pos_top=f"{st.get('grid_top', 60) - 18}px",
            textstyle_opts=opts.TextStyleOpts(color=c, font_size=12),
        )

    def _tooltip(self, dark: bool) -> opts.TooltipOpts:
        if dark:
            return opts.TooltipOpts(
                trigger="axis",
                background_color=self.DARK["tooltip_bg"],
                border_color=self.DARK["tooltip_border"],
                textstyle_opts=opts.TextStyleOpts(color=self.DARK["text"], font_size=13),
            )
        return opts.TooltipOpts(trigger="axis")

    def _xaxis(self, name: str, dark: bool) -> opts.AxisOpts:
        c = self.DARK["text2"] if dark else "#475569"
        lc = self.DARK["text3"] if dark else "#94a3b8"
        return opts.AxisOpts(
            name=name,
            name_textstyle_opts=opts.TextStyleOpts(color=c, font_size=12),
            axislabel_opts=opts.LabelOpts(rotate=30, color=lc, font_size=11),
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(
                    color=self.DARK["axis_line"] if dark else "#cbd5e0",
                ),
            ),
        )

    def _yaxis(self, name: str, dark: bool) -> opts.AxisOpts:
        c = self.DARK["text2"] if dark else "#475569"
        lc = self.DARK["text3"] if dark else "#475569"
        return opts.AxisOpts(
            name=name,
            name_textstyle_opts=opts.TextStyleOpts(color=c, font_size=12),
            axislabel_opts=opts.LabelOpts(color=lc, font_size=11),
            splitline_opts=opts.SplitLineOpts(
                is_show=True,
                linestyle_opts=opts.LineStyleOpts(
                    color=self.DARK["split_line"] if dark else "#f1f5f9",
                ),
            ),
        )

    # ==================== 主入口 ====================

    def _needs_dual_axis(self, df, y_cols, threshold=2):
        """If 2+ Y columns, always split: first on left, rest on right."""
        if len(y_cols) < 2:
            return y_cols, []
        # Always split: first column on left axis, rest on right
        return [y_cols[0]], y_cols[1:]

    def _make_dual_axis_chart(self, ChartClass, df, x_col, y_cols, td, dark, **kwargs):
        """Build a dual Y-axis chart when y_cols have incompatible scales.
        left_cols go on left axis, right_cols on right axis."""
        left_cols, right_cols = self._needs_dual_axis(df, y_cols)

        x_data = df[x_col].astype(str).tolist()

        # Main chart (left axis)
        chart_title = kwargs.pop("title", "")
        chart = ChartClass(self._global_opts("", td, dark, **kwargs))
        chart.add_xaxis(x_data)
        for i, yc in enumerate(left_cols):
            c = td["colors"][i % len(td["colors"])]
            chart.add_yaxis(yc, df[yc].round(2).tolist(), color=c,
                            yaxis_index=0,
                            itemstyle_opts=opts.ItemStyleOpts(border_radius=[6, 6, 0, 0]))

        if right_cols:
            # Extend right axis
            chart.extend_axis(
                yaxis=opts.AxisOpts(
                    name=right_cols[0] if len(right_cols) == 1 else "右轴",
                    position="right",
                    name_textstyle_opts=opts.TextStyleOpts(color=td["title_color"]),
                    axislabel_opts=opts.LabelOpts(color=td["colors"][len(left_cols) % len(td["colors"])]),
                )
            )
            # Overlay chart for right axis
            overlay = ChartClass()
            overlay.add_xaxis(x_data)
            for i, yc in enumerate(right_cols):
                c = td["colors"][(len(left_cols) + i) % len(td["colors"])]
                overlay.add_yaxis(yc, df[yc].round(2).tolist(), color=c,
                                  yaxis_index=1,
                                  itemstyle_opts=opts.ItemStyleOpts(border_radius=[6, 6, 0, 0]))
            chart.overlap(overlay)

        chart.set_global_opts(
            title_opts=self._title(chart_title, td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis(left_cols[0] if left_cols else "", dark),
        )
        return chart.render_embed()

    def _make_dual_axis_line(self, df, x_col, y_cols, td, dark, **kwargs):
        """Dual Y-axis line chart with smooth curves."""
        left_cols, right_cols = self._needs_dual_axis(df, y_cols)
        x_data = df[x_col].astype(str).tolist()

        chart_title = kwargs.pop("title", "")
        chart = Line(self._global_opts("", td, dark, **kwargs))
        chart.add_xaxis(x_data)
        for i, yc in enumerate(left_cols):
            c = td["colors"][i % len(td["colors"])]
            chart.add_yaxis(yc, df[yc].round(2).tolist(), color=c, yaxis_index=0,
                            is_smooth=True, linestyle_opts=opts.LineStyleOpts(width=3),
                            areastyle_opts=opts.AreaStyleOpts(opacity=0.08),
                            symbol="circle", symbol_size=6)

        if right_cols:
            chart.extend_axis(
                yaxis=opts.AxisOpts(
                    name=right_cols[0] if len(right_cols) == 1 else "右轴",
                    position="right",
                    name_textstyle_opts=opts.TextStyleOpts(color=td["title_color"]),
                    axislabel_opts=opts.LabelOpts(color=td["colors"][len(left_cols) % len(td["colors"])]),
                )
            )
            overlay = Line()
            overlay.add_xaxis(x_data)
            for i, yc in enumerate(right_cols):
                c = td["colors"][(len(left_cols) + i) % len(td["colors"])]
                overlay.add_yaxis(yc, df[yc].round(2).tolist(), color=c,
                                  yaxis_index=1, is_smooth=True,
                                  linestyle_opts=opts.LineStyleOpts(width=3),
                                  areastyle_opts=opts.AreaStyleOpts(opacity=0.08),
                                  symbol="diamond", symbol_size=6)
            chart.overlap(overlay)

        chart.set_global_opts(
            title_opts=self._title(chart_title, td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis(left_cols[0] if left_cols else "", dark),
        )
        return chart.render_embed()

    def build(self, df: pd.DataFrame, chart_type: str, x_column: str,
              y_columns: list, title: str, theme: str,
              chart_theme: str = "light", style_template: str = "clean", **kwargs) -> str:
        """主入口"""
        dark = (chart_theme == "dark")
        theme_data = self._get_theme_data(theme, dark)
        st = self.get_style_template(style_template)
        kwargs["_style"] = st

        method_map = {
            "bar": self._bar, "line": self._line, "pie": self._pie,
            "scatter": self._scatter, "stacked_bar": self._stacked_bar,
            "grouped_bar": self._grouped_bar, "boxplot": self._boxplot,
            "histogram": self._histogram, "heatmap": self._heatmap,
            "scatter_matrix": self._scatter_matrix, "bubble": self._bubble,
            "funnel": self._funnel, "treemap": self._treemap,
            "area": self._area, "radar": self._radar, "gauge": self._gauge,
        }
        fn = method_map.get(chart_type, self._bar)
        return fn(df, x_column, y_columns, title, theme_data, dark, **kwargs)

    # ==================== 基础图表 ====================

    def _bar(self, df, x_col, y_cols, title, td, dark, **kwargs):
        # Auto dual Y-axis if scales differ >5x
        if len(y_cols) >= 2:
            left_cols, right_cols = self._needs_dual_axis(df, y_cols)
            if right_cols:
                return self._make_dual_axis_chart(Bar, df, x_col, y_cols, td, dark, title=title, **kwargs)

        bar = Bar(self._global_opts(title, td, dark, **kwargs))
        bar.add_xaxis(df[x_col].astype(str).tolist())
        for i, yc in enumerate(y_cols):
            c = td["colors"][i % len(td["colors"])]
            bar.add_yaxis(
                yc, df[yc].round(2).tolist(), color=c,
                itemstyle_opts=opts.ItemStyleOpts(
                    border_radius=[6, 6, 0, 0],
                ),
            )
        bar.set_global_opts(
            title_opts=self._title(title or f"柱状图 - {x_col}", td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis(y_cols[0] if y_cols else "", dark),
        )
        return bar.render_embed()

    def _line(self, df, x_col, y_cols, title, td, dark, **kwargs):
        # Auto dual Y-axis if scales differ >5x
        if len(y_cols) >= 2:
            left_cols, right_cols = self._needs_dual_axis(df, y_cols)
            if right_cols:
                return self._make_dual_axis_line(df, x_col, y_cols, td, dark, title=title, **kwargs)

        line = Line(self._global_opts(title, td, dark, **kwargs))
        line.add_xaxis(df[x_col].astype(str).tolist())
        for i, yc in enumerate(y_cols):
            c = td["colors"][i % len(td["colors"])]
            line.add_yaxis(
                yc, df[yc].round(2).tolist(), color=c,
                is_smooth=True,
                linestyle_opts=opts.LineStyleOpts(width=3),
                areastyle_opts=opts.AreaStyleOpts(opacity=0.08),
                symbol="circle", symbol_size=6,
            )
        line.set_global_opts(
            title_opts=self._title(title or f"折线图 - {x_col}", td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis(y_cols[0] if y_cols else "", dark),
        )
        return line.render_embed()

    def _pie(self, df, name_col, y_cols, title, td, dark, **kwargs):
        value_col = y_cols[0] if isinstance(y_cols, list) else y_cols
        pie = Pie(self._global_opts(title, td, dark, **kwargs))
        data_pairs = [(str(row[name_col]), round(float(row[value_col].iloc[0]) if hasattr(row[value_col], 'iloc') else float(row[value_col]), 2))
                      for _, row in df.iterrows()]
        pie.add(
            "", data_pairs, radius=["45%", "78%"],
            label_opts=opts.LabelOpts(
                formatter="{b}: {d}%",
                color=td["title_color"],
                font_size=12,
                font_family="Segoe UI, Microsoft YaHei, sans-serif",
            ),
        )
        pie.set_colors(td["colors"])
        pie.set_global_opts(
            title_opts=self._title(title or f"饼图 - {name_col}", td["title_color"]),
            tooltip_opts=opts.TooltipOpts(
                trigger="item", formatter="{b}: {c} ({d}%)",
                background_color=self.DARK["tooltip_bg"] if dark else "#fff",
            ),
            legend_opts=opts.LegendOpts(
                pos_top="40px", type_="scroll",
                textstyle_opts=opts.TextStyleOpts(
                    color=self.DARK["text2"] if dark else "#64748b",
                ),
            ),
        )
        return pie.render_embed()

    def _scatter(self, df, x_col, y_cols, title, td, dark, **kwargs):
        sc = Scatter(self._global_opts(title, td, dark, **kwargs))
        x_data = df[x_col].tolist()
        sc.add_xaxis(x_data)
        for i, yc in enumerate(y_cols):
            c = td["colors"][i % len(td["colors"])]
            sc.add_yaxis(
                yc, df[yc].round(2).tolist(),
                symbol_size=20,
                itemstyle_opts=opts.ItemStyleOpts(color=c, opacity=0.9),
            )
        sc.set_global_opts(
            title_opts=self._title(title or f"散点图 - {x_col} vs {', '.join(y_cols)}", td["title_color"]),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
            xaxis_opts=opts.AxisOpts(type_="value", name=x_col, name_textstyle_opts=opts.TextStyleOpts(color=td["title_color"])),
            yaxis_opts=self._yaxis(", ".join(y_cols), dark),
        )
        return sc.render_embed()

    # ==================== 对比图表 ====================

    def _stacked_bar(self, df, x_col, y_cols, title, td, dark, **kwargs):
        bar = Bar(self._global_opts(title, td, dark, **kwargs))
        bar.add_xaxis(df[x_col].astype(str).tolist())
        for i, yc in enumerate(y_cols):
            bar.add_yaxis(
                yc, df[yc].round(2).tolist(),
                stack="stack1", color=td["colors"][i % len(td["colors"])],
            )
        bar.set_global_opts(
            title_opts=self._title(title or "堆叠柱状图", td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis("", dark),
        )
        return bar.render_embed()

    def _grouped_bar(self, df, x_col, y_cols, title, td, dark, **kwargs):
        # Auto dual Y-axis if scales differ >5x
        if len(y_cols) >= 2:
            left_cols, right_cols = self._needs_dual_axis(df, y_cols)
            if right_cols:
                return self._make_dual_axis_chart(Bar, df, x_col, y_cols, td, dark, title=title or "分组柱状图", **kwargs)

        bar = Bar(self._global_opts(title, td, dark, **kwargs))
        bar.add_xaxis(df[x_col].astype(str).tolist())
        for i, yc in enumerate(y_cols):
            c = td["colors"][i % len(td["colors"])]
            bar.add_yaxis(
                yc, df[yc].round(2).tolist(), color=c,
                itemstyle_opts=opts.ItemStyleOpts(
                    border_radius=[4, 4, 0, 0],
                ),
            )
        bar.set_global_opts(
            title_opts=self._title(title or "分组柱状图", td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis("", dark),
        )
        return bar.render_embed()

    # ==================== 分布图表 ====================

    def _boxplot(self, df, x_col, y_cols, title, td, dark, **kwargs):
        bp = Boxplot(self._global_opts(title, td, dark, **kwargs))
        data_list, x_labels = [], []
        for yc in y_cols:
            data_list.append(df[yc].dropna().tolist())
            x_labels.append(yc)
        bp.add_xaxis(x_labels)
        bp.add_yaxis("", bp.prepare_data(data_list))
        bp.set_global_opts(
            title_opts=self._title(title or "箱线图", td["title_color"]),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis("", dark),
        )
        return bp.render_embed()

    def _histogram(self, df, x_col, y_cols, title, td, dark, **kwargs):
        # histogram uses y-column only, x_col is ignored
        col = y_cols[0] if isinstance(y_cols, list) else y_cols
        values = df[col].dropna()
        counts, bins = np.histogram(values, bins=15)
        bin_labels = [f"{bins[i]:.1f}" for i in range(len(bins)-1)]

        bar = Bar(self._global_opts(title, td, dark, **kwargs))
        bar.add_xaxis(bin_labels)
        c = td["colors"][0]
        bar.add_yaxis(
            col, counts.tolist(), color=c,
            itemstyle_opts=opts.ItemStyleOpts(
                border_radius=[4, 4, 0, 0],
            ),
        )
        bar.set_global_opts(
            title_opts=self._title(title or f"直方图 - {col}", td["title_color"]),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(rotate=45)),
            yaxis_opts=self._yaxis("频数", dark),
        )
        return bar.render_embed()

    # ==================== 关系图表 (plotly) ====================

    def _heatmap(self, df, x_col, y_cols, title, td, dark, **kwargs):
        numeric_df = df.select_dtypes(include=[np.number])
        if len(numeric_df.columns) < 2:
            return "<p style='color:#f87171'>热力图需要至少2个数值列</p>"

        corr = numeric_df.corr().round(3)
        bg = self.DARK["bg"] if dark else td["bg_color"]
        fig = go.Figure(data=go.Heatmap(
            z=corr.values, x=corr.columns.tolist(), y=corr.columns.tolist(),
            colorscale=[[0, bg], [1, td["colors"][0]]],
            text=corr.values, texttemplate="%{text}",
        ))
        tc = td["title_color"]
        fig.update_layout(
            title=dict(text=title or "相关性热力图", font=dict(color=tc, size=16)),
            paper_bgcolor=bg, plot_bgcolor=bg,
            height=500, font=dict(color=tc),
        )
        return fig.to_html(full_html=False)

    def _scatter_matrix(self, df, x_col, y_cols, title, td, dark, **kwargs):
        numeric_df = df.select_dtypes(include=[np.number]).dropna()
        if len(numeric_df.columns) < 2:
            return "<p style='color:#f87171'>散点矩阵需要至少2个数值列</p>"
        cols = numeric_df.columns[:6].tolist()
        bg = self.DARK["bg"] if dark else td["bg_color"]
        fig = px.scatter_matrix(numeric_df[cols], title=title or "散点矩阵")
        tc = td["title_color"]
        fig.update_layout(
            paper_bgcolor=bg, plot_bgcolor=bg,
            height=600, font=dict(color=tc),
        )
        return fig.to_html(full_html=False)

    # ==================== 其他图表 ====================

    def _bubble(self, df, x_col, y_cols, title, td, dark, **kwargs):
        sc = Scatter(self._global_opts(title, td, dark, **kwargs))
        x_data = df[x_col].tolist()
        y_data = df[y_cols[0]].tolist() if y_cols else []
        size_col = y_cols[1] if len(y_cols) > 1 else (y_cols[0] if y_cols else None)
        if size_col:
            sizes = [max(5, min(50, abs(float(v))*5)) for v in df[size_col].fillna(1).tolist()]
        else:
            sizes = [15] * len(x_data)
        sc.add_xaxis(x_data)
        sc.add_yaxis(
            "", y_data, symbol_size=sizes,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(color=td["colors"][0], opacity=0.8),
        )
        sc.set_global_opts(
            title_opts=self._title(title or "气泡图", td["title_color"]),
            xaxis_opts=opts.AxisOpts(type_="value", name=x_col, name_textstyle_opts=opts.TextStyleOpts(color=td["title_color"])),
            yaxis_opts=self._yaxis(y_cols[0] if y_cols else "", dark),
        )
        return sc.render_embed()

    def _funnel(self, df, name_col, y_cols, title, td, dark, **kwargs):
        value_col = y_cols[0] if isinstance(y_cols, list) else y_cols
        funnel = Funnel(self._global_opts(title, td, dark, **kwargs))
        data = [(str(row[name_col]), round(float(row[value_col]), 2))
                 for _, row in df.iterrows()]
        data.sort(key=lambda x: x[1], reverse=True)
        funnel.add("", data, color=td["colors"])
        funnel.set_global_opts(
            title_opts=self._title(title or "漏斗图", td["title_color"]),
            tooltip_opts=opts.TooltipOpts(trigger="item"),
        )
        return funnel.render_embed()

    def _treemap(self, df, x_col, y_cols, title, td, dark, **kwargs):
        tm = TreeMap(self._global_opts(title, td, dark, **kwargs))
        data = [{"value": round(float(row[yc]), 2), "name": str(row[x_col])}
                for _, row in df.iterrows() for yc in y_cols[:1]]
        tm.add("", data, leaf_depth=1, label_opts=opts.LabelOpts(position="inside"))
        tm.set_global_opts(
            title_opts=self._title(title or "矩形树图", td["title_color"]),
        )
        tm.set_colors(td["colors"])
        return tm.render_embed()

    def _area(self, df, x_col, y_cols, title, td, dark, **kwargs):
        # Auto dual Y-axis if scales differ >5x
        if len(y_cols) >= 2:
            left_cols, right_cols = self._needs_dual_axis(df, y_cols)
            if right_cols:
                return self._make_dual_axis_line(df, x_col, y_cols, td, dark, title=title, **kwargs)

        line = Line(self._global_opts(title, td, dark, **kwargs))
        line.add_xaxis(df[x_col].astype(str).tolist())
        for i, yc in enumerate(y_cols):
            c = td["colors"][i % len(td["colors"])]
            line.add_yaxis(
                yc, df[yc].round(2).tolist(), color=c,
                areastyle_opts=opts.AreaStyleOpts(opacity=0.25),
                is_smooth=True, linestyle_opts=opts.LineStyleOpts(width=2),
            )
        line.set_global_opts(
            title_opts=self._title(title or f"面积图 - {x_col}", td["title_color"]),
            tooltip_opts=self._tooltip(dark),
            legend_opts=self._legend(dark),
            xaxis_opts=self._xaxis("", dark),
            yaxis_opts=self._yaxis("", dark),
        )
        return line.render_embed()

    def _radar(self, df, x_col, y_cols, title, td, dark, **kwargs):
        radar = Radar(self._global_opts(title, td, dark, **kwargs))
        y_col = y_cols[0] if y_cols else None
        if not y_col:
            return self._bar(df, x_col, [df.columns[1]], title, td, dark, **kwargs)
        values = df[y_col].dropna().tolist()
        max_val = max(values) * 1.2
        schema = [opts.RadarIndicatorItem(name=str(row[x_col]), max_=round(max_val, 1))
                  for _, row in df.iterrows()]
        radar.add_schema(schema=schema[:10])
        radar.add(
            "", [values[:10]], color=td["colors"][0],
            areastyle_opts=opts.AreaStyleOpts(opacity=0.25),
        )
        radar.set_global_opts(
            title_opts=self._title(title or "雷达图", td["title_color"]),
        )
        return radar.render_embed()

    def _gauge(self, df, x_col, y_cols, title, td, dark, **kwargs):
        value_col = y_cols[0] if isinstance(y_cols, list) else y_cols
        if not value_col:
            return "<p style='color:#f87171'>仪表盘需要一个数值列</p>"
        val = round(float(df[value_col].mean()), 1)
        gauge = Gauge(self._global_opts(title, td, dark))
        gauge.add(
            "", [("", val)], split_number=5,
            axisline_opts=opts.AxisLineOpts(
                linestyle_opts=opts.LineStyleOpts(
                    color=[(0.3, td["colors"][2]), (0.7, td["colors"][1]), (1, td["colors"][0])],
                    width=30,
                ),
            ),
        )
        gauge.set_global_opts(
            title_opts=self._title(title or f"仪表盘 - {value_col}", td["title_color"]),
        )
        return gauge.render_embed()

    # ==================== Spec 导出（纯 ECharts option JSON） ====================

    def build_spec(self, df: pd.DataFrame, chart_type: str, x_column: str,
                   y_columns: list, title: str, theme: str,
                   chart_theme: str = "light", style_template: str = "clean", **kwargs) -> dict:
        """返回 ECharts option dict（JSON-serializable），用于前端 setOption() 渲染。

        对于 pyecharts 渲染的图表类型：从 render_embed() 的 HTML 中提取 option JSON。
        对于 plotly 渲染的图表类型（heatmap/scatter_matrix）：返回占位 spec。
        """
        if chart_type in ("heatmap", "scatter_matrix"):
            # plotly 图表暂时保留 HTML 模式
            html = self.build(df, chart_type, x_column, y_columns, title, theme,
                              chart_theme, style_template, **kwargs)
            return {"_html": html, "_type": chart_type, "_note": "plotly — rendered via HTML"}

        html = self.build(df, chart_type, x_column, y_columns, title, theme,
                          chart_theme, style_template, **kwargs)
        m = re.search(r'option_\w+\s*=\s*(\{.*?\});\s*\n\s*chart_\w+\.setOption', html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return {"_error": "Failed to extract spec from HTML", "_html": html}

    # ==================== 导出 ====================

    def export_png(self, chart_html: str, export_id: str, dpi: int, export_dir: str) -> str:
        filename = f"chart_{export_id}.html"
        filepath = os.path.join(export_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"<html><head><meta charset='utf-8'></head><body>{chart_html}</body></html>")
        return filepath
