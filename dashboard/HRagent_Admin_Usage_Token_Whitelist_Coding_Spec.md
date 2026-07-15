# HRagent 管理后台：用户使用记录、Token 用量可视化与白名单管理 Coding Spec

> 项目：`HRagent-emotion-merged-main`  
> 文档用途：直接交给 Coding AI 进行设计、编码、测试和验收  
> 根管理员：`aah5sgh@bosch.com`  
> 目标路由：`/admin`  
> 文档状态：可执行方案

---

## 1. 可行性结论

**结论：可行，建议直接基于现有技术栈增量开发，不新增独立管理系统。**

现有项目已经具备以下基础能力：

- 后端：FastAPI、PostgreSQL/pgvector、Redis、Pydantic Settings；
- 前端：React 19、TypeScript、Vite、React Router；
- 身份认证：本地账号、Argon2id 密码哈希、Redis Session、HttpOnly Cookie；
- 权限字段：`app_users.role` 已支持 `user/admin`；
- 白名单：已有 `auth_whitelist` 表、`WhitelistService` 和管理员白名单接口；
- 管理页面：已有 `frontend/src/pages/AdminPage.tsx`，当前可以创建账号、启停白名单、重置密码和删除授权；
- 用户业务会话：`sessions.owner_user_id` 已经能够关联登录用户；
- LLM 调用：统一经过 `ModelFarmLangChainChatModel`，响应中已经能够提取 `usage`，但尚未持久化；
- 当前根管理员逻辑中已经出现 `aah5sgh@bosch.com`，可继续作为唯一超级管理员。

因此，本次开发应当采用“**扩展现有 AdminPage + 增加管理 API + 增加用量事实表 + 在统一 LLM 适配器中埋点**”的方式实现。

### 1.1 本次禁止采用的方案

不得执行以下做法：

1. 不创建第二套独立后端，例如 Django Admin、Node.js Admin Server；
2. 不引入第二个数据库；
3. 不通过 Grafana 直接管理用户和白名单；
4. 不从 Loki 日志反向统计 Token 作为主数据源；
5. 不在每个 Agent 文件中分别手写 Token 统计逻辑；
6. 不在前端判断管理员后绕过后端权限检查；
7. 不存储完整 Prompt、完整模型回复或用户对话正文到用量表；
8. 不将缺失的 Token 数据默认为 0；
9. 不允许删除、停用、降级根管理员 `aah5sgh@bosch.com`；
10. 不将模型 API Key、用户密码或 Session ID 返回给管理端。

---

## 2. 建设目标

管理后台需要让唯一根管理员 `aah5sgh@bosch.com` 完成以下工作：

### 2.1 用户使用情况管理

- 查看系统用户总数、启用用户数、白名单用户数；
- 查看不同用户的登录时间、最近使用时间、业务会话数量；
- 查看不同用户的 API 请求数量、成功率和错误数量；
- 查看不同用户的 LLM 调用次数；
- 查看每个用户在指定时间范围内使用的输入 Token、输出 Token和总 Token；
- 查看用户使用了哪些模型和哪些业务任务；
- 查看调用耗时、状态和 Token 数据来源；
- 支持用户、模型、任务、状态、时间范围筛选；
- 支持分页和 CSV 导出。

### 2.2 Token 用量可视化

- 今日 Token；
- 最近 7 天 Token；
- 最近 30 天 Token；
- 输入 Token、输出 Token和总 Token趋势；
- 用户 Token 排名；
- 模型使用占比；
- 业务任务使用占比；
- 调用成功率；
- 平均响应时间；
- 精确 Token 与估算 Token 的比例。

### 2.3 白名单与账号管理

- 查看全部白名单账号；
- 新增 Bosch 邮箱白名单；
- 创建本地账号；
- 启用或停用白名单；
- 修改显示名称和备注；
- 重置本地账号密码；
- 停用账号并强制清除该用户全部登录 Session；
- 删除非管理员白名单；
- 查看管理员操作审计记录；
- 根管理员不可被停用、删除或修改角色。

### 2.4 本期明确不做

- 不实现正式 Bosch OIDC/SSO；
- 不计算真实费用，除非后续提供每个内部模型的输入、输出计价规则；
- 不实现用户自助查看 Token；
- 不实现复杂多级 RBAC；
- 不实现硬性 Token 阻断或自动限流；
- 不把 Grafana 作为业务管理页面；
- 不记录或展示用户 Prompt 与模型完整回答。

---

## 3. 总体架构

```text
Browser
  └── React /admin
        ├── Overview Dashboard
        ├── Users & Token Usage
        ├── Usage Records
        ├── Whitelist & Accounts
        └── Security Audit
                 │
                 ▼
FastAPI /api/v1/admin/*
  ├── require_super_admin_session
  ├── AdminAnalyticsService
  ├── UsageTrackingService
  ├── AdminAccountService
  ├── AdminAuditService
  └── APIRequestAuditMiddleware
                 │
                 ├── PostgreSQL
                 │     ├── app_users
                 │     ├── auth_whitelist
                 │     ├── auth_audit_log
                 │     ├── sessions
                 │     ├── llm_usage_events          [新增]
                 │     ├── api_request_events        [新增]
                 │     └── admin_action_audit_log    [新增]
                 │
                 └── Redis
                       ├── 登录 Session
                       └── 活跃 Session 统计

ModelFarmLangChainChatModel
  ├── _generate
  ├── _agenerate
  ├── astream_text
  └── astream_events
          │
          └── UsageTrackingService.record_*()
```

### 3.1 核心原则

1. **PostgreSQL 是业务管理数据的唯一事实源**；
2. **Token 统计统一放在 LLM 适配器层**，避免漏统计；
3. **所有管理 API 必须由后端鉴权**；
4. **统计失败不得导致业务模型调用失败**；
5. **缺失 Token 必须标记为 unavailable 或 estimated**；
6. **全部时间按 UTC 入库，前端按浏览器时区显示**；
7. **所有写操作必须进入管理员审计表**；
8. **不保存请求正文、Prompt、模型回复、密码和 API Key**。

---

## 4. 唯一根管理员安全模型

### 4.1 新增配置

修改：`backend/config/settings.py`

```python
admin_super_email: str = "aah5sgh@bosch.com"
admin_console_enabled: bool = True
admin_usage_tracking_enabled: bool = True
admin_usage_estimation_enabled: bool = True
admin_usage_retention_days: int = 365
admin_api_audit_retention_days: int = 90
admin_export_max_rows: int = 50000
admin_default_range_days: int = 7
```

环境变量示例：

```env
ADMIN_SUPER_EMAIL=aah5sgh@bosch.com
ADMIN_CONSOLE_ENABLED=true
ADMIN_USAGE_TRACKING_ENABLED=true
ADMIN_USAGE_ESTIMATION_ENABLED=true
ADMIN_USAGE_RETENTION_DAYS=365
ADMIN_API_AUDIT_RETENTION_DAYS=90
ADMIN_EXPORT_MAX_ROWS=50000
ADMIN_DEFAULT_RANGE_DAYS=7
```

