"""Semantic matcher — uses cosine similarity to match obligations to controls."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from config import settings
from models.domain import ComplianceObligation, InternalControl, MappingResult
from services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class SemanticMatcher:
    """Match compliance obligations to internal controls via embedding similarity."""

    def __init__(self, embedder: Optional[EmbeddingService] = None):
        self.embedder = embedder or EmbeddingService()

    def match_all(
        self,
        obligations: list[ComplianceObligation],
        controls: list[InternalControl],
    ) -> list[MappingResult]:
        """Match all obligations against all controls."""
        if not obligations or not controls:
            logger.warning(
                f"Empty input: {len(obligations)} obligations, "
                f"{len(controls)} controls"
            )
            return []

        ob_texts = [o.description for o in obligations]
        ctrl_texts = [c.description for c in controls]

        ob_embs = self.embedder.embed_batch(ob_texts)
        ctrl_embs = self.embedder.embed_batch(ctrl_texts)

        valid_ob = [(i, e) for i, e in enumerate(ob_embs) if e]
        valid_ctrl = [(i, e) for i, e in enumerate(ctrl_embs) if e]

        if not valid_ob or not valid_ctrl:
            logger.error("Failed to generate embeddings.")
            return []

        ob_indices, ob_vectors = zip(*valid_ob)
        ctrl_indices, ctrl_vectors = zip(*valid_ctrl)

        sim_matrix = cosine_similarity(
            np.array(ob_vectors), np.array(ctrl_vectors)
        )

        results = []
        threshold_covered = settings.match_threshold_covered
        threshold_partial = settings.match_threshold_partial
        top_k = settings.match_top_k

        for ob_idx_in_batch, ob_orig_idx in enumerate(ob_indices):
            obligation = obligations[ob_orig_idx]
            scores = sim_matrix[ob_idx_in_batch]

            # Get top-k control indices
            top_indices = np.argsort(scores)[::-1][:top_k]

            for ctrl_idx_in_batch in top_indices:
                ctrl_orig_idx = ctrl_indices[ctrl_idx_in_batch]
                control = controls[ctrl_orig_idx]
                score = float(scores[ctrl_idx_in_batch])

                if score >= threshold_covered:
                    status = "covered"
                elif score >= threshold_partial:
                    status = "partial"
                else:
                    status = "missing"

                results.append(
                    MappingResult(
                        obligation_id=obligation.id,
                        control_id=control.id,
                        control_name=control.name,
                        similarity_score=round(score, 4),
                        coverage_status=status,
                    )
                )

        logger.info(f"Generated {len(results)} mapping results.")
        return results
