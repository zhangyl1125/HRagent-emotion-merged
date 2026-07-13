# HRagent 人格化员工对话最终落地方案

> 适用场景：HRBP 在绩效反馈、困难沟通、员工辅导场景中进行对话预演。系统通过“语音转文字 + 员工人格模型 + 情绪状态机 + 动态 Prompt”让 AI 员工在对话过程中表现得更像真实员工。

---

## 1. 最终结论

当前阶段最适合落地的方案不是直接做“实时语音通话”，而是：

```text
HRBP 语音输入
  ↓
语音转文字 ASR
  ↓
HRBP 确认文本并发送
  ↓
话术质量分析 Conversation Analyzer
  ↓
员工人格模型 Persona Profile
  ↓
员工情绪/态度状态机 Emotion State Machine
  ↓
动态员工 Prompt Dynamic Persona Prompt
  ↓
员工 Agent 生成更像真实员工的回复
  ↓
前端展示员工回复、当前情绪、态度变化、复盘建议
```

这套方案可以让 AI 员工表现出：

```text
1. 有稳定人格，不是每轮随机反应。
2. 会根据 HRBP 的说法产生情绪变化。
3. 会从防御、犹豫、沉默逐渐转向反思、合作。
4. 会根据不同员工画像产生不同回答。
5. 会在复盘报告中解释“为什么员工态度发生变化”。
```

---

## 2. 本期功能边界

### 2.1 本期要做

```text
1. HRBP 语音转文字。
2. HRBP 确认文本后发送。
3. 系统分析 HRBP 话术质量。
4. 员工 Agent 根据人格和情绪状态生成回复。
5. 员工态度随对话过程动态变化。
6. 页面显示当前员工状态、情绪强度、变化原因。
7. Report 中输出情绪转折点和沟通建议。
```

### 2.2 本期不做

```text
1. 不做实时语音通话。
2. 不做 AI 实时打断。
3. 不强依赖实时 TTS。
4. 不本地部署大语音模型。
5. 不拉取 qwen3-asr-flash-realtime Docker 镜像。
```

### 2.3 可选快速增强

如果需要快速实现“员工语音输出”，可以在前端使用浏览器 Web Speech API 朗读员工回复：

```text
员工 Agent 文字回复
  ↓
前端按句子切分
  ↓
SpeechSynthesisUtterance 朗读
  ↓
根据员工情绪调整 rate / pitch / volume
```

这是前端增强，不影响主流程。

---

## 3. 产品目标

### 3.1 用户视角效果

HRBP 使用系统时，应感受到：

```text
我说得太直接，员工会变得防御。
我只给结论没有证据，员工会质疑或沉默。
我先共情再给事实，员工会逐渐愿意沟通。
我给出支持方案，员工会从抵触转为合作。
不同员工画像的反应方式不一样。
```

### 3.2 产品经理可验收效果

页面上可以看到：

```text
当前员工状态：防御抵触
情绪强度：58/100
信任程度：35/100
沟通开放度：42/100
变化原因：HRBP 反馈较直接，缺少具体事实和共情
实时建议：先确认员工压力，再给出具体案例
```

复盘报告中可以看到：

```text
第 3 轮，员工从“防御抵触”转为“开始反思”。
触发原因：HRBP 先确认了员工压力，并使用具体交付案例进行反馈。
建议：继续保持“共情 + 事实 + 支持方案”的沟通结构。
```

---

## 4. 总体技术架构

```text
┌─────────────────────────────────────────────┐
│                 Frontend React              │
│                                             │
│ RehearsalStep 页面                           │
│ - 语音录制按钮                               │
│ - ASR 转写文本输入框                         │
│ - 对话窗口                                   │
│ - EmotionBadge 当前员工状态                  │
│ - EmotionTimeline 情绪变化轨迹               │
│ - 可选：Web Speech API 朗读员工回复           │
└──────────────────────┬──────────────────────┘
                       │ HTTP / SSE
                       ▼
┌─────────────────────────────────────────────┐
│                Backend FastAPI               │
│                                             │
│ - ASR Route                                  │
│ - Rehearsal Message Stream Route             │
│ - Conversation Analyzer                      │
│ - Persona Profile Service                    │
│ - Emotion State Machine                      │
│ - Dynamic Prompt Builder                     │
│ - Report Generator                           │
└──────────────────────┬──────────────────────┘
                       │
        ┌──────────────┼──────────────────┐
        ▼              ▼                  ▼
┌─────────────┐ ┌────────────────┐ ┌────────────────┐
│ Qwen ASR     │ │ Bosch LLM API   │ │ PostgreSQL      │
│ qwen3-asr    │ │ chat/completion │ │ Session/Report   │
│ flash        │ │ Employee Agent  │ │ Emotion History  │
└─────────────┘ └────────────────┘ └────────────────┘
                       │
                       ▼
                  ┌─────────┐
                  │ Redis   │
                  │ Session │
                  │ Cache   │
                  └─────────┘
```