### 4.2 新增超级管理员依赖

修改：`backend/core/auth_dependency.py`

新增：

```python
def require_super_admin_session(
    session: AuthSession = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    expected = settings.admin_super_email.strip().lower()
    actual = session.user.email.strip().lower()

    if session.role != "admin" or actual != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super administrator access required",
        )
    return session
```

### 4.3 权限要求

所有 `/api/v1/admin/*` API 必须使用：

```python
Depends(require_super_admin_session)
```

不能只使用：

```python
Depends(require_admin_session)
```

原因：当前数据库中的 `role` 字段可能被误修改，根管理员必须同时满足：

```text
role == admin
AND
email == aah5sgh@bosch.com
```

### 4.4 生产环境保护

当 `ENVIRONMENT != local` 时必须满足：

```text
AUTH_ENABLED=true
AUTH_COOKIE_SECURE=true
ADMIN_CONSOLE_ENABLED=true
ADMIN_SUPER_EMAIL=aah5sgh@bosch.com
```

当 `AUTH_ENABLED=false` 时：

- `/admin` 前端不可进入；
- `/api/v1/admin/*` 必须返回 `403`；
- 不允许使用当前 `local@bosch.com` 的模拟管理员访问管理 API。

### 4.5 根管理员不可变规则

后端必须强制执行：

```text
aah5sgh@bosch.com 不可：
- 删除；
- 停用；
- 移出白名单；
- 修改为 user；
- 强制注销自身全部 Session，除非执行显式“退出登录”；
- 被其他账号重置密码。
```

前端按钮禁用只是辅助，真正限制必须在后端实现。

---

## 5. 数据库设计

新增迁移文件：

```text
backend/db/migrations/0003_add_admin_usage_tables.sql
```

同时必须将幂等建表逻辑同步加入：

```text
backend/repositories/postgres_repository.py::init_schema()
```

项目当前会在 `PostgresRepository()` 初始化时执行 `init_schema()`，因此不能只增加 SQL 迁移文件而不修改 `init_schema()`。

### 5.1 LLM Token 用量事实表

```sql
CREATE TABLE IF NOT EXISTS llm_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id UUID NOT NULL,
    call_id UUID NOT NULL UNIQUE,

    user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    email_snapshot CITEXT,
    business_session_id TEXT,

    task_name VARCHAR(100),
    provider VARCHAR(60) NOT NULL,
    model VARCHAR(160) NOT NULL,
    endpoint_kind VARCHAR(30) NOT NULL DEFAULT 'chat',
    is_stream BOOLEAN NOT NULL DEFAULT FALSE,

    input_tokens BIGINT,
    output_tokens BIGINT,
    reasoning_tokens BIGINT,
    cached_input_tokens BIGINT,
    total_tokens BIGINT,
    token_source VARCHAR(20) NOT NULL DEFAULT 'unavailable',

    status VARCHAR(20) NOT NULL,
    http_status INTEGER,
    latency_ms INTEGER,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    provider_request_id VARCHAR(255),
    error_code VARCHAR(120),

    usage_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT llm_usage_token_source_check
      CHECK (token_source IN ('provider', 'estimated', 'unavailable')),
    CONSTRAINT llm_usage_status_check
      CHECK (status IN ('success', 'error', 'cancelled')),
    CONSTRAINT llm_usage_nonnegative_check
      CHECK (
        COALESCE(input_tokens, 0) >= 0
        AND COALESCE(output_tokens, 0) >= 0
        AND COALESCE(reasoning_tokens, 0) >= 0
        AND COALESCE(cached_input_tokens, 0) >= 0
        AND COALESCE(total_tokens, 0) >= 0
      )
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_created
ON llm_usage_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created
ON llm_usage_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_email_created
ON llm_usage_events(email_snapshot, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_model_created
ON llm_usage_events(model, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_task_created
ON llm_usage_events(task_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_status_created
ON llm_usage_events(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_business_session
ON llm_usage_events(business_session_id, created_at DESC)
WHERE business_session_id IS NOT NULL;
```

#### 字段说明

| 字段 | 含义 |
|---|---|
| `trace_id` | 一次 HTTP 请求或后台任务的链路 ID；一次请求可包含多次模型调用 |
| `call_id` | 单次模型调用唯一 ID，必须防止重复写入 |
| `user_id` | 当前登录用户 ID；账号删除后允许置空 |
| `email_snapshot` | 调用发生时的邮箱快照，用于用户停用后仍能审计 |
| `business_session_id` | HRagent 业务会话 ID，可为空 |
| `task_name` | `employee`、`guidance`、`intent`、`profile`、`coach_report` 等 |
| `token_source` | `provider`、`estimated`、`unavailable` |
| `usage_metadata` | 只允许保存标准化后的数字字段，不保存完整模型响应 |

### 5.2 API 使用记录表

```sql
CREATE TABLE IF NOT EXISTS api_request_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id UUID NOT NULL,
    user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    email_snapshot CITEXT,

    method VARCHAR(10) NOT NULL,
    route_template VARCHAR(255) NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_request_created
ON api_request_events(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_request_user_created
ON api_request_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_request_route_created
ON api_request_events(route_template, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_api_request_status_created
ON api_request_events(status_code, created_at DESC);
```

该表不得保存：

- Query 参数原文；
- Request Body；
- Response Body；
- Cookie；
- Authorization Header；
- 用户输入内容；
- 上传文件内容。

### 5.3 管理员操作审计表

```sql
CREATE TABLE IF NOT EXISTS admin_action_audit_log (
    id BIGSERIAL PRIMARY KEY,
    trace_id UUID NOT NULL,

    actor_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    actor_email CITEXT NOT NULL,

    action_type VARCHAR(80) NOT NULL,
    target_type VARCHAR(60) NOT NULL,
    target_key TEXT,

    before_state JSONB,
    after_state JSONB,
    success BOOLEAN NOT NULL,
    reason VARCHAR(200),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_action_created
ON admin_action_audit_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_action_actor_created
ON admin_action_audit_log(actor_email, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_action_target_created
ON admin_action_audit_log(target_type, target_key, created_at DESC);
```

审计表中禁止保存密码和密码哈希。

### 5.4 扩展白名单表

```sql
ALTER TABLE auth_whitelist
ADD COLUMN IF NOT EXISTS created_by CITEXT;

ALTER TABLE auth_whitelist
ADD COLUMN IF NOT EXISTS updated_by CITEXT;

ALTER TABLE auth_whitelist
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
```

建议将当前的 `set_allowed()` 更新为同时写入：

```text
note
created_by
updated_by
updated_at
```

### 5.5 不建立汇总表

当前预计 5～7 个业务用户，初期直接对事实表聚合即可，不创建每日汇总表或物化视图。

只有当 `llm_usage_events` 超过约 100 万行、管理查询明显变慢时，再增加每日汇总表。

