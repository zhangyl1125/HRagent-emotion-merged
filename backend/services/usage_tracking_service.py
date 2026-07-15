from __future__ import annotations
import logging
from math import ceil
from typing import Any
from uuid import uuid4
from backend.config.settings import get_settings
from backend.core.usage_context import get_usage_request_context
from backend.models.usage import NormalizedTokenUsage
from backend.repositories.usage_repository import UsageRepository

logger = logging.getLogger(__name__)

class UsageTrackingService:
    @staticmethod
    def normalize(raw: dict[str, Any] | None, *, estimated_input_bytes: int = 0, estimated_output_bytes: int = 0) -> NormalizedTokenUsage:
        raw = raw or {}
        def value(*keys: str) -> int | None:
            for key in keys:
                item = raw.get(key)
                if isinstance(item, (int,float)) and not isinstance(item,bool) and item >= 0: return int(item)
                if isinstance(item,str) and item.strip().isdigit(): return int(item)
            return None
        details = raw.get('completion_tokens_details') if isinstance(raw.get('completion_tokens_details'),dict) else {}
        prompt_details = raw.get('prompt_tokens_details') if isinstance(raw.get('prompt_tokens_details'),dict) else {}
        incoming=value('prompt_tokens','input_tokens','input_token_count')
        outgoing=value('completion_tokens','output_tokens','output_token_count')
        reasoning = value('reasoning_tokens')
        if reasoning is None:
            reasoning = UsageTrackingService._positive(details.get('reasoning_tokens'))
        cached=UsageTrackingService._positive(prompt_details.get('cached_tokens')) or UsageTrackingService._positive(raw.get('cached_tokens'))
        total=value('total_tokens','total_token_count')
        if total is None and incoming is not None and outgoing is not None: total=incoming+outgoing
        if incoming is not None or outgoing is not None or total is not None:
            return NormalizedTokenUsage(incoming,outgoing,reasoning,cached,total,'provider')
        if get_settings().admin_usage_estimation_enabled and (estimated_input_bytes or estimated_output_bytes):
            incoming=ceil(estimated_input_bytes/3.5) if estimated_input_bytes else 0
            outgoing=ceil(estimated_output_bytes/3.5) if estimated_output_bytes else 0
            return NormalizedTokenUsage(incoming,outgoing,None,None,incoming+outgoing,'estimated')
        return NormalizedTokenUsage()
    @staticmethod
    def _positive(value: Any) -> int | None:
        return int(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and value >= 0 else None
    def record(self, *, usage: NormalizedTokenUsage, task_name: str | None, provider: str, model: str, streaming: bool, status: str, duration_ms: int | None, retry_count: int=0, http_status: int | None=None, error_code: str | None=None, provider_request_id: str | None=None, input_bytes: int=0, output_bytes: int=0) -> None:
        settings=get_settings()
        if not settings.admin_usage_tracking_enabled: return
        context=get_usage_request_context()
        trace=context.trace_id if context.trace_id and len(context.trace_id)==36 else None
        try:
            UsageRepository().insert_event({'call_id':str(uuid4()),'trace_id':trace,'user_id':context.user_id,'email_snapshot':context.email,'business_session_id':context.business_session_id,'task_name':task_name,'provider':provider,'model':model,'is_streaming':streaming,'input_tokens':usage.input_tokens,'output_tokens':usage.output_tokens,'reasoning_tokens':usage.reasoning_tokens,'cached_tokens':usage.cached_tokens,'total_tokens':usage.total_tokens,'usage_source':usage.source,'status':status,'http_status':http_status,'duration_ms':duration_ms,'retry_count':retry_count,'provider_request_id':provider_request_id,'error_code':error_code,'usage_metadata':{}})
        except Exception:
            logger.warning('LLM usage event write failed', exc_info=False)
        else:
            logger.info('llm_usage | task=%s | provider=%s | model=%s | source=%s | status=%s | input_tokens=%s | output_tokens=%s | total_tokens=%s | duration_ms=%s', task_name or 'unknown', provider, model, usage.source, status, usage.input_tokens if usage.input_tokens is not None else 'null', usage.output_tokens if usage.output_tokens is not None else 'null', usage.total_tokens if usage.total_tokens is not None else 'null', duration_ms if duration_ms is not None else 'null')
