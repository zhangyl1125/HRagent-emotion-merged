# HRagent-05 Token 费用优化落地建议

## 1. 文档目的

本文基于 [`less_token.md`](less_token.md) 的通用方法，并结合 HRagent-05 当前代码调用链，筛选能够在本项目实际落地的 Token 降耗方案。

本文仅提供分析与实施建议，不代表已授权修改业务代码。实际实施仍须遵循 `specs/token-concurrency-optimization/` 的阶段门禁。

约束如下：

- 仅使用项目当前支持的外部模型 API，不引入 Ollama 或本地模型。
- 不改变六步业务流程、成功响应、SSE 事件名称及顺序、Pydantic Schema 和证据引用规则。
- 不缓存完整 AI 员工回复，不记录 Prompt、完整模型回复、员工正文或真实凭据。
- 模型切换、服务地址、数据库结构、鉴权、Docker 和外部基础设施变更不在本文范围内。

## 2. 当前项目的主要 Token 热点

| 业务阶段 | 当前调用与上下文 | 主要浪费 | 相关位置 |
| --- | --- | --- | --- |
| 谈前指导 Guidance | 5 个栏目分别调用模型；每次重复发送 Profile、Intent、Persona、Motivation、Emotion、检索片段和企业文化 | 相同输入被重复发送 5 次 | `backend/services/guidance_service.py`、`backend/agents/guidance_agent.py` |
| 15 轮对话预演 | 每轮员工回复都序列化完整对话，并重复发送资料、人格、诉求、情绪和 RAG 结果 | 对话越长，后续轮次输入 Token 增长越快 | `backend/agents/employee_agent.py`、`backend/prompts/employee/reply.jinja2` |
| 动态状态更新 | 动态预演中 Motivation 与 Emotion 可并行发起两次模型调用 | 两次调用携带高度相似的经理消息和会话状态 | `backend/workflows/nodes.py`、`backend/services/simulation_motivation_scoring_service.py`、`backend/services/emotion_transition_service.py` |
| 复盘报告 CoachReport | 4 个评估任务加 5 个报告栏目，最多形成 9 次模型调用；评估与栏目重复携带完整对话 | 完整对话、评估结果和检索材料被多次重复发送 | `backend/services/coach_service.py`、`backend/agents/coach_agent/` |
| RAG | Guidance 最终可取 8 个通用片段和 4 个文化片段；员工回复取 4 个片段；Coach 按多个任务分别检索和重排 | 重复构造查询、Embedding/Rerank 调用及过长片段进入 Prompt | `backend/services/retrieval_service.py`、`backend/services/guidance_service.py`、`backend/agents/employee_agent.py` |
| 用量监控 | LLM 调用已写入 `llm_usage_events`；Embedding、Rerank、ASR 的费用口径未统一进入该表 | 难以完整归因一次业务流程的模型费用 | `backend/services/usage_tracking_service.py`、`backend/services/embedding_service.py`、`backend/services/rerank_service.py` |

当前已有两项可复用基础能力：

- `backend/services/cache_service.py` 已提供稳定 JSON 序列化、摘要键和 Redis 缓存门面。
- `backend/services/usage_tracking_service.py` 已记录任务、Provider、模型、输入/输出/缓存 Token、耗时和状态。

## 3. `less_token.md` 中可直接应用的方案

### 3.1 合并重复模型调用

这是本项目收益最高的优化。

| 对象 | 当前 | 建议目标 | 预计直接效果 |
| --- | --- | --- | --- |
| Guidance | 5 次栏目调用 | 1 次结构化调用生成完整 `GuidanceReport` | 相同上下文不再重复发送 5 次，重复输入理论上可减少约 80% |
| CoachReport | 4 次评估 + 5 次栏目调用 | 第 1 次生成四项评估，第 2 次生成完整报告 | 调用数由最多 9 次降到最多 2 次，大幅减少完整对话重复输入 |
| 动态状态更新 | Motivation、Emotion 各 1 次 | 1 次结构化调用同时返回两类状态 | 每轮最多减少 1 次重复状态输入 |

兼容要求：

- Guidance 一次生成后，后端仍按原顺序拆分并发送 `section_start`、`delta`、`section_done` 和 `done`。
- Coach 两次调用的结果仍需映射为现有四项 `CoachTaskResult` 与完整 `CoachReport`。
- 任一结构化结果校验失败时必须使用受控降级，不得返回不完整但标记成功的报告。

### 3.2 对话上下文压缩

