# SOP.md: Standard Operating Procedure
## Project: AI Agency Platform (Gemma 4 Multi-Agent Prototype)
## Version: 1.0 (Hackathon Sprint)
## Team Size: 2–3 Developers
## Objective: Build a domain-switchable multi-agent system where users select a purpose (e.g., YouTube, Legal) and watch a specialized team collaborate via shared memory.

---

## 1. 🎯 Mission & Scope
- **Primary Goal:** Demonstrate a functional "Hub-and-Spoke" multi-agent system where a Lead Agent orchestrates specialized Workers based on user-selected domains.
- **Key Differentiator:** Dynamic team assembly (one codebase, multiple domain configs) + Real-time visibility of agent collaboration via a shared memory board.
- **Constraints:** 
  - **$0 Cost:** Strictly use Free Tier (Google Cloud $300 credit, Vertex AI Express, Local Ollama).
  - **Time:** 48-Hour Hackathon Sprint.
  - **Tech:** FastAPI (Backend), React/Streamlit (Frontend), SQLite (Taskbox), Redis/memX (State).

---

## 2. 🏗️ Architecture Standards
All team members must adhere to this architectural blueprint:

### 2.1 Core Components
| Component | Technology | Responsibility |
| :--- | :--- | :--- |
| **Orchestrator** | FastAPI + Python Loop | Manages state machine, routes tasks, polls Taskbox. |
| **Agents** | Gemma 4 (via Ollama/Vertex) | Execute specific roles (Idea, Script, SEO, Critic). |
| **Taskbox** | SQLite (WAL Mode) | Durable message queue (`tasks`, `inboxes`, `audit_log`). |
| **Shared State** | Redis (Upstash Free) or Local Redis | Real-time pub/sub for `memX` (task status, shared vars). |
| **Memory** | FAISS (Local) + SQLite | Semantic caching and episodic logging. |
| **UI** | React (Vite) or Streamlit | Visualizes agent steps, memory updates, and final output. |

### 2.2 Data Flow Protocol
1. **User Input:** Selects Domain (e.g., "YouTube") + Goal.
2. **Lead Agent:** Loads domain config → Decomposes goal → Writes tasks to `SQLite Taskbox`.
3. **Workers:** Poll their specific inbox → Execute (LLM call) → Write result to DB + Update Redis state.
4. **Critic:** Reviews outputs → Approves or Requests Revision.
5. **Synthesizer:** Aggregates approved results → Returns final package to User.

---

## 3. 👥 Team Roles & Responsibilities

###  Developer A: Backend & Orchestration Lead
- **Focus:** FastAPI setup, Agent logic, Database schema, Model routing.
- **Deliverables:**
  - `main.py`: FastAPI entry point with WebSocket support.
  - `agents.py`: Classes for Lead, Workers, Critic.
  - `taskbox.py`: SQLite WAL interaction layer.
  - `router.py`: Logic to switch between Local (Ollama) and Cloud (Vertex) models.
- **Key Task:** Ensure the "Domain Config" loader works dynamically (swapping prompts based on selection).

### 🔹 Developer B: Frontend & Observability Lead
- **Focus:** React/Streamlit UI, Real-time updates, Visualization of agent thoughts.
- **Deliverables:**
  - `App.tsx` / `app.py`: Main dashboard.
  - Components: "Agent Status Cards", "Live Memory Log", "Final Output Viewer".
  - Integration: Connect to FastAPI WebSockets for real-time task updates.
- **Key Task:** Make the "thinking process" visible (e.g., show "Scriptwriter is drafting..." live).

### 🔹 Developer C: Prompt Engineering & Testing (Optional/Shared)
- **Focus:** `SKILL.md` and `CLAUDE.md` refinement, Domain Configs, Testing.
- **Deliverables:**
  - `domains/`: JSON/YAML configs for YouTube, Legal, Startup, etc.
  - `prompts/`: Refined system prompts for each role.
  - Test Cases: Run 3 full workflows end-to-end; debug hallucinations.
- **Key Task:** Ensure the "Critic" agent actually catches errors and forces retries.

