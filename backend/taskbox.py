"""
taskbox.py: SQLite WAL-mode Taskbox — the durable message queue for inter-agent communication.

Tables:
  - tasks:     Main task records (goal, status, input/output)
  - inboxes:   Per-agent message inbox for task routing
  - audit_log: Immutable log of all agent actions for observability

All writes go through WAL mode for concurrent read/write safety.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiosqlite
from loguru import logger

from schemas import AuditLogEntry, InboxMessage, TaskRecord, TaskStatus


# ── Default DB path ───────────────────────────────────────────────────
DEFAULT_DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/taskbox.db")


class TaskBox:
    """
    Async SQLite Taskbox manager.
    Handles all CRUD operations for tasks, inboxes, and audit logs.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create the database, enable WAL, and set up tables."""
        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Enable WAL mode for concurrent reads during writes
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA busy_timeout=5000;")

        # Create tables
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id         TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                domain          TEXT NOT NULL,
                agent_role      TEXT NOT NULL,
                goal            TEXT NOT NULL,
                input_data      TEXT DEFAULT '{}',
                output_data     TEXT DEFAULT '{}',
                status          TEXT DEFAULT 'pending',
                parent_task_id  TEXT,
                priority        INTEGER DEFAULT 0,
                error_message   TEXT,
                retry_count     INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inboxes (
                message_id      TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                target_agent    TEXT NOT NULL,
                source_agent    TEXT NOT NULL,
                task_id         TEXT NOT NULL,
                content         TEXT DEFAULT '{}',
                created_at      TEXT NOT NULL,
                read            INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                log_id          TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                agent_role      TEXT NOT NULL,
                action          TEXT NOT NULL,
                details         TEXT DEFAULT '{}',
                status          TEXT DEFAULT 'completed',
                error_message   TEXT,
                token_count     INTEGER,
                latency_ms      REAL,
                timestamp       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_role);
            CREATE INDEX IF NOT EXISTS idx_inboxes_target ON inboxes(target_agent, read);
            CREATE INDEX IF NOT EXISTS idx_inboxes_session ON inboxes(session_id);
            CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
        """)
        await self._db.commit()
        logger.info(f"TaskBox initialized at {self.db_path} (WAL mode)")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("TaskBox connection closed")

    # ── Task Operations ───────────────────────────────────────────────

    async def write_task(self, task: TaskRecord) -> TaskRecord:
        """Insert a new task into the Taskbox."""
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO tasks (task_id, session_id, domain, agent_role, goal,
                               input_data, output_data, status, parent_task_id,
                               priority, error_message, retry_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id, task.session_id, task.domain, task.agent_role,
                task.goal, json.dumps(task.input_data), json.dumps(task.output_data),
                task.status.value, task.parent_task_id, task.priority,
                task.error_message, task.retry_count, now, now
            ),
        )
        await self._db.commit()
        logger.debug(f"Task written: {task.task_id} → {task.agent_role} ({task.status})")
        return task

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update a task's status and optionally its output or error."""
        now = datetime.utcnow().isoformat()
        fields = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status.value, now]

        if output_data is not None:
            fields.append("output_data = ?")
            values.append(json.dumps(output_data))

        if error_message is not None:
            fields.append("error_message = ?")
            values.append(error_message)

        values.append(task_id)
        query = f"UPDATE tasks SET {', '.join(fields)} WHERE task_id = ?"
        await self._db.execute(query, values)
        await self._db.commit()
        logger.debug(f"Task {task_id} → {status.value}")

    async def increment_retry(self, task_id: str) -> int:
        """Increment retry count and return the new value."""
        await self._db.execute(
            "UPDATE tasks SET retry_count = retry_count + 1, updated_at = ? WHERE task_id = ?",
            (datetime.utcnow().isoformat(), task_id),
        )
        await self._db.commit()
        cursor = await self._db.execute(
            "SELECT retry_count FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return row["retry_count"] if row else 0

    async def get_task(self, task_id: str) -> Optional[dict]:
        """Retrieve a single task by ID."""
        cursor = await self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            result["input_data"] = json.loads(result["input_data"])
            result["output_data"] = json.loads(result["output_data"])
            return result
        return None

    async def get_tasks_by_session(self, session_id: str) -> list[dict]:
        """Get all tasks for a session, ordered by creation time."""
        cursor = await self._db.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["input_data"] = json.loads(r["input_data"])
            r["output_data"] = json.loads(r["output_data"])
            results.append(r)
        return results

    async def get_pending_tasks(self, session_id: str, agent_role: str) -> list[dict]:
        """Get pending tasks for a specific agent in a session."""
        cursor = await self._db.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ? AND agent_role = ? AND status = 'pending'
            ORDER BY priority DESC, created_at ASC
            """,
            (session_id, agent_role),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["input_data"] = json.loads(r["input_data"])
            r["output_data"] = json.loads(r["output_data"])
            results.append(r)
        return results

    # ── Inbox Operations ──────────────────────────────────────────────

    async def send_to_inbox(self, message: InboxMessage) -> None:
        """Write a message to an agent's inbox."""
        await self._db.execute(
            """
            INSERT INTO inboxes (message_id, session_id, target_agent, source_agent,
                                 task_id, content, created_at, read)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                message.message_id, message.session_id, message.target_agent,
                message.source_agent, message.task_id,
                json.dumps(message.content), message.created_at.isoformat()
            ),
        )
        await self._db.commit()
        logger.debug(f"Inbox message: {message.source_agent} → {message.target_agent}")

    async def poll_inbox(self, session_id: str, agent_role: str) -> list[dict]:
        """Poll unread messages from an agent's inbox."""
        cursor = await self._db.execute(
            """
            SELECT * FROM inboxes
            WHERE session_id = ? AND target_agent = ? AND read = 0
            ORDER BY created_at ASC
            """,
            (session_id, agent_role),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["content"] = json.loads(r["content"])
            results.append(r)

        # Mark as read
        if results:
            ids = [r["message_id"] for r in results]
            placeholders = ",".join(["?"] * len(ids))
            await self._db.execute(
                f"UPDATE inboxes SET read = 1 WHERE message_id IN ({placeholders})", ids
            )
            await self._db.commit()

        return results

    # ── Audit Log ─────────────────────────────────────────────────────

    async def log_action(self, entry: AuditLogEntry) -> None:
        """Write an entry to the immutable audit log."""
        await self._db.execute(
            """
            INSERT INTO audit_log (log_id, session_id, agent_role, action, details,
                                   status, error_message, token_count, latency_ms, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.log_id, entry.session_id, entry.agent_role, entry.action,
                json.dumps(entry.details), entry.status.value, entry.error_message,
                entry.token_count, entry.latency_ms, entry.timestamp.isoformat()
            ),
        )
        await self._db.commit()

    async def get_audit_log(self, session_id: str) -> list[dict]:
        """Retrieve the full audit log for a session."""
        cursor = await self._db.execute(
            "SELECT * FROM audit_log WHERE session_id = ? ORDER BY timestamp ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["details"] = json.loads(r["details"])
            results.append(r)
        return results

    # ── Utilities ─────────────────────────────────────────────────────

    async def get_session_summary(self, session_id: str) -> dict:
        """Get a summary of task statuses for a session."""
        cursor = await self._db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM tasks WHERE session_id = ?
            GROUP BY status
            """,
            (session_id,),
        )
        rows = await cursor.fetchall()
        return {row["status"]: row["count"] for row in rows}

    async def cleanup_session(self, session_id: str) -> None:
        """Remove all data for a completed session (optional cleanup)."""
        for table in ("tasks", "inboxes", "audit_log"):
            await self._db.execute(
                f"DELETE FROM {table} WHERE session_id = ?", (session_id,)
            )
        await self._db.commit()
        logger.info(f"Session {session_id} cleaned up")
