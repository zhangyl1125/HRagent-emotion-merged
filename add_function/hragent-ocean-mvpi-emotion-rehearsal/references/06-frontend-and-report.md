## 11. 前端改造清单

### 11.1 `domain.ts` 新增类型

```ts
export interface OceanDimensionValue {
  score: number;
  normalized: number;
  label: string;
  description: string;
}

export interface OceanProfile {
  openness: OceanDimensionValue;
  conscientiousness: OceanDimensionValue;
  extraversion: OceanDimensionValue;
  agreeableness: OceanDimensionValue;
  neuroticism: OceanDimensionValue;
  source?: 'manual_slider' | 'default' | 'imported';
  completed?: boolean;
}

export interface MotivationProfile {
  primary_motivation: string;
  secondary_motivation?: string | null;
  primary_weight?: number;
  secondary_weight?: number;
  primary_confidence?: number;
  secondary_confidence?: number;
  evidence?: string[];
  user_confirmed?: boolean;
}

export interface OceanPersonaSelection {
  selected_persona_id: string;
  confidence: number;
  reason: string;
  ocean_summary: string;
  persona_override?: string | null;
  risk_notes?: string[];
}
```

### 11.2 `client.ts` 新增 API

```ts
inferMotivation: (sessionId: string) => requestJson<SessionState>(`/setup/${sessionId}/motivation/infer`, {
  method: 'POST',
  body: '{}',
}),
confirmMotivation: (sessionId: string, payload: MotivationProfile) => requestJson<SessionState>(`/setup/${sessionId}/motivation`, {
  method: 'PATCH',
  body: JSON.stringify(payload),
}),
confirmOcean: (sessionId: string, oceanProfile: OceanProfile, difficultyId: string) => requestJson<SessionState>(`/setup/${sessionId}/ocean`, {
  method: 'PATCH',
  body: JSON.stringify({ ocean_profile: oceanProfile, difficulty_id: difficultyId, auto_select_persona: true }),
}),
```

### 11.3 `PersonaStep.tsx` 页面结构

替换当前 Persona 列表优先的交互为：

```text
左侧主卡片：
  1. 员工诉求确认
  2. OCEAN 五条滑块
  3. 选择难度
  4. 按钮：生成并确认模拟设定

右侧摘要卡片：
  1. 员工信息
  2. 沟通意图
  3. 主诉求/辅诉求
  4. OCEAN 摘要
  5. 大模型选择的人格 Persona
  6. 难度
```

### 11.4 滑块组件行为

```tsx
function OceanSlider({ dimension, value, onChange }) {
  return (
    <div className="ocean-slider-row">
      <div className="ocean-slider-head">
        <strong>{dimension.label}</strong>
        <span>{value.score}/10 · {value.label}</span>
      </div>
      <input
        type="range"
        min={1}
        max={10}
        step={1}
        value={value.score}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label={dimension.label}
      />
      <p>{value.description}</p>
    </div>
  );
}
```

### 11.5 验收标准

1. 五条滑块必须全部存在，默认值为 5。
2. 每次拖动，当前标签必须实时更新。
3. 点击确认后，`SessionState.ocean_profile` 必须有五维完整数据。
4. 后端返回 persona 后，右侧摘要必须展示 `persona.name`、`ocean_summary`、`reason`。
5. 旧 Persona 选择流程如仍保留，不得与 OCEAN 结果冲突；最终以 `state.persona` 为唯一生效人格。

---
## 12. 复盘报告增强

### 12.1 报告新增字段

修改 `backend/schemas/coach.py`，在 `CoachReport` 中新增可选字段，保持兼容：

```python
class DemandSatisfactionSummary(BaseModel):
    primary_motivation: str | None = None
    secondary_motivation: str | None = None
    primary_satisfaction_final: float | None = None
    secondary_satisfaction_final: float | None = None
    total_satisfaction_final: float | None = None
    key_turns: list[str] = Field(default_factory=list)

class OceanReportSummary(BaseModel):
    ocean_summary: str | None = None
    selected_persona_id: str | None = None
    selected_persona_name: str | None = None
    manager_adaptation_score: int | None = Field(default=None, ge=0, le=100)
    adaptation_notes: list[str] = Field(default_factory=list)

class EmotionTransitionSummary(BaseModel):
    start_emotion: str | None = None
    end_emotion: str | None = None
    peak_risk_emotion: str | None = None
    trajectory_summary: str | None = None
    turn_level_observations: list[str] = Field(default_factory=list)

class CoachReport(BaseModel):
    # existing fields remain
    demand_satisfaction: DemandSatisfactionSummary | None = None
    ocean_persona_report: OceanReportSummary | None = None
    emotion_transition: EmotionTransitionSummary | None = None
    intent_alignment: str | None = None
    conversation_structure_feedback: list[str] = Field(default_factory=list)
    executable_next_actions: list[str] = Field(default_factory=list)
```

