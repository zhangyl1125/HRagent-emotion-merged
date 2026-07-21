# 阶段 03：外部 API 并发调度与过载保护

## 目标

在多个后端 worker 间统一限制同一 provider/model 的执行量，允许 50 个活跃流程有界排队，并防止 429、超时和重试风暴。

## 现状

- HTTP 连接池容量不能代表外部模型 API 的实际并发额度。
- 进程内 Lock/Semaphore 无法跨 worker 协调。
- Guidance、Coach 和状态更新存在局部并行，可能在流量峰值瞬间放大请求。

## 改动

1. 在统一 LLM 适配层前增加 `LLMExecutionCoordinator`，所有同步、异步和流式调用必须经过它。
2. 使用 Redis 原子操作维护按 provider/model 隔离的等待队列和带 TTL 租约；释放动作必须位于 `finally`。
3. 优先级固定为预演交互、Guidance、CoachReport，同优先级保持先进先出。
4. 队列达到上限后立即拒绝新重任务，并返回稳定的容量错误与建议重试时间。
5. Redis 不可用时启用单进程保守门限 1，禁止退化为无限并发；恢复后自动回到分布式协调。
6. 客户端取消、SSE 断开、超时和 worker 退出必须释放或由 TTL 回收租约。

## 接口与配置

- 新增 `LLM_MAX_INFLIGHT=4`、`LLM_QUEUE_MAX_DEPTH=100`、`LLM_QUEUE_TIMEOUT_SECONDS=600`、`LLM_LEASE_TTL_SECONDS=0`；TTL 为 0 时按请求超时和重试次数推导。
- 普通接口容量不足返回 HTTP 503，稳定错误码为 `capacity_busy`，包含 `retry_after_seconds`。
- SSE 在原事件流内发送 `error`，数据包含相同错误码和重试时间；成功事件不变。

## 测试

- 单测队列顺序、优先级、超时、取消和异常释放。
- 使用多个进程模拟同一 provider/model，确认全局执行数不超过配置值。
- 中断持有租约的 worker，确认 TTL 后可继续获取。
- 关闭 Redis，确认使用本地门限且不会出现无限并发。
- 模拟外部 API 429 和慢响应，确认队列深度与执行数受控。

## 验收

- 任意时刻同一 provider/model 的模型执行数不超过 `LLM_MAX_INFLIGHT`。
- 50 个活跃流程不会触发未处理 429、租约泄漏或无限排队。
- 预演交互不会被新进入的 Coach 批处理长期饿死。
- Redis 故障时业务可降级且仍保持有界并发。

## 回滚

关闭协调器功能开关，恢复阶段 02 调用路径；保留配置但不读取。回滚前先确认外部 API 流量处于安全范围。

## 停止条件

需要新增基础设施服务、修改 Docker 网络、改变外部 API 配额或 Redis 原子语义无法验证时停止并重新授权。
