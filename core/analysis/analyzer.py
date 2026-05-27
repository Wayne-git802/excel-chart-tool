"""数据分析服务：列类型推断、统计摘要、列间关系"""
import pandas as pd
import numpy as np

TYPE_LABEL_CN = {
    "numeric": "数值",
    "int_category": "整数分类",
    "binary": "二值",
    "datetime": "日期",
    "category": "分类",
    "text": "文本",
    "empty": "空",
}


def _column_info(col_name: str, series: pd.Series) -> dict:
    """Build a single column info dict (frontend-compatible)."""
    s = series.dropna()
    null_pct = round((series.isna().sum() / len(series)) * 100, 1)
    unique_count = s.nunique() if len(s) > 0 else 0

    if len(s) == 0:
        return {
            "name": col_name,
            "dtype": "empty",
            "dtype_cn": TYPE_LABEL_CN["empty"],
            "unique_count": 0,
            "null_pct": 100.0,
            "min": None, "max": None, "mean": None,
        }

    dtype = str(s.dtype)

    # bool detection must come BEFORE numeric (pandas bools are numeric subtypes)
    if pd.api.types.is_bool_dtype(s):
        type_label = "binary"

    elif pd.api.types.is_numeric_dtype(s):
        if unique_count <= 2:
            type_label = "binary"
        elif unique_count <= 20:
            type_label = "int_category"
        else:
            type_label = "numeric"
    elif pd.api.types.is_datetime64_any_dtype(s):
        type_label = "datetime"
    else:
        type_label = "category" if unique_count <= 20 else "text"

    info = {
        "name": col_name,
        "dtype": dtype,
        "dtype_cn": TYPE_LABEL_CN.get(type_label, type_label),
        "unique_count": unique_count,
        "null_pct": null_pct,
        "min": None,
        "max": None,
        "mean": None,
    }

    if pd.api.types.is_numeric_dtype(s):
        info["min"] = round(float(s.min()), 2)
        info["max"] = round(float(s.max()), 2)
        info["mean"] = round(float(s.mean()), 2)

    return info


def build_analysis(df: pd.DataFrame) -> dict:
    """完整的分析结果，供前端和 AI 使用"""
    columns = [_column_info(col, df[col]) for col in df.columns]
    numeric_cols = [c["name"] for c in columns if c["dtype_cn"] in ("数值", "整数分类")]
    category_cols = [c["name"] for c in columns if c["dtype_cn"] in ("分类", "整数分类", "二值")]

    # 相关性矩阵（仅数值列）
    top_corr = {}
    if len(numeric_cols) >= 2:
        corr_matrix = df[numeric_cols].corr().round(3)
        pairs = []
        for i, a in enumerate(numeric_cols):
            for j, b in enumerate(numeric_cols):
                if i < j:
                    val = corr_matrix.loc[a, b]
                    if pd.notna(val):
                        pairs.append((f"{a} × {b}", abs(float(val))))
        pairs.sort(key=lambda x: x[1], reverse=True)
        top_corr = dict(pairs[:10])

    return {
        "row_count": len(df),
        "col_count": len(df.columns),
        "columns": columns,
        "numeric_cols": numeric_cols,
        "category_cols": category_cols,
        "top_correlations": top_corr,
    }


def build_preview(df: pd.DataFrame, n: int = 100) -> dict:
    """返回前 n 行数据预览，值全部转为 Python 原生类型"""
    preview_df = df.head(n).copy()
    # Convert to safe JSON-serializable types
    for col in preview_df.columns:
        if pd.api.types.is_datetime64_any_dtype(preview_df[col]):
            preview_df.loc[:, col] = preview_df[col].dt.strftime("%Y-%m-%d").where(
                preview_df[col].notna(), other=None
            )
    
    # Convert entire DataFrame to object dtype, then replace all NaN with None
    preview_df = preview_df.astype(object).where(preview_df.notna(), other=None)
    rows = preview_df.values.tolist()
    
    return {
        "columns": [str(c) for c in preview_df.columns],
        "rows": rows,
        "preview_n": len(preview_df),
    }
