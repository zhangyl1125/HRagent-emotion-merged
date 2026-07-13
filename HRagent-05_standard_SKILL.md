---
name: hragent-ocean-mvpi-emotion-rehearsal
description: "Use this skill when working on HRagent-05 performance-feedback rehearsal features involving communication intent recognition, employee motivation modeling with MVPI, OCEAN slider-based persona selection, VAD/Markov emotion transition, Employee Agent replies, or Coach Report generation. It defines execution workflow, business rules, schema contracts, prompt inputs, safety boundaries, tests, and acceptance criteria."
---

# HRagent-05 OCEAN + MVPI 动态情绪预演 Skill

## 0. 元信息

```yaml
name: hragent-ocean-mvpi-emotion-rehearsal
description: >-
  Use this skill when working on HRagent-05 performance-feedback rehearsal features involving communication intent recognition, employee motivation modeling with MVPI, OCEAN slider-based persona selection, VAD/Markov emotion transition, Employee Agent replies, or Coach Report generation. It defines execution workflow, business rules, schema contracts, prompt inputs, safety boundaries, tests, and acceptance criteria.
skill_id: hragent05-ocean-mvpi-emotion-rehearsal
version: 1.0.0
status: production-ready-spec
scope: HRagent-05 绩效反馈准备、谈前指导、员工对话预演、复盘报告
primary_users:
  - HRBP
  - Manager
  - AI Coding Agent
  - Product/Prompt Engineer
runtime_context:
  frontend: React + TypeScript + Vite
  backend: FastAPI + Python 3.11 + Pydantic + LangGraph/LangChain
  data_services: PostgreSQL + pgvector, Redis, MinerU
```

本 Skill 用于把上传文档中的业务规则工程化为可落地的员工模拟能力：沟通意图识别、员工主/辅诉求建模、OCEAN 大五人格滑块、Persona 选择、VAD + Markov 情绪转换、Employee Agent 回复、Coach Report 复盘。

---

## 1. 使用边界

### 1.1 何时必须使用

当任务涉及以下任意主题时启用本 Skill：

- 绩效反馈、发展型反馈、改进型反馈、退出型沟通、复合型沟通；
- 员工主诉求、辅诉求、MVPI、动机满足度；
- OCEAN 大五人格五条滑块、人格画像、Persona 选择；
- 员工情绪动态变化、VAD、Markov、对话预演；
- Employee Agent 话术生成；
- Coach Report、复盘报告、替代表达、下一步行动建议。

### 1.2 何时不得使用

以下情况不得把本 Skill 作为事实或合规结论来源：

- 正式劳动关系处理、解除、赔偿、争议仲裁、法律判断；
- 医学、心理诊断或人格障碍判断；
- 员工真实绩效定级、晋升、调薪审批结论；
- 缺少对话内容却要求对具体 HRBP 表现做事实性评价。

### 1.3 输出原则

所有输出必须满足：

1. **可解释**：情绪、诉求、人格、回复之间存在明确因果链。
2. **可追踪**：每轮对话都能记录输入、信号、满足度、情绪迁移、员工回复。
3. **可执行**：报告给出的建议必须能落地，不能只写“多共情”“加强沟通”。
4. **可回退**：LLM 失败时使用规则兜底，不阻断主流程。
5. **可验证**：关键字段通过 Schema 校验，边界值有测试用例。

---

## 2. 核心模型

```text
H = 对话历史，包括 HRBP 话术、员工回复、情绪日志、上下文事实
P = 角色人格/人设，包括 OCEAN、Persona、主诉求、辅诉求、难度
E_t = 当前情绪状态，包括离散情绪、VAD、动机满足度、强度、概率分布

f(H, P, E_t) -> (E_{t+1}, R)

E_{t+1} = 下一轮情绪状态
R = 员工下一句自然语言回复
```

工程解释：

```text
用户输入/HRBP 话术
  -> 话术信号分析
  -> 主/辅诉求满足度更新
  -> VAD + Markov 情绪迁移
  -> Persona + OCEAN 风格注入
  -> Employee Agent 回复
  -> emotion_log
  -> Coach Report 复盘
```

---

## 3. 输入契约

### 3.1 必需输入

