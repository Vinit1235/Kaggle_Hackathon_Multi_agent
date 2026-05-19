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
from dotenv import load_dotenv

load_dotenv()

from agents import CriticAgent, LeadAgent, SynthesizerAgent, WorkerAgent
from config_loader import config_loader
from memory import memx, semantic_cache
from langgraph_workflow import LangGraphWorkflow
from router import model_router
from schemas import (
    DomainType, HealthCheck, RunWorkflowRequest, FollowUpRequest,
    RunWorkflowResponse, SessionInfo, TaskStatus,
    AuthLoginRequest, AuthRegisterRequest, AuthResponse, AuthUser,
)
from taskbox import TaskBox
from supabase_auth import create_user as supabase_create_user, login_user as supabase_login_user, SupabaseAuthError


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
    gemini_ok = await model_router.check_gemini()   # PRIMARY backend (Gemini API)
    ollama_ok = await model_router.check_ollama()    # FALLBACK backend (local)
    await semantic_cache.initialize()
    
    from security import security_shield
    security_shield.initialize()

    # Load user preferences (CLAUDE.md Section 2: MUST load at session start)
    config_loader.load_user_preferences()
    config_loader.load_constitution()

    logger.info(f"  Gemini: {'✅' if gemini_ok else '⚠️ not available (set GEMINI_API_KEY)'}")
    logger.info(f"  Ollama: {'✅' if ollama_ok else '⚠️ not available (local fallback)'}")
    logger.info(f"  Redis:  {'✅' if redis_ok else '⚠️ in-memory fallback'}")
    logger.info(f"  DB:     {'✅ Supabase' if taskbox._use_postgres else '✅ SQLite'}")
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
        gemini_connected=model_router._gemini_available or False,
        ollama_connected=model_router._ollama_available or False,
        redis_connected=memx.is_connected,
        db_initialized=taskbox._pool is not None or taskbox._db is not None,
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


@app.post("/api/auth/register", response_model=AuthResponse)
async def register_user(request: AuthRegisterRequest):
    """Register a new user using Supabase Auth (admin create + login)."""
    try:
        await supabase_create_user(request.email, request.password)
        session = await supabase_login_user(request.email, request.password)
    except SupabaseAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Auth register failed: {e}")
        raise HTTPException(status_code=500, detail="Auth registration failed")

    user = session.get("user") or {}
    return AuthResponse(
        user=AuthUser(id=user.get("id", ""), email=user.get("email")),
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token"),
        expires_in=session.get("expires_in"),
        token_type=session.get("token_type"),
    )


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_user(request: AuthLoginRequest):
    """Login an existing user using Supabase Auth."""
    try:
        session = await supabase_login_user(request.email, request.password)
    except SupabaseAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Auth login failed: {e}")
        raise HTTPException(status_code=500, detail="Auth login failed")

    user = session.get("user") or {}
    return AuthResponse(
        user=AuthUser(id=user.get("id", ""), email=user.get("email")),
        access_token=session.get("access_token", ""),
        refresh_token=session.get("refresh_token"),
        expires_in=session.get("expires_in"),
        token_type=session.get("token_type"),
    )


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


@app.post("/api/followup", response_model=RunWorkflowResponse)
async def run_followup(request: FollowUpRequest):
    """
    Handle a follow-up message for an existing session.
    Retrieves previous output and runs a new workflow session.
    """
    # 1. Fetch old session info from memX
    info = await memx.read_state(f"session:{request.session_id}:info")
    if not info or "domain" not in info:
        raise HTTPException(status_code=404, detail="Original session not found or invalid.")

    domain = info["domain"]
    
    # 2. Fetch final output from old session
    final_output = await memx.read_state(f"session:{request.session_id}:final_output")
    prev_context = json.dumps(final_output) if final_output else "No previous output found."

    # 3. Create a NEW session ID for the follow-up
    new_session_id = uuid.uuid4().hex
    
    # 4. Construct the new goal embedding the previous context
    new_goal = f"Previous Workflow Output:\n{prev_context}\n\nUser Follow-up Request:\n{request.message}"
    
    session = SessionInfo(
        session_id=new_session_id,
        domain=DomainType(domain),
        user_goal=new_goal,
        user_preferences=request.user_preferences,
    )
    active_sessions[new_session_id] = session

    await memx.update_state(
        f"session:{new_session_id}:info",
        {"domain": domain, "goal": new_goal, "status": "started"},
    )

    # 5. Create a RunWorkflowRequest for the new session
    run_req = RunWorkflowRequest(
        domain=DomainType(domain),
        user_goal=new_goal,
        user_preferences=request.user_preferences
    )

    asyncio.create_task(_execute_workflow(new_session_id, run_req))

    return RunWorkflowResponse(
        session_id=new_session_id,
        domain=domain,
        status="started",
        message=f"Follow-up workflow started with session {new_session_id}",
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
        orchestrator = LangGraphWorkflow(session_id, request.domain, taskbox)

        # Wire up WebSocket broadcasting as the event callback
        async def ws_event_handler(event: dict):
            await broadcast_to_session(session_id, event)

        orchestrator.on_event(ws_event_handler)

        result = await orchestrator.run(request.user_goal, user_prefs)

        if result.get("content"):
            await memx.update_state(
                f"session:{session_id}:final_output",
                {"content": result.get("content", ""), "status": result.get("status", "completed")},
            )

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