*(Note: If only 2 members, split C's tasks between A and B).*

---

## 4. 🛠️ Development Workflow (Step-by-Step)

### Phase 1: Setup (Hours 0–4)
1. **Repo Init:** `git init`, create `backend/` and `frontend/` folders.
2. **Env Setup:** 
   - Install Ollama: `ollama pull gemma4:e2b` (and `gemma4:31b` if cloud access allows).
   - Start Redis: `docker run -d -p 6379:6379 redis` or connect to Upstash Free.
   - Create SQLite DB: `sqlite3 taskbox.db` → Enable WAL: `PRAGMA journal_mode=WAL;`.
3. **Config Files:** Create `SKILL.md`, `CLAUDE.md`, and `domains/youtube.json`, `domains/legal.json`.

### Phase 2: Core Logic (Hours 4–20)
1. **Build Taskbox:** Implement `write_task()`, `poll_inbox()`, `update_status()` in Python.
2. **Define Agents:** Code the `LeadAgent` loop that reads `domains/*.json` and spawns worker tasks.
3. **Model Router:** Implement logic: `if complexity > threshold -> vertex_ai else -> ollama_local`.
4. **Test Loop:** Run a hardcoded "YouTube" flow manually in terminal to verify DB writes/reads.

### Phase 3: Integration & UI (Hours 20–36)
1. **WebSocket Bridge:** Connect FastAPI events to Frontend.
2. **UI Components:** Build the "Live Feed" showing agent messages appearing in real-time.
3. **Domain Switcher:** Add dropdown in UI to select "YouTube" vs "Legal" and reload agent config.
4. **End-to-End Test:** Run full flow from UI input to final output.

### Phase 4: Polish & Demo Prep (Hours 36–48)
1. **Error Handling:** Add retry logic for failed API calls.
2. **Observability:** Add simple logging to UI (e.g., "Token count", "Time taken").
3. **Demo Script:** Prepare a 2-minute walkthrough: "Watch me switch from YouTube to Legal instantly."
4. **Submission:** Record video, write README, submit to Kaggle/Hackathon portal.

---

## 5. 📝 Coding Standards & Conventions

### 5.1 Naming Conventions
- **Variables:** `snake_case` (e.g., `task_id`, `session_status`).
- **Classes:** `PascalCase` (e.g., `LeadAgent`, `TaskBoxManager`).
- **Files:** `lowercase_with_underscores.py` (e.g., `agent_router.py`).
- **DB Tables:** `snake_case` (e.g., `agent_logs`, `shared_state`).

### 5.2 Error Handling
- **Never** let the app crash on an LLM timeout. Wrap all model calls in `try-except` blocks.
- **Log** errors to `audit_log` table with `status='failed'` and `error_message`.
- **Fallback:** If Cloud API fails, automatically switch to Local Ollama mode.

### 5.3 Prompt Management
- **Do not** hardcode prompts inside Python files.
- **Do** load prompts from `SKILL.md` and `CLAUDE.md` dynamically.
- **Do** use f-strings to inject domain-specific context (e.g., `f"You are a {role} for the {domain} team."`).

---

## 6.  Troubleshooting & Fallbacks

| Issue | Immediate Action | Fallback Strategy |
| :--- | :--- | :--- |
| **API Rate Limit Hit** | Check Redis counter. Pause new tasks. | Switch all workers to **Local Ollama** immediately. |
| **Context Window Full** | Trigger summarization step. | Drop oldest tool logs; keep only summary + current task. |
| **Agent Stuck in Loop** | Detect >3 retries on same task. | Force "Critic" to intervene and rewrite instructions. |
| **Redis Connection Lost** | Catch exception. | Switch to **SQLite-only** polling mode (slower but durable). |
| **Video Gen Too Slow** | Timeout after 30s. | Return a **Storyboard/Prompt** instead of actual video file. |

---

## 7. ✅ Definition of Done (DoD)
The prototype is considered "Done" when:
1. [ ] User can select at least **2 different domains** (e.g., YouTube, Legal).
2. [ ] The system spins up the correct team of agents for the selected domain.
3. [ ] Agents communicate via **SQLite Taskbox** (verified by checking DB).
4. [ ] Real-time updates are visible in the **UI** (no page refresh needed).
5. [ ] The "Critic" agent successfully rejects at least one bad output during testing.
6. [ ] The entire workflow runs on **Free Tier** resources ($0 spend).
7. [ ] Code is committed to GitHub with a clear `README.md`.

---

## 8. 📚 References
- **Architecture Doc:** `Building Gemma 4 Multi-Agent Systems.docx`
- **Constitution:** `CLAUDE.md`
- **Skills Library:** `SKILL.md`
- **Domain Configs:** `domains/` folder

---
*Last Updated: May 14, 2026 | Author: AI Agency Team*