# HRagent 语音转文字驱动员工情绪变化模块技术方案

## 0. 文档定位

本文档用于指导 AI Coding 工具在现有 HRagent 项目中实现如下功能：

> **HRBP 通过语音输入表达反馈内容，系统先完成语音转文字，再根据 HRBP 的话术内容、语气信息和对话上下文，让虚拟员工在文本回复中呈现合理的态度与情绪变化。**

当前阶段**不实现实时语音输入、实时语音输出、实时 TTS 播放**。

当前阶段的核心闭环是：

```text
HRBP 点击麦克风
  ↓
录制一段语音
  ↓
ASR 语音转文字
  ↓
文字进入对话输入框
  ↓
HRBP 确认并发送
  ↓
情绪/态度转换引擎分析 HRBP 话术
  ↓
更新虚拟员工态度状态
  ↓
员工 Agent 按当前情绪状态生成文本回复
  ↓
页面展示员工回复 + 当前情绪状态
```

---

## 1. 本期功能边界

### 1.1 本期要做

```text
1. 语音转文字：HRBP 说话后，系统识别成文本。
2. 文本确认：识别结果进入输入框，HRBP 可以修改。
3. 情绪分析：系统分析 HRBP 输入对员工情绪的影响。
4. 态度转换：员工状态在多轮对话中动态变化。
5. 文本表现：员工回复内容体现当前态度，例如防御、犹豫、反思、合作。
6. UI 展示：页面展示当前员工态度和变化原因。
7. 复盘记录：后续报告可以显示情绪转折点。
```

### 1.2 本期不做

```text
1. 不做实时边说边出字。
2. 不做 AI 实时语音播报。
3. 不做全双工语音对话。
4. 不做本地部署语音大模型。
5. 不把 ASR 音频长期落盘。
6. 不让虚拟员工出现辱骂、人身攻击、歧视或过度戏剧化内容。
```

### 1.3 推荐交互

```text
点击麦克风 → 开始录音
再次点击 / 自动静音结束 → 停止录音
后端调用 ASR → 返回识别文本
文本填入输入框 → HRBP 确认后点击发送
员工根据话术质量和上下文产生情绪变化并回复
```

---

## 2. 推荐总体方案

### 2.1 技术路线

本期采用：

```text
录音式 ASR + LLM 话术分析 + 规则状态机 + 动态 Persona Prompt
```

具体说明：

```text
ASR 只负责把 HRBP 的语音变成文字。
LLM 负责判断 HRBP 话术质量和潜在情绪影响。
规则状态机负责控制员工情绪变化的稳定性和边界。
动态 Persona Prompt 负责让员工回复体现当前态度。
前端 UI 负责展示当前员工状态、强度和变化原因。
```

### 2.2 为什么不直接靠 Prompt

不建议只在员工 Agent Prompt 中写：

```text
请根据用户话术动态改变情绪。
```

原因：

```text
1. 情绪状态不可追踪。
2. 多轮对话容易遗忘上一轮状态。
3. 难以在 UI 上展示当前员工状态。
4. 难以生成复盘报告。
5. 情绪变化可能跳变太大。
6. 高压场景容易生成不符合企业边界的内容。
```

所以需要将“员工当前态度状态”作为结构化数据保存在后端 session 中。

---

## 3. 系统架构

```text
┌─────────────────────────────────────────────┐
│                Frontend React                │
│                                             │
│  RehearsalStep.tsx                           │
│  - 麦克风录音按钮                            │
│  - ASR 转写结果输入框                        │
│  - 员工情绪 Badge                            │
│  - 情绪变化提示                              │
└───────────────────────┬─────────────────────┘
                        │ HTTP / WebSocket
                        ▼
┌─────────────────────────────────────────────┐
│                 FastAPI Backend              │
│                                             │
│  /api/v1/asr/transcribe                      │
│  - 接收音频文件 Blob                         │
│  - 调用 qwen3-asr-flash / Bosch ASR 网关      │
│  - 返回 transcript                           │
│                                             │
│  /api/v1/rehearsal/{session_id}/message      │
│  - 接收 HRBP 文本                            │
│  - 调用 Emotion Analyzer                     │
│  - 调用 Attitude State Machine               │
│  - 构造动态员工 Prompt                       │
│  - 调用 Employee Agent 生成回复              │
└───────────────────────┬─────────────────────┘
                        │
      ┌─────────────────┼──────────────────┐
      ▼                 ▼                  ▼
┌──────────────┐ ┌────────────────┐ ┌────────────────────┐
│ ASR Service   │ │ Emotion Engine │ │ Employee Agent       │
│ qwen3-asr     │ │ 状态机 + LLM    │ │ Bosch LLM / Qwen      │
│ flash         │ │ 话术分析        │ │ 文本回复生成          │
└──────────────┘ └────────────────┘ └────────────────────┘
```

