"""FastAPI router for V2 conversational data runtime.

Session lifecycle:
  upload -> session created -> apply operations -> undo -> get state / chart
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from files.reader import get_sheets, load_sheet
from core.v2.backends.pandas_backend import PandasBackend
from core.v2.ir.column_info import ColumnInfo, extract_columns
from core.v2.ir.operations import (
    ChartPatchOp,
    FilterOp,
    LimitOp,
    Operation,
    SortOp,
)
from core.v2.state.conversation_state import ConversationState, create_session

router = APIRouter(prefix="/api/v2")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ── In-memory stores ───────────────────────────────────────

_cache: dict[str, tuple[pd.DataFrame, float]] = {}
_CACHE_TTL = 3600

_sessions: dict[str, tuple[str, pd.DataFrame, list[ColumnInfo], ConversationState]] = {}

_backend = PandasBackend()

_OP_MAP: dict[str, type] = {
    "FilterOp": FilterOp,
    "SortOp": SortOp,
    "LimitOp": LimitOp,
    "ChartPatchOp": ChartPatchOp,
}


# ── Helpers ────────────────────────────────────────────────

def _cache_key(file_path: str, sheet_name: str) -> str:
    return f"{file_path}::{sheet_name}"


def _cache_get(key: str) -> pd.DataFrame | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    df, ts = entry
    if time.time() - ts > _CACHE_TTL:
        del _cache[key]
        return None
    return df


def _cache_set(key: str, df: pd.DataFrame) -> None:
    _cache[key] = (df, time.time())
    if len(_cache) > 50:
        oldest = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest]


def _read_df(file_path: str, sheet_name: str) -> pd.DataFrame:
    key = _cache_key(file_path, sheet_name)
    df = _cache_get(key)
    if df is None:
        df = load_sheet(file_path, sheet_name)
        _cache_set(key, df)
    return df


def _deserialize_op(data: dict[str, Any]) -> Operation:
    data = dict(data)
    op_type = data.pop("type")
    cls = _OP_MAP[op_type]
    if "y_columns" in data and isinstance(data["y_columns"], list):
        data["y_columns"] = tuple(data["y_columns"])
    return cls(**data)


# ── Endpoints ──────────────────────────────────────────────

@router.post("/upload")
async def upload(file: UploadFile = File(...), sheet_name: str = Form("")):
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("xlsx", "xls", "csv"):
        return JSONResponse(
            {"ok": False, "error": f"不支持的文件格式 .{ext}"},
            status_code=400,
        )

    path = os.path.join(UPLOADS_DIR, filename)
    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        sheets = get_sheets(path)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"无法读取文件：{e}"}, status_code=400)

    if not sheet_name:
        sheet_name = sheets[0] if sheets else "Sheet1"
    elif sheet_name not in sheets:
        return JSONResponse({"ok": False, "error": f"工作表 '{sheet_name}' 不存在"}, status_code=400)

    try:
        df = _read_df(path, sheet_name)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取数据失败：{e}"}, status_code=500)

    file_key = _cache_key(path, sheet_name)
    meta = create_session(file_key, df, _backend)

    state = ConversationState(session_id=meta["session_id"], file_key=file_key)
    columns_info = extract_columns(df, _backend)
    _sessions[meta["session_id"]] = (file_key, df, columns_info, state)

    return JSONResponse({
        "ok": True,
        "error": None,
        "file_path": path,
        "sheets": sheets,
        "session": meta,
    })


@router.post("/sessions/{sid}/apply")
async def apply_operation(sid: str, request: Request):
    entry = _sessions.get(sid)
    if entry is None:
        return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)

    _file_key, base_df, columns_info, state = entry

    try:
        body = await request.json()
        op_data = body.get("op", {})
        if not op_data or "type" not in op_data:
            return JSONResponse({"ok": False, "error": "缺少 op 或 op.type"}, status_code=400)
        op = _deserialize_op(op_data)
    except (KeyError, TypeError, ValueError) as e:
        return JSONResponse({"ok": False, "error": f"无效的操作：{e}"}, status_code=400)

    result = state.apply_operation(op, base_df, columns_info, _backend)
    return JSONResponse(result)


@router.post("/sessions/{sid}/undo")
async def undo_operation(sid: str):
    entry = _sessions.get(sid)
    if entry is None:
        return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)

    _file_key, base_df, columns_info, state = entry
    result = state.undo_operation(base_df, columns_info, _backend)
    return JSONResponse(result)


@router.get("/sessions/{sid}/state")
async def get_state(sid: str):
    entry = _sessions.get(sid)
    if entry is None:
        return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)

    _file_key, base_df, columns_info, state = entry
    result = state.to_frontend_state(base_df, columns_info, _backend)
    return JSONResponse({"ok": True, "error": None, **result})


@router.get("/sessions/{sid}/chart")
async def get_chart(sid: str):
    entry = _sessions.get(sid)
    if entry is None:
        return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)

    _file_key, base_df, _columns_info, state = entry
    df = state.materialize(base_df, _backend)
    return JSONResponse({
        "ok": True,
        "error": None,
        "data": df.to_dict("records"),
        "row_count": len(df),
    })
