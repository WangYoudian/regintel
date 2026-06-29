"""Pydantic domain models — shared across all versions."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class Regulation(BaseModel):
    """An uploaded or sample regulatory document."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    source: str = ""  # FCA / PRA / MAS / RBI
    published_date: Optional[date] = None
    content: str = ""
    summary: str = ""
    file_path: str = ""


class ComplianceObligation(BaseModel):
    """A single compliance obligation extracted from a regulation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    regulation_id: str = ""
    description: str = ""
    source_ref: str = ""  # e.g. "Article 3.2", "Section 5(b)"
    category: str = ""  # Access Control / Data Protection / Reporting / etc.
    risk_level: str = "Medium"  # High / Medium / Low
    embedding: list[float] = Field(default_factory=list)


class InternalControl(BaseModel):
    """An internal control measure from the control library."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    category: str = ""
    frequency: str = ""  # Daily / Weekly / Monthly / Quarterly / Annually
    owner: str = ""
    status: str = "active"  # active / draft / deprecated
    embedding: list[float] = Field(default_factory=list)


class MappingResult(BaseModel):
    """Result of semantically matching an obligation against a control."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    obligation_id: str = ""
    control_id: str = ""
    control_name: str = ""
    similarity_score: float = 0.0
    coverage_status: str = "missing"  # covered / partial / missing


class GapAnalysis(BaseModel):
    """A compliance gap identified from a mapping result."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mapping_result_id: str = ""
    obligation_id: str = ""
    obligation_description: str = ""
    control_name: str = ""
    similarity_score: float = 0.0
    coverage_status: str = "missing"
    gap_description: str = ""
    risk_impact: str = ""


class Recommendation(BaseModel):
    """An AI-generated remediation recommendation for a gap."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gap_analysis_id: str = ""
    obligation_id: str = ""
    action_items: list[str] = Field(default_factory=list)
    priority: str = "Medium"  # High / Medium / Low
    estimated_effort: str = ""


class AnalysisReport(BaseModel):
    """Complete analysis result combining all steps."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    regulation: Regulation = Field(default_factory=Regulation)
    obligations: list[ComplianceObligation] = Field(default_factory=list)
    mappings: list[MappingResult] = Field(default_factory=list)
    gaps: list[GapAnalysis] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)

    def coverage_summary(self) -> dict:
        """Return coverage statistics."""
        total = len(self.mappings) or 1
        covered = sum(1 for m in self.mappings if m.coverage_status == "covered")
        partial = sum(1 for m in self.mappings if m.coverage_status == "partial")
        missing = sum(1 for m in self.mappings if m.coverage_status == "missing")
        return {
            "total_obligations": len(self.obligations),
            "covered": covered,
            "partial": partial,
            "missing": missing,
            "coverage_score": round(
                (covered + 0.5 * partial) / total * 100, 1
            ),
        }

    def to_markdown(self) -> str:
        """Render report as Markdown."""
        summary = self.coverage_summary()
        lines = [
            f"# RegIntel AI — Compliance Analysis Report",
            f"",
            f"**Regulation:** {self.regulation.title}",
            f"**Source:** {self.regulation.source}",
            f"**Date:** {self.generated_at.strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"## Executive Summary",
            f"",
            f"- Total obligations identified: {summary['total_obligations']}",
            f"- Fully covered: {summary['covered']}",
            f"- Partially covered: {summary['partial']}",
            f"- Not covered: {summary['missing']}",
            f"- Overall coverage score: {summary['coverage_score']}%",
            f"",
            f"## Gaps & Recommendations",
            f"",
        ]
        for gap in self.gaps:
            lines.append(f"### Gap: {gap.obligation_description[:80]}")
            lines.append(f"")
            lines.append(f"- **Obligation:** {gap.obligation_description}")
            lines.append(f"- **Current Control:** {gap.control_name}")
            lines.append(f"- **Similarity Score:** {gap.similarity_score:.2f}")
            lines.append(f"- **Status:** {gap.coverage_status}")
            lines.append(f"- **Gap Description:** {gap.gap_description}")
            lines.append(f"- **Risk Impact:** {gap.risk_impact}")
            lines.append(f"")
            for rec in self.recommendations:
                if rec.obligation_id == gap.obligation_id:
                    lines.append(f"**Recommendation (Priority: {rec.priority}):**")
                    for action in rec.action_items:
                        lines.append(f"- {action}")
                    lines.append(f"- Estimated effort: {rec.estimated_effort}")
                    lines.append(f"")
        return "\n".join(lines)
