"""Report generator — converts AnalysisReport to download formats."""

from __future__ import annotations

import logging

from models.domain import AnalysisReport

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate downloadable reports from analysis results."""

    def generate(self, report: AnalysisReport, fmt: str = "markdown") -> str:
        """Generate a report in the specified format."""
        if fmt == "markdown":
            return report.to_markdown()
        else:
            logger.warning(f"Unsupported format: {fmt}, falling back to markdown.")
            return report.to_markdown()
