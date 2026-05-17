"""
router.py: Model Router — supports Antigravity Proxy (OpenAI-compatible), Ollama, and Vertex AI.
Priority: Antigravity Proxy → Local Ollama → Vertex AI (cloud).

Antigravity proxy at localhost:8080 gives access to:
  - gemini-3-flash, gemini-2.5-flash, gemini-2.5-flash-lite
  - claude-opus-4-6-thinking, claude-sonnet-4-6
  - gemini-3-1-flash-lite, gemini-2.5-flash-thinking
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from loguru import logger

# ── Configuration ─────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
PROXY_BASE_URL = os.getenv("ANTIGRAVITY_PROXY_URL", "http://localhost:8080")
PROXY_AUTH_TOKEN = os.getenv("ANTHROPIC_AUTH_TOKEN", "test")
COMPLEXITY_THRESHOLD = float(os.getenv("COMPLEXITY_THRESHOLD", "0.6"))

# Default models via proxy
PROXY_LIGHT_MODEL = os.getenv("PROXY_LIGHT_MODEL", "gemini-2.5-flash-lite")   # cheap & fast
PROXY_MEDIUM_MODEL = os.getenv("PROXY_MEDIUM_MODEL", "gemini-3-flash")         # balanced
PROXY_HEAVY_MODEL = os.getenv("PROXY_HEAVY_MODEL", "claude-opus-4-6-thinking") # heavy reasoning


class ModelRouter:
    """
    Routes LLM calls to the best available backend:
    1. Antigravity Proxy (OpenAI-compatible, localhost:8080) — PRIMARY
    2. Local Ollama — FALLBACK if proxy unavailable
    3. Vertex AI — FUTURE (placeholder)
    """

    def __init__(self):
        self._ollama_available: Optional[bool] = None
        self._proxy_available: Optional[bool] = None
        self._vertex_available: Optional[bool] = None

    async def check_proxy(self) -> bool:
        """Check if Antigravity proxy is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{PROXY_BASE_URL}/v1/models",
                    headers={"Authorization": f"Bearer {PROXY_AUTH_TOKEN}"},
                )
                self._proxy_available = resp.status_code == 200
                if self._proxy_available:
                    data = resp.json()
                    model_ids = [m["id"] for m in data.get("data", [])]
                    logger.info(f"Proxy available — {len(model_ids)} models: {model_ids[:5]}")
        except Exception as e:
            logger.warning(f"Proxy not reachable: {e}")
            self._proxy_available = False
        return self._proxy_available

    async def check_ollama(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        logger.info(f"Ollama available: {self._ollama_available}")
        return self._ollama_available

    def _select_proxy_model(self, model: str, complexity: float) -> str:
        """
        Map a requested model name to an available proxy model.
        If the model looks like an Ollama model (e.g. gemma4:e2b), remap to a proxy equivalent.
        """
        # If it's already a proxy-native model, use it directly
        proxy_models = {
            "gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite",
            "gemini-2.5-flash-thinking", "gemini-3-1-flash-lite", "gemini-3-1-pro",
            "claude-opus-4-6-thinking", "claude-sonnet-4-6",
        }
        if model in proxy_models:
            return model

        # Remap Ollama/Gemma models → proxy equivalents by complexity
        if complexity > COMPLEXITY_THRESHOLD:
            return PROXY_HEAVY_MODEL
        elif complexity > 0.3:
            return PROXY_MEDIUM_MODEL
        else:
            return PROXY_LIGHT_MODEL

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
        Route a generation request to the best available backend.
        Uses Semantic Caching to avoid duplicate LLM calls.
        """
        start = time.time()
        
        # ── Phase 4: Semantic Caching ──
        # Build embedding for the prompt (we use a simple string combination for now, 
        # in a real setup we'd generate an actual vector embedding)
        # Note: Since the real model generates an embedding, we simulate it or use 
        # the simple string-based cache search structure.
        # Actually, let's just use the exact prompt string for now if embedding isn't loaded.
        full_prompt = f"{system_prompt}\n{user_prompt}"
        
        from memory import semantic_cache
        # If semantic cache is fully initialized with sentence-transformers we'd use it:
        # But we can also use a simple exact-match cache as fallback if it's not.
        cached_result = await semantic_cache.search(full_prompt) if hasattr(semantic_cache, 'search') else None
        
        if cached_result:
            logger.info("Semantic cache HIT! Returning cached result.")
            cached_result["latency_ms"] = (time.time() - start) * 1000
            cached_result["model_used"] += " (cached)"
            return cached_result
            
        from rate_limiter import rate_limiter
        await rate_limiter.acquire_token()

        from security import security_shield

        # ── Primary: Antigravity Proxy ─────────────────────────────────
        if self._proxy_available:
            proxy_model = self._select_proxy_model(model, complexity)
            try:
                result = await self._call_proxy(proxy_model, system_prompt, user_prompt, temperature, max_tokens)
                result["latency_ms"] = (time.time() - start) * 1000
                result["content"] = security_shield.sanitize_text(result.get("content", ""))
                if hasattr(semantic_cache, 'store'):
                    await semantic_cache.store(full_prompt, result)
                return result
            except Exception as e:
                logger.warning(f"Proxy call failed ({proxy_model}), trying Ollama: {e}")

        # ── Fallback: Local Ollama ─────────────────────────────────────
        if self._ollama_available:
            try:
                result = await self._call_ollama(model, system_prompt, user_prompt, temperature, max_tokens)
                result["latency_ms"] = (time.time() - start) * 1000
                result["content"] = security_shield.sanitize_text(result.get("content", ""))
                if hasattr(semantic_cache, 'store'):
                    await semantic_cache.store(full_prompt, result)
                return result
            except Exception as e:
                logger.error(f"Ollama call failed: {e}")

        # ── Final fallback: error ──────────────────────────────────────
        logger.error("No LLM backend available!")
        return {
            "content": "[ERROR: No LLM backend available. Ensure proxy (localhost:8080) or Ollama is running.]",
            "model_used": model,
            "latency_ms": (time.time() - start) * 1000,
            "tokens": 0,
            "error": "No LLM backend available",
        }

    async def _call_proxy(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """Call the Antigravity proxy (OpenAI-compatible /v1/chat/completions)."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{PROXY_BASE_URL}/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {PROXY_AUTH_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)

        return {
            "content": content,
            "model_used": f"proxy:{model}",
            "tokens": tokens,
            "error": None,
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
            "model_used": f"ollama:{model}",
            "tokens": tokens,
            "error": None,
        }

    async def _call_vertex(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """Call Vertex AI — placeholder for future integration."""
        logger.info(f"Vertex AI call: {model} (not yet implemented)")
        raise NotImplementedError("Vertex AI integration pending")

    async def list_local_models(self) -> list[str]:
        """List models available — from proxy first, then Ollama."""
        models = []

        if self._proxy_available:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{PROXY_BASE_URL}/v1/models",
                        headers={"Authorization": f"Bearer {PROXY_AUTH_TOKEN}"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        models = [m["id"] for m in data.get("data", [])]
                        return models
            except Exception:
                pass

        if self._ollama_available:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        return [m["name"] for m in data.get("models", [])]
            except Exception:
                pass

        return models


model_router = ModelRouter()
