"""
rag.py: Hybrid Retrieval (FAISS + BM25) with Reciprocal Rank Fusion (RRF).
Per SOP Phase 3: "Implement RRF scoring (k=60) and τ=0.50 threshold filter."
"""

from __future__ import annotations

from typing import Any, Optional
from loguru import logger
import numpy as np

try:
    import faiss
    from sentence_transformers import SentenceTransformer
    from rank_bm25 import BM25Okapi
except ImportError:
    logger.warning("RAG dependencies missing. Install: faiss-cpu sentence-transformers rank-bm25")

class HybridRAG:
    def __init__(self, embedding_model: str = "all-MiniLM-L6-v2"):
        self._embedding_model_name = embedding_model
        self._model = None
        self._faiss_index = None
        self._bm25 = None
        self._documents: list[str] = []
        self._metadata: list[dict] = []
        self._initialized = False

    async def initialize(self):
        """Load embedding model and initialize indices."""
        try:
            self._model = SentenceTransformer(self._embedding_model_name)
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._faiss_index = faiss.IndexFlatIP(self._dimension)
            self._initialized = True
            logger.info(f"HybridRAG initialized with {self._embedding_model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize RAG: {e}")

    def add_documents(self, documents: list[str], metadata: Optional[list[dict]] = None):
        """Add documents to both FAISS and BM25."""
        if not self._initialized:
            return

        if not documents:
            return

        if metadata is None:
            metadata = [{} for _ in documents]

        # 1. Add to FAISS
        embeddings = self._model.encode(documents, convert_to_numpy=True)
        # Normalize for Inner Product -> Cosine Similarity
        faiss.normalize_L2(embeddings)
        self._faiss_index.add(embeddings)

        # 2. Add to BM25
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
        """Hybrid search combining FAISS and BM25 via RRF."""
        if not self._initialized or len(self._documents) == 0:
            return []

        # 1. FAISS Search
        query_embedding = self._model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)
        faiss_scores, faiss_indices = self._faiss_index.search(query_embedding, top_k)
        
        faiss_ranks = {}
        for rank, (score, idx) in enumerate(zip(faiss_scores[0], faiss_indices[0])):
            if idx != -1 and score >= threshold:
                faiss_ranks[int(idx)] = rank + 1

        # 2. BM25 Search
        tokenized_query = query.lower().split()
        bm25_scores = self._bm25.get_scores(tokenized_query)
        # Get top-k BM25 indices
        top_bm25_indices = np.argsort(bm25_scores)[::-1][:top_k]
        
        bm25_ranks = {}
        for rank, idx in enumerate(top_bm25_indices):
            if bm25_scores[idx] > 0:
                bm25_ranks[int(idx)] = rank + 1

        # 3. RRF Fusion
        rrf_scores = self._rrf(faiss_ranks, bm25_ranks, k=60)
        
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