---

## 4. 技术栈清单

### 4.1 前端技术栈

| 技术 | 用途 |
|---|---|
| React | 对话预演页面开发 |
| TypeScript | 类型约束，提高代码稳定性 |
| Vite | 前端构建 |
| MediaRecorder API | 录制 HRBP 语音 |
| `navigator.mediaDevices.getUserMedia` | 获取麦克风权限 |
| FormData / Blob | 上传音频文件到后端 |
| SSE / WebSocket | 接收员工 Agent 流式文本回复；如当前已有 SSE 可继续沿用 |
| CSS / existing global.css | 录音按钮、情绪 Badge、状态提示样式 |

### 4.2 后端技术栈

| 技术 | 用途 |
|---|---|
| FastAPI | 后端 API 服务 |
| Python 3.11 | 后端运行环境 |
| Uvicorn | ASGI 服务 |
| httpx | 调用 Bosch AIGC / ASR HTTP 接口 |
| python-multipart | 接收前端上传的音频文件 |
| Pydantic | 配置与 Schema 管理 |
| Redis | 可选，用于缓存 session 情绪状态 |
| PostgreSQL | 可选，用于持久化对话与复盘数据 |

### 4.3 模型与服务

| 服务 | 推荐用途 |
|---|---|
| `qwen3-asr-flash` | 本期首选，录音完成后转文字 |
| `qwen3-asr-flash-realtime` | 后续实时语音输入升级备用，本期不作为主方案 |
| Bosch AIGC Chat Completions | 员工 Agent 回复生成、情绪分析 JSON 生成 |
| qwen-plus / qwen-turbo / 企业内可用模型 | 情绪分析、话术质量判断、员工回复生成 |

### 4.4 Docker 技术栈

| 容器 | 是否需要新增 |
|---|---|
| frontend | 需要修改并重新 build |
| backend | 需要修改并重新 build |
| postgres | 不需要新增 |
| redis | 不需要新增 |
| ASR 模型镜像 | 不需要，本期调用远程 ASR 服务 |

---

## 5. ASR 语音转文字方案

### 5.1 推荐本期使用非实时录音转写

由于产品当前需求不是实时语音，而是“HRBP 说话 → 转文字 → 员工产生情绪变化”，建议本期使用录音文件转写方式：

```text
前端录音 Blob
  ↓
POST /api/v1/asr/transcribe
  ↓
后端转发到 qwen3-asr-flash / Bosch ASR 网关
  ↓
返回 transcript
  ↓
前端 setMessage(transcript)
```

优势：

```text
1. 逻辑简单，开发风险低。
2. 不需要 WebSocket ASR。
3. 不需要 AudioWorklet。
4. 不需要处理实时音频帧。
5. 更适合当前“识别后确认再发送”的 HR 训练场景。
6. 更容易做录音时长限制、失败重试和日志审计。
```

### 5.2 前端录音流程

```text
用户点击麦克风
  ↓
浏览器请求麦克风权限
  ↓
MediaRecorder 开始录音
  ↓
用户再次点击或达到最大时长自动停止
  ↓
生成 audio/webm 或 audio/wav Blob
  ↓
上传后端 /api/v1/asr/transcribe
  ↓
获取 transcript
  ↓
填入当前输入框
```

### 5.3 音频格式建议

优先级：

```text
1. webm/opus：浏览器兼容较好，前端实现简单。
2. wav/pcm：ASR 兼容性强，但前端处理成本更高。
```

建议第一版：

```text
前端使用 MediaRecorder 生成 audio/webm。
后端如 ASR 网关支持 webm/opus，则直接转发。
如果网关只支持 wav/pcm，则后端增加 ffmpeg 转码。
```

后端可选依赖：

