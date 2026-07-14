from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

TaskStatus = Literal["success", "insufficient_information", "failed"]
RiskSeverity = Literal["critical", "high", "medium", "low"]


class EvidenceRef(BaseModel):
    turn_index: int
    speaker: str
    quote: str
    note: str | None = None


class DimensionScore(BaseModel):
    id: str
    name: str
    score: int | None = None
    level: str | None = None
    comment: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class BetterPhrase(BaseModel):
    original: str | None = None
    suggestion: str
    reason: str


class RiskItem(BaseModel):
    rule_id: str | None = None
    severity: RiskSeverity = "low"
    category: str = "沟通风险"
    matched_text: str | None = None
    explanation: str
    safer_phrase: str | None = None


class CoachTaskResult(BaseModel):
    task_id: str
    task_name: str
    status: TaskStatus = "success"
    score: int | None = None
    summary: str
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvement_points: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    better_phrases: list[BetterPhrase] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def preserve_unstructured_evidence(cls, value: Any) -> Any:
        """Retain real model analysis that is not a usable conversation reference."""
        if not isinstance(value, dict):
            return value
        raw_evidence = value.get("evidence")
        if raw_evidence is None or raw_evidence == {}:
            return value
        entries = list(raw_evidence) if isinstance(raw_evidence, (list, tuple)) else [raw_evidence]
        references: list[dict[str, Any]] = []
        unstructured: list[Any] = []
        for entry in entries:
            if isinstance(entry, dict) and {"turn_index", "speaker", "quote"}.issubset(entry):
                references.append(entry)
            else:
                unstructured.append(entry)
        if not unstructured:
            return value
        normalized = dict(value)
        normalized["evidence"] = references
        extra = dict(normalized.get("extra") or {})
        existing = extra.get("unstructured_evidence")
        if existing:
            extra["unstructured_evidence"] = [*list(existing), *unstructured]
        else:
            extra["unstructured_evidence"] = unstructured
        normalized["extra"] = extra
        return normalized

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"completed", "complete", "ok", "passed", "pass"}:
                return "success"
            if normalized in {"insufficient", "not_enough_information", "not_applicable", "n/a"}:
                return "insufficient_information"
            if normalized in {"error", "failure"}:
                return "failed"
        return value

    @field_validator(
        "dimension_scores",
        "evidence",
        "strengths",
        "improvement_points",
        "risks",
        "better_phrases",
        "citations",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name == "dimension_scores":
            return cls._normalize_dimension_scores(value)
        if info.field_name == "risks":
            return cls._normalize_risks(value)
        if info.field_name == "better_phrases":
            return cls._normalize_better_phrases(value)
        if info.field_name == "citations":
            return cls._normalize_citations(value)
        return cls._as_list(value)

    @classmethod
    def _as_list(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, dict):
            if not value:
                return []
            if any(key in value for key in {"id", "turn_index", "suggestion", "rule_id", "source", "chunk_id"}):
                return [value]
            return list(value.values())
        return [value]

    @classmethod
    def _normalize_dimension_scores(cls, value: Any) -> list[Any]:
        items = cls._as_list(value)
        normalized: list[Any] = []
        if isinstance(value, dict) and not any(key in value for key in {"id", "name", "score", "level", "comment"}):
            items = [
                {"id": str(key), "name": str(key), "score": item}
                if isinstance(item, (int, float))
                else {"id": str(key), "name": str(key), **item}
                if isinstance(item, dict)
                else {"id": str(key), "name": str(key), "comment": str(item)}
                for key, item in value.items()
            ]
        for index, item in enumerate(items):
            if isinstance(item, dict):
                normalized.append(cls._normalize_dimension_score_item(item))
            elif isinstance(item, (int, float)):
                normalized.append({"id": f"dimension_{index + 1}", "name": f"dimension_{index + 1}", "score": item})
            else:
                normalized.append({"id": f"dimension_{index + 1}", "name": f"dimension_{index + 1}", "comment": str(item)})
        return normalized

    @classmethod
    def _normalize_dimension_score_item(cls, item: dict[str, Any]) -> dict[str, Any]:
        """Keep model-provided assessment text without fabricating evidence refs."""
        normalized = dict(item)
        evidence = normalized.get("evidence")
        evidence_texts: list[str] = []
        if isinstance(evidence, str):
            evidence_texts = [evidence]
            normalized["evidence"] = []
        elif isinstance(evidence, list):
            evidence_texts = [entry for entry in evidence if isinstance(entry, str)]
            if evidence_texts:
                normalized["evidence"] = [entry for entry in evidence if not isinstance(entry, str)]
        evidence_text = "\n".join(entry.strip() for entry in evidence_texts if entry.strip())
        if evidence_text:
            comment = str(normalized.get("comment") or "").strip()
            normalized["comment"] = f"{comment}\n{evidence_text}" if comment else evidence_text
        return normalized

    @classmethod
    def _normalize_risks(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                if "explanation" not in item:
                    item = {**item, "explanation": str(item.get("description") or item.get("risk") or item.get("summary") or item)}
                normalized.append(item)
            else:
                normalized.append({"explanation": str(item)})
        return normalized

    @classmethod
    def _normalize_better_phrases(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                suggestion = item.get("suggestion") or item.get("suggested_phrase") or item.get("better_phrase") or item.get("safer_phrase") or item.get("phrase")
                reason = item.get("reason") or item.get("explanation") or "建议替换表达，降低沟通风险。"
                original = item.get("original") or item.get("original_context") or item.get("matched_text")
                normalized.append({"original": original, "suggestion": str(suggestion or item), "reason": str(reason)})
            else:
                normalized.append({"suggestion": str(item), "reason": "建议替换表达，降低沟通风险。"})
        return normalized

    @classmethod
    def _normalize_citations(cls, value: Any) -> list[Any]:
        normalized: list[Any] = []
        for item in cls._as_list(value):
            if isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"source": str(item)})
        return normalized
