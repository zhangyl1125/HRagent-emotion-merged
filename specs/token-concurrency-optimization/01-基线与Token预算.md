# 阶段 01：基线与 Token 预算

## 目标

建立可重复的完整业务流程基线，固定 Token 统计口径、质量样本和性能门禁，避免用不一致数据证明优化有效。

## 现状

- 已有 `llm_usage_events` 记录任务、模型、输入/输出 Token、重试、耗时和状态。
- Locust 已覆盖建会话、资料、Guidance、15 轮预演和 CoachReport，但必须核实 0 请求、SSE 不完整和退出码门禁。
- 外部 Provider 可能返回 `provider`、`estimated` 或 `unavailable` 用量来源，三者不能混为同一精度。

## 改动

1. 固定一套合成员工资料、配置和 15 条经理话术，作为所有阶段共同基准。
2. 记录完整流程的总调用数，以及按 `profile`、`intent`、`guidance`、`employee`、状态更新、Coach 评估和报告分组的输入/输出 Token。
3. Locust 在请求总数为 0、SSE 缺少 `done`、Guidance `complete` 非真、Report 返回 `error` 或完整流程未结束时必须失败。
4. 用测试开始/结束时间、测试账号和 `business_session_id` 关联用量；不得在日志中打印会话标识或凭据。
5. 保存结构化质量快照：Guidance 字段、15 轮员工回复、Emotion/Motivation 状态和 CoachReport 必填字段。

## 接口与配置

- 不改变公开 API。
- 增加压测环境变量 `HRAGENT_BASELINE_LABEL` 与 `HRAGENT_MIN_REQUESTS`；标签只能使用非敏感测试标识。
- Provider 用量不可用时，阶段报告必须单独列出估算值，不能将空值写成 0。

## 测试

- 执行一次 1 用户完整流程并确认请求数大于 0。
- 故意模拟 SSE 无 `done`、Guidance 不完整和 Report `error`，确认 Locust 非零退出。
- 查询对应测试时间窗的 `llm_usage_events`，核对调用数及输入/输出合计。
- 对相同合成输入重复执行，确认统计偏差可解释且 Schema 一致。

## 验收

- 一条完整流程成功包含 1 次 Guidance、15 轮预演和 1 次 CoachReport。
- 所有模型任务均有用量来源，`unavailable` 项被明确列出。
- 形成后续阶段唯一使用的基线调用数、输入 Token、输出 Token、耗时和质量快照。
- 质量门禁不会把 0 请求或不完整 SSE 判为通过。

## 回滚

删除新增的纯测试参数与基线脚本改动；不得删除业务会话或历史用量表。保留原始基线报告供比较。

## 停止条件

外部 API 未授权压测、测试账号不是隔离账号、Provider 用量无法统计且估算口径未确认，或完整流程本身无法成功时停止。
