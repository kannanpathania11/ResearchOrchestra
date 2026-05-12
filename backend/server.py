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
    user_id: str = "student_user"
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
        media_type="text/event-stream"
    )

@app.get("/health")
async def health():
    return {"status": "ok", "project": "ResearchOrchestra"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
