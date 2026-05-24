"""
Snapshot — dump AgentState at key moments for debugging and error replay.

Snapshots are lightweight JSON files written to logs/{session_id}/snapshots/.
Each snapshot is timestamped and numbered sequentially.
"""
import json
import os
import time
from models.agent_state import AgentState


SNAPSHOT_DIR_NAME = "snapshots"


def snapshot_dir(session_id: str) -> str:
    """Return the snapshot directory for a session."""
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", session_id)
    return os.path.join(base, SNAPSHOT_DIR_NAME)


def take_snapshot(state: AgentState, label: str = "") -> str:
    """Dump AgentState to a timestamped JSON file. Returns the file path."""
    d = state.to_dict()
    d["_snapshot_label"] = label
    d["_snapshot_at"] = time.time()

    sdir = snapshot_dir(state.session_id)
    os.makedirs(sdir, exist_ok=True)

    # Sequential naming: 001, 002, ...
    existing = [f for f in os.listdir(sdir) if f.endswith(".json")]
    seq = len(existing) + 1
    filename = f"{seq:03d}_{label.replace(' ', '_') or 'snapshot'}.json"
    fpath = os.path.join(sdir, filename)

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, default=str)

    return fpath


def latest_snapshot(session_id: str) -> dict | None:
    """Load the most recent snapshot for a session (for error replay)."""
    sdir = snapshot_dir(session_id)
    if not os.path.exists(sdir):
        return None
    files = sorted([f for f in os.listdir(sdir) if f.endswith(".json")])
    if not files:
        return None
    fpath = os.path.join(sdir, files[-1])
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_snapshots(session_id: str) -> list[dict]:
    """List all snapshots for a session with metadata."""
    sdir = snapshot_dir(session_id)
    if not os.path.exists(sdir):
        return []
    results = []
    for fname in sorted(os.listdir(sdir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(sdir, fname)
        try:
            stat = os.stat(fpath)
            results.append({
                "file": fname,
                "size_kb": round(stat.st_size / 1024, 1),
                "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            })
        except Exception:
            pass
    return results
