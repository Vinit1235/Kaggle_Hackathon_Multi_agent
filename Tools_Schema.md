# TOOL_SCHEMAS.md: Available Functions & APIs
## Version: 1.0
## Instruction: Agents MUST call these tools using the exact JSON format provided. Do not invent new tools.

### 1. Memory & Communication Tools
**Tool Name:** `write_to_taskbox`
- **Description:** Writes a task result or status update to the shared SQLite database.
- **Parameters:**
  - `session_id` (string): Unique ID for the current user session.
  - `agent_role` (string): Role of the agent writing (e.g., "Script_Writer").
  - `content` (string): The actual output or message.
  - `status` (string): "pending", "completed", "failed".
- **Usage Example:** `write_to_taskbox(session_id="sess_123", agent_role="Script_Writer", content="Draft complete...", status="completed")`

**Tool Name:** `update_shared_state`
- **Description:** Updates a key in the Redis memX layer for real-time sync.
- **Parameters:**
  - `key` (string): e.g., "current_script", "seo_keywords".
  - `value` (string/json): The data to store.
- **Usage Example:** `update_shared_state(key="seo_keywords", value={"tags": ["AI", "Hackathon"]})`

**Tool Name:** `read_shared_state`
- **Description:** Retrieves the latest value for a specific key from Redis.
- **Parameters:** `key` (string).
- **Usage Example:** `read_shared_state(key="user_preferences")`

### 2. External Action Tools
**Tool Name:** `web_search`
- **Description:** Searches the internet for trending topics or factual verification.
- **Parameters:** `query` (string), `num_results` (int, default 3).
- **Usage Example:** `web_search(query="trending youtube tech topics 2026")`

**Tool Name:** `generate_image_prompt`
- **Description:** Creates a detailed prompt for an image generation model (DALL-E/Midjourney).
- **Parameters:** `subject` (string), `style` (string).
- **Usage Example:** `generate_image_prompt(subject="futuristic city", style="cyberpunk")`

### 3. Control Flow Tools
**Tool Name:** `request_revision`
- **Description:** Used by Critic to send a task back to a worker with feedback.
- **Parameters:** `target_agent` (string), `feedback` (string).
- **Usage Example:** `request_revision(target_agent="Script_Writer", feedback="Tone is too formal, make it casual.")`

**Tool Name:** `finalize_project`
- **Description:** Signals the Lead Agent that all tasks are complete and ready for synthesis.
- **Parameters:** `summary` (string).