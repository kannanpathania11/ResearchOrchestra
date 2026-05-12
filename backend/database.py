import os
import sys
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from supervisor_agent.src.agent import builder
from supervisor_agent.src.shared import DB_URI

class DatabaseManager:
    def __init__(self):
        self.pool = None
        self.graph = None
        self.store = None

    async def connect(self):
        """Initializes the PostgreSQL connection pool."""
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
            print("Database Connection Pool Opened.")
        return self.pool

    async def disconnect(self):
        """Closes the PostgreSQL connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            print("Database Connection Pool Closed.")

    async def get_researcher(self):
        """Compiles and returns the Supervisor Graph with persistence."""
        if not self.pool:
            await self.connect()
            
        if not self.graph:
            # Initialize Persistent Layer
            checkpointer = AsyncPostgresSaver(self.pool)
            await checkpointer.setup()

            self.store = AsyncPostgresStore(self.pool)
            await self.store.setup()

            # Compile Graph with Persistence
            self.graph = builder.compile(checkpointer=checkpointer, store=self.store)
            print("Supervisor Graph Compiled & Ready.")
            
        return self.graph, self.store

    def get_pool(self):
        return self.pool

# Global instance for shared use
db_manager = DatabaseManager()
