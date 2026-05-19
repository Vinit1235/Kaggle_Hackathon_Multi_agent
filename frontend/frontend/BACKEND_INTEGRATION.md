# AI Agency Platform - Backend Integration Guide

## Overview

This document describes the API endpoints and WebSocket events needed to connect the React frontend to a FastAPI backend. The frontend is designed as a **simulation mode** that can work independently but is structured to integrate seamlessly with a real backend.

---

## 1. API Base Configuration

**Base URL:** `http://localhost:8000/api`

**WebSocket URL:** `ws://localhost:8000/ws/{session_id}`

**Authentication:** Bearer token in Authorization header (future enhancement)

---

## 2. REST API Endpoints

### 2.1 Health Check

```
GET /api/health
```

**Description:** Check system connectivity and service status.

**Response:**
```json
{
  "status": "healthy",
  "services": {
    "gemini": { "status": "connected", "latency_ms": 45 },
    "redis": { "status": "connected" },
    "database": { "status": "connected" }
  },
  "timestamp": "2026-05-19T01:20:00Z"
}
```

---

### 2.2 Get Available Domains

```
GET /api/domains
```

**Description:** Retrieve all available domain teams and their agent configurations.

**Response:**
```json
{
  "domains": [
    {
      "id": "youtube",
      "name": "YouTube Creator",
      "description": "Create engaging video content...",
      "icon": "video",
      "color": "#ff0000",
      "agents": [
        {
          "id": "idea-generator",
          "name": "Idea Generator",
          "role": "Creative strategist for content ideas",
          "color": "#ff6b6b",
          "capabilities": ["trending_analysis", "content_ideas", "hook_generation"]
        }
      ]
    }
  ]
}
```

---

### 2.3 Launch Agent Team

```
POST /api/run
```

**Description:** Initialize a new agent team session for a specific domain and goal.

**Request:**
```json
{
  "domain_id": "youtube",
  "goal": "Create a video about AI trends in 2025",
  "user_id": "user-123",
  "options": {
    "priority": "normal",
    "timeout_seconds": 300,
    "callback_url": null
  }
}
```

**Response:**
```json
{
  "session_id": "sess_abc123xyz",
  "domain_id": "youtube",
  "status": "initializing",
  "agents": [
    { "id": "agent-1", "name": "Idea Generator", "status": "spawning" },
    { "id": "agent-2", "name": "Script Writer", "status": "spawning" }
  ],
  "created_at": "2026-05-19T01:20:00Z"
}
```

---

### 2.4 Get Session Status

```
GET /api/session/{session_id}
```

**Description:** Get current status of a running session.

**Response:**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "running",
  "progress": 65,
  "current_phase": "processing",
  "agents": [
    {
      "id": "agent-1",
      "name": "Idea Generator",
      "status": "completed",
      "task": "Generated 5 content ideas",
      "progress": 100
    },
    {
      "id": "agent-2",
      "name": "Script Writer",
      "status": "working",
      "task": "Writing video script...",
      "progress": 60
    }
  ],
  "started_at": "2026-05-19T01:20:00Z",
  "estimated_completion": "2026-05-19T01:25:00Z"
}
```

---

### 2.5 Get Session Output

```
GET /api/session/{session_id}/output
```

**Description:** Retrieve the final output from a completed session.

**Response:**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "completed",
  "output": {
    "title": "YouTube Content Strategy",
    "summary": "Comprehensive strategy for AI trends video...",
    "sections": [
      {
        "title": "Video Ideas",
        "items": ["Idea 1", "Idea 2", "Idea 3"]
      }
    ],
    "metadata": {
      "execution_time_ms": 45000,
      "agents_used": 5,
      "tokens_consumed": 12000
    }
  },
  "completed_at": "2026-05-19T01:24:30Z"
}
```

---

### 2.6 Cancel Session

```
POST /api/session/{session_id}/cancel
```

**Description:** Cancel an ongoing session and terminate all agents.

**Response:**
```json
{
  "session_id": "sess_abc123xyz",
  "status": "cancelled",
  "agents_terminated": 5,
  "cancelled_at": "2026-05-19T01:22:00Z"
}
```

---

## 3. WebSocket Events

### 3.1 Connection

**URL:** `ws://localhost:8000/ws/{session_id}`

**Connection Flow:**
1. Client connects to WebSocket using session_id
2. Server sends initial state event
3. Bidirectional communication begins

---

### 3.2 Server-to-Client Events

#### Agent Spawned

```json
{
  "type": "agent_spawned",
  "timestamp": "2026-05-19T01:20:05Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "status": "idle",
    "color": "#ff6b6b"
  }
}
```

#### Agent Status Changed

```json
{
  "type": "agent_status",
  "timestamp": "2026-05-19T01:20:10Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "status": "working",
    "task": "Analyzing trending topics...",
    "progress": 35
  }
}
```

