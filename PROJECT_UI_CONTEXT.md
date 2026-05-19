# AI Agency Platform - UI & Architecture Context

## 1. Project Overview
The **AI Agency Platform** is a highly dynamic, domain-switchable multi-agent system powered by Gemini (and local Ollama fallbacks). Users can select a specific "domain" (e.g., a "YouTube Creator" team or a "Legal Squad"), input a high-level goal, and watch as a team of specialized AI agents collaboratively breaks down, executes, reviews, and synthesizes the task in real-time.

## 2. Tech Stack & Architecture
*   **Frontend:** React 19 + Vite (Vanilla CSS for styling).
*   **Backend:** FastAPI (Python) running a custom Hub-and-Spoke agent orchestrator.
*   **Database (Task persistence):** Supabase (PostgreSQL).
*   **State / Memory Sync:** Redis (memX layer) for real-time inter-agent state.
*   **Vector Database (RAG):** Pinecone (with Upstash Vector fallback).
*   **Real-time Communication:** WebSockets stream the live agent thought processes and actions from the backend to the frontend UI.

## 3. Frontend Implementation Deep-Dive
The frontend logic is primarily contained within `src/App.jsx` and styling in `src/App.css` / `src/index.css`. 

### Key Application Sections
1.  **Status Header (`.app-header`)**
    *   Displays the application brand.
    *   Shows real-time connection statuses for Gemini, Redis, and the DB (TaskBox) using glowing status dots.
2.  **Domain Selector (`.domain-section`)**
    *   Fetches available domains from the backend API.
    *   Displays a grid of selectable "Domain Cards" (e.g., YouTube Creator).
    *   Each card lists the specialized agents that make up that team (e.g., *Idea_Generator, Script_Writer, SEO_Specialist*).
3.  **Goal Input (`.goal-section`)**
    *   A text area where the user provides their prompt/goal.
    *   A "Launch Team" button that triggers a `POST /api/run` request, returning a `session_id`.
4.  **Agent Team Dashboard (`.agents-section`)**
    *   Displays a grid of "Agent Cards".
    *   Each card represents a specific agent on the team.
    *   As the WebSocket receives data, these cards update their states (Idle, Working [with a loading spinner], Reviewing, Done, Error) and display the agent's current task/message.
5.  **Live Agent Feed (`.feed-section`)**
    *   A scrolling, terminal-style feed that connects to `ws://[backend]/ws/{session_id}`.
    *   Displays a chronological log of every action, thought, and communication between the agents (timestamped and color-coded by agent type).
6.  **Final Output (`.output-section`)**
    *   A prominent container that renders the final synthesized output once the workflow is completed.

### Current Design System & Aesthetics
*   **Theme:** A premium dark mode utilizing deep midnight blues and purples (`#0a0b0f`, `#12131a`).
*   **Typography:** Google Fonts `Outfit` for sleek, modern headings and `Inter` for highly legible body text.
*   **Effects (Glassmorphism):** The UI relies heavily on glassmorphism. Cards and containers use semi-transparent backgrounds with `backdrop-filter: blur(12px)` over subtle animated gradient backgrounds.
*   **Micro-animations:** Elements smoothly slide up on page load. Cards elevate and cast glowing box-shadows on hover. Status dots pulse to indicate live connections.

## 4. Instructions for the UI AI
When redesigning or improving this UI, keep the following in mind:
*   **Maintain the WebSocket Integration:** The UI relies on the React `useEffect` and `useCallback` hooks that manage the WebSocket connection (`wsRef`) and append to the `feedItems` state.
*   **Emphasize "Aliveness":** The core appeal of this app is watching the AI team collaborate. The Agent Cards and the Live Feed need to feel incredibly responsive and dynamic.
*   **Use Rich Aesthetics:** Do not resort to generic dashboard styling. Continue utilizing gradients, glassmorphism, glowing borders, and modern typography to ensure the app feels like a premium, state-of-the-art AI tool.
