# HRagent-05：OCEAN 大五人格滑块 + 员工诉求 + 动态情绪转换 + 复盘报告可执行需求说明

> 文档类型：可直接交给 AI Coding 工具或工程团队执行的 Markdown 需求与技术实施文档。  
> 目标项目：`HRagent-05`。  
> 适用范围：现有“员工信息 → 沟通意图 → Persona → 谈前指导 → 预演 → 复盘”工作流。  
> 核心约束：不破坏现有 API 和前端流程；新增 OCEAN 与员工诉求能力必须兼容既有 Persona、MVPI 动机满足度、情绪状态机与 Coach Report。

---

## 0. 执行结论

本次需求不是替换现有 Persona，而是在“模拟设定 Persona 步骤”中新增一层 **OCEAN 大五人格滑块输入** 与 **员工主/辅诉求识别**，再由大模型在受控 JSON Schema 下选择或生成更贴合的人格设定，最终把该人格设定作为 `P` 传入动态情绪/回复公式：

```text
输入：H = 对话历史
输入：P = 角色人格/人设，包含 OCEAN + Persona + 主/辅诉求
输入：E_t = 当前情绪状态，包含 VAD + 离散情绪 + 满足度
输出：E_{t+1} = 下一轮合理情绪状态
输出：R = 下一轮员工回复

f(H, P, E_t) -> (E_{t+1}, R)
```

落地后，系统必须支持以下闭环：

```text
员工资料/自由文本
  -> 识别沟通意图 intent
  -> 识别员工主诉求 + 辅诉求 motivation
  -> 用户拖动 5 条 OCEAN 滑块，每条 1~10 档
  -> 大模型根据 OCEAN + intent + motivation 选择/合成人格 P
  -> 每轮 HRBP 话术进入情绪分析器
  -> 更新主/辅诉求满足度
  -> 通过 VAD + Markov 矩阵 + LLM 判断得到 E_{t+1}
  -> Employee Agent 根据 H、P、E_{t+1} 生成员工回复 R
  -> Coach Report 复盘沟通意图匹配、诉求满足、情绪承接、事实沟通、后续计划
```

---

## 1. 本期功能边界

### 1.1 本期必须实现

1. **确定沟通意图**
   - 保留现有 `backend/business_config/intents.yaml` 中的 5 类业务意图。
   - 支持用户手动选择，也支持 `free_text + profile` 的 LLM 识别。
   - 将现有意图标准化为情绪引擎的 `InterviewPurpose`。

2. **确定员工诉求**
   - 新增员工主诉求 `primary_motivation` 与辅诉求 `secondary_motivation`。
   - 诉求枚举使用 MVPI 6 类：`commerce`、`power`、`recognition`、`affiliation`、`security`、`hedonism`。
   - 主诉求权重 70%，辅诉求权重 30%。
   - 支持用户确认/修正。

3. **OCEAN 大五人格滑块**
   - 新增 5 条线：`O`、`C`、`E`、`A`、`N`。
   - 每条线从细到粗表示从低特征到高特征，共 10 档。
   - 用户拖动完成后，前端提交 5 个 1~10 分值和对应特征文案。

4. **大模型选择人格**
   - 后端新增 `OceanPersonaSelector`。
   - 输入：员工资料、沟通意图、主/辅诉求、OCEAN 五维、现有 Persona 列表。
   - 输出：一个最终 `PersonaConfig`，必须优先映射到现有 persona；确需补充时，用 `persona_override` 表达，不新增危险或越界人格。

5. **情绪转换参考图中公式**
   - 扩展现有情绪状态为：满足度 + VAD + 离散情绪。
   - 每轮先更新主/辅诉求满足度，再更新 VAD/离散情绪，再生成员工回复。
   - Markov 基础转移概率由 VAD 距离和相邻约束决定；LLM 对话分析结果只作为加权项，不允许无理由大跳变。

6. **复盘报告增强**
   - 报告必须复盘：沟通意图是否清晰、员工诉求是否被回应、OCEAN 人格是否被正确承接、情绪转换轨迹、情绪承接质量、事实沟通质量、后续发展/改进/退出计划。
   - 报告必须输出结构化 JSON，并在前端渲染为可读报告。

### 1.2 本期不做

