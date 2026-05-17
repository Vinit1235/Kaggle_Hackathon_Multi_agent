"""
memory.py: Redis memX layer + FAISS semantic memory for the multi-agent system.
Handles real-time state sync (Redis pub/sub) and semantic caching.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from loguru import logger

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class MemXStateManager:
    """
    Redis-backed real-time state manager (memX).
    Falls back to in-memory dict if Redis is unavailable (per SOP troubleshooting).
    """

    def __init__(self):
        self._redis = None
        self._fallback_store: dict[str, str] = {}
        self._using_fallback = False
        self._pubsub = None

    async def connect(self) -> bool:
        """Attempt to connect to Redis. Fall back to in-memory if unavailable."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            await self._redis.ping()
            logger.info(f"Redis connected: {REDIS_URL}")
            return True
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}), using in-memory fallback")
            self._using_fallback = True
            return False

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def update_state(self, key: str, value: Any) -> None:
        """Update a key in the shared state (memX)."""
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if self._using_fallback:
            self._fallback_store[key] = serialized
        else:
            try:
                await self._redis.set(key, serialized)
                await self._redis.publish("memx_updates", json.dumps({"key": key, "value": value}))
            except Exception as e:
                logger.error(f"Redis write failed: {e}")
                self._fallback_store[key] = serialized

    async def read_state(self, key: str) -> Optional[Any]:
        """Read a key from shared state."""
        if self._using_fallback:
            raw = self._fallback_store.get(key)
        else:
            try:
                raw = await self._redis.get(key)
            except Exception:
                raw = self._fallback_store.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def delete_state(self, key: str) -> None:
        if self._using_fallback:
            self._fallback_store.pop(key, None)
        else:
            try:
                await self._redis.delete(key)
            except Exception:
                self._fallback_store.pop(key, None)

    async def get_session_state(self, session_id: str) -> dict:
        """Get all state keys for a specific session."""
        prefix = f"session:{session_id}:"
        if self._using_fallback:
            return {
                k.replace(prefix, ""): json.loads(v)
                for k, v in self._fallback_store.items()
                if k.startswith(prefix)
            }
        try:
            keys = []
            async for key in self._redis.scan_iter(match=f"{prefix}*"):
                keys.append(key)
            result = {}
            for key in keys:
                val = await self._redis.get(key)
                try:
                    result[key.replace(prefix, "")] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    result[key.replace(prefix, "")] = val
            return result
        except Exception:
            return {}

    @property
    def is_connected(self) -> bool:
        return not self._using_fallback


class SemanticCache:
    """
    FAISS-based semantic cache for deduplicating LLM calls.
    Per Execution Plan Phase 4: If similarity > 0.85, return cached output.
    """

    def __init__(self):
        self._index = None
        self._cache: dict[int, dict] = {}
        self._initialized = False
        self.similarity_threshold = 0.85

    async def initialize(self) -> bool:
        """Initialize FAISS index and embedding model. Returns False if unavailable."""
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._index = faiss.IndexFlatIP(self._dimension)
            self._initialized = True
            logger.info("Semantic cache initialized (FAISS + SentenceTransformer)")
            return True
        except ImportError:
            logger.warning("FAISS/SentenceTransformers not installed — semantic caching disabled")
            return False

    async def search(self, text: str) -> Optional[dict]:
        """Search cache for a similar prompt. Returns cached result or None."""
        if not self._initialized or self._index.ntotal == 0:
            return None
        try:
            import faiss
            import numpy as np
            embedding = self._model.encode([text], convert_to_numpy=True)
            faiss.normalize_L2(embedding)
            scores, indices = self._index.search(embedding, 1)
            if scores[0][0] >= self.similarity_threshold:
                idx = int(indices[0][0])
                return self._cache.get(idx)
        except Exception as e:
            logger.error(f"Semantic cache search failed: {e}")
        return None

    async def store(self, text: str, result: dict) -> None:
        """Store a new text prompt + result in the cache."""
        if not self._initialized:
            return
        try:
            import faiss
            import numpy as np
            embedding = self._model.encode([text], convert_to_numpy=True)
            faiss.normalize_L2(embedding)
            idx = self._index.ntotal
            self._index.add(embedding)
            self._cache[idx] = result
        except Exception as e:
            logger.error(f"Semantic cache store failed: {e}")


memx = MemXStateManager()
semantic_cache = SemanticCache()
