"""
schemas.py: Pydantic models for the AI Agency Platform.
Defines all data structures used across the system.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REVISION_REQUESTED = "revision_requested"


class AgentRole(str, Enum):
    LEAD = "Lead"
    WORKER = "Worker"
    CRITIC = "Critic"
    SYNTHESIZER = "Synthesizer"


class ModelTier(str, Enum):
    LOCAL_LIGHT = "local_light"       # gemma4:e2b / e4b
    LOCAL_HEAVY = "local_heavy"       # gemma4:26b-moe
    CLOUD_DENSE = "cloud_dense"       # gemma4:31b-dense via Vertex AI


class DomainType(str, Enum):
    YOUTUBE_CREATOR = "youtube_creator"
    LEGAL_SQUAD = "legal_squad"


# ── Task & Inbox Models ───────────────────────────────────────────────

class TaskCreate(BaseModel):
    """Schema for creating a new task in the Taskbox."""
    session_id: str
    domain: DomainType
    agent_role: str
    goal: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    parent_task_id: Optional[str] = None
    priority: int = Field(default=0, ge=0, le=10)


class TaskRecord(BaseModel):
    """Full task record as stored in SQLite."""
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    domain: str
    agent_role: str
    goal: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    parent_task_id: Optional[str] = None
    priority: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int = 0


class InboxMessage(BaseModel):
    """Message in an agent's inbox."""
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    target_agent: str
    source_agent: str
    task_id: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    read: bool = False


class AuditLogEntry(BaseModel):
    """Entry in the audit log for observability."""
    log_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    agent_role: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.COMPLETED
    error_message: Optional[str] = None
    token_count: Optional[int] = None
    latency_ms: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Domain Config Models ──────────────────────────────────────────────

class TeamMember(BaseModel):
    """A single agent role within a domain team."""
    role: str
    model: str
    goal: str


class DomainConfig(BaseModel):
    """Configuration for a single domain (e.g., YouTube Creator)."""
    description: str
    team_roles: list[TeamMember]
    workflow: list[str]


# ── Session & User Models ─────────────────────────────────────────────

class SessionCreate(BaseModel):
    """Request to create a new user session."""
    domain: DomainType
    user_goal: str
    user_preferences: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    """Active session metadata."""
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    domain: DomainType
    user_goal: str
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    active_agents: list[str] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Request / Response ────────────────────────────────────────────

class RunWorkflowRequest(BaseModel):
    """Request body for /api/run endpoint."""
    domain: DomainType
    user_goal: str
    user_preferences: dict[str, Any] = Field(default_factory=dict)


class RunWorkflowResponse(BaseModel):
    """Response for /api/run endpoint."""
    session_id: str
    domain: str
    status: str
    message: str


class AgentStatusUpdate(BaseModel):
    """WebSocket message for real-time agent status updates."""
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    agent_role: str
    status: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HealthCheck(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"
    gemini_connected: bool = False
    ollama_connected: bool = False
    redis_connected: bool = False
    db_initialized: bool = False