```yaml
employee_profile:
  type: object
  required: true
  description: 员工岗位、级别、绩效事实、背景、已知约束
intent:
  type: enum
  required: true
  values:
    - development
    - improvement
    - exit
    - development_improvement
    - improvement_exit
motivation_profile:
  type: object
  required: true
  fields:
    primary_motivation: MVPI 六类之一
    secondary_motivation: MVPI 六类之一且不得等于 primary_motivation
    primary_weight: 0.7
    secondary_weight: 0.3
ocean_profile:
  type: object
  required: true
  fields:
    openness: 1..10
    conscientiousness: 1..10
    extraversion: 1..10
    agreeableness: 1..10
    neuroticism: 1..10
conversation_history:
  type: array
  required: false
emotion_state:
  type: object
  required: false
```

### 3.2 缺失输入兜底

```yaml
missing_intent:
  first: 请求用户选择
  second: LLM 根据 free_text + employee_profile 识别
  third: 关键词规则
  fallback: improvement
missing_motivation_profile:
  fallback: 按 intent 默认主/辅诉求
  confidence: low
missing_ocean_profile:
  fallback:
    openness: 5
    conscientiousness: 5
    extraversion: 5
    agreeableness: 5
    neuroticism: 5
  source: default
missing_emotion_state:
  emotion_id: calm_neutral
  vad:
    valence: 0.0
    arousal: 0.2
    dominance: 0.5
  primary_satisfaction: 0
  secondary_satisfaction: 0
  total_satisfaction: 0
```

---

## 4. 沟通意图识别

### 4.1 意图枚举

只允许以下 5 类业务意图：

```yaml
development:
  label: 发展型反馈
  goal: 认可绩效与潜力，规划成长路径，激励员工承担更大职责。
improvement:
  label: 改进型反馈
  goal: 客观指出绩效差距，明确改善标准、期限和支持资源。
exit:
  label: 退出型沟通
  goal: 在 HR/Legal 框架下基于事实启动合规退出流程。
development_improvement:
  label: 发展+改进混合反馈
  goal: 肯定发展潜力，同时指出局部短板并制定轻量改进方案。
improvement_exit:
  label: 改进+退出预警反馈
  goal: 设定最后窗口期，明确硬性目标和未达标后果。
```

### 4.2 识别优先级

```text
用户手动选择 > LLM 识别 > 关键词规则 > improvement
```

### 4.3 关键词规则

```yaml
development:
  positive_keywords:
    - 晋升
    - 发展路径
    - 成长机会
    - 继任
    - 更大职责
    - 培养
improvement:
  positive_keywords:
    - 改进
    - 差距
    - 不达标
    - 提升计划
    - 反馈短板
exit:
  positive_keywords:
    - 退出
    - 离岗
    - 岗位不匹配
    - 安置
    - 解除流程
improvement_exit:
  positive_keywords:
    - 最后机会
    - 退出预警
    - 未达标进入退出
    - PIP 后果
    - 硬性目标
development_improvement:
  positive_keywords:
    - 一方面发展
    - 同时改进
    - 优势与短板
    - 发展但需要补齐
```

### 4.4 约束

- 用户已手动确认的 intent 不得被模型覆盖。
- 复合意图不得被简化为单一意图。
- 出现“最后机会”“退出预警”“未达标进入退出流程”时，优先识别为 `improvement_exit`。
- `intent` 必须进入 `SessionState`、`EmotionState`、Employee Agent Prompt 和 Coach Report Prompt。

---

## 5. 员工诉求与 MVPI 动机模型

### 5.1 动机枚举

```yaml
commerce:
  label: 薪酬/奖金/收益
  employee_focus: 我的回报、奖金、薪酬是否匹配贡献。
power:
  label: 晋升/职权/影响力
  employee_focus: 我是否有更大职责、职位空间和影响力。
recognition:
  label: 认可/可见度/公平评价
  employee_focus: 我的贡献是否被看见、评价是否公平。
affiliation:
  label: 团队融洽/归属
  employee_focus: 团队是否支持我，我是否被接纳。
security:
  label: 稳定/安全感/岗位风险
  employee_focus: 我的岗位、流程、未来是否稳定可预期。
hedonism:
  label: 舒适工作环境/工作内容多样性
  employee_focus: 工作体验、节奏、内容是否可接受。
```

