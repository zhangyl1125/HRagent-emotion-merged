# HRagent-05 用户注册登录与认证安全改造方案

## 1. 需求目标

在 HRagent-05 前端页面新增用户注册与登录能力，并在后端实现认证、会话、白名单、并发控制和未来 SSO 升级预留。

### 1.1 本期必须完成

| 模块 | 要求 |
|---|---|
| 前端 | 新增 `LoginPage`、`RegisterPage`、`ProtectedRoute`、登录态展示与登出 |
| 后端 | 新增认证接口、用户模型、密码哈希服务、会话服务、认证依赖 |
| 密码安全 | 使用 `Argon2id + random salt + cost factor`，不存明文密码 |
| 白名单 | 仅允许 `aah5sgh@bosch.com`、`uay4sgh@bosch.com` 注册和登录 |
| 并发 | 支持并限制最大活跃会话数 `100` |
| 未来 SSO | 预留 `auth_provider`、`provider_subject`、OIDC 登录入口和账号绑定字段 |

### 1.2 本期不做

- 不接入正式 Bosch SSO。
- 不做短信、邮箱验证码、MFA。
- 不做复杂 RBAC，仅保留 `user/admin` 角色字段。
- 不改变现有 HRagent 业务流程，只在进入系统前增加认证保护。

---

## 2. 推荐总体架构

```text
frontend
  ├── /login
  ├── /register
  ├── ProtectedRoute
  └── AuthContext / Zustand Store
        │
        ▼
backend FastAPI
  ├── /api/v1/auth/register
  ├── /api/v1/auth/login
  ├── /api/v1/auth/logout
  ├── /api/v1/auth/me
  ├── AuthMiddleware / get_current_user
  ├── PasswordService(Argon2id)
  ├── WhitelistService
  └── SessionService(Redis + HttpOnly Cookie)
        │
        ├── PostgreSQL: users, auth_whitelist, auth_audit_log
        └── Redis: session:{sid}, auth:active_sessions, rate_limit:*
```

---

## 3. 文件改造清单

### 3.1 后端新增文件

```text
backend/api/routes/auth.py
backend/schemas/auth.py
backend/models/user.py
backend/services/password_service.py
backend/services/auth_service.py
backend/services/session_service.py
backend/services/whitelist_service.py
backend/services/rate_limit_service.py
backend/core/security.py
backend/core/auth_dependency.py
backend/db/migrations/xxxx_add_auth_tables.sql
tests/test_auth_register_login.py
tests/test_auth_whitelist.py
tests/test_auth_concurrency.py
```

### 3.2 前端新增文件

```text
frontend/src/pages/LoginPage.tsx
frontend/src/pages/RegisterPage.tsx
frontend/src/routes/ProtectedRoute.tsx
frontend/src/store/authStore.ts
frontend/src/api/auth.ts
frontend/src/types/auth.ts
```

### 3.3 需要修改的现有文件

```text
backend/main.py
backend/core/config.py
frontend/src/App.tsx
frontend/src/api/client.ts
frontend/src/layouts/AppLayout.tsx
docker-compose.yml
.env.example
```

---

## 4. 数据库设计

### 4.1 用户表

```sql
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email CITEXT NOT NULL UNIQUE,
    display_name VARCHAR(120),
    password_hash TEXT,
    auth_provider VARCHAR(20) NOT NULL DEFAULT 'local',
    provider_subject VARCHAR(255),
    role VARCHAR(30) NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_email_verified BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT app_users_auth_provider_check
      CHECK (auth_provider IN ('local', 'oidc'))
);
```

### 4.2 白名单表

```sql
CREATE TABLE IF NOT EXISTS auth_whitelist (
    email CITEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO auth_whitelist (email, enabled, note)
VALUES
  ('aah5sgh@bosch.com', TRUE, 'initial whitelist'),
  ('uay4sgh@bosch.com', TRUE, 'initial whitelist')
ON CONFLICT (email) DO UPDATE SET enabled = EXCLUDED.enabled;
```

### 4.3 登录审计表

