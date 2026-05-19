"""
memory.py: Redis memX layer + Pinecone semantic memory for the multi-agent system.
Handles real-time state sync (Redis/Upstash) and semantic caching (Pinecone).
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from loguru import logger

# ── Redis Configuration ──────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "")
UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# ── Pinecone Configuration ───────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "agency-rag")


class MemXStateManager:
    """
    Redis-backed real-time state manager (memX).
    Supports: standard Redis URL, Upstash REST API, or in-memory fallback.
    """

    def __init__(self):
        self._redis = None
        self._upstash_client = None
        self._fallback_store: dict[str, str] = {}
        self._using_fallback = False

    async def connect(self) -> bool:
        """Attempt to connect to Redis. Fall back to in-memory if unavailable."""
        # Try Upstash REST first (preferred for serverless/cloud)
        if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN:
            try:
                from upstash_redis import Redis as UpstashRedis
                self._upstash_client = UpstashRedis(
                    url=UPSTASH_REDIS_REST_URL,
                    token=UPSTASH_REDIS_REST_TOKEN,
                )
                # Test connection
                self._upstash_client.ping()
                logger.info(f"Upstash Redis connected: {UPSTASH_REDIS_REST_URL[:30]}...")
                return True
            except Exception as e:
                logger.warning(f"Upstash Redis failed ({e}), trying standard Redis...")

        # Try standard Redis URL
        if REDIS_URL:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
                await self._redis.ping()
                logger.info(f"Redis connected: {REDIS_URL}")
                return True
            except Exception as e:
                logger.warning(f"Redis unavailable ({e}), using in-memory fallback")

        logger.warning("No Redis configured, using in-memory fallback")
        self._using_fallback = True
        return False

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None
        # Upstash REST client doesn't need explicit close

    async def update_state(self, key: str, value: Any) -> None:
        """Update a key in the shared state (memX)."""
        serialized = json.dumps(value) if not isinstance(value, str) else value

        # Upstash REST
        if self._upstash_client:
            try:
                self._upstash_client.set(key, serialized)
                return
            except Exception as e:
                logger.error(f"Upstash write failed: {e}")
                self._fallback_store[key] = serialized
                return

        # Standard Redis
        if self._redis and not self._using_fallback:
            try:
                await self._redis.set(key, serialized)
                await self._redis.publish("memx_updates", json.dumps({"key": key, "value": value}))
                return
            except Exception as e:
                logger.error(f"Redis write failed: {e}")
                self._fallback_store[key] = serialized
                return

        # Fallback
        self._fallback_store[key] = serialized

    async def read_state(self, key: str) -> Optional[Any]:
        """Read a key from shared state."""
        raw = None

        # Upstash REST
        if self._upstash_client:
            try:
                raw = self._upstash_client.get(key)
            except Exception:
                raw = self._fallback_store.get(key)
        # Standard Redis
        elif self._redis and not self._using_fallback:
            try:
                raw = await self._redis.get(key)
            except Exception:
                raw = self._fallback_store.get(key)
        else:
            raw = self._fallback_store.get(key)

        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def delete_state(self, key: str) -> None:
        if self._upstash_client:
            try:
                self._upstash_client.delete(key)
                return
            except Exception:
                pass
        if self._redis and not self._using_fallback:
            try:
                await self._redis.delete(key)
                return
            except Exception:
                pass
        self._fallback_store.pop(key, None)

    async def get_session_state(self, session_id: str) -> dict:
        """Get all state keys for a specific session."""
        prefix = f"session:{session_id}:"

        # Upstash REST — use SCAN
        if self._upstash_client:
            try:
                # Upstash REST scan
                keys = []
                cursor = 0
                while True:
                    cursor, batch = self._upstash_client.scan(cursor, match=f"{prefix}*", count=100)
                    keys.extend(batch)
                    if cursor == 0:
                        break

                result = {}
                for key in keys:
                    val = self._upstash_client.get(key)
                    try:
                        result[key.replace(prefix, "")] = json.loads(val) if val else None
                    except (json.JSONDecodeError, TypeError):
                        result[key.replace(prefix, "")] = val
                return result
            except Exception:
                return {}

        # Standard Redis
        if self._redis and not self._using_fallback:
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

        # Fallback
        return {
            k.replace(prefix, ""): json.loads(v)
            for k, v in self._fallback_store.items()
            if k.startswith(prefix)
        }

    @property
    def is_connected(self) -> bool:
        return bool(self._upstash_client or (self._redis and not self._using_fallback))


class SemanticCache:
    """
    Pinecone-based semantic cache for deduplicating LLM calls.
    Falls back to local FAISS if Pinecone is unavailable.
    Per Execution Plan Phase 4: If similarity > 0.85, return cached output.
    """

    def __init__(self):
        self._pinecone_index = None
        self._local_index = None
        self._model = None
        self._cache: dict[str, dict] = {}  # id -> result
        self._initialized = False
        self._use_pinecone = False
        self.similarity_threshold = 0.999

    async def initialize(self) -> bool:
        """Initialize Pinecone or fall back to FAISS."""
        # Try Pinecone first
        if PINECONE_API_KEY:
            try:
                from pinecone import Pinecone
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer("all-MiniLM-L6-v2")
                pc = Pinecone(api_key=PINECONE_API_KEY)

                # Check if index exists, create if not
                existing = [idx.name for idx in pc.list_indexes()]
                if PINECONE_INDEX_NAME not in existing:
                    from pinecone import ServerlessSpec
                    pc.create_index(
                        name=PINECONE_INDEX_NAME,
                        dimension=384,  # all-MiniLM-L6-v2 dimension
                        metric="cosine",
                        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                    )
                    logger.info(f"Created Pinecone index: {PINECONE_INDEX_NAME}")

                self._pinecone_index = pc.Index(PINECONE_INDEX_NAME)
                self._use_pinecone = True
                self._initialized = True
                logger.info(f"Semantic cache initialized (Pinecone: {PINECONE_INDEX_NAME})")
                return True
            except Exception as e:
                logger.warning(f"Pinecone init failed ({e}), trying local FAISS...")

        # Fallback to local FAISS
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._local_index = faiss.IndexFlatIP(self._dimension)
            self._local_cache: dict[int, dict] = {}
            self._initialized = True
            logger.info("Semantic cache initialized (local FAISS fallback)")
            return True
        except ImportError:
            logger.warning("FAISS/SentenceTransformers not installed — semantic caching disabled")
            return False

    async def search(self, text: str) -> Optional[dict]:
        """Search cache for a similar prompt. Returns cached result or None."""
        return None # TEMPORARILY DISABLED due to embedding truncation issue
        if not self._initialized:
            return None

        try:
            import numpy as np
            embedding = self._model.encode([text], convert_to_numpy=True)

            if self._use_pinecone:
                results = self._pinecone_index.query(
                    vector=embedding[0].tolist(),
                    top_k=1,
                    include_metadata=True,
                )
                if results.matches and results.matches[0].score >= self.similarity_threshold:
                    match_id = results.matches[0].id
                    metadata = results.matches[0].metadata
                    return {
                        "content": metadata.get("content", ""),
                        "model_used": metadata.get("model_used", ""),
                        "tokens": int(metadata.get("tokens", 0)),
                        "error": None,
                    }
            else:
                # Local FAISS
                if self._local_index.ntotal == 0:
                    return None
                import faiss
                faiss.normalize_L2(embedding)
                scores, indices = self._local_index.search(embedding, 1)
                if scores[0][0] >= self.similarity_threshold:
                    idx = int(indices[0][0])
                    return self._local_cache.get(idx)

        except Exception as e:
            logger.error(f"Semantic cache search failed: {e}")
        return None

    async def store(self, text: str, result: dict) -> None:
        """Store a new text prompt + result in the cache."""
        if not self._initialized:
            return

        try:
            import numpy as np
            import hashlib
            embedding = self._model.encode([text], convert_to_numpy=True)

            if self._use_pinecone:
                vec_id = hashlib.md5(text.encode()).hexdigest()
                self._pinecone_index.upsert(vectors=[{
                    "id": vec_id,
                    "values": embedding[0].tolist(),
                    "metadata": {
                        "content": (result.get("content", ""))[:3000],  # Pinecone metadata limit
                        "model_used": result.get("model_used", ""),
                        "tokens": result.get("tokens", 0),
                    }
                }])
            else:
                # Local FAISS
                import faiss
                faiss.normalize_L2(embedding)
                idx = self._local_index.ntotal
                self._local_index.add(embedding)
                self._local_cache[idx] = result

        except Exception as e:
            logger.error(f"Semantic cache store failed: {e}")


memx = MemXStateManager()
semantic_cache = SemanticCache()