### 5.2 主/辅诉求权重

```text
primary_weight = 0.7
secondary_weight = 0.3
primary_satisfaction_0 = 0
secondary_satisfaction_0 = 0

total_satisfaction = primary_satisfaction * 0.7 + secondary_satisfaction * 0.3
```

### 5.3 默认诉求映射

```yaml
development:
  primary_motivation: power
  secondary_motivation: recognition
improvement:
  primary_motivation: recognition
  secondary_motivation: security
exit:
  primary_motivation: security
  secondary_motivation: recognition
development_improvement:
  primary_motivation: power
  secondary_motivation: recognition
improvement_exit:
  primary_motivation: security
  secondary_motivation: affiliation
```

### 5.4 话术加分维度

每轮 HRBP 话术必须抽取以下信号，分值范围 `0..1`：

```yaml
empathy: 是否承接员工情绪、允许负面感受存在
clarity: 结论、标准、后续安排是否清楚
specificity: 是否有具体事实、例子、时间点、衡量标准
respectfulness: 是否尊重员工，不做人身判断
pressure: 是否施压、威胁、压制表达
support_plan: 是否给出改进/成长/过渡支持计划
objective_evidence: 是否基于客观绩效证据
placement_support: 退出或过渡场景下是否有体面安置/流程说明
recognition: 是否具体认可贡献或努力
growth_path: 是否有成长路径、资源、里程碑
compensation_or_reward: 是否回应薪酬、奖金、回报或资源收益
red_line_hit: 是否命中红线
```

> 工程实现时字段名必须使用 ASCII：`growth_path`，不得使用中文或混合字符字段名。

### 5.5 满足度增减规则

```yaml
positive_rules:
  targeted_primary_empathy:
    effect: primary_delta +4..+10
  targeted_secondary_empathy:
    effect: secondary_delta +2..+6
  primary_mvpi_solution:
    effect: primary_delta +10..+25
  secondary_mvpi_support:
    effect: secondary_delta +4..+12
  objective_evidence_with_respect:
    effect: primary_delta +2..+8
  clear_next_step:
    effect: primary_delta +4..+12
negative_rules:
  deny_feeling:
    effect: primary_delta -8..-18, secondary_delta -4..-10
  vague_criticism:
    effect: primary_delta -6..-15
  pressure_without_plan:
    effect: primary_delta -8..-20
  red_line_hit:
    effect: primary_delta -20..-45, secondary_delta -10..-25
```

### 5.6 目的差异化加权

```yaml
development:
  high_gain_signals:
    - recognition
    - compensation_or_reward
    - growth_path
  low_gain_risk: 只谈限制或短板，不先肯定高绩效
improvement:
  high_gain_signals:
    - clarity
    - support_plan
    - growth_path
    - security
    - affiliation
  low_gain_risk: 只批评不给改进计划
exit:
  high_gain_signals:
    - placement_support
    - objective_evidence
    - empathy
    - respectfulness
    - clarity
  high_risk: 直接劝退、人格评价、无事实解释
development_improvement:
  full_gain_condition: 同时覆盖发展认可与局部改进路径
  half_gain_condition: 只夸优点不提短板，或只批评不认可亮点
improvement_exit:
  full_gain_condition: 同时覆盖最后改进窗口、硬性标准、支持资源、后果边界
  high_risk: 不给行为解释却评价态度差
```

---

## 6. OCEAN 大五人格滑块

### 6.1 五维定义

```yaml
O:
  key: openness
  label: 开放性
  line: 从细到粗表示从保守稳定到开放探索
C:
  key: conscientiousness
  label: 尽责性
  line: 从细到粗表示从执行波动到严谨闭环
E:
  key: extraversion
  label: 外向性
  line: 从细到粗表示从沉默内敛到主动外显
A:
  key: agreeableness
  label: 宜人性
  line: 从细到粗表示从直接挑战到合作体谅
N:
  key: neuroticism
  label: 情绪敏感性
  line: 从细到粗表示从稳定冷静到高度敏感
```

### 6.2 滑块工程约束