```text
ffmpeg
pydub
```

如果公司服务器安装 ffmpeg 不方便，优先确认 Bosch ASR 网关是否支持 webm/opus 或 wav 文件上传。

---

## 6. 情绪与态度状态设计

### 6.1 员工态度状态枚举

新增文件：

```text
backend/schemas/emotion.py
```

建议状态：

```python
from enum import Enum

class EmployeeAttitude(str, Enum):
    CALM_NEUTRAL = "calm_neutral"                 # 平静中立
    GUARDED_HESITANT = "guarded_hesitant"         # 谨慎犹豫
    DEFENSIVE_RESISTANT = "defensive_resistant"   # 防御抵触
    FRUSTRATED_PUSHBACK = "frustrated_pushback"   # 不满反驳
    SILENT_WITHDRAWN = "silent_withdrawn"         # 沉默退缩
    REFLECTIVE_SOFTENING = "reflective_softening" # 开始反思
    COOPERATIVE_CONSTRUCTIVE = "cooperative_constructive" # 合作建设性
```

### 6.2 状态含义

| 状态 | 中文 | 员工回复表现 |
|---|---|---|
| `calm_neutral` | 平静中立 | 正常回应，没有明显防御 |
| `guarded_hesitant` | 谨慎犹豫 | 回答保守，有所保留 |
| `defensive_resistant` | 防御抵触 | 解释困难，质疑反馈是否片面 |
| `frustrated_pushback` | 不满反驳 | 表达委屈或不满，但保持职场边界 |
| `silent_withdrawn` | 沉默退缩 | 回避、短句、不愿展开 |
| `reflective_softening` | 开始反思 | 接受部分反馈，愿意听具体例子 |
| `cooperative_constructive` | 合作建设性 | 主动讨论改进和下一步方案 |

### 6.3 情绪强度

每个 session 保存：

```python
emotion_intensity: int  # 0 - 100
```

建议上限：

```text
普通训练：60
高压训练：75
默认不超过 75，避免员工表现过度戏剧化。
```

---

## 7. 情绪分析输入信号

本期主要使用文本信号。

### 7.1 HRBP 语音转写文本

示例：

```text
你这个季度交付质量不太稳定，尤其是两个关键节点都有延期。
```

系统分析：

```text
是否具体？
是否尊重？
是否有共情？
是否有事实依据？
是否只是笼统否定？
是否给出支持方案？
```

### 7.2 ASR 可选情绪字段

如果 ASR 返回音频情绪字段，可以作为辅助信号：

```json
{
  "transcript": "我理解你压力很大，但我们还是要看实际交付结果。",
  "audio_emotion": "neutral"
}
```

注意：

```text
audio_emotion 表示 HRBP 说话声音中的情绪，不等于员工情绪。
员工情绪必须由 HRBP 文本内容 + 对话历史 + 当前员工状态综合决定。
```

### 7.3 对话历史

分析最近 3-5 轮：

```text
HRBP 是否连续施压？
HRBP 是否承认员工困难？
HRBP 是否给出具体案例？
HRBP 是否提出支持方案？
员工上一轮是否已经防御？
员工是否已经开始软化？
```

---

## 8. 情绪分析 LLM 输出结构

新增 Schema：

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class EmotionSignal(BaseModel):
    user_text_emotion: Optional[str] = None
    audio_emotion: Optional[str] = None
    empathy: float = Field(ge=0, le=1)
    clarity: float = Field(ge=0, le=1)
    specificity: float = Field(ge=0, le=1)
    respectfulness: float = Field(ge=0, le=1)
    pressure: float = Field(ge=0, le=1)
    support_plan: float = Field(ge=0, le=1)
    likely_employee_reaction: Literal["escalate", "soften", "withdraw", "stay"]
    risk_flags: List[str] = []
