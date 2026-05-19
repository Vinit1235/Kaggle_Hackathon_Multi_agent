"""
langgraph_workflow.py: LangGraph-based workflow execution with LangChain models.
"""

from __future__ import annotations

import asyncio
import json
import operator
import os
from typing import Any, Optional

from loguru import logger
from typing_extensions import Annotated, TypedDict

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_community.chat_message_histories import RedisChatMessageHistory
from langgraph.graph import StateGraph, START, END
from pinecone import Pinecone, ServerlessSpec

from config_loader import config_loader
from schemas import DomainType, TaskRecord, TaskStatus
from taskbox import TaskBox


class GraphState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    outputs: dict[str, str]
    reviews: dict[str, dict]
    revision_queue: list[str]
    retry_counts: dict[str, int]
    task_ids: dict[str, str]
    retrieval_context: list[str]
    user_goal: str
    user_preferences: dict[str, Any]
    final_output: str


class InMemoryChatHistory:
    def __init__(self) -> None:
        self.messages: list[BaseMessage] = []

    def add_message(self, message: BaseMessage) -> None:
        self.messages.append(message)


class TokenStreamHandler(AsyncCallbackHandler):
    def __init__(self, emit, agent_role: str) -> None:
        self._emit = emit
        self._agent_role = agent_role

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        await self._emit("stream", self._agent_role, token)


class LangGraphWorkflow:
    def __init__(self, session_id: str, domain: DomainType, taskbox: TaskBox) -> None:
        self.session_id = session_id
        self.domain = domain
        self.taskbox = taskbox
        self.raw_config = config_loader.get_raw_domain_config(domain)
        self._event_callbacks: list = []

        self._vector_store = self._init_vector_store()
        self._chat_history = self._init_chat_history(session_id)

    def on_event(self, callback) -> None:
        self._event_callbacks.append(callback)

    async def _emit(self, event_type: str, agent: str, message: str, **extra: Any) -> None:
        event = {"type": event_type, "agent": agent, "message": message, **extra}
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.error(f"Event callback failed: {e}")

    def _init_chat_history(self, session_id: str):
        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            try:
                return RedisChatMessageHistory(session_id=session_id, url=redis_url)
            except Exception as e:
                logger.warning(f"Redis chat history unavailable: {e}")
        upstash_url = os.getenv("UPSTASH_REDIS_REST_URL", "")
        upstash_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
        if upstash_url and upstash_token:
            try:
                from langchain_community.chat_message_histories import UpstashRedisChatMessageHistory
                return UpstashRedisChatMessageHistory(
                    session_id=session_id,
                    url=upstash_url,
                    token=upstash_token,
                )
            except Exception as e:
                logger.warning(f"Upstash chat history unavailable: {e}")
        return InMemoryChatHistory()

    def _init_vector_store(self) -> Optional[PineconeVectorStore]:
        pinecone_api_key = os.getenv("PINECONE_API_KEY", "")
        index_name = os.getenv("PINECONE_INDEX_NAME", "agency-rag")
        if not pinecone_api_key:
            return None

        try:
            pc = Pinecone(api_key=pinecone_api_key)
            dimension = int(os.getenv("PINECONE_DIMENSION", "768"))
            if pc.has_index(index_name):
                try:
                    desc = pc.describe_index(index_name)
                    existing_dim = getattr(desc, "dimension", None) or desc.get("dimension")
                    if existing_dim and existing_dim != dimension:
                        logger.warning(
                            "Pinecone index dimension mismatch (index=%s, env=%s). "
                            "Set PINECONE_DIMENSION to %s or recreate the index.",
                            existing_dim,
                            dimension,
                            existing_dim,
                        )
                        return None
                except Exception as e:
                    logger.warning(f"Failed to describe Pinecone index: {e}")
            else:
                cloud = os.getenv("PINECONE_CLOUD", "aws")
                region = os.getenv("PINECONE_REGION", "us-east-1")
                pc.create_index(
                    name=index_name,
                    dimension=dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=cloud, region=region),
                )

            embeddings = GoogleGenerativeAIEmbeddings(
                model=os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004"),
                google_api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
            )
            index = pc.Index(index_name)
            return PineconeVectorStore(index=index, embedding=embeddings)
        except Exception as e:
            logger.warning(f"Pinecone init failed: {e}")
            return None

    def _safe_model_name(self, requested: str) -> str:
        if requested.startswith("gemini-"):
            return requested
        return os.getenv("DEFAULT_GEMINI_MODEL", "gemini-2.0-flash")

    def _build_model(self, model_name: str, temperature: float, max_tokens: int, stream: bool, callbacks=None):
        return ChatGoogleGenerativeAI(
            model=self._safe_model_name(model_name),
            temperature=temperature,
            max_output_tokens=max_tokens,
            streaming=stream,
            callbacks=callbacks or [],
            google_api_key=os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""),
        )

    async def _retrieve_context(self, query: str) -> list[str]:
        if not self._vector_store:
            return []
        retriever = self._vector_store.as_retriever(search_kwargs={"k": 3})
        try:
            docs = await asyncio.to_thread(retriever.invoke, query)
            return [d.page_content for d in docs]
        except Exception as e:
            logger.warning(f"Retriever failed: {e}")
            return []

    def _agent_goal(self, role: str) -> str:
        for role_cfg in self.raw_config.get("team_roles", []):
            if role_cfg.get("role") == role:
                return role_cfg.get("goal", "")
        return ""

    async def _run_agent(
        self,
        role: str,
        state: GraphState,
        stream_to_ui: bool = False,
        revision_feedback: Optional[str] = None,
    ) -> str:
        model_cfg = config_loader.get_agent_model_config(self.domain, role)
        system_prompt = config_loader.build_agent_system_prompt(
            self.domain, role, state.get("user_preferences", {})
        )

        input_context: dict[str, Any] = {
            "user_goal": state.get("user_goal", ""),
            "previous_outputs": state.get("outputs", {}),
            "retrieval_context": state.get("retrieval_context", []),
            "conversation_history": [
                {"role": m.type, "content": m.content} for m in self._chat_history.messages
            ],
        }
        if revision_feedback:
            input_context["revision_feedback"] = revision_feedback

        user_prompt = (
            f"Task: {self._agent_goal(role)}\n\n"
            f"Input Context:\n{json.dumps(input_context, indent=2)}\n\n"
            "Produce your best work. Follow user preferences strictly."
        )

        callbacks = []
        if stream_to_ui:
            callbacks.append(TokenStreamHandler(self._emit, role))

        model = self._build_model(
            model_cfg.get("model", "gemini-2.0-flash"),
            model_cfg.get("temperature", 0.7),
            model_cfg.get("max_tokens", 2048),
            stream_to_ui,
            callbacks=callbacks,
        )

        result = await model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        content = result.content if isinstance(result, AIMessage) else str(result)
        return content

    async def _run_critic(self, role: str, output: str, user_preferences: dict[str, Any]) -> dict:
        system_prompt = config_loader.build_agent_system_prompt(self.domain, "Critic", user_preferences)
        model_cfg = config_loader.get_agent_model_config(self.domain, "Critic")
        prompt = (
            f"Review this output from {role}:\n\n"
            f"Original Goal: {self._agent_goal(role)}\n\n"
            f"Output:\n{output[:3000]}\n\n"
            f"User Preferences: {json.dumps(user_preferences)}\n\n"
            "Evaluate: accuracy, completeness, tone compliance, style errors.\n"
            "Return JSON with: verdict (approved/revision_requested), score (0-1), feedback."
        )

        model = self._build_model(
            model_cfg.get("model", "gemini-2.5-flash"),
            model_cfg.get("temperature", 0.3),
            model_cfg.get("max_tokens", 1024),
            False,
        )
        result = await model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])

        content = result.content if isinstance(result, AIMessage) else str(result)
        try:
            if "{" in content:
                json_str = content[content.index("{"):content.rindex("}") + 1]
                review = json.loads(json_str)
            else:
                review = {"verdict": "approved", "score": 0.7, "feedback": content}
        except (json.JSONDecodeError, ValueError):
            review = {"verdict": "approved", "score": 0.7, "feedback": content}

        return review

    async def run(self, user_goal: str, user_preferences: dict[str, Any]) -> dict:
        workflow = self.raw_config.get("workflow", [])
        parallel_stages = self.raw_config.get("parallel_stages", [])

        parallel_roles = {role for stage in parallel_stages for role in stage}
        sequential_roles = [r for r in workflow if r != "Critic" and r not in parallel_roles]

        async def lead_node(state: GraphState):
            await self._emit("status", "Lead", "Decomposing goal into subtasks...")
            task_ids: dict[str, str] = {}
            for role in [r for r in workflow if r != "Critic"]:
                task = TaskRecord(
                    session_id=self.session_id,
                    domain=self.domain.value,
                    agent_role=role,
                    goal=self._agent_goal(role),
                    input_data={"user_goal": user_goal, "preference_note": json.dumps(user_preferences)},
                )
                await self.taskbox.write_task(task)
                task_ids[role] = task.task_id
            return {"task_ids": task_ids}

        async def seq_node(state: GraphState):
            outputs = dict(state.get("outputs", {}))
            retry_counts = dict(state.get("retry_counts", {}))

            for role in sequential_roles:
                await self._emit("status", role, f"Working on: {self._agent_goal(role)[:80]}...")
                content = await self._run_agent(role, state)
                outputs[role] = content

                task_id = state.get("task_ids", {}).get(role)
                if task_id:
                    await self.taskbox.update_task_status(
                        task_id,
                        TaskStatus.COMPLETED,
                        output_data={"content": content},
                    )
                retry_counts.setdefault(role, 0)
                await self._emit("task_complete", role, f"{role} finished (completed)")

            return {"outputs": outputs, "retry_counts": retry_counts}

        async def parallel_node(state: GraphState):
            outputs = dict(state.get("outputs", {}))
            retry_counts = dict(state.get("retry_counts", {}))

            for stage in parallel_stages:
                await self._emit("status", "System", f"Parallel execution: {stage}")

                async def _run(role: str):
                    await self._emit("status", role, f"Working on: {self._agent_goal(role)[:80]}...")
                    content = await self._run_agent(role, state)
                    task_id = state.get("task_ids", {}).get(role)
                    if task_id:
                        await self.taskbox.update_task_status(
                            task_id,
                            TaskStatus.COMPLETED,
                            output_data={"content": content},
                        )
                    await self._emit("task_complete", role, f"{role} finished (completed)")
                    return role, content

                results = await asyncio.gather(*[_run(r) for r in stage])
                for role, content in results:
                    outputs[role] = content
                    retry_counts.setdefault(role, 0)

            return {"outputs": outputs, "retry_counts": retry_counts}

        async def critic_node(state: GraphState):
            outputs = state.get("outputs", {})
            reviews: dict[str, dict] = {}
            revision_queue: list[str] = []

            await self._emit("status", "Critic", f"Reviewing {len(outputs)} outputs...")
            for role, content in outputs.items():
                review = await self._run_critic(role, content, user_preferences)
                reviews[role] = review

                verdict = review.get("verdict", "approved")
                await self._emit(
                    "review",
                    "Critic",
                    f"{'Approved' if verdict == 'approved' else 'Revision requested'}: {role}",
                    verdict=verdict,
                    score=review.get("score", 0.0),
                )

                if verdict == "revision_requested":
                    current_retry = state.get("retry_counts", {}).get(role, 0)
                    if current_retry < self.raw_config.get("max_retries", 3):
                        revision_queue.append(role)

            return {"reviews": reviews, "revision_queue": revision_queue}

        async def revision_node(state: GraphState):
            revision_queue = state.get("revision_queue", [])
            outputs = dict(state.get("outputs", {}))
            retry_counts = dict(state.get("retry_counts", {}))

            for role in revision_queue:
                feedback = state.get("reviews", {}).get(role, {}).get("feedback", "")
                retry_counts[role] = retry_counts.get(role, 0) + 1
                await self._emit("status", role, f"Revising (attempt {retry_counts[role]})...")
                content = await self._run_agent(role, state, revision_feedback=feedback)
                outputs[role] = content

                task_id = state.get("task_ids", {}).get(role)
                if task_id:
                    await self.taskbox.update_task_status(
                        task_id,
                        TaskStatus.COMPLETED,
                        output_data={"content": content},
                    )

            return {"outputs": outputs, "retry_counts": retry_counts, "revision_queue": []}

        async def synth_node(state: GraphState):
            await self._emit("status", "Synthesizer", "Creating final deliverable...")
            await self._emit("stream_start", "Synthesizer", "")

            combined = "\n\n".join(
                f"--- {role} Output ---\n{content}"
                for role, content in state.get("outputs", {}).items()
            )
            input_context = {
                "user_goal": user_goal,
                "combined_outputs": combined,
                "retrieval_context": state.get("retrieval_context", []),
            }
            prompt = (
                "You are synthesizing the final deliverable from a team of specialists.\n\n"
                f"Combined Outputs:\n{combined[:6000]}\n\n"
                f"Input Context:\n{json.dumps(input_context, indent=2)}\n\n"
                "Create a cohesive, polished final package that integrates all outputs. "
                "Follow user preferences for formatting and tone."
            )

            model_cfg = config_loader.get_agent_model_config(self.domain, "Synthesizer")
            system_prompt = config_loader.build_agent_system_prompt(
                self.domain, "Synthesizer", user_preferences
            )

            callbacks = [TokenStreamHandler(self._emit, "Synthesizer")]
            model = self._build_model(
                model_cfg.get("model", "gemini-2.5-flash"),
                model_cfg.get("temperature", 0.5),
                model_cfg.get("max_tokens", 4096),
                True,
                callbacks=callbacks,
            )

            result = await model.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ])
            content = result.content if isinstance(result, AIMessage) else str(result)

            await self._emit("stream_end", "Synthesizer", "")
            await self._emit("final_output", "Synthesizer", "Workflow complete!", content=content)
            await self._emit("workflow_complete", "System", "All done!")
            return {"final_output": content, "messages": [AIMessage(content=content)]}

        def should_revise(state: GraphState) -> str:
            if state.get("revision_queue"):
                return "revision"
            return "synth"

        graph = StateGraph(GraphState)
        graph.add_node("lead", lead_node)
        graph.add_node("sequential", seq_node)
        graph.add_node("parallel", parallel_node)
        graph.add_node("critic", critic_node)
        graph.add_node("revision", revision_node)
        graph.add_node("synth", synth_node)

        graph.add_edge(START, "lead")
        graph.add_edge("lead", "sequential")
        graph.add_edge("sequential", "parallel")
        graph.add_edge("parallel", "critic")
        graph.add_conditional_edges("critic", should_revise, {"revision": "revision", "synth": "synth"})
        graph.add_edge("revision", "critic")
        graph.add_edge("synth", END)

        compiled = graph.compile()

        retrieval_context = await self._retrieve_context(user_goal)
        initial_state: GraphState = {
            "messages": [HumanMessage(content=user_goal)],
            "outputs": {},
            "reviews": {},
            "revision_queue": [],
            "retry_counts": {},
            "task_ids": {},
            "retrieval_context": retrieval_context,
            "user_goal": user_goal,
            "user_preferences": user_preferences,
            "final_output": "",
        }

        if self._chat_history:
            self._chat_history.add_message(HumanMessage(content=user_goal))

        await self._emit("status", "System", "Workflow starting...")
        result = await compiled.ainvoke(initial_state)

        final_output = result.get("final_output", "")
        if self._chat_history and final_output:
            self._chat_history.add_message(AIMessage(content=final_output))

        return {"status": "completed", "content": final_output}
