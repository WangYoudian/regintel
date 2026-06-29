"""Recommendation engine — generates AI-powered remediation suggestions."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

from models.domain import GapAnalysis, Recommendation
from services.llm_client import LLMClient

logger = logging.getLogger(__name__)

RECOMMEND_PROMPT = """You are a compliance remediation specialist.
Given a compliance gap, propose actionable remediation steps.

Obligation: {obligation}
Current control: {control}
Gap: {gap_description}
Risk: {risk_impact}

Return JSON with:
- action_items: array of 2-4 concrete, ordered action steps
- priority: High / Medium / Low
- estimated_effort: short description of time/resources needed
"""


class _RecommendationItem(BaseModel):
    action_items: list[str] = []
    priority: str = "Medium"
    estimated_effort: str = ""


class RecommendationEngine:
    """Generate remediation recommendations for compliance gaps."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def generate(
        self,
        gaps: list[GapAnalysis],
        obligation_texts: dict[str, str] = None,
    ) -> list[Recommendation]:
        """Generate recommendations for each gap."""
        obligation_texts = obligation_texts or {}
        recommendations = []

        for gap in gaps:
            ob_text = obligation_texts.get(gap.obligation_id, gap.obligation_id)
            prompt = RECOMMEND_PROMPT.format(
                obligation=ob_text,
                control=gap.control_name,
                gap_description=gap.gap_description,
                risk_impact=gap.risk_impact,
            )

            result = self.llm.chat_structured(
                [{"role": "user", "content": prompt}],
                response_model=_RecommendationItem,
                max_retries=1,
            )

            if result:
                recommendations.append(
                    Recommendation(
                        gap_analysis_id=gap.id,
                        obligation_id=gap.obligation_id,
                        action_items=result.action_items,
                        priority=result.priority,
                        estimated_effort=result.estimated_effort,
                    )
                )

        logger.info(f"Generated {len(recommendations)} recommendations.")
        return recommendations
