"""
StateManager — namespace-aware persistence for AgentState.

Uses SQLite key-value table with namespace prefix for future multi-user support.
Single-user mode: namespace="default".
Multi-user mode (future): namespace = user_id.
"""
import json
import os
import sqlite3
import threading
from models.agent_state import AgentState, UserPreferences


class StateManager:
    """CRUD for AgentState with namespace prefix isolation."""

    _TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS agent_state (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace   TEXT    NOT NULL DEFAULT 'default',
            key         TEXT    NOT NULL,
            value       TEXT    NOT NULL,
            updated_at  REAL    NOT NULL,
            UNIQUE(namespace, key)
        )
    """

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(self._TABLE_SQL)
        self.conn.commit()
        self._lock = threading.Lock()
        self._namespace = "default"  # will become user_id in multi-user

    # ── namespace control ────────────────────────────────────

    @property
    def namespace(self) -> str:
        return self._namespace

    @namespace.setter
    def namespace(self, value: str):
        self._namespace = value

    # ── key-value primitives ─────────────────────────────────

    def _get(self, key: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM agent_state WHERE namespace=? AND key=?",
                (self._namespace, key)
            ).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str):
        import time
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO agent_state (namespace, key, value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (self._namespace, key, value, time.time())
            )
            self.conn.commit()

    def _delete(self, key: str):
        with self._lock:
            self.conn.execute(
                "DELETE FROM agent_state WHERE namespace=? AND key=?",
                (self._namespace, key)
            )
            self.conn.commit()

    # ── AgentState CRUD ──────────────────────────────────────

    def save_state(self, state: AgentState):
        """Persist full AgentState to SQLite."""
        state.touch()
        self._set("agent_state", json.dumps(state.to_dict(), ensure_ascii=False, default=str))

    def load_state(self, session_id: str = "") -> AgentState:
        """Load AgentState. If session_id given, try to match; otherwise latest."""
        raw = self._get("agent_state")
        if raw:
            try:
                d = json.loads(raw)
                if not session_id or d.get("session_id") == session_id:
                    return AgentState.from_dict(d)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        # Return fresh state
        s = AgentState(namespace=self._namespace)
        if session_id:
            s.session_id = session_id
        return s

    def new_session(self, file_path: str = "", sheet_name: str = "") -> AgentState:
        """Create a fresh session, saving the previous one if it existed."""
        state = AgentState(namespace=self._namespace)
        state.file_path = file_path
        state.sheet_name = sheet_name
        self.save_state(state)
        return state

    # ── User Preferences ─────────────────────────────────────

    def save_preferences(self, prefs: UserPreferences):
        self._set("user_preferences", json.dumps(prefs.to_dict(), ensure_ascii=False))

    def load_preferences(self) -> UserPreferences:
        raw = self._get("user_preferences")
        if raw:
            try:
                return UserPreferences.from_dict(json.loads(raw))
            except (json.JSONDecodeError, KeyError):
                pass
        return UserPreferences()

    # ── cross-session lookup ─────────────────────────────────

    def find_previous_session(self, file_path: str) -> AgentState | None:
        """Check if this file was analysed before (by filename match)."""
        raw = self._get("agent_state")
        if not raw:
            return None
        try:
            d = json.loads(raw)
            prev_path = d.get("file_path", "")
            prev_sheet = d.get("sheet_name", "")
            if prev_path and os.path.basename(prev_path) == os.path.basename(file_path):
                return AgentState.from_dict(d)
        except Exception:
            pass
        return None