---

## 5. 技术栈清单

### 5.1 前端技术栈

| 技术 | 用途 |
|---|---|
| React | 页面和组件开发 |
| TypeScript | 类型约束 |
| Vite | 前端构建 |
| MediaRecorder | 录制 HRBP 语音 |
| FormData / Blob | 上传音频文件给后端 ASR |
| SSE / Fetch Streaming | 接收员工 Agent 流式回复 |
| Web Speech API，可选 | 快速实现员工语音输出 |
| CSS Modules / global.css | Bosch 风格 UI 样式 |

前端新增重点组件：

```text
frontend/src/components/rehearsal/EmotionBadge.tsx
frontend/src/components/rehearsal/EmotionTimeline.tsx
frontend/src/components/rehearsal/CoachHintCard.tsx
frontend/src/hooks/useSpeechToText.ts
frontend/src/hooks/useEmotionState.ts
frontend/src/hooks/useSpeechOutput.ts   # 可选
```

### 5.2 后端技术栈

| 技术 | 用途 |
|---|---|
| FastAPI | 后端 API |
| Pydantic | Persona、Emotion、Analyzer 结构化数据 |
| httpx | 调用 Bosch LLM API / ASR API |
| PostgreSQL | 保存会话、员工画像、情绪轨迹、报告 |
| Redis | 保存会话实时状态缓存 |
| SSE | 流式返回员工回复 |
| Docker Compose | 部署 backend/frontend/postgres/redis |

后端新增模块：

```text
backend/schemas/persona.py
backend/schemas/emotion.py
backend/schemas/conversation_analysis.py
backend/services/persona_profile_service.py
backend/services/conversation_analyzer.py
backend/services/emotion_state_machine.py
backend/services/dynamic_prompt_builder.py
backend/services/asr_service.py
backend/services/report_emotion_summary.py
```

### 5.3 模型与 API

| 模块 | 推荐 |
|---|---|
| ASR 语音转文字 | `qwen3-asr-flash` |
| 后续实时 ASR 预留 | `qwen3-asr-flash-realtime` |
| 员工 Agent / 分析模型 | Bosch Chat Completions API |
| URL | `https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions` |
| TTS 快速方案，可选 | 浏览器 Web Speech API |
| TTS 企业版，可选 | CosyVoice / Bosch TTS 网关，等后续接口开放 |

---

## 6. 核心设计一：员工人格模型 Persona Profile

### 6.1 设计原则

员工不能只靠一句 Prompt 扮演。需要把员工画像结构化保存：

```text
稳定人格：员工长期不变的行为倾向
动态状态：对话过程中会变化的情绪和态度
```

### 6.2 Persona 结构

新增文件：

```text
backend/schemas/persona.py
```

建议结构：

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import List


class PersonaType(str, Enum):
    EMOTIONALLY_FRUSTRATED = "emotionally_frustrated"      # 情绪受挫型
    DEFENSIVE_EXPLAINER = "defensive_explainer"            # 防御解释型
    SILENT_WITHDRAWN = "silent_withdrawn"                  # 沉默退缩型
    HIGH_ACHIEVER_PRESSURED = "high_achiever_pressured"    # 高成就压力型
    FAIRNESS_SENSITIVE = "fairness_sensitive"              # 公平敏感型


class EmployeePersona(BaseModel):
    employee_id: str
    employee_name: str
    persona_type: PersonaType
    communication_style: str
    core_motivation: str
    fear_or_concern: str
    trigger_points: List[str]
    softening_conditions: List[str]
    default_attitude: str = "guarded_hesitant"
    sensitivity: int = Field(ge=0, le=100)
    defensiveness: int = Field(ge=0, le=100)
    openness: int = Field(ge=0, le=100)
    need_for_recognition: int = Field(ge=0, le=100)