1. 不新增数据库迁移作为强依赖。若当前 Session 存储可承载新增字段，优先以 Pydantic state 兼容落地。
2. 不替换现有 `personas.yaml`；OCEAN 只是 Persona 选择和动态 prompt 的上层输入。
3. 不让员工 Agent 引用政策、法律条款或替 HR 下正式结论。
4. 不让大模型自由输出非结构化人格结论；所有 LLM 输出必须走 Pydantic Schema 校验。
5. 不改变 ASR/TTS 的现有安全边界和密钥位置。

---

## 2. 现有项目接入点

当前项目已有以下能力，应复用，不重写：

| 能力 | 当前文件 | 本次处理方式 |
|---|---|---|
| 沟通意图配置 | `backend/business_config/intents.yaml` | 复用，并增加前端/报告解释字段 |
| Persona 配置 | `backend/business_config/personas.yaml` | 复用，OCEAN 选择结果最终映射到此处 |
| Session 状态 | `backend/schemas/state.py` | 增加 `ocean_profile`、`motivation_profile`、`selected_persona_reason` |
| 情绪状态 | `backend/schemas/emotion.py` | 扩展 VAD、emotion_id、emotion_probability、emotion_trace |
| MVPI 满足度 | `backend/schemas/motivation.py`、`backend/services/motivation_scoring_service.py` | 复用公式，增强诉求识别输入 |
| 情绪转换 | `backend/services/attitude_transition_engine.py` | 新增 VAD/Markov 引擎，保持原接口 `compute_next_state` |
| 员工回复 Prompt | `backend/prompts/employee/reply.jinja2` | 注入 OCEAN、主/辅诉求、VAD 情绪 |
| 复盘报告 | `backend/schemas/coach.py`、`backend/prompts/coach/report.jinja2` | 扩展字段，仍返回 `CoachReport` |
| 前端 Persona 步骤 | `frontend/src/pages/steps/PersonaStep.tsx` | 新增 OCEAN 滑块和诉求确认区 |
| 前端类型/API | `frontend/src/types/domain.ts`、`frontend/src/api/client.ts` | 增加请求/响应类型，不破坏旧方法 |

---

## 3. 用户流程改造

### 3.1 原流程

```text
员工信息 -> 沟通意图 -> Persona -> 谈前指导 -> 预演 -> 复盘
```

### 3.2 新流程

```text
员工信息
  -> 沟通意图
  -> 员工诉求确认
  -> OCEAN 五线滑动
  -> 大模型选择人格
  -> 难度确认
  -> 谈前指导
  -> 预演
  -> 复盘报告
```

### 3.3 前端页面归属

本期不新增一级步骤，仍使用 `PersonaStep` 页面承载以下三块：

1. **员工诉求确认区**
   - 展示系统识别出的主诉求/辅诉求。
   - 用户可下拉修正。

2. **OCEAN 五线滑块区**
   - 5 条线，每条 1~10 档。
   - 每条线实时显示当前档位标签和说明。

3. **人格选择结果区**
   - 用户点击“生成员工人格”后，后端返回推荐 Persona。
   - 用户确认后进入谈前指导。

---

## 4. 沟通意图识别规则

### 4.1 支持意图

沿用现有 `intents.yaml`：

| 前端/配置 ID | 中文名 | 情绪引擎 purpose | 说明 |
|---|---|---|---|
| `development` | 发展型反馈 | `motivation` | 认可绩效/潜力，规划成长回报 |
| `improvement` | 改进型反馈 | `improvement` | 指出差距，制定改进计划 |
| `exit` | 退出型沟通 | `exit` | 基于事实和流程进行退出沟通 |
| `development_improvement` | 发展+改进混合反馈 | `motivation_improvement` | 同时保留认可与局部改进 |
| `improvement_exit` | 改进+退出预警反馈 | `improvement_exit` | 最后窗口期，明确后果 |

### 4.2 识别输入

```json
{
  "employee_profile": "EmployeeProfile",
  "free_text": "用户输入的沟通目标描述",
  "selected_intent_id": "用户手动选择，可为空"
}
```

### 4.3 决策优先级

```text
用户手动选择 intent_id
  > LLM 根据 free_text + employee_profile 识别
  > profile.conversation_topic 关键词识别
  > default_intent = improvement
```

