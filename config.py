"""Application configuration."""

import os
import sys
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    llm_api_endpoint: str = os.getenv(
        "LLM_API_ENDPOINT", "https://api.openai.com/v1"
    )
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o")

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_method: str = os.getenv("EMBEDDING_METHOD", "tfidf")

    # Matching thresholds
    match_threshold_covered: float = 0.85
    match_threshold_partial: float = 0.65
    match_top_k: int = 3

    # Data paths
    mock_controls_path: str = "data/mock/internal_controls.json"
    sample_regulation_path: str = "data/mock/sample_regulation.md"

    # Streamlit
    page_title: str = "RegIntel AI"
    page_icon: str = "🛡️"

    def validate(self):
        """Check critical config and warn on issues."""
        if not self.llm_api_key:
            logger.warning(
                "LLM_API_KEY is not set. "
                "Compliance extraction, gap analysis, and recommendation "
                "features will fail at runtime. "
                "Set the LLM_API_KEY environment variable or edit config.py."
            )
            print(
                "⚠️  WARNING: LLM_API_KEY not configured.\n"
                "   Set it via environment variable or edit config.py.\n"
                "   Without it, LLM-dependent features (extraction, "
                "gap analysis, recommendations) will not work.",
                file=sys.stderr,
            )


settings = Settings()
settings.validate()
