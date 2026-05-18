"""
Database manager for ResearchOrchestra.
Manages the PostgreSQL connection pool and compiles the LangGraph supervisor
with AsyncPostgresSaver (checkpoints) and AsyncPostgresStore (long-term memory).
"""

from __future__ import annotations

import os
import sys

from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

# Ensure backend root is importable
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from core.config import DB_URI
from agents.graph import supervisor_builder


class DatabaseManager:
    """
    Singleton-style manager for the PostgreSQL pool and compiled LangGraph.

    Lifecycle
    ---------
    connect()        — open the pool (called on FastAPI startup)
    get_researcher() — compile and return the graph with persistence attached
    disconnect()     — close the pool (called on FastAPI shutdown)
    """

    def __init__(self) -> None:
        self.pool = None
        self.graph = None
        self.store = None

    async def connect(self):
        """Open the async connection pool if not already open."""
        if not self.pool:
            self.pool = AsyncConnectionPool(
                conninfo=DB_URI,
                open=False,
                max_size=20,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            await self.pool.open()
        return self.pool

    async def disconnect(self) -> None:
        """Close the connection pool gracefully."""
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def ensure_thread_titles_table(self) -> None:
        """Create the thread_titles table if it doesn't exist."""
        if not self.pool:
            await self.connect()
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS thread_titles (
                        user_id    TEXT        NOT NULL,
                        thread_id  TEXT        NOT NULL,
                        title      TEXT        NOT NULL DEFAULT 'New Chat',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, thread_id)
                    )
                """)
                await cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_thread_titles_user_id
                        ON thread_titles (user_id, created_at DESC)
                """)

    async def upsert_thread_title(self, user_id: str, thread_id: str, title: str) -> None:
        """Insert a thread title on first message; ignore subsequent calls."""
        if not self.pool:
            await self.connect()
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO thread_titles (user_id, thread_id, title)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, thread_id) DO NOTHING
                    """,
                    (user_id, thread_id, title),
                )

    async def get_thread_titles(self, user_id: str) -> list[dict]:
        """Return all threads for a user, newest first — single fast query."""
        if not self.pool:
            await self.connect()
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT thread_id, title
                    FROM thread_titles
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
                rows = await cur.fetchall()
        return [{"thread_id": r["thread_id"], "title": r["title"]} for r in rows]

    async def get_researcher(self):
        """
        Compile and return the supervisor graph with PostgreSQL persistence.

        The graph is compiled once and cached. Subsequent calls return the
        cached instance. Returns (graph, store).
        """
        if not self.pool:
            await self.connect()

        if not self.graph:
            checkpointer = AsyncPostgresSaver(self.pool)
            await checkpointer.setup()

            self.store = AsyncPostgresStore(self.pool)
            await self.store.setup()

            self.graph = supervisor_builder.compile(checkpointer=checkpointer, store=self.store)

        return self.graph, self.store

    def get_pool(self):
        return self.pool


# Global singleton — imported by server.py
db_manager = DatabaseManager()
