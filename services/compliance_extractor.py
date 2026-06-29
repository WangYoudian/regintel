"""Compliance obligation extractor — uses LLM to extract obligations."""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel

from config import settings
from models.domain import ComplianceObligation
from services.llm_client import LLMClient

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """You are a compliance analyst. Analyze the following regulatory document 
and extract all explicit compliance obligations (new or changed requirements).

For each obligation, provide:
- description: Clear description of what the firm must do
- source_ref: The exact section/article reference from the source document
- category: One of: Access Control, Data Protection, Reporting & Disclosure, 
  Risk Management, AML/KYC, Third Party Management, Operational Resilience, 
  Conduct & Culture
- risk_level: High if non-compliance could lead to regulatory sanctions, 
  Medium if it requires process changes, Low if it's informational

Return a JSON object with a single key "obligations" containing an array of objects.
Be thorough — extract ALL obligations, even implicit ones.
"""


class _ObligationItem(BaseModel):
    description: str = ""
    source_ref: str = ""
    category: str = ""
    risk_level: str = "Medium"


class _ObligationListWrapper(BaseModel):
    obligations: list[_ObligationItem] = []


class ComplianceExtractor:
    """Extract structured compliance obligations from regulation text."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    def extract(
        self, regulation_text: str, regulation_id: str = ""
    ) -> list[ComplianceObligation]:
        """Extract obligations from regulation text using LLM."""
        if not regulation_text.strip():
            logger.warning("Empty regulation text provided.")
            return []

        messages = [
            {"role": "user", "content": regulation_text[:15000]},
        ]

        result = self.llm.chat_structured(
            messages,
            response_model=_ObligationListWrapper,
            max_retries=2,
        )

        if result is None or not result.obligations:
            logger.warning("LLM returned no obligations, trying simpler prompt.")
            result = self._fallback_extract(regulation_text)

        obligations = []
        seen = set()
        for item in (result.obligations if result else []):
            dedup_key = item.description[:80].lower()
            if dedup_key not in seen:
                seen.add(dedup_key)
                obligations.append(
                    ComplianceObligation(
                        regulation_id=regulation_id,
                        description=item.description,
                        source_ref=item.source_ref,
                        category=item.category,
                        risk_level=item.risk_level,
                    )
                )

        logger.info(f"Extracted {len(obligations)} unique obligations.")
        return obligations

    def _fallback_extract(self, text: str) -> Optional[_ObligationListWrapper]:
        """Fallback: simpler prompt if structured extraction fails."""
        messages = [
            {
                "role": "user",
                "content": (
                    f"Extract all compliance obligations from this document. "
                    f"Return JSON with key 'obligations' as an array. "
                    f"Each item has: description, source_ref, category, risk_level.\n\n{text[:12000]}"
                ),
            }
        ]
        return self.llm.chat_structured(messages, _ObligationListWrapper, max_retries=1)
