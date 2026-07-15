from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

UsageSource = Literal['provider', 'estimated', 'unavailable']

@dataclass(frozen=True)
class NormalizedTokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    source: UsageSource = 'unavailable'
