"""In-memory + JSON-persisted store for sessions and parsed DocumentTrees.

The DocumentTree object holds large `source_text` and span metadata that
we don't want to serialize on every API call. So we keep it in-process,
keyed by session id, and persist only the Session JSON (which is small).
"""
from __future__ import annotations

import asyncio
import logging
import logging.handlers
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from paper_agent.ir import DocumentTree
from paper_agent.parsers import LaTeXParser, WordParser
from paper_agent.session import Session, SESSION_DIR


_LOGGER = logging.getLogger("paper_agent")
LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIR / "server.log"


class SessionStore:
    """Thread-safe in-memory store of Session + DocumentTree pairs.

    Sessions are persisted to disk on every mutation so a server restart
    can rehydrate them; the DocumentTree is re-parsed on demand from
    `Session.source_path`.
    """

    def __init__(self, dir: Optional[Path] = None) -> None:
        self.dir = Path(dir) if dir else SESSION_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._trees: dict[str, DocumentTree] = {}
        self._lock = threading.RLock()
        self._load_all()

    def _load_all(self) -> None:
        """Rehydrate persisted sessions from disk on startup."""
        for path in sorted(self.dir.glob("sess-*.json")):
            try:
                sess = Session.load(path.stem, self.dir)
                with self._lock:
                    self._sessions[sess.id] = sess
            except Exception as exc:
                _LOGGER.warning("Could not load session %s: %s", path.name, exc)

    # ----------------------------------------------------------- sessions

    def put(self, session: Session, tree: DocumentTree) -> None:
        with self._lock:
            self._sessions[session.id] = session
            self._trees[session.id] = tree
        session.save(self.dir)

    def get(self, sid: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(sid)

    def tree(self, sid: str) -> Optional[DocumentTree]:
        with self._lock:
            t = self._trees.get(sid)
            if t is not None:
                return t
        # Tree not cached — re-parse from source file on demand
        sess = self.get(sid)
        if sess is None or not Path(sess.source_path).exists():
            return None
        try:
            if sess.source_type == "latex":
                text = Path(sess.source_path).read_text(encoding="utf-8", errors="replace")
                tree = LaTeXParser().parse(text)
            else:
                tree = WordParser().parse_file(sess.source_path)
            with self._lock:
                self._trees[sid] = tree
            return tree
        except Exception as exc:
            _LOGGER.warning("Could not re-parse tree for %s: %s", sid, exc)
            return None

    def attach_tree(self, sid: str, tree: DocumentTree) -> None:
        with self._lock:
            self._trees[sid] = tree

    def save(self, sid: str) -> None:
        s = self.get(sid)
        if s is not None:
            s.save(self.dir)

    def list_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions.keys())


# ---------------------------------------------------------------------------
# Tiny in-memory log buffer (so the UI can show recent server activity).
# ---------------------------------------------------------------------------

class RingLogHandler(logging.Handler):
    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.buf: deque[str] = deque(maxlen=capacity)
        self.subscribers: set[asyncio.Queue] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        self.buf.append(line)
        # broadcast to all SSE subscribers (non-blocking)
        for q in list(self.subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def snapshot(self) -> list[str]:
        return list(self.buf)


def setup_logging() -> RingLogHandler:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    ring = RingLogHandler()
    ring.setFormatter(fmt)

    # Rotating file handler -- 5 MB per file, 5 files of history kept.
    file_h = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)

    logging.basicConfig(level=logging.INFO, handlers=[stream, file_h, ring], force=True)
    _LOGGER.info("paper_agent logging initialized -> %s", LOG_FILE)
    return ring


def read_log_history(limit: int = 1000, offset: int = 0) -> list[str]:
    """Read the persistent log file from oldest backups to current.

    Returns up to `limit` lines, optionally skipping `offset` from the end
    so the UI can paginate backwards through history.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    # backups (oldest first) ... .5 .4 .3 .2 .1, then current
    for i in range(5, 0, -1):
        p = LOG_FILE.with_suffix(f".log.{i}")
        if p.exists():
            files.append(p)
    if LOG_FILE.exists():
        files.append(LOG_FILE)

    lines: list[str] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    lines.append(line.rstrip("\n"))
        except OSError:
            continue
    if offset > 0:
        lines = lines[: max(0, len(lines) - offset)]
    if limit > 0:
        lines = lines[-limit:]
    return lines


# Module-level singletons used by the FastAPI app.
STORE = SessionStore()
LOG_HANDLER: Optional[RingLogHandler] = None


def get_log_handler() -> RingLogHandler:
    global LOG_HANDLER
    if LOG_HANDLER is None:
        LOG_HANDLER = setup_logging()
    return LOG_HANDLER