当前 `EmployeeAgent._build_reply_prompt()` 向员工回复模型传入完整 `state.conversation`。15 轮流程中，这是最明显的累积型 Token 热点。

滑动窗口与滚动记忆可以组合使用，且适合本项目：滑动窗口负责保留最近对话的原文语气、上下文和即时追问；滚动记忆负责保留被窗口移出的长期事实。两者不是二选一，也不应把同一段原文同时放入两处。

建议采用：

- 滑动窗口固定保留最近 6 个对话 turn 原文，并按完整 turn 边界截取，不能截断单条经理或员工消息。
- 更早内容压缩为最多 2,000 字符的滚动记忆。
- 滚动记忆只保留事实、数字、承诺、分歧、待确认项和已采取的行动。
- 不写入心理诊断、隐藏推理、逐句复述或完整员工回复。
- 最新经理消息只保留一个来源，避免同时出现在 `conversation` 和 `latest_manager_message` 中重复发送。

每次新增对话后，应先将超出窗口的最早完整 turn 增量合并进滚动记忆，再生成下一轮 Prompt。若滚动记忆达到上限，应基于字段白名单压缩已有记忆，而不是丢弃窗口中的最近原文。窗口和记忆都无法承载的关键事实、数字、承诺或红线信息时，必须停止压缩并保留该信息。

滚动记忆建议使用现有 Session `state_json` 中的可选字段保存，不新增数据库列。旧会话没有该字段时继续按旧结构读取。

### 3.3 精简静态 Prompt

`backend/prompts/employee/reply.jinja2` 包含每轮重复发送的规则。可以在不删除安全边界的前提下进行以下整理：

- 合并语义重复的角色、语气和格式要求。
- 将 Profile、Intent、Persona、Difficulty 等输入改为紧凑 JSON，移除空字段、时间戳和仅供界面展示的字段。
- 静态规则放在 Prompt 前部，动态上下文放在后部，提高外部 Provider Prompt Cache 命中的可能性。
- 禁止项、事实一致性、人格连续性、红线和输出格式属于不可删除内容。
- 为 Prompt 增加版本号，便于缓存隔离、灰度和回滚。

不能直接假设外部 Provider 一定给予 Prompt Cache 折扣。是否命中及优惠金额必须以 Provider 返回的 `cached_tokens` 和实际账单为准。

### 3.4 限制输出长度和使用结构化输出

项目已经按任务提供 `llm_*_max_tokens` 配置，并支持 Pydantic 结构化输出。建议：

- 用阶段 01 基线统计每个任务输出 Token 的 P95，再为该任务设置略高于 P95 的上限。
- Guidance、状态更新、Coach 评估和最终报告优先使用结构化 Schema，减少解释性包装文本。
- 员工回复保持自然语言流式输出，但设置符合单轮对话长度的独立上限。
- 不应为降费过度压缩 Coach 证据、风险项或建议话术；完整性门禁优先于费用目标。

### 3.5 RAG 检索与上下文裁剪

可以从两部分减少费用：减少外部检索模型调用，以及减少送入 LLM 的检索文本。

建议：

- 对同一业务阶段的相同检索上下文做稳定摘要键，复用查询结果。
- Guidance 五栏目合并后只检索一次，结果供完整报告使用。
- Coach 四项评估共享候选集合，再按任务筛选，避免五组近似查询重复做 Embedding/Rerank。
- 对候选片段按 `chunk_id` 去重，并设置单片段字符上限和总字符预算。
- 通过基线比较逐步调整 `vector_top_k`、`rerank_top_n` 和最终 Prompt Top-K，不能直接凭经验大幅减少。
- 保留引用所需的 `chunk_id`、来源和必要原文，避免 Token 降低后失去证据可追溯性。

### 3.6 缓存、Singleflight 与幂等

项目已有 Guidance、CoachReport、TTS、文档解析等缓存，可进一步应用 `less_token.md` 的缓存友好设计：

- 缓存键使用排序后的稳定 JSON，并排除非语义时间戳。
- 缓存键加入模型、知识库版本、Prompt 版本和所有影响结果的业务字段。
- 对相同 Guidance/CoachReport 缓存未命中增加 Redis Singleflight，避免多个 worker 同时重复生成。
- 重试必须复用幂等标识，防止客户端重连或 SSE 重试重复计费。
- Redis 异常时使用保守的本地并发上限，不得退化为无限模型并发。

禁止缓存完整 AI 员工回复。对话预演只能缓存规范允许的派生状态，例如情绪信号或滚动记忆。

