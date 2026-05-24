"""
Observability logger — lightweight JSONL append-only logging.

Three streams:
  - prompts.jsonl  : every LLM call (prompt, response, model, tokens, latency)
  - actions.jsonl  : every user action (action, params, result)
  - errors.jsonl   : every error (traceback, context)

Zero dependencies beyond stdlib. Append-only JSONL — no schema, no migrations.
Write failures silently skipped — logging never breaks the main flow.
"""
import json
import os
import time
import threading
from datetime import datetime, timedelta


LOG_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


class SessionLogger:
    """Per-session logger that appends to JSONL files under logs/{session_id}/."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.dir = os.path.join(LOG_ROOT, session_id)
        self._lock = threading.Lock()

    # ── path helpers ──────────────────────────────────────────
    def _ensure_dir(self):
        os.makedirs(self.dir, exist_ok=True)

    def _append(self, filename: str, record: dict):
        record.setdefault("ts", datetime.now().isoformat())
        try:
            self._ensure_dir()
            with self._lock:
                with open(os.path.join(self.dir, filename), "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # logging must never crash the app

    # ── public API ────────────────────────────────────────────

    def log_prompt(self, *, action: str, model: str, prompt: str,
                   response: str = "", tokens_in: int = 0, tokens_out: int = 0,
                   latency_ms: float = 0, extra: dict | None = None):
        self._append("prompts.jsonl", {
            "action": action,
            "model": model,
            "prompt": prompt,
            "response": response,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": round(latency_ms, 1),
            **(extra or {}),
        })

    def log_action(self, *, action: str, params: dict | None = None,
                   result: str = "ok", extra: dict | None = None):
        self._append("actions.jsonl", {
            "action": action,
            "params": params or {},
            "result": result,
            **(extra or {}),
        })

    def log_error(self, *, action: str, error: str,
                  traceback: str = "", context: dict | None = None):
        self._append("errors.jsonl", {
            "action": action,
            "error": error,
            "traceback": traceback,
            "context": context or {},
        })

    def get_meta(self) -> dict:
        """Summarise this session's logs for the debug panel."""
        try:
            prom_path = os.path.join(self.dir, "prompts.jsonl")
            err_path = os.path.join(self.dir, "errors.jsonl")
            total_tokens = 0
            prompt_count = 0
            if os.path.exists(prom_path):
                with open(prom_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                            total_tokens += rec.get("tokens_in", 0) + rec.get("tokens_out", 0)
                            prompt_count += 1
                        except json.JSONDecodeError:
                            pass
            error_count = 0
            if os.path.exists(err_path):
                error_count = sum(1 for _ in open(err_path, "r", encoding="utf-8"))
            return {
                "session_id": self.session_id,
                "prompt_count": prompt_count,
                "total_tokens": total_tokens,
                "error_count": error_count,
            }
        except Exception:
            return {"session_id": self.session_id, "error": "unable to read meta"}

    def get_recent(self, stream: str = "actions", limit: int = 20) -> list[dict]:
        """Return the last N entries from a stream (for debug panel)."""
        try:
            fpath = os.path.join(self.dir, f"{stream}.jsonl")
            if not os.path.exists(fpath):
                return []
            lines = []
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    lines.append(line)
            results = []
            for line in lines[-limit:]:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return results
        except Exception:
            return []


# ── global cleanup ───────────────────────────────────────────

def cleanup_old_logs(keep_days: int = 7):
    """Remove log directories older than `keep_days`. Called on startup."""
    if not os.path.exists(LOG_ROOT):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for name in os.listdir(LOG_ROOT):
        dpath = os.path.join(LOG_ROOT, name)
        if not os.path.isdir(dpath):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(dpath))
            if mtime < cutoff:
                import shutil
                shutil.rmtree(dpath, ignore_errors=True)
        except Exception:
            pass


def schedule_cleanup(interval_hours: int = 6, keep_days: int = 7):
    """Register a periodic cleanup timer (non-blocking). Call once at startup."""
    def _run():
        cleanup_old_logs(keep_days)
        threading.Timer(interval_hours * 3600, _run).start()
    # First cleanup in 60 seconds (give app time to start)
    threading.Timer(60, _run).start()