---

## 6. 请求上下文与关联关系

### 6.1 扩展 ContextVar

修改：

```text
backend/core/session_context.py
```

将当前仅保存 `user_id` 的方式扩展为：

```python
from dataclasses import dataclass
from contextvars import ContextVar, Token

@dataclass(frozen=True)
class UsageRequestContext:
    trace_id: str
    user_id: str | None
    email: str | None
    role: str | None
    business_session_id: str | None = None

_current_usage_context: ContextVar[UsageRequestContext | None] = ContextVar(
    "current_usage_context",
    default=None,
)
```

必须保留现有 `get_current_auth_user_id()` 的兼容行为，避免破坏 SessionRepository。

### 6.2 Trace ID 中间件

新增：

```text
backend/middleware/request_context.py
```

要求：

1. 每个 HTTP 请求生成 UUID `trace_id`；
2. 若请求头提供合法 `X-Request-ID`，可以复用，但必须限制长度并清洗；
3. 将 `trace_id` 写入：
   - ContextVar；
   - `request.state.trace_id`；
   - 响应头 `X-Request-ID`；
4. 请求结束后正确 reset ContextVar，避免并发串用户。

### 6.3 登录用户上下文

修改：

```text
backend/core/auth_dependency.py::get_current_session()
```

认证成功后写入：

```python
request.state.auth_user_id = session.user_id
request.state.auth_email = session.user.email
request.state.auth_role = session.role
```

同时更新 UsageRequestContext 中的用户字段。

### 6.4 业务 Session ID

在具有 `session_id` 的路由或服务入口中，使用上下文管理器临时绑定：

```python
with bind_business_session(session_id):
    result = await service.generate(...)
```

优先覆盖以下调用：

- guidance；
- rehearsal；
- report；
- employee simulation；
- profile extraction；
- intent recognition。

如果某次模型调用无法获得业务 Session ID，允许为空，但用户 ID 和 trace ID 不得丢失。

---

## 7. Token 统计实现

### 7.1 统一埋点位置

Token 统计必须放在：

```text
backend/services/langchain_llm_service.py
```

重点修改以下方法：

```text
ModelFarmLangChainChatModel._generate
ModelFarmLangChainChatModel._agenerate
ModelFarmLangChainChatModel.astream_text
ModelFarmLangChainChatModel.astream_events
```

不能在 `employee_agent.py`、`guidance_agent.py` 等业务 Agent 中分别统计，否则会出现：

- 重复计数；
- 漏计结构化输出；
- 漏计重试；
- 漏计流式输出；
- 后续新增 Agent 时忘记埋点。

### 7.2 新增文件

```text
backend/models/usage.py
backend/repositories/usage_repository.py
backend/services/usage_tracking_service.py
backend/core/usage_context.py
```

### 7.3 标准化 Token 字段

不同模型 API 可能返回不同字段名，必须统一映射。

支持至少以下形式：

```json
{
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 30,
    "total_tokens": 130
  }
}
```

```json
{
  "usage": {
    "input_tokens": 100,
    "output_tokens": 30,
    "total_tokens": 130
  }
}
```

```json
{
  "data": {
    "usage": {
      "input_tokens": 100,
      "output_tokens": 30
    }
  }
}
```

并读取可能存在的：

```text
completion_tokens_details.reasoning_tokens
output_tokens_details.reasoning_tokens
prompt_tokens_details.cached_tokens
input_tokens_details.cached_tokens
```

建议定义：

```python
@dataclass(frozen=True)
class NormalizedTokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cached_input_tokens: int | None
    total_tokens: int | None
    source: Literal["provider", "estimated", "unavailable"]
    metadata: dict[str, int]
```

### 7.4 Token 计算规则

#### 规则 A：Provider 返回 Token

```text
token_source = provider
```

优先使用 Provider 返回的 `total_tokens`。

当 Provider 未返回 `total_tokens`，但返回 input/output 时：

```text
total_tokens = input_tokens + output_tokens
```

`reasoning_tokens` 通常已经包含在 output/completion tokens 中，不应再次加到 total，避免重复计算。

#### 规则 B：Provider 未返回 Token，但允许估算

```text
token_source = estimated
```

估算只用于趋势和管理参考，不作为结算或硬限额依据。

建议估算器：

```python
estimated_tokens = max(1, math.ceil(len(text.encode("utf-8")) / 3.5))
```

输入估算基于规范化 messages 文本，输出估算基于实际输出文本。

前端必须使用 `≈` 或“估算”标签展示。

#### 规则 C：无法获得或估算

```text
token_source = unavailable
input_tokens = NULL
output_tokens = NULL
total_tokens = NULL
```

不得写成 0。

### 7.5 非流式调用统计

`_generate()` 与 `_agenerate()` 中需要记录：

- 开始时间；
- trace_id；
- call_id；
- user_id/email；
- business_session_id；
- task_name；
- provider；
- model；
- request 是否流式；
- Provider usage；
- HTTP 状态码；
- Provider request ID；
- 重试次数；
- 耗时；
- success/error。

伪代码：

```python
call_id = uuid4()
started = monotonic()
last_status = None
attempt_count = 0

try:
    for attempt in ...:
        attempt_count = attempt + 1
        response = ...
        last_status = response.status_code
        data = response.json()
        usage = normalize_usage(data)
        result = self._chat_result_from_response(data)

        usage_tracker.record_success(
            call_id=call_id,
            usage=usage,
            latency_ms=elapsed_ms(started),
            attempt_count=attempt_count,
            provider_request_id=response.headers.get("x-request-id"),
            ...,
        )
        return result
except Exception as exc:
    usage_tracker.record_error(...)
    raise
```

### 7.6 流式调用统计

当前流式解析只返回文字，需要改造为同时收集最终 usage。

要求：

1. 每个流式调用只写入一条 `llm_usage_events`；
2. 不能为每个 chunk 写一条记录；
3. 解析流中的最后 usage 数据；
4. 若 Provider 不返回 usage，则使用输出累计文本进行估算；
5. 客户端取消连接时记录 `status=cancelled`；
6. 异常时记录 `status=error`；
7. 记录完成后再结束 generator 的 finally；
8. 不记录完整输出正文。

建议新增：

```python
@dataclass
class StreamUsageAccumulator:
    usage: dict | None = None
    output_text_parts: list[str] = field(default_factory=list)
```

为了避免大量内存，只用于估算时累计字符数，不需要保存完整文本。更推荐保存：

```text
output_utf8_bytes
output_char_count
```

而不是保存所有 chunk。

### 7.7 统计失败隔离

Token 统计是辅助功能，必须遵循：

```text
统计写库失败 != LLM 业务调用失败
```

实现要求：

- `UsageTrackingService.record_*()` 捕获数据库异常；
- 只输出结构化 warning 日志；
- 不抛出到业务 Agent；
- 不记录 Prompt 和 Response；
- 不无限重试；
- 单次记录失败最多重试 1 次。

### 7.8 防重复