#### Agent Thinking

```json
{
  "type": "agent_thinking",
  "timestamp": "2026-05-19T01:20:15Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "thought": "Processing user query to identify key themes...",
    "phase": "analysis"
  }
}
```

#### Agent Action

```json
{
  "type": "agent_action",
  "timestamp": "2026-05-19T01:20:20Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "action": "search",
    "details": "Searching for AI trends 2025...",
    "duration_ms": 1500
  }
}
```

#### Agent Communication

```json
{
  "type": "agent_communication",
  "timestamp": "2026-05-19T01:20:25Z",
  "data": {
    "from_agent": "Idea Generator",
    "to_agent": "Script Writer",
    "message": "Found 5 trending topics. Passing to script writer for development.",
    "intent": "handoff"
  }
}
```

#### Agent Completed

```json
{
  "type": "agent_completed",
  "timestamp": "2026-05-19T01:20:30Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "status": "completed",
    "output": "Generated content ideas for AI trends 2025",
    "tokens_used": 850
  }
}
```

#### Agent Terminated

```json
{
  "type": "agent_terminated",
  "timestamp": "2026-05-19T01:24:00Z",
  "data": {
    "agent_id": "agent-1",
    "agent_name": "Idea Generator",
    "reason": "task_complete"
  }
}
```

#### Session Complete

```json
{
  "type": "session_complete",
  "timestamp": "2026-05-19T01:24:30Z",
  "data": {
    "session_id": "sess_abc123xyz",
    "status": "completed",
    "summary": "All agents completed successfully",
    "total_duration_ms": 270000,
    "output_available": true
  }
}
```

#### Error Event

```json
{
  "type": "error",
  "timestamp": "2026-05-19T01:21:00Z",
  "data": {
    "agent_id": "agent-2",
    "error_code": "rate_limit_exceeded",
    "message": "API rate limit reached, pausing for 30 seconds",
    "recoverable": true
  }
}
```

---

### 3.3 Client-to-Server Events (Future)

#### Send Message

```json
{
  "type": "user_message",
  "data": {
    "message": "Can you add more video ideas?",
    "timestamp": "2026-05-19T01:22:00Z"
  }
}
```

#### Cancel Request

```json
{
  "type": "cancel_request",
  "data": {
    "reason": "User requested cancellation"
  }
}
```

---

## 4. Database Schema (Supabase/PostgreSQL)

### 4.1 Sessions Table

```sql
CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id VARCHAR(50) NOT NULL,
  user_id VARCHAR(100),
  goal TEXT NOT NULL,
  status VARCHAR(20) DEFAULT 'initializing',
  progress INTEGER DEFAULT 0,
  output JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);

CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_status ON sessions(status);
```

### 4.2 Agents Table

```sql
CREATE TABLE agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id),
  name VARCHAR(100) NOT NULL,
  role VARCHAR(100),
  status VARCHAR(20) DEFAULT 'idle',
  task TEXT,
  progress INTEGER DEFAULT 0,
  color VARCHAR(10),
  spawned_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP
);

CREATE INDEX idx_agents_session_id ON agents(session_id);
```

### 4.3 Feed Events Table

```sql
CREATE TABLE feed_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id),
  agent_id UUID REFERENCES agents(id),
  event_type VARCHAR(50) NOT NULL,
  message TEXT,
  metadata JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_feed_events_session_id ON feed_events(session_id);
```

---

## 5. Redis Schema (memX Layer)

### 5.1 Session State

**Key:** `session:{session_id}:state`

```json
{
  "status": "running",
  "current_phase": "agent_work",
  "active_agents": ["agent-1", "agent-2"],
  "progress": 65,
  "last_update": "2026-05-19T01:20:30Z"
}
```

### 5.2 Agent State

**Key:** `session:{session_id}:agent:{agent_id}`

```json
{
  "name": "Idea Generator",
  "status": "working",
  "task": "Analyzing trends...",
  "progress": 60,
  "memory": ["context item 1", "context item 2"]
}
```

### 5.3 Shared Memory (Inter-agent Communication)

**Key:** `session:{session_id}:shared_memory`

```json
{
  "shared_context": {
    "goal": "Create AI video",
    "constraints": ["5-10 minute length", "educational"]
  },
  "agent_outputs": {
    "idea-generator": ["Idea 1", "Idea 2"],
    "script-writer": "Script draft..."
  }
}
```

---

## 6. Pinecone Vector Schema (RAG)

### 6.1 Index Configuration

**Index Name:** `ai-agency-knowledge`

**Dimension:** 1536 (for text-embedding models)

**Metric:** Cosine similarity

### 6.2 Namespace Structure

