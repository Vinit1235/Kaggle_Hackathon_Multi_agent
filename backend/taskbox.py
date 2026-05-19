"""
taskbox.py: Supabase PostgreSQL Taskbox — the durable message queue for inter-agent communication.

Tables:
  - tasks:     Main task records (goal, status, input/output)
  - inboxes:   Per-agent message inbox for task routing
  - audit_log: Immutable log of all agent actions for observability

Supports both Supabase (cloud) and SQLite (local dev fallback).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from schemas import AuditLogEntry, InboxMessage, TaskRecord, TaskStatus


# ── Configuration ─────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/taskbox.db")


class TaskBox:
    """
    Async Taskbox manager with Supabase PostgreSQL (cloud) or SQLite (local) support.
    Automatically selects backend based on DATABASE_URL availability.
    """

    def __init__(self, db_path: str = SQLITE_DB_PATH):
        self.db_path = db_path
        self._db = None
        self._pool = None
        self._use_postgres = bool(DATABASE_URL)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create the database connection and set up tables."""
        if self._use_postgres:
            await self._init_postgres()
        else:
            await self._init_sqlite()

    async def _init_postgres(self) -> None:
        """Initialize Supabase PostgreSQL connection."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                ssl="require",
            )

            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id         TEXT PRIMARY KEY,
                        session_id      TEXT NOT NULL,
                        domain          TEXT NOT NULL,
                        agent_role      TEXT NOT NULL,
                        goal            TEXT NOT NULL,
                        input_data      JSONB DEFAULT '{}',
                        output_data     JSONB DEFAULT '{}',
                        status          TEXT DEFAULT 'pending',
                        parent_task_id  TEXT,
                        priority        INTEGER DEFAULT 0,
                        error_message   TEXT,
                        retry_count     INTEGER DEFAULT 0,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS inboxes (
                        message_id      TEXT PRIMARY KEY,
                        session_id      TEXT NOT NULL,
                        target_agent    TEXT NOT NULL,
                        source_agent    TEXT NOT NULL,
                        task_id         TEXT NOT NULL,
                        content         JSONB DEFAULT '{}',
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        read            BOOLEAN DEFAULT FALSE
                    );

                    CREATE TABLE IF NOT EXISTS audit_log (
                        log_id          TEXT PRIMARY KEY,
                        session_id      TEXT NOT NULL,
                        agent_role      TEXT NOT NULL,
                        action          TEXT NOT NULL,
                        details         JSONB DEFAULT '{}',
                        status          TEXT DEFAULT 'completed',
                        error_message   TEXT,
                        token_count     INTEGER,
                        latency_ms      DOUBLE PRECISION,
                        timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
                    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                    CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_role);
                    CREATE INDEX IF NOT EXISTS idx_inboxes_target ON inboxes(target_agent, read);
                    CREATE INDEX IF NOT EXISTS idx_inboxes_session ON inboxes(session_id);
                    CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
                """)

            logger.info(f"TaskBox initialized with Supabase PostgreSQL")

        except Exception as e:
            logger.error(f"PostgreSQL init failed: {e}. Falling back to SQLite.")
            self._use_postgres = False
            await self._init_sqlite()

    async def _init_sqlite(self) -> None:
        """Initialize local SQLite (fallback for dev)."""
        import aiosqlite

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA busy_timeout=5000;")

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
        logger.info(f"TaskBox initialized at {self.db_path} (SQLite WAL mode)")

    async def close(self) -> None:
        """Close the database connection."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("TaskBox PostgreSQL pool closed")
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("TaskBox SQLite connection closed")

    # ── Task Operations ───────────────────────────────────────────────

    async def write_task(self, task: TaskRecord) -> TaskRecord:
        """Insert a new task into the Taskbox."""
        now = datetime.utcnow().isoformat()

        if self._use_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO tasks (task_id, session_id, domain, agent_role, goal,
                                       input_data, output_data, status, parent_task_id,
                                       priority, error_message, retry_count, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    """,
                    task.task_id, task.session_id, task.domain, task.agent_role,
                    task.goal, json.dumps(task.input_data), json.dumps(task.output_data),
                    task.status.value, task.parent_task_id, task.priority,
                    task.error_message, task.retry_count, now, now
                )
        else:
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

        if self._use_postgres:
            async with self._pool.acquire() as conn:
                if output_data is not None and error_message is not None:
                    await conn.execute(
                        "UPDATE tasks SET status=$1, updated_at=$2, output_data=$3, error_message=$4 WHERE task_id=$5",
                        status.value, now, json.dumps(output_data), error_message, task_id
                    )
                elif output_data is not None:
                    await conn.execute(
                        "UPDATE tasks SET status=$1, updated_at=$2, output_data=$3 WHERE task_id=$4",
                        status.value, now, json.dumps(output_data), task_id
                    )
                elif error_message is not None:
                    await conn.execute(
                        "UPDATE tasks SET status=$1, updated_at=$2, error_message=$3 WHERE task_id=$4",
                        status.value, now, error_message, task_id
                    )
                else:
                    await conn.execute(
                        "UPDATE tasks SET status=$1, updated_at=$2 WHERE task_id=$3",
                        status.value, now, task_id
                    )
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE tasks SET retry_count = retry_count + 1, updated_at = $1 WHERE task_id = $2",
                    datetime.utcnow().isoformat(), task_id
                )
                row = await conn.fetchrow("SELECT retry_count FROM tasks WHERE task_id = $1", task_id)
                return row["retry_count"] if row else 0
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
                if row:
                    result = dict(row)
                    # PostgreSQL JSONB returns dicts directly
                    if isinstance(result["input_data"], str):
                        result["input_data"] = json.loads(result["input_data"])
                    if isinstance(result["output_data"], str):
                        result["output_data"] = json.loads(result["output_data"])
                    return result
                return None
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM tasks WHERE session_id = $1 ORDER BY created_at ASC",
                    session_id
                )
                results = []
                for row in rows:
                    r = dict(row)
                    if isinstance(r["input_data"], str):
                        r["input_data"] = json.loads(r["input_data"])
                    if isinstance(r["output_data"], str):
                        r["output_data"] = json.loads(r["output_data"])
                    results.append(r)
                return results
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE session_id = $1 AND agent_role = $2 AND status = 'pending'
                    ORDER BY priority DESC, created_at ASC
                    """,
                    session_id, agent_role
                )
                results = []
                for row in rows:
                    r = dict(row)
                    if isinstance(r["input_data"], str):
                        r["input_data"] = json.loads(r["input_data"])
                    if isinstance(r["output_data"], str):
                        r["output_data"] = json.loads(r["output_data"])
                    results.append(r)
                return results
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO inboxes (message_id, session_id, target_agent, source_agent,
                                         task_id, content, created_at, read)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE)
                    """,
                    message.message_id, message.session_id, message.target_agent,
                    message.source_agent, message.task_id,
                    json.dumps(message.content), message.created_at.isoformat()
                )
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM inboxes
                    WHERE session_id = $1 AND target_agent = $2 AND read = FALSE
                    ORDER BY created_at ASC
                    """,
                    session_id, agent_role
                )
                results = []
                for row in rows:
                    r = dict(row)
                    if isinstance(r["content"], str):
                        r["content"] = json.loads(r["content"])
                    results.append(r)

                if results:
                    ids = [r["message_id"] for r in results]
                    await conn.execute(
                        "UPDATE inboxes SET read = TRUE WHERE message_id = ANY($1::text[])",
                        ids
                    )
                return results
        else:
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
        """Write an entry to the immutable audit log with data compression."""
        # ── Phase 4: Log Compression ──
        # Strip details to essential fields and truncate large strings
        compressed_details = {}
        for k, v in entry.details.items():
            if isinstance(v, str) and len(v) > 200:
                compressed_details[k] = v[:200] + "... [TRUNCATED]"
            elif k not in ["raw_response", "full_prompt"]: # Drop massive redundant keys
                compressed_details[k] = v

        if self._use_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log (log_id, session_id, agent_role, action, details,
                                           status, error_message, token_count, latency_ms, timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    entry.log_id, entry.session_id, entry.agent_role, entry.action,
                    json.dumps(compressed_details), entry.status.value,
                    entry.error_message[:200] + "..." if entry.error_message and len(entry.error_message) > 200 else entry.error_message,
                    entry.token_count, entry.latency_ms, entry.timestamp.isoformat()
                )
        else:
            await self._db.execute(
                """
                INSERT INTO audit_log (log_id, session_id, agent_role, action, details,
                                       status, error_message, token_count, latency_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.log_id, entry.session_id, entry.agent_role, entry.action,
                    json.dumps(compressed_details), entry.status.value,
                    entry.error_message[:200] + "..." if entry.error_message and len(entry.error_message) > 200 else entry.error_message,
                    entry.token_count, entry.latency_ms, entry.timestamp.isoformat()
                ),
            )
            await self._db.commit()

    async def get_audit_log(self, session_id: str) -> list[dict]:
        """Retrieve the full audit log for a session."""
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM audit_log WHERE session_id = $1 ORDER BY timestamp ASC",
                    session_id
                )
                results = []
                for row in rows:
                    r = dict(row)
                    if isinstance(r["details"], str):
                        r["details"] = json.loads(r["details"])
                    results.append(r)
                return results
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT status, COUNT(*) as count
                    FROM tasks WHERE session_id = $1
                    GROUP BY status
                    """,
                    session_id
                )
                return {row["status"]: row["count"] for row in rows}
        else:
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
        if self._use_postgres:
            async with self._pool.acquire() as conn:
                for table in ("tasks", "inboxes", "audit_log"):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE session_id = $1", session_id
                    )
        else:
            for table in ("tasks", "inboxes", "audit_log"):
                await self._db.execute(
                    f"DELETE FROM {table} WHERE session_id = ?", (session_id,)
                )
            await self._db.commit()
        logger.info(f"Session {session_id} cleaned up")
