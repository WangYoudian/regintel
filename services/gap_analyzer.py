"""Gap analyzer — identifies compliance gaps from mapping results."""

from __future__ import annotations

import logging
from typing import Optional

from models.domain import GapAnalysis, MappingResult
from services.llm_client import LLMClient

logger = logging.getLogger(__name__)

GAP_ANALYSIS_PROMPT = """Analyze the compliance gap between a regulatory obligation 
and an existing internal control.

Regulatory obligation: {obligation}
Current control: {control}
Similarity score: {score}
Coverage status: {status}

Provide a JSON response with:
- gap_description: Brief description of what's missing or insufficient
- risk_impact: Potential regulatory or business impact of this gap
"""


class GapAnalyzer:
    """Analyze mapping results to identify compliance gaps."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def analyze(
        self, mappings: list[MappingResult], obligations: list = None
    ) -> list[GapAnalysis]:
        """Analyze mapping results and produce gap analyses."""
        gaps = []

        # Group mappings by obligation, take the best match for each
        best_by_obligation: dict[str, MappingResult] = {}
        for m in mappings:
            ob_id = m.obligation_id
            if (
                ob_id not in best_by_obligation
                or m.similarity_score > best_by_obligation[ob_id].similarity_score
            ):
                best_by_obligation[ob_id] = m

        for m in best_by_obligation.values():
            if m.coverage_status == "covered":
                continue

            gap = self._generate_gap(m)
            gaps.append(gap)

        logger.info(f"Generated {len(gaps)} gap analyses.")
        return gaps

    def _generate_gap(self, mapping: MappingResult) -> GapAnalysis:
        """Generate a gap analysis for a single mapping."""
        ob_text = mapping.obligation_id  # will be enriched with obligation text
        prompt = GAP_ANALYSIS_PROMPT.format(
            obligation=ob_text,
            control=mapping.control_name,
            score=mapping.similarity_score,
            status=mapping.coverage_status,
        )

        result = self.llm.chat_structured(
            [{"role": "user", "content": prompt}],
            response_model=_GapItem,
            max_retries=1,
        )

        return GapAnalysis(
            mapping_result_id=mapping.id,
            obligation_id=mapping.obligation_id,
            control_name=mapping.control_name,
            similarity_score=mapping.similarity_score,
            coverage_status=mapping.coverage_status,
            gap_description=result.gap_description if result else "See AI recommendation.",
            risk_impact=result.risk_impact if result else "",
        )


from pydantic import BaseModel


class _GapItem(BaseModel):
    gap_description: str = ""
    risk_impact: str = ""