- `domain-knowledge`: General domain information
- `session:{session_id}`: Session-specific knowledge
- `agent-outputs`: Cached agent outputs for retrieval

---

## 7. Integration Instructions

### 7.1 Frontend API Service Setup

Create `src/services/api.js`:

```javascript
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export const api = {
  // Health check
  async checkHealth() {
    const res = await fetch(`${API_BASE}/health`);
    return res.json();
  },

  // Get domains
  async getDomains() {
    const res = await fetch(`${API_BASE}/domains`);
    return res.json();
  },

  // Launch session
  async launchSession(domainId, goal) {
    const res = await fetch(`${API_BASE}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain_id: domainId, goal })
    });
    return res.json();
  },

  // Get session status
  async getSessionStatus(sessionId) {
    const res = await fetch(`${API_BASE}/session/${sessionId}`);
    return res.json();
  },

  // Get session output
  async getSessionOutput(sessionId) {
    const res = await fetch(`${API_BASE}/session/${sessionId}/output`);
    return res.json();
  },

  // Cancel session
  async cancelSession(sessionId) {
    const res = await fetch(`${API_BASE}/session/${sessionId}/cancel`, {
      method: 'POST'
    });
    return res.json();
  }
};
```

### 7.2 WebSocket Service

Create `src/services/websocket.js`:

```javascript
export class AgentWebSocket {
  constructor(sessionId, onMessage) {
    this.sessionId = sessionId;
    this.onMessage = onMessage;
    this.ws = null;
  }

  connect() {
    const wsUrl = `ws://localhost:8000/ws/${this.sessionId}`;
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => console.log('WebSocket connected');
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.onMessage(data);
    };
    this.ws.onclose = () => console.log('WebSocket disconnected');
    this.ws.onerror = (err) => console.error('WebSocket error:', err);
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  disconnect() {
    this.ws?.close();
  }
}
```

### 7.3 Environment Variables

Create `.env` file:

```
VITE_API_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000
```

---

## 8. Feature Mapping

### Frontend Features -> Backend Requirements

| Frontend Feature | Backend Endpoint | Notes |
|-----------------|------------------|-------|
| Domain Selection | `GET /api/domains` | Returns available domain teams |
| Goal Input | `POST /api/run` | Creates new session |
| Agent Spawning | WebSocket `agent_spawned` | Real-time event |
| Agent Status | WebSocket `agent_status` | Real-time updates |
| Live Feed | WebSocket events | Aggregated feed items |
| Agent Termination | WebSocket `agent_terminated` | Real-time event |
| Final Output | `GET /api/session/{id}/output` | Polling or WebSocket |
| Session Cancel | `POST /api/session/{id}/cancel` | Immediate termination |

---

## 9. Error Handling

### Error Codes

| Code | Description | Frontend Action |
|------|-------------|-----------------|
| `INVALID_DOMAIN` | Domain ID not found | Show error, prompt re-selection |
| `INVALID_GOAL` | Goal text too short | Show validation error |
| `SESSION_NOT_FOUND` | Session ID doesn't exist | Redirect to home |
| `SESSION_COMPLETED` | Session already finished | Show results |
| `RATE_LIMIT` | Too many requests | Show retry message |
| `AGENT_ERROR` | Individual agent failed | Log error, continue |
| `SESSION_TIMEOUT` | Session exceeded timeout | Auto-terminate |

---

## 10. Testing Checklist

- [ ] Health endpoint returns correct status
- [ ] Domains are fetched and displayed
- [ ] Session launches and returns session_id
- [ ] WebSocket connects successfully
- [ ] Agent spawn events fire correctly
- [ ] Agent status updates reflect in UI
- [ ] Live feed receives all event types
- [ ] Output is retrieved and displayed
- [ ] Session cancellation works
- [ ] Error states are handled gracefully

---

## 11. Example FastAPI Implementation Structure

```
backend/
├── main.py                 # FastAPI app entry
├── routers/
│   ├── __init__.py
│   ├── domains.py          # Domain endpoints
│   ├── sessions.py         # Session management
│   └── health.py           # Health check
├── services/
│   ├── __init__.py
│   ├── agent_orchestrator.py  # Hub-and-Spoke logic
│   ├── websocket_manager.py   # WebSocket handling
│   └── domain_loader.py       # Load domain configs
├── models/
│   ├── __init__.py
│   ├── session.py          # Session models
│   ├── agent.py            # Agent models
│   └── events.py           # Event schemas
├── db/
│   ├── __init__.py
│   ├── supabase.py         # Database client
│   └── redis.py            # Redis client
└── config.py               # Configuration
```

---

## 12. API Versioning

Current version: `v1`

All endpoints are prefixed with `/api/v1/` for future versioning support.

Example: `GET /api/v1/domains`

---

*Document Version: 1.0*  
*Last Updated: 2026-05-19*