### 3.7 用量监控和成本归因

当前 `llm_usage_events` 可以作为主要数据源。建议按完整业务流程汇总：

- `profile`、`intent`、`guidance`、`employee_reply`、`simulation_state`、`coach_evaluation`、`coach_report` 的调用数。
- Provider、模型、输入 Token、输出 Token、Reasoning Token、Cached Token、重试次数、耗时和状态。
- 用户维度、业务会话维度和任务维度的总量，但看板不展示 Prompt 或员工正文。
- Provider 未返回 Token 时单独标记 `estimated` 或 `unavailable`，不能与真实 Token 混为一类。

Embedding、Rerank 和 ASR 应单独统计：

- Embedding 按 Provider 的输入 Token 或实际计费单位计算。
- Rerank 按文本量、调用次数或 Provider 实际计费单位计算。
- ASR 通常按音频时长计费，不应伪装成 LLM Token。
- TTS 若已不再用于机器人回复，则不应纳入当前业务流程的 Token 优化收益。

## 4. 可补充的项目专项优化

### 4.1 规则优先，模型兜底

对于可通过确定性规则计算的状态，不必每轮调用模型：

- 无动态 Persona/Motivation 时继续使用现有规则引擎。
- 输入没有触发情绪或诉求变化时，可复用上一状态并跳过更新调用。
- 只有规则置信度不足或触发关键变化时再调用结构化状态模型。

该方案必须通过人格连续性和情绪变化测试，不能以省 Token 为由让员工反应失真。

### 4.2 删除重复序列化字段

同一语义可能同时存在于 Profile、Persona、Motivation、Emotion 和 Rehearsal Context 中。建议为每类任务建立字段白名单：

- Guidance 只携带生成五个栏目必需的字段。
- Employee Reply 只携带当前人格表现、动态情绪、当前诉求、最近对话和必要证据。
- Coach Evaluation 保留完整证据，但不同评估维度只传其真正使用的字段。
- 最终 CoachReport 主要消费已结构化的四项评估，避免再次传入所有原始上下文；只有证据引用所需片段例外。

### 4.3 费用预算与软硬门禁

建议为完整流程设置两级预算：

- 软门禁：输入 Token 达到预算的 80% 时触发上下文压缩、RAG 裁剪和告警。
- 硬门禁：单个任务超过最大上下文或输出预算时停止该次模型调用，返回现有安全错误结构。

预算必须按任务设置，不能用一个全局值同时限制员工短回复和完整 CoachReport。

## 5. 暂不适合本项目直接应用的方案

| `less_token.md` 方案 | 当前判断 | 原因 |
| --- | --- | --- |
| 本地部署替代外部 API | 不应用 | 项目专项明确只使用现有外部模型 API，不使用 Ollama |
| 随意切换小模型或级联模型 | 暂缓 | 会改变模型配置和输出质量，属于高风险变更；需独立质量基线与授权 |
| 模型微调 | 暂缓 | 需要训练数据、隐私审查、模型托管和长期版本治理，当前投入产出不明确 |
| 将系统提示改成英文 | 不建议作为首选 | 可能影响中文业务语义、红线和话术质量，应先做 Prompt 去重而不是语言替换 |
| 缓存完整员工回复 | 禁止 | 会固化动态人格对话，并带来隐私和串会话风险 |
| 仅靠增加并行调用提速 | 不能降低 Token | 并行只降低等待时间；无界并发还会放大 429、重试和重复费用 |
| 暴露完整推理链用于调试 | 禁止 | 增加输出 Token，并可能泄露内部推理和敏感上下文 |

## 6. 推荐实施顺序

必须遵循现有 Specs 的阶段顺序：

1. 阶段 01：完成固定合成流程基线，得到每任务调用数、输入/输出 Token、耗时、状态和费用口径。
2. 阶段 02：实施 Guidance 一次调用、Coach 最多两次调用、状态合并、Prompt 精简和最近 6 turn + 2,000 字符滚动记忆。
3. 阶段 03：增加外部 API 的跨 worker 有界并发、排队和过载保护，避免 429 重试扩大费用。
4. 阶段 04：完善 Redis Singleflight、缓存版本、重试分类和幂等。
5. 阶段 05：补全按用户、任务、Provider、模型和业务流程的 Token 与费用看板。
6. 阶段 06：使用 50 个隔离测试账号执行完整流程验收。
7. 阶段 07：按功能开关灰度发布，保留旧路径作为回滚手段。

