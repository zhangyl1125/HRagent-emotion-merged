from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from backend.config.settings import Settings, get_settings
from backend.core.auth_dependency import require_super_admin_session
from backend.repositories.postgres_repository import PostgresRepository
from backend.services.auth_session_service import AuthSession

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_super_admin_session)])


def repo() -> PostgresRepository:
    return PostgresRepository()


def window(days: int | None, start: datetime | None, end: datetime | None, settings: Settings) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    to = end or now
    frm = start or to - timedelta(days=days or settings.admin_default_range_days)
    if frm.tzinfo is None or to.tzinfo is None or frm >= to or to - frm > timedelta(days=366):
        raise HTTPException(400, "Invalid time range")
    return frm, to


def page(total: int, items: list[dict], number: int, size: int) -> dict:
    return {"items": items, "page": number, "page_size": size, "total": total, "total_pages": ceil(total / size) if total else 0}

def _audit_action(request: Request, action: str, target_email: str | None, success: bool, reason: str | None = None) -> None:
    try:
        trace = getattr(request.state, 'trace_id', None)
        with repo().connection() as conn:
            conn.execute("INSERT INTO admin_action_audit_log(trace_id, actor_user_id, actor_email, action, target_email, success, reason) VALUES (%s,%s,%s,%s,%s,%s,%s)", (trace if isinstance(trace, str) and len(trace) == 36 else None, getattr(request.state, 'auth_user_id', None), getattr(request.state, 'auth_email', None), action, target_email, success, reason))
    except Exception:
        return


@router.get("/overview")
def overview(days: int | None = Query(None, ge=1, le=366), start: datetime | None = None, end: datetime | None = None, settings: Settings = Depends(get_settings)):
    frm, to = window(days, start, end, settings)
    with repo().connection() as conn:
        data = conn.execute("""SELECT
          (SELECT count(DISTINCT user_id) FROM api_request_events WHERE created_at >= %s AND created_at < %s) AS active_users,
          (SELECT count(*) FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS llm_calls,
          (SELECT COALESCE(sum(total_tokens), 0) FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS total_tokens,
          (SELECT count(*) FILTER (WHERE status='success') FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS successful_calls,
          (SELECT COALESCE(avg(duration_ms),0) FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS avg_duration_ms,
          (SELECT count(*) FROM auth_whitelist WHERE enabled) AS whitelist_count,
          (SELECT count(*) FROM sessions WHERE updated_at >= %s AND updated_at < %s) AS business_sessions,
          (SELECT count(*) FROM api_request_events WHERE status_code >= 400 AND created_at >= %s AND created_at < %s) AS api_errors,
          (SELECT count(*) FILTER (WHERE usage_source='estimated') FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS estimated_calls,
          (SELECT count(*) FILTER (WHERE usage_source='unavailable') FROM llm_usage_events WHERE created_at >= %s AND created_at < %s) AS unavailable_calls""", (frm,to,frm,to,frm,to,frm,to,frm,to,frm,to,frm,to,frm,to,frm,to,frm,to)).fetchone()
    return {"range": {"from": frm, "to": to}, **dict(data), "tracking_enabled": settings.admin_usage_tracking_enabled}


@router.get("/usage/trend")
def trend(days: int | None = Query(None, ge=1, le=366), granularity: Literal['hour','day'] = 'day', start: datetime | None = None, end: datetime | None = None, settings: Settings = Depends(get_settings)):
    frm, to = window(days, start, end, settings)
    bucket = "hour" if granularity == "hour" else "day"
    with repo().connection() as conn:
        rows = conn.execute(f"""SELECT date_trunc('{bucket}', created_at) AS bucket, COALESCE(sum(total_tokens),0) AS total_tokens,
             count(*) FILTER (WHERE usage_source='provider') AS provider_calls, count(*) FILTER (WHERE usage_source='estimated') AS estimated_calls,
             count(*) FILTER (WHERE usage_source='unavailable') AS unavailable_calls
             FROM llm_usage_events WHERE created_at >= %s AND created_at < %s GROUP BY 1 ORDER BY 1""", (frm,to)).fetchall()
    return {"items": [dict(r) for r in rows], "range": {"from": frm, "to": to}}


@router.get("/usage/events")
def events(page_number: int = Query(1, alias='page', ge=1), page_size: int = Query(50, ge=1, le=200), email: str | None = None, model: str | None = None, task: str | None = None, status: str | None = None, days: int | None = Query(None, ge=1, le=366), settings: Settings = Depends(get_settings)):
    frm, to = window(days, None, None, settings); filters = ["created_at >= %s", "created_at < %s"]; args: list = [frm,to]
    for column, value in (("email_snapshot",email),("model",model),("task_name",task),("status",status)):
        if value: filters.append(f"{column} = %s"); args.append(value.lower() if column == 'email_snapshot' else value)
    where = " AND ".join(filters)
    with repo().connection() as conn:
        total = conn.execute(f"SELECT count(*) AS c FROM llm_usage_events WHERE {where}", args).fetchone()['c']
        rows = conn.execute(f"""SELECT created_at, email_snapshot, task_name, model, is_streaming, input_tokens, output_tokens, reasoning_tokens, cached_tokens, total_tokens, usage_source, duration_ms, status, http_status, error_code, trace_id, business_session_id FROM llm_usage_events WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s""", [*args,page_size,(page_number-1)*page_size]).fetchall()
    return page(total, [dict(r) for r in rows], page_number, page_size)


