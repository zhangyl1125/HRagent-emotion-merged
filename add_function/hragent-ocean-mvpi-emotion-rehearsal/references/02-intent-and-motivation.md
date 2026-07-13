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
