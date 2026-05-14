# EXECUTION PLAN: AI Agency Platform (Gemma 4 Multi-Agent Prototype)
**Objective:** Build a domain-switchable multi-agent system where users select a purpose (e.g., YouTube, Legal), triggering a specialized team of agents that collaborate via shared memory.
**Team Size:** 2–3 Developers
**Resources:** Free-Tier Only (Ollama, SQLite, Redis, Vertex AI Express)

---

## 🔹 Phase 1: Foundation & Environment Setup
**Goal:** Establish the local/cloud dev environment, model access, and base infrastructure.
- [ ] **Cloud Setup:** Create Google Cloud account, activate $300 Free Trial, enable Vertex AI API & Cloud Run API.
- [ ] **Local Inference:** Install Ollama/llama.cpp. Pull Gemma 4 models (`gemma4:e2b`, `gemma4:e4b`, `gemma4:26b-moe`).
- [ ] **Project Scaffolding:** Initialize Git repo. Set up FastAPI backend and React/Vite frontend skeletons. Install `google-adk`.
- [ ] **Database Init:** Create SQLite database with WAL mode (`PRAGMA journal_mode=WAL;`) for the `Taskbox`.
- [ ] **Memory Layer:** Provision Redis (Upstash Free or Local Docker) for `memX` state sync.
- [ ] **Config Loading:** Create `SKILL.md`, `CLAUDE.md`, `USER_PREFERENCES.md`, and `DOMAIN_CONFIGS.json`. Write loader scripts.
- **✅ Deliverable:** Dev server running, models responding locally, DB/Redis connected.

---

## 🔹 Phase 2: Core Orchestration & Agent Roles
**Goal:** Build the Hub-and-Spoke engine using Google ADK and implement the Taskbox relay.
- [ ] **Define Agent Classes:** Code `LeadAgent`, `WorkerAgents` (dynamic based on domain), and `CriticAgent` using ADK primitives.
- [ ] **Implement Taskbox Relay:** Build SQLite schema (`tasks`, `inboxes`, `audit_log`). Write `write_task()` and `poll_inbox()` functions.
- [ ] **Wire ADK Primitives:** Implement `ParallelAgent` for independent tasks and `SequentialAgent` for dependencies.
- [ ] **Model Router Logic:** Write heuristic routing: Complexity > Threshold → Vertex AI (31B); Else → Local Ollama (E2B/E4B).
- [ ] **Dry Run Test:** Execute flow: User Input → Lead Decomposes → Workers Execute → Synthesizer Merges.
- **✅ Deliverable:** End-to-end text-based workflow working locally with hybrid routing.

---

## 🔹 Phase 3: Memory, State & Context Management
**Goal:** Solve context blowup and enable real-time coordination via `memX`.
- [ ] **Deploy memX Layer:** Set up FastAPI WebSocket endpoints + Redis Pub/Sub for real-time state sync.
- [ ] **Named Sessions:** Implement `session_id` generation. Create `/resume?session_id=X` endpoint to load compacted history.
- [ ] **Hybrid Retrieval (RAG):** Integrate `faiss-cpu` + `rank-bm25`. Implement RRF scoring (k=60) and τ=0.50 threshold filter.
- [ ] **Context Compaction:** Add logic to summarize conversation history every N turns, preserving only key decisions.
- [ ] **Preference Injection:** Ensure `USER_PREFERENCES.md` is dynamically loaded into every agent's system prompt.
- **✅ Deliverable:** Real-time state sync, context stays <32K tokens, retrieval returns grounded results.

---

## 🔹 Phase 4: Optimization & Free-Tier Survival
**Goal:** Maximize throughput within rate limits and ensure zero-cost operation.
- [ ] **Semantic Caching:** Vectorize prompts. Check local cache. If similarity > 0.85, return cached output.
- [ ] **Quantization & Offloading:** Configure local workers to run strictly in 4-bit GGUF. Add fallback logic for cloud quota hits.
- [ ] **Log Compression:** Strip tool outputs to essential fields (`status`, `error`, `result`) before storing in SQLite.
- [ ] **Containerization:** Create `Dockerfile` for FastAPI. Configure `min-instances=0` for Cloud Run scale-to-zero.
- [ ] **Rate Limit Guard:** Implement Redis counter to track RPM. Queue tasks in SQLite if limit approached.
- **✅ Deliverable:** System handles parallel tasks within free RPM, caches redundant calls, scales efficiently.

---

## 🔹 Phase 5: Security, Observability & Testing
**Goal:** Make the system debuggable, secure, and robust against hallucinations.
- [ ] **LangSmith Integration:** Connect SDK. Trace Lead, Worker, and Critic steps. Visualize execution tree.
- [ ] **OpenTelemetry (OTel):** Instrument FastAPI/Redis calls. Export traces to local Jaeger/Honeycomb.
- [ ] **Security Shields:** Integrate Model Armor (Express) or `presidio` for PII/injection scanning.
- [ ] **Critic Validation Loop:** Implement "Independent Verification": Critic re-solves and compares results.
- [ ] **Load Testing:** Use `locust` to simulate concurrent users. Verify SQLite WAL concurrency.
- **✅ Deliverable:** Live observability dashboard, secured I/O, automated validation loop.

---

## 🔹 Phase 6: Deployment & Demo Prep
**Goal:** Deploy to cloud, build UI, and prepare submission.
- [ ] **Backend Deployment:** Push Docker image to Artifact Registry. Deploy to Cloud Run (GPU attached, scale-to-zero).
- [ ] **Frontend Deployment:** Build React app. Deploy to Vercel/GitHub Pages. Connect to Cloud Run URL.
- [ ] **Scenario Integration:** Hardcode one specific use case (e.g., *YouTube Creator*) for the primary demo flow.
- [ ] **Observability UI:** Embed simplified LangSmith traces or status indicators in the React dashboard.
- [ ] **Submission Package:** Record demo video, write README highlighting "$0 Cost" and "Dynamic Teams", submit to Kaggle.
- **✅ Deliverable:** Fully deployed, demo-ready system with documentation.