"""
router.py: Model Router — switches between Local (Ollama) and Cloud (Vertex AI).
Per SOP: if complexity > threshold → Vertex AI; else → Local Ollama.
Includes automatic fallback if cloud API fails.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from loguru import logger

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
COMPLEXITY_THRESHOLD = float(os.getenv("COMPLEXITY_THRESHOLD", "0.6"))


class ModelRouter:
    """Routes LLM calls to Local Ollama or Cloud Vertex AI based on complexity."""

    def __init__(self):
        self._ollama_available: Optional[bool] = None
        self._vertex_available: Optional[bool] = None

    async def check_ollama(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    async def generate(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        complexity: float = 0.5,
    ) -> dict[str, Any]:
        """
        Route a generation request to the appropriate backend.
        Returns: {"content": str, "model_used": str, "latency_ms": float, "tokens": int}
        """
        start = time.time()

        # Decide routing
        use_cloud = complexity > COMPLEXITY_THRESHOLD and self._vertex_available
        if use_cloud:
            try:
                result = await self._call_vertex(model, system_prompt, user_prompt, temperature, max_tokens)
                result["latency_ms"] = (time.time() - start) * 1000
                return result
            except Exception as e:
                logger.warning(f"Vertex AI failed, falling back to Ollama: {e}")

        # Default: Local Ollama
        try:
            result = await self._call_ollama(model, system_prompt, user_prompt, temperature, max_tokens)
            result["latency_ms"] = (time.time() - start) * 1000
            return result
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return {
                "content": "",
                "model_used": model,
                "latency_ms": (time.time() - start) * 1000,
                "tokens": 0,
                "error": str(e),
            }

    async def _call_ollama(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """Call Ollama's local API."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("message", {}).get("content", "")
        tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

        return {
            "content": content,
            "model_used": model,
            "tokens": tokens,
            "error": None,
        }

    async def _call_vertex(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """
        Call Vertex AI for cloud inference.
        Placeholder — requires google-cloud-aiplatform setup.
        """
        logger.info(f"Vertex AI call: {model} (placeholder)")
        # TODO: Wire up google-cloud-aiplatform or google-generativeai SDK
        # For now, fall through to Ollama via the fallback in generate()
        raise NotImplementedError("Vertex AI integration pending — using Ollama fallback")

    async def list_local_models(self) -> list[str]:
        """List models available in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []


model_router = ModelRouter()