```

LLM 输出示例：

```json
{
  "user_text_emotion": "calm",
  "audio_emotion": "neutral",
  "empathy": 0.72,
  "clarity": 0.81,
  "specificity": 0.68,
  "respectfulness": 0.91,
  "pressure": 0.35,
  "support_plan": 0.20,
  "likely_employee_reaction": "soften",
  "risk_flags": []
}
```

---

## 9. 态度状态机规则

### 9.1 状态转换逻辑

```text
用户直接否定 + 缺少事实 → 员工更防御
用户高压追问 + 缺少共情 → 员工不满或沉默
用户共情 + 具体事实 → 员工开始软化
用户给出支持方案 → 员工转向合作
用户空泛鼓励但没有具体行动 → 员工保持谨慎
用户持续打断或命令式表达 → 员工抵触增强
```

### 9.2 状态转换图

```text
calm_neutral
  ├─ 模糊批评 / 缺少共情 → guarded_hesitant
  ├─ 直接否定 / 高压表达 → defensive_resistant
  └─ 共情 + 具体事实 → reflective_softening

guarded_hesitant
  ├─ 继续施压 → defensive_resistant
  ├─ 忽视情绪 → silent_withdrawn
  └─ 共情 + 事实 → reflective_softening

defensive_resistant
  ├─ 继续否定 → frustrated_pushback
  ├─ 降低压力 → guarded_hesitant
  └─ 共情 + 事实 + 支持 → reflective_softening

frustrated_pushback
  ├─ 继续施压 → 保持 frustrated_pushback，不升级到辱骂
  ├─ 承认员工困难 → defensive_resistant
  └─ 给出具体支持 → reflective_softening

silent_withdrawn
  ├─ 开放式提问 + 降低压力 → guarded_hesitant
  └─ 继续追问 → 保持 silent_withdrawn

reflective_softening
  ├─ 给出支持方案 → cooperative_constructive
  ├─ 再次强压 → defensive_resistant
  └─ 事实不清 → guarded_hesitant

cooperative_constructive
  ├─ 持续支持 → 保持 cooperative_constructive
  └─ 突然强压 → guarded_hesitant / defensive_resistant
```

### 9.3 防跳变机制

必须实现：

```text
1. 单轮最多变化一个等级。
2. 防御状态不能一轮直接跳到完全合作。
3. 合作状态不能因为一句话直接跳到愤怒。
4. 高压状态不允许出现辱骂、人身攻击、歧视。
5. 每次转换必须记录 transition_reason。
6. 如果 LLM 分析失败，保持当前状态。
```

---

## 10. 后端新增文件设计

### 10.1 新增文件清单

```text
backend/schemas/emotion.py
backend/services/asr_service.py
backend/services/emotion_analyzer.py
backend/services/attitude_transition_engine.py
backend/services/dynamic_persona_builder.py
backend/api/routes/asr.py
```

如果当前项目已经有部分文件，则在现有模块中合并实现，不重复创建功能重叠文件。

---

## 11. 后端 API 设计

### 11.1 ASR 转写接口

```text
POST /api/v1/asr/transcribe
```

请求：

```text
multipart/form-data
file: audio Blob
session_id: string
language: zh / en / auto
```

响应：

```json
{
  "text": "我理解你这段时间压力很大，但这次反馈主要聚焦交付质量。",
  "audio_emotion": "neutral",
  "duration_seconds": 8.4,
  "provider": "qwen3-asr-flash"
}
```

错误响应：

```json
{
  "error": "ASR_TRANSCRIBE_FAILED",
  "message": "语音识别失败，请重试。"
}
```

### 11.2 Rehearsal 消息接口改造

现有接口可能类似：

```text
POST /api/v1/rehearsal/{session_id}/message
GET  /api/v1/rehearsal/{session_id}/message/stream
```

需要在员工回复生成前增加：

```text
1. 读取当前 EmotionState。
2. 调用 EmotionAnalyzer 分析 HRBP 文本。
3. 调用 AttitudeTransitionEngine 计算新状态。
4. 生成 Dynamic Attitude Prompt。
5. 注入 Employee Agent。
6. 返回员工回复与 emotion_state。
```

响应中新增：

```json
{
  "employee_message": "我知道结果不理想，但我觉得只看交付质量有点片面。这个季度需求变更很多，我也承担了不少临时任务。",
  "emotion_state": {
    "current_attitude": "defensive_resistant",
    "intensity": 52,
    "previous_attitude": "guarded_hesitant",
    "transition_reason": "direct_criticism_with_low_empathy"
  }
}
```

如果使用 SSE 流式返回，新增事件：

```text
event: emotion.updated
data: {"current_attitude":"defensive_resistant","intensity":52,"transition_reason":"direct_criticism_with_low_empathy"}
```

---

## 12. 核心服务实现说明

### 12.1 asr_service.py

职责：

```text
1. 接收 UploadFile。
2. 校验文件大小和时长。
3. 调用 qwen3-asr-flash 或 Bosch ASR HTTP 网关。
4. 返回 transcript。
5. 不长期保存原始音频。
```

伪代码：

```python
class AsrService:
    async def transcribe(self, file: UploadFile, language: str = "zh") -> AsrResult:
        audio_bytes = await file.read()
        self._validate_audio(audio_bytes)
        result = await self._call_asr_provider(audio_bytes, language)
        return AsrResult(
            text=result.text,
            audio_emotion=result.audio_emotion,
            duration_seconds=result.duration_seconds,
            provider=self.settings.asr_model,
        )
