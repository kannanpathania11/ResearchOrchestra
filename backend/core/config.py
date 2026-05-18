"""
Application configuration.
Single source of truth for environment variables and connection strings.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DB_URI: str = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable",
)

# ── LLM ───────────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

# ── Search ────────────────────────────────────────────────────────────────────
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Firebase ──────────────────────────────────────────────────────────────────
FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "researchorchestra")

# Comma-separated list of allowed CORS origins.
# Dev default: localhost only. Set this in prod to your real domain.
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# ── LangSmith observability ───────────────────────────────────────────────────
# Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY in your .env to enable.
# All LangGraph runs are automatically traced — no code changes needed.
LANGSMITH_TRACING: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGSMITH_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "ResearchOrchestra")
