---
name: optimize-token-cost
description: 审计并安全降低 LLM、RAG、Agent、多轮对话和多模态工程项目的 Token 用量及模型费用。当任务涉及 Prompt 或上下文压缩、调用合并、缓存、模型路由、并发重试、用量归因、优化前后对比或降费质量门禁时使用。
---

# Token 成本优化

以完整业务结果为单位降低模型费用，同时保持质量、安全、Schema、流式协议和用户流程稳定。

## 核心流程

1. **确认边界**：读取仓库指令与调用架构，列出受保护契约、隐私限制和需单独授权的变更。
2. **建立基线**：使用固定合成流程记录调用、Token、费用、延迟、失败、重试和质量；拒绝零样本通过。
3. **定位热点**：从 Prompt、Context、Harness 三层查找重复输入、无效上下文和重复工作。
4. **选择方案**：按可验证收益、质量风险、可回滚性和实施成本排序；一次只修改一个维度。
5. **验证结果**：用相同流程比较完整业务结果，检查费用、性能、Schema、安全、证据和流式行为。
6. **渐进发布**：从离线或小流量开始，保留旧路径；触发停止条件时回滚并报告未验证项。

## 资料路由

只读取当前任务需要的资料，不要一次加载全部 `references/`。

| 当前任务 | 按需读取 |
| --- | --- |
| 快速选择优化模式与实施顺序 | [references/playbook.md](references/playbook.md) |
| 建立调用、Token、费用和延迟基线 | [references/measurement-baseline.md](references/measurement-baseline.md) |
| 精简 Prompt、工具定义或多轮上下文 | [references/prompt-context.md](references/prompt-context.md) |
| 设计 RAG、缓存、路由、批处理、并发或重试 | [references/cache-routing-concurrency.md](references/cache-routing-concurrency.md) |
| 定义质量门禁、发布、回滚和报告 | [references/validation-rollout.md](references/validation-rollout.md) |
| 运行用量聚合、基线对比或载荷审计工具 | [references/tools.md](references/tools.md) |

## 工具路由

优先直接执行脚本；只有修改或排查脚本时才读取源码。

| 目标 | 工具 |
| --- | --- |
| 聚合脱敏用量并计算版本化费用 | `scripts/aggregate_usage.py` |
| 对比基线与候选结果并执行门禁 | `scripts/compare_runs.py` |
| 检查合成 JSON 载荷的重复和大小 | `scripts/audit_payload.py` |

运行工具前读取 [references/tools.md](references/tools.md)，遵守输入 Schema、退出码和隐私限制。

## 强制规则

- 没有同口径、非零基线时，不宣称 Token 或费用降低。
- 只使用合成、脱敏或聚合数据，不记录 Prompt、完整输出、个人数据或凭据。
- 保持成功响应、Schema、流式顺序、错误语义、安全规则和证据链。
- 模型、Provider、微调、部署、数据库或基础设施变更必须单独授权。
- 并发、批处理和流式不天然降低 Token；Prompt Cache 命中也不等于逻辑输入消失。
- 若质量、安全、隔离、费用或稳定性门禁失败，停止实施并回滚。
