"""Excel / CSV 读取与解析服务"""
import pandas as pd
from pathlib import Path
from typing import Optional

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

CSV_SHEET_NAME = "Sheet1"  # virtual sheet name for CSV files


def _read_file(filepath: str, **kwargs):
    """Read Excel (.xlsx/.xls) or CSV with automatic engine selection."""
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else "xlsx"

    if ext == "csv":
        return pd.read_csv(filepath, **kwargs)

    if ext == "xls":
        # Old binary .xls — read with xlrd 1.2.0 directly, then convert to DataFrame
        # (pandas rejects xlrd < 2.0, but 2.0 dropped .xls support)
        import xlrd
        wb = xlrd.open_workbook(filepath)
        sheet_name = kwargs.pop("sheet_name", 0)
        if isinstance(sheet_name, str):
            ws = wb.sheet_by_name(sheet_name)
        else:
            ws = wb.sheet_by_index(sheet_name)
        # Read all data
        data = []
        for r in range(ws.nrows):
            data.append([ws.cell_value(r, c) for c in range(ws.ncols)])
        # Handle header
        header_row = kwargs.pop("header", 0)
        if header_row is None:
            header_row = 0
        if header_row < len(data):
            columns = data[header_row]
            rows = data[header_row + 1:]
        else:
            columns = list(range(len(data[0]) if data else 0))
            rows = data
        return pd.DataFrame(rows, columns=columns)

    return pd.read_excel(filepath, engine="openpyxl", **kwargs)


def get_sheets(filepath: str) -> list[str]:
    """返回文件的所有 sheet 名。CSV 返回虚拟 sheet。"""
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else "xlsx"

    if ext == "csv":
        return [CSV_SHEET_NAME]

    if ext == "xls":
        import xlrd
        wb = xlrd.open_workbook(filepath)
        return wb.sheet_names()

    try:
        xl = pd.ExcelFile(filepath, engine="openpyxl")
        return xl.sheet_names
    except Exception:
        xl = pd.ExcelFile(filepath)
        return xl.sheet_names


def load_sheet(filepath: str, sheet_name: str | int = 0, header_row: int | None = None) -> pd.DataFrame:
    """加载指定 sheet。header_row=None 时自动检测真正的表头行。CSV 忽略 sheet_name。"""
    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else "xlsx"

    if ext == "csv":
        return _read_file(filepath)

    if header_row is not None:
        return _read_file(filepath, sheet_name=sheet_name, header=header_row)

    # 自动检测：找第一个所有列都有非空字符串的行
    raw = _read_file(filepath, sheet_name=sheet_name, header=None, nrows=10)
    for row_idx in range(len(raw)):
        row_vals = raw.iloc[row_idx].dropna().values
        if len(row_vals) >= max(2, len(raw.columns) * 0.5):
            # 检查是否像列名（字符串类型、非纯数字）
            str_count = sum(1 for v in row_vals if isinstance(v, str) and not str(v).replace('.', '').isdigit())
            if str_count >= len(row_vals) * 0.5:
                return _read_file(filepath, sheet_name=sheet_name, header=row_idx)

    # 兜底
    return _read_file(filepath, sheet_name=sheet_name)


def detect_header_issues(df: pd.DataFrame) -> dict:
    """检测列名问题。返回 {has_issues: bool, unnamed_cols: [...], suggestions: [...]}"""
    unnamed = [c for c in df.columns if 'Unnamed' in str(c) or str(c).strip() == '' or pd.isna(c)]
    return {
        "has_issues": len(unnamed) > 0,
        "unnamed_cols": unnamed,
        "header_row_used": 0
    }


def get_preview_data(df: pd.DataFrame, rows: int = 20) -> list[dict]:
    """取前 N 行用于前端预览，返回 JSON-friendly 格式"""
    return df.head(rows).fillna("").to_dict(orient="records")
