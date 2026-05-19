"""
context.py: Context Compaction logic.
Per SOP Phase 3: "Add logic to summarize conversation history every N turns, preserving only key decisions."
"""

from __future__ import annotations

from loguru import logger
from schemas import TaskRecord
from router import model_router

class ContextCompactor:
    """Summarizes and compacts long conversation histories."""

    def __init__(self, compaction_threshold: int = 5):
        self.compaction_threshold = compaction_threshold

    async def check_and_compact(self, session_id: str, tasks: list[TaskRecord]) -> str:
        """
        Check if the task history exceeds the threshold. If so, summarize it.
        Returns the summarized context string.
        """
        if len(tasks) < self.compaction_threshold:
            # Just return full context if below threshold
            return self._build_full_context(tasks)

        logger.info(f"Session {session_id} hit compaction threshold ({len(tasks)} tasks). Compacting...")
        
        # Build prompt for summarization
        history_text = self._build_full_context(tasks)
        
        system_prompt = (
            "You are an AI context compressor. Your job is to summarize the following workflow history.\n"
            "CRITICAL: Preserve key decisions, constraints, and final approved data. Omit intermediate failures and chatty text."
        )
        
        try:
            # Using light model for fast compaction
            result = await model_router.generate(
                model="gemini-2.0-flash", 
                system_prompt=system_prompt,
                user_prompt=f"HISTORY TO SUMMARIZE:\n\n{history_text}",
                temperature=0.3,
                max_tokens=1024,
                complexity=0.2 # force light model usage if router maps it
            )
            
            if result.get("error"):
                logger.error(f"Compaction failed: {result['error']}")
                return history_text
                
            summary = result.get("content", "")
            logger.info(f"Compaction successful. Original size: {len(history_text)} chars. New size: {len(summary)} chars.")
            return summary
            
        except Exception as e:
            logger.error(f"Error during context compaction: {e}")
            return history_text

    def _build_full_context(self, tasks: list[TaskRecord]) -> str:
        """Build a raw text representation of the task history."""
        parts = []
        for t in tasks:
            status = t.status.value
            role = t.agent_role
            goal = t.goal
            content = t.output_data.get("content", "")[:500]  # truncate huge outputs
            parts.append(f"[{role} - {status}] Goal: {goal}\nOutput: {content}\n")
        return "\n".join(parts)

context_compactor = ContextCompactor()