```yaml
range: 1..10
step: 1
default: 5
normalized: score / 10
source_values:
  - manual_slider
  - default
  - imported
ui_required_fields:
  - dimension_name
  - score
  - label
  - description
  - line_thickness_preview
```

### 6.3 五条线 10 档特征映射

#### O / 开放性

| 分值 | 标签 | 员工模拟特征 |
|---:|---|---|
| 1 | 保守固守 | 明显偏好既有规则，抗拒新方案，要求稳定依据。 |
| 2 | 偏传统 | 更相信成熟做法，对创新承诺保持谨慎。 |
| 3 | 谨慎尝试 | 可接受小范围试点，但需要低风险边界。 |
| 4 | 稳妥改良 | 愿意在现有框架内优化，不喜欢剧烈变化。 |
| 5 | 开放均衡 | 能在稳定和探索之间切换。 |
| 6 | 愿意探索 | 对成长机会、学习资源有正向兴趣。 |
| 7 | 主动学习 | 主动询问新职责、新方法和发展资源。 |
| 8 | 创新导向 | 倾向提出新方案，关注突破和空间。 |
| 9 | 跨界探索 | 愿意承担未知任务，但可能低估落地约束。 |
| 10 | 高度开拓 | 强烈追求变化、创新和自主空间。 |

#### C / 尽责性

| 分值 | 标签 | 员工模拟特征 |
|---:|---|---|
| 1 | 极弱计划 | 缺少计划感，容易回避承诺和检查点。 |
| 2 | 低自律 | 需要外部提醒，行动闭环弱。 |
| 3 | 依赖提醒 | 能执行明确任务，但容易漏掉跟进。 |
| 4 | 执行波动 | 状态好时能推进，压力下计划变形。 |
| 5 | 基本可靠 | 能完成常规要求，需要关键节点确认。 |
| 6 | 有计划 | 关注目标、步骤和时间点。 |
| 7 | 责任稳定 | 愿意承担责任，重视复盘和承诺。 |
| 8 | 高标准 | 关注事实、质量标准和评估口径。 |
| 9 | 严谨闭环 | 会追问证据链、里程碑和验收标准。 |
| 10 | 强结构化 | 强烈要求逻辑、数据、边界和流程一致性。 |

#### E / 外向性

| 分值 | 标签 | 员工模拟特征 |
|---:|---|---|
| 1 | 强内向沉默 | 压力下大量沉默，倾向短句回应。 |
| 2 | 少表达 | 不主动展开，除非被安全地邀请。 |
| 3 | 谨慎表达 | 会表达核心担忧，但保留较多。 |
| 4 | 偏安静 | 可交流，但不主动主导谈话。 |
| 5 | 表达均衡 | 能问答互动，表达强度适中。 |
| 6 | 主动表达 | 会主动说明背景和诉求。 |
| 7 | 外显互动 | 会追问、澄清、争取资源。 |
| 8 | 主导节奏 | 倾向把谈话拉回自己关注点。 |
| 9 | 强势表达 | 可能连续追问、谈条件、要求明确答复。 |
| 10 | 高度外向 | 强烈表达诉求，情绪和谈判倾向都更外显。 |

#### A / 宜人性

| 分值 | 标签 | 员工模拟特征 |
|---:|---|---|
| 1 | 强对抗 | 直接挑战结论，低信任，高交换意识。 |
| 2 | 低配合 | 优先保护自身利益，容易质疑公平性。 |
| 3 | 直接挑战 | 会明确指出不同意和要求依据。 |
| 4 | 保留合作 | 可合作，但需要先处理疑虑。 |
| 5 | 合作均衡 | 愿意沟通，也会表达不满。 |
| 6 | 愿意配合 | 在被尊重时较快进入问题解决。 |
| 7 | 信任合作 | 倾向理解对方立场，愿意共同制定计划。 |
| 8 | 高体谅 | 会照顾关系，但可能压抑真实诉求。 |
| 9 | 高顺应 | 容易表面接受，需要主动挖掘真实担忧。 |
| 10 | 高度利他 | 强关系导向，可能过度让步或回避冲突。 |

#### N / 情绪敏感性

