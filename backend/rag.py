"""
rag.py: Hybrid Retrieval (Pinecone + BM25) with Reciprocal Rank Fusion (RRF).
Per SOP Phase 3: "Implement RRF scoring (k=60) and τ=0.50 threshold filter."

Supports Pinecone (cloud) with local FAISS fallback.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from loguru import logger
import numpy as np

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_RAG_INDEX = os.getenv("PINECONE_RAG_INDEX", "agency-rag")

try:
    from sentence_transformers import SentenceTransformer
    from rank_bm25 import BM25Okapi
except ImportError:
    logger.warning("RAG dependencies missing. Install: sentence-transformers rank-bm25")

class HybridRAG:
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        self._embedding_model_name = embedding_model
        self._model = None
        self._pinecone_index = None
        self._faiss_index = None
        self._bm25 = None
        self._documents: list[str] = []
        self._metadata: list[dict] = []
        self._initialized = False
        self._use_pinecone = False

    async def initialize(self):
        """Load embedding model and initialize vector index (Pinecone or FAISS)."""
        try:
            self._model = SentenceTransformer(self._embedding_model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()

            # Try Pinecone first
            if PINECONE_API_KEY:
                try:
                    from pinecone import Pinecone
                    pc = Pinecone(api_key=PINECONE_API_KEY)
                    self._pinecone_index = pc.Index(PINECONE_RAG_INDEX)
                    self._use_pinecone = True
                    logger.info(f"HybridRAG initialized with Pinecone: {PINECONE_RAG_INDEX}")
                except Exception as e:
                    logger.warning(f"Pinecone RAG init failed ({e}), using local FAISS")

            # Fallback to FAISS
            if not self._use_pinecone:
                try:
                    import faiss
                    self._faiss_index = faiss.IndexFlatIP(self._dimension)
                    logger.info(f"HybridRAG initialized with local FAISS")
                except ImportError:
                    logger.warning("FAISS not available, vector search disabled")

            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize RAG: {e}")

    def add_documents(self, documents: list[str], metadata: Optional[list[dict]] = None):
        """Add documents to vector index and BM25."""
        if not self._initialized:
            return

        if not documents:
            return

        if metadata is None:
            metadata = [{} for _ in documents]

        # Add to vector index
        embeddings = self._model.encode(documents, convert_to_numpy=True)

        if self._use_pinecone:
            import hashlib
            vectors = []
            for i, (doc, emb, meta) in enumerate(zip(documents, embeddings, metadata)):
                vec_id = hashlib.md5(doc.encode()).hexdigest()
                vectors.append({
                    "id": vec_id,
                    "values": emb.tolist(),
                    "metadata": {**meta, "content": doc[:3000]}
                })
            # Upsert in batches
            for i in range(0, len(vectors), 100):
                self._pinecone_index.upsert(vectors=vectors[i:i+100])
        elif self._faiss_index is not None:
            import faiss
            faiss.normalize_L2(embeddings)
            self._faiss_index.add(embeddings)

        # Add to BM25
        self._documents.extend(documents)
        self._metadata.extend(metadata)

        tokenized_docs = [doc.lower().split() for doc in self._documents]
        self._bm25 = BM25Okapi(tokenized_docs)
        logger.info(f"Added {len(documents)} documents to HybridRAG. Total: {len(self._documents)}")

    def _rrf(self, faiss_ranks: dict[int, float], bm25_ranks: dict[int, float], k: int = 60) -> dict[int, float]:
        """Compute Reciprocal Rank Fusion (RRF) scores."""
        rrf_scores = {}
        all_indices = set(faiss_ranks.keys()).union(set(bm25_ranks.keys()))

        for idx in all_indices:
            score = 0.0
            if idx in faiss_ranks:
                rank = faiss_ranks[idx]
                score += 1.0 / (k + rank)
            if idx in bm25_ranks:
                rank = bm25_ranks[idx]
                score += 1.0 / (k + rank)
            rrf_scores[idx] = score

        return rrf_scores

    def search(self, query: str, top_k: int = 5, threshold: float = 0.50) -> list[dict]:
        """Hybrid search combining vector search and BM25 via RRF."""
        if not self._initialized or len(self._documents) == 0:
            return []

        # 1. Vector Search (Pinecone or FAISS)
        query_embedding = self._model.encode([query], convert_to_numpy=True)

        vector_ranks = {}
        if self._use_pinecone:
            results = self._pinecone_index.query(
                vector=query_embedding[0].tolist(),
                top_k=top_k,
                include_metadata=True,
            )
            for rank, match in enumerate(results.matches):
                if match.score >= threshold:
                    # Find document index by content
                    content = match.metadata.get("content", "")
                    for i, doc in enumerate(self._documents):
                        if doc[:100] == content[:100]:
                            vector_ranks[i] = rank + 1
                            break
        elif self._faiss_index is not None:
            import faiss
            faiss.normalize_L2(query_embedding)
            scores, indices = self._faiss_index.search(query_embedding, top_k)
            for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx != -1 and score >= threshold:
                    vector_ranks[int(idx)] = rank + 1

        # 2. BM25 Search
        if self._bm25 is None:
            bm25_ranks = {}
        else:
            tokenized_query = query.lower().split()
            bm25_scores = self._bm25.get_scores(tokenized_query)
            top_bm25_indices = np.argsort(bm25_scores)[::-1][:top_k]
            bm25_ranks = {}
            for rank, idx in enumerate(top_bm25_indices):
                if bm25_scores[idx] > 0:
                    bm25_ranks[int(idx)] = rank + 1

        # 3. RRF Fusion
        rrf_scores = self._rrf(vector_ranks, bm25_ranks, k=60)

        # Sort by RRF score descending
        sorted_indices = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in sorted_indices[:top_k]:
            results.append({
                "content": self._documents[idx],
                "metadata": self._metadata[idx],
                "score": score
            })

        return results

rag_engine = HybridRAG()