`call_id` 必须唯一，并由数据库唯一约束保护。

写入使用：

```sql
INSERT ... ON CONFLICT (call_id) DO NOTHING
```

---

## 8. API 请求使用记录

### 8.1 新增中间件

新增：

```text
backend/middleware/api_request_audit.py
```

每次业务 API 请求完成后记录：

- trace_id；
- user_id；
- email_snapshot；
- HTTP method；
- FastAPI route template；
- status_code；
- duration_ms；
- created_at。

### 8.2 记录 route template，不记录原始 URL

正确：

```text
/api/v1/rehearsal/{session_id}/message
```

禁止：

```text
/api/v1/rehearsal/a-real-session-id/message?keyword=xxx
```

### 8.3 排除路径

默认不记录：

```text
/api/v1/health
/docs
/openapi.json
/favicon.ico
静态资源
```

认证接口由 `auth_audit_log` 记录，`/auth/login` 与 `/auth/register` 不需要重复写入敏感信息。

### 8.4 记录失败隔离

API 审计写入失败时，不影响原 API 响应。

---

## 9. 管理 API 设计

新增路由：

```text
backend/api/routes/admin.py
```

在 `backend/main.py` 注册：

```python
app.include_router(admin.router, prefix=settings.api_prefix)
```

所有端点统一依赖：

```python
Depends(require_super_admin_session)
```

新增：

```text
backend/schemas/admin.py
backend/repositories/admin_repository.py
backend/services/admin_analytics_service.py
backend/services/admin_audit_service.py
```

### 9.1 Dashboard 总览

```http
GET /api/v1/admin/overview
```

Query：

```text
from: ISO datetime，可选
to: ISO datetime，可选
timezone: IANA timezone，可选
```

默认最近 7 天。

响应示例：

```json
{
  "range": {
    "from": "2026-07-07T00:00:00Z",
    "to": "2026-07-14T00:00:00Z"
  },
  "users": {
    "total": 24,
    "active": 9,
    "whitelisted": 24,
    "disabled": 1
  },
  "sessions": {
    "business_sessions": 42,
    "active_auth_sessions": 5
  },
  "llm": {
    "calls": 318,
    "success_calls": 305,
    "error_calls": 13,
    "success_rate": 0.9591,
    "input_tokens": 428100,
    "output_tokens": 126300,
    "total_tokens": 554400,
    "estimated_tokens": 19800,
    "unavailable_calls": 3,
    "avg_latency_ms": 2840
  },
  "api": {
    "requests": 1420,
    "errors": 38,
    "error_rate": 0.0268
  }
}
```

### 9.2 Token 趋势

```http
GET /api/v1/admin/usage/trend
```

Query：

```text
from
to
granularity=hour|day
user_id
model
task_name
token_source
```

响应：

```json
{
  "items": [
    {
      "bucket": "2026-07-14T00:00:00Z",
      "input_tokens": 12000,
      "output_tokens": 4200,
      "total_tokens": 16200,
      "calls": 14,
      "errors": 1
    }
  ]
}
```

### 9.3 用户使用排名

```http
GET /api/v1/admin/usage/users
```

Query：

```text
from
to
search
status=all|active|disabled|whitelisted
sort=total_tokens|calls|last_active|sessions
order=asc|desc
page
page_size
```

每行返回：

```json
{
  "user_id": "uuid",
  "email": "user@bosch.com",
  "display_name": "User",
  "role": "user",
  "is_active": true,
  "whitelist_enabled": true,
  "last_login_at": "...",
  "last_active_at": "...",
  "business_sessions": 9,
  "api_requests": 210,
  "llm_calls": 56,
  "input_tokens": 80120,
  "output_tokens": 22100,
  "total_tokens": 102220,
  "provider_tokens": 98420,
  "estimated_tokens": 3800,
  "error_calls": 2
}
```

### 9.4 用户详情

```http
GET /api/v1/admin/usage/users/{user_id}
```

包含：

- 用户信息；
- 白名单状态；
- 最近登录；
- 最近活动；
- 活跃 Session 数；
- 业务 Session 数；
- Token 汇总；
- 模型分布；
- 任务分布；
- 最近 LLM 调用；
- 最近 API 请求；
- 最近认证审计。

### 9.5 LLM 调用记录

```http
GET /api/v1/admin/usage/events
```

Query：

```text
from
to
user_id
email
model
task_name
status
token_source
business_session_id
page
page_size
```

默认：

```text
page_size=50
max page_size=200
```

返回字段：

```text
time
email
task_name
model
is_stream
input_tokens
output_tokens
total_tokens
token_source
latency_ms
status
http_status
error_code
trace_id
business_session_id
```

不得返回：

```text
Prompt
Response
API Key
Cookie
完整 Provider Raw Response
```

### 9.6 API 使用记录

```http
GET /api/v1/admin/activity/api-requests
```

支持：

```text
from/to/user/status_code/route/page/page_size
```

### 9.7 登录审计

```http
GET /api/v1/admin/activity/auth-audit
```

读取现有 `auth_audit_log`，支持：

```text
from/to/email/event_type/success/page/page_size
```

IP 地址默认不返回前端；如确需展示，只显示脱敏值。

### 9.8 管理员操作审计

```http
GET /api/v1/admin/activity/admin-actions
```

支持：

```text
from/to/action_type/target_key/success/page/page_size
```

### 9.9 白名单列表

```http
GET /api/v1/admin/whitelist
```

支持：

```text
search
enabled
registered
page
page_size
```

返回：

```text
email
display_name
role
whitelist_enabled
registered
is_active
note
created_at
updated_at
last_login_at
last_active_at
total_tokens_30d
```

### 9.10 新增白名单

```http
POST /api/v1/admin/whitelist
```

请求：

```json
{
  "email": "user@bosch.com",
  "display_name": "User",
  "note": "HR Demo access",
  "create_local_account": true,
  "temporary_password": "12345678"
}
```

规则：

- 仅允许 `bosch.com` 和 `*.bosch.com`；
- 邮箱统一转小写；
- 密码不得进入日志和审计 JSON；
- 如果 `create_local_account=false`，只加白名单，等待用户注册；
- 如果创建本地账号，使用现有 PasswordService；
- 操作写入 `admin_action_audit_log`。

### 9.11 更新白名单

```http
PATCH /api/v1/admin/whitelist/{email}
```

请求：

```json
{
  "enabled": false,
  "note": "Access expired"
}
```

停用后必须：

1. 更新 `auth_whitelist.enabled=false`；
2. 更新 `app_users.is_active=false`；
3. 删除该用户 Redis 登录 Session；
4. 写管理员审计；
5. 不删除历史 Token 和使用记录。

### 9.12 删除白名单

```http
DELETE /api/v1/admin/whitelist/{email}
```

规则：

- 根管理员禁止删除；
- 删除白名单行；
- 用户表采用停用，不物理删除；
- 清除 Redis Session；
- 历史记录保留；
- 写管理员审计。

