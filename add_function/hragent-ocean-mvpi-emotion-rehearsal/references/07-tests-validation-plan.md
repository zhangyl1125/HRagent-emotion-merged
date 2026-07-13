## 13. 测试用例

### 13.1 OCEAN 选择人格

#### 用例 A：高 C、低 E、高 N

```json
{
  "O": 4,
  "C": 9,
  "E": 2,
  "A": 5,
  "N": 8,
  "intent": "improvement",
  "primary_motivation": "recognition"
}
```

期望：

```text
候选应包含 data_logic_challenger 或 silent_avoidant。
最终 persona_override 必须体现：关注事实依据、标准、公平性，压力下可能短句/防备。
```

#### 用例 B：高 E、低 A、主诉求 Power

```json
{
  "O": 6,
  "C": 6,
  "E": 9,
  "A": 2,
  "N": 6,
  "intent": "development",
  "primary_motivation": "power"
}
```

期望：

```text
候选应包含 outcome_negotiator。
员工回复更主动追问晋升、权限、资源，但不得威胁或攻击。
```

#### 用例 C：高 A、高 N

```json
{
  "O": 5,
  "C": 5,
  "E": 4,
  "A": 8,
  "N": 8,
  "intent": "development_improvement",
  "primary_motivation": "recognition"
}
```

期望：

```text
候选应包含 emotionally_hurt 或 support_dependent。
员工应表现为受挫、担心机会受影响，需要被看见和确认。
```

### 13.2 情绪转换

#### 用例 D：直接否定，无共情

输入 HRBP：

```text
你这个季度结果就是不达标，主要还是你态度有问题。
```

期望：

```text
red_line_hit=true 或 risk_flags 包含 subjective_attack。
满足度下降。
情绪不得缓和，应转向 defensive_resistant / frustrated_pushback / angry_unfairness。
```

#### 用例 E：共情 + 事实 + 支持计划

输入 HRBP：

```text
我能理解你会觉得委屈，因为这个项目中途确实发生过两次需求变化。我们先把背景放进来一起看，同时也看三个已确认的交付指标：上线时间、客户反馈和跨部门同步记录。接下来两周我会和你每周复盘一次，先把优先级和资源缺口对齐。
```

期望：

```text
empathy、specificity、objective_evidence、support_plan 均较高。
主/辅满足度上升。
情绪应转向 guarded_hesitant -> reflective_softening，不能直接完全合作，除非前序满足度已经很高。
```

### 13.3 报告

#### 用例 F：完成 4 轮预演后生成报告

期望：

```text
报告包含 intent_alignment。
报告包含 demand_satisfaction。
报告包含 ocean_persona_report。
报告包含 emotion_transition。
至少给 2 条 key_strengths，2 条 key_improvements，1 条 better_phrase，3 条 executable_next_actions。
```

---
## 14. 构建与验证命令

后端修改后执行：

```bash
cd /path/to/HRagent-05
python -m compileall backend
pytest tests/test_agents.py tests/test_workflows.py tests/test_coach_schema.py -q
docker compose build backend
docker compose up -d backend
curl -fsS http://localhost:8111/api/v1/health
```

前端修改后执行：

```bash
cd /path/to/HRagent-05/frontend
npm run build
cd ..
docker compose build frontend
docker compose up -d frontend
curl -k -fsS https://localhost:8443/api/v1/health
```

端到端手工验收：

```text
1. 新建 Session。
2. 录入员工信息。
3. 选择/识别沟通意图。
4. 自动识别员工主/辅诉求，并手动修正一次。
5. 拖动 OCEAN 五条线。
6. 点击生成并确认模拟设定。
7. 进入谈前指导。
8. 进入预演，连续输入 3~5 轮 HRBP 话术。
9. 查看右侧情绪状态是否随话术变化。
10. 生成复盘报告，检查是否包含诉求、OCEAN、情绪轨迹、替代表达和下一步行动。
```

---
## 16. 安全与边界

1. 员工 Agent 只能扮演员工本人，不得替 HR/公司/法律做结论。
2. OCEAN 只能用于沟通模拟，不得输出心理诊断、病理判断、人格缺陷标签。
3. 退出或改进+退出场景中，系统必须提示 HR/Legal 边界，不得给正式解除、赔偿、签字结论。
4. 高压人格也不得辱骂、人身攻击、歧视表达或明显戏剧化。
5. 报告只做训练复盘，不作为正式绩效结论。
6. 不把 API Key、ASR/TTS/LLM 密钥暴露到前端。

---
## 17. 分阶段实施计划

### P0：最小可用，1~2 天

1. 新增 `ocean.py` schema。
2. 前端 PersonaStep 增加五条 OCEAN 滑块。
3. 后端支持保存 `ocean_profile`。
4. 实现规则版 Persona 选择，不依赖 LLM。
5. Employee Prompt 注入 OCEAN 摘要。
6. 报告展示 OCEAN 与 Persona。

验收：

```text
拖动滑块 -> 确认 -> SessionState 中有 ocean_profile -> 预演员工回复风格受影响 -> 报告显示 OCEAN。
```

### P1：诉求识别 + LLM Persona 选择，2~4 天