| 分值 | 标签 | 员工模拟特征 |
|---:|---|---|
| 1 | 高度稳定 | 压力下仍保持冷静，主要关注事实。 |
| 2 | 稳定冷静 | 负面反馈下情绪波动很低。 |
| 3 | 低敏感 | 能承受批评，但仍关注公平。 |
| 4 | 可控波动 | 会短暂不安，能较快回到理性。 |
| 5 | 情绪均衡 | 反应中等，取决于话术质量。 |
| 6 | 略敏感 | 对否定性语言较敏感，需要承接。 |
| 7 | 压力易焦虑 | 容易担心未来影响和岗位风险。 |
| 8 | 高防御 | 面对不清晰反馈会明显防御或受挫。 |
| 9 | 强烈不安 | 可能反复确认是否被否定或被放弃。 |
| 10 | 高度应激 | 在高压或红线话术下容易快速升级到强防御、沉默或焦虑。 |

---

## 7. Persona 选择

### 7.1 硬约束

- 最终 `selected_persona_id` 必须存在于 `backend/business_config/personas.yaml`。
- LLM 不得创造新 persona_id。
- LLM 只能在候选中选择、解释原因、生成 `persona_override`。
- `persona_override` 只能补充风格，不得突破 Employee Agent 安全边界。

### 7.2 候选规则

```yaml
rules:
  - if: N >= 7 and A <= 4
    persona_id: defensive_rebuttal
  - if: N >= 7 and E <= 3
    persona_id: silent_avoidant
  - if: N >= 7 and A >= 6
    persona_id: emotionally_hurt
  - if: C >= 8 and O <= 5
    persona_id: data_logic_challenger
  - if: E >= 7 and A <= 4
    persona_id: outcome_negotiator
  - if: A <= 3 and primary_motivation in [commerce, power]
    persona_id: outcome_negotiator
  - if: A >= 8 and C <= 5
    persona_id: support_dependent
  - if: C <= 4 and A >= 5
    persona_id: overpromising
  - if: O <= 4 and N >= 6
    persona_id: external_attribution
fallback:
  development: outcome_negotiator
  improvement: data_logic_challenger
  exit: defensive_rebuttal
  development_improvement: emotionally_hurt
  improvement_exit: defensive_rebuttal
```

### 7.3 结构化输出

```json
{
  "selected_persona_id": "data_logic_challenger",
  "confidence": 0.82,
  "reason": "C=9 表示高标准和证据导向，O=4 表示偏稳定，主诉求为 recognition，适合数据逻辑追问型。",
  "ocean_summary": "该员工重视事实链、评价口径和明确标准，对泛泛反馈不易接受。",
  "persona_override": "在追问时保持克制，但会连续要求样本、标准和后续验证方式。",
  "risk_notes": ["避免无证据评价", "避免越权承诺评级或晋升"]
}
```

---

## 8. VAD + Markov 情绪转换

### 8.1 情绪状态 Schema

```yaml
emotion_id: string
vad:
  valence: -1..1      # 情绪正负
  arousal: 0..1       # 激活强度
  dominance: 0..1     # 控制感
primary_satisfaction: 0..100
secondary_satisfaction: 0..100
total_satisfaction: 0..100
emotion_probability: map[string, float]
emotion_band: string
turn_index: integer
transition_reason: string
```

### 8.2 基础情绪集合

```yaml
calm_neutral:
  vad: {valence: 0.0, arousal: 0.20, dominance: 0.50}
guarded_hesitant:
  vad: {valence: -0.20, arousal: 0.35, dominance: 0.35}
anxious_worried:
  vad: {valence: -0.45, arousal: 0.65, dominance: 0.25}
hurt_disappointed:
  vad: {valence: -0.55, arousal: 0.55, dominance: 0.25}
defensive_resistant:
  vad: {valence: -0.45, arousal: 0.70, dominance: 0.55}
frustrated_pushback:
  vad: {valence: -0.60, arousal: 0.78, dominance: 0.60}
angry_unfairness:
  vad: {valence: -0.75, arousal: 0.90, dominance: 0.70}
silent_withdrawn:
  vad: {valence: -0.50, arousal: 0.25, dominance: 0.15}
skeptical_challenging:
  vad: {valence: -0.25, arousal: 0.55, dominance: 0.65}
negotiating_firm:
  vad: {valence: -0.10, arousal: 0.55, dominance: 0.75}
reflective_softening:
  vad: {valence: 0.15, arousal: 0.35, dominance: 0.55}
cooperative_constructive:
  vad: {valence: 0.45, arousal: 0.45, dominance: 0.70}
```

