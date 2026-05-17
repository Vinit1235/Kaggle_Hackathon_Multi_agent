"""
main.py: FastAPI entry point for the AI Agency Platform.
Provides REST endpoints + WebSocket for real-time agent status updates.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from agents import CriticAgent, LeadAgent, SynthesizerAgent, WorkerAgent
from config_loader import config_loader
from memory import memx, semantic_cache
from orchestrator import WorkflowOrchestrator
from router import model_router
from schemas import (
    DomainType, HealthCheck, RunWorkflowRequest,
    RunWorkflowResponse, SessionInfo, TaskStatus,
)
from taskbox import TaskBox


# ── Globals ───────────────────────────────────────────────────────────
taskbox = TaskBox()
active_sessions: dict[str, SessionInfo] = {}
ws_connections: dict[str, list[WebSocket]] = {}


# ── Lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🚀 Starting AI Agency Platform...")

    # Initialize core services
    await taskbox.initialize()
    redis_ok = await memx.connect()
    proxy_ok = await model_router.check_proxy()   # PRIMARY backend
    ollama_ok = await model_router.check_ollama()  # FALLBACK backend
    await semantic_cache.initialize()
    
    from security import security_shield
    security_shield.initialize()

    # Load user preferences (CLAUDE.md Section 2: MUST load at session start)
    config_loader.load_user_preferences()
    config_loader.load_constitution()

    logger.info(f"  Proxy:  {'✅' if proxy_ok else '⚠️ not available'}")
    logger.info(f"  Ollama: {'✅' if ollama_ok else '⚠️ not available (fallback)'}")
    logger.info(f"  Redis:  {'✅' if redis_ok else '⚠️ fallback mode'}")
    logger.info(f"  Domains: {config_loader.list_available_domains()}")
    logger.info("✅ AI Agency Platform ready!")

    yield

    # Shutdown
    await taskbox.close()
    await memx.disconnect()
    logger.info("AI Agency Platform shut down.")


# ── App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Agency Platform",
    description="Gemma 4 Multi-Agent System — Hub-and-Spoke Architecture",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Observability (Phase 5) ───────────────────────────────────────────
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry FastAPI instrumentation enabled.")
except ImportError:
    logger.warning("OpenTelemetry not installed. Tracing disabled.")

# ── REST Endpoints ────────────────────────────────────────────────────

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """System health check."""
    return HealthCheck(
        proxy_connected=model_router._proxy_available or False,
        ollama_connected=model_router._ollama_available or False,
        redis_connected=memx.is_connected,
        db_initialized=taskbox._db is not None,
    )


@app.get("/api/domains")
async def list_domains():
    """List available domain configurations."""
    domains = config_loader.list_available_domains()
    result = []
    for d in domains:
        try:
            dt = DomainType(d)
            cfg = config_loader.load_domain_config(dt)
            result.append({
                "id": d,
                "description": cfg.description,
                "team_roles": [r.role for r in cfg.team_roles],
                "workflow": cfg.workflow,
            })
        except Exception:
            result.append({"id": d, "description": "Config load error", "team_roles": [], "workflow": []})
    return {"domains": result}


@app.post("/api/run", response_model=RunWorkflowResponse)
async def run_workflow(request: RunWorkflowRequest):
    """
    Start a new multi-agent workflow.
    1. Create session → 2. Lead decomposes → 3. Workers execute → 4. Critic reviews → 5. Synthesize.
    """
    session_id = uuid.uuid4().hex
    session = SessionInfo(
        session_id=session_id,
        domain=request.domain,
        user_goal=request.user_goal,
        user_preferences=request.user_preferences,
    )
    active_sessions[session_id] = session

    # Store session in memX
    await memx.update_state(
        f"session:{session_id}:info",
        {"domain": request.domain.value, "goal": request.user_goal, "status": "started"},
    )

    # Run workflow in background
    asyncio.create_task(_execute_workflow(session_id, request))

    return RunWorkflowResponse(
        session_id=session_id,
        domain=request.domain.value,
        status="started",
        message=f"Workflow started with session {session_id}",
    )


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Get the current state of a session."""
    if session_id not in active_sessions:
        raise HTTPException(404, "Session not found")

    tasks = await taskbox.get_tasks_by_session(session_id)
    summary = await taskbox.get_session_summary(session_id)
    state = await memx.get_session_state(session_id)

    return {
        "session": active_sessions[session_id].model_dump(),
        "tasks": tasks,
        "summary": summary,
        "agent_states": state,
    }


@app.get("/api/session/{session_id}/audit")
async def get_audit_log(session_id: str):
    """Get the full audit trail for a session."""
    logs = await taskbox.get_audit_log(session_id)
    return {"session_id": session_id, "audit_log": logs}


from context import context_compactor

@app.get("/api/session/{session_id}/resume")
async def resume_session(session_id: str):
    """Resume a previous session — load compacted history (Phase 3: Named Sessions)."""
    
    tasks = await taskbox.get_tasks_by_session(session_id)
    if not tasks:
        raise HTTPException(404, "Session not found in active sessions or database")
        
    state = await memx.get_session_state(session_id)
    
    # Run context compaction
    compacted_history = await context_compactor.check_and_compact(session_id, tasks)

    if session_id not in active_sessions:
        return {
            "session_id": session_id,
            "status": "resumed",
            "tasks": tasks,
            "agent_states": state,
            "compacted_history": compacted_history
        }

    return {
        "session": active_sessions[session_id].model_dump(),
        "tasks": tasks,
        "agent_states": state,
        "compacted_history": compacted_history
    }


# ── WebSocket ─────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Real-time WebSocket for agent status updates."""
    await websocket.accept()

    if session_id not in ws_connections:
        ws_connections[session_id] = []
    ws_connections[session_id].append(websocket)

    logger.info(f"WebSocket connected: session {session_id}")
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            logger.debug(f"WS received: {data}")
    except WebSocketDisconnect:
        ws_connections[session_id].remove(websocket)
        logger.info(f"WebSocket disconnected: session {session_id}")


async def broadcast_to_session(session_id: str, message: dict) -> None:
    """Send a message to all WebSocket clients for a session."""
    if session_id in ws_connections:
        dead = []
        for ws in ws_connections[session_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_connections[session_id].remove(ws)


# ── Workflow Engine (uses WorkflowOrchestrator) ───────────────────────

async def _execute_workflow(session_id: str, request: RunWorkflowRequest) -> None:
    """
    Main workflow execution using WorkflowOrchestrator.
    Handles: Lead → Workers (sequential/parallel) → Critic → Synthesizer.
    """
    user_prefs = request.user_preferences or config_loader.get_user_preferences()

    try:
        orchestrator = WorkflowOrchestrator(session_id, request.domain, taskbox)

        # Wire up WebSocket broadcasting as the event callback
        async def ws_event_handler(event: dict):
            await broadcast_to_session(session_id, event)

        orchestrator.on_event(ws_event_handler)

        result = await orchestrator.run(request.user_goal, user_prefs)

        # Update session status
        if session_id in active_sessions:
            active_sessions[session_id].status = result.get("status", "completed")

        await memx.update_state(f"session:{session_id}:info", {"status": result.get("status", "completed")})

    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        await broadcast_to_session(session_id, {
            "type": "error", "agent": "System", "message": str(e),
        })
        if session_id in active_sessions:
            active_sessions[session_id].status = "failed"


# ── Run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
