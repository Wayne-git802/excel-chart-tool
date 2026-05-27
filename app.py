"""
Excel 智能图表工具 — FastAPI Backend
"""
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import json
import time
import pandas as pd

from files.reader import load_sheet, get_sheets, detect_header_issues
from core.analysis.analyzer import build_analysis, build_preview
from core.chart.builder import ChartBuilder
from state.manager import StateManager
from state.logger import schedule_cleanup
from models.database import TemplateDB

app = FastAPI(title="Excel Chart Tool")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "exports"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/exports", StaticFiles(directory=os.path.join(BASE_DIR, "exports")), name="exports")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.auto_reload = True

# In-memory store: file_path -> (dataframe, timestamp) TTL cache
_cache: dict = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour

# In-memory profile cache: "file_path::sheet" -> DatasetProfile
_profile_cache: dict = {}


def _cache_get(key: str) -> pd.DataFrame | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    df, ts = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        del _cache[key]
        return None
    return df


def _cache_set(key: str, df: pd.DataFrame):
    _cache[key] = (df, time.time())
    # Evict oldest entries if cache grows too large
    if len(_cache) > 50:
        oldest_key = min(_cache, key=lambda k: _cache[k][1])
        del _cache[oldest_key]
db = TemplateDB(os.path.join(BASE_DIR, "data", "templates.db"))
state_manager = StateManager(os.path.join(BASE_DIR, "data", "agent_state.db"))
chart_builder = ChartBuilder()
_chat_service = None  # lazy init — heavy import (~60s), only on first /api/chat call

# Start log cleanup scheduler (runs every 6 hours, keeps 7 days)
schedule_cleanup(interval_hours=6, keep_days=7)


def _read_df(file_path: str, sheet_name: str) -> pd.DataFrame:
    """Read dataframe from file, with TTL caching + auto-eviction."""
    key = f"{file_path}::{sheet_name}"
    df = _cache_get(key)
    if df is None:
        df = load_sheet(file_path, sheet_name)
        _cache_set(key, df)
    return df


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve index.html directly (bypass Jinja2 cache)"""
    index_path = os.path.join(BASE_DIR, "templates", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Auto-version static assets to bust QQ browser cache
    import time
    ver = str(int(time.time()))
    content = content.replace('__CACHEBUST__', ver)
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "ETag": ver,  # forces revalidation every request
        },
    )


# ─── API ──────────────────────────────────────────────


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Upload Excel, detect sheets."""
    # Server-side file type validation
    filename = file.filename or ""
    print(f"[UPLOAD] received filename: {repr(filename)}", flush=True)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    print(f"[UPLOAD] ext={repr(ext)}", flush=True)
    if ext not in ("xlsx", "xls", "csv"):
        return JSONResponse(
            {"error": f"不支持的文件格式 .{ext}，请上传 .xlsx / .xls / .csv 文件 (收到: {filename})"},
            status_code=400,
        )

    path = os.path.join(BASE_DIR, "uploads", filename)
    with open(path, "wb") as f:
        f.write(await file.read())

    try:
        sheets = get_sheets(path)
    except Exception as e:
        return JSONResponse(
            {"error": f"无法读取文件：{e}"},
            status_code=400,
        )
    return JSONResponse({"file_path": path, "sheets": sheets})


@app.post("/api/analyze")
async def analyze(file_path: str = Form(...), sheet_name: str = Form(...)):
    """Read sheet and return analysis + profile."""
    try:
        if not os.path.exists(file_path):
            return JSONResponse({"error": "File not found"}, status_code=400)

        df = _read_df(file_path, sheet_name)
        analysis = build_analysis(df)
        preview = build_preview(df)
        issues = detect_header_issues(df)

        # ── v10: Profile the dataset ──
        from core.profiling.profiler import DataProfiler
        profile = DataProfiler.enhance(analysis["columns"], df)
        _profile_cache[f"{file_path}::{sheet_name}"] = profile

        return JSONResponse({
            "columns": analysis["columns"],
            "row_count": analysis["row_count"],
            "col_count": analysis["col_count"],
            "preview": preview,
            "top_correlations": analysis["top_correlations"],
            "header_issues": issues,
            "profile": profile.to_dict(),  # v10
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"分析失败：{e}"}, status_code=500)


@app.post("/api/reanalyze")
async def reanalyze(file_path: str = Form(...), sheet_name: str = Form(...), header_row: int = Form(0)):
    """用户指定 header_row 后重新分析"""
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=400)

    df = load_sheet(file_path, sheet_name, header_row=header_row)
    # Update cache with the new dataframe
    key = f"{file_path}::{sheet_name}"
    _cache_set(key, df)

    analysis = build_analysis(df)
    preview = build_preview(df)
    issues = detect_header_issues(df)
    issues["header_row_used"] = header_row

    return JSONResponse({
        "columns": analysis["columns"],
        "row_count": analysis["row_count"],
        "col_count": analysis["col_count"],
        "preview": preview,
        "top_correlations": analysis["top_correlations"],
        "header_issues": issues,
    })


