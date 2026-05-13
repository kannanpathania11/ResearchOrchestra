import os
import sys
import json
import uuid
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from database import db_manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_manager.connect()
    yield
    await db_manager.disconnect()

app = FastAPI(title="ResearchOrchestra API", lifespan=lifespan)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"
    thread_id: str = None



async def stream_research(message: str, user_id: str, thread_id: str) -> AsyncGenerator[str, None]:
    graph, store = await db_manager.get_researcher()
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    
    initial_state = {
        "messages":        [HumanMessage(content=message)],
        "forced_mode":     "auto",
        "research_mode":   None,
        "subgraph_output": None,
        "summary":         "",
        "last_summary_idx": 0,
        "search_results":  [],
    }

    try:
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            kind = event["event"]
            
            # Handle custom events from our nodes (research_update, report_token)
            if kind == "on_custom_event":
                data = event["data"]
                if event["name"] == "research_update":
                    yield f"data: {json.dumps({'type': 'status', 'content': data.get('message', '')})}\n\n"
                elif event["name"] == "report_token":
                    yield f"data: {json.dumps({'type': 'token', 'content': data.get('content', '')})}\n\n"
            
            # Handle the final output from the supervisor/sub-agents
            elif kind == "on_chain_end":
                if event["name"] == "LangGraph": # Final graph completion
                    output = event.get("data", {}).get("output")
                    if output and "subgraph_output" in output:
                        yield f"data: {json.dumps({'type': 'final', 'content': output['subgraph_output']})}\n\n"
    except Exception as e:
        error_msg = str(e)
        if "rate_limit_exceeded" in error_msg.lower() or "429" in error_msg or "413" in error_msg:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Groq API Rate Limit Reached! The context size exceeded the limits of the free tier. Please try a more narrow topic or wait a minute before trying again.'})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'content': f'An internal error occurred: {error_msg}'})}\n\n"

    yield "data: [DONE]\n\n"

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    thread_id = request.thread_id or str(uuid.uuid4())
    return StreamingResponse(
        stream_research(request.message, request.user_id, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Prevent nginx/proxy buffering
        }
    )

@app.get("/chat/history")
async def get_chat_history(user_id: str = "anonymous"):
    """
    Returns a list of all threads for a user with a title derived from
    the first HumanMessage in the thread. Uses aget_state for correct
    LangChain message deserialization.
    """
    pool = await db_manager.connect()
    graph, _ = await db_manager.get_researcher()

    # Step 1: Fetch distinct thread_ids for this user from checkpoints table
    thread_ids = []
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT DISTINCT thread_id
                FROM checkpoints
                WHERE metadata->>'user_id' = %s
                ORDER BY thread_id DESC
            """, (user_id,))
            rows = await cur.fetchall()
            thread_ids = [row['thread_id'] for row in rows]

    # Step 2: For each thread, get the state and extract the title from first HumanMessage
    threads = []
    for tid in thread_ids:
        try:
            config = {"configurable": {"thread_id": tid, "user_id": user_id}}
            state = await graph.aget_state(config)
            if not state or not state.values:
                continue

            messages = state.values.get("messages", [])
            title = "New Chat"
            for msg in messages:
                if isinstance(msg, HumanMessage):
                    raw = msg.content
                    # content can be a str or a list of content blocks
                    text = raw if isinstance(raw, str) else (
                        " ".join(b.get("text", "") for b in raw if isinstance(b, dict))
                    )
                    title = text[:60] + "..." if len(text) > 60 else text
                    break

            threads.append({"thread_id": tid, "title": title})
        except Exception:
            # Skip threads that fail to load (corrupted checkpoints etc.)
            continue

    return {"threads": threads}

@app.get("/chat/history/{thread_id}")
async def get_thread_history(thread_id: str, user_id: str = "anonymous"):
    """
    Returns all messages for a given thread using LangGraph's aget_state.
    Handles HumanMessage, AIMessage, and content that may be a string or list.
    """
    graph, _ = await db_manager.get_researcher()

    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)

    if not state or not state.values:
        return {"messages": []}

    messages = state.values.get("messages", [])

    def extract_content(msg) -> str:
        """Safely extract string content from any LangChain message."""
        content = msg.content
        if isinstance(content, str):
            return content
        # Content is a list of content blocks (e.g. tool calls, text blocks)
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
    for msg in messages:
        content = extract_content(msg)
        if not content.strip():  # skip empty messages (tool artifacts etc.)
            continue
        if isinstance(msg, HumanMessage):
            formatted.append({"role": "user", "content": content})
        else:
            # AIMessage, SystemMessage, ToolMessage — all shown as assistant
            formatted.append({"role": "assistant", "content": content})

    return {"messages": formatted}

@app.delete("/chat/history/{thread_id}")
async def delete_thread(thread_id: str, user_id: str = "anonymous"):
    """Delete a thread and all its checkpoints. Only the owning user can delete."""
    pool = await db_manager.connect()
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Ownership check: verify this thread belongs to the requesting user
            await cur.execute("""
                SELECT thread_id FROM checkpoints
                WHERE thread_id = %s AND metadata->>'user_id' = %s
                LIMIT 1
            """, (thread_id, user_id))
            row = await cur.fetchone()
            
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Thread not found or you do not have permission to delete it."
                )
            
            # Delete from all checkpoint tables (order matters due to implicit dependencies)
            await cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoint_blobs  WHERE thread_id = %s", (thread_id,))
            await cur.execute("DELETE FROM checkpoints       WHERE thread_id = %s", (thread_id,))
    
    return {"status": "deleted", "thread_id": thread_id}

@app.get("/health")
async def health():
    return {"status": "ok", "project": "ResearchOrchestra"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
