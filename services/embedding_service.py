"""Embedding service — generates text embeddings with multiple backends.

Priority:
  1. Internal LLM API (configurable via LLMClient)
  2. sentence-transformers (best quality, needs PyTorch)
  3. sklearn TfidfVectorizer (lightweight, always works — default for v1)
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate embedding vectors from text."""

    def __init__(self, method: str = ""):
        self.method = method or "tfidf"  # tfidf | sbert | api
        self._sbert_model = None
        self._tfidf_vectorizer = None
        self._tfidf_fitted = False

    # ── Public API ──

    def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        if not text.strip():
            return []

        if self.method == "sbert":
            return self._embed_sbert(text)
        elif self.method == "api":
            return self._embed_api(text)
        else:
            return self._embed_tfidf([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts efficiently."""
        valid = [t for t in texts if t.strip()]
        if not valid:
            return [[] for _ in texts]

        if self.method == "sbert":
            return self._embed_sbert_batch(texts)
        elif self.method == "api":
            return [self._embed_api(t) for t in texts]
        else:
            return self._embed_tfidf(texts)

    # ── Backend: TfidfVectorizer (default, no extra deps) ──

    def _embed_tfidf(self, texts: list[str]) -> list[list[float]]:
        """TF-IDF weighted average word vectors — lightweight, deterministic."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        import numpy as np

        if not self._tfidf_fitted:
            self._tfidf_vectorizer = TfidfVectorizer(
                max_features=384,
                stop_words="english",
                sublinear_tf=True,
            )
            # Fit on a small seed corpus + the input texts
            seed = [
                "access control review privileged user quarterly",
                "data encryption protection privacy pii",
                "regulatory reporting disclosure compliance",
                "risk management assessment monitoring",
                "aml kyc customer due diligence sanctions",
                "third party vendor supplier assessment",
                "operational resilience business continuity disaster recovery",
                "conduct culture trading surveillance conflicts of interest",
            ]
            self._tfidf_vectorizer.fit(seed + texts)
            self._tfidf_fitted = True
        else:
            # Transform only when already fitted
            pass

        try:
            X = self._tfidf_vectorizer.transform(texts)
            dense = X.toarray()
            # L2 normalize
            norms = np.linalg.norm(dense, axis=1, keepdims=True)
            norms[norms == 0] = 1
            dense = dense / norms
            return dense.tolist()
        except Exception as e:
            logger.error(f"TF-IDF embedding failed: {e}")
            return [[] for _ in texts]

    # ── Backend: sentence-transformers (better quality, needs torch) ──

    def _load_sbert(self):
        if self._sbert_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading SBERT model: {settings.embedding_model}")
                self._sbert_model = SentenceTransformer(settings.embedding_model)
            except ImportError:
                logger.warning(
                    "sentence-transformers not installed; "
                    "use 'pip install sentence-transformers' to enable."
                )
                self._sbert_model = False  # sentinel

    def _embed_sbert(self, text: str) -> list[float]:
        self._load_sbert()
        if not self._sbert_model:
            return self._embed_tfidf([text])[0]
        try:
            vec = self._sbert_model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.error(f"SBERT failed: {e}, falling back to TF-IDF")
            return self._embed_tfidf([text])[0]

    def _embed_sbert_batch(self, texts: list[str]) -> list[list[float]]:
        self._load_sbert()
        if not self._sbert_model:
            return self._embed_tfidf(texts)
        try:
            vecs = self._sbert_model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )
            return vecs.tolist()
        except Exception as e:
            logger.error(f"SBERT batch failed: {e}, falling back to TF-IDF")
            return self._embed_tfidf(texts)

    # ── Backend: Internal LLM API (future) ──

    def _embed_api(self, text: str) -> list[float]:
        from services.llm_client import LLMClient
        llm = LLMClient()
        result = llm.embed(text)
        if result:
            return result
        logger.warning("LLM API embedding unavailable, using TF-IDF fallback")
        return self._embed_tfidf([text])[0]
