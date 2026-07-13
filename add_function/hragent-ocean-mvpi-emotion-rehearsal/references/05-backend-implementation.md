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