```

### 6.3 示例员工画像

```json
{
  "employee_id": "E001",
  "employee_name": "JI Yingzi",
  "persona_type": "emotionally_frustrated",
  "communication_style": "表达谨慎，但对负面评价敏感，需要先被理解",
  "core_motivation": "希望自己的努力被看见",
  "fear_or_concern": "担心绩效评价忽略了实际困难和额外付出",
  "trigger_points": [
    "HRBP 直接说表现不好",
    "HRBP 没有给具体例子",
    "HRBP 否定努力过程",
    "HRBP 使用命令式语气"
  ],
  "softening_conditions": [
    "HRBP 先承认压力和努力",
    "HRBP 给出具体事实",
    "HRBP 说明评价依据",
    "HRBP 提出支持方案"
  ],
  "default_attitude": "guarded_hesitant",
  "sensitivity": 75,
  "defensiveness": 65,
  "openness": 45,
  "need_for_recognition": 80
}
```

---

## 7. 核心设计二：HRBP 话术分析 Conversation Analyzer

### 7.1 分析目标

每次 HRBP 发送文本后，系统先分析这句话对员工可能产生的影响。

分析维度：

| 字段 | 含义 |
|---|---|
| `empathy` | 是否表达共情 |
| `specificity` | 是否给出具体事实 |
| `respectfulness` | 是否尊重员工 |
| `pressure` | 是否带有压迫感 |
| `clarity` | 反馈是否清晰 |
| `support_plan` | 是否提供支持方案 |
| `recognition` | 是否认可员工努力 |
| `blame_level` | 是否归责过重 |
| `open_question` | 是否使用开放式问题 |

### 7.2 输出结构

新增文件：

```text
backend/schemas/conversation_analysis.py
```

```python
from pydantic import BaseModel, Field
from typing import List, Literal


class ConversationSignal(BaseModel):
    empathy: float = Field(ge=0, le=1)
    specificity: float = Field(ge=0, le=1)
    respectfulness: float = Field(ge=0, le=1)
    pressure: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    support_plan: float = Field(ge=0, le=1)
    recognition: float = Field(ge=0, le=1)
    blame_level: float = Field(ge=0, le=1)
    open_question: float = Field(ge=0, le=1)
    likely_employee_reaction: Literal[
        "escalate",
        "soften",
        "withdraw",
        "cooperate",
        "stay"
    ]
    risk_flags: List[str] = []
    short_reason: str
    coach_hint: str
```

### 7.3 Analyzer Prompt

```text
你是 HR 绩效反馈训练系统中的对话质量分析器。
你的任务不是生成员工回复，而是分析 HRBP 最新这句话会如何影响员工情绪和态度。

请只输出 JSON，不要输出解释。

分析维度：
- empathy：是否表达理解和共情
- specificity：是否给出具体事实、案例、行为
- respectfulness：是否尊重员工
- pressure：是否带有压迫、命令、强否定
- clarity：反馈是否清晰
- support_plan：是否提供下一步支持
- recognition：是否认可员工努力
- blame_level：是否过度归责
- open_question：是否使用开放式问题引导员工表达

员工基础画像：
{employee_persona}

当前员工状态：
{current_emotion_state}

最近对话历史：
{conversation_history}

HRBP 最新输入：
{hrbp_text}

请输出：
{
  "empathy": 0.0,
  "specificity": 0.0,
  "respectfulness": 0.0,
  "pressure": 0.0,
  "clarity": 0.0,
  "support_plan": 0.0,
  "recognition": 0.0,
  "blame_level": 0.0,
  "open_question": 0.0,
  "likely_employee_reaction": "escalate|soften|withdraw|cooperate|stay",
  "risk_flags": [],
  "short_reason": "一句话解释原因",
  "coach_hint": "给 HRBP 的一句改进建议"
}
```

---

## 8. 核心设计三：员工情绪/态度状态机

### 8.1 状态枚举

新增文件：

```text
backend/schemas/emotion.py
```

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


class EmployeeAttitude(str, Enum):
    CALM_NEUTRAL = "calm_neutral"                         # 平静中立
    GUARDED_HESITANT = "guarded_hesitant"                 # 谨慎犹豫
    DEFENSIVE_RESISTANT = "defensive_resistant"           # 防御抵触
    FRUSTRATED_PUSHBACK = "frustrated_pushback"           # 受挫反驳
    SILENT_WITHDRAWN = "silent_withdrawn"                 # 沉默退缩
    REFLECTIVE_SOFTENING = "reflective_softening"         # 开始反思
    COOPERATIVE_CONSTRUCTIVE = "cooperative_constructive" # 合作建设性


class EmotionState(BaseModel):
    session_id: str
    current_attitude: EmployeeAttitude
    previous_attitude: Optional[EmployeeAttitude] = None
    intensity: int = Field(ge=0, le=100)
    trust_level: int = Field(ge=0, le=100)
    pressure_level: int = Field(ge=0, le=100)
    engagement_level: int = Field(ge=0, le=100)
    transition_reason: Optional[str] = None
    coach_hint: Optional[str] = None
    turn_index: int = 0
```

### 8.2 状态说明

| 状态 | 中文含义 | 员工表现 |
|---|---|---|
| `calm_neutral` | 平静中立 | 正常沟通，没有明显抵触 |
| `guarded_hesitant` | 谨慎犹豫 | 回答保留，试探 HRBP 意图 |
| `defensive_resistant` | 防御抵触 | 解释困难，质疑评价是否片面 |
| `frustrated_pushback` | 受挫反驳 | 表达不满，但保持职场边界 |
| `silent_withdrawn` | 沉默退缩 | 句子短，回避表达，需要引导 |
| `reflective_softening` | 开始反思 | 愿意听具体反馈，部分承认问题 |
| `cooperative_constructive` | 合作建设性 | 主动讨论改进方案 |