当前 `specs/token-concurrency-optimization/README.md` 中阶段 01 为 `blocked`，原因是测试凭据轮换和真实外部 API 基线费用授权尚未完成。因此本文中的阶段 02 及后续内容目前只能作为待实施方案，不能越过门禁直接修改业务代码。

## 7. 目标与验收指标

### 7.1 Token 与调用目标

- 相同合成资料和固定 15 轮消息下，完整流程输入 Token 相对阶段 01 基线至少降低 50%。
- Guidance 模型调用从 5 次降为 1 次。
- CoachReport 模型调用从最多 9 次降为最多 2 次。
- 动态 Motivation 与 Emotion 更新从每轮最多 2 次降为最多 1 次，并评估规则跳过率。
- Provider 返回的 Token、估算 Token 和不可用 Token 分开统计。

### 7.2 质量与兼容目标

- Guidance 和 CoachReport Schema 校验通过率为 100%。
- SSE 事件名称、顺序和成功响应字段保持兼容。
- 15 轮对话中的事实、数字、承诺和待确认项能够持续承接。
- Coach 证据引用、红线检测和人格表现不能因压缩而缺失。
- 黄金样本 Coach 总分相对基线漂移不超过现有 Spec 允许范围。

### 7.3 并发目标

- 50 个活跃完整流程中至少 49 条完整结束。
- 请求总失败率低于 1%。
- 429、超时和重试不会形成重试风暴或重复生成。

## 8. 成本计算建议

不要在业务代码中写死价格。价格应由受控配置或 Grafana 查询参数维护，并保留生效时间和币种。

单次 LLM 调用费用可按 Provider 实际价格计算：

```text
费用 = 输入 Token / 1,000,000 × 输入单价
     + 缓存输入 Token / 1,000,000 × 缓存输入单价
     + 输出 Token / 1,000,000 × 输出单价
     + 其他 Provider 明确计费项
```

完整业务流程费用应按同一 `business_session_id` 汇总所有任务，并把 ASR、Embedding、Rerank 等不同计费单位单列，最后再计算总费用。

## 9. 建议涉及的文件范围

后续获得阶段授权时，预计只需围绕以下文件实施：

- Prompt 与上下文：`backend/prompts/employee/reply.jinja2`、`backend/agents/employee_agent.py`。
- Guidance 合并：`backend/agents/guidance_agent.py`、`backend/services/guidance_service.py`、相关 Schema 和测试。
- Coach 合并：`backend/agents/coach_agent/`、`backend/services/coach_service.py`、相关 Schema 和测试。
- 状态合并：`backend/workflows/nodes.py`、Motivation/Emotion 服务及相关测试。
- RAG 裁剪：`backend/services/retrieval_service.py` 和查询配置。
- 缓存与 Singleflight：`backend/services/cache_service.py` 及 Guidance/Coach 调用点。
- 用量与费用：`backend/services/usage_tracking_service.py`、`llm_usage_events` 现有查询层和 Grafana 看板。
- 完整流程验收：`locust-loadtest/tests/load/hragent_locustfile.py`。

具体修改范围仍以每个阶段开始时的实际代码复核为准。

## 10. 风险与停止条件

出现以下情况应停止优化并回到上一稳定路径：

- Token 降幅只能通过删除安全规则、证据引用或人格约束才能达到。
- 结构化输出导致现有 Schema 或 SSE 契约不兼容。
- 滚动记忆遗漏关键事实、数字、承诺或红线原话。
- Provider 不支持所需结构化输出、用量字段或幂等能力，且没有兼容方案。
- 缓存键不能完整覆盖用户、会话、模型、Prompt 和知识库版本，存在串数据风险。
- 测试需要真实员工数据、生产凭据、未授权外部 API 费用或数据库迁移。

## 11. 结论

对 HRagent-05 最有价值的降费组合不是单独缩短一句 Prompt，而是：

1. 将 Guidance 的 5 次调用合并为 1 次。
2. 将 CoachReport 的最多 9 次调用压缩为最多 2 次。
3. 将预演完整历史改为最近 6 turn 加受控滚动记忆。
4. 合并或按规则跳过 Motivation/Emotion 更新。
5. 对 RAG、缓存和重试做去重，避免相同请求被重复计费。
6. 以 `llm_usage_events` 的真实数据验证完整流程至少 50% 的输入 Token 降幅。

这些方案与当前项目架构相匹配，但必须先解除阶段 01 阻塞并取得对应阶段授权，再按 Specs 顺序实施。