```

### 12.2 emotion_analyzer.py

职责：

```text
用 LLM 把 HRBP 文本转成结构化 EmotionSignal。
```

Prompt 模板：

```text
你是 HR 绩效反馈训练系统中的对话质量分析器。
你的任务不是生成员工回复，而是分析 HRBP 这句话会如何影响虚拟员工的态度。

请只输出 JSON。

分析维度：
- empathy: 是否表达理解和共情
- clarity: 表达是否清晰
- specificity: 是否包含具体事实或案例
- respectfulness: 是否尊重员工
- pressure: 是否施压、否定或命令式表达
- support_plan: 是否给出支持方案或下一步行动
- likely_employee_reaction: 员工更可能升级、软化、退缩还是保持

当前员工状态：{current_attitude}
最近对话历史：{history}
HRBP 最新输入：{user_text}
ASR 音频情绪：{audio_emotion}

输出 JSON：
{
  "user_text_emotion": "calm|angry|anxious|confident|unclear",
  "audio_emotion": "neutral|null",
  "empathy": 0.0,
  "clarity": 0.0,
  "specificity": 0.0,
  "respectfulness": 0.0,
  "pressure": 0.0,
  "support_plan": 0.0,
  "likely_employee_reaction": "escalate|soften|withdraw|stay",
  "risk_flags": []
}
```

### 12.3 attitude_transition_engine.py

职责：

```text
输入 EmotionSignal 和当前 EmotionState，输出下一状态。
```

伪代码：

```python
def compute_next_state(current: EmotionState, signal: EmotionSignal) -> EmotionState:
    if signal.risk_flags:
        return keep_with_safety_reason(current)

    if signal.pressure > 0.75 and signal.empathy < 0.30:
        return escalate(current, reason="high_pressure_low_empathy")

    if signal.respectfulness < 0.45:
        return escalate(current, reason="low_respectfulness")

    if signal.empathy > 0.65 and signal.specificity > 0.55:
        return soften(current, reason="empathy_with_specific_evidence")

    if signal.support_plan > 0.60:
        return soften(current, reason="concrete_support_plan")

    if signal.likely_employee_reaction == "withdraw":
        return withdraw(current, reason="employee_likely_to_withdraw")

    return stay(current, reason="no_significant_change")
```

### 12.4 dynamic_persona_builder.py

职责：

```text
把当前员工态度状态转换成 Employee Agent 的动态 Prompt。
```

输出示例：

```text
[当前员工态度状态]
状态：defensive_resistant
强度：52/100
变化原因：HRBP 表达较直接，缺少对员工困难的确认。

[回复要求]
你现在明显有防御和抵触，但仍然保持职场边界。
你的回复应该体现：
1. 你觉得评价可能有些片面。
2. 你会解释本季度遇到的困难。
3. 你会希望 HRBP 提供更具体的依据。
4. 不允许辱骂、人身攻击、歧视或威胁。
5. 回复长度控制在 1-3 句话。
```

---

## 13. 前端改造方案

### 13.1 需要新增/修改文件

```text
frontend/src/hooks/useSpeechToText.ts
frontend/src/components/rehearsal/EmotionBadge.tsx
frontend/src/components/rehearsal/EmotionTimeline.tsx
frontend/src/pages/steps/RehearsalStep.tsx
frontend/src/styles/global.css
frontend/src/lib/client.ts
```

### 13.2 useSpeechToText.ts

职责：

```text
1. 获取麦克风权限。
2. 使用 MediaRecorder 录音。
3. 维护 recording / transcribing / error 状态。
4. 停止录音后上传音频。
5. 返回 transcript。
6. 将 transcript 填入输入框。
```

接口设计：

```typescript
type SpeechToTextState = {
  recording: boolean
  transcribing: boolean
  error: string | null
  transcript: string
}