### 8.3 状态转换规则

```text
calm_neutral
  ├─ 高压力 + 低共情 → defensive_resistant
  ├─ 模糊负面反馈 → guarded_hesitant
  └─ 共情 + 具体事实 → cooperative_constructive

guarded_hesitant
  ├─ 持续施压 → defensive_resistant
  ├─ 忽视情绪 → silent_withdrawn
  └─ 共情 + 具体事实 → reflective_softening

defensive_resistant
  ├─ 继续否定/压迫 → frustrated_pushback
  ├─ 只追问不支持 → guarded_hesitant
  └─ 共情 + 事实 + 支持 → reflective_softening

frustrated_pushback
  ├─ 继续施压 → 保持 frustrated_pushback，不能升级为攻击
  ├─ HRBP 承认困难 → defensive_resistant
  └─ HRBP 给支持方案 → reflective_softening

silent_withdrawn
  ├─ 继续追问/施压 → 保持沉默退缩
  └─ 开放式问题 + 降低压力 → guarded_hesitant / reflective_softening

reflective_softening
  ├─ 支持方案明确 → cooperative_constructive
  ├─ 再次否定 → defensive_resistant
  └─ 空泛鼓励 → guarded_hesitant

cooperative_constructive
  ├─ 持续支持 → 保持 cooperative_constructive
  └─ 突然强压 → guarded_hesitant / defensive_resistant
```

### 8.4 规则代码示例

```python
def compute_next_state(current: EmotionState, signal: ConversationSignal) -> EmotionState:
    next_state = current.model_copy(deep=True)
    next_state.previous_attitude = current.current_attitude
    next_state.turn_index = current.turn_index + 1

    # 压力和归责增加
    if signal.pressure > 0.7 or signal.blame_level > 0.7:
        next_state.pressure_level = min(100, current.pressure_level + 15)
    else:
        next_state.pressure_level = max(0, current.pressure_level - 5)

    # 共情、事实、支持会提升信任
    if signal.empathy > 0.6 and signal.specificity > 0.5:
        next_state.trust_level = min(100, current.trust_level + 15)
    if signal.support_plan > 0.6:
        next_state.engagement_level = min(100, current.engagement_level + 20)

    # 高压低共情：升级防御
    if signal.pressure > 0.7 and signal.empathy < 0.3:
        next_state.current_attitude = escalate(current.current_attitude)
        next_state.intensity = min(75, current.intensity + 15)
        next_state.transition_reason = "HRBP 表达压力较高，且缺少共情确认"

    # 共情 + 具体事实：软化
    elif signal.empathy > 0.6 and signal.specificity > 0.5:
        next_state.current_attitude = soften(current.current_attitude)
        next_state.intensity = max(20, current.intensity - 10)
        next_state.transition_reason = "HRBP 先确认员工感受，并给出了具体事实"

    # 支持方案：转向合作
    elif signal.support_plan > 0.6:
        next_state.current_attitude = cooperate(current.current_attitude)
        next_state.intensity = max(15, current.intensity - 15)
        next_state.transition_reason = "HRBP 提供了明确支持方案"

    # 模糊反馈：进入谨慎或沉默
    elif signal.specificity < 0.3 and signal.clarity < 0.4:
        next_state.current_attitude = guarded_or_withdraw(current.current_attitude)
        next_state.transition_reason = "HRBP 反馈较模糊，员工难以理解评价依据"

    else:
        next_state.transition_reason = "当前话术未明显改变员工态度"

    next_state.coach_hint = signal.coach_hint
    return anti_jump_guard(current, next_state)
```

---

## 9. 核心设计四：动态员工 Prompt

### 9.1 Prompt 组成

员工 Agent 每轮生成回复前，Prompt 应由 4 部分组成：

```text
1. 固定系统边界：企业绩效反馈场景、安全边界
2. 员工基础人格：Persona Profile
3. 当前情绪状态：Emotion State
4. 当前回复策略：本轮应该如何回应 HRBP
```

### 9.2 Prompt Builder 输出示例

新增文件：

```text
backend/services/dynamic_prompt_builder.py
```

示例：

