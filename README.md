# AI Agency Platform — Gemma 4 Multi-Agent System

> **$0 Cost** | **Domain-Switchable** | **Real-Time Collaboration** | **Hub-and-Spoke Architecture**

## 🎯 What Is This?

A multi-agent AI system where users select a purpose (YouTube Creator, Legal Squad, etc.) and watch a specialized team of AI agents collaborate in real-time via shared memory.

**Key Features:**
- **Dynamic Team Assembly** — One codebase, multiple domain configs
- **Hub-and-Spoke** — Lead Agent orchestrates Workers, Critic reviews, Synthesizer merges
- **Live Visibility** — Watch agents think, draft, review, and revise in real-time
- **Free-Tier Only** — Runs on Ollama (local) + SQLite + Redis

## 🏗️ Architecture

```
User → React UI → FastAPI → Lead Agent
                              ↓
                    ┌─────────┼─────────┐
                    ↓         ↓         ↓
               Worker 1   Worker 2   Worker N
                    ↓         ↓         ↓
                    └─────────┼─────────┘
                              ↓
                         Critic Agent
                              ↓
                       Synthesizer Agent
                              ↓
                        Final Output → UI
```

**Communication:** SQLite Taskbox (WAL mode) + Redis memX (pub/sub)

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.ai) installed locally

### 1. Pull Gemma 4 Models
```bash
ollama pull gemma4:e2b
ollama pull gemma4:26b-moe    # optional, for heavier tasks
```

### 2. Backend Setup
```bash
cd backend
cp .env.example .env
pip install -r requirements.txt
python main.py
```
Backend runs at `http://localhost:8000`

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:5173`

### 4. (Optional) Redis
```bash
docker run -d -p 6379:6379 redis
```
System works without Redis (falls back to in-memory state).

## 📁 Project Structure

```
├── backend/
│   ├── main.py              # FastAPI + WebSocket + Workflow Engine
│   ├── agents.py            # Lead, Worker, Critic, Synthesizer
│   ├── taskbox.py           # SQLite WAL Taskbox (message queue)
│   ├── router.py            # Ollama ↔ Vertex AI model routing
│   ├── config_loader.py     # Domain configs + prompt loader
│   ├── memory.py            # Redis memX + FAISS semantic cache
│   ├── schemas.py           # Pydantic data models
│   ├── domains/             # Domain team configs (JSON)
│   └── prompts/             # Agent system prompts (Markdown)
├── frontend/
│   └── src/
│       ├── App.jsx          # Live dashboard
│       ├── App.css          # Component styles
│       └── index.css        # Design system
├── CLAUDE.md                # Agent constitution
├── SOP.md                   # Standard operating procedure
├── Execution_Plan.md        # Build phases
└── README.md                # This file
```

## 🔧 Available Domains

| Domain | Team | Description |
|--------|------|-------------|
| **YouTube Creator** | Idea Generator → Script Writer → Visual Director → SEO Specialist → Critic | End-to-end video content creation |
| **Legal Squad** | Clause Drafter → Compliance Checker → Plain Language Translator → Critic | Contract drafting and compliance |

## 📝 License
Built for Kaggle Hackathon 2026. MIT License.