function useSpeechToText(options: {
  sessionId: string
  onTranscript: (text: string, meta?: { audioEmotion?: string }) => void
}) {
  return {
    recording,
    transcribing,
    error,
    startRecording,
    stopRecording,
    resetTranscript,
  }
}
```

### 13.3 RehearsalStep.tsx 改造

当前麦克风按钮从“占位提示”改为：

```tsx
<button
  className={`mic-button ${recording ? 'recording' : ''} ${transcribing ? 'transcribing' : ''}`}
  type="button"
  disabled={rehearsalStreaming || transcribing}
  onClick={recording ? stopRecording : startRecording}
>
  {recording ? '停止录音' : transcribing ? '识别中' : '语音输入'}
</button>
```

识别完成：

```tsx
onTranscript={(text, meta) => {
  setMessage(text)
  setLastAudioEmotion(meta?.audioEmotion)
}}
```

发送消息时：

```typescript
await sendRehearsalMessage({
  sessionId,
  text: message,
  inputMode: 'voice_asr',
  audioEmotion: lastAudioEmotion,
})
```

### 13.4 EmotionBadge.tsx

展示内容：

```text
员工当前状态：防御抵触
情绪强度：52/100
变化原因：表达较直接，缺少共情
```

状态映射：

| 状态 | 显示文案 |
|---|---|
| `calm_neutral` | 平静 |
| `guarded_hesitant` | 谨慎 |
| `defensive_resistant` | 防御 |
| `frustrated_pushback` | 不满 |
| `silent_withdrawn` | 沉默 |
| `reflective_softening` | 反思 |
| `cooperative_constructive` | 合作 |

---

## 14. 配置项设计

`.env.example` 新增：

```env
# Speech To Text
ASR_ENABLED=true
ASR_PROVIDER=bosch_qwen
ASR_MODEL=qwen3-asr-flash
ASR_HTTP_URL=https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions
ASR_API_KEY=replace-with-bosch-token
ASR_MAX_AUDIO_SECONDS=60
ASR_MAX_AUDIO_MB=20
ASR_LANGUAGE=zh

# Realtime ASR Reserved, not used in current phase
ASR_REALTIME_MODEL=qwen3-asr-flash-realtime
ASR_WS_URL=

# Emotion Engine
EMOTION_ENGINE_ENABLED=true
EMOTION_ANALYZER_PROVIDER=bosch_llm
EMOTION_ANALYZER_MODEL=qwen-plus
EMOTION_HISTORY_WINDOW=5
EMOTION_STATE_MAX_INTENSITY=75
EMOTION_STATE_ANTI_JUMP=true