```text
你正在扮演一名员工，参加 HRBP 的绩效反馈沟通预演。
你不是助手，不要解释系统规则。你要像真实员工一样自然回应。

[员工基础人格]
员工姓名：JI Yingzi
人格类型：情绪受挫型
沟通风格：表达谨慎，但对负面评价敏感，需要先被理解。
核心动机：希望自己的努力被看见。
主要担忧：担心绩效评价忽略实际困难和额外付出。
触发点：HRBP 直接否定表现、不给具体例子、忽略努力过程。
软化条件：HRBP 表达理解、给出具体事实、说明支持方案。

[当前员工状态]
当前态度：defensive_resistant
情绪强度：58/100
信任程度：35/100
压力程度：70/100
沟通开放度：42/100
状态变化原因：HRBP 反馈较直接，缺少具体事实和共情。

[本轮回复策略]
- 你应表现出防御和抵触。
- 你可以解释自己的困难。
- 你可以质疑评价是否足够具体。
- 你仍然处在职场沟通中，不能辱骂、人身攻击、歧视或威胁。
- 回复控制在 1-3 句话。
- 语气要自然，避免像客服模板。

[HRBP 最新输入]
{hrbp_text}
```

### 9.3 不同状态的回复策略

| 状态 | Prompt 策略 |
|---|---|
| `guarded_hesitant` | 短句、试探、有保留 |
| `defensive_resistant` | 解释困难，质疑评价依据 |
| `frustrated_pushback` | 表达不满，但不能攻击 |
| `silent_withdrawn` | 回答少，回避深入，需要 HRBP 引导 |
| `reflective_softening` | 开始理解，愿意听具体反馈 |
| `cooperative_constructive` | 主动讨论下一步改进 |

---

## 10. 前端实现方案

### 10.1 页面改动

当前页面：

```text
frontend/src/pages/steps/RehearsalStep.tsx
```

需要增加：

```text
1. 语音输入按钮：录音 → 上传 → 转文字 → 填入输入框
2. EmotionBadge：显示当前员工态度
3. EmotionTimeline：显示状态变化轨迹
4. CoachHintCard：显示当前 HRBP 话术建议
5. 可选 Auto Speak：员工回复自动朗读
```

### 10.2 EmotionBadge 示例

```tsx
type EmotionState = {
  current_attitude: string;
  intensity: number;
  trust_level: number;
  pressure_level: number;
  engagement_level: number;
  transition_reason?: string;
  coach_hint?: string;
};

export function EmotionBadge({ state }: { state: EmotionState }) {
  return (
    <div className="emotion-card">
      <div className="emotion-title">员工状态</div>
      <div className="emotion-main">{mapAttitudeLabel(state.current_attitude)}</div>
      <div className="emotion-row">情绪强度：{state.intensity}/100</div>
      <div className="emotion-row">信任程度：{state.trust_level}/100</div>
      <div className="emotion-row">压力程度：{state.pressure_level}/100</div>
      <div className="emotion-row">开放度：{state.engagement_level}/100</div>
      {state.transition_reason && (
        <div className="emotion-reason">变化原因：{state.transition_reason}</div>
      )}
    </div>
  );
}
```

### 10.3 态度中文映射

```ts
export const attitudeLabelMap: Record<string, string> = {
  calm_neutral: '平静中立',
  guarded_hesitant: '谨慎犹豫',
  defensive_resistant: '防御抵触',
  frustrated_pushback: '受挫反驳',
  silent_withdrawn: '沉默退缩',
  reflective_softening: '开始反思',
  cooperative_constructive: '合作建设性',
};
```

### 10.4 可选语音输出

快速版使用浏览器 Web Speech API：

```ts
export function speakEmployeeText(text: string, attitude: string) {
  if (!window.speechSynthesis) return;

  const config = {
    calm_neutral: { rate: 1.0, pitch: 1.0, volume: 1.0 },
    guarded_hesitant: { rate: 0.9, pitch: 0.9, volume: 0.85 },
    defensive_resistant: { rate: 1.08, pitch: 1.0, volume: 1.0 },
    frustrated_pushback: { rate: 1.12, pitch: 1.1, volume: 1.0 },
    silent_withdrawn: { rate: 0.82, pitch: 0.85, volume: 0.75 },
    reflective_softening: { rate: 0.95, pitch: 0.95, volume: 0.9 },
    cooperative_constructive: { rate: 1.0, pitch: 1.0, volume: 1.0 },
  }[attitude] ?? { rate: 1.0, pitch: 1.0, volume: 1.0 };

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'zh-CN';
  utterance.rate = config.rate;
  utterance.pitch = config.pitch;
  utterance.volume = config.volume;
  window.speechSynthesis.speak(utterance);
}
```

---

## 11. 后端 API 设计

### 11.1 ASR 语音转文字

```http
POST /api/v1/asr/transcribe
Content-Type: multipart/form-data
```

请求：

```text
file: audio/webm 或 audio/wav
language: zh
```

响应：

```json
{
  "text": "我想和你聊一下今年的绩效反馈。",
  "duration_seconds": 6.2,
  "model": "qwen3-asr-flash"
}
```