### 4.4 验收标准

1. 用户手动选择 `development_improvement` 时，后端不得改成 `development`。
2. `free_text` 包含“最后机会”“不达标就进入退出流程”时，应识别为 `improvement_exit`。
3. `free_text` 包含“晋升发展”“培养路径”“更大职责”且无明显改进压力时，应识别为 `development`。
4. 识别结果必须包含：`intent_id`、`confidence`、`reason`、`config`。

---

## 5. 员工诉求识别规则

### 5.1 MVPI 诉求枚举

| motivation_id | 中文名 | 员工常见表达 | HRBP 应回应的方向 |
|---|---|---|---|
| `commerce` | 薪酬/奖金/收益 | “涨薪呢？”“奖金怎么算？” | 回报机制、边界、下一步资格条件 |
| `power` | 晋升/职权/影响力 | “什么时候能升？”“我能不能带项目？” | 职责范围、成长路径、授权边界 |
| `recognition` | 认可/可见度/公平评价 | “我的贡献有没有被看到？” | 具体认可、事实证据、公平口径 |
| `affiliation` | 团队融洽/归属 | “团队是不是不认可我？” | 团队支持、协作安排、关系修复 |
| `security` | 稳定/安全感 | “会不会影响岗位？”“是不是要优化我？” | 流程稳定性、预期管理、支持计划 |
| `hedonism` | 舒适/工作内容多样性 | “工作太单一/压力太大” | 工作体验、资源协调、节奏安排 |

### 5.2 主/辅诉求结构

```python
class MotivationProfile(BaseModel):
    primary_motivation: MvpiMotivation
    secondary_motivation: MvpiMotivation | None = None
    primary_weight: float = 0.7
    secondary_weight: float = 0.3
    primary_confidence: float = Field(ge=0, le=1)
    secondary_confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    user_confirmed: bool = False
```

### 5.3 总满足度公式

```text
primary_satisfaction_0 = 0
secondary_satisfaction_0 = 0

primary_satisfaction_{t+1} = clip(primary_satisfaction_t + primary_delta_t, 0, 100)
secondary_satisfaction_{t+1} = clip(secondary_satisfaction_t + secondary_delta_t, 0, 100)

total_satisfaction_t = primary_satisfaction_t * 0.7 + secondary_satisfaction_t * 0.3
```

### 5.4 诉求识别 Prompt

新增文件：`backend/prompts/setup/motivation_extract.jinja2`

```jinja2
你是绩效沟通场景中的员工诉求识别器。
只能从以下 motivation_id 中选择：commerce, power, recognition, affiliation, security, hedonism。

输入：
profile={{ profile }}
intent={{ intent }}
conversation_topic={{ conversation_topic }}
free_text={{ free_text }}

请输出 JSON，字段必须为：
{
  "primary_motivation": "...",
  "secondary_motivation": "... or null",
  "primary_confidence": 0-1,
  "secondary_confidence": 0-1,
  "evidence": ["不超过3条证据"],
  "reason": "不超过120字"
}

规则：
1. 主诉求是最可能引发情绪的核心诉求。
2. 辅诉求只能放大或缓和情绪，不得与主诉求相同。
3. 如果证据不足，优先根据 intent 使用默认值，但 confidence 不得超过 0.55。
4. 不得编造员工资料中没有的事实。
```

### 5.5 默认诉求兜底

| purpose | primary_motivation | secondary_motivation |
|---|---|---|
| `motivation` | `power` | `recognition` |
| `improvement` | `recognition` | `security` |
| `exit` | `security` | `recognition` |
| `motivation_improvement` | `power` | `recognition` |
| `improvement_exit` | `security` | `affiliation` |

### 5.6 验收标准

1. 用户选择/修正诉求后，最终 `SessionState.emotion_state.primary_motivation` 与 `secondary_motivation` 必须同步更新。
2. 主/辅诉求相同必须返回 400 或自动将辅诉求置空并提示。
3. 每轮预演后 `emotion_log.signal.primary_delta`、`secondary_delta` 必须有值。
4. 复盘报告必须展示主/辅诉求满足度最终值和变化趋势。

---

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

## 8. 后端改造清单

### 8.1 新增文件

