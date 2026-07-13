from __future__ import annotations

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from backend.config.settings import get_settings


class PromptService:
    def __init__(self, prompt_dir: Path | None = None):
        self.prompt_dir = prompt_dir or get_settings().prompt_dir
        self.env = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_path: str, **kwargs) -> str:
        return self.env.get_template(template_path).render(**kwargs)
