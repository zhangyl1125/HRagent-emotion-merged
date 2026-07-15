# HRagent 管理后台 Coding Spec（拆分版）

本目录按实施依赖拆分 `../HRagent_Admin_Usage_Token_Whitelist_Coding_Spec.md`，便于 Coding AI 分阶段阅读和执行。原始规范保持不变。

## 阅读与实施顺序

1. [01-范围与安全模型](01-范围与安全模型.md)
2. [02-数据模型与请求上下文](02-数据模型与请求上下文.md)
3. [03-Token-与-API-用量采集](03-Token-与-API-用量采集.md)
4. [04-管理-API-与查询规则](04-管理-API-与查询规则.md)
5. [05-白名单-审计与-CSRF](05-白名单-审计与-CSRF.md)
6. [06-前端管理控制台](06-前端管理控制台.md)
7. [07-测试部署与回滚](07-测试部署与回滚.md)

## 不可突破的约束

- 仅增量扩展现有 FastAPI、PostgreSQL、Redis 与 React 应用；不得建立第二套后台、数据库或通过 Grafana 管理业务账号。
- PostgreSQL 是管理数据唯一事实源；Token 埋点只在统一 LLM 适配器层进行。
- 所有 `/api/v1/admin/*` 由后端超级管理员依赖保护；前端判断仅用于体验。
- 不保存 Prompt、模型完整回复、请求/响应正文、密码、Cookie、Session ID 或 API Key。
- Provider 缺失 Token 时必须标记 `estimated` 或 `unavailable`，不得默认写为 `0`。
- 统计与审计写入失败不得中断业务调用；根管理员不可被删除、停用、降级或被其他账号重置密码。