@app.post("/api/recommend")
async def recommend(file_path: str = Form(...), sheet_name: str = Form(...), refine_prompt: str = Form("")):
    """AI chart recommendations via DeepSeek. Optionally refine with user prompt."""
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=400)

    df = _read_df(file_path, sheet_name)
    analysis = build_analysis(df)

    try:
        from core.analysis.recommender import get_recommendations
        recs = get_recommendations(df, analysis, refine_prompt=refine_prompt)
    except Exception as e:
        recs = [
            {"type": "bar", "type_cn": "柱状图",
             "x": analysis["numeric_cols"][0] if analysis["numeric_cols"] else "",
             "y": analysis["numeric_cols"][1:2] if len(analysis["numeric_cols"]) > 1 else [],
             "reason": "默认推荐（AI 服务暂不可用）"}
        ]
    return JSONResponse({"recommendations": recs})


@app.post("/api/chart")
async def gen_chart(
    file_path: str = Form(...),
    sheet_name: str = Form(...),
    chart_type: str = Form(...),
    x_column: str = Form(""),
    y_columns: str = Form("[]"),
    title: str = Form(""),
    theme: str = Form("business"),
    chart_theme: str = Form("light"),
    style_template: str = Form("clean"),
):
    """Generate chart HTML."""
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=400)

    df = _read_df(file_path, sheet_name).head(100)
    y_list = json.loads(y_columns) if y_columns else []

    # Auto-detect y_columns if empty
    if not y_list:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]) and str(col) != x_column:
                y_list.append(str(col))
                if len(y_list) >= 2:
                    break
        if not y_list and df.columns.size > 1:
            y_list = [str(df.columns[1])]

    # Validate columns exist
    all_cols = set(df.columns)
    if x_column and x_column not in all_cols:
        return JSONResponse({"error": f"X 轴列 '{x_column}' 不存在"}, status_code=400)
    for yc in y_list:
        if yc not in all_cols:
            return JSONResponse({"error": f"Y 轴列 '{yc}' 不存在"}, status_code=400)

    # Auto-detect x_column for chart types that need it
    if not x_column:
        no_x_types = {"heatmap", "scatter_matrix", "histogram", "boxplot", "gauge", "pie"}
        if chart_type not in no_x_types:
            # Prefer first non-numeric column, or fall back to first column
            for col in df.columns:
                if not pd.api.types.is_numeric_dtype(df[col]):
                    x_column = str(col)
                    break
            if not x_column and df.columns.size > 0:
                x_column = str(df.columns[0])

    html = chart_builder.build(df, chart_type, x_column, y_list, title, theme, chart_theme, style_template)
    spec = chart_builder.build_spec(df, chart_type, x_column, y_list, title, theme, chart_theme, style_template)
    return JSONResponse({"chart_html": html, "chart_spec": spec})


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    """SSE streaming chat endpoint — natural language → chart generation."""
    global _chat_service
    if _chat_service is None:
        from core.chat_service import ChatService
        _chat_service = ChatService(state_manager, chart_builder)
        import builtins
        try:
            with builtins.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "debug.log"),"a",encoding="utf-8") as f:
                f.write("[APP] ChatService initialized\n")
        except: pass

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "请求体需要 JSON 格式"}, status_code=400)

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse({"error": "消息不能为空"}, status_code=400)

    session_id = body.get("session_id", "")

    # Bind file context (optional — frontend can pass file info)
    file_path = body.get("file_path", "")
    sheet_name = body.get("sheet_name", "")
    chat_context = body.get("context", {}) or {}
    insight_ctx = chat_context.get("insight") if isinstance(chat_context, dict) else None

    # Load or create state
    if session_id:
        state = state_manager.load_state(session_id)
        if state.session_id != session_id:
            state = state_manager.new_session()
            state.session_id = session_id
    else:
        state = state_manager.new_session()

    # Bind file if provided and different from current
    if file_path and file_path != state.file_path:
        state.file_path = file_path
        state.sheet_name = sheet_name
        # Load columns from analyzer if not yet populated
        if not state.columns and file_path and sheet_name:
            try:
                df_temp = _read_df(file_path, sheet_name)
                analysis = build_analysis(df_temp)
                state.columns = analysis.get("columns", [])
                state.row_count = len(df_temp)
            except Exception:
                pass

        # ── v10: Ensure profile is cached ──
        cache_key = f"{file_path}::{sheet_name}"
        if cache_key not in _profile_cache:
            try:
                from core.profiling.profiler import DataProfiler
                df_temp = _read_df(file_path, sheet_name)
                analysis = build_analysis(df_temp)
                _profile_cache[cache_key] = DataProfiler.enhance(analysis["columns"], df_temp)
            except Exception:
                pass

        state_manager.save_state(state)

    # ── v10: Get profile from cache (NOT from state) ──
    cache_key = f"{file_path}::{sheet_name}"
    profile = _profile_cache.get(cache_key) if file_path else None

    # Get df from cache
    df = None
    if state.file_path and state.sheet_name:
        try:
            df = _read_df(state.file_path, state.sheet_name)
        except Exception:
            pass

    prefs = state.user_preferences

    async def sse_stream():
        async for event in _chat_service.chat(
            message=message,
            session_id=state.session_id,
            state=state,
            df=df,
            theme=prefs.fav_color_scheme,
            chart_theme=prefs.theme,
            insight_context=insight_ctx,
            profile=profile,  # v10
        ):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/explore")