### 8.3 情绪区间

```yaml
extreme_resistance:
  range: 0 <= total_satisfaction < 20
  behavior: 极端对抗、防御、焦虑、沉默或质疑。
negative_defensive:
  range: 20 <= total_satisfaction < 40
  behavior: 负面仍强，但开始对具体事实或支持有反应。
rational_softening:
  range: 40 <= total_satisfaction < 60
  behavior: 火气下降，愿意沟通，但残留不满。
active_engagement:
  range: 60 <= total_satisfaction < 80
  behavior: 基本进入问题解决，但仍关注核心诉求兑现。
emotion_resolved:
  range: 80 <= total_satisfaction <= 100
  behavior: 负面明显消解，接纳反馈，主动对齐后续行动。
```

### 8.4 Markov 选择公式

```text
base = log(T[current_emotion][candidate_emotion] + epsilon)
signal_score = affinity(candidate_emotion, extracted_signal)
ocean_bias = bias(candidate_emotion, ocean_profile)
motivation_gap = gap_bias(candidate_emotion, primary_gap, secondary_gap)
satisfaction_bias = band_bias(candidate_emotion, total_satisfaction)
redline_bias = redline_boost(candidate_emotion, red_line_hit)

score(candidate) = base
                 + alpha * signal_score
                 + beta  * ocean_bias
                 + gamma * motivation_gap
                 + delta * satisfaction_bias
                 + redline_bias

P(candidate) = softmax(lambda * score(candidate))
E_{t+1} = argmax(P) 或按策略采样
```

推荐默认参数：

```yaml
lambda: 2.2
alpha: 1.25
beta: 0.85
gamma: 0.70
delta: 0.90
epsilon: 0.0001
strategy: maximum_probability
```

### 8.5 防跳变规则

- 非红线情况下，单轮最多跨越 2 个情绪强度阶梯。
- `cooperative_constructive` 不得一轮跳到 `angry_unfairness`，除非 `red_line_hit=true`。
- `total_satisfaction >= 80` 时，除红线外不得输出高强度负面情绪。
- `total_satisfaction < 20` 时，不得直接输出完全合作，除非连续两轮高共情且有清晰支持计划。
- `silent_withdrawn` 需要低压力开放问题、停顿空间或安全感承诺才能缓和。
- 高 N 员工更容易焦虑、防御、受挫；高 C 员工更关注事实和标准；高 E 员工更外显；低 A 员工更挑战；低 E 员工更易沉默。

---

## 9. Employee Agent 回复生成

### 9.1 回复契约

Employee Agent 只能输出员工直接说出口的话。

```yaml
output_format: plain_text
allowed_speaker: employee
max_paragraphs: 1
max_sentences: 4
forbidden:
  - Markdown
  - 分析过程
  - 系统规则
  - 评价 HRBP 的内部评分
  - 法律或政策权威结论
```

### 9.2 回复必须体现

1. 当前主诉求是否被看见。
2. 当前辅诉求是否被回应。
3. 当前 OCEAN 人格风格。
4. 当前情绪状态与上一轮变化。
5. 当前 intent 下员工合理关注点。

### 9.3 风格约束

```yaml
high_N:
  must_not: 一轮内突然完全冷静或无条件接纳
high_C:
  must_include_when_relevant: 事实、标准、时间点、证据、验收方式
high_E:
  may_include: 主动追问、争取资源、表达立场
low_E:
  style: 短句、保留、停顿、回避
low_A:
  may_include: 直接挑战结论、要求公平交换
high_A:
  style: 合作、顾及关系，但保留未满足诉求的不安
```

---

## 10. Coach Report 复盘

### 10.1 报告结构