### 9.13 重置密码

可以保留当前：

```http
PATCH /api/v1/auth/admin/accounts/{email}/password
```

也可以迁移为：

```http
POST /api/v1/admin/accounts/{email}/reset-password
```

为了避免破坏现有前端和测试，建议：

- 新接口作为主接口；
- 旧接口保留兼容并内部调用相同 Service；
- 两者都必须使用 `require_super_admin_session`；
- 审计中只能记录“执行了密码重置”，不能记录密码或哈希。

### 9.14 CSV 导出

```http
GET /api/v1/admin/usage/export.csv
```

要求：

- 使用相同筛选条件；
- 最大导出行数由 `ADMIN_EXPORT_MAX_ROWS` 控制；
- 内容类型：`text/csv; charset=utf-8`；
- 加 UTF-8 BOM，方便 Excel 打开中文；
- 不导出 Prompt、Response、IP、User-Agent；
- 防止 CSV Formula Injection：以 `= + - @` 开头的单元格前增加 `'`。

---

## 10. 后端查询规则

### 10.1 时间范围

所有管理查询必须：

- 使用半开区间：`created_at >= from AND created_at < to`；
- `from` 和 `to` 最大跨度默认不超过 366 天；
- 默认最近 7 天；
- 数据库存 UTC；
- API 返回 ISO 8601 UTC；
- 前端负责本地化显示。

### 10.2 Token 汇总

只对非空 Token 进行求和：

```sql
SUM(COALESCE(total_tokens, 0))
```

同时必须返回：

```text
provider_tokens
estimated_tokens
unavailable_calls
```

不能只返回一个总数而隐藏数据质量。

### 10.3 活跃用户定义

用户在时间范围内满足任一条件即可视为活跃：

- 存在 `api_request_events`；
- 存在 `llm_usage_events`；
- 存在业务 `sessions.updated_at`；
- 成功登录。

### 10.4 最近使用时间

```text
last_active_at = GREATEST(
  app_users.last_login_at,
  MAX(api_request_events.created_at),
  MAX(llm_usage_events.created_at),
  MAX(sessions.updated_at)
)
```

### 10.5 分页

所有表格接口必须返回：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0,
  "total_pages": 0
}
```

不得一次性返回全部历史记录。

### 10.6 SQL 安全

- 所有筛选值使用参数绑定；
- 排序字段使用后端白名单映射，不允许直接拼接用户输入；
- 邮箱使用 CITEXT 或统一 lower；
- 禁止前端传任意 SQL 字段名。

---

## 11. 前端管理页面设计

### 11.1 路由与页面

保留：

```text
/admin
```

重构：

```text
frontend/src/pages/AdminPage.tsx
```

建议拆分为：

```text
frontend/src/pages/admin/AdminOverviewTab.tsx
frontend/src/pages/admin/AdminUsersTab.tsx
frontend/src/pages/admin/AdminUsageEventsTab.tsx
frontend/src/pages/admin/AdminWhitelistTab.tsx
frontend/src/pages/admin/AdminAuditTab.tsx

frontend/src/components/admin/AdminShell.tsx
frontend/src/components/admin/AdminTabs.tsx
frontend/src/components/admin/AdminFilterBar.tsx
frontend/src/components/admin/AdminKpiCard.tsx
frontend/src/components/admin/TokenTrendChart.tsx
frontend/src/components/admin/TopUsersBarChart.tsx
frontend/src/components/admin/ModelUsageDonut.tsx
frontend/src/components/admin/UsageDataTable.tsx
frontend/src/components/admin/UserDetailDrawer.tsx
frontend/src/components/admin/WhitelistDialog.tsx
frontend/src/components/admin/ConfirmActionDialog.tsx

frontend/src/api/admin.ts
frontend/src/types/admin.ts
```

### 11.2 页面信息架构

```text
Admin Console
├── Overview
│   ├── KPI cards
│   ├── Token trend
│   ├── Top users
│   ├── Model distribution
│   ├── Task distribution
│   └── Recent errors
├── Users & Tokens
│   ├── User search/filter
│   ├── User usage table
│   └── User detail drawer
├── Usage Records
│   ├── Date/model/task/status filters
│   ├── LLM usage table
│   └── CSV export
├── Whitelist & Accounts
│   ├── Add whitelist/account
│   ├── Enable/disable
│   ├── Reset password
│   ├── Delete authorization
│   └── Root admin lock
└── Security Audit
    ├── Login audit
    ├── Admin action audit
    └── API error records
```

### 11.3 顶部区域

显示：

```text
Bosch 品牌标识
标题：HRagent Admin Console
当前管理员：aah5sgh@bosch.com
统计范围
最后刷新时间
刷新按钮
返回工作台
```

### 11.4 Overview KPI

至少包含：

1. 活跃用户；
2. 总 Token；
3. LLM 调用次数；
4. 调用成功率；
5. 平均响应时间；
6. 白名单账号；
7. 业务 Session 数；
8. API 错误数。

每个 KPI 显示当前区间值，不伪造环比。只有后端返回前一周期数据时才显示环比。

### 11.5 图表

为了减少公司代理环境下的依赖安装，本期**不强制引入 ECharts/Recharts**，优先使用 React + 原生 SVG 实现轻量图表。

必须实现：

- Token 趋势折线/面积图；
- Top 用户水平柱状图；
- 模型使用占比环形图；
- 任务使用占比列表或环形图。

图表要求：

- 响应式；
- 支持 Hover Tooltip；
- 有空数据状态；
- 不只依赖颜色表达状态；
- 显示单位，例如 `K`、`M`；
- Token 估算值在 Tooltip 中标记；
- 不使用过度渐变、玻璃拟态和大圆角；
- 继续使用现有 Bosch 配色和 CSS 变量。

### 11.6 用户用量表

列：

```text
用户
账号状态
白名单状态
最近登录
最近活动
业务会话
API 请求
LLM 调用
输入 Token
输出 Token
总 Token
错误调用
操作
```

操作：

```text
查看详情
停用/启用
重置密码
```

### 11.7 LLM 调用记录表

列：

```text
时间
用户
业务任务
模型
流式/非流式
输入 Token
输出 Token
总 Token
数据来源
耗时
状态
```

Token 来源显示：

```text
精确
估算
不可用
```

估算值前使用：

```text
≈12,340
```

### 11.8 白名单页面

保留当前 AdminPage 的账号管理能力，但进行以下改造：

- 账号创建表单放入 Modal/Drawer；
- 列表增加搜索、分页和状态筛选；
- 显示备注、最近登录、最近使用和 30 天 Token；
- 根管理员行显示锁图标；
- 根管理员的停用、删除按钮禁用；
- 危险操作必须二次确认；
- 停用操作说明“将立即清除该用户登录 Session”；
- 删除只删除授权，不删除历史审计与 Token 数据。

### 11.9 审计页面

使用三个子标签：

```text
登录审计
管理员操作
API 错误
```

不得在页面中显示：

- 密码；
- 密码哈希；
- Cookie；
- Session ID；
- API Key；
- 完整用户输入；
- 完整模型回答。

### 11.10 前端权限

`AdminPage` 入口仍可使用：

```typescript
if (user?.role !== 'admin') return <Navigate to="/" replace />;
```

但必须额外校验邮箱：

```typescript
const isSuperAdmin =
  user?.role === 'admin' &&
  user.email.toLowerCase() === 'aah5sgh@bosch.com';