async def explore_deprecated():
    """Deprecated — exploration merged into /api/chat. Returns 410 Gone."""
    return JSONResponse(
        {"error": "deprecated", "redirect": "/api/chat",
         "message": "探索模式已合并到对话模式，请使用 /api/chat"},
        status_code=410
    )


# ── InsightEngine endpoints ──

@app.post("/api/insights")
async def run_insights(
    file_path: str = Form(...),
    sheet_name: str = Form(...),
):
    """Run InsightEngine on uploaded data and return clustered insights."""
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found"}, status_code=400)

    try:
        df = _read_df(file_path, sheet_name).head(2000)  # cap for performance

        # Run engine
        from core.analysis.insight_engine import InsightEngine
        engine = InsightEngine()
        result = engine.run(df, context={"file_path": file_path, "sheet_name": sheet_name})

        # Serialize: ClusteredInsight → dict
        def _serialize_insight(ci) -> dict:
            r = ci.representative
            return {
                "type": r.type,
                "title": r.title,
                "description": r.description,
                "score": round(r.score, 3),
                "effect_size": round(r.effect_size, 3) if r.effect_size else 0,
                "confidence": round(ci.confidence_aggregated, 3),
                "source_count": ci.source_count,
                "sources": ci.sources,
                "columns": r.columns or [],
                "chart_hint": r.chart_spec_hint or {},
                "payload": r.payload or {},
            }

        return JSONResponse({
            "insights": [_serialize_insight(c) for c in result["insights"]],
            "top_insights": [_serialize_insight(c) for c in result["top_insights"]],
            "raw_count": result["raw_count"],
            "cluster_count": result["cluster_count"],
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"洞察分析失败：{e}"}, status_code=500)


@app.get("/api/templates")
async def list_templates():
    return JSONResponse({"templates": db.list_templates()})


@app.post("/api/templates")
async def save_template(
    name: str = Form(...),
    chart_type: str = Form(...),
    x_column: str = Form(...),
    y_columns: str = Form("[]"),
    config: str = Form("{}"),
):
    tid = db.save_template(name, chart_type, x_column, y_columns, config)
    return JSONResponse({"id": tid, "message": "Template saved"})


@app.delete("/api/templates/{template_id}")
async def delete_template(template_id: int):
    db.delete_template(template_id)
    return JSONResponse({"message": "Template deleted"})


@app.get("/api/themes")
async def list_themes():
    return JSONResponse({"themes": chart_builder.get_themes()})


@app.post("/api/export")
async def export_chart(
    chart_html: str = Form(...),
    format: str = Form("png"),
):
    """Export chart as PNG/PDF/HTML."""
    import uuid
    from files.exporter import export_png, export_pdf

    export_id = uuid.uuid4().hex[:8]

    if format == "pdf":
        filepath = export_pdf(chart_html, export_id)
        if filepath:
            filename = os.path.basename(filepath)
            return JSONResponse({"url": f"/exports/{filename}", "format": "pdf"})

    if format in ("png", "png_hd"):
        dpi = 300 if format == "png_hd" else 150
        filepath = export_png(chart_html, export_id, dpi=dpi)
        if filepath:
            filename = os.path.basename(filepath)
            return JSONResponse({"url": f"/exports/{filename}", "format": format})

    # Fallback: save as HTML
    filepath = os.path.join(BASE_DIR, "exports", f"chart_{export_id}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<script src="/static/js/echarts.min.js"></script>
</head><body>{chart_html}</body></html>""")
    return JSONResponse({"url": f"/exports/chart_{export_id}.html", "format": "html"})


# ─── v10 Debug ─────────────────────────────────────────────

@app.get("/api/debug/ledger")
async def debug_ledger(session_id: str = ""):
    """Return decision ledger for a session."""
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    state = state_manager.load_state(session_id)
    if not state or not hasattr(state, "ledger") or state.ledger is None:
        return JSONResponse({"error": "no ledger found for session"}, status_code=404)
    return JSONResponse(state.ledger.to_dict())


@app.get("/api/debug/profile")
async def debug_profile(session_id: str = ""):
    """Return dataset profile for a session."""
    if not session_id:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    state = state_manager.load_state(session_id)
    if not state or state.profile is None:
        return JSONResponse({"error": "no profile found for session"}, status_code=404)
    return JSONResponse(state.profile.to_dict())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8800)