```text
backend/schemas/ocean.py
backend/services/ocean_persona_selector.py
backend/services/motivation_extraction_service.py
backend/services/vad_markov_engine.py
backend/prompts/setup/ocean_persona_select.jinja2
backend/prompts/setup/motivation_extract.jinja2
backend/business_config/ocean_traits.yaml
```

### 8.2 修改文件

```text
backend/schemas/state.py
backend/schemas/emotion.py
backend/schemas/api.py
backend/schemas/coach.py
backend/services/setup_service.py
backend/services/rehearsal_service.py
backend/services/attitude_transition_engine.py
backend/services/dynamic_persona_builder.py
backend/services/motivation_scoring_service.py
backend/api/routes/setup.py
backend/prompts/employee/reply.jinja2
backend/prompts/coach/report.jinja2
frontend/src/types/domain.ts
frontend/src/api/client.ts
frontend/src/pages/steps/PersonaStep.tsx
frontend/src/styles/global.css
frontend/src/pages/steps/ReportStep.tsx
```

### 8.3 `state.py` 增量字段

```python
from backend.schemas.ocean import OceanProfile, OceanPersonaSelection
from backend.schemas.motivation import MvpiMotivation

class MotivationProfile(BaseModel):
    primary_motivation: MvpiMotivation
    secondary_motivation: MvpiMotivation | None = None
    primary_weight: float = 0.7
    secondary_weight: float = 0.3
    primary_confidence: float = 0.0
    secondary_confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    user_confirmed: bool = False

class SessionState(BaseModel):
    # existing fields remain
    ocean_profile: OceanProfile | None = None
    motivation_profile: MotivationProfile | None = None
    ocean_persona_selection: OceanPersonaSelection | None = None
```

### 8.4 `api.py` 增量请求

```python
class ConfirmMotivationRequest(BaseModel):
    primary_motivation: str
    secondary_motivation: str | None = None
    user_confirmed: bool = True

class ConfirmOceanRequest(BaseModel):
    ocean_profile: OceanProfile
    auto_select_persona: bool = True
    difficulty_id: str = "medium"
    run_mode: str = "guidance_then_rehearsal"
```

### 8.5 `setup.py` 新增路由

```python
@router.post("/{session_id}/motivation/infer", response_model=SessionState)
async def infer_motivation(session_id: str, service: SetupService = Depends(get_setup_service)):
    return await service.infer_motivation(session_id)

@router.patch("/{session_id}/motivation", response_model=SessionState)
def confirm_motivation(session_id: str, payload: ConfirmMotivationRequest, service: SetupService = Depends(get_setup_service)):
    return service.confirm_motivation(session_id, payload)

@router.patch("/{session_id}/ocean", response_model=SessionState)
async def confirm_ocean(session_id: str, payload: ConfirmOceanRequest, service: SetupService = Depends(get_setup_service)):
    return await service.confirm_ocean(session_id, payload)
```

### 8.6 `SetupService` 新增行为

```python
async def infer_motivation(self, session_id: str) -> SessionState:
    state = self.session_service.get_session(session_id)
    state.motivation_profile = await MotivationExtractionService().infer(state)
    self._sync_emotion_motivation(state)
    return self.session_service.save_session(state)

def confirm_motivation(self, session_id: str, payload: ConfirmMotivationRequest) -> SessionState:
    state = self.session_service.get_session(session_id)
    state.motivation_profile = MotivationProfile(
        primary_motivation=payload.primary_motivation,
        secondary_motivation=payload.secondary_motivation,
        user_confirmed=payload.user_confirmed,
    )
    self._sync_emotion_motivation(state)
    return self.session_service.save_session(state)

async def confirm_ocean(self, session_id: str, payload: ConfirmOceanRequest) -> SessionState:
    state = self.session_service.get_session(session_id)
    state.ocean_profile = payload.ocean_profile
    if payload.auto_select_persona:
        selection = await OceanPersonaSelector().select(state)
        state.ocean_persona_selection = selection
        state.persona = self.loader.personas()[selection.selected_persona_id]
        state.rehearsal_context.persona_override = selection.persona_override
    state.difficulty = self.loader.difficulties()[payload.difficulty_id]
    state.run_mode = payload.run_mode
    self._sync_emotion_motivation(state)
    return self.session_service.save_session(state)
```