### 12.2 报告必须覆盖的复盘维度

| 维度 | 判断内容 | 输出形式 |
|---|---|---|
| 沟通意图一致性 | HRBP 是否围绕当前 intent 推进 | `intent_alignment` |
| 员工诉求回应 | 主诉求/辅诉求是否被看见并落地 | `demand_satisfaction` |
| OCEAN 适配 | HRBP 是否适配员工人格特点 | `ocean_persona_report` |
| 情绪承接 | 是否共情、接纳、避免打压 | `key_strengths` / `key_improvements` |
| 事实沟通 | 是否有绩效事实、标准、例子和证据链 | `task_results` / `citations` |
| 后续计划 | 是否有明确行动、时间点、支持资源 | `executable_next_actions` |
| 风险表达 | 是否出现红线或高风险措辞 | `top_risks` / `better_phrases` |

### 12.3 `coach/report.jinja2` 新增要求

```jinja2
你必须基于 task_results、emotion_log、profile、motivation_profile、ocean_profile、ocean_persona_selection 生成最终报告。
不得编造对话中没有出现的事实。

报告必须包含：
1. 沟通意图是否清晰：HRBP 的每轮话术是否服务于当前 intent。
2. 员工主/辅诉求：哪些话术提高或降低了满足度。
3. OCEAN 适配：HRBP 是否针对员工的 O/C/E/A/N 特征调整表达。
4. 情绪转换：从开始到结束的情绪轨迹、最高风险点、缓和节点。
5. 情绪承接：是否有 2-3 次承接情绪，是否从员工角度解释其情绪。
6. 事实沟通：是否回到产出要求、方向正确性、结果是否达预期、达成过程行为。
7. 发展/改进/退出计划：是否有下一步明确计划，不同 intent 下关注点是否正确。
8. 更好表达：给出原句、替代表达、原因。
9. 下一步行动：输出可执行 action，不输出空泛建议。
```

### 12.4 前端报告 Markdown 模板

前端 `ReportStep.tsx` 渲染时按以下结构展示：

```markdown
# 绩效沟通预演复盘报告

## 1. 总体结论
- 综合评分：{{ overall_score }}/100
- 当前沟通意图：{{ intent_name }}
- 最终员工状态：{{ end_emotion }}
- 总结：{{ summary }}

## 2. 沟通意图匹配
{{ intent_alignment }}

## 3. 员工诉求与满足度
| 诉求 | 类型 | 最终满足度 | 关键影响话术 |
|---|---|---:|---|
| 主诉求 | {{ primary_motivation }} | {{ primary_satisfaction_final }} | {{ primary_key_turn }} |
| 辅诉求 | {{ secondary_motivation }} | {{ secondary_satisfaction_final }} | {{ secondary_key_turn }} |

## 4. OCEAN 人格适配
- 人格摘要：{{ ocean_summary }}
- 推荐 Persona：{{ selected_persona_name }}
- 适配评分：{{ manager_adaptation_score }}/100
- 主要观察：{{ adaptation_notes }}

## 5. 情绪转换轨迹
| 回合 | HRBP 关键话术 | 员工情绪前 | 员工情绪后 | 满足度变化 | 解释 |
|---:|---|---|---|---:|---|
{{ emotion_transition_rows }}

## 6. 做得好的地方
{{ key_strengths }}

## 7. 需要改进的地方
{{ key_improvements }}

## 8. 高风险点与替代表达
| 原表达 | 风险 | 建议替代表达 | 原因 |
|---|---|---|---|
{{ better_phrase_rows }}

## 9. 下一步行动
{{ executable_next_actions }}

## 10. 免责声明
本报告仅用于预演复盘、话术建议和风险提示，最终 HR/Legal/业务判断由人工负责。
```

### 12.5 报告验收标准

1. 报告必须提及当前 intent。
2. 报告必须显示主诉求、辅诉求、最终满足度。
3. 报告必须显示 OCEAN 摘要和最终 Persona。
4. 报告必须至少列出 1 个情绪变化节点；无对话时提示“尚无预演对话，无法复盘”。
5. `better_phrases` 不得只给空泛建议，必须有可替换句。
6. `executable_next_actions` 必须是动词开头的行动项，例如“在 24 小时内补充 2 个绩效事实样例”。
7. 退出/改进+退出场景必须提示 HR/Legal 升级边界。

---
