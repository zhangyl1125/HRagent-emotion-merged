export type StepKey = 'profile' | 'intent' | 'simulation' | 'guidance' | 'rehearsal' | 'report';

export type SessionStage = 'created' | 'profile_ready' | 'setup_ready' | 'guidance_ready' | 'rehearsal' | 'report_ready' | 'ended';

export interface EmployeeProfile {
  employee_id?: string | null;
  name?: string | null;
  employee_alias?: string | null;
  role?: string | null;
  department?: string | null;
  level?: string | null;
  reporting_line?: string | null;
  performance_rating?: string | null;
  review_cycle?: string | null;
  conversation_topic?: string | null;
  key_goals?: unknown[] | string | null;
  facts?: unknown[] | string | null;
  past_ratings?: unknown[] | string | null;
  historical_feedback?: unknown[] | string | null;
  management_actions?: unknown[] | string | null;
  employee_status_summary?: string | null;
  sensitive_constraints?: Record<string, { status?: string | null } | string | null> | null;
  source_profile_text?: string | null;
  [key: string]: unknown;
}

export interface EmployeeRecord {
  employee_id?: string | null;
  name?: string | null;
  employee_alias?: string | null;
  role?: string | null;
  department?: string | null;
  manager?: string | null;
  profile?: EmployeeProfile | null;
  profile_text?: string | null;
  [key: string]: unknown;
}

export interface EmployeeSearchResponse {
  database?: string;
  items: EmployeeRecord[];
}

export interface IntentOption {
  id: string;
  name?: string;
  business_goal?: string;
  expected_outcome?: string;
  red_lines?: string[];
  employee_agent_hint?: string;
  coach_focus?: string[];
  [key: string]: unknown;
}