```markdown
# 绩效沟通预演复盘报告

## 1. 总体结论
## 2. 沟通意图匹配
## 3. 员工诉求与满足度
## 4. OCEAN 人格适配
## 5. 情绪转换轨迹
## 6. 情绪承接与事实沟通
## 7. 做得好的地方
## 8. 需要改进的地方
## 9. 高风险点与替代表达
## 10. 下一步行动
## 11. 免责声明
```

### 10.2 必须包含字段

```yaml
intent_alignment:
  required: true
  description: 沟通意图是否清晰一致，是否偏离目标。
demand_satisfaction:
  required: true
  description: 主/辅诉求是否被回应，满足度如何变化。
ocean_persona_report:
  required: true
  description: HRBP 话术是否适配员工 OCEAN 与 Persona。
emotion_transition:
  required: true
  description: 情绪轨迹、最高风险点、缓和节点。
emotion_holding:
  required: true
  description: 是否承接/接纳员工情绪。
fact_communication:
  required: true
  description: 是否回到产出要求、事实、标准、例子。
future_plan:
  required: true
  description: 是否给出明确发展、改进或退出相关计划。
better_phrases:
  required: true
  item_schema:
    original: string
    risk: string
    alternative: string
    reason: string
executable_next_actions:
  required: true
  rule: 必须使用动词开头，包含对象、时间、产出物或验证标准。
disclaimer:
  required: true
  text: 本报告仅用于绩效沟通训练，不构成正式 HR、绩效、法律或劳动关系处理结论。
```

### 10.3 复盘判断标准

报告必须检查主管是否做到：

1. 开场定调：说明绩效结果、产出是否符合预期。
2. 承接情绪：接纳被反馈者情绪，从员工角度解释其情绪来源。
3. 回到产出：从方向正确性、结果是否满足预期、达成过程行为三个维度说明要求。
4. 未来计划：给出明确的发展、改进或退出流程下一步。

### 10.4 报告禁止

- 不得编造对话中没有出现的事实。
- 不得把员工人格或心理状态写成诊断。
- 不得替 HR、Manager、Legal 下正式结论。
- 不得输出空泛建议，例如“加强沟通”“多换位思考”，除非转化为具体行动。
- 退出或改进+退出场景必须提示 HR/Legal 升级边界。

---

## 11. 工程落地建议

### 11.1 优先复用文件

```text
backend/business_config/intents.yaml
backend/business_config/personas.yaml
backend/schemas/state.py
backend/schemas/emotion.py
backend/schemas/motivation.py
backend/services/motivation_scoring_service.py
backend/services/attitude_transition_engine.py
backend/services/emotion_analyzer.py
backend/services/emotion_state_service.py
backend/services/rehearsal_service.py
backend/services/dynamic_persona_builder.py
backend/services/setup_service.py
backend/api/routes/setup.py
backend/api/routes/rehearsal.py
backend/prompts/employee/reply.jinja2
backend/prompts/coach/report.jinja2
frontend/src/pages/steps/PersonaStep.tsx
frontend/src/pages/steps/ReportStep.tsx
frontend/src/types/domain.ts
frontend/src/api/client.ts
```

### 11.2 建议新增文件

```text
backend/business_config/ocean_traits.yaml
backend/schemas/ocean.py
backend/services/ocean_persona_selector.py
backend/services/motivation_extraction_service.py
backend/services/vad_markov_engine.py
backend/prompts/setup/ocean_persona_select.jinja2
backend/prompts/setup/motivation_extract.jinja2
tests/test_ocean_persona_selector.py
tests/test_vad_markov_engine.py
tests/test_motivation_profile.py
```

### 11.3 API 兼容要求

新增字段必须为可选字段并有默认值，避免破坏旧 Session：

```yaml
SessionState:
  ocean_profile: OceanProfile | None = None
  motivation_profile: MotivationProfile | None = None
  ocean_persona_selection: OceanPersonaSelection | None = None
EmotionState:
  vad: VadState = default
  emotion_probability: dict[str, float] = {}
```

### 11.4 Intent 兼容层

若工程中存在旧枚举 `motivation` / `motivation_improvement`，必须建立兼容映射，不得直接删除旧值：

```yaml
legacy_to_current:
  motivation: development
  improvement: improvement
  exit: exit
  motivation_improvement: development_improvement
  improvement_exit: improvement_exit
current_to_legacy:
  development: motivation
  improvement: improvement
  exit: exit
  development_improvement: motivation_improvement
  improvement_exit: improvement_exit
```

