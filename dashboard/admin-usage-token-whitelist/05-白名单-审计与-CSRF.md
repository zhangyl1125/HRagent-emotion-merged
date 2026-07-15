# 05：白名单、审计与 CSRF

提取 `backend/services/admin_account_service.py`，集中 list/create/update whitelist、创建本地账号、重置密码、停用、删除授权、保护根管理员、清除 Session 与写审计；旧 `AuthService.admin_*` 内部委托此服务，保持旧接口与测试兼容。

邮箱只允许 `domain == "bosch.com" or domain.endswith(".bosch.com")`，统一小写；不可使用简单的 `endswith("bosch.com")`。密码继续使用现有 PasswordService：纯数字至少 8 位，其他至少 15 位，最大 128 位，Argon2id 存储，永不回显。

白名单停用必须同步禁用用户、清除其 Redis 登录 Session、写审计、保留历史 usage；删除白名单只删除授权、停用用户并清除 Session，不删除历史。根管理员相关操作一律后端拒绝。

审计 `whitelist_create/enable/disable/delete`、`account_create/disable`、`password_reset`、显示名/备注更新、`usage_export`。before/after 仅保留业务状态，禁止密码、哈希、临时密码、session ID、API key。

认证依赖 Cookie，因此新增 `GET /api/v1/auth/csrf`：随机 Token 绑定 Redis Session，前端仅内存保存。所有 `/admin/*` 和 `/auth/admin/*` 写操作发送 `X-CSRF-Token`，同时校验 Origin/Referer。Cookie 保持 HttpOnly、Secure、SameSite Lax/Strict；CSRF Token 不记日志，失效返回 403 且不自动重试。

保留：LLM usage 365 天、API request 90 天、管理员审计至少 365 天或公司政策、认证审计 180 天或政策。新增 `scripts/cleanup_admin_usage.py` 支持 `--dry-run`、每批最多删除 10,000 行、输出数量；默认不删管理员审计，可每日 Cron。系统只记录谁/何时/模型/任务/结果/Token/耗时，不记录用户或模型正文、文档、密码、Key、Cookie。
