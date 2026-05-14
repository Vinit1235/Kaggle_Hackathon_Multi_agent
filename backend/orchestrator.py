"""
orchestrator.py: ADK-style orchestration primitives — ParallelAgent and SequentialAgent wrappers.
These coordinate multi-agent workflows with proper dependency management.

Per Execution Plan Phase 2:
  - ParallelAgent: runs independent tasks concurrently
  - SequentialAgent: runs dependent tasks in order
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from loguru import logger

from agents import CriticAgent, LeadAgent, SynthesizerAgent, WorkerAgent
from config_loader import config_loader
from memory import memx
from schemas import DomainType, TaskStatus
from taskbox import TaskBox


class SequentialAgent:
    """
    Executes a list of agent roles one-by-one in workflow order.
    Each agent waits for the previous to finish before starting.
    Output from each step is passed as input context to the next.
    """

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        self.session_id = session_id
        self.domain = domain
        self.taskbox = taskbox

    async def execute(
        self,
        roles: list[str],
        user_preferences: dict,
        initial_context: dict | None = None,
    ) -> list[dict]:
        """Run agents sequentially, chaining outputs."""
        results = []
        carry_context = initial_context or {}

        for role in roles:
            logger.info(f"[Sequential] Executing: {role}")
            await memx.update_state(
                f"session:{self.session_id}:orchestrator",
                {"mode": "sequential", "current_agent": role, "step": len(results) + 1, "total": len(roles)},
            )

            # Get pending tasks for this agent
            pending = await self.taskbox.get_pending_tasks(self.session_id, role)
            if not pending:
                logger.warning(f"[Sequential] No pending tasks for {role}, skipping")
                continue

            worker = WorkerAgent(role, self.session_id, self.domain, self.taskbox)

            for task in pending:
                # Inject carry-over context from previous agent
                if carry_context:
                    task["input_data"]["previous_outputs"] = carry_context

                output = await worker.execute_task(task, user_preferences)

                if not output.get("error"):
                    carry_context[role] = output.get("content", "")
                    results.append({
                        "agent_role": role,
                        "task_id": task["task_id"],
                        "output": output,
                        "status": "completed",
                    })
                else:
                    results.append({
                        "agent_role": role,
                        "task_id": task["task_id"],
                        "output": output,
                        "status": "failed",
                    })

        logger.info(f"[Sequential] Completed {len(results)} tasks across {len(roles)} roles")
        return results


class ParallelAgent:
    """
    Executes a list of agent roles concurrently.
    Used for independent tasks that don't depend on each other.
    """

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        self.session_id = session_id
        self.domain = domain
        self.taskbox = taskbox

    async def execute(
        self,
        roles: list[str],
        user_preferences: dict,
        shared_context: dict | None = None,
    ) -> list[dict]:
        """Run multiple agents in parallel."""
        logger.info(f"[Parallel] Executing concurrently: {roles}")
        await memx.update_state(
            f"session:{self.session_id}:orchestrator",
            {"mode": "parallel", "agents": roles, "count": len(roles)},
        )

        async def _run_agent(role: str) -> list[dict]:
            pending = await self.taskbox.get_pending_tasks(self.session_id, role)
            if not pending:
                return []

            worker = WorkerAgent(role, self.session_id, self.domain, self.taskbox)
            agent_results = []

            for task in pending:
                if shared_context:
                    task["input_data"]["shared_context"] = shared_context

                output = await worker.execute_task(task, user_preferences)
                agent_results.append({
                    "agent_role": role,
                    "task_id": task["task_id"],
                    "output": output,
                    "status": "completed" if not output.get("error") else "failed",
                })

            return agent_results

        # Run all agents concurrently
        tasks = [_run_agent(role) for role in roles]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for i, res in enumerate(all_results):
            if isinstance(res, Exception):
                logger.error(f"[Parallel] {roles[i]} failed: {res}")
                results.append({
                    "agent_role": roles[i],
                    "task_id": "unknown",
                    "output": {"error": str(res)},
                    "status": "failed",
                })
            else:
                results.extend(res)

        logger.info(f"[Parallel] Completed {len(results)} tasks")
        return results


class WorkflowOrchestrator:
    """
    Full workflow orchestrator that reads domain config and executes:
    1. Lead decomposes goal → creates tasks
    2. Workers execute (sequential or parallel based on domain config)
    3. Critic reviews all outputs
    4. Synthesizer merges approved results

    Uses `parallel_stages` from domain config to determine which roles run concurrently.
    """

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        self.session_id = session_id
        self.domain = domain
        self.taskbox = taskbox
        self.raw_config = config_loader.get_raw_domain_config(domain)
        self._event_callbacks: list = []

    def on_event(self, callback):
        """Register a callback for workflow events (for WebSocket broadcasting)."""
        self._event_callbacks.append(callback)

    async def _emit(self, event_type: str, agent: str, message: str, **extra):
        """Emit an event to all registered callbacks."""
        event = {"type": event_type, "agent": agent, "message": message, **extra}
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.error(f"Event callback failed: {e}")

    async def run(self, user_goal: str, user_preferences: dict) -> dict:
        """Execute the full multi-agent workflow."""
        await self._emit("status", "System", "Workflow starting...")

        # ── Step 1: Lead decomposes goal ──
        await self._emit("status", "Lead", "Decomposing goal into subtasks...")
        lead = LeadAgent(self.session_id, self.domain, self.taskbox)
        tasks = await lead.decompose_goal(user_goal, user_preferences)
        await self._emit("status", "Lead", f"Created {len(tasks)} subtasks")

        # ── Step 2: Workers execute ──
        workflow = self.raw_config.get("workflow", [])
        parallel_stages = self.raw_config.get("parallel_stages", [])

        # Flatten parallel stage roles
        parallel_roles = set()
        for stage in parallel_stages:
            for role in stage:
                parallel_roles.add(role)

        # Separate sequential and parallel roles (exclude Critic)
        sequential_roles = [r for r in workflow if r != "Critic" and r not in parallel_roles]

        # Execute sequential roles first
        if sequential_roles:
            await self._emit("status", "System", f"Sequential execution: {sequential_roles}")
            seq = SequentialAgent(self.session_id, self.domain, self.taskbox)
            seq_results = await seq.execute(sequential_roles, user_preferences)
            for r in seq_results:
                await self._emit(
                    "task_complete", r["agent_role"],
                    f"{r['agent_role']} finished ({r['status']})",
                    task_id=r["task_id"],
                )

        # Execute parallel stages
        for stage in parallel_stages:
            await self._emit("status", "System", f"Parallel execution: {stage}")
            par = ParallelAgent(self.session_id, self.domain, self.taskbox)
            # Build shared context from sequential results
            all_tasks = await self.taskbox.get_tasks_by_session(self.session_id)
            shared_ctx = {}
            for t in all_tasks:
                if t["status"] == "completed":
                    shared_ctx[t["agent_role"]] = t.get("output_data", {}).get("content", "")

            par_results = await par.execute(stage, user_preferences, shared_context=shared_ctx)
            for r in par_results:
                await self._emit(
                    "task_complete", r["agent_role"],
                    f"{r['agent_role']} finished ({r['status']})",
                    task_id=r["task_id"],
                )

        # ── Step 3: Critic reviews ──
        all_tasks = await self.taskbox.get_tasks_by_session(self.session_id)
        completed = [t for t in all_tasks if t["status"] == "completed"]
        await self._emit("status", "Critic", f"Reviewing {len(completed)} outputs...")

        critic = CriticAgent(self.session_id, self.domain, self.taskbox)
        max_retries = self.raw_config.get("max_retries", 3)
        reviews = []

        for task in completed:
            review = await critic.review_output(task, user_preferences)
            reviews.append(review)
            await self._emit(
                "review", "Critic",
                f"{'✅ Approved' if review.get('verdict') == 'approved' else '🔄 Revision requested'}: {task['agent_role']}",
                verdict=review.get("verdict", "approved"),
                score=review.get("score", 0),
            )

            # Handle revision loop
            if review.get("verdict") == "revision_requested":
                for retry in range(max_retries):
                    await self._emit("status", task["agent_role"], f"Revising (attempt {retry + 1}/{max_retries})...")
                    worker = WorkerAgent(task["agent_role"], self.session_id, self.domain, self.taskbox)

                    # Reset task to pending for re-execution
                    await self.taskbox.update_task_status(task["task_id"], TaskStatus.PENDING)
                    task["status"] = "pending"
                    task["input_data"]["revision_feedback"] = review.get("feedback", {})

                    output = await worker.execute_task(task, user_preferences)
                    if output.get("error"):
                        continue

                    # Re-fetch and re-review
                    updated = await self.taskbox.get_task(task["task_id"])
                    review = await critic.review_output(updated, user_preferences)
                    if review.get("verdict") == "approved":
                        await self._emit("status", "Critic", f"✅ Approved {task['agent_role']} after revision")
                        break

        # ── Step 4: Synthesize ──
        final_tasks = await self.taskbox.get_tasks_by_session(self.session_id)
        approved = [t for t in final_tasks if t["status"] == "completed"]

        if not approved:
            await self._emit("error", "System", "No approved outputs to synthesize")
            return {"status": "failed", "error": "No approved outputs"}

        await self._emit("status", "Synthesizer", "Creating final deliverable...")
        synth = SynthesizerAgent(self.session_id, self.domain, self.taskbox)
        final_output = await synth.synthesize(approved, user_preferences)

        await memx.update_state(f"session:{self.session_id}:final_output", final_output)
        await self._emit(
            "final_output", "Synthesizer",
            "Workflow complete!",
            content=final_output.get("content", "")[:2000],
        )
        await self._emit("workflow_complete", "System", "All done!")

        return {
            "status": "completed",
            "session_id": self.session_id,
            "final_output": final_output,
            "task_count": len(final_tasks),
            "approved_count": len(approved),
        }