### 8.7 `complete_setup` 校验

`complete_setup` 必须新增校验：

```text
必须存在 employee_profile
必须存在 intent
必须存在 motivation_profile
必须存在 ocean_profile
必须存在 persona
必须存在 difficulty
```

兼容规则：

```text
如果旧流程只调用 confirmPersona：
  自动生成 default ocean_profile = 五维均 5
  自动调用 infer_motivation 兜底
  保证旧前端/旧测试不失败
```

---

## 9. Employee Agent Prompt 改造

### 9.1 Prompt 注入变量

在 `EmployeeAgent._build_reply_prompt` 中新增：

```python
motivation_profile=state.motivation_profile.model_dump(mode="json") if state.motivation_profile else {},
ocean_profile=state.ocean_profile.model_dump(mode="json") if state.ocean_profile else {},
ocean_persona_selection=state.ocean_persona_selection.model_dump(mode="json") if state.ocean_persona_selection else {},
emotion_state=state.emotion_state.model_dump(mode="json"),
```

### 9.2 `employee/reply.jinja2` 新增段落

```jinja2
员工大五人格 OCEAN：
{% if ocean_profile %}
* 开放性 O：{{ ocean_profile.openness.score }}/10，{{ ocean_profile.openness.label }}，{{ ocean_profile.openness.description }}
* 尽责性 C：{{ ocean_profile.conscientiousness.score }}/10，{{ ocean_profile.conscientiousness.label }}，{{ ocean_profile.conscientiousness.description }}
* 外向性 E：{{ ocean_profile.extraversion.score }}/10，{{ ocean_profile.extraversion.label }}，{{ ocean_profile.extraversion.description }}
* 宜人性 A：{{ ocean_profile.agreeableness.score }}/10，{{ ocean_profile.agreeableness.label }}，{{ ocean_profile.agreeableness.description }}
* 情绪敏感 N：{{ ocean_profile.neuroticism.score }}/10，{{ ocean_profile.neuroticism.label }}，{{ ocean_profile.neuroticism.description }}
{% else %}
未设置，按当前 Persona 默认表现。
{% endif %}

员工主/辅诉求：
{% if motivation_profile %}
* 主诉求：{{ motivation_profile.primary_motivation }}，权重 70%。
* 辅诉求：{{ motivation_profile.secondary_motivation or '无' }}，权重 30%。
{% endif %}

当前情绪状态：
* 离散情绪：{{ emotion_state.emotion_id or emotion_state.current_attitude }}
* VAD：{{ emotion_state.vad if emotion_state.vad else '未设置' }}
* 总满足度：{{ emotion_state.total_satisfaction }}
* 情绪说明：{{ emotion_state.emotion_description }}

回复约束：
1. 员工最先回应主诉求是否被看见。
2. 语气必须符合 OCEAN；例如 N 高不能突然完全冷静，C 高必须关心证据和标准，A 低可以更直接挑战但不得攻击个人。
3. 回复仍然只输出员工会直接说出口的话，不输出 Markdown。
```

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

## 15. 配置项

在 `.env.example` 中新增：

```bash
# OCEAN persona selection
OCEAN_PERSONA_SELECTOR_ENABLED=true
OCEAN_PERSONA_SELECTOR_MODEL=
OCEAN_PERSONA_SELECTOR_TIMEOUT_SECONDS=8

# VAD Markov emotion engine
VAD_MARKOV_ENGINE_ENABLED=true
EMOTION_SELECTION_STRATEGY=maximum_probability
VAD_MARKOV_LAMBDA=2.2
VAD_MARKOV_ALPHA_SIGNAL=1.25
VAD_MARKOV_BETA_OCEAN=0.85
VAD_MARKOV_GAMMA_MOTIVATION=0.70
VAD_MARKOV_DELTA_SATISFACTION=0.90

# Motivation extraction
MOTIVATION_EXTRACTOR_ENABLED=true
MOTIVATION_EXTRACTOR_TIMEOUT_SECONDS=8
```

读取位置：`backend/config/settings.py`。

要求：

```text
1. 默认启用 OCEAN 和 VAD Markov。
2. 若模型调用失败，回退到规则人格选择和现有 EmotionStateService。
3. 缓存失败不得阻断业务。
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