```sql
CREATE TABLE IF NOT EXISTS auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    email CITEXT,
    event_type VARCHAR(40) NOT NULL,
    success BOOLEAN NOT NULL,
    reason VARCHAR(120),
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_audit_email_created
ON auth_audit_log(email, created_at DESC);
```

### 4.4 SSO 预留索引

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_oidc_subject
ON app_users(auth_provider, provider_subject)
WHERE provider_subject IS NOT NULL;
```

---

## 5. 密码存储方案：加盐 + KDF

### 5.1 推荐算法

本项目本期推荐：

```text
algorithm: Argon2id
memory_cost: 19456 KiB
time_cost: 2
parallelism: 1
salt_len: 16 bytes
hash_len: 32 bytes
target_verify_time: < 1s
```

说明：

- `Argon2id` 自带随机 salt，最终保存的是完整 encoded hash。
- 数据库只保存 `password_hash`，不保存明文密码。
- 不要自己手写 salt 拼接逻辑，交给成熟库处理。
- 登录成功后，如 `check_needs_rehash=true`，自动升级 hash 参数。

### 5.2 依赖安装

```bash
pip install "argon2-cffi>=23.1.0" "email-validator>=2.0.0"
```

### 5.3 PasswordService 示例

```python
# backend/services/password_service.py

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError


class PasswordService:
    def __init__(self) -> None:
        self._ph = PasswordHasher(
            time_cost=2,
            memory_cost=19456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )

    def hash_password(self, plain_password: str) -> str:
        self._validate_password_policy(plain_password)
        return self._ph.hash(plain_password)

    def verify_password(self, plain_password: str, password_hash: str) -> bool:
        try:
            return self._ph.verify(password_hash, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._ph.check_needs_rehash(password_hash)
        except (VerificationError, InvalidHashError):
            return True

    def _validate_password_policy(self, password: str) -> None:
        if len(password) < 15:
            raise ValueError("PASSWORD_TOO_SHORT")
        if len(password) > 128:
            raise ValueError("PASSWORD_TOO_LONG")
```

### 5.4 密码策略

```yaml
min_length: 15
max_length: 128
allow_unicode: true
allow_whitespace: true
composition_rules: false
allow_paste: true
password_strength_meter: recommended
periodic_rotation: false
forced_rotation_when_leaked_or_reset: true
```

---

## 6. 白名单策略

### 6.1 白名单源

本期使用数据库表 + 环境变量双层控制：

```bash
AUTH_ALLOWED_EMAILS=aah5sgh@bosch.com,uay4sgh@bosch.com
AUTH_WHITELIST_ENABLED=true
```

推荐逻辑：

```text
1. 注册时检查 email 是否在 auth_whitelist 且 enabled=true。
2. 登录时再次检查 email 是否仍在 auth_whitelist。
3. 用户已注册但被移出白名单时，禁止继续登录。
4. 管理端未完成前，可以通过 SQL 或 seed 脚本维护白名单。
```

### 6.2 WhitelistService 示例

```python
# backend/services/whitelist_service.py

class WhitelistService:
    def __init__(self, repo, config) -> None:
        self.repo = repo
        self.config = config

    async def is_allowed(self, email: str) -> bool:
        normalized = email.strip().lower()

        if not self.config.AUTH_WHITELIST_ENABLED:
            return True

        env_allowed = {
            item.strip().lower()
            for item in self.config.AUTH_ALLOWED_EMAILS.split(",")
            if item.strip()
        }

        if normalized in env_allowed:
            return True

        return await self.repo.exists_enabled_email(normalized)
```

---

## 7. 会话设计

### 7.1 推荐方案

使用 `HttpOnly + Secure + SameSite=Lax` Cookie 保存不透明 `session_id`，Redis 保存会话内容。

理由：

- 前端 JS 不能读取 Cookie，降低 XSS 窃取 token 风险。
- Redis 可快速撤销会话。
- 未来切换 OIDC SSO 时仍可复用同一套应用会话。
- 不需要在前端 localStorage 保存 token。

### 7.2 Cookie 配置

```yaml
cookie_name: hragent_session
http_only: true
secure: true
same_site: lax
path: /
idle_timeout_minutes: 30
absolute_timeout_hours: 8
```

开发环境如无 HTTPS，可临时：

```bash
AUTH_COOKIE_SECURE=false
```

生产环境必须：

```bash
AUTH_COOKIE_SECURE=true
```

### 7.3 Redis Key

```text
session:{session_id} -> {
  "user_id": "...",
  "email": "...",
  "role": "user",
  "created_at": "...",
  "last_seen_at": "..."
}

auth:active_sessions -> sorted set
  score = last_seen_timestamp
  member = session_id
```

---

## 8. 并发 100 用户方案

### 8.1 需要明确的业务含义

当前白名单只有两个邮箱，因此“100 并发”建议定义为：

```text
系统最多允许 100 个活跃会话同时使用。
如果未来需要 100 个独立用户，需要扩展 whitelist 或切换到 SSO group-based allowlist。
```

### 8.2 配置项

```bash
AUTH_MAX_ACTIVE_SESSIONS=100
AUTH_SESSION_IDLE_TIMEOUT_MINUTES=30
AUTH_SESSION_ABSOLUTE_TIMEOUT_HOURS=8

AUTH_LOGIN_HASH_MAX_CONCURRENCY=8
AUTH_LOGIN_RATE_LIMIT_PER_EMAIL=5/minute
AUTH_LOGIN_RATE_LIMIT_PER_IP=20/minute

WEB_CONCURRENCY=4
UVICORN_LIMIT_CONCURRENCY=200
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=20
REDIS_MAX_CONNECTIONS=50
```

### 8.3 活跃会话限制逻辑

```python
# backend/services/session_service.py

class SessionService:
    async def create_session(self, user) -> str:
        await self.cleanup_expired_sessions()

        active_count = await self.redis.zcard("auth:active_sessions")
        if active_count >= self.config.AUTH_MAX_ACTIVE_SESSIONS:
            raise RuntimeError("MAX_ACTIVE_SESSIONS_REACHED")

        session_id = self.generate_session_id()
        await self.redis.setex(
            f"session:{session_id}",
            self.config.SESSION_TTL_SECONDS,
            self.serialize_session(user),
        )
        await self.redis.zadd("auth:active_sessions", {session_id: self.now_ts()})
        return session_id
```

### 8.4 Argon2 登录并发保护

Argon2id 是有意消耗 CPU/RAM 的算法，因此不能让无限登录请求同时做 KDF。建议对登录哈希校验设置单独并发上限：

```python
# backend/services/auth_service.py

import asyncio

hash_semaphore = asyncio.Semaphore(8)

async def verify_password_limited(password_service, password, password_hash):
    async with hash_semaphore:
        return password_service.verify_password(password, password_hash)
```

### 8.5 负载测试

```bash
pip install locust

locust -f tests/load/locustfile.py \
  --headless \
  -u 100 \
  -r 10 \
  --run-time 5m \
  --host http://localhost:8111
```

验收指标建议：

```yaml
active_sessions: 100
GET /api/v1/auth/me p95: < 300ms
业务普通接口 p95: < 800ms
登录接口 p95: < 3000ms
error_rate: < 1%
database_pool_exhausted: false
redis_connection_exhausted: false
```

---

## 9. API 设计

### 9.1 Register

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "aah5sgh@bosch.com",
  "password": "a-long-passphrase-123",
  "display_name": "AAH5SGH"
}
```

成功响应：

```json
{
  "success": true,
  "message": "Account created. Please sign in."
}
```

失败响应统一：

```json
{
  "success": false,
  "message": "Registration failed. Please check your information or contact administrator."
}
```

### 9.2 Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "aah5sgh@bosch.com",
  "password": "a-long-passphrase-123"
}
```

成功响应：

```json
{
  "success": true,
  "user": {
    "email": "aah5sgh@bosch.com",
    "display_name": "AAH5SGH",
    "role": "user"
  }
}
```

后端同时设置 Cookie：

```http
Set-Cookie: hragent_session=<opaque-session-id>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=28800
```

登录失败统一：

```json
{
  "success": false,
  "message": "Invalid email or password."
}
```

### 9.3 Me

```http
GET /api/v1/auth/me
```

成功响应：

```json
{
  "authenticated": true,
  "user": {
    "email": "aah5sgh@bosch.com",
    "display_name": "AAH5SGH",
    "role": "user"
  }
}
```

### 9.4 Logout

```http
POST /api/v1/auth/logout
```

响应：

```json
{
  "success": true
}
```

---

## 10. 后端路由示例

```python
# backend/api/routes/auth.py

