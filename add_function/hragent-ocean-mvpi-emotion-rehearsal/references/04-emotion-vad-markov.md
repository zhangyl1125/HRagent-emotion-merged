## 7. 情绪转换模型：VAD + Markov + LLM

### 7.1 情绪状态结构

扩展 `EmotionState`，保留旧字段，新增字段：

```python
class VadState(BaseModel):
    valence: float = Field(ge=-1, le=1)     # 情绪正负，-1 最负，1 最正
    arousal: float = Field(ge=0, le=1)      # 激活强度，0 平静，1 高激活
    dominance: float = Field(ge=0, le=1)    # 控制感，0 失控/无力，1 高控制感

class EmotionState(BaseModel):
    # existing fields remain
    current_attitude: EmployeeAttitude = EmployeeAttitude.CALM_NEUTRAL
    intensity: int = Field(default=20, ge=0, le=100)
    primary_satisfaction: float = Field(default=0.0, ge=0, le=100)
    secondary_satisfaction: float = Field(default=0.0, ge=0, le=100)
    total_satisfaction: float = Field(default=0.0, ge=0, le=100)

    # new fields
    emotion_id: str = "calm_neutral"
    vad: VadState = Field(default_factory=lambda: VadState(valence=0.0, arousal=0.2, dominance=0.5))
    emotion_probability: dict[str, float] = Field(default_factory=dict)
    ocean_influence: dict[str, float] = Field(default_factory=dict)
```

### 7.2 12 个基础情绪状态

| emotion_id | 中文 | V | A | D | 映射到现有 attitude |
|---|---|---:|---:|---:|---|
| `calm_neutral` | 平静中性 | 0.00 | 0.20 | 0.55 | `calm_neutral` |
| `guarded_hesitant` | 谨慎防备 | -0.20 | 0.35 | 0.40 | `guarded_hesitant` |
| `anxious_worried` | 焦虑担心 | -0.55 | 0.75 | 0.25 | `guarded_hesitant` |
| `hurt_disappointed` | 受挫失望 | -0.60 | 0.55 | 0.25 | `defensive_resistant` |
| `defensive_resistant` | 防御抵触 | -0.55 | 0.65 | 0.45 | `defensive_resistant` |
| `frustrated_pushback` | 挫败反驳 | -0.70 | 0.80 | 0.55 | `frustrated_pushback` |
| `angry_unfairness` | 愤怒不公 | -0.85 | 0.90 | 0.65 | `frustrated_pushback` |
| `silent_withdrawn` | 沉默退缩 | -0.50 | 0.30 | 0.15 | `silent_withdrawn` |
| `skeptical_challenging` | 质疑追问 | -0.35 | 0.60 | 0.65 | `defensive_resistant` |
| `negotiating_firm` | 坚持谈判 | -0.25 | 0.55 | 0.75 | `guarded_hesitant` |
| `reflective_softening` | 反思松动 | 0.15 | 0.35 | 0.55 | `reflective_softening` |
| `cooperative_constructive` | 合作建设 | 0.45 | 0.35 | 0.70 | `cooperative_constructive` |

### 7.3 Markov 基础转移矩阵

基础概率由 VAD 距离决定：

```text
d(i,j) = sqrt(
  1.2 * (V_i - V_j)^2 +
  1.0 * (A_i - A_j)^2 +
  0.8 * (D_i - D_j)^2
)

base_prob(i,j) = exp(-lambda * d(i,j)) * adjacency_penalty(i,j)
lambda = 2.2

如果 j 与 i 在情绪强度阶梯上距离 > 2：adjacency_penalty = 0.10
否则：adjacency_penalty = 1.00
```

### 7.4 对话信号加权

每轮 HRBP 话术经过 `EmotionAnalyzer` 输出 `EmotionSignal`：

```python
class EmotionSignal(BaseModel):
    empathy: float
    clarity: float
    specificity: float
    respectfulness: float
    pressure: float
    support_plan: float
    objective_evidence: float
    placement_support: float
    recognition: float
    growth_path: float
    compensation_or_reward: float
    red_line_hit: bool
    likely_employee_reaction: Literal["escalate", "soften", "withdraw", "stay"]
```

加权规则：

```text
red_line_hit = true:
  增加 angry_unfairness / frustrated_pushback / defensive_resistant 概率
  降低 cooperative_constructive / reflective_softening 概率

empathy >= 0.65 且 specificity >= 0.50:
  增加 reflective_softening 概率

support_plan >= 0.65:
  增加 cooperative_constructive / reflective_softening 概率

pressure >= 0.70 且 empathy < 0.30:
  增加 anxious_worried / defensive_resistant / frustrated_pushback 概率

objective_evidence >= 0.60 且 respectfulness >= 0.50:
  对 C 高员工增加 skeptical_challenging -> reflective_softening 的概率

placement_support >= 0.60:
  对 exit / improvement_exit 增加 guarded_hesitant -> reflective_softening 的概率
```