# Bosch LLM Gateway
BOSCH_LLM_BASE_URL=https://aigc.bosch.com.cn/llmservice/api/v1
BOSCH_CHAT_COMPLETIONS_URL=https://aigc.bosch.com.cn/llmservice/api/v1/chat/completions
BOSCH_API_KEY=replace-with-bosch-token
```

说明：

```text
1. ASR_MODEL 本期使用 qwen3-asr-flash。
2. ASR_REALTIME_MODEL 仅作为后续升级预留。
3. ASR_WS_URL 本期可以为空。
4. Bosch chat/completions 是否支持音频输入需要内部确认。
5. 如果 Bosch 网关不支持音频输入，需要单独申请 ASR 文件转写接口。
```

---

## 15. Docker 与部署说明

### 15.1 是否需要新增 Docker 镜像

不需要新增 ASR 或情绪模型镜像。

本期是远程调用：

```text
qwen3-asr-flash：远程 ASR 服务
Bosch LLM：远程 Chat Completions 服务
Emotion Engine：后端 Python 代码实现
```

### 15.2 需要重新构建

```bash
docker compose build --no-cache backend frontend
docker compose up -d --force-recreate backend frontend
```

### 15.3 如果增加 ffmpeg 转码

Dockerfile backend 需要安装：

```dockerfile
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
```

如果不需要转码，可以不加 ffmpeg。

---

## 16. 数据存储设计

### 16.1 Session Emotion State

可存 Redis 或 PostgreSQL。

最小结构：

```json
{
  "session_id": "xxx",
  "current_attitude": "defensive_resistant",
  "previous_attitude": "guarded_hesitant",
  "intensity": 52,
  "transition_reason": "direct_criticism_with_low_empathy",
  "turn_index": 4,
  "updated_at": "2026-06-29T12:00:00Z"
}
```

### 16.2 Conversation Emotion Log

用于复盘：

```json
{
  "session_id": "xxx",
  "turn_index": 4,
  "hrbp_text": "你这个季度交付质量不太稳定。",
  "input_mode": "voice_asr",
  "audio_emotion": "neutral",
  "employee_attitude_before": "guarded_hesitant",
  "employee_attitude_after": "defensive_resistant",
  "intensity": 52,
  "transition_reason": "direct_criticism_with_low_empathy",
  "employee_reply": "我知道结果不理想，但我觉得只看交付质量有点片面。"
}
```

---

## 17. 安全与业务边界

### 17.1 员工不允许出现的内容

```text
辱骂
人身攻击
歧视表达
威胁
极端情绪宣泄
过度戏剧化
脱离企业绩效反馈场景
```

### 17.2 HRBP 语音数据处理

```text
1. 默认不保存原始音频。
2. 只保存转写文本和必要的元数据。
3. 日志不记录完整音频内容。
4. API Key 只放后端环境变量。
5. 前端不得暴露 Bosch Token 或 ASR Key。
```

### 17.3 员工情绪强度控制

```text
默认最大强度：75/100
普通场景建议：60/100
高压训练场景建议：75/100
无论强度多高，都必须保持企业沟通边界。
```

---

## 18. MVP 开发任务拆分

### P0：语音转文字 + 情绪状态变化

```text
1. 实现 /api/v1/asr/transcribe。
2. 前端实现 MediaRecorder 录音。
3. ASR 结果填入输入框。
4. 新增 EmotionState / EmotionSignal Schema。
5. 新增 EmotionAnalyzer。
6. 新增 AttitudeTransitionEngine。
7. 员工回复前注入动态态度 Prompt。
8. 前端显示 EmotionBadge。
```

### P1：复盘与可解释性

```text
1. 保存每轮状态变化日志。
2. 复盘报告显示情绪转折点。
3. 显示触发原因和 HRBP 话术建议。
4. 支持导出报告。
```

### P2：场景配置

```text
1. 支持设置员工初始状态。
2. 支持设置训练难度。
3. 支持设置员工 persona：敏感型、抵触型、沉默型、合作型。
4. 支持不同场景情绪上限。
```

---

## 19. 验收标准

### 19.1 语音转文字验收

| 项目 | 标准 |
|---|---|
| 录音 | 点击麦克风可开始/停止录音 |
| 权限 | 首次使用会请求麦克风权限 |
| 转写 | 停止录音后 1-5 秒内返回文本，具体取决于音频长度和网关延迟 |
| 回填 | 转写文本自动进入输入框 |
| 修改 | HRBP 可以手动修改识别结果 |
| 失败 | ASR 失败时有明确错误提示 |

### 19.2 情绪变化验收

| 场景 | 预期员工变化 |
|---|---|
| HRBP 直接批评，无具体事实 | 员工转向防御 |
| HRBP 只施压、不共情 | 员工转向不满或沉默 |
| HRBP 先共情再给事实 | 员工开始软化 |
| HRBP 给出支持方案 | 员工转向合作 |
| HRBP 表达强硬 | 员工可以抵触，但不能辱骂攻击 |

### 19.3 典型测试用例

#### 用例 1：直接批评

HRBP：

```text
你这个季度表现很差，交付质量完全不行。
```

预期：

```text
员工状态：calm_neutral → defensive_resistant
员工回复：解释困难，质疑评价是否片面。
```

#### 用例 2：共情 + 事实

HRBP：

```text
我理解你这段时间资源压力很大，所以我们先聚焦两个具体交付案例，而不是否定你的全部努力。
```

预期：

```text
员工状态：defensive_resistant → reflective_softening
员工回复：愿意听具体案例，但仍保留解释空间。
```

#### 用例 3：支持方案

HRBP：

```text
下个周期我们可以一起明确优先级，我也会帮你协调需求变更时的沟通机制。
```

预期：

```text
员工状态：reflective_softening → cooperative_constructive
员工回复：愿意讨论下一步改进。
```

---

## 20. 给 AI Coding 工具的执行提示词

可以直接复制给 AI Coding 工具：

```text
请基于当前 HRagent 项目实现“语音转文字驱动员工情绪变化”功能。

