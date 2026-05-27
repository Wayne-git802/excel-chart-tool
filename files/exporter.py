"""导出模块 — 用 Chrome headless 转 PNG/PDF"""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

EXPORT_DIR = Path(__file__).parent.parent / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = Path(__file__).parent.parent / "static"


def _find_browser() -> str | None:
    """查找可用浏览器（Chrome > Edge）"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        shutil.which("msedge"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def _make_full_html(chart_html: str, width: int = 1400, height: int = 900) -> str:
    """生成自包含 HTML，内联 ECharts JS"""
    echarts_path = STATIC_DIR / "js" / "echarts.min.js"
    if echarts_path.exists():
        with open(echarts_path, "r", encoding="utf-8") as f:
            echarts_js = f.read()
    else:
        echarts_js = ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; }}
  body {{ background: white; width: {width}px; height: {height}px; }}
  .chart-container {{ width: {width}px; height: {height}px; }}
</style>
<script>{echarts_js}</script>
</head><body>{chart_html}</body></html>"""


def export_png(chart_html: str, export_id: str, dpi: int = 150) -> str | None:
    """用浏览器 headless 截图导出 PNG"""
    browser = _find_browser()
    if not browser:
        return _fallback_html(chart_html, export_id)

    width = int(1400 * dpi / 150)
    height = int(900 * dpi / 150)

    html = _make_full_html(chart_html, width, height)

    # 写入临时 HTML
    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", delete=False, encoding="utf-8"
    )
    tmp.write(html)
    tmp.close()

    png_path = EXPORT_DIR / f"{export_id}.png"

    try:
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--window-size={width},{height}",
                f"--screenshot={png_path}",
                f"file:///{tmp.name.replace(os.sep, '/')}",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except subprocess.CalledProcessError:
        return _fallback_html(chart_html, export_id)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    return str(png_path)


def export_pdf(chart_html: str, export_id: str) -> str | None:
    """用浏览器 headless 导出 PDF"""
    browser = _find_browser()
    if not browser:
        return _fallback_html(chart_html, export_id)

    html = _make_full_html(chart_html)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", delete=False, encoding="utf-8"
    )
    tmp.write(html)
    tmp.close()

    pdf_path = EXPORT_DIR / f"{export_id}.pdf"

    try:
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--print-to-pdf=" + str(pdf_path),
                f"file:///{tmp.name.replace(os.sep, '/')}",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except subprocess.CalledProcessError:
        return _fallback_html(chart_html, export_id)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    return str(pdf_path)


def _fallback_html(chart_html: str, export_id: str) -> str:
    """无 Chrome 时保存 HTML 供浏览器打开"""
    html_path = EXPORT_DIR / f"{export_id}.html"
    full = _make_full_html(chart_html)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(full)
    return str(html_path)
