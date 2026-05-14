"""
agents.py: Agent classes for the Hub-and-Spoke multi-agent system.
Implements LeadAgent, WorkerAgent, CriticAgent, and SynthesizerAgent.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from config_loader import config_loader
from memory import memx
from router import model_router
from schemas import (
    AuditLogEntry, DomainType, InboxMessage, TaskRecord, TaskStatus
)
from taskbox import TaskBox


class BaseAgent:
    """Base class for all agents with shared utilities."""

    def __init__(self, role: str, session_id: str, domain: DomainType, taskbox: TaskBox):
        self.role = role
        self.session_id = session_id
        self.domain = domain
        self.taskbox = taskbox

    async def _call_llm(self, user_prompt: str, user_preferences: Optional[dict] = None) -> dict:
        """Make an LLM call using the model router with proper prompt loading."""
        system_prompt = config_loader.build_agent_system_prompt(
            self.domain, self.role, user_preferences
        )
        model_config = config_loader.get_agent_model_config(self.domain, self.role)
        result = await model_router.generate(
            model=model_config["model"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=model_config["temperature"],
            max_tokens=model_config["max_tokens"],
        )
        # Log to audit
        await self.taskbox.log_action(AuditLogEntry(
            session_id=self.session_id,
            agent_role=self.role,
            action="llm_call",
            details={"model": model_config["model"], "prompt_preview": user_prompt[:200]},
            status=TaskStatus.COMPLETED if not result.get("error") else TaskStatus.FAILED,
            error_message=result.get("error"),
            token_count=result.get("tokens", 0),
            latency_ms=result.get("latency_ms", 0),
        ))
        return result

    async def _update_memx_status(self, status: str, message: str = "") -> None:
        """Push a status update to memX for real-time UI."""
        await memx.update_state(
            f"session:{self.session_id}:agent:{self.role}",
            {"status": status, "message": message, "timestamp": datetime.utcnow().isoformat()},
        )


class LeadAgent(BaseAgent):
    """
    Orchestrator — decomposes user goals into tasks and assigns them to Workers.
    Uses the domain config to determine which Workers to spawn.
    """

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        super().__init__("Lead", session_id, domain, taskbox)
        self.domain_config = config_loader.load_domain_config(domain)

    async def decompose_goal(self, user_goal: str, user_preferences: dict) -> list[TaskRecord]:
        """Break a user goal into subtasks for each worker in the workflow."""
        await self._update_memx_status("thinking", "Decomposing user goal into subtasks...")

        prompt = (
            f"User Goal: {user_goal}\n\n"
            f"Domain: {self.domain.value}\n"
            f"Available Workers: {json.dumps(self.domain_config.workflow)}\n"
            f"Worker Descriptions:\n"
        )
        for member in self.domain_config.team_roles:
            prompt += f"  - {member.role}: {member.goal}\n"

        prompt += (
            "\nDecompose this goal into one task per worker. "
            "Return a JSON array of objects with: target_agent, goal, input_context."
        )

        result = await self._call_llm(prompt, user_preferences)
        tasks: list[TaskRecord] = []

        # Parse LLM response into tasks
        try:
            content = result.get("content", "")
            # Try to extract JSON from the response
            if "[" in content:
                json_str = content[content.index("["):content.rindex("]") + 1]
                task_specs = json.loads(json_str)
            else:
                # Fallback: create default tasks from domain config
                task_specs = [
                    {"target_agent": m.role, "goal": m.goal, "input_context": {"user_goal": user_goal}}
                    for m in self.domain_config.team_roles
                    if m.role != "Critic"
                ]
        except (json.JSONDecodeError, ValueError):
            logger.warning("LLM response not valid JSON, using default task decomposition")
            task_specs = [
                {"target_agent": m.role, "goal": m.goal, "input_context": {"user_goal": user_goal}}
                for m in self.domain_config.team_roles
                if m.role != "Critic"
            ]

        # Write tasks to Taskbox
        for spec in task_specs:
            task = TaskRecord(
                session_id=self.session_id,
                domain=self.domain.value,
                agent_role=spec["target_agent"],
                goal=spec.get("goal", ""),
                input_data={
                    **spec.get("input_context", {}),
                    "user_goal": user_goal,
                    "preference_note": json.dumps(user_preferences),
                },
            )
            await self.taskbox.write_task(task)
            tasks.append(task)
            logger.info(f"Task created: {task.task_id} → {task.agent_role}")

        await self._update_memx_status("delegating", f"Created {len(tasks)} tasks")
        return tasks


class WorkerAgent(BaseAgent):
    """Generic worker that executes its assigned task using the LLM."""

    async def execute_task(self, task: dict, user_preferences: dict) -> dict:
        """Execute a single task and write results back to Taskbox."""
        task_id = task["task_id"]
        await self._update_memx_status("working", f"Executing: {task['goal'][:80]}...")
        await self.taskbox.update_task_status(task_id, TaskStatus.IN_PROGRESS)

        prompt = (
            f"Task: {task['goal']}\n\n"
            f"Input Context:\n{json.dumps(task.get('input_data', {}), indent=2)}\n\n"
            "Produce your best work. Follow user preferences strictly."
        )

        try:
            result = await self._call_llm(prompt, user_preferences)
            if result.get("error"):
                raise RuntimeError(result["error"])

            output = {"content": result["content"], "model_used": result.get("model_used", "")}
            await self.taskbox.update_task_status(task_id, TaskStatus.COMPLETED, output_data=output)
            await self._update_memx_status("done", "Task completed")
            return output

        except Exception as e:
            retry_count = await self.taskbox.increment_retry(task_id)
            if retry_count >= 3:
                await self.taskbox.update_task_status(task_id, TaskStatus.FAILED, error_message=str(e))
                await self._update_memx_status("failed", f"Failed after {retry_count} retries")
            else:
                await self.taskbox.update_task_status(task_id, TaskStatus.PENDING, error_message=str(e))
                await self._update_memx_status("retrying", f"Retry {retry_count}/3")
            return {"error": str(e)}


class CriticAgent(BaseAgent):
    """Reviews all worker outputs for quality, tone, and user preference compliance."""

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        super().__init__("Critic", session_id, domain, taskbox)

    async def review_output(self, task: dict, user_preferences: dict) -> dict:
        """Review a completed task output. Returns verdict: approved/revision_requested."""
        await self._update_memx_status("reviewing", f"Reviewing {task['agent_role']}'s output...")

        output_content = task.get("output_data", {}).get("content", "")
        prompt = (
            f"Review this output from {task['agent_role']}:\n\n"
            f"Original Goal: {task['goal']}\n\n"
            f"Output:\n{output_content[:3000]}\n\n"
            f"User Preferences: {json.dumps(user_preferences)}\n\n"
            "Evaluate: accuracy, completeness, tone compliance, style errors.\n"
            "Return JSON with: verdict (approved/revision_requested), score (0-1), feedback."
        )

        result = await self._call_llm(prompt, user_preferences)
        content = result.get("content", "")

        # Parse verdict
        try:
            if "{" in content:
                json_str = content[content.index("{"):content.rindex("}") + 1]
                review = json.loads(json_str)
            else:
                review = {"verdict": "approved", "score": 0.7, "feedback": content}
        except (json.JSONDecodeError, ValueError):
            review = {"verdict": "approved", "score": 0.7, "feedback": content}

        verdict = review.get("verdict", "approved")
        if verdict == "revision_requested":
            # Send revision request back to the worker
            await self.taskbox.send_to_inbox(InboxMessage(
                session_id=self.session_id,
                target_agent=task["agent_role"],
                source_agent="Critic",
                task_id=task["task_id"],
                content={"feedback": review.get("feedback", ""), "action": "revise"},
            ))
            await self.taskbox.update_task_status(task["task_id"], TaskStatus.REVISION_REQUESTED)
            await self._update_memx_status("revision_sent", f"Sent revision to {task['agent_role']}")
        else:
            await self._update_memx_status("approved", f"Approved {task['agent_role']}'s output")

        return review


class SynthesizerAgent(BaseAgent):
    """Aggregates all approved results into the final output package."""

    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox):
        super().__init__("Synthesizer", session_id, domain, taskbox)

    async def synthesize(self, approved_tasks: list[dict], user_preferences: dict) -> dict:
        """Combine approved task outputs into a final deliverable."""
        await self._update_memx_status("synthesizing", "Merging all approved outputs...")

        parts = []
        for task in approved_tasks:
            role = task.get("agent_role", "Unknown")
            content = task.get("output_data", {}).get("content", "")
            parts.append(f"--- {role} Output ---\n{content}")

        combined = "\n\n".join(parts)
        prompt = (
            "You are synthesizing the final deliverable from a team of specialists.\n\n"
            f"Combined Outputs:\n{combined[:6000]}\n\n"
            "Create a cohesive, polished final package that integrates all outputs. "
            "Follow user preferences for formatting and tone."
        )

        result = await self._call_llm(prompt, user_preferences)
        final_output = {
            "content": result.get("content", ""),
            "model_used": result.get("model_used", ""),
            "sources": [t.get("agent_role", "") for t in approved_tasks],
        }
        await self._update_memx_status("complete", "Final synthesis delivered")
        return final_output
