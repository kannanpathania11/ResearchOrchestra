import logging
import os
import sys
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from core.config import LOG_LEVEL, ALLOWED_ORIGINS
from core.db import db_manager

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ResearchOrchestra starting up — log level: %s", LOG_LEVEL)
    await db_manager.connect()
    await db_manager.ensure_thread_titles_table()
    yield
    await db_manager.disconnect()
    logger.info("ResearchOrchestra shut down.")


app = FastAPI(title="ResearchOrchestra API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


# ── Request model ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"
    thread_id: str | None = None
    research_pipeline_mode: bool = False
    research_mode: str = "academic_help"  # "interview_intel" | "job_scenario" | "academic_help"


# ── Core streaming helper ─────────────────────────────────────────────────────

async def _stream_graph(
    graph,
    input_: dict | Command,
    config: dict,
) -> AsyncGenerator[str, None]:
    try:
        async for event in graph.astream_events(input_, config=config, version="v2"):
            kind = event["event"]
            if kind == "on_custom_event":
                data = event["data"]
                if event["name"] == "research_update":
                    yield f"data: {json.dumps({'type': 'status', 'content': data.get('message', '')})}\n\n"
                elif event["name"] == "report_token":
                    yield f"data: {json.dumps({'type': 'token', 'content': data.get('content', '')})}\n\n"
            elif kind == "on_chain_end" and event["name"] == "LangGraph":
                output = event.get("data", {}).get("output")
                if output and "subgraph_output" in output:
                    yield f"data: {json.dumps({'type': 'final', 'content': output['subgraph_output']})}\n\n"

    except Exception as e:
        error_msg = str(e)
        if "rate_limit_exceeded" in error_msg.lower() or "429" in error_msg or "413" in error_msg:
            content = (
                "Groq API Rate Limit Reached! The context size exceeded the limits "
                "of the free tier. Please try a more narrow topic or wait a minute."
            )
        else:
            content = f"An internal error occurred: {error_msg}"
        yield f"data: {json.dumps({'type': 'error', 'content': content})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Check for interrupt (clarification needed)
    try:
        snapshot = await graph.aget_state(config)
        if snapshot and snapshot.tasks:
            for task in snapshot.tasks:
                interrupts = getattr(task, "interrupts", ())
                if interrupts:
                    interrupt_value = interrupts[0].value
                    questions = interrupt_value.get("questions", [])
                    message = interrupt_value.get(
                        "message",
                        "I need a bit more information before generating the report.",
                    )
                    yield f"data: {json.dumps({'type': 'interrupt', 'content': message, 'questions': questions})}\n\n"
                    break
    except Exception as exc:
        logger.warning("Could not check interrupt state: %s", exc)

    yield "data: [DONE]\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/chat")
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, body: ChatRequest):
    user_id = body.user_id or "anonymous"
    thread_id = body.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

    graph, _ = await db_manager.get_researcher()

    # Persist thread title (first message wins)
    title = body.message[:60] + ("..." if len(body.message) > 60 else "")
    await db_manager.upsert_thread_title(user_id, thread_id, title)

    # Detect whether this thread is currently interrupted (waiting for clarification)
    try:
        snapshot = await graph.aget_state(config)
        is_interrupted = bool(
            snapshot
            and snapshot.tasks
            and any(getattr(t, "interrupts", ()) for t in snapshot.tasks)
        )
    except Exception:
        is_interrupted = False

    if is_interrupted:
        graph_input: dict | Command = Command(resume=body.message)
    else:
        graph_input = {
            "messages":               [HumanMessage(content=body.message)],
            "forced_mode":            "auto",
            "research_mode":          body.research_mode if body.research_pipeline_mode else None,
            "research_pipeline_mode": body.research_pipeline_mode,
            "subgraph_output":        None,
            "summary":                "",
            "last_summary_idx":       0,
            "search_results":         [],
        }

    return StreamingResponse(
        _stream_graph(graph, graph_input, config),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/chat/history")
@limiter.limit("60/minute")
async def get_chat_history(request: Request, user_id: str = "anonymous"):
    threads = await db_manager.get_thread_titles(user_id)
    return {"threads": threads}


@app.get("/chat/history/{thread_id}")
@limiter.limit("60/minute")
async def get_thread_history(request: Request, thread_id: str, user_id: str = "anonymous"):
    graph, _ = await db_manager.get_researcher()
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)

    if not state or not state.values:
        return {"messages": []}

    def extract_content(msg) -> str:
        content = msg.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and "text" in block:
                    parts.append(block["text"])
            return "\n".join(parts)
        return str(content)

    formatted = []
    for msg in state.values.get("messages", []):
        content = extract_content(msg)
        if not content.strip():
            continue
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        formatted.append({"role": role, "content": content})

    return {"messages": formatted}


@app.delete("/chat/history/{thread_id}")
@limiter.limit("30/minute")
async def delete_thread(request: Request, thread_id: str, user_id: str = "anonymous"):
    pool = await db_manager.connect()

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT thread_id FROM checkpoints WHERE thread_id = %s AND metadata->>'user_id' = %s LIMIT 1",
                (thread_id, user_id),
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Thread not found.")

            await cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoint_blobs  WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoints       WHERE thread_id = %s", (thread_id,))
            await cur.execute(
                "DELETE FROM thread_titles WHERE thread_id = %s AND user_id = %s",
                (thread_id, user_id),
            )

    return {"status": "deleted", "thread_id": thread_id}


@app.get("/health")
async def health():
    return {"status": "ok", "project": "ResearchOrchestra"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
