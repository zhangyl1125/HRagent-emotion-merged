from __future__ import annotations

from pathlib import Path

from backend.exceptions.parser_errors import UnsupportedFileTypeError


class FileExtractor:
    """Native text reader kept for explicit text files only."""

    supported_text_extensions = {".txt", ".md"}

    def extract_text(self, path: Path) -> str:
        if path.suffix.lower() not in self.supported_text_extensions:
            raise UnsupportedFileTypeError(f"Unsupported native text file type: {path.suffix.lower()}")
        text = path.read_text(encoding="utf-8", errors="strict").strip()
        if not text:
            raise UnsupportedFileTypeError(f"Empty text file: {path}")
        return text
