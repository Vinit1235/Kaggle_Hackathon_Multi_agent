"""
router.py: Model Router — supports Google Gemini API (primary) and Ollama (local fallback).
Priority: Gemini API → Local Ollama.

Gemini free tier models:
  - gemini-2.0-flash (15 RPM, 1M tokens/day)
  - gemini-1.5-flash (15 RPM, 1M tokens/day)
  - gemini-2.5-flash (10 RPM)
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from loguru import logger

# ── Configuration ─────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" or "ollama"
COMPLEXITY_THRESHOLD = float(os.getenv("COMPLEXITY_THRESHOLD", "0.6"))

# Gemini model tiers
GEMINI_LIGHT_MODEL = os.getenv("GEMINI_LIGHT_MODEL", "gemini-2.0-flash")
GEMINI_HEAVY_MODEL = os.getenv("GEMINI_HEAVY_MODEL", "gemini-2.5-flash")

# Gemini API base URL
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class ModelRouter:
    """
    Routes LLM calls to the best available backend:
    1. Google Gemini API — PRIMARY (free tier, no credit card)
    2. Local Ollama — FALLBACK for local development
    """

    def __init__(self):
        self._ollama_available: Optional[bool] = None
        self._gemini_available: Optional[bool] = None

    async def check_proxy(self) -> bool:
        """Check if Gemini API is reachable (replaces old proxy check)."""
        return await self.check_gemini()

    async def check_gemini(self) -> bool:
        """Check if Gemini API key is set and working."""
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set. Gemini API disabled.")
            self._gemini_available = False
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GEMINI_API_BASE}/models?key={GEMINI_API_KEY}"
                )
                self._gemini_available = resp.status_code == 200
                if self._gemini_available:
                    data = resp.json()
                    model_names = [m.get("name", "") for m in data.get("models", [])[:5]]
                    logger.info(f"Gemini API available — sample models: {model_names}")
        except Exception as e:
            logger.warning(f"Gemini API check failed: {e}")
            self._gemini_available = False
        return self._gemini_available

    async def check_ollama(self) -> bool:
        """Check if Ollama is reachable (local dev fallback)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        logger.info(f"Ollama available: {self._ollama_available}")
        return self._ollama_available

    def _select_gemini_model(self, model: str, complexity: float) -> str:
        """
        Map a requested model name to a Gemini model based on complexity.
        If model is already a valid Gemini model, use it directly.
        """
        gemini_models = {
            "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash",
            "gemini-2.5-flash-lite", "gemini-1.5-pro",
        }
        if model in gemini_models:
            return model

        # Route by complexity
        if complexity > COMPLEXITY_THRESHOLD:
            return GEMINI_HEAVY_MODEL
        else:
            return GEMINI_LIGHT_MODEL

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

        # ── Semantic Caching ──
        full_prompt = f"{system_prompt}\n{user_prompt}"

        from memory import semantic_cache
        cached_result = await semantic_cache.search(full_prompt) if hasattr(semantic_cache, 'search') else None

        if cached_result:
            logger.info("Semantic cache HIT! Returning cached result.")
            cached_result["latency_ms"] = (time.time() - start) * 1000
            cached_result["model_used"] += " (cached)"
            return cached_result

        from rate_limiter import rate_limiter
        await rate_limiter.acquire_token()

        from security import security_shield

        # ── Primary: Gemini API ───────────────────────────────────────
        if self._gemini_available:
            gemini_model = self._select_gemini_model(model, complexity)
            try:
                result = await self._call_gemini(gemini_model, system_prompt, user_prompt, temperature, max_tokens)
                result["latency_ms"] = (time.time() - start) * 1000
                result["content"] = security_shield.sanitize_text(result.get("content", ""))
                if hasattr(semantic_cache, 'store'):
                    await semantic_cache.store(full_prompt, result)
                return result
            except Exception as e:
                logger.warning(f"Gemini call failed ({gemini_model}), trying Ollama: {e}")

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
            "content": "[ERROR: No LLM backend available. Set GEMINI_API_KEY or run Ollama locally.]",
            "model_used": model,
            "latency_ms": (time.time() - start) * 1000,
            "tokens": 0,
            "error": "No LLM backend available",
        }

    async def _call_gemini(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """Call Google Gemini API via REST (generateContent endpoint)."""
        url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "topP": 0.95,
            },
        }

        # Gemini supports systemInstruction for system prompts
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
            payload["contents"] = [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ]

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Parse Gemini response
        candidates = data.get("candidates", [])
        content = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        tokens = usage.get("totalTokenCount", 0)

        return {
            "content": content,
            "model_used": f"gemini:{model}",
            "tokens": tokens,
            "error": None,
        }

    async def _call_ollama(
        self, model: str, system_prompt: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        """Call Ollama's local API (fallback for local development)."""
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

    async def list_local_models(self) -> list[str]:
        """List available models from Gemini or Ollama."""
        models = []

        if self._gemini_available:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{GEMINI_API_BASE}/models?key={GEMINI_API_KEY}"
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
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