注意：当前阶段不是实时语音输入，也不是实时语音输出。本期只需要实现 HRBP 录一段语音，系统转成文字，HRBP 确认发送后，虚拟员工根据 HRBP 的话术内容产生合理的态度和情绪变化，并以文本回复体现出来。

后端要求：
1. 新增 /api/v1/asr/transcribe 接口，接收 multipart audio file，调用 qwen3-asr-flash 或 Bosch ASR HTTP 网关，返回 transcript、audio_emotion、duration_seconds。
2. 新增 backend/schemas/emotion.py，定义 EmployeeAttitude、EmotionSignal、EmotionState。
3. 新增 backend/services/emotion_analyzer.py，调用 Bosch Chat Completions，分析 HRBP 文本的 empathy、clarity、specificity、respectfulness、pressure、support_plan，并返回结构化 JSON。
4. 新增 backend/services/attitude_transition_engine.py，实现员工态度状态机，包含 calm_neutral、guarded_hesitant、defensive_resistant、frustrated_pushback、silent_withdrawn、reflective_softening、cooperative_constructive。
5. 新增 backend/services/dynamic_persona_builder.py，把当前员工态度转换成动态 Prompt，并在 Employee Agent 回复前注入。
6. 修改 rehearsal message 处理逻辑：收到 HRBP 文本后，先更新员工情绪状态，再生成员工回复。
7. 保存每轮 emotion_state、transition_reason、input_mode，用于复盘。
8. 增加 EMOTION_ENGINE_ENABLED 开关，关闭后保持原逻辑。
9. 保证员工高压状态下也不能出现辱骂、人身攻击、歧视或脱离企业场景的内容。

前端要求：
1. 新增 useSpeechToText.ts，使用 MediaRecorder 录音并上传到 /api/v1/asr/transcribe。
2. 修改 RehearsalStep.tsx，把原麦克风占位按钮改成真实录音按钮。
3. ASR 转写完成后，将文本填入输入框，允许 HRBP 修改后再发送。
4. 发送消息时携带 inputMode='voice_asr' 和 audioEmotion。
5. 新增 EmotionBadge.tsx，展示员工当前态度、强度、变化原因。
6. 如果当前使用 SSE 流式回复，需要支持 emotion.updated 事件。
7. UI 风格保持现有 Bosch 风格，不要做过度花哨的情绪动画。

配置要求：
1. .env.example 增加 ASR_ENABLED、ASR_PROVIDER、ASR_MODEL、ASR_HTTP_URL、ASR_API_KEY、ASR_MAX_AUDIO_SECONDS、EMOTION_ENGINE_ENABLED、EMOTION_ANALYZER_MODEL 等配置。
2. ASR_MODEL 本期默认 qwen3-asr-flash。
3. qwen3-asr-flash-realtime 只作为后续实时语音升级预留，本期不要强依赖 ASR_WS_URL。

验收标准：
1. 点击麦克风可以录音并转文字。
2. 转写文本自动进入输入框。
3. HRBP 直接批评时，员工变得防御。
4. HRBP 共情加事实时，员工开始软化。
5. HRBP 给出支持方案时，员工变得合作。
6. 前端能显示当前员工态度和变化原因。
7. 复盘日志能记录每轮情绪状态变化。
```

---

## 21. 参考资料

- 阿里云百炼实时语音识别文档说明，实时识别通过 WebSocket 接收音频流并转写，也支持情绪状态识别、热词、时间戳等能力。当前文档作为后续实时升级参考。  
  https://help.aliyun.com/zh/model-studio/real-time-speech-recognition-user-guide

- Qwen-ASR-Realtime Server Events 文档说明了实时转写中的 `conversation.item.input_audio_transcription.text` 与 `conversation.item.input_audio_transcription.completed` 等事件，以及事件中可包含 `emotion` 字段。当前阶段仅作为后续实时升级参考。  
  https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-server-events