### 7.5 OCEAN 对情绪转换的影响

```text
N 高：提高 anxious_worried、hurt_disappointed、defensive_resistant 的先验概率。
C 高：提高 skeptical_challenging 的先验概率；若事实清晰，提高 reflective_softening。
E 高：提高 frustrated_pushback、negotiating_firm 的外显概率。
E 低：提高 silent_withdrawn 概率。
A 低：提高 angry_unfairness、negotiating_firm、defensive_resistant。
A 高：提高 cooperative_constructive，但 N 高时转为 hurt_disappointed。
O 高：提高 reflective_softening 和 growth_path 相关缓和概率。
O 低：提高 guarded_hesitant 和 security 相关防备概率。
```

### 7.6 最终转移公式

```text
score_j = log(base_prob(current_emotion, j) + eps)
          + alpha * signal_bias_j
          + beta * ocean_bias_j
          + gamma * motivation_bias_j
          + delta * satisfaction_bias_j
          + redline_bias_j

T_t(current_emotion -> j) = softmax(score_j)

E_{t+1} = select_next_emotion(T_t, strategy)
```

默认参数：

```python
alpha = 1.25
beta = 0.85
gamma = 0.70
delta = 0.90
eps = 1e-6
strategy = "maximum_probability"
```

### 7.7 选择策略

支持三种策略，配置项为 `EMOTION_SELECTION_STRATEGY`：

| 策略 | 配置值 | 说明 | 适用场景 |
|---|---|---|---|
| 最大概率 | `maximum_probability` | 选择概率最高情绪 | 默认，稳定可测 |
| 期望 VAD | `expected_value` | 计算 VAD 期望后映射最近情绪 | 更平滑 |
| 概率采样 | `probabilistic_sampling` | 按概率随机采样 | 演示多样性，不用于自动测试 |

### 7.8 防跳变规则

1. 非红线情况下，单轮最多跨越 2 个情绪强度阶梯。
2. `cooperative_constructive` 不得一轮跳到 `angry_unfairness`，除非 `red_line_hit=true`。
3. `silent_withdrawn` 需要低压力开放问题或明确安全感才能缓和。
4. 满足度 `total_satisfaction >= 80` 时，除红线外不得输出高强度负面情绪。
5. 满足度 `<20` 时，不得直接输出完全合作，除非连续两轮 `empathy>=0.75` 且 `support_plan>=0.65`。

---
## 10. VAD Markov Engine 实现

### 10.1 新增 `backend/services/vad_markov_engine.py`

核心接口：

```python
class VadMarkovEngine:
    def compute_next_emotion(
        self,
        *,
        current_state: EmotionState,
        signal: EmotionSignal,
        ocean_profile: OceanProfile | None,
        motivation_profile: MotivationProfile | None,
        interview_purpose: InterviewPurpose | str,
    ) -> EmotionState:
        ...
```

### 10.2 与现有 `AttitudeTransitionEngine` 的关系

修改 `AttitudeTransitionEngine._compute_motivation_state`：

```text
现有逻辑：
  MotivationScoringService -> total_satisfaction -> EmotionStateService.expression_for

新逻辑：
  MotivationScoringService -> total_satisfaction -> VadMarkovEngine.compute_next_emotion
  -> EmotionStateService 只作为 fallback 或旧字段映射
```

### 10.3 输出字段要求

每轮 `emotion_log` 必须记录：

```json
{
  "turn_index": 3,
  "employee_attitude_before": "guarded_hesitant",
  "employee_attitude_after": "defensive_resistant",
  "emotion_id_before": "guarded_hesitant",
  "emotion_id_after": "skeptical_challenging",
  "vad_before": {"valence": -0.2, "arousal": 0.35, "dominance": 0.4},
  "vad_after": {"valence": -0.35, "arousal": 0.6, "dominance": 0.65},
  "transition_probability": 0.42,
  "top_candidates": [
    {"emotion_id": "skeptical_challenging", "probability": 0.42},
    {"emotion_id": "defensive_resistant", "probability": 0.31}
  ],
  "primary_delta": 6.0,
  "secondary_delta": 3.0
}
```

如短期不扩展 `ConversationEmotionLog` schema，可先把新增字段放入 `signal.risk_flags` 不合适；正确做法是扩展 schema，前端安全忽略未知字段。

---
