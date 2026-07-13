from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.config.settings import get_settings
from backend.schemas.difficulty import DifficultyConfig
from backend.schemas.intent import IntentConfig
from backend.schemas.persona import PersonaConfig
from backend.schemas.simulation import BigFivePersonality, EmotionAnchor, MotiveOption


class BusinessConfigLoader:
    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or get_settings().business_config_dir

    def load_yaml(self, relative_path: str) -> dict[str, Any]:
        path = self.config_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Missing business config: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Business config must be a mapping: {path}")
        return data

    def intents(self) -> dict[str, IntentConfig]:
        data = self.load_yaml("intents.yaml")
        return {item["id"]: IntentConfig(**item) for item in data.get("supported_intents", [])}

    def default_intent_id(self) -> str:
        data = self.load_yaml("intents.yaml")
        return data.get("default_intent", "pip_underperformance")

    def personas(self) -> dict[str, PersonaConfig]:
        data = self.load_yaml("personas.yaml")
        return {item["id"]: PersonaConfig(**item) for item in data.get("personas", [])}

    def difficulties(self) -> dict[str, DifficultyConfig]:
        data = self.load_yaml("difficulty.yaml")
        return {item["id"]: DifficultyConfig(**item) for item in data.get("levels", [])}

    def default_difficulty_id(self) -> str:
        data = self.load_yaml("difficulty.yaml")
        return data.get("default_difficulty", "medium")

    def motives(self) -> dict[str, MotiveOption]:
        data = self.load_yaml("motives.yaml")
        return {item["id"]: MotiveOption(**item) for item in data.get("motives", [])}

    def motive_recommendation(self, intent_id: str | None) -> dict[str, Any]:
        data = self.load_yaml("motives.yaml")
        recommendations = data.get("intent_recommendations", {})
        default = data.get("default_recommendation", {})
        return recommendations.get(intent_id or "", default) or default

    def emotion_anchors(self) -> dict[str, EmotionAnchor]:
        data = self.load_yaml("emotion_space.yaml")
        return {item["id"]: EmotionAnchor(**item) for item in data.get("anchors", [])}

    def default_big_five(self) -> BigFivePersonality:
        data = self.load_yaml("emotion_space.yaml")
        return BigFivePersonality(**(data.get("default_big_five") or {}))

    def personality_initial_vad_weights(self) -> dict[str, Any]:
        data = self.load_yaml("emotion_space.yaml")
        weights = data.get("personality_initial_vad_weights") or {}
        return weights if isinstance(weights, dict) else {}

    def default_emotion_anchor_id(self, intent_id: str | None = None) -> str | None:
        data = self.load_yaml("emotion_space.yaml")
        by_intent = data.get("initial_anchor_by_intent", {})
        anchor_id = by_intent.get(intent_id or "") or data.get("default_anchor")
        anchors = self.emotion_anchors()
        return anchor_id if anchor_id in anchors else next(iter(anchors), None)

    def query_config(self) -> dict[str, Any]:
        return self.load_yaml("query.yaml")

    def coach_config(self, filename: str) -> dict[str, Any]:
        return self.load_yaml(f"coach/{filename}")

    def all_coach_configs(self) -> dict[str, dict[str, Any]]:
        return {
            "coach_tasks": self.coach_config("coach_tasks.yaml"),
            "query": self.query_config(),
            "coach_schema": self.coach_config("coach_schema.yaml"),
            "rubric": self.coach_config("rubric.yaml"),
            "emotion": self.coach_config("emotion.yaml"),
            "performance": self.coach_config("performance.yaml"),
            "redline": self.coach_config("redline.yaml"),
        }


@lru_cache(maxsize=1)
def get_config_loader() -> BusinessConfigLoader:
    return BusinessConfigLoader()
