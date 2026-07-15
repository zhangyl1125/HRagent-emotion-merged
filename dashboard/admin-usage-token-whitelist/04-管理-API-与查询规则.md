# 04：管理 API 与查询规则

新增 `backend/api/routes/admin.py` 并在 `backend/main.py` 注册；新增 schemas、admin repository、analytics service、audit service。每个端点统一使用 `Depends(require_super_admin_session)`。

## 端点

| 端点 | 作用 |
|---|---|
| `GET /admin/overview` | 默认 7 天的用户、Session、LLM、API 汇总 |
| `GET /admin/usage/trend` | 按 hour/day、用户、模型、任务、来源筛选的 Token 趋势 |
| `GET /admin/usage/users` | 用户 Token 排名与状态、活动、会话统计 |
| `GET /admin/usage/users/{user_id}` | 用户详情、分布、最近 LLM/API/认证记录 |
| `GET /admin/usage/events` | 分页 LLM 调用记录 |
| `GET /admin/activity/api-requests` | API 调用审计 |
| `GET /admin/activity/auth-audit` | 既有登录审计 |
| `GET /admin/activity/admin-actions` | 管理员操作审计 |
| `GET/POST/PATCH/DELETE /admin/whitelist` | 白名单与账号管理 |
| `GET /admin/usage/export.csv` | 与列表同筛选条件的受限 CSV 导出 |

用量事件只返回时间、邮箱、任务、模型、流式标记、Token、来源、耗时、状态、HTTP 状态、错误码、trace 和业务 session；不得返回 Prompt、Response、Key、Cookie 或完整 Provider 原始响应。默认 `page_size=50`、最大 200。CSV 最大行数取 `ADMIN_EXPORT_MAX_ROWS`，加 UTF-8 BOM，并对 `= + - @` 开头单元格加 `'`，禁止导出敏感字段。

## 查询约束

所有时间查询为 `[from, to)`，默认最近 7 天、最大跨度 366 天；数据库和 API 返回 UTC，前端做时区展示。Token 汇总只累加非空值，但必须并列返回 provider/estimated 与 unavailable call 数，不能掩盖数据质量。

活跃用户由 API、LLM、业务 Session 更新或成功登录任一条件确定；最近活动取登录、API、LLM、业务 Session 时间的最大值。所有表格返回 `items/page/page_size/total/total_pages`，绝不全量返回。所有条件参数化；排序字段只用后端白名单映射；邮箱使用 CITEXT 或 lowercase。
