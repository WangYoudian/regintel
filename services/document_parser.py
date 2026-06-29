"""Document parser — extracts text from PDF, DOCX, TXT files."""

import logging
import re
from pathlib import Path

from models.domain import Regulation

logger = logging.getLogger(__name__)


class DocumentParser:
    """Parse uploaded regulatory documents into structured text."""

    def parse(self, file_path: str) -> Regulation:
        """Parse a file and return a Regulation object."""
        path = Path(file_path)
        content = ""
        ext = path.suffix.lower()

        if ext == ".pdf":
            content = self._parse_pdf(path)
        elif ext == ".docx":
            content = self._parse_docx(path)
        elif ext in (".txt", ".md"):
            content = path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        title = path.stem.replace("_", " ").replace("-", " ").title()
        chunks = self._chunk_by_sections(content)

        return Regulation(
            title=title,
            content=content,
            file_path=file_path,
            summary=self._generate_summary(content, chunks),
        )

    def _parse_pdf(self, path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.error("PyMuPDF not installed, falling back to raw text.")
            return path.read_text(encoding="utf-8", errors="ignore")

        text_parts = []
        with fitz.open(path) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)

    def _parse_docx(self, path: Path) -> str:
        """Extract text from DOCX using python-docx."""
        try:
            from docx import Document
        except ImportError:
            logger.error("python-docx not installed, falling back.")
            return path.read_text(encoding="utf-8", errors="ignore")

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)

    def _chunk_by_sections(self, text: str) -> list[dict]:
        """Split text into sections by heading patterns."""
        heading_pattern = re.compile(r"^(#{1,3}\s|\d+\.\s|[A-Z][A-Z\s]{2,})", re.MULTILINE)
        chunks = []
        current = []
        current_heading = "preamble"

        for line in text.split("\n"):
            if heading_pattern.match(line):
                if current:
                    chunks.append({
                        "heading": current_heading.strip(),
                        "content": "\n".join(current).strip(),
                    })
                current_heading = line
                current = []
            else:
                current.append(line)

        if current:
            chunks.append({
                "heading": current_heading.strip(),
                "content": "\n".join(current).strip(),
            })

        return chunks

    def _generate_summary(self, content: str, chunks: list[dict]) -> str:
        """Generate a brief summary from the document structure."""
        total_words = len(content.split())
        num_sections = len(chunks)
        first_heading = chunks[0]["heading"] if chunks else "N/A"
        return (
            f"{num_sections} sections, ~{total_words} words. "
            f"Starts with: '{first_heading}'."
        )
