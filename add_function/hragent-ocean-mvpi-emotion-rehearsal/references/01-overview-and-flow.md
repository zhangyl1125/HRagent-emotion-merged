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
