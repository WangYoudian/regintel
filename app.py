"""RegIntel AI — v1 Streamlit Prototype."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from config import settings
from models.domain import AnalysisReport
from services.pipeline import RegIntelPipeline

# ── Page config ──
st.set_page_config(
    page_title=settings.page_title,
    page_icon=settings.page_icon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load custom CSS ──
css_path = Path("styles/custom.css")
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


# ── Session state initialisation ──
if "pipeline" not in st.session_state:
    st.session_state.pipeline = RegIntelPipeline()
if "report" not in st.session_state:
    st.session_state.report = None
if "processing" not in st.session_state:
    st.session_state.processing = False
if "current_step" not in st.session_state:
    st.session_state.current_step = 0


# ── Helper functions ──

def run_analysis(file_path: str) -> AnalysisReport:
    """Execute the pipeline and return a report."""
    st.session_state.processing = True
    st.session_state.current_step = 0
    try:
        report = st.session_state.pipeline.run(file_path)
        st.session_state.report = report
        st.session_state.current_step = 6
        return report
    except Exception as e:
        st.error(f"Analysis failed: {e}")
        st.session_state.processing = False
        return None
    finally:
        st.session_state.processing = False


def load_sample():
    """Load the sample regulation and run analysis."""
    sample_path = settings.sample_regulation_path
    report = run_analysis(sample_path)
    return report


def load_uploaded_file(uploaded_file) -> str | None:
    """Save uploaded file to temp location and return path."""
    if uploaded_file is None:
        return None
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, dir="data/uploads"
    ) as tmp:
        tmp.write(uploaded_file.getvalue())
        return tmp.name


# ── Sidebar ──
with st.sidebar:
    st.markdown(f"# 🛡️ {settings.page_title}")
    st.markdown("**v1 Prototype** — Streamlit + Session State")
    st.divider()

    st.markdown("### 📄 Document")

    col1, col2 = st.columns(2)
    with col1:
        sample_btn = st.button(
            "📥 Load Sample", use_container_width=True, type="primary"
        )
    with col2:
        disabled = st.session_state.processing
        if st.button("🔄 Reset", use_container_width=True, disabled=disabled):
            st.session_state.report = None
            st.session_state.current_step = 0
            st.rerun()

    uploaded_file = st.file_uploader(
        "Or upload a PDF, DOCX or TXT file",
        type=["pdf", "docx", "txt", "md"],
        disabled=st.session_state.processing,
    )

    if uploaded_file is not None:
        file_path = load_uploaded_file(uploaded_file)
        if file_path and st.button(
            "▶️ Run Analysis", use_container_width=True, type="primary"
        ):
            run_analysis(file_path)

    if sample_btn:
        load_sample()

    st.divider()
    st.markdown("### 📊 Coverage Summary")
    if st.session_state.report:
        summary = st.session_state.report.coverage_summary()
        st.metric("Total Obligations", summary["total_obligations"])
        st.metric("✅ Covered", summary["covered"])
        st.metric("🟠 Partial", summary["partial"])
        st.metric("❌ Missing", summary["missing"])
        st.metric("Score", f"{summary['coverage_score']}%")

    st.divider()
    st.markdown("### ℹ️ About")
    st.markdown(
        "RegIntel AI uses GenAI + NLP to automate regulatory compliance analysis. "
        "Upload a regulatory document to identify obligations, map them to internal "
        "controls, and generate remediation recommendations."
    )


# ── Main area ──

st.markdown(
    "<h1 class='main-header'>RegIntel AI — Compliance Analysis</h1>",
    unsafe_allow_html=True,
)

report: AnalysisReport = st.session_state.report

if report is None:
    # ── Landing state ──
    st.markdown("### Welcome to RegIntel AI")
    st.markdown(
        "Upload a regulatory document or load the sample to get started. "
        "The system will automatically extract compliance obligations, "
        "match them against your internal controls, identify gaps, "
        "and generate remediation recommendations."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Step 1:** Upload or load a document")
        st.markdown("PDF, DOCX, TXT supported")
    with col2:
        st.markdown("**Step 2:** AI extracts obligations")
        st.markdown("LLM-powered analysis")
    with col3:
        st.markdown("**Step 3:** Review results & export")
        st.markdown("Dashboard with gap analysis")

    st.info(
        "💡 Click **📥 Load Sample** in the sidebar to try with "
        "a sample FCA Operational Resilience regulation.",
        icon="💡",
    )

elif st.session_state.processing:
    # ── Processing state ──
    st.markdown("### ⏳ Analysis in Progress")
    st.progress(0.5, text="Processing document...")
    st.markdown(
        "This may take 30-60 seconds depending on document length "
        "and LLM response time."
    )

else:
    # ── Results display ──
    summary = report.coverage_summary()

    # Dashboard row
    cols = st.columns(5)
    metrics = [
        ("Total", summary["total_obligations"], "🔍"),
        ("Covered", summary["covered"], "✅"),
        ("Partial", summary["partial"], "🟠"),
        ("Missing", summary["missing"], "❌"),
        ("Score", f"{summary['coverage_score']}%", "📊"),
    ]
    for col, (label, value, icon) in zip(cols, metrics):
        with col:
            st.markdown(
                f"<div class='kpi-card'>"
                f"<div class='kpi-value'>{icon} {value}</div>"
                f"<div class='kpi-label'>{label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Tabbed view ──
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Obligations", "🔗 Matching", "⚠️ Gaps & Recommendations", "📄 Report"]
    )

    with tab1:
        st.markdown("### Extracted Compliance Obligations")
        if report.obligations:
            for ob in report.obligations:
                risk_icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(
                    ob.risk_level, "⚪"
                )
                with st.expander(
                    f"{risk_icon} [{ob.category}] {ob.description[:100]}..."
                ):
                    st.markdown(f"**Source:** `{ob.source_ref}`")
                    st.markdown(f"**Category:** {ob.category}")
                    st.markdown(f"**Risk Level:** {ob.risk_level}")
                    st.markdown(f"**Full text:** {ob.description}")
        else:
            st.info("No obligations extracted.")

    with tab2:
        st.markdown("### Obligation × Control Matching Matrix")
        if report.mappings:
            rows = []
            for m in report.mappings:
                status_icon = {
                    "covered": "✅",
                    "partial": "🟠",
                    "missing": "❌",
                }.get(m.coverage_status, "⚪")
                rows.append(
                    {
                        "Status": f"{status_icon} {m.coverage_status.title()}",
                        "Obligation ID": m.obligation_id[:8],
                        "Matched Control": m.control_name,
                        "Similarity": f"{m.similarity_score:.2%}",
                    }
                )
            df = pd.DataFrame(rows)

            def color_status(val):
                if "Covered" in val:
                    return "background-color: #c8e6c9"
                elif "Partial" in val:
                    return "background-color: #ffe0b2"
                elif "Missing" in val:
                    return "background-color: #ffcdd2"
                return ""

            styled = df.style.applymap(color_status, subset=["Status"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
        else:
            st.info("No mapping results.")

    with tab3:
        st.markdown("### Gaps & Recommendations")
        if report.gaps:
            for gap in report.gaps:
                with st.container():
                    st.markdown(
                        f"<div class='gap-card'>"
                        f"<strong>⚠️ Gap</strong> — {gap.obligation_description[:100] if gap.obligation_description else 'See details'}"
                        f"<br/><em>Control:</em> {gap.control_name} "
                        f"| <em>Score:</em> {gap.similarity_score:.2%}"
                        f"| <em>Status:</em> {gap.coverage_status}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # Show recommendations for this gap
                    for rec in report.recommendations:
                        if rec.obligation_id == gap.obligation_id:
                            priority_icon = {
                                "High": "🔴",
                                "Medium": "🟡",
                                "Low": "🟢",
                            }.get(rec.priority, "⚪")
                            st.markdown(
                                f"<div class='rec-card'>"
                                f"<strong>{priority_icon} Recommendation "
                                f"({rec.priority})</strong>"
                                f"<br/><em>Effort:</em> {rec.estimated_effort}"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                            for action in rec.action_items:
                                st.markdown(f"- {action}")
                    st.divider()
        else:
            st.info("No gaps identified — all obligations are covered.")

    with tab4:
        st.markdown("### Compliance Analysis Report")
        st.markdown(f"**Regulation:** {report.regulation.title}")
        st.markdown(f"**Source:** {report.regulation.source}")
        st.markdown(f"**Summary:** {report.regulation.summary}")

        report_md = report.to_markdown()
        st.markdown(report_md)

        st.download_button(
            label="📥 Download Report (Markdown)",
            data=report_md,
            file_name=f"regintel_report_{report.regulation.title[:30]}.md".replace(
                " ", "_"
            ),
            mime="text/markdown",
            use_container_width=True,
        )