export interface PersonaOption {
  id: string;
  name?: string;
  profile_short?: string;
  profile_prompt?: string;
  reply_style?: {
    classic_lines?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface DifficultyOption {
  id: string;
  name?: string;
  description?: string;
  [key: string]: unknown;
}

export interface SetupOptions {
  intents: IntentOption[];
  default_intent?: string | null;
  personas: PersonaOption[];
  difficulties: DifficultyOption[];
  default_difficulty?: string | null;
  motives: MotiveOption[];
  emotion_anchors: EmotionAnchor[];
  default_big_five?: BigFivePersonality | null;
  motive_recommendations?: Record<string, MotiveRecommendation>;
  default_motive_recommendation?: MotiveRecommendation | null;
}

export interface IntentResult {
  intent_id?: string;
  id?: string;
  name?: string;
  [key: string]: unknown;
}

export interface ConversationTurn {
  speaker?: string;
  text?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}


export type EmployeeAttitude =
  | 'calm_neutral'
  | 'guarded_hesitant'
  | 'defensive_resistant'
  | 'frustrated_pushback'
  | 'silent_withdrawn'
  | 'reflective_softening'
  | 'cooperative_constructive';

export interface EmotionState {
  current_attitude: EmployeeAttitude;
  previous_attitude?: EmployeeAttitude | null;
  intensity: number;
  transition_reason: string;
  interview_purpose?: string;
  primary_motivation?: string;
  secondary_motivation?: string;
  primary_satisfaction?: number;
  secondary_satisfaction?: number;
  total_satisfaction?: number;
  emotion_band?: string;
  emotion_description?: string;
  last_primary_delta?: number;
  last_secondary_delta?: number;
  turn_index: number;
  current_vad?: VADVector;
  current_anchor_id?: string | null;
  transition_strategy?: 'expected_value' | 'maximum_probability' | 'sampling';
  last_reason_summary?: string | null;
  reply_emotion_guidance?: string | null;
  has_manager_response?: boolean;
  updated_at?: string;
}

export interface MotivationState {
  primary_motive_id?: string | null;
  secondary_motive_ids?: string[];
  primary_score?: number;
  secondary_scores?: Record<string, number>;
  total_satisfaction?: number;
  last_change_reason?: string | null;
  has_manager_response?: boolean;
  updated_at?: string;
}

export interface EmotionSignal {
  user_text_emotion?: string | null;
  audio_emotion?: string | null;
  empathy?: number;
  clarity?: number;
  specificity?: number;
  respectfulness?: number;
  pressure?: number;
  support_plan?: number;
  objective_evidence?: number;
  placement_support?: number;
  recognition?: number;
  growth_path?: number;
  compensation_or_reward?: number;
  red_line_hit?: boolean;
  analysis_reason?: string;
  primary_delta?: number;
  secondary_delta?: number;
  likely_employee_reaction?: 'escalate' | 'soften' | 'withdraw' | 'stay';
  risk_flags?: string[];
}

export interface ConversationEmotionLog {
  turn_index: number;
  hrbp_text: string;
  input_mode?: string;
  audio_emotion?: string | null;
  employee_attitude_before: EmployeeAttitude;
  employee_attitude_after: EmployeeAttitude;
  intensity: number;
  transition_reason: string;
  employee_reply?: string | null;
  signal?: EmotionSignal | null;
  vad_before?: VADVector | null;
  vad_after?: VADVector | null;
  emotion_anchor_before?: string | null;
  emotion_anchor_after?: string | null;
  motivation_before?: MotivationState | null;
  motivation_after?: MotivationState | null;
  created_at?: string;
}

export interface AsrTranscribeResponse {
  text: string;
  audio_emotion?: string | null;
  duration_seconds?: number;
  provider?: string;
}

export interface RehearsalMessageOptions {
  inputMode?: 'text' | 'voice_asr';
  audioEmotion?: string | null;
}

export interface RehearsalRuntimeContext {
  runtime_notes?: string[];
  persona_override?: string | null;
  active_persona_id?: string | null;
  active_difficulty_id?: string | null;
  initial_persona_id?: string | null;
  initial_difficulty_id?: string | null;
  updated_at?: string;
  [key: string]: unknown;
}

export interface RehearsalContextUpdatePayload {
  runtime_note?: string | null;
  runtime_notes?: string[] | string | null;
  persona_override?: string | null;
  persona_id?: string | null;
  difficulty_id?: string | null;
  clear_context?: boolean;
}

export interface SessionState {
  session_id: string;
  stage: SessionStage;
  run_mode?: string;
  employee_profile?: EmployeeProfile | null;
  intent?: IntentResult | null;
  persona?: PersonaOption | null;
  difficulty?: DifficultyOption | null;
  personality?: BigFivePersonality | null;
  motivation?: MotivationState | null;
  setup_ready?: boolean;
  guidance_report_id?: string | null;
  coach_report_id?: string | null;
  rehearsal_context?: RehearsalRuntimeContext | null;
  emotion_state?: EmotionState | null;
  emotion_log?: ConversationEmotionLog[];
  conversation?: ConversationTurn[];
  user_turn_count?: number;
  max_user_turns?: number;
  warnings?: string[];
  [key: string]: unknown;
}

export interface DocumentRecord {
  document_id?: string;
  parsed_text?: string;
  [key: string]: unknown;
}

export interface GuidanceReport {
  session_id?: string;
  intent_id?: string;
  purpose?: string | null;
  opening_suggestion?: string | null;
  risk_preview?: string[] | null;
  response_strategies?: string[] | null;
  safer_phrases?: string[] | null;
  disclaimer?: string | null;
  [key: string]: unknown;
}

export type WorkflowStreamStatus = 'idle' | 'streaming' | 'ready' | 'partial_error';
export type DraftSectionStatus = 'idle' | 'generating' | 'done' | 'error';
export type CoachTaskStatus = 'idle' | 'running' | 'done' | 'error';

export type GuidanceSectionKey = 'purpose' | 'opening_suggestion' | 'risk_preview' | 'response_strategies' | 'safer_phrases';

export interface GuidanceSectionDraft {
  key: GuidanceSectionKey;
  title: string;
  text: string;
  status: DraftSectionStatus;
  error?: string | null;
}

export interface CoachReport {
  overall_score?: number;
  summary?: string;
  key_strengths?: string[];
  key_improvements?: string[];
  top_risks?: Array<{ explanation?: string; category?: string } | string>;
  better_phrases?: Array<{ suggestion?: string } | string>;
  [key: string]: unknown;
}

export type CoachReportSectionKey = 'summary_score' | 'risks' | 'strengths_improvements' | 'better_phrases' | 'next_step';

export interface CoachSectionDraft {
  key: CoachReportSectionKey;
  title: string;
  text: string;
  status: DraftSectionStatus;
  error?: string | null;
}

export interface CoachTaskDraft {
  task_id: string;
  task_name: string;
  status: CoachTaskStatus;
  summary?: string;
  score?: number | null;
  error?: string | null;
}

export interface StreamEvent<T = Record<string, unknown>> {
  event: string;
  data: T;
}

export interface BigFivePersonality {
  openness: number;
  conscientiousness: number;
  extraversion: number;
  agreeableness: number;
  neuroticism: number;
}

export interface MotiveOption {
  id: string;
  name?: string;
  dimension?: string;
  description?: string;
  examples?: string[];
  [key: string]: unknown;
}

export interface VADVector {
  valence: number;
  arousal: number;
  dominance: number;
}

export interface EmotionAnchor {
  id: string;
  name?: string;
  description?: string;
  vad: VADVector;
  [key: string]: unknown;
}

export interface MotiveRecommendation {
  primary_motive_id?: string;
  secondary_motive_ids?: string[];
}
