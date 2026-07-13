---
name: hragent-ocean-mvpi-emotion-rehearsal
description: Use this skill when implementing or reviewing HRagent-05 features for OCEAN big-five sliders, MVPI primary/secondary employee motivations, persona selection, VAD/Markov emotion transitions, Employee Agent persona-aware replies, and Coach Report emotion/personality review. Load only the relevant references for the requested layer.
---

# HRagent-05 OCEAN + MVPI Dynamic Emotion Rehearsal

Use this skill for HRagent-05 work involving OCEAN 大五人格滑块, employee motivation, persona selection, dynamic emotion transition, rehearsal replies, or report review. Keep changes compatible with the existing HRagent-05 workflow and do not modify HRagent-06.

## Core Workflow

The target flow is:

```text
Employee profile -> Intent -> Motivation confirmation -> OCEAN sliders -> Persona selection -> Guidance -> Rehearsal -> Report
```

The runtime formula is:

```text
f(H, P, E_t) -> (E_{t+1}, R)
```

Where:

- `H`: conversation history.
- `P`: persona context, including OCEAN, selected Persona, primary/secondary motivation.
- `E_t`: current emotion state, including satisfaction, VAD, discrete emotion.
- `E_{t+1}`: next emotion state.
- `R`: employee reply.

## Reference Loading Guide

Read only the reference needed for the current task:

- Product scope, user flow, existing project integration: `references/01-overview-and-flow.md`
- Intent mapping and MVPI motivation rules: `references/02-intent-and-motivation.md`
- OCEAN slider labels, schemas, persona selection prompt/rules: `references/03-ocean-slider-persona.md`
- VAD/Markov emotion transition model and anti-jump rules: `references/04-emotion-vad-markov.md`
- Backend file plan, SessionState/API changes, prompts/config: `references/05-backend-implementation.md`
- Frontend types/API/PersonaStep/report rendering: `references/06-frontend-and-report.md`
- Tests, validation commands, phases, final acceptance checklist: `references/07-tests-validation-plan.md`

## Engineering Constraints

- Preserve existing API compatibility where the spec requires it.
- Do not make database migrations a hard dependency unless the user explicitly asks.
- Existing Persona configuration remains authoritative; OCEAN selects or supplements, it does not replace `personas.yaml`.
- LLM outputs must be schema-validated and have rule fallback.
- OCEAN is for communication simulation only; do not produce diagnosis, pathology labels, or formal HR/legal conclusions.
- Do not expose API keys or move secrets to frontend code.
- Keep frontend consistent with Bosch-style restrained UI.

## Implementation Order

1. Read current code before editing: `state.py`, `emotion.py`, `motivation.py`, `attitude_transition_engine.py`, `PersonaStep.tsx`, `domain.ts`, `client.ts`.
2. Add schemas and API fields compatibly.
3. Implement rule fallback before LLM selection.
4. Add or modify UI controls with stable dimensions and clear labels.
5. Connect rehearsal emotion transition and report output.
6. Validate backend compile/tests and frontend build according to `references/07-tests-validation-plan.md`.
