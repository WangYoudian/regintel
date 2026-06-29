"""Pipeline orchestrator — coordinates all services for a complete analysis."""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from models.domain import (
    AnalysisReport,
    ComplianceObligation,
    InternalControl,
    Regulation,
)
from services.compliance_extractor import ComplianceExtractor
from services.document_parser import DocumentParser
from services.embedding_service import EmbeddingService
from services.gap_analyzer import GapAnalyzer
from services.llm_client import LLMClient
from services.matcher import SemanticMatcher
from services.recommendation_engine import RecommendationEngine
from services.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class RegIntelPipeline:
    """Orchestrate the full compliance analysis pipeline."""

    def __init__(self):
        self.llm = LLMClient()
        self.parser = DocumentParser()
        self.embedder = EmbeddingService()
        self.extractor = ComplianceExtractor(self.llm)
        self.matcher = SemanticMatcher(self.embedder)
        self.gap_analyzer = GapAnalyzer(self.llm)
        self.recommender = RecommendationEngine(self.llm)
        self.reporter = ReportGenerator()

        # In-memory control library for v1
        self._controls: list[InternalControl] = []

    @property
    def controls(self) -> list[InternalControl]:
        if not self._controls:
            self._controls = self._load_controls()
        return self._controls

    def _load_controls(self) -> list[InternalControl]:
        """Load internal controls from mock JSON."""
        import json
        from pathlib import Path

        path = Path(settings.mock_controls_path)
        if not path.exists():
            logger.warning(f"Controls file not found: {path}")
            return []

        with open(path) as f:
            data = json.load(f)

        controls = [InternalControl(**item) for item in data]
        logger.info(f"Loaded {len(controls)} internal controls.")

        # Pre-compute embeddings for all controls
        texts = [c.description for c in controls]
        embs = self.embedder.embed_batch(texts)
        for c, emb in zip(controls, embs):
            c.embedding = emb

        return controls

    def run(self, file_path: str) -> AnalysisReport:
        """Execute the full analysis pipeline."""
        logger.info(f"Starting analysis for: {file_path}")

        # 1. Parse document
        regulation = self.parser.parse(file_path)

        # 2. Extract compliance obligations
        obligations = self.extractor.extract(
            regulation.content, regulation_id=regulation.id
        )

        # 3. Embed obligations
        for ob in obligations:
            ob.embedding = self.embedder.embed(ob.description)

        # 4. Semantic matching
        mappings = self.matcher.match_all(obligations, self.controls)

        # 5. Gap analysis — pass obligation text map for LLM context
        ob_text_map = {o.id: o.description for o in obligations}
        gaps = self.gap_analyzer.analyze(mappings)

        # 6. Generate recommendations
        recommendations = self.recommender.generate(gaps, ob_text_map)

        # 7. Assemble report
        report = AnalysisReport(
            regulation=regulation,
            obligations=obligations,
            mappings=mappings,
            gaps=gaps,
            recommendations=recommendations,
        )

        logger.info(
            f"Analysis complete: {len(obligations)} obligations, "
            f"{len(mappings)} mappings, {len(gaps)} gaps, "
            f"{len(recommendations)} recommendations."
        )
        return report
