from __future__ import annotations

from pathlib import Path

from backend.exceptions.parser_errors import ParserError, UnsupportedFileTypeError
from backend.parsers.mineru import MinerUParser


class ParserRouter:
    def __init__(self):
        self.mineru = MinerUParser()
        self.mineru_extensions = {".pdf", ".docx", ".pptx", ".xlsx"}
        self.native_text_extensions = {".txt", ".md"}

    def parse_file(self, path: Path, *, fast_mode: bool = False) -> tuple[str, dict]:
        suffix = path.suffix.lower()
        if suffix in self.mineru_extensions:
            text = self.mineru.parse(path, fast_mode=fast_mode)
            return text, {"parser": "mineru", **dict(self.mineru.last_metadata)}
        if suffix in self.native_text_extensions:
            text = path.read_text(encoding="utf-8", errors="strict").strip()
            if not text:
                raise ParserError(f"文本文件为空: {path}")
            return text, {"parser": "native_text", "input_path": str(path)}
        raise UnsupportedFileTypeError(f"Unsupported file type: {suffix}. Supported document files: {sorted(self.mineru_extensions)}; native text: {sorted(self.native_text_extensions)}")
