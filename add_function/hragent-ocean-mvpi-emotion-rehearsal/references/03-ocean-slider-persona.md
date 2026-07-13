## 6. OCEAN 大五人格五条线设计

### 6.1 UI 交互定义

在 `PersonaStep.tsx` 中新增组件 `OceanSliderPanel`。

每条线：

```text
左端：细线，分值 1，低特征
右端：粗线，分值 10，高特征
滑块范围：1~10，整数步进
显示内容：维度名 + 当前档位标签 + 当前档位解释
```

视觉要求：

```css
线宽 = 2px + score * 0.8px
滑块圆点大小 = 14px + score * 0.6px
当前标签必须跟随 score 更新
```

### 6.2 五条线的 10 档特征

#### O：Openness 开放性，从细到粗

| 分值 | 标签 | 员工表现 |
|---:|---|---|
| 1 | 保守务实 | 偏好既有做法，不主动尝试新路径 |
| 2 | 经验导向 | 更信过往经验，对新方案保持距离 |
| 3 | 规则偏好 | 希望先明确边界和标准再行动 |
| 4 | 谨慎尝试 | 可接受小范围试点，但需要安全感 |
| 5 | 中性开放 | 对新想法不排斥，也不主动推动 |
| 6 | 愿意尝试 | 在有支持时愿意试新方法 |
| 7 | 好奇探索 | 会追问可能性和替代方案 |
| 8 | 创新整合 | 能将反馈转化为改进假设 |
| 9 | 抽象愿景 | 关注长期方向、模式和系统性机会 |
| 10 | 高度创造 | 强烈希望突破现状，抗拒重复事务 |

#### C：Conscientiousness 尽责性，从细到粗

| 分值 | 标签 | 员工表现 |
|---:|---|---|
| 1 | 随性松散 | 计划性弱，容易忽略承诺细节 |
| 2 | 容易拖延 | 接受目标但行动启动慢 |
| 3 | 需被提醒 | 需要经理给明确检查点 |
| 4 | 节奏不稳 | 有责任心但执行波动较大 |
| 5 | 基本负责 | 能完成明确任务，但需标准清晰 |
| 6 | 有计划 | 会要求优先级、节点和资源 |
| 7 | 自律推进 | 能主动拆解行动计划 |
| 8 | 高标准 | 对评价标准和结果质量敏感 |
| 9 | 强执行 | 重视承诺、复盘和交付闭环 |
| 10 | 完美控制 | 对模糊反馈强烈不适，容易追问细节 |

#### E：Extraversion 外向性，从细到粗

| 分值 | 标签 | 员工表现 |
|---:|---|---|
| 1 | 安静内收 | 压力下话很少，偏沉默 |
| 2 | 保留表达 | 只回答必要内容，不主动展开 |
| 3 | 少量回应 | 会表达顾虑，但句子短 |
| 4 | 被动互动 | 需要经理引导才继续说 |
| 5 | 适度社交 | 能正常交流，不强势表达 |
| 6 | 主动沟通 | 会主动澄清事实和期待 |
| 7 | 热情表达 | 表达较多，情绪外显 |
| 8 | 影响他人 | 会争取资源和支持者 |
| 9 | 高能推动 | 反应快，可能连续追问或辩论 |
| 10 | 外向主导 | 容易主导谈话节奏，强表达诉求 |

#### A：Agreeableness 宜人性，从细到粗

| 分值 | 标签 | 员工表现 |
|---:|---|---|
| 1 | 竞争强硬 | 倾向保护自身利益，直接挑战结论 |
| 2 | 怀疑防备 | 先质疑动机和公平性 |
| 3 | 讲条件 | 接受行动前会谈交换条件 |
| 4 | 克制反驳 | 不轻易接受，但保持礼貌 |
| 5 | 礼貌中立 | 可沟通，但不会快速让步 |
| 6 | 愿意合作 | 对合理事实和支持会缓和 |
| 7 | 体谅他人 | 能理解经理部分难处 |
| 8 | 信任支持 | 倾向相信善意并共同解决 |
| 9 | 高度配合 | 容易接受反馈并跟进计划 |
| 10 | 过度迁就 | 可能压抑真实诉求，只口头答应 |

#### N：Neuroticism 神经质/情绪敏感性，从细到粗

| 分值 | 标签 | 员工表现 |
|---:|---|---|
| 1 | 冷静稳定 | 负面信息下仍能保持理性 |
| 2 | 低波动 | 有顾虑但不明显外显 |
| 3 | 理性克制 | 先问事实，不先表达情绪 |
| 4 | 偶有担忧 | 对后果有轻度担心 |
| 5 | 轻度敏感 | 会关注评价和关系影响 |
| 6 | 容易紧张 | 对负面反馈反应较快 |
| 7 | 反复担心 | 需要多次确认安全和认可 |
| 8 | 防御波动 | 容易在委屈、防御、追问间切换 |
| 9 | 焦虑放大 | 对 PIP/退出/机会受损高度敏感 |
| 10 | 高敏爆发 | 可能强烈对抗或明显退缩，但仍保持职场边界 |

