"""Application configuration."""

import os
from dataclasses import dataclass, field


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


settings = Settings()
