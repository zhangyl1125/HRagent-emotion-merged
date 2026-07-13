from __future__ import annotations

from typing import Any

DEFAULT_CHUNK_SIZE = 2800
DEFAULT_CHUNK_OVERLAP = 120
# Paragraph is the final natural split boundary. Do not recursively split into
# sentences or words; oversized single paragraphs fall back to hard split.
RECURSIVE_SEPARATORS = ("\n\n",)


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    chunk_size = max(1, int(chunk_size or DEFAULT_CHUNK_SIZE))
    overlap = max(0, min(int(overlap or 0), chunk_size // 2))
    splits = _recursive_split(text, chunk_size, RECURSIVE_SEPARATORS)
    return _merge_splits(splits, chunk_size=chunk_size, overlap=overlap)


def chunk_blocks(
    text: str,
    blocks: list[dict[str, Any]] | None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Create paragraph-level chunks while preserving available MinerU block metadata."""
    chunk_size = max(1, int(chunk_size or DEFAULT_CHUNK_SIZE))
    overlap = max(0, min(int(overlap or 0), chunk_size // 2))
    output: list[dict[str, Any]] = []
    usable_blocks = [b for b in (blocks or []) if str(b.get("text") or "").strip()]
    if not usable_blocks:
        for idx, chunk in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap)):
            output.append({"text": chunk, "page": None, "section": None, "block_indexes": [], "chunk_index": idx})
        return output

    buffer: list[str] = []
    block_indexes: list[int] = []
    page = None
    section = None

    def append_chunk(chunk: str, chunk_page: Any, chunk_section: Any, indexes: list[int]) -> None:
        cleaned = chunk.strip()
        if not cleaned:
            return
        output.append({
            "text": cleaned,
            "page": chunk_page,
            "section": chunk_section,
            "block_indexes": list(indexes),
            "chunk_index": len(output),
        })

    def flush() -> None:
        nonlocal buffer, block_indexes, page, section
        append_chunk("\n".join(buffer), page, section, block_indexes)
        buffer = []
        block_indexes = []
        page = None
        section = None

    for idx, block in enumerate(usable_blocks):
        block_text = str(block.get("text") or "").strip()
        if not block_text:
            continue
        block_page = block.get("page")
        block_section = block.get("section")

        if len(block_text) > chunk_size:
            flush()
            for piece in chunk_text(block_text, chunk_size=chunk_size, overlap=overlap):
                append_chunk(piece, block_page, block_section, [idx])
            continue

        pending_size = len("\n".join(buffer)) + len(block_text) + (1 if buffer else 0)
        if buffer and pending_size > chunk_size:
            flush()
        if not buffer:
            page = block_page
            section = block_section
        elif page is None and block_page is not None:
            page = block_page
        if block_section:
            section = block_section
        buffer.append(block_text)
        block_indexes.append(idx)
    flush()

    if not output:
        for idx, chunk in enumerate(chunk_text(text, chunk_size=chunk_size, overlap=overlap)):
            output.append({"text": chunk, "page": None, "section": None, "block_indexes": [], "chunk_index": idx})
    return output


def _recursive_split(text: str, chunk_size: int, separators: tuple[str, ...]) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    if not separators:
        return _hard_split(text, chunk_size)

    separator = separators[0]
    if separator not in text:
        return _recursive_split(text, chunk_size, separators[1:])

    pieces = _split_keep_separator(text, separator)
    output: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= chunk_size:
            output.append(piece)
        else:
            output.extend(_recursive_split(piece, chunk_size, separators[1:]))
    return output or _hard_split(text, chunk_size)


def _split_keep_separator(text: str, separator: str) -> list[str]:
    parts = text.split(separator)
    if len(parts) == 1:
        return [text]
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        suffix = separator if index < len(parts) - 1 else ""
        pieces.append(part + suffix)
    return pieces


def _merge_splits(splits: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for split in splits:
        piece = split.strip()
        if not piece:
            continue
        if not current:
            current = piece
            continue
        candidate = _join_text(current, piece)
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        chunks.extend(_hard_split(current, chunk_size))
        tail = _tail_overlap(current, overlap)
        candidate = _join_text(tail, piece) if tail else piece
        current = candidate if len(candidate) <= chunk_size else piece
    if current:
        chunks.extend(_hard_split(current, chunk_size))
    return [chunk for chunk in chunks if chunk.strip()]


def _join_text(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    return f"{left}\n{right}"


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    return text.strip()[-overlap:].strip()


def _hard_split(text: str, chunk_size: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[index:index + chunk_size].strip() for index in range(0, len(text), chunk_size) if text[index:index + chunk_size].strip()]