### 6.3 前端提交结构

```ts
export interface OceanDimensionValue {
  score: number;            // 1..10
  normalized: number;       // score / 10
  label: string;
  description: string;
}

export interface OceanProfile {
  openness: OceanDimensionValue;
  conscientiousness: OceanDimensionValue;
  extraversion: OceanDimensionValue;
  agreeableness: OceanDimensionValue;
  neuroticism: OceanDimensionValue;
  source: 'manual_slider';
  completed: boolean;
}
```

### 6.4 后端 Schema

新增文件：`backend/schemas/ocean.py`

```python
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator

OceanDimension = Literal[
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
]

class OceanDimensionValue(BaseModel):
    score: int = Field(ge=1, le=10)
    normalized: float = Field(ge=0.1, le=1.0)
    label: str
    description: str

class OceanProfile(BaseModel):
    openness: OceanDimensionValue
    conscientiousness: OceanDimensionValue
    extraversion: OceanDimensionValue
    agreeableness: OceanDimensionValue
    neuroticism: OceanDimensionValue
    source: Literal["manual_slider", "default", "imported"] = "manual_slider"
    completed: bool = True

    @model_validator(mode="after")
    def sync_normalized(self):
        for name in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
            item = getattr(self, name)
            item.normalized = round(item.score / 10, 2)
        return self

class OceanPersonaSelection(BaseModel):
    selected_persona_id: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    ocean_summary: str
    persona_override: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
```

### 6.5 人格选择策略

执行顺序：

```text
1. 读取 OCEAN 五维分值。
2. 根据规则生成候选 persona 列表。
3. 把候选 persona、intent、motivation、employee_profile 交给 LLM 选择。
4. 校验 selected_persona_id 必须存在于 personas.yaml。
5. 如果 LLM 输出不存在的 persona_id，回退到规则最高分候选。
6. 将 persona_override 写入 rehearsal_context，用于补充 OCEAN 特征。
```

### 6.6 规则候选映射

| 条件 | 优先候选 |
|---|---|
| `N>=7` 且 `A<=4` | `defensive_rebuttal` |
| `N>=7` 且 `E<=3` | `silent_avoidant` |
| `N>=7` 且 `A>=6` | `emotionally_hurt` |
| `C>=8` 且 `O<=5` | `data_logic_challenger` |
| `E>=7` 且 `A<=4` | `outcome_negotiator` |
| `A<=3` 且主诉求为 `commerce/power` | `outcome_negotiator` |
| `A>=8` 且 `C<=5` | `support_dependent` |
| `C<=4` 且 `A>=5` | `overpromising` |
| `O<=4` 且 `N>=6` | `external_attribution` |
| 无明显极端 | 按 intent 默认 persona 或 `data_logic_challenger` |

### 6.7 LLM 人格选择 Prompt

新增文件：`backend/prompts/setup/ocean_persona_select.jinja2`

```jinja2
你是 HRagent 员工 Persona 选择器。你只能从候选 personas 中选择一个 selected_persona_id。
不得创造不存在的人设 ID；如需要补充细节，只能写 persona_override。

输入：
employee_profile={{ employee_profile }}
intent={{ intent }}
motivation_profile={{ motivation_profile }}
ocean_profile={{ ocean_profile }}
candidate_personas={{ candidate_personas }}
all_personas={{ all_personas }}

输出 JSON：
{
  "selected_persona_id": "必须属于 all_personas 的 id",
  "confidence": 0-1,
  "reason": "说明 OCEAN + 诉求 + intent 为什么适合该 persona，不超过160字",
  "ocean_summary": "将五维特征压缩为一句员工沟通风格，不超过120字",
  "persona_override": "用于 employee prompt 的人格补充，不超过200字，不能突破安全边界",
  "risk_notes": ["可为空，不超过3条"]
}

选择规则：
1. N 高表示情绪敏感或防御/退缩风险高。
2. C 高表示更关注证据、标准、计划和承诺闭环。
3. E 高表示更可能外显表达、追问、谈判；E 低更可能沉默或短句。
4. A 低表示更挑战、更讲条件；A 高表示更合作但可能压抑诉求。
5. O 高表示更接受探索和发展路径；O 低更偏安全、规则和确定性。
6. 主诉求必须影响 persona_override 的关注点。
7. 不得输出心理诊断、人格障碍、病理化描述。
```

---