from fastapi import APIRouter, Depends, Response, Request, HTTPException, status
from backend.schemas.auth import RegisterRequest, LoginRequest, AuthUserResponse
from backend.services.auth_service import AuthService
from backend.core.auth_dependency import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
async def register(payload: RegisterRequest, auth_service: AuthService = Depends()):
    try:
        await auth_service.register(payload)
        return {"success": True, "message": "Account created. Please sign in."}
    except Exception:
        return {
            "success": False,
            "message": "Registration failed. Please check your information or contact administrator.",
        }


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(),
):
    result = await auth_service.login(payload, request)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    response.set_cookie(
        key="hragent_session",
        value=result.session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=8 * 60 * 60,
        path="/",
    )
    return {"success": True, "user": result.user}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return {"authenticated": True, "user": current_user}


@router.post("/logout")
async def logout(
    response: Response,
    auth_service: AuthService = Depends(),
    current_user=Depends(get_current_user),
):
    await auth_service.logout(current_user.session_id)
    response.delete_cookie("hragent_session", path="/")
    return {"success": True}
```

---

## 11. 前端实现方案

### 11.1 路由保护

```tsx
// frontend/src/routes/ProtectedRoute.tsx

import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

export function ProtectedRoute() {
  const { initialized, user } = useAuthStore();

  if (!initialized) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
```

### 11.2 API Client

```ts
// frontend/src/api/client.ts

import axios from "axios";

export const apiClient = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);
```

### 11.3 Auth API

```ts
// frontend/src/api/auth.ts

import { apiClient } from "./client";

export async function login(email: string, password: string) {
  const res = await apiClient.post("/auth/login", { email, password });
  return res.data;
}

export async function register(email: string, password: string, displayName?: string) {
  const res = await apiClient.post("/auth/register", {
    email,
    password,
    display_name: displayName,
  });
  return res.data;
}

export async function getMe() {
  const res = await apiClient.get("/auth/me");
  return res.data;
}

export async function logout() {
  const res = await apiClient.post("/auth/logout");
  return res.data;
}
```

### 11.4 App 路由示例

```tsx
// frontend/src/App.tsx

import { Routes, Route } from "react-router-dom";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ProtectedRoute } from "./routes/ProtectedRoute";
import { AppLayout } from "./layouts/AppLayout";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route element={<ProtectedRoute />}>
        <Route path="/*" element={<AppLayout />} />
      </Route>
    </Routes>
  );
}
```

---

## 12. 错误提示与安全边界

### 12.1 登录错误

前端统一展示：

```text
邮箱或密码错误，或账号暂不可用。
```

后端日志记录真实原因：

```yaml
wrong_password
user_not_found
not_whitelisted
account_disabled
session_limit_reached
rate_limited
```

### 12.2 注册错误

前端统一展示：

```text
注册失败，请检查信息或联系管理员。
```

不要直接提示：

```text
该邮箱不在白名单
该邮箱已经注册
```

这样可以减少账号枚举风险。

---

## 13. Rate Limit 与 Lockout

### 13.1 建议规则

```yaml
login_per_email: 5/minute
login_per_ip: 20/minute
register_per_ip: 3/hour
lockout_after_failed_attempts: 10
lockout_duration_minutes: 15
exponential_backoff: true
captcha: optional_after_repeated_failures
```

### 13.2 Redis Key

```text
rate:login:email:{email}
rate:login:ip:{ip}
rate:register:ip:{ip}
lockout:email:{email}
```

---

## 14. 未来 SSO 升级路线

### 14.1 本期必须预留的字段

```yaml
auth_provider:
  values:
    - local
    - oidc
