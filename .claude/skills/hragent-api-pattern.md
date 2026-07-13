---
name: hragent-api-pattern
description: Standard API development pattern for HRagent-05 FastAPI backend. Use when adding a new API endpoint, creating a new business domain module, or understanding the service→schema→route architecture.
triggers:
  - 新增接口
  - 新增 API
  - 路由
  - route
  - service
  - schema
  - 后端架构
  - FastAPI
scope: HRagent-05
---

# HRagent-05 API 服务开发模式

来源：[backend/main.py](../../backend/main.py)、[backend/api/](../../backend/api/)、[backend/services/](../../backend/services/)、[backend/schemas/](../../backend/schemas/)

## 三层架构

```
api/routes/xxx.py       # 路由层：HTTP 请求/响应处理、参数校验、状态码
    ↓ 调用
services/xxx_service.py  # 服务层：业务逻辑、协调多个 agent/repository
    ↓ 使用
schemas/xxx.py           # Schema 层：Pydantic 请求/响应模型
```

## 路由注册

在 [main.py](../../backend/main.py) 中：

```python
from backend.api.routes import xxx

# 公开路由（不需要认证）
app.include_router(health.router, prefix=settings.api_prefix)

# 受保护路由（需要登录）
protected_routers = [
    sessions.router, documents.router, employees.router,
    setup.router, guidance.router, rehearsal.router,
    reports.router, tts.router,
]
for router in protected_routers:
    dependencies = [Depends(get_current_user)] if settings.auth_enabled else []
    app.include_router(router, prefix=settings.api_prefix, dependencies=dependencies)
```

**规则：**
- 一般业务路由放在 `protected_routers` 列表中。
- 只有 health、auth（register/login）、asr 是公开或条件公开的。

## 路由文件模板

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from backend.api.dependencies import get_xxx_service
from backend.schemas.xxx import XxxRequest, XxxResponse
from backend.services.xxx_service import XxxService

router = APIRouter(prefix="/xxx", tags=["xxx"])


@router.post("/action", response_model=XxxResponse)
async def do_action(
    request: XxxRequest,
    service: XxxService = Depends(get_xxx_service),
):
    try:
        return await service.do_action(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
```

## 依赖注入

在 [api/dependencies.py](../../backend/api/dependencies.py) 中注册服务工厂：

```python
def get_xxx_service() -> XxxService:
    return XxxService()
```

## Schema 规范

```python
# 请求模型
class XxxRequest(BaseModel):
    session_id: str
    param1: str = Field(..., min_length=1)
    param2: int | None = None  # 可选字段

# 响应模型
class XxxResponse(BaseModel):
    id: str
    status: str
    data: dict | None = None
```

**兼容性要求：**
- 新增字段必须为可选（`| None = None`）并有默认值。
- 不删除已有字段、不改字段类型。
- 不改变已有 API 的响应结构。

## Service 服务模板

```python
from backend.config.settings import Settings, get_settings
from backend.services.cache_service import CacheService

class XxxService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache = CacheService(self.settings)

    async def do_action(self, request: XxxRequest) -> XxxResponse:
        # 1. 尝试缓存
        # 2. 执行核心逻辑
        # 3. 写入缓存
        # 4. 返回结果
        ...
```

## 新增业务域 Checklist

新增一个完整的业务域（如 `feedback`）需要创建/修改：

1. `backend/schemas/feedback.py` — 请求/响应 Pydantic 模型
2. `backend/services/feedback_service.py` — 业务逻辑
3. `backend/api/routes/feedback.py` — FastAPI router
4. `backend/api/dependencies.py` — 添加 `get_feedback_service` 工厂
5. `backend/main.py` — 注册 router 到 `protected_routers`
6. 如需 LLM prompt：`backend/prompts/feedback/xxx.jinja2`
7. 如需配置：`backend/business_config/feedback/xxx.yaml`
8. 测试：`tests/test_feedback_service.py`

## 异常处理

全局异常处理器在 [api/error_handlers.py](../../backend/api/error_handlers.py)：

```python
def register_error_handlers(app: FastAPI):
    # 统一处理各类异常，返回一致的错误格式
    ...
```

自定义异常在 [exceptions/](../../backend/exceptions/)：
- `llm_errors.py` — LLM 调用异常
- `parser_errors.py` — 文档解析异常
- `workflow_errors.py` — 工作流异常

## 禁止事项

1. ❌ 不在路由层直接调用 LLM 或数据库
2. ❌ 不改变已有 API 的响应结构
3. ❌ 不把敏感配置（API key）暴露到响应中
4. ❌ 不随意修改 API prefix（`/api/v1`）
5. ❌ 不绕过 `get_current_user` 认证（除非是公开路由）