### 11.2 员工 Agent 消息流

```http
POST /api/v1/rehearsal/{session_id}/message/stream
```

请求：

```json
{
  "message": "我理解你今年确实承担了很多额外任务，但我们也需要看几个具体交付问题。"
}
```

SSE 返回事件：

```text
event: emotion.updated
data: {
  "current_attitude": "reflective_softening",
  "previous_attitude": "defensive_resistant",
  "intensity": 42,
  "trust_level": 55,
  "pressure_level": 48,
  "engagement_level": 60,
  "transition_reason": "HRBP 先确认员工压力，并给出了具体反馈方向",
  "coach_hint": "继续保持共情和事实结合。"
}
```

```text
event: message.delta
data: {"text": "如果是具体交付问题，"}
```

```text
event: message.delta
data: {"text": "我可以一起看。"}
```

```text
event: message.done
data: {
  "text": "如果是具体交付问题，我可以一起看。只是我也希望你能看到当时确实有很多临时需求。"
}
```

### 11.3 获取当前情绪状态

```http
GET /api/v1/rehearsal/{session_id}/emotion
```

响应：

```json
{
  "session_id": "xxx",
  "current_attitude": "defensive_resistant",
  "intensity": 58,
  "trust_level": 35,
  "pressure_level": 70,
  "engagement_level": 42,
  "transition_reason": "HRBP 反馈较直接，缺少具体事实和共情。"
}
```

---

## 12. 数据库存储设计

### 12.1 employee_personas 表