provider_subject:
  description: SSO provider 中的稳定用户唯一 ID
email:
  description: verified email，用于本地账号与 SSO 账号绑定
password_hash:
  nullable: true
```

### 14.2 未来 OIDC 流程

```text
1. 用户点击 “使用公司 SSO 登录”
2. 前端跳转到 /api/v1/auth/oidc/login
3. 后端重定向到 IdP Authorization Endpoint
4. 用户在 IdP 完成登录
5. IdP 回调 /api/v1/auth/oidc/callback
6. 后端校验 ID Token：iss、aud、exp、signature
7. 后端读取 email / sub / group claims
8. 检查 email 或 group 是否允许访问
9. 创建或绑定 app_users 账号
10. 创建本系统 session_id Cookie
```

### 14.3 本地账号迁移到 SSO

```text
Phase 1: local password + allowlist
Phase 2: 增加 SSO 登录入口，local 与 oidc 并存
Phase 3: SSO 登录成功后按 verified email 绑定本地账号
Phase 4: 管理员确认后把 auth_provider 改为 oidc
Phase 5: 禁用普通用户 local password 登录，仅保留 break-glass admin
```

### 14.4 SSO 后的白名单升级

本期：

```text
email allowlist:
  - aah5sgh@bosch.com
  - uay4sgh@bosch.com
```

未来：

```text
group allowlist:
  - HRagent-Users
  - HRagent-Admins
```

---

## 15. 环境变量

```bash
# Auth
AUTH_ENABLED=true
AUTH_COOKIE_NAME=hragent_session
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_SESSION_IDLE_TIMEOUT_MINUTES=30
AUTH_SESSION_ABSOLUTE_TIMEOUT_HOURS=8

# Whitelist
AUTH_WHITELIST_ENABLED=true
AUTH_ALLOWED_EMAILS=aah5sgh@bosch.com,uay4sgh@bosch.com

# Password KDF
AUTH_PASSWORD_KDF=argon2id
AUTH_ARGON2_MEMORY_COST=19456
AUTH_ARGON2_TIME_COST=2
AUTH_ARGON2_PARALLELISM=1
AUTH_ARGON2_HASH_LEN=32
AUTH_ARGON2_SALT_LEN=16
AUTH_LOGIN_HASH_MAX_CONCURRENCY=8

# Concurrency
AUTH_MAX_ACTIVE_SESSIONS=100
WEB_CONCURRENCY=4
UVICORN_LIMIT_CONCURRENCY=200
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=20
REDIS_MAX_CONNECTIONS=50

# Future SSO
AUTH_SSO_ENABLED=false
AUTH_OIDC_ISSUER=
AUTH_OIDC_CLIENT_ID=
AUTH_OIDC_CLIENT_SECRET=
AUTH_OIDC_REDIRECT_URI=
AUTH_OIDC_ALLOWED_GROUPS=
```

---

## 16. 测试方案

### 16.1 单元测试

```bash
pytest tests/test_auth_register_login.py -q
pytest tests/test_auth_whitelist.py -q
pytest tests/test_auth_concurrency.py -q
```

必须覆盖：

```yaml
password:
  - hash 不能等于明文
  - hash 以 $argon2id$ 开头
  - 相同密码两次 hash 结果不同
  - 错误密码校验失败
  - 低于 15 位密码拒绝
whitelist:
  - aah5sgh@bosch.com 可以注册
  - uay4sgh@bosch.com 可以注册
  - 非白名单邮箱不可注册
  - 移出白名单后不可登录
session:
  - 未登录访问业务接口返回 401
  - 登录后 /auth/me 返回用户信息
  - logout 后 session 失效
concurrency:
  - 第 100 个活跃 session 创建成功
  - 第 101 个活跃 session 被拒绝或提示系统繁忙
