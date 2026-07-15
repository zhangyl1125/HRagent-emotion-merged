# 03：Token 与 API 用量采集

## 统一 Token 埋点

仅修改 `backend/services/langchain_llm_service.py` 中 `ModelFarmLangChainChatModel._generate`、`_agenerate`、`astream_text`、`astream_events`。不得在各业务 Agent 中重复实现。新增 `backend/models/usage.py`、`backend/repositories/usage_repository.py`、`backend/services/usage_tracking_service.py`、`backend/core/usage_context.py`。

统一将 Provider 的 `prompt_tokens/completion_tokens`、`input_tokens/output_tokens`、嵌套 `data.usage` 映射到 `NormalizedTokenUsage`；同时读取 reasoning/cached token 详情。来源规则：Provider 数据为 `provider`；无 Provider usage 但允许估算则为 `estimated`；不可得为 `unavailable`，所有 Token 字段 `NULL`，绝不能写 0。

Provider 未给 total 而给输入/输出时，`total = input + output`；reasoning 通常已包含在 output 中，不得二次相加。估算仅供趋势参考，采用规范化 messages 与实际输出的 UTF-8 字节估算（建议 `ceil(bytes / 3.5)`）；前端必须显著标记 `≈` / “估算”。

## 非流式、流式与隔离

非流式调用记录开始时间、trace/call/user/session、任务、provider/model、状态、Provider request ID、HTTP 状态、重试次数、耗时和标准化 usage。重试后成功只写一条最终记录；异常写一条 error 后重新抛出业务异常。

流式调用每次仅写一条：累计最后 usage 或仅累计输出字节/字符数用于估算，禁止保存所有 chunk/完整输出；客户端取消写 `cancelled`，异常写 `error`，在 generator `finally` 完成记录。

写入失败必须被 `UsageTrackingService.record_*()` 捕获，最多重试一次，只记脱敏 warning，不中断模型调用。数据库以 `call_id` 唯一约束和 `INSERT ... ON CONFLICT (call_id) DO NOTHING` 防重复。

## API 请求审计

新增 `backend/middleware/api_request_audit.py`，在业务 API 请求结束后写 trace、用户/邮箱快照、method、FastAPI route template、状态和耗时。只记录模板如 `/api/v1/rehearsal/{session_id}/message`，绝不记录真实路径参数、query/body。排除 health、docs、openapi、favicon、静态资源和由现有 `auth_audit_log` 覆盖的认证接口。写库失败不改变原响应。
