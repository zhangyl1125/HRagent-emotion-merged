from __future__ import annotations

from pathlib import Path

from backend.config.settings import get_settings
from backend.parsers.parser_router import ParserRouter
from backend.parsers.text_parser import TextParser
from backend.schemas.document import ParsedDocument
from backend.services.cache_service import CacheService, cache_digest, sha256_bytes, sha256_text


class DocumentPipeline:
    def __init__(self):
        self.router = ParserRouter()
        self.text_parser = TextParser()
        self.settings = get_settings()
        self.cache = CacheService(self.settings)

    def parse_text(self, text: str, document_id: str, filename: str | None = None) -> ParsedDocument:
        key = self._text_cache_key(text)
        cached = self.cache.get_json(key)
        if cached:
            return self._rehydrate(cached, document_id=document_id, filename=filename)

        parsed = self.text_parser.parse(text=text, document_id=document_id, filename=filename)
        self.cache.set_json(key, parsed.model_dump(mode="json"), self.settings.document_parse_cache_ttl_seconds)
        return parsed

    def parse_file(self, path: Path, document_id: str, *, fast_mode: bool = False) -> ParsedDocument:
        file_bytes = path.read_bytes()
        key = self._file_cache_key(path, file_bytes, fast_mode=fast_mode)
        cached = self.cache.get_json(key)
        if cached:
            return self._rehydrate(cached, document_id=document_id, filename=path.name, input_path=str(path))

        text, metadata = self.router.parse_file(path, fast_mode=fast_mode)
        parsed = ParsedDocument(
            document_id=document_id,
            filename=path.name,
            text=text,
            pages=list(metadata.get("pages") or []),
            blocks=list(metadata.get("structured_blocks") or []),
            tables=list(metadata.get("tables") or []),
            images=list(metadata.get("images") or []),
            metadata=metadata,
        )
        self.cache.set_json(key, parsed.model_dump(mode="json"), self.settings.document_parse_cache_ttl_seconds)
        return parsed

    def _text_cache_key(self, text: str) -> str:
        digest = cache_digest({
            "kind": "text",
            "text_hash": sha256_text(text),
            "parser": "native_text",
            "version": "v1",
        })
        return self.cache.namespaced("doc_parse", digest)

    def _file_cache_key(self, path: Path, file_bytes: bytes, *, fast_mode: bool = False) -> str:
        digest = cache_digest({
            "kind": "file",
            "file_hash": sha256_bytes(file_bytes),
            "suffix": path.suffix.lower(),
            "fast_mode": fast_mode,
            "mineru_enabled": self.settings.mineru_enabled,
            "mineru_backend": self.settings.mineru_backend,
            "mineru_effort": self.settings.mineru_effort,
            "mineru_parse_method": self.settings.mineru_parse_method,
            "mineru_lang": self.settings.mineru_lang,
            "kb_index_version": self.settings.kb_index_version,
        })
        return self.cache.namespaced("doc_parse", digest)

    @staticmethod
    def _rehydrate(payload: dict, *, document_id: str, filename: str | None, input_path: str | None = None) -> ParsedDocument:
        parsed = ParsedDocument.model_validate(payload)
        metadata = dict(parsed.metadata or {})
        metadata["cache_hit"] = True
        if input_path:
            metadata["input_path"] = input_path
        return parsed.model_copy(update={
            "document_id": document_id,
            "filename": filename,
            "metadata": metadata,
        })
