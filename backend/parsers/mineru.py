from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import get_settings
from backend.exceptions.parser_errors import ParserError


def normalize_space(value: Any) -> str:
    """Normalize parser text fields into compact single-space text."""
    return re.sub(r"\s+", " ", str(value)).strip()


class MinerUParser:
    """MinerU HTTP API adapter for the official Docker deployment.

    The backend no longer embeds MinerU, torch, or vLLM. It uploads files to the
    dedicated MinerU API service and stores returned artifacts under runtime data
    so the existing chunking and metadata path can continue to work.
    """

    def __init__(self):
        self.settings = get_settings()
        self.last_metadata: dict[str, Any] = {}

    def parse(self, path: Path, *, fast_mode: bool = False) -> str:
        self.last_metadata = {"parser": "mineru", "input_path": str(path)}
        if not self.settings.mineru_enabled:
            raise ParserError("MINERU_ENABLED=false；当前项目要求 MinerU 必须启用。")
        if not path.exists():
            raise ParserError(f"待解析文件不存在: {path}")

        output_dir = self._make_output_dir(path)
        started_at = time.time()
        self.last_metadata.update({
            "status": "running",
            "api_url": self.settings.mineru_api_url,
            "backend": self.settings.mineru_backend,
            "effort": "medium" if fast_mode else self.settings.mineru_effort,
            "fast_mode": fast_mode,
            "output_dir": str(output_dir),
        })

        payload = self._request_parse(path, fast_mode=fast_mode)
        elapsed = round(time.time() - started_at, 3)
        text, result_key = self._extract_markdown(payload)
        markdown_path = output_dir / f"{path.stem}.md"
        markdown_path.write_text(text, encoding="utf-8")
        self._write_api_artifacts(output_dir, path.stem, payload, result_key)

        artifacts = self._collect_artifacts(
            output_dir=output_dir,
            markdown_path=markdown_path,
            markdown_text=text,
        )
        self.last_metadata.update({
            "status": "success",
            "elapsed_seconds": elapsed,
            "markdown_path": str(markdown_path),
            "markdown_chars": len(text),
            "result_key": result_key,
            **artifacts,
        })
        return text

    def _request_parse(self, path: Path, *, fast_mode: bool = False) -> dict[str, Any]:
        url = self.settings.mineru_api_url.rstrip("/") + "/file_parse"
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        form_data = {
            "lang_list": self.settings.mineru_lang,
            "backend": self.settings.mineru_backend,
            "effort": "medium" if fast_mode else self.settings.mineru_effort,
            "parse_method": self.settings.mineru_parse_method,
            "formula_enable": "false" if fast_mode else "true",
            "table_enable": "true",
            "image_analysis": "false" if fast_mode else "true",
            "return_md": "true",
            "return_middle_json": "false" if fast_mode else "true",
            "return_model_output": "false",
            "return_content_list": "false" if fast_mode else "true",
            "return_images": "false",
            "response_format_zip": "false",
            "return_original_file": "false",
            "client_side_output_generation": "false",
            "start_page_id": "0",
            "end_page_id": "99999",
        }
        timeout = httpx.Timeout(self.settings.mineru_timeout_seconds)
        try:
            with path.open("rb") as handle:
                files = [("files", (path.name, handle, mime_type))]
                response = httpx.post(url, data=form_data, files=files, timeout=timeout)
        except httpx.TimeoutException as exc:
            message = f"MinerU API 解析超时: {path.name}"
            self.last_metadata.update({"status": "timeout", "error": message})
            raise ParserError(message) from exc
        except httpx.HTTPError as exc:
            message = f"MinerU API 请求失败: {exc}"
            self.last_metadata.update({"status": "http_error", "error": message})
            raise ParserError(message) from exc

        self.last_metadata.update({"http_status": response.status_code})
        if response.status_code >= 400:
            body = response.text[-1000:]
            message = f"MinerU API 解析失败，status={response.status_code}: {body}"
            self.last_metadata.update({"status": "failed", "error": message})
            raise ParserError(message)
        try:
            payload = response.json()
        except ValueError as exc:
            message = "MinerU API 返回非 JSON 响应。"
            self.last_metadata.update({"status": "invalid_json", "error": message, "body": response.text[-1000:]})
            raise ParserError(message) from exc
        return payload

    @staticmethod
    def _extract_markdown(payload: dict[str, Any]) -> tuple[str, str]:
        results = payload.get("results")
        if not isinstance(results, dict) or not results:
            raise ParserError("MinerU API 未返回 results。")
        for key, value in results.items():
            if isinstance(value, dict):
                text = str(value.get("md_content") or "").strip()
                if text:
                    return text, str(key)
        raise ParserError("MinerU API 未返回 Markdown 内容。")

    @staticmethod
    def _write_api_artifacts(output_dir: Path, source_stem: str, payload: dict[str, Any], result_key: str) -> None:
        result = payload.get("results", {}).get(result_key, {})
        if not isinstance(result, dict):
            return
        artifact_names = {
            "middle_json": f"{source_stem}_middle.json",
            "content_list": f"{source_stem}_content_list.json",
            "model_output": f"{source_stem}_model.json",
        }
        for field, filename in artifact_names.items():
            value = result.get(field)
            if value is None:
                continue
            target = output_dir / filename
            if isinstance(value, str):
                target.write_text(value, encoding="utf-8")
            else:
                target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _make_output_dir(self, path: Path) -> Path:
        digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        output_dir = self.settings.resolved_mineru_output_dir / f"{path.stem}_{digest}_{stamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _collect_artifacts(self, output_dir: Path, markdown_path: Path, markdown_text: str) -> dict[str, Any]:
        json_paths = [p for p in output_dir.rglob("*.json") if p.is_file()]
        blocks: list[dict[str, Any]] = []
        pages: dict[str, dict[str, Any]] = {}
        for json_path in json_paths:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue
            extracted = self._extract_blocks_from_json(data, json_path)
            for block in extracted:
                blocks.append(block)
                page = block.get("page")
                if page is not None:
                    pages[str(page)] = {"page": page}

        if not blocks:
            blocks = self._blocks_from_markdown(markdown_text)
        tables = [block for block in blocks if str(block.get("type", "")).lower() in {"table", "table_body"}]
        tables.extend(self._markdown_table_blocks(markdown_text))

        images = [
            {"path": str(path), "type": "image", "page": self._page_from_path(path)}
            for path in sorted(output_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        ]
        for image in images:
            page = image.get("page")
            if page is not None:
                pages[str(page)] = {"page": page}

        artifact_paths = [str(markdown_path)] + [str(p) for p in json_paths] + [img["path"] for img in images]
        return {
            "pages": list(pages.values()),
            "page_count": len(pages),
            "structured_blocks": blocks,
            "block_count": len(blocks),
            "tables": tables,
            "table_count": len(tables),
            "images": images,
            "image_count": len(images),
            "artifact_paths": artifact_paths,
        }

    def _extract_blocks_from_json(self, data: Any, json_path: Path) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, dict):
                return
            block_type = node.get("type") or node.get("block_type") or node.get("category") or node.get("layout_type")
            text = node.get("text") or node.get("content") or node.get("md") or node.get("html")
            page = node.get("page") or node.get("page_idx") or node.get("page_num") or node.get("page_no")
            bbox = node.get("bbox") or node.get("poly") or node.get("box")
            if block_type or text or bbox:
                normalized_text = normalize_space(text) if text is not None else None
                blocks.append({
                    "type": str(block_type or "text"),
                    "text": normalized_text,
                    "page": page,
                    "bbox": bbox,
                    "source_json": str(json_path),
                })
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        walk(data)
        return blocks[:5000]

    @staticmethod
    def _blocks_from_markdown(markdown_text: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        current_section = None
        for idx, raw_line in enumerate(markdown_text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                current_section = line.lstrip("#").strip() or None
                block_type = "heading"
            elif line.startswith("!") and "](" in line:
                block_type = "image_reference"
            elif "|" in line and re.search(r"\|\s*-{3,}\s*\|", line):
                block_type = "table_separator"
            elif "|" in line:
                block_type = "table"
            else:
                block_type = "text"
            blocks.append({"type": block_type, "text": line, "page": None, "section": current_section, "line_index": idx})
        return blocks

    @staticmethod
    def _markdown_table_blocks(markdown_text: str) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        rows: list[str] = []
        for line in markdown_text.splitlines() + [""]:
            if "|" in line.strip():
                rows.append(line.strip())
                continue
            if len(rows) >= 2:
                tables.append({"type": "table", "text": "\n".join(rows), "page": None})
            rows = []
        return tables

    @staticmethod
    def _page_from_path(path: Path) -> int | None:
        match = re.search(r"(?:page|p)[_-]?(\d+)", path.stem, re.I)
        if match:
            return int(match.group(1))
        return None