---

## 12. Prompt 注入契约

### 12.1 Employee Reply Prompt 必须注入

```yaml
employee_profile: required
intent_config: required
persona_config: required
difficulty_config: required
ocean_profile: required
motivation_profile: required
ocean_persona_selection: required
emotion_state: required
conversation_history: required
business_context_cheatsheet: optional
```

### 12.2 Coach Report Prompt 必须注入

```yaml
conversation_history: required
emotion_log: required
intent: required
motivation_profile: required
ocean_profile: required
ocean_persona_selection: required
employee_profile: required
coach_schema: required
redline_result: optional
```

---

## 13. 测试用例要求

### 13.1 单元测试

必须覆盖：

- OCEAN 分值边界：0、1、5、10、11。
- 主诉求和辅诉求相同时报错。
- 缺失 OCEAN 时五维默认 5。
- Persona 选择只返回已存在 persona_id。
- `total_satisfaction` 公式严格为 `0.7/0.3`。
- 红线命中时情绪允许快速升级。
- 非红线时情绪不可跨越超过 2 个阶梯。
- `total_satisfaction >= 80` 时不得输出高强度负面情绪。
- Employee Agent 不输出 Markdown。
- Coach Report 的 `better_phrases` 包含原句、风险、替代表达、原因。

### 13.2 黄金场景

```yaml
case_1_development_high_C:
  intent: development
  ocean: {O: 6, C: 9, E: 5, A: 6, N: 3}
  motivation: {primary: power, secondary: recognition}
  expected_persona: data_logic_challenger
  expected_employee_focus: 晋升标准、发展路径、事实依据
case_2_improvement_high_N_low_A:
  intent: improvement
  ocean: {O: 4, C: 6, E: 6, A: 2, N: 8}
  motivation: {primary: recognition, secondary: security}
  expected_persona: defensive_rebuttal
  expected_employee_focus: 公平性、是否被否定、岗位风险
case_3_exit_low_E_high_N:
  intent: exit
  ocean: {O: 3, C: 5, E: 2, A: 5, N: 9}
  motivation: {primary: security, secondary: recognition}
  expected_persona: silent_avoidant
  expected_employee_focus: 流程、安置、被记录方式
case_4_development_improvement_high_A:
  intent: development_improvement
  ocean: {O: 7, C: 4, E: 5, A: 9, N: 6}
  motivation: {primary: power, secondary: recognition}
  expected_persona: support_dependent
  expected_employee_focus: 保持发展机会、明确短板补齐方式
case_5_improvement_exit_high_E_low_A:
  intent: improvement_exit
  ocean: {O: 5, C: 7, E: 8, A: 3, N: 8}
  motivation: {primary: security, secondary: affiliation}
  expected_persona: defensive_rebuttal_or_outcome_negotiator
  expected_employee_focus: 最后期限、后果、资源、换岗或缓冲可能
```

---

## 14. 验收命令

```bash
python -m compileall backend
pytest tests/test_agents.py tests/test_workflows.py tests/test_coach_schema.py -q
pytest tests/test_ocean_persona_selector.py tests/test_vad_markov_engine.py tests/test_motivation_profile.py -q
cd frontend && npm run build
```

如无法运行测试，最终交付必须说明：

```text
未验证项：
- 未执行命令：...
- 原因：...
- 风险：...
- 建议下一步：...
```

---

## 15. 最小可交付 Definition of Done

完成本 Skill 对应需求时，必须满足：

- 用户能选择或识别 5 类沟通意图。
- 用户能确认主诉求和辅诉求。
- 用户能拖动 O/C/E/A/N 五条 1~10 档滑块。
- 后端能校验 OCEAN、MVPI、intent 并写入 SessionState。
- 后端能选择已存在的 persona_id。
- 每轮预演能更新主/辅满足度、总满足度和情绪状态。
- Employee Agent 回复符合人格、诉求、意图、情绪状态。
- 复盘报告包含诉求、OCEAN、情绪轨迹、高风险话术、替代表达和下一步行动。
- 构建或测试失败时有明确说明，不隐瞒风险。
