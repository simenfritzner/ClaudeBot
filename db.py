"""
Thesis Bot — Database
SQLite for task state, session memory, long-term memory, and cost tracking.
"""
import aiosqlite
import json
import os
from datetime import datetime, timezone

from config import DB_PATH


async def init_db():
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'queued',
                description TEXT NOT NULL,
                model       TEXT,
                step_count  INTEGER DEFAULT 0,
                max_steps   INTEGER DEFAULT 10,
                token_cost  REAL DEFAULT 0.0,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                result      TEXT,
                error       TEXT,
                discord_message_id TEXT,
                discord_channel_id TEXT
            );

            CREATE TABLE IF NOT EXISTS memory_session (
                id          TEXT PRIMARY KEY,
                task_id     TEXT NOT NULL,
                summary     TEXT NOT NULL,
                tags        TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_long_term (
                id          TEXT PRIMARY KEY,
                session_date TEXT NOT NULL,
                summary     TEXT NOT NULL,
                tags        TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cost_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                task_id     TEXT,
                model       TEXT NOT NULL,
                input_tokens  INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS heartbeats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                tasks_queued    INTEGER,
                tasks_active    INTEGER,
                budget_used_today REAL
            );
        """)
        await db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_task_id() -> str:
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    return f"t_{date_part}_{time_part}"


# === Task Operations ===

async def create_task(description: str, max_steps: int = 10) -> dict:
    """Create a new task and return it."""
    task = {
        "id": _generate_task_id(),
        "created_at": _now(),
        "updated_at": _now(),
        "status": "queued",
        "description": description,
        "model": None,
        "step_count": 0,
        "max_steps": max_steps,
        "token_cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "result": None,
        "error": None,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO tasks (id, created_at, updated_at, status, description, max_steps)
               VALUES (:id, :created_at, :updated_at, :status, :description, :max_steps)""",
            task,
        )
        await db.commit()
    return task


async def update_task(task_id: str, **kwargs):
    """Update task fields."""
    kwargs["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = :{k}" for k in kwargs)
    kwargs["task_id"] = task_id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = :task_id",
            kwargs,
        )
        await db.commit()


async def get_task(task_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_active_tasks() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE status IN ('queued', 'in_progress', 'classifying') ORDER BY created_at"
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_stale_tasks() -> list[dict]:
    """Find tasks stuck in 'in_progress' (for crash recovery)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE status = 'in_progress'"
        )
        return [dict(row) for row in await cursor.fetchall()]


# === Cost Tracking ===

async def log_cost(task_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO cost_log (timestamp, task_id, model, input_tokens, output_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now(), task_id, model, input_tokens, output_tokens, cost_usd),
        )
        # Also update the task's running total
        await db.execute(
            """UPDATE tasks SET
                token_cost = token_cost + ?,
                input_tokens = input_tokens + ?,
                output_tokens = output_tokens + ?
               WHERE id = ?""",
            (cost_usd, input_tokens, output_tokens, task_id),
        )
        await db.commit()


async def get_daily_cost() -> float:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log WHERE timestamp LIKE ?",
            (f"{today}%",),
        )
        row = await cursor.fetchone()
        return row[0]


async def get_monthly_cost() -> float:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log WHERE timestamp LIKE ?",
            (f"{month}%",),
        )
        row = await cursor.fetchone()
        return row[0]


# === Memory Operations ===

async def save_session_memory(task_id: str, summary: dict, tags: list[str]):
    mem_id = f"sm_{task_id}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO memory_session (id, task_id, summary, tags, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (mem_id, task_id, json.dumps(summary), ",".join(tags), _now()),
        )
        await db.commit()


async def get_recent_session_memories(limit: int = 2) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM memory_session ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def search_memories(keywords: list[str], limit: int = 3) -> list[dict]:
    """Search session and long-term memories by tags."""
    conditions = " OR ".join(["tags LIKE ?" for _ in keywords])
    params = [f"%{kw}%" for kw in keywords]

    results = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for table in ("memory_session", "memory_long_term"):
            cursor = await db.execute(
                f"SELECT * FROM {table} WHERE {conditions} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            )
            results.extend([dict(row) for row in await cursor.fetchall()])
    return results[:limit]


# === Heartbeat ===

async def log_heartbeat(tasks_queued: int, tasks_active: int, budget_today: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO heartbeats (timestamp, tasks_queued, tasks_active, budget_used_today)
               VALUES (?, ?, ?, ?)""",
            (_now(), tasks_queued, tasks_active, budget_today),
        )
        await db.commit()