1. 实现 `MotivationExtractionService`。
2. 实现 `OceanPersonaSelector` LLM 结构化选择。
3. 支持用户确认/修正主辅诉求。
4. `emotion_state` 初始化时同步主辅诉求。
5. 报告展示诉求满足度。

验收：

```text
不同 intent + OCEAN + 诉求会得到不同 persona 和 persona_override。
LLM 失败时仍有规则 fallback。
```

### P2：VAD Markov 情绪转换，3~5 天

1. 新增 12 个基础情绪和 VAD 表。
2. 实现 `VadMarkovEngine`。
3. 接入 `AttitudeTransitionEngine`。
4. 扩展 `emotion_log` 记录情绪候选概率。
5. 前端 EmotionBadge 显示新 emotion_id 与描述。

验收：

```text
同样 HRBP 话术，在不同 OCEAN 人格下，情绪转换不同但符合防跳变规则。
```

### P3：复盘报告完整增强，2~3 天

1. 扩展 `CoachReport` schema。
2. 修改 `coach/report.jinja2`。
3. 前端 ReportStep 展示新结构。
4. 增加报告测试。

验收：

```text
报告可解释：为什么情绪变化、哪句话影响主诉求、HRBP 如何适配 OCEAN、下一步怎么做。
```

---
## 18. 给 AI Coding 工具的最终执行提示词

```text
你正在修改 HRagent-05 项目。请按以下要求实施，不要修改 HRagent-06 或其他项目。

目标：在现有“员工信息 -> 沟通意图 -> Persona -> 谈前指导 -> 预演 -> 复盘”流程中，新增 OCEAN 大五人格滑块、员工主/辅诉求识别、基于 VAD + Markov + LLM 的情绪转换，并增强复盘报告。

必须阅读并复用：
- backend/business_config/intents.yaml
- backend/business_config/personas.yaml
- backend/schemas/state.py
- backend/schemas/emotion.py
- backend/schemas/motivation.py
- backend/services/motivation_scoring_service.py
- backend/services/attitude_transition_engine.py
- backend/services/rehearsal_service.py
- backend/prompts/employee/reply.jinja2
- backend/prompts/coach/report.jinja2
- frontend/src/pages/steps/PersonaStep.tsx
- frontend/src/types/domain.ts
- frontend/src/api/client.ts

新增：
- backend/schemas/ocean.py
- backend/services/ocean_persona_selector.py
- backend/services/motivation_extraction_service.py
- backend/services/vad_markov_engine.py
- backend/prompts/setup/ocean_persona_select.jinja2
- backend/prompts/setup/motivation_extract.jinja2
- backend/business_config/ocean_traits.yaml

关键要求：
1. OCEAN 五条线分别为 O/C/E/A/N，每条 1~10 档，从细到粗，每档有中文标签和解释。
2. 员工主诉求和辅诉求使用 MVPI 6 类，主诉求 70%，辅诉求 30%。
3. 用户确认 OCEAN 后，后端必须选择一个现有 personas.yaml 中的 persona_id；必要补充写入 persona_override。
4. 每轮预演执行：EmotionAnalyzer -> MotivationScoring -> VadMarkovEngine -> EmployeeAgent reply。
5. 动态公式为 f(H, P, E_t) -> (E_{t+1}, R)，其中 P 包含 OCEAN、Persona、主辅诉求。
6. 报告必须包含 intent_alignment、demand_satisfaction、ocean_persona_report、emotion_transition、better_phrases、executable_next_actions。
7. 保持旧 API 兼容：旧 confirmPersona 流程仍可用，缺失 OCEAN 时默认五维 5 分，缺失诉求时按 intent 兜底。
8. LLM 输出全部走 Pydantic 结构化校验；失败时使用规则 fallback。
9. 不暴露密钥，不新增不必要依赖，不改变 Docker 端口，不修改数据库 schema 作为强依赖。

完成后执行：
python -m compileall backend
pytest tests/test_agents.py tests/test_workflows.py tests/test_coach_schema.py -q
cd frontend && npm run build
```

---
## 19. 最终验收清单

| 编号 | 验收项 | 必须通过 |
|---:|---|---|
| 1 | 能识别/确认沟通意图 | 是 |
| 2 | 能识别/确认员工主诉求、辅诉求 | 是 |
| 3 | PersonaStep 有 O/C/E/A/N 五条 1~10 滑块 | 是 |
| 4 | 每条滑块 10 个特征标签从细到粗映射 | 是 |
| 5 | 点击确认后后端返回最终 persona | 是 |
| 6 | SessionState 保存 ocean_profile、motivation_profile、ocean_persona_selection | 是 |
| 7 | Employee Agent 回复受 OCEAN + 诉求 + 情绪状态影响 | 是 |
| 8 | 每轮预演更新主/辅满足度与 total_satisfaction | 是 |
| 9 | 每轮预演更新 VAD/离散情绪 | 是 |
| 10 | 情绪转换遵守防跳变和红线规则 | 是 |
| 11 | 复盘报告显示沟通意图、诉求、OCEAN、情绪轨迹 | 是 |
| 12 | 复盘报告给出可执行下一步行动 | 是 |
| 13 | LLM 失败有 fallback，不阻断流程 | 是 |
| 14 | 旧流程兼容 | 是 |
| 15 | 后端 compile/test 与前端 build 通过 | 是 |