```

这只是 UX 保护，后端仍必须执行超级管理员依赖。

### 11.11 API 请求处理

新增统一 Admin API：

```text
frontend/src/api/admin.ts
```

要求：

- `credentials: 'include'`；
- 统一错误解析；
- 支持 `AbortController`；
- 切换筛选条件时取消旧请求；
- 表格分页请求后端；
- 401 跳登录；
- 403 跳首页并提示无权限；
- CSV 使用 Blob 下载；
- 不在前端缓存密码。

---

## 12. 白名单与账号服务重构

### 12.1 当前问题

现有管理员账号逻辑分布在：

```text
backend/api/routes/auth.py
backend/services/auth_service.py
backend/services/whitelist_service.py
frontend/src/pages/AdminPage.tsx
```

本次应提取公共逻辑，避免新旧接口重复 SQL。

### 12.2 推荐新增服务

```text
backend/services/admin_account_service.py
```

负责：

```text
list_accounts
create_whitelist_entry
create_local_account
update_whitelist
reset_password
disable_account
delete_authorization
protect_super_admin
clear_user_sessions
write_admin_audit
```

旧的 `AuthService.admin_*` 方法可以内部委托给 `AdminAccountService`，保证兼容已有测试和接口。

### 12.3 域名校验

必须保留并统一：

```python
domain == "bosch.com" or domain.endswith(".bosch.com")
```

禁止仅使用：

```python
email.endswith("bosch.com")
```

否则 `evilbosch.com` 可能被错误接受。

### 12.4 密码策略

继续复用现有：

```text
backend/services/password_service.py
```

当前规则：

- 纯数字密码至少 8 位；
- 非纯数字密码至少 15 位；
- 最大 128 位；
- Argon2id 存储。

前后端校验必须一致。不得在管理页面中显示旧密码。

---

## 13. 管理员操作审计

以下动作必须写入 `admin_action_audit_log`：

```text
whitelist_create
whitelist_enable
whitelist_disable
whitelist_delete
account_create
account_disable
password_reset
account_display_name_update
account_note_update
usage_export
```

审计 before/after 示例：

```json
{
  "before_state": {
    "email": "user@bosch.com",
    "enabled": true,
    "is_active": true,
    "note": "Demo"
  },
  "after_state": {
    "email": "user@bosch.com",
    "enabled": false,
    "is_active": false,
    "note": "Access expired"
  }
}
```

密码重置审计：

```json
{
  "action_type": "password_reset",
  "target_key": "user@bosch.com",
  "before_state": null,
  "after_state": {
    "password_reset": true
  }
}
```

禁止出现：

```text
password
password_hash
temporary_password
session_id
api_key
```

---

## 14. CSRF 与敏感写操作保护

当前认证使用 Cookie。管理端写操作必须增加 CSRF 防护。

### 14.1 推荐实现

新增：

```http
GET /api/v1/auth/csrf
```

- 后端生成随机 Token；
- Token 绑定当前 Redis Session；
- 前端保存于内存；
- POST/PATCH/PUT/DELETE 请求发送：

```http
X-CSRF-Token: <token>
```

### 14.2 校验范围

至少保护：

```text
/api/v1/admin/* 的全部写操作
/api/v1/auth/admin/* 的全部写操作
```

### 14.3 附加校验

- 校验 `Origin` 或 `Referer` 与允许的前端 Origin 匹配；
- Cookie 保持 `HttpOnly`、`Secure`、`SameSite=Lax/Strict`；
- CSRF Token 不写日志；
- Token 失效返回 403，不自动重试写操作。

---

## 15. 数据保留与隐私

### 15.1 默认保留期

| 数据 | 默认保留 |
|---|---:|
| `llm_usage_events` | 365 天 |
| `api_request_events` | 90 天 |
| `admin_action_audit_log` | 365 天或按公司政策 |
| `auth_audit_log` | 180 天或按公司政策 |
| 业务 Session | 保持项目现有策略 |

### 15.2 清理脚本

新增：

```text
scripts/cleanup_admin_usage.py
```

支持：

```bash
python scripts/cleanup_admin_usage.py --dry-run
python scripts/cleanup_admin_usage.py
```

删除规则：

```sql
DELETE FROM llm_usage_events
WHERE created_at < NOW() - make_interval(days => %s);

DELETE FROM api_request_events
WHERE created_at < NOW() - make_interval(days => %s);
```

脚本要求：

- 支持 dry-run；
- 分批删除，每批不超过 10,000 行；
- 输出删除数量；
- 不删除管理员审计，除非配置明确允许；
- 可由服务器 Cron 每天执行一次。

### 15.3 隐私边界

用量系统只记录：

```text
谁使用
何时使用
使用哪个模型
使用哪个任务
调用结果
Token 数量
耗时
```

用量系统不记录：

```text
用户说了什么
模型回答了什么
上传了什么文档
密码是什么
API Key 是什么
Session Cookie 是什么
```

---

## 16. 文件改造清单

### 16.1 后端新增

```text
backend/api/routes/admin.py
backend/schemas/admin.py
backend/models/usage.py
backend/core/usage_context.py
backend/middleware/request_context.py
backend/middleware/api_request_audit.py
backend/repositories/usage_repository.py
backend/repositories/admin_repository.py
backend/services/usage_tracking_service.py
backend/services/admin_analytics_service.py
backend/services/admin_account_service.py
backend/services/admin_audit_service.py
backend/db/migrations/0003_add_admin_usage_tables.sql
scripts/cleanup_admin_usage.py

tests/test_admin_superuser_authorization.py
tests/test_usage_normalization.py
tests/test_usage_tracking_non_stream.py
tests/test_usage_tracking_stream.py
tests/test_admin_analytics_api.py
tests/test_admin_whitelist_api.py
tests/test_admin_audit_log.py
tests/test_api_request_audit.py
```

### 16.2 后端修改

```text
backend/config/settings.py
backend/core/auth_dependency.py
backend/core/session_context.py
backend/main.py
backend/repositories/postgres_repository.py
backend/services/langchain_llm_service.py
backend/services/auth_service.py
backend/services/whitelist_service.py
backend/services/auth_session_service.py
backend/api/routes/auth.py
backend/api/routes/guidance.py
backend/api/routes/rehearsal.py
backend/api/routes/reports.py
backend/api/routes/setup.py
```

### 16.3 前端新增

```text
frontend/src/api/admin.ts
frontend/src/types/admin.ts
frontend/src/pages/admin/AdminOverviewTab.tsx
frontend/src/pages/admin/AdminUsersTab.tsx
frontend/src/pages/admin/AdminUsageEventsTab.tsx
frontend/src/pages/admin/AdminWhitelistTab.tsx
frontend/src/pages/admin/AdminAuditTab.tsx
frontend/src/components/admin/AdminShell.tsx
frontend/src/components/admin/AdminTabs.tsx
frontend/src/components/admin/AdminFilterBar.tsx
frontend/src/components/admin/AdminKpiCard.tsx
frontend/src/components/admin/TokenTrendChart.tsx
frontend/src/components/admin/TopUsersBarChart.tsx
frontend/src/components/admin/ModelUsageDonut.tsx
frontend/src/components/admin/UsageDataTable.tsx
frontend/src/components/admin/UserDetailDrawer.tsx
frontend/src/components/admin/WhitelistDialog.tsx
frontend/src/components/admin/ConfirmActionDialog.tsx
```

### 16.4 前端修改

```text
frontend/src/pages/AdminPage.tsx
frontend/src/App.tsx
frontend/src/api/auth.ts
frontend/src/types/auth.ts
frontend/src/store/authStore.tsx
frontend/src/styles/global.css
```

---

## 17. 实施顺序

Coding AI 必须按以下顺序实施，禁止先写 UI 再补数据链路。

### Phase 1：数据库与权限

1. 增加 Settings；
2. 增加超级管理员依赖；
3. 建立三张新表；
4. 扩展白名单表；
5. 同步修改 `PostgresRepository.init_schema()`；
6. 编写迁移和权限测试。

### Phase 2：Token 统计链路

1. 增加 Usage Context；
2. 增加 UsageRepository；
3. 增加 UsageTrackingService；
4. 非流式埋点；
5. 流式埋点；
6. Provider usage 标准化；
7. 估算与 unavailable 逻辑；
8. 测试重试、失败、取消和重复写入。

### Phase 3：API 使用记录

1. 增加 trace_id middleware；
2. 增加 API request audit；
3. 排除 health/docs/static；
4. 测试不记录请求正文。

### Phase 4：管理 API

1. Overview；
2. Trend；
3. Users；
4. User detail；
5. Usage events；
6. API/Auth/Admin audit；
7. Whitelist CRUD；
8. CSV export。

### Phase 5：前端管理页

1. Admin Shell 和 Tabs；
2. Overview Dashboard；
3. Users & Tokens；
4. Usage Records；
5. Whitelist & Accounts；
6. Security Audit；
7. 响应式和空状态；
8. 错误处理和权限跳转。

### Phase 6：验收与回归

1. 后端单元测试；
2. API 集成测试；
3. 前端 TypeScript build；
4. Docker Compose 启动；
5. 真正执行一次 LLM 调用并核对 usage；
6. 管理页核对相同 Token；
7. 停用用户并确认 Session 失效；
8. 核对审计记录；
9. 确认普通用户无法访问管理 API。

---

## 18. 测试要求

### 18.1 权限测试

必须覆盖：

```text
未登录访问 /api/v1/admin/* -> 401
普通用户访问 -> 403
role=admin 但邮箱不是 aah5sgh@bosch.com -> 403
aah5sgh@bosch.com 且 role=admin -> 200
AUTH_ENABLED=false 且非 local 安全模式 -> 403
```

### 18.2 根管理员保护测试

```text
停用根管理员 -> 400/403
删除根管理员 -> 400/403
移出白名单 -> 400/403
普通管理员重置根管理员密码 -> 403
```

### 18.3 Token 标准化测试

覆盖：

```text
prompt_tokens/completion_tokens/total_tokens
input_tokens/output_tokens/total_tokens
nested data.usage
reasoning_tokens
cached_tokens
只有 total_tokens
usage 缺失
非法负数
字符串数字
None
```

### 18.4 非流式统计测试

验证：

- 成功调用写一条；
- 失败调用写一条 error；
- 重试后成功只写一条最终记录，并记录 attempt_count；
- `call_id` 重复不会重复写；
- Token 与 Mock Provider 返回一致；
- 数据库写入失败不影响 LLM 返回。

### 18.5 流式统计测试

验证：

- 多个 chunk 只写一条；
- 最终 usage 可以读取；
- 没有 usage 时进入 estimated；
- 关闭估算时进入 unavailable；
- 客户端取消时 status=cancelled；
- 不存储输出文本。

### 18.6 API 审计测试

验证：

- 记录 route template；
- 不记录 path 中的真实 session_id；
- 不记录 query；
- 不记录 body；
- health/docs 不记录；
- 500 仍记录；
- 写库失败不改变原响应。

### 18.7 白名单测试

验证：

- Bosch 域名可添加；
- `evilbosch.com` 不可添加；
- 停用后用户立即失去 Session；
- 删除后历史 usage 仍存在；
- 密码不进入审计；
- 重复添加幂等；
- 搜索和分页正确。

### 18.8 Analytics 测试

验证：

- 时间边界使用半开区间；
- Provider 和 estimated 分开统计；
- unavailable call 单独计数；
- 无数据返回 0 和空数组，不返回 500；
- 普通用户不能查询他人用量；
- 分页 total 正确；
- 排序字段不可注入。

### 18.9 前端测试与构建

至少执行：

```bash
cd frontend
npm run build
```

并验证：

- 普通用户看不到管理入口；
- 直接输入 `/admin` 会跳转；
- 管理员可切换 Tab；
- 无数据页面正常；
- API 失败有明确提示；
- 表格移动端可横向滚动；
- 根管理员危险按钮禁用；
- CSV 导出正常。

---

## 19. 验收标准

### 19.1 功能验收

- [ ] `aah5sgh@bosch.com` 可以进入 `/admin`；
- [ ] 其他用户无法访问管理 API；
- [ ] Dashboard 显示用户、调用和 Token 汇总；
- [ ] Token 趋势图能够按 24 小时、7 天、30 天筛选；
- [ ] 用户表能够查看每个用户 Token；
- [ ] 能够查看每次模型调用记录；
- [ ] 能区分精确、估算、不可用 Token；
- [ ] 能查看登录和管理员审计；
- [ ] 能添加、启用、停用、删除白名单；
- [ ] 停用用户后其 Redis Session 立即失效；
- [ ] 根管理员无法被停用或删除；
- [ ] 能导出筛选后的 CSV；
- [ ] 不存储 Prompt 和完整 Response。

### 19.2 数据准确性验收

选择一次 Mock 或真实模型调用：

```text
Provider usage.total_tokens
=
llm_usage_events.total_tokens
=
管理页面对应调用记录 total_tokens
```

允许模型不返回 usage，但此时必须显示：

```text
estimated 或 unavailable
```

不能显示为精确值。

### 19.3 性能验收

在 100,000 条 `llm_usage_events` 测试数据下：

```text
Overview API p95 < 500 ms
User usage list p95 < 700 ms
Usage event page p95 < 500 ms
默认分页 50 条
前端首屏不一次加载全部明细
```

若测试环境资源不足，可接受略高，但不得执行无分页全表扫描。

### 19.4 安全验收

- [ ] 所有 Admin API 后端校验超级管理员；
- [ ] 管理写操作具有 CSRF 保护；
- [ ] 密码、Cookie、API Key 不在日志和审计；
- [ ] CSV 防公式注入；
- [ ] SQL 排序字段使用白名单；
- [ ] 根管理员保护由后端强制；
- [ ] `AUTH_ENABLED=false` 不会在生产暴露管理端。

---

## 20. Docker 与部署

本功能不新增容器，继续使用现有：

```text
frontend
backend
postgres
redis
```

### 20.1 数据库初始化

```bash
docker compose exec backend python scripts/init_postgres.py
```

### 20.2 管理员账号初始化

继续使用：

```bash
docker compose exec -it backend python scripts/provision_authorized_accounts.py
```

必须确认：

```sql
SELECT email, role, is_active
FROM app_users
WHERE lower(email::text) = 'aah5sgh@bosch.com';
```

预期：

```text
email = aah5sgh@bosch.com
role = admin
is_active = true
```

白名单预期：

```sql
SELECT email, enabled
FROM auth_whitelist
WHERE lower(email::text) = 'aah5sgh@bosch.com';
```

预期：

```text
enabled = true
```

### 20.3 构建

```bash
docker compose build backend frontend
docker compose up -d
```

### 20.4 健康检查

```bash
curl -k https://localhost:8443/api/v1/health
```

登录管理员后检查：

```text
GET /api/v1/admin/overview -> 200
GET /api/v1/admin/usage/users -> 200
GET /api/v1/admin/whitelist -> 200
```

普通用户检查：

```text
GET /api/v1/admin/overview -> 403
```

---

## 21. 回滚方案

### 21.1 应用回滚

- 回滚前端 AdminPage；
- 从 `main.py` 移除 admin router；
- 关闭：

```env
ADMIN_CONSOLE_ENABLED=false
ADMIN_USAGE_TRACKING_ENABLED=false
```

### 21.2 数据库回滚

默认不建议立即删除事实表，以保留审计数据。

如必须清理：

```sql
DROP TABLE IF EXISTS admin_action_audit_log;
DROP TABLE IF EXISTS api_request_events;
DROP TABLE IF EXISTS llm_usage_events;
```

删除前必须先备份。

白名单新增字段可以保留，不影响旧版本。

### 21.3 业务保护

Token 统计关闭后：

- LLM 调用仍能正常运行；
- 用户登录和业务流程不受影响；
- 管理页面显示“用量统计已关闭”；
- 不得因为统计组件异常导致 HRagent 不可用。

---

## 22. Coding AI 最终执行指令

请严格基于当前项目实现，不得重写整套应用。

### 22.1 必须先阅读

```text
AGENTS.md
backend/config/settings.py
backend/core/auth_dependency.py
backend/core/session_context.py
backend/repositories/postgres_repository.py
backend/services/langchain_llm_service.py
backend/services/auth_service.py
backend/services/whitelist_service.py
backend/services/auth_session_service.py
backend/api/routes/auth.py
backend/main.py
frontend/src/pages/AdminPage.tsx
frontend/src/api/auth.ts
frontend/src/store/authStore.tsx
frontend/src/App.tsx
frontend/src/styles/global.css
```

### 22.2 编码约束

1. 保留现有 API 兼容性；
2. 保留现有登录、注册和业务流程；
3. 不引入新的后端框架；
4. 不引入新的数据库；
5. 图表优先使用原生 SVG；
6. SQL 必须参数化；
7. 所有新 Pydantic Schema 必须有明确字段类型；
8. 所有 Admin API 必须分页；
9. 所有 Admin 写操作必须审计；
10. 所有 Token 数据必须标注来源；
11. 不能将 unavailable 当成 0；
12. 不能存 Prompt、Response、密码、Cookie 或 API Key；
13. 统计写入失败不能中断业务；
14. 根管理员保护必须写后端测试；
15. 修改后必须更新 README 或新增管理员使用说明。

### 22.3 必须交付

```text
1. 完整代码变更
2. 数据库迁移
3. 新增与修改文件清单
4. 单元测试和集成测试
5. 前端 build 结果
6. Docker Compose 启动验证
7. 管理员操作手册
8. 回滚说明
9. 已知限制
10. Token 精确/估算/不可用的测试证据
```

### 22.4 完成定义

只有同时满足以下条件才可声明完成：

```text
- 后端测试通过；
- 前端 npm run build 通过；
- Docker Compose 可启动；
- 管理员可查看用户用量和 Token；
- 普通用户返回 403；
- 白名单操作可用；
- 根管理员不可被删除或停用；
- 流式和非流式调用都有统计；
- 不记录 Prompt 和完整回复；
- 管理操作均有审计记录。
```

---

## 23. 推荐最终页面效果

管理页面应体现为一个内部运营控制台，而不是普通用户工作台的简单复制：

```text
┌────────────────────────────────────────────────────────────────────┐
│ Bosch | HRagent Admin Console        aah5sgh@bosch.com  [返回工作台] │
├────────────────────────────────────────────────────────────────────┤
│ Overview | Users & Tokens | Usage Records | Whitelist | Audit      │
├────────────────────────────────────────────────────────────────────┤
│ [活跃用户] [总Token] [调用次数] [成功率] [平均耗时] [白名单账号]     │
├────────────────────────────────────────────────────────────────────┤
│ Token Trend                                  Model Distribution     │
│ ┌───────────────────────────────────────┐     ┌─────────────────┐   │
│ │             SVG Trend Chart           │     │   Donut Chart   │   │
│ └───────────────────────────────────────┘     └─────────────────┘   │
├────────────────────────────────────────────────────────────────────┤
│ Top Users by Token                                                 │
│ User                  Calls     Input     Output     Total   Status │
│ user1@bosch.com          56      80K        22K       102K   Active │
│ user2@bosch.com          40      55K        18K        73K   Active │
└────────────────────────────────────────────────────────────────────┘
```

整体设计继续遵循当前 Bosch 项目风格：

- 清晰；
- 克制；
- 信息密度适中；
- 少用大圆角；
- 不使用炫目的渐变；
- 状态颜色符合语义；
- 重要数据优先；
- 表格和筛选可快速操作。

---

## 24. 最终结论

该功能与当前 HRagent 技术栈高度匹配，开发风险可控。

最关键的技术点不是绘制管理页面，而是建立可靠的数据链路：

```text
登录用户
  -> Request Context
  -> LLM 统一适配器
  -> Token 标准化
  -> PostgreSQL 用量事实表
  -> Admin Analytics API
  -> React 可视化管理页面
```

只要严格遵循“统一埋点、后端强鉴权、Token 来源标记、隐私数据不落表、根管理员不可变”五项原则，该方案可以直接进入 Coding 实施。