```

### 16.2 手工验收

```text
1. 打开系统，未登录时自动跳转 /login。
2. 使用非白名单邮箱注册，注册失败。
3. 使用 aah5sgh@bosch.com 注册成功。
4. 使用正确密码登录成功。
5. 刷新页面后仍保持登录态。
6. 点击退出后无法访问业务页面。
7. 查看数据库 password_hash，不存在明文密码。
8. 查看 Redis，存在 session:{sid} 和 auth:active_sessions。
9. 模拟 100 个活跃会话，系统可正常访问。
10. 第 101 个会话按配置被限制。
```

### 16.3 负载测试

```bash
locust -f tests/load/locustfile.py \
  --headless \
  -u 100 \
  -r 10 \
  --run-time 5m \
  --host http://localhost:8111
```

---

## 17. Definition of Done

```yaml
frontend:
  - LoginPage 可用
  - RegisterPage 可用
  - ProtectedRoute 生效
  - 登录态刷新不丢失
  - 登出后清除状态
backend:
  - 注册接口完成
  - 登录接口完成
  - 登出接口完成
  - /auth/me 完成
  - 业务接口接入 get_current_user
security:
  - 密码使用 Argon2id
  - 数据库无明文密码
  - 注册与登录均检查白名单
  - Cookie 设置 HttpOnly / Secure / SameSite
  - 错误信息不泄露账号是否存在
  - 登录限流和失败审计完成
concurrency:
  - 最大活跃会话数为 100
  - 100 并发压测通过
sso_ready:
  - app_users 已包含 auth_provider / provider_subject
  - OIDC 环境变量已预留
  - 代码层存在 AuthProvider 抽象或可扩展入口
```

---

## 18. 实施顺序

```text
Step 1: 增加数据库表和 .env.example 配置
Step 2: 实现 PasswordService、WhitelistService、SessionService
Step 3: 实现 /auth/register、/auth/login、/auth/logout、/auth/me
Step 4: 给核心业务 API 增加 get_current_user 依赖
Step 5: 实现前端 LoginPage、RegisterPage、ProtectedRoute
Step 6: 实现错误提示、登录态刷新、登出
Step 7: 增加 rate limit、lockout、audit log
Step 8: 增加 100 active sessions 限制
Step 9: 编写单元测试与集成测试
Step 10: 执行 100 用户负载测试
Step 11: 预留 OIDC SSO 文件和配置，但默认关闭
```

---

## 19. 风险与注意点

| 风险 | 说明 | 处理 |
|---|---|---|
| Argon2id 参数过高 | 100 人同时登录时可能占用较高内存 | 限制 `AUTH_LOGIN_HASH_MAX_CONCURRENCY=8` |
| 错误提示泄露账号 | 提示“邮箱不存在”会导致账号枚举 | 前端统一错误提示，后端日志记录真实原因 |
| Cookie 在 HTTP 下不可用 | `Secure=true` 要求 HTTPS | 开发环境可临时 `AUTH_COOKIE_SECURE=false` |
| 两个白名单邮箱与 100 用户冲突 | 只有 2 个 named users，无法代表 100 个独立用户 | 若需要 100 独立用户，应扩展 whitelist 或使用 SSO group |
| localStorage 存 token | XSS 后容易被窃取 | 使用 HttpOnly Cookie |
| SSO 迁移困难 | 只按本地密码建模会难迁移 | 现在就加入 `auth_provider` 和 `provider_subject` |
| 登录限流过严 | 可能影响真实用户 | 区分 email、IP、全局限流，允许管理员解锁 |

---

## 20. 推荐最小提交拆分

```text
commit 1: add auth database schema and config
commit 2: add password, whitelist, session services
commit 3: add auth API routes and dependencies
commit 4: add frontend login/register/protected routes
commit 5: protect existing business routes
commit 6: add rate limit, audit log, active session cap
commit 7: add tests and load-test scripts
commit 8: add SSO-ready provider fields and disabled OIDC stubs
```
