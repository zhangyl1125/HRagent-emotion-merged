from __future__ import annotations
import json
from typing import Any
from backend.repositories.postgres_repository import PostgresRepository

class UsageRepository:
    def __init__(self) -> None: self.repo = PostgresRepository()
    def insert_event(self, event: dict[str, Any]) -> None:
        columns = ('call_id','trace_id','user_id','email_snapshot','business_session_id','task_name','provider','model','is_streaming','input_tokens','output_tokens','reasoning_tokens','cached_tokens','total_tokens','usage_source','status','http_status','duration_ms','retry_count','provider_request_id','error_code','usage_metadata')
        values = [json.dumps(event.get(key) or {}) if key == 'usage_metadata' else event.get(key) for key in columns]
        with self.repo.connection() as conn:
            conn.execute(f"INSERT INTO llm_usage_events ({','.join(columns)}) VALUES ({','.join(['%s']*len(columns))}) ON CONFLICT (call_id) DO NOTHING", values)
