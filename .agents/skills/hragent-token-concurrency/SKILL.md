---
name: hragent-token-concurrency
description: Execute HRagent-05 token-reduction and external-model-API concurrency work in gated stages. Use when changing prompts, LLM call counts, conversation context, Redis model-call coordination, singleflight, retries, idempotency, usage monitoring, Locust full-flow tests, or rollout controls under specs/token-concurrency-optimization.
---

# HRagent Token 与并发优化

按阶段降低完整业务流程的输入 Token，并为外部模型 API 提供跨 worker 的有界并发控制。保持现有成功响应、SSE 事件顺序和业务 Schema 兼容。

## 执行入口

1. 读取根目录 `AGENTS.md`。
2. 读取 `references/current-architecture.md`，确认代码现状仍与参考一致。
3. 读取 `specs/token-concurrency-optimization/README.md`。
4. 只读取并实施当前获批阶段的 Spec；不得提前实施后续阶段。
5. 在修改前记录基线，在修改后执行当前 Spec 的测试与验收。
6. 只有当前阶段全部通过，才将 README 状态改为 `completed` 并进入下一阶段。

## 不可突破的约束

- 仅使用当前 `main` 基线支持的外部模型 API；不得合并或移植 `ollama` 分支，不得操作 Ollama、GPU 或模型卷。
- 不记录或提交 Prompt、完整模型回复、员工正文、密码、Cookie、Session Token、API Key 或真实测试凭据。
- 不缓存完整 AI 员工回复；只允许缓存规范明确列出的派生结果。
- 不改变现有成功响应、SSE 事件名称、字段语义或六步业务流程。
- Redis 故障不得退化为无限模型并发；使用 Spec 定义的保守本地门限并记录脱敏告警。
- 数据库迁移、鉴权、模型、服务地址、输出结构、Docker 和外部系统变更必须重新获得授权。
- 不自动提交、推送、合并或清理用户数据。

## 阶段路由

| 阶段 | Spec | 进入条件 |
|---|---|---|
| 01 | `01-基线与Token预算.md` | 所有优化开始前 |
| 02 | `02-调用合并与上下文压缩.md` | 阶段 01 基线完整 |
| 03 | `03-外部API并发调度与过载保护.md` | 阶段 02 Token 门禁通过 |
| 04 | `04-缓存单飞重试与幂等.md` | 阶段 03 并发控制通过 |
| 05 | `05-用量监控与质量门禁.md` | 阶段 04 稳定性测试通过 |
| 06 | `06-50并发验收.md` | 阶段 01-05 全部完成 |
| 07 | `07-发布回滚与持续优化.md` | 阶段 06 验收通过 |

## 配套 Skills

- Docker 服务管理：读取 `.claude/skills/hragent-docker.md`。
- Redis 设计：读取 `.claude/skills/redis-cache-facade.md`。
- Locust：读取 `.claude/skills/locust-loadtest.md`。
- 构建验证：读取 `.claude/skills/hragent-build-verify.md`。
- 配置变更：读取 `.claude/skills/fastapi-pydantic-settings.md`。

## 停止条件

遇到以下任一情况立即停止当前阶段并报告：

- 工作区存在不属于当前阶段的改动，且无法安全隔离。
- 外部 API 不返回可量化的 Token，且估算口径尚未在阶段 01 固定。
- 优化导致 Schema、SSE 顺序、证据引用或员工人格表现回归。
- 需要真实员工数据、生产凭据、数据库迁移、模型切换或基础设施扩容。
- 50 并发测试环境没有 50 个隔离测试账号或外部 API 压测授权。

## 交付格式

完成每个阶段时说明：修改文件、关键行为、基线与结果、验证命令、未通过门禁、回滚方式和下一阶段是否可进入。不得仅以“命令成功”替代业务验收。