@router.get("/usage/users")
def usage_users(page_number: int = Query(1, alias='page', ge=1), page_size: int = Query(50, ge=1, le=200), days: int | None = Query(None, ge=1, le=366), settings: Settings = Depends(get_settings)):
    frm,to = window(days,None,None,settings)
    with repo().connection() as conn:
        total = conn.execute("SELECT count(*) AS c FROM app_users").fetchone()['c']
        rows = conn.execute("""SELECT u.id::text AS user_id,u.email::text,u.display_name,u.role,u.is_active,u.last_login_at,
          COALESCE(sum(e.input_tokens),0) input_tokens,COALESCE(sum(e.output_tokens),0) output_tokens,COALESCE(sum(e.total_tokens),0) total_tokens,
          count(e.id) llm_calls,count(e.id) FILTER (WHERE e.status <> 'success') errors,max(e.created_at) last_llm_at
          FROM app_users u LEFT JOIN llm_usage_events e ON e.user_id=u.id AND e.created_at >= %s AND e.created_at < %s
          GROUP BY u.id ORDER BY total_tokens DESC,u.email LIMIT %s OFFSET %s""",(frm,to,page_size,(page_number-1)*page_size)).fetchall()
    return page(total,[dict(r) for r in rows],page_number,page_size)


@router.get("/activity/api-requests")
def api_requests(page_number: int = Query(1,alias='page',ge=1),page_size: int = Query(50,ge=1,le=200)):
    with repo().connection() as conn:
        total=conn.execute("SELECT count(*) c FROM api_request_events").fetchone()['c']; rows=conn.execute("SELECT created_at,email_snapshot,method,route_template,status_code,duration_ms,trace_id FROM api_request_events ORDER BY created_at DESC LIMIT %s OFFSET %s",(page_size,(page_number-1)*page_size)).fetchall()
    return page(total,[dict(r) for r in rows],page_number,page_size)


@router.get("/activity/auth-audit")
def auth_audit(page_number: int = Query(1,alias='page',ge=1),page_size: int = Query(50,ge=1,le=200)):
    with repo().connection() as conn:
        total=conn.execute("SELECT count(*) c FROM auth_audit_log").fetchone()['c']; rows=conn.execute("SELECT email::text,event_type,success,reason,created_at FROM auth_audit_log ORDER BY created_at DESC LIMIT %s OFFSET %s",(page_size,(page_number-1)*page_size)).fetchall()
    return page(total,[dict(r) for r in rows],page_number,page_size)


@router.get("/usage/export.csv")
def export_usage(settings: Settings = Depends(get_settings), admin: AuthSession = Depends(require_super_admin_session)):
    with repo().connection() as conn:
        rows=conn.execute("SELECT created_at,email_snapshot,task_name,model,is_streaming,input_tokens,output_tokens,total_tokens,usage_source,duration_ms,status,http_status,error_code,trace_id,business_session_id FROM llm_usage_events ORDER BY created_at DESC LIMIT %s",(settings.admin_export_max_rows,)).fetchall()
        conn.execute("INSERT INTO admin_action_audit_log(actor_user_id,actor_email,action,success) VALUES (%s,%s,'usage_export',TRUE)",(admin.user_id,admin.user.email))
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(['created_at','email','task','model','streaming','input_tokens','output_tokens','total_tokens','source','duration_ms','status','http_status','error_code','trace_id','business_session_id'])
    for row in rows: writer.writerow([("'"+str(v)) if isinstance(v,str) and v[:1] in '=+-@' else v for v in row.values()])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename=usage.csv'})

from fastapi import Request
from backend.schemas.auth import AdminAccountCreateRequest, AdminPasswordResetRequest, AdminWhitelistUpdateRequest
from backend.services.auth_service import AuthService, RegistrationFailed

@router.get('/whitelist')
def whitelist_list():
    return {'items': AuthService().list_admin_accounts()}

@router.post('/whitelist')
async def whitelist_create(payload: AdminAccountCreateRequest, request: Request):
    try:
        result = await AuthService().admin_create_account(payload, request)
        _audit_action(request, 'account_create', payload.email, True)
        return result
    except RegistrationFailed as exc:
        raise HTTPException(400, 'Unable to create account') from exc

@router.patch('/whitelist/{email}')
def whitelist_update(email: str, payload: AdminWhitelistUpdateRequest, request: Request):
    if payload.email != email.strip().lower():
        raise HTTPException(400, 'Email mismatch')
    try:
        result = AuthService().admin_set_whitelist(email, payload.enabled, request)
        _audit_action(request, 'whitelist_enable' if payload.enabled else 'whitelist_disable', email, True)
        return result
    except RegistrationFailed as exc:
        raise HTTPException(400, 'Unable to update whitelist') from exc

@router.patch('/whitelist/{email}/password')
async def whitelist_password(email: str, payload: AdminPasswordResetRequest, request: Request):
    try:
        result = await AuthService().admin_reset_password(email, payload, request)
        _audit_action(request, 'password_reset', email, True)
        return result
    except RegistrationFailed as exc:
        raise HTTPException(400, 'Unable to reset password') from exc

@router.delete('/whitelist/{email}', status_code=204)
def whitelist_delete(email: str, request: Request):
    try:
        AuthService().admin_delete_account(email, request)
        _audit_action(request, 'whitelist_delete', email, True)
    except RegistrationFailed as exc:
        raise HTTPException(400, 'Unable to delete account') from exc

@router.get('/activity/admin-actions')
def admin_actions(page_number: int = Query(1, alias='page', ge=1), page_size: int = Query(50, ge=1, le=200)):
    with repo().connection() as conn:
        total = conn.execute('SELECT count(*) c FROM admin_action_audit_log').fetchone()['c']
        rows = conn.execute('SELECT created_at,actor_email::text,action,target_email::text,success,reason FROM admin_action_audit_log ORDER BY created_at DESC LIMIT %s OFFSET %s', (page_size, (page_number - 1) * page_size)).fetchall()
    return page(total, [dict(row) for row in rows], page_number, page_size)
