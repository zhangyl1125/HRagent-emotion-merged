# HRagent Token 与并发现状参考

## 目录

1. 基线边界
2. Token 热点
3. 并发热点
4. 可复用能力
5. 实施前复核

## 基线边界

- 实施基线为 `main` 分支。
- 当前 LLM Provider 仅包括 `openai_compatible`、`bosch_openai_compatible` 和 `bosch_messages`。
- 本优化不使用、不合并、不移植 `ollama` 分支能力。
- 完整流程固定为一次谈前指导、15 轮对话和一次复盘报告。
- PostgreSQL 的 `llm_usage_events` 已能记录任务、模型、输入/输出 Token、重试、耗时和状态。

## Token 热点

### 对话预演

- `backend/prompts/employee/reply.jinja2` 包含大量每轮重复的静态规则。
- `EmployeeAgent` 每轮序列化完整对话，同时重复传入 Profile、Intent、Persona、Difficulty、Motivation、Emotion 与检索片段。
- 情绪变化和诉求变化当前可分别触发模型调用，与员工回复重复携带相近上下文。

### 谈前指导

- `GuidanceService` 为五个栏目并行发起模型任务。
- 每个栏目重复携带员工资料、意图、人格、诉求、情绪、知识片段和企业文化信息。
- Guidance 已有语义缓存，优化时必须保留缓存兼容和降级语义。

### 复盘报告

- `CoachService` 同时启动四个评估任务，然后为五个报告栏目继续启动模型任务。
- 评估任务重复携带完整对话；报告栏目重复携带完整对话、评估结果和检索上下文。
- 当前 `coach_report_max_concurrency_per_worker` 只限制单 worker 中同时生成的报告数，不能限制报告内部模型调用，也不能跨 worker 协调。

## 并发热点

- Web 进程默认允许多个 worker，统一 LLM HTTP 客户端连接池明显大于外部模型服务的实际容量。
- Guidance、CoachReport 和预演状态更新均包含局部 `asyncio.gather` 或 `create_task` 并发。
- 现有进程内 Lock/Semaphore 无法防止不同 worker 同时冲击同一 provider/model。
- 通用重试缺少统一的错误分类、退避抖动和 `Retry-After` 支持，可能放大 429 或临时故障。
- Guidance/Report 缓存锁主要是进程内锁；多个 worker 同时缓存未命中时仍可能重复生成。

## 可复用能力

- Redis 门面：`backend/services/cache_service.py`。
- 统一 LLM 适配层：`backend/services/langchain_llm_service.py`。
- 用量采集：`backend/services/usage_tracking_service.py` 与 `llm_usage_events.usage_metadata`。
- 完整流程压测：`locust-loadtest/tests/load/hragent_locustfile.py`。
- Grafana 看板：`observability/grafana/dashboards/hragent-logs.json`。

## 实施前复核

每个阶段开始前重新使用 `rg` 检查上述路径和调用关系。若实现已变化，以实际代码为准并先更新本参考；不得依据过期行号直接修改。