```sql
CREATE TABLE employee_personas (
  id UUID PRIMARY KEY,
  employee_id VARCHAR(64) NOT NULL,
  employee_name VARCHAR(128) NOT NULL,
  persona_type VARCHAR(64) NOT NULL,
  communication_style TEXT,
  core_motivation TEXT,
  fear_or_concern TEXT,
  trigger_points JSONB,
  softening_conditions JSONB,
  sensitivity INT DEFAULT 50,
  defensiveness INT DEFAULT 50,
  openness INT DEFAULT 50,
  need_for_recognition INT DEFAULT 50,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 12.2 session_emotion_states 表

```sql
CREATE TABLE session_emotion_states (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL,
  turn_index INT NOT NULL,
  previous_attitude VARCHAR(64),
  current_attitude VARCHAR(64) NOT NULL,
  intensity INT NOT NULL,
  trust_level INT NOT NULL,
  pressure_level INT NOT NULL,
  engagement_level INT NOT NULL,
  transition_reason TEXT,
  coach_hint TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### 12.3 conversation_analysis 表

```sql
CREATE TABLE conversation_analysis (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL,
  turn_index INT NOT NULL,
  hrbp_text TEXT NOT NULL,
  empathy FLOAT,
  specificity FLOAT,
  respectfulness FLOAT,
  pressure FLOAT,
  clarity FLOAT,
  support_plan FLOAT,
  recognition FLOAT,
  blame_level FLOAT,
  open_question FLOAT,
  likely_employee_reaction VARCHAR(64),
  short_reason TEXT,
  coach_hint TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 13. `.env` 配置

```env
# Bosch LLM API
BOSCH_LLM_BASE_URL=https://aigc.bosch.com.cn/llmservice/api/v1
BOSCH_CHAT_COMPLETIONS_URL=https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions
BOSCH_API_KEY=replace-with-bosch-token
BOSCH_LLM_MODEL=qwen-plus

# ASR
ASR_ENABLED=true
ASR_PROVIDER=bosch_qwen
ASR_MODEL=qwen3-asr-flash
ASR_HTTP_URL=https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions
ASR_LANGUAGE=zh

# Emotion Engine
EMOTION_ENGINE_ENABLED=true
EMOTION_ANALYZER_PROVIDER=bosch_llm
EMOTION_ANALYZER_MODEL=qwen-plus
EMOTION_HISTORY_WINDOW=5
EMOTION_MAX_INTENSITY=75
EMOTION_ENABLE_ANTI_JUMP=true

# Optional Voice Output
SPEECH_OUTPUT_ENABLED=true
SPEECH_OUTPUT_PROVIDER=browser_web_speech
```

说明：

```text
1. 当前使用 qwen3-asr-flash 做语音转文字。
2. qwen3-asr-flash-realtime 只作为后续实时语音升级预留。
3. Bosch chat/completions URL 是 HTTP 地址，不是实时语音 WebSocket 地址。
4. 本期不需要新增 ASR/TTS Docker 镜像。
```

---

## 14. Docker 部署说明

### 14.1 是否需要新增 Docker 镜像

本期不需要新增专门的语音模型或情绪模型 Docker 镜像。

原因：

```text
1. qwen3-asr-flash 是远程 API，不是本地镜像。
2. Bosch LLM API 是远程 HTTP 服务。
3. 情绪状态机是后端业务代码，不需要模型镜像。
4. Web Speech API 是浏览器能力，不需要后端容器。
```

### 14.2 需要重建的服务

需要重建：

```text
backend：新增 Emotion Engine、ASR Route、Prompt Builder
frontend：新增 EmotionBadge、EmotionTimeline、语音输入 UI
```

执行命令：

```bash
cd ~/projects/HRagent-06

docker compose build --no-cache backend frontend
docker compose up -d --force-recreate backend frontend
docker compose logs -f backend
```

### 14.3 不需要执行

```bash
docker pull qwen3-asr-flash
docker pull qwen3-asr-flash-realtime
docker pull bosch-asr
```

这些都不是当前方案需要的本地镜像。

---

## 15. 实现步骤

### P0：最小可用版本

目标：员工已经明显“更像人”。

任务：

```text
1. 新增 Persona 数据结构。
2. 为员工创建 3-5 个基础 Persona 模板。
3. 新增 Conversation Analyzer，分析 HRBP 话术质量。
4. 新增 Emotion State Machine，维护员工态度状态。
5. 新增 Dynamic Prompt Builder。
6. 修改 Rehearsal Message Stream：
   - 用户消息进入后先分析话术
   - 更新员工情绪状态
   - 构造动态 Prompt
   - 调用员工 Agent 生成回复
   - SSE 返回 emotion.updated 和 message.delta
7. 前端显示当前员工状态和变化原因。
8. 报告中记录每轮情绪状态。
```

### P1：语音转文字增强

目标：HRBP 可以说话，系统转写后进入对话。

任务：

```text
1. 前端使用 MediaRecorder 录音。
2. 后端新增 /api/v1/asr/transcribe。
3. 调用 qwen3-asr-flash 完成语音转文字。
4. 转写文本自动填入输入框。
5. HRBP 确认后再发送。
```

### P2：员工语音输出快速版

目标：员工回复能被朗读。

任务：

```text
1. 前端新增自动朗读开关。
2. 使用 Web Speech API 朗读员工回复。
3. 根据 current_attitude 调整 rate、pitch、volume。
4. 增加停止朗读按钮。
```

### P3：报告增强

目标：让训练价值可解释。

任务：

```text
1. Report 中新增情绪时间线。
2. 输出关键转折点。
3. 输出 HRBP 做得好的话术。
4. 输出下一次优化建议。
5. 输出“员工为什么从防御转为合作”。
```

---

## 16. 实现效果示例

### 示例 1：HRBP 直接批评

HRBP：

```text
你这一年的绩效没有达到预期，很多事情做得都不够好。
```

Analyzer 输出：

```json
{
  "empathy": 0.1,
  "specificity": 0.2,
  "respectfulness": 0.6,
  "pressure": 0.8,
  "clarity": 0.4,
  "support_plan": 0.0,
  "recognition": 0.0,
  "blame_level": 0.7,
  "likely_employee_reaction": "escalate",
  "short_reason": "反馈压力较高，但缺少具体事实和共情"
}
```

员工状态变化：

```text
guarded_hesitant → defensive_resistant
```

员工回复：

```text
我知道结果可能没有完全达到预期，但如果只是说很多事情都不够好，我会觉得有点笼统。能不能具体说一下哪些地方最影响评价？
```

---

### 示例 2：HRBP 共情 + 具体事实

HRBP：

```text
我理解你今年承担了不少临时任务，这部分努力我们是看见的。今天我想先聚焦两个具体交付案例，看看哪些地方影响了整体评价。
```

员工状态变化：

```text
defensive_resistant → reflective_softening
```

员工回复：

```text
如果是具体案例，我愿意一起看。只是我也希望这些临时任务的影响能被放进整体背景里考虑。
```

---

### 示例 3：HRBP 给出支持方案

HRBP：

```text
下个周期我们可以一起明确优先级。如果有临时需求插入，我也会帮你一起确认哪些任务需要重新排序。
```

员工状态变化：

```text
reflective_softening → cooperative_constructive
```

员工回复：

```text
这样会比较清楚，我也会更知道哪些事情要优先保证。如果能提前对齐优先级，我觉得下个周期会更好推进。
```

---

## 17. 验收标准

### 17.1 功能验收

| 验收项 | 标准 |
|---|---|
| 语音转文字 | HRBP 录音后可得到可编辑文本 |
| 员工画像 | 每个员工有基础人格配置 |
| 话术分析 | 每轮 HRBP 输入后生成结构化评分 |
| 情绪变化 | 员工状态会根据 HRBP 话术变化 |
| 回复拟人化 | 员工回复符合当前状态和人格 |
| UI 展示 | 页面显示员工状态、强度、变化原因 |
| Report | 报告展示情绪转折点和建议 |
| 安全边界 | 不出现辱骂、人身攻击、歧视、威胁 |

### 17.2 业务验收

```text
1. HRBP 直接否定时，员工变得防御或沉默。
2. HRBP 表达共情时，员工态度缓和。
3. HRBP 给出具体事实时，员工愿意讨论。
4. HRBP 给出支持方案时，员工转向合作。
5. 不同 Persona 的员工对同一句 HRBP 话术反应不同。
6. Report 可以解释员工态度为什么变化。
```

---

## 18. 给 AI Coding 工具的最终执行提示词

```text
请在当前 HRagent 项目中实现“人格化员工对话与情绪变化模块”。

当前业务边界：
1. 当前不是实时语音通话。
2. 当前功能是 HRBP 语音转文字，HRBP 确认文本后发送。
3. 员工 Agent 根据 HRBP 的话术、人设和当前情绪状态进行回复。
4. 目标是让员工回复更像真实人类员工，而不是模板机器人。

后端实现要求：
1. 新增 backend/schemas/persona.py，定义 EmployeePersona、PersonaType。
2. 新增 backend/schemas/emotion.py，定义 EmployeeAttitude、EmotionState。
3. 新增 backend/schemas/conversation_analysis.py，定义 ConversationSignal。
4. 新增 backend/services/persona_profile_service.py，用于加载员工 Persona。
5. 新增 backend/services/conversation_analyzer.py，调用 Bosch Chat Completions API，分析 HRBP 话术的 empathy、specificity、respectfulness、pressure、clarity、support_plan、recognition、blame_level、open_question 等指标，只返回 JSON。
6. 新增 backend/services/emotion_state_machine.py，根据 ConversationSignal 和当前 EmotionState 更新员工状态。
7. 新增 backend/services/dynamic_prompt_builder.py，将 EmployeePersona + EmotionState + HRBP 最新输入组装为员工 Agent 的动态 Prompt。
8. 修改 rehearsal message stream 接口：
   - 接收 HRBP 文本
   - 加载当前 employee persona
   - 加载当前 emotion state
   - 调用 conversation analyzer
   - 更新 emotion state
   - 保存 analysis 和 emotion state
   - 构建 dynamic prompt
   - 调用员工 Agent 生成回复
   - SSE 先返回 emotion.updated，再返回 message.delta 和 message.done
9. 新增 /api/v1/asr/transcribe 接口，用于接收前端音频文件并调用 qwen3-asr-flash 进行语音转文字。
10. 新增 EMOTION_ENGINE_ENABLED 开关，关闭后保持原有对话逻辑。
11. 保证高压状态下员工可以不满、防御、反驳，但不能辱骂、人身攻击、歧视或威胁。

前端实现要求：
1. 修改 RehearsalStep.tsx。
2. 新增语音录制功能，使用 MediaRecorder，录音后上传 /api/v1/asr/transcribe。
3. ASR 返回文本后填入输入框，由 HRBP 确认后发送。
4. 新增 EmotionBadge 组件，显示当前员工状态、情绪强度、信任程度、压力程度、开放度、变化原因。
5. 新增 EmotionTimeline 组件，显示状态变化轨迹。
6. 新增 CoachHintCard 组件，显示 HRBP 当前话术建议。
7. 处理 SSE 的 emotion.updated 事件，实时更新右侧状态面板。
8. 可选：新增自动朗读员工回复开关，使用浏览器 Web Speech API。

配置要求：
1. 使用 Bosch Chat Completions URL：
   https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions
2. ASR 模型使用 qwen3-asr-flash。
3. qwen3-asr-flash-realtime 只作为后续实时升级预留，本期不使用。
4. 本期不新增 Docker 镜像，只需要重建 backend 和 frontend。

验收标准：
1. HRBP 直接批评时，员工状态从谨慎或中立变为防御抵触。
2. HRBP 共情并给出具体事实时，员工从防御转为开始反思。
3. HRBP 给出支持方案时，员工转为合作建设性。
4. 页面能看到员工状态变化和变化原因。
5. Report 能输出情绪转折点和沟通建议。
6. 回复自然、克制、像真实员工，不像客服模板。
```

---

## 19. 最终推荐路线

```text
第一阶段：语音转文字 + 员工情绪状态变化
第二阶段：右侧面板展示员工状态和实时建议
第三阶段：Report 输出情绪转折点
第四阶段：前端 Web Speech API 快速实现员工语音输出
第五阶段：后续如有实时 WebSocket ASR/TTS，再升级为实时语音通话
```

最终判断：

```text
这套方案可以落地。
不需要新增 Docker 语音模型镜像。
不需要当前就实现实时语音通话。
最重要的是先实现：Persona Profile + Conversation Analyzer + Emotion State Machine + Dynamic Prompt。
```
