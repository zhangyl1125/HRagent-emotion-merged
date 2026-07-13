import { createContext, PropsWithChildren, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  BigFivePersonality,
  CoachReport,
  CoachReportSectionKey,
  CoachSectionDraft,
  CoachTaskDraft,
  ConversationTurn,
  EmployeeProfile,
  EmployeeRecord,
  GuidanceReport,
  GuidanceSectionDraft,
  GuidanceSectionKey,
  MotiveRecommendation,
  EmotionState,
  RehearsalContextUpdatePayload,
  RehearsalMessageOptions,
  WorkflowStreamStatus,
  SessionState,
  SetupOptions,
} from '../types/domain';
import {
  composeProfileText,
  DEFAULT_PROFILE_TEXT,
  employeeRecordText,
  getApiBase,
  profileFromEmployeeRecord,
} from '../utils/format';

interface ToastState {
  message: string;
  type: 'ok' | 'error';
}

interface SetupSnapshot {
  profile?: EmployeeProfile | null;
  intentId?: string | null;
  personaId?: string | null;
  difficultyId?: string | null;
  personality?: BigFivePersonality | null;
  primaryMotiveId?: string | null;
  secondaryMotiveIds?: string[] | null;
}

interface WorkflowContextValue {
  apiBase: string;
  sessionId: string | null;
  session: SessionState | null;
  sessions: SessionState[];
  options: SetupOptions;
  profileText: string;
  selectedFile: File | null;
  employeeResults: EmployeeRecord[];
  selectedEmployee: EmployeeRecord | null;
  selectedIntentId: string | null;
  selectedPersonaId: string | null;
  selectedDifficultyId: string | null;
  selectedPersonality: BigFivePersonality;
  selectedPrimaryMotiveId: string | null;
  selectedSecondaryMotiveIds: string[];
  guidanceReport: GuidanceReport | null;
  guidanceSections: GuidanceSectionDraft[];
  guidanceStatus: WorkflowStreamStatus;
  coachReport: CoachReport | null;
  reportStatus: WorkflowStreamStatus;
  coachTasks: CoachTaskDraft[];
  coachSections: CoachSectionDraft[];
  liveConversation: ConversationTurn[] | null;
  rehearsalStreaming: boolean;
  loading: { active: boolean; text: string };
  toast: ToastState | null;
  displayedProfile: EmployeeProfile | null;
  setProfileText: (text: string) => void;
  setSelectedFile: (file: File | null) => void;
  setSelectedIntentId: (id: string) => void;
  setSelectedPersonaId: (id: string) => void;
  setSelectedDifficultyId: (id: string) => void;
  setSelectedPersonality: (personality: BigFivePersonality) => void;
  updatePersonalityDimension: (dimension: keyof BigFivePersonality, value: number) => void;
  setSelectedPrimaryMotiveId: (id: string) => void;
  setSelectedSecondaryMotiveIds: (ids: string[]) => void;
  bootstrap: () => Promise<void>;
  refreshSession: () => Promise<SessionState | null>;
  refreshSessionList: () => Promise<SessionState[]>;
  switchSession: (sessionId: string) => Promise<SessionState | null>;
  lookupEmployee: (query: string) => Promise<void>;
  selectEmployee: (record: EmployeeRecord) => void;
  confirmProfile: () => Promise<void>;
  confirmIntent: () => Promise<void>;
  confirmPersona: () => Promise<void>;
  confirmSimulation: () => Promise<void>;
  ensureGuidance: () => Promise<void>;
  startNewSession: () => Promise<SessionState>;
  deleteSession: (sessionId: string) => Promise<SessionState | null>;
  updateRehearsalContext: (payload: RehearsalContextUpdatePayload) => Promise<SessionState | null>;
  sendMessage: (message: string, options?: RehearsalMessageOptions) => Promise<void>;
  endRehearsal: () => Promise<void>;
  ensureReport: () => Promise<void>;
  exportReport: () => void;
  showToast: (message: string, type?: 'ok' | 'error') => void;
}

const DEFAULT_BIG_FIVE: BigFivePersonality = {
  openness: 50,
  conscientiousness: 50,
  extraversion: 50,
  agreeableness: 50,
  neuroticism: 50,
};
const emptyOptions: SetupOptions = { intents: [], personas: [], difficulties: [], motives: [], emotion_anchors: [], default_big_five: DEFAULT_BIG_FIVE };
const guidanceSectionSeeds: Array<{ key: GuidanceSectionKey; title: string }> = [
  { key: 'purpose', title: '沟通目标' },
  { key: 'opening_suggestion', title: '开场建议' },
  { key: 'risk_preview', title: '风险提醒' },
  { key: 'response_strategies', title: '应对策略' },
  { key: 'safer_phrases', title: '推荐话术' },
];
const coachTaskSeeds: Array<{ task_id: string; task_name: string }> = [
  { task_id: 'rubric_evaluation', task_name: 'Rubric 综合评估' },
  { task_id: 'emotion_evaluation', task_name: '情绪承接评估' },
  { task_id: 'performance_evaluation', task_name: '绩效反馈质量评估' },
  { task_id: 'redline_check', task_name: '话术红线检测' },
];
const coachSectionSeeds: Array<{ key: CoachReportSectionKey; title: string }> = [
  { key: 'summary_score', title: '综合结论与评分' },
  { key: 'risks', title: '风险提示' },
  { key: 'strengths_improvements', title: '优势与待改进' },
  { key: 'better_phrases', title: '建议话术' },
  { key: 'next_step', title: '下一步建议' },
];
const WorkflowContext = createContext<WorkflowContextValue | null>(null);

function createGuidanceSections(status: GuidanceSectionDraft['status'] = 'idle'): GuidanceSectionDraft[] {
  return guidanceSectionSeeds.map((section) => ({ ...section, text: '', status, error: null }));
}

function createCoachTasks(status: CoachTaskDraft['status'] = 'idle'): CoachTaskDraft[] {
  return coachTaskSeeds.map((task) => ({ ...task, status, summary: '', score: null, error: null }));
}

function createCoachSections(status: CoachSectionDraft['status'] = 'idle'): CoachSectionDraft[] {
  return coachSectionSeeds.map((section) => ({ ...section, text: '', status, error: null }));
}

function asGuidanceSectionKey(value: unknown): GuidanceSectionKey | null {
  return typeof value === 'string' && guidanceSectionSeeds.some((section) => section.key === value) ? value as GuidanceSectionKey : null;
}

function asCoachSectionKey(value: unknown): CoachReportSectionKey | null {
  return typeof value === 'string' && coachSectionSeeds.some((section) => section.key === value) ? value as CoachReportSectionKey : null;
}

function clampPersonalityScore(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 50;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function normalizeBigFive(value?: Partial<BigFivePersonality> | null): BigFivePersonality {
  return {
    openness: clampPersonalityScore(value?.openness ?? DEFAULT_BIG_FIVE.openness),
    conscientiousness: clampPersonalityScore(value?.conscientiousness ?? DEFAULT_BIG_FIVE.conscientiousness),
    extraversion: clampPersonalityScore(value?.extraversion ?? DEFAULT_BIG_FIVE.extraversion),
    agreeableness: clampPersonalityScore(value?.agreeableness ?? DEFAULT_BIG_FIVE.agreeableness),
    neuroticism: clampPersonalityScore(value?.neuroticism ?? DEFAULT_BIG_FIVE.neuroticism),
  };
}

function samePersonality(left: BigFivePersonality | null | undefined, right: BigFivePersonality | null | undefined): boolean {
  return JSON.stringify(normalizeBigFive(left)) === JSON.stringify(normalizeBigFive(right));
}

function recommendationForIntent(options: SetupOptions, intentId: string | null | undefined): MotiveRecommendation | null {
  return (intentId ? options.motive_recommendations?.[intentId] : null) || options.default_motive_recommendation || null;
}

function sessionIntentId(state: SessionState | null): string | null {
  return state?.intent?.intent_id || state?.intent?.id || null;
}

function sessionPersonaId(state: SessionState | null): string | null {
  return state?.persona?.id || null;
}

function sessionDifficultyId(state: SessionState | null): string | null {
  return state?.difficulty?.id || null;
}

function sessionPrimaryMotiveId(state: SessionState | null): string | null {
  return state?.motivation?.primary_motive_id || null;
}

function sessionSecondaryMotiveIds(state: SessionState | null): string[] {
  return state?.motivation?.secondary_motive_ids?.filter(Boolean).slice(0, 2) || [];
}

function hasDownstreamProgress(state: SessionState | null): boolean {
  return Boolean(
    state?.intent ||
    state?.persona ||
    state?.difficulty ||
    state?.personality ||
    state?.motivation ||
    state?.setup_ready ||
    state?.guidance_report_id ||
    state?.coach_report_id ||
    state?.conversation?.length,
  );
}

function profileFingerprint(profile: EmployeeProfile | null | undefined): string {
  if (!profile) return '';
  const stable: Record<string, unknown> = {};
  Object.keys(profile)
    .filter((key) => key !== 'source_profile_text')
    .sort()
    .forEach((key) => {
      const value = profile[key];
      if (value !== undefined && value !== null && value !== '') stable[key] = value;
    });
  return JSON.stringify(stable);
}

function sameProfile(left: EmployeeProfile | null | undefined, right: EmployeeProfile | null | undefined): boolean {
  if (!left && !right) return true;
  if (!left || !right) return false;
  if (left.employee_id && right.employee_id) return left.employee_id === right.employee_id;
  return profileFingerprint(left) === profileFingerprint(right);
}

function friendlyErrorMessage(error: unknown): string {
  const err = error as Error & { name?: string };
  if (err?.name === 'AbortError') return '请求超时，请稍后重试。';
  const message = err?.message || String(error);
  if (message.includes('employee_profile_required_fields')) {
    return '员工信息还不完整，请先补充或重新确认员工档案。';
  }
  if (message.includes('setup 未完成')) {
    return '准备流程还未完成，请确认员工信息、意图、人格与诉求。';
  }
  return message;
}

const ACTIVE_SESSION_STORAGE_KEY = 'hr_agent_session_id';

function readActiveSessionId(): string | null {
  const tabSessionId = window.sessionStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  const legacySessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  if (legacySessionId) window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  return tabSessionId || legacySessionId;
}

function writeActiveSessionId(sessionId: string): void {
  window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
}

function clearActiveSessionId(): void {
  window.sessionStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
}

export function WorkflowProvider({ children }: PropsWithChildren) {
  const [apiBase] = useState(getApiBase());
  const [sessionId, setSessionId] = useState<string | null>(() => readActiveSessionId());
  const [session, setSession] = useState<SessionState | null>(null);
  const [sessions, setSessions] = useState<SessionState[]>([]);
  const [options, setOptions] = useState<SetupOptions>(emptyOptions);
  const [profileText, setProfileText] = useState(DEFAULT_PROFILE_TEXT);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [employeeResults, setEmployeeResults] = useState<EmployeeRecord[]>([]);
  const [selectedEmployee, setSelectedEmployee] = useState<EmployeeRecord | null>(null);
  const [selectedIntentId, setSelectedIntentIdState] = useState<string | null>(null);
  const [selectedPersonaId, setSelectedPersonaIdState] = useState<string | null>(null);
  const [selectedDifficultyId, setSelectedDifficultyIdState] = useState<string | null>(null);
  const [selectedPersonality, setSelectedPersonalityState] = useState<BigFivePersonality>(DEFAULT_BIG_FIVE);
  const [selectedPrimaryMotiveId, setSelectedPrimaryMotiveIdState] = useState<string | null>(null);
  const [selectedSecondaryMotiveIds, setSelectedSecondaryMotiveIdsState] = useState<string[]>([]);
  const [guidanceReport, setGuidanceReport] = useState<GuidanceReport | null>(null);
  const [guidanceSections, setGuidanceSections] = useState<GuidanceSectionDraft[]>(() => createGuidanceSections());
  const [guidanceStatus, setGuidanceStatus] = useState<WorkflowStreamStatus>('idle');
  const [coachReport, setCoachReport] = useState<CoachReport | null>(null);
  const [reportStatus, setReportStatus] = useState<WorkflowStreamStatus>('idle');
  const [coachTasks, setCoachTasks] = useState<CoachTaskDraft[]>(() => createCoachTasks());
  const [coachSections, setCoachSections] = useState<CoachSectionDraft[]>(() => createCoachSections());
  const [liveConversation, setLiveConversation] = useState<ConversationTurn[] | null>(null);
  const [rehearsalStreaming, setRehearsalStreaming] = useState(false);
  const [loading, setLoading] = useState({ active: false, text: '处理中...' });
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<number | null>(null);
  const bootstrapStarted = useRef(false);
  const freshSessionPromise = useRef<Promise<SessionState> | null>(null);
  const guidanceInFlight = useRef(false);
  const reportInFlight = useRef(false);

  const displayedProfile = selectedEmployee ? profileFromEmployeeRecord(selectedEmployee) : session?.employee_profile || null;
  const effectiveSelectedIntentId = selectedIntentId || sessionIntentId(session);
  const effectiveSelectedPersonaId = selectedPersonaId || sessionPersonaId(session);
  const effectiveSelectedDifficultyId = selectedDifficultyId || sessionDifficultyId(session);
  const effectiveSelectedPersonality = normalizeBigFive(selectedPersonality);
  const effectiveSelectedPrimaryMotiveId = selectedPrimaryMotiveId || sessionPrimaryMotiveId(session);
  const effectiveSelectedSecondaryMotiveIds = selectedSecondaryMotiveIds.length
    ? selectedSecondaryMotiveIds
    : sessionSecondaryMotiveIds(session);

  const clearDownstreamState = useCallback(() => {
    setGuidanceReport(null);
    setGuidanceSections(createGuidanceSections());
    setGuidanceStatus('idle');
    setCoachReport(null);
    setReportStatus('idle');
    setCoachTasks(createCoachTasks());
    setCoachSections(createCoachSections());
    setLiveConversation(null);
  }, []);
  const syncSimulationSelection = useCallback((state: SessionState | null, loadedOptions: SetupOptions = options) => {
    const recommendation = recommendationForIntent(loadedOptions, sessionIntentId(state));
    setSelectedPersonalityState(normalizeBigFive(state?.personality || loadedOptions.default_big_five));
    setSelectedPrimaryMotiveIdState(sessionPrimaryMotiveId(state) || recommendation?.primary_motive_id || null);
    const secondary = sessionSecondaryMotiveIds(state);
    setSelectedSecondaryMotiveIdsState(
      secondary.length
        ? secondary
        : recommendation?.secondary_motive_ids?.filter(Boolean).slice(0, 2) || [],
    );
  }, [options]);

  const applyRecommendation = useCallback((loadedOptions: SetupOptions, intentId: string | null, force = false) => {
    const recommendation = recommendationForIntent(loadedOptions, intentId);
    if (!recommendation) return;
    if (recommendation.primary_motive_id) {
      setSelectedPrimaryMotiveIdState((current) => force || !current ? recommendation.primary_motive_id || null : current);
    }
    const secondary = recommendation.secondary_motive_ids?.filter(Boolean).slice(0, 2) || [];
    if (secondary.length === 2) {
      setSelectedSecondaryMotiveIdsState((current) => force || current.length !== 2 ? secondary : current);
    }
  }, []);


  const resetWorkspaceState = useCallback(() => {
    setProfileText(DEFAULT_PROFILE_TEXT);
    setSelectedFile(null);
    setEmployeeResults([]);
    setSelectedEmployee(null);
    setSelectedIntentIdState(null);
    setSelectedPersonaIdState(null);
    setSelectedDifficultyIdState(null);
    setSelectedPersonalityState(normalizeBigFive(options.default_big_five));
    setSelectedPrimaryMotiveIdState(null);
    setSelectedSecondaryMotiveIdsState([]);
    clearDownstreamState();
  }, [clearDownstreamState, options.default_big_five]);

  const showToast = useCallback((message: string, type: 'ok' | 'error' = 'ok') => {
    setToast({ message, type });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4200);
  }, []);

  const rememberSession = useCallback((next: SessionState) => {
    setSessions((current) => {
      const merged = [next, ...current.filter((item) => item.session_id !== next.session_id)];
      return merged.slice(0, 100);
    });
  }, []);

  const refreshSessionList = useCallback(async (): Promise<SessionState[]> => {
    const loaded = await api.listSessions();
    setSessions(loaded);
    return loaded;
  }, []);

  const runTask = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<T> => {
    setLoading({ active: true, text: label });
    try {
      return await fn();
    } catch (error) {
      const err = error as Error & { name?: string };
      showToast(friendlyErrorMessage(error), 'error');
      throw error;
    } finally {
      setLoading({ active: false, text: '处理中...' });
    }
  }, [showToast]);

  const buildSetupSnapshot = useCallback((base: SessionState | null, overrides: SetupSnapshot = {}): SetupSnapshot => ({
    profile: overrides.profile !== undefined ? overrides.profile : base?.employee_profile || displayedProfile,
    intentId: overrides.intentId !== undefined ? overrides.intentId : selectedIntentId || sessionIntentId(base),
    personaId: overrides.personaId !== undefined ? overrides.personaId : selectedPersonaId || sessionPersonaId(base),
    difficultyId: overrides.difficultyId !== undefined ? overrides.difficultyId : selectedDifficultyId || sessionDifficultyId(base),
    personality: overrides.personality !== undefined ? overrides.personality : base?.personality || selectedPersonality,
    primaryMotiveId: overrides.primaryMotiveId !== undefined ? overrides.primaryMotiveId : selectedPrimaryMotiveId || sessionPrimaryMotiveId(base),
    secondaryMotiveIds: overrides.secondaryMotiveIds !== undefined ? overrides.secondaryMotiveIds : (selectedSecondaryMotiveIds.length ? selectedSecondaryMotiveIds : sessionSecondaryMotiveIds(base)),
  }), [displayedProfile, selectedDifficultyId, selectedIntentId, selectedPersonaId, selectedPersonality, selectedPrimaryMotiveId, selectedSecondaryMotiveIds]);

  const createSessionFromSetupSnapshot = useCallback(async (snapshot: SetupSnapshot): Promise<SessionState> => {
    const created = await api.createSession();
    writeActiveSessionId(created.session_id);
    setSessionId(created.session_id);

    let next = created;
    if (snapshot.profile) {
      next = await api.confirmProfile(created.session_id, snapshot.profile);
    }
    if (snapshot.intentId) {
      next = await api.confirmIntent(created.session_id, snapshot.intentId, null);
    }
    const hasSimulation = Boolean(snapshot.personality && snapshot.primaryMotiveId && snapshot.secondaryMotiveIds?.length === 2);
    const hasLegacyPersona = Boolean(snapshot.personaId && snapshot.difficultyId);
    if (snapshot.personality && snapshot.primaryMotiveId && snapshot.secondaryMotiveIds?.length === 2) {
      next = await api.confirmSimulation(created.session_id, normalizeBigFive(snapshot.personality), snapshot.primaryMotiveId, snapshot.secondaryMotiveIds);
    } else if (snapshot.personaId && snapshot.difficultyId) {
      next = await api.confirmPersona(created.session_id, snapshot.personaId, snapshot.difficultyId);
    }
    if (snapshot.profile && snapshot.intentId && (hasSimulation || hasLegacyPersona)) {
      next = await api.completeSetup(created.session_id);
    }

    setSession(next);
    rememberSession(next);
    syncSimulationSelection(next);
    clearDownstreamState();
    return next;
  }, [clearDownstreamState, rememberSession, syncSimulationSelection]);

  const beginFreshSessionFromSnapshot = useCallback((snapshot: SetupSnapshot) => {
    if (freshSessionPromise.current) return freshSessionPromise.current;
    setSession((current) => current ? {
      ...current,
      conversation: [],
      user_turn_count: 0,
      guidance_report_id: null,
      coach_report_id: null,
      setup_ready: false,
      stage: snapshot.profile ? 'profile_ready' : 'created',
    } : current);
    clearDownstreamState();

    const promise = createSessionFromSetupSnapshot(snapshot).catch((error) => {
      showToast(friendlyErrorMessage(error), 'error');
      throw error;
    });
    freshSessionPromise.current = promise;
    void promise.finally(() => {
      if (freshSessionPromise.current === promise) freshSessionPromise.current = null;
    });
    return promise;
  }, [clearDownstreamState, createSessionFromSetupSnapshot, showToast]);

  const setSelectedIntentId = useCallback((id: string) => {
    setSelectedIntentIdState((current) => {
      const previous = current || sessionIntentId(session);
      if (previous && previous !== id) clearDownstreamState();
      return id;
    });
    applyRecommendation(options, id, !session?.motivation);
  }, [applyRecommendation, clearDownstreamState, options, session]);

  const setSelectedPersonaId = useCallback((id: string) => {
    setSelectedPersonaIdState((current) => {
      const previous = current || sessionPersonaId(session);
      if (previous && previous !== id) clearDownstreamState();
      return id;
    });
  }, [clearDownstreamState, session]);

  const setSelectedDifficultyId = useCallback((id: string) => {
    setSelectedDifficultyIdState((current) => {
      const previous = current || sessionDifficultyId(session);
      if (previous && previous !== id) clearDownstreamState();
      return id;
    });
  }, [clearDownstreamState, session]);
  const setSelectedPersonality = useCallback((personality: BigFivePersonality) => {
    setSelectedPersonalityState(normalizeBigFive(personality));
  }, []);

  const updatePersonalityDimension = useCallback((dimension: keyof BigFivePersonality, value: number) => {
    setSelectedPersonalityState((current) => ({ ...current, [dimension]: clampPersonalityScore(value) }));
  }, []);

  const setSelectedPrimaryMotiveId = useCallback((id: string) => {
    setSelectedPrimaryMotiveIdState((current) => {
      if (current && current !== id) clearDownstreamState();
      return id;
    });
    setSelectedSecondaryMotiveIdsState((current) => current.filter((motiveId) => motiveId !== id).slice(0, 2));
  }, [clearDownstreamState]);

  const setSelectedSecondaryMotiveIds = useCallback((ids: string[]) => {
    const clean = ids.filter(Boolean).filter((id, index, array) => array.indexOf(id) === index).slice(0, 2);
    setSelectedSecondaryMotiveIdsState(clean);
    clearDownstreamState();
  }, [clearDownstreamState]);


  const ensureSession = useCallback(async (): Promise<SessionState> => {
    if (freshSessionPromise.current) {
      return await freshSessionPromise.current;
    }
    if (sessionId) {
      try {
        const loaded = await api.getSession(sessionId);
        setSession(loaded);
        rememberSession(loaded);
        syncSimulationSelection(loaded);
        return loaded;
      } catch {
        clearActiveSessionId();
        setSessionId(null);
      }
    }
    const created = await api.createSession();
    writeActiveSessionId(created.session_id);
    setSessionId(created.session_id);
    setSession(created);
    rememberSession(created);
    syncSimulationSelection(created);
    return created;
  }, [rememberSession, sessionId, syncSimulationSelection]);

  const startNewSession = useCallback(async (): Promise<SessionState> => {
    return await runTask('创建绩效反馈会话', async () => {
      const created = await api.createSession();
      writeActiveSessionId(created.session_id);
      setSessionId(created.session_id);
      setSession(created);
      rememberSession(created);
      resetWorkspaceState();
      return created;
    });
  }, [rememberSession, resetWorkspaceState, runTask]);

  const deleteSession = useCallback(async (targetSessionId: string): Promise<SessionState | null> => {
    return await runTask('删除会话', async () => {
      await api.deleteSession(targetSessionId);
      const remaining = sessions.filter((item) => item.session_id !== targetSessionId);
      if (targetSessionId !== sessionId) {
        setSessions(remaining);
        showToast('会话已删除');
        return session;
      }

      clearActiveSessionId();
      resetWorkspaceState();
      let next = remaining.length ? await api.getSession(remaining[0].session_id) : null;
      if (!next) next = await api.createSession();
      writeActiveSessionId(next.session_id);
      setSessionId(next.session_id);
      setSession(next);
      setSessions([next, ...remaining.filter((item) => item.session_id !== next.session_id)]);
      syncSimulationSelection(next);
      showToast('会话已删除');
      return next;
    });
  }, [resetWorkspaceState, runTask, session, sessionId, sessions, showToast, syncSimulationSelection]);

  const refreshSession = useCallback(async (): Promise<SessionState | null> => {
    const currentId = sessionId || readActiveSessionId();
    if (!currentId) return null;
    const loaded = await api.getSession(currentId);
    setSession(loaded);
    rememberSession(loaded);
    syncSimulationSelection(loaded);
    setLiveConversation(null);
    return loaded;
  }, [rememberSession, sessionId, syncSimulationSelection]);

  const loadSetupOptions = useCallback(async () => {
    if (options.intents.length) return options;
    const response = await api.setupOptions();
    const loaded: SetupOptions = {
      ...response,
      intents: response.intents || [],
      personas: response.personas || [],
      difficulties: response.difficulties || [],
      motives: response.motives || [],
      emotion_anchors: response.emotion_anchors || [],
    };
    setOptions(loaded);
    if (session?.personality) setSelectedPersonalityState(normalizeBigFive(session.personality));
    else if (loaded.default_big_five) setSelectedPersonalityState(normalizeBigFive(loaded.default_big_five));
    applyRecommendation(loaded, selectedIntentId || sessionIntentId(session) || loaded.default_intent || null, false);
    return loaded;
  }, [applyRecommendation, options, selectedIntentId, session]);

  const switchSession = useCallback(async (targetSessionId: string): Promise<SessionState | null> => {
    if (!targetSessionId || targetSessionId === sessionId) return session;
    return await runTask('切换会话', async () => {
      const loaded = await api.getSession(targetSessionId);
      writeActiveSessionId(loaded.session_id);
      setSessionId(loaded.session_id);
      setSession(loaded);
      rememberSession(loaded);
      resetWorkspaceState();
      syncSimulationSelection(loaded);
      setLiveConversation(null);
      return loaded;
    });
  }, [rememberSession, resetWorkspaceState, runTask, session, sessionId, syncSimulationSelection]);

  const bootstrap = useCallback(async () => {
    if (bootstrapStarted.current) return;
    bootstrapStarted.current = true;
    try {
      await runTask('载入工作台', async () => {
        const activeSession = await ensureSession();
        await refreshSessionList();
        const loadedOptions = await loadSetupOptions();
        syncSimulationSelection(activeSession, loadedOptions);
      });
    } finally {
      bootstrapStarted.current = false;
    }
  }, [ensureSession, loadSetupOptions, refreshSessionList, runTask, syncSimulationSelection]);

  const lookupEmployee = useCallback(async (query: string) => {
    await runTask('匹配员工信息', async () => {
      const safeQuery = query.trim();
      if (!safeQuery) throw new Error('请输入员工姓名或工号。');
      const params = new URLSearchParams({ limit: '10' });
      params.set('q', safeQuery);
      const result = await api.searchEmployees(params);
      setEmployeeResults(result.items || []);
      const single = result.items?.length === 1 ? result.items[0] : null;
      if (single) {
        const matchedProfile = profileFromEmployeeRecord(single);
        const changed = !sameProfile(matchedProfile, session?.employee_profile);
        setSelectedEmployee(single);
        setProfileText('');
        setSelectedFile(null);
        setEmployeeResults([]);
        if (changed) clearDownstreamState();
      } else {
        setSelectedEmployee(null);
      }
      if (!result.items?.length) throw new Error('未匹配到员工，请改用手动输入或上传资料。');
      showToast(single ? '已匹配员工信息' : '请选择匹配结果');
    });
  }, [clearDownstreamState, runTask, session?.employee_profile, showToast]);

  const selectEmployee = useCallback((record: EmployeeRecord) => {
    const matchedProfile = profileFromEmployeeRecord(record);
    const changed = !sameProfile(matchedProfile, session?.employee_profile);
    setSelectedEmployee(record);
    setProfileText('');
    setSelectedFile(null);
    setEmployeeResults([]);
    if (changed) clearDownstreamState();
    showToast(changed ? '员工信息已选择，确认后将开启新的会话。' : '员工信息已选择。');
  }, [clearDownstreamState, session?.employee_profile, showToast]);

  const confirmProfile = useCallback(async () => {
    await runTask('确认员工信息', async () => {
      const activeSession = await ensureSession();
      const baseText = composeProfileText(selectedEmployee, profileText);
      if (!baseText && !selectedFile && !selectedEmployee && !activeSession.employee_profile) {
        throw new Error('请先匹配员工、粘贴信息或上传参考资料。');
      }

      const selectedProfile = selectedEmployee ? profileFromEmployeeRecord(selectedEmployee) : null;
      const profileChanged = selectedProfile
        ? !sameProfile(selectedProfile, activeSession.employee_profile)
        : Boolean((baseText || selectedFile) && activeSession.employee_profile);
      const needsFreshSession = profileChanged && Boolean(activeSession.employee_profile || hasDownstreamProgress(activeSession));

      let parsedFileText = '';
      if (selectedFile) {
        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('session_id', activeSession.session_id);
        const record = await api.uploadDocument(formData);
        parsedFileText = record.parsed_text || '';
      }

      const supplementalText = [baseText, parsedFileText ? `上传资料补充：\n${parsedFileText}` : ''].filter(Boolean).join('\n\n');
      let updated: SessionState;

      if (selectedProfile) {
        const dbText = employeeRecordText(selectedEmployee);
        selectedProfile.source_profile_text = [
          dbText || selectedProfile.source_profile_text || '',
          supplementalText ? `补充背景：\n${supplementalText}` : '',
        ].filter(Boolean).join('\n\n');

        if (needsFreshSession) {
          updated = await beginFreshSessionFromSnapshot(buildSetupSnapshot(activeSession, { profile: selectedProfile }));
        } else {
          updated = await api.confirmProfile(activeSession.session_id, selectedProfile);
        }
      } else if (supplementalText) {
        if (needsFreshSession) {
          const snapshot = buildSetupSnapshot(activeSession, { profile: null });
          const targetSession = await beginFreshSessionFromSnapshot(snapshot);
          await api.uploadText(targetSession.session_id, supplementalText);
          updated = await api.getSession(targetSession.session_id);
          if (updated.employee_profile && snapshot.intentId && (
            (snapshot.personality && snapshot.primaryMotiveId && snapshot.secondaryMotiveIds?.length === 2)
            || (snapshot.personaId && snapshot.difficultyId)
          )) {
            updated = await api.completeSetup(targetSession.session_id);
          }
        } else {
          await api.uploadText(activeSession.session_id, supplementalText);
          updated = await api.getSession(activeSession.session_id);
        }
      } else {
        updated = activeSession;
      }

      if (!updated.employee_profile) throw new Error('未获得结构化员工信息。');
      setSession(updated);
      setEmployeeResults([]);
      setSelectedFile(null);
      if (supplementalText) setProfileText('');
      if (profileChanged) clearDownstreamState();
      showToast('员工信息已确认');
    });
  }, [beginFreshSessionFromSnapshot, buildSetupSnapshot, clearDownstreamState, ensureSession, profileText, runTask, selectedEmployee, selectedFile, showToast]);

  const confirmIntent = useCallback(async () => {
    await runTask('确认意图', async () => {
      const activeSession = await ensureSession();
      const intentId = selectedIntentId || sessionIntentId(activeSession);
      if (!intentId) throw new Error('请选择对话意图。');

      const currentIntentId = sessionIntentId(activeSession);
      const intentChanged = Boolean(currentIntentId && currentIntentId !== intentId);
      const needsFreshSession = intentChanged && hasDownstreamProgress(activeSession);
      const updated = needsFreshSession
        ? await beginFreshSessionFromSnapshot(buildSetupSnapshot(activeSession, { intentId }))
        : await api.confirmIntent(activeSession.session_id, intentId, profileText.trim() || null);

      setSession(updated);
      applyRecommendation(options, intentId, !activeSession.motivation);
      if (intentChanged) clearDownstreamState();
      showToast('意图已确认');
    });
  }, [applyRecommendation, beginFreshSessionFromSnapshot, buildSetupSnapshot, clearDownstreamState, ensureSession, options, profileText, runTask, selectedIntentId, showToast]);

  const confirmPersona = useCallback(async () => {
    await runTask('确认 Persona', async () => {
      const activeSession = await ensureSession();
      const personaId = selectedPersonaId || sessionPersonaId(activeSession);
      const difficultyId = selectedDifficultyId || sessionDifficultyId(activeSession);
      if (!personaId) throw new Error('请选择 Persona。');
      if (!difficultyId) throw new Error('请选择难度。');

      const currentPersonaId = sessionPersonaId(activeSession);
      const currentDifficultyId = sessionDifficultyId(activeSession);
      const personaChanged = Boolean(currentPersonaId && currentPersonaId !== personaId);
      const difficultyChanged = Boolean(currentDifficultyId && currentDifficultyId !== difficultyId);
      const needsFreshSession = (personaChanged || difficultyChanged) && hasDownstreamProgress(activeSession);

      const completed = needsFreshSession
        ? await beginFreshSessionFromSnapshot(buildSetupSnapshot(activeSession, { personaId, difficultyId }))
        : await api.confirmPersona(activeSession.session_id, personaId, difficultyId).then(() => api.completeSetup(activeSession.session_id));

      setSession(completed);
      if (personaChanged || difficultyChanged) clearDownstreamState();
      showToast('Persona 已确认');
    });
  }, [beginFreshSessionFromSnapshot, buildSetupSnapshot, clearDownstreamState, ensureSession, runTask, selectedDifficultyId, selectedPersonaId, showToast]);

  const confirmSimulation = useCallback(async () => {
    await runTask('确认人格与诉求', async () => {
      const activeSession = await ensureSession();
      const personality = normalizeBigFive(selectedPersonality);
      const primaryMotiveId = selectedPrimaryMotiveId || sessionPrimaryMotiveId(activeSession);
      const secondaryMotiveIds = (selectedSecondaryMotiveIds.length
        ? selectedSecondaryMotiveIds
        : sessionSecondaryMotiveIds(activeSession)).filter(Boolean).slice(0, 2);
      if (!primaryMotiveId) throw new Error('请选择主诉求。');
      if (secondaryMotiveIds.length !== 2) throw new Error('请选择两个辅诉求。');
      if (secondaryMotiveIds.includes(primaryMotiveId)) throw new Error('主诉求和辅诉求不能重复。');
      if (new Set(secondaryMotiveIds).size !== 2) throw new Error('两个辅诉求不能重复。');

      const personalityChanged = Boolean(activeSession.personality && !samePersonality(activeSession.personality, personality));
      const motiveChanged = Boolean(activeSession.motivation && (
        activeSession.motivation.primary_motive_id !== primaryMotiveId
        || JSON.stringify(activeSession.motivation.secondary_motive_ids || []) !== JSON.stringify(secondaryMotiveIds)
      ));
      const needsFreshSession = (personalityChanged || motiveChanged) && hasDownstreamProgress(activeSession);

      const completed = needsFreshSession
        ? await beginFreshSessionFromSnapshot(buildSetupSnapshot(activeSession, { personality, primaryMotiveId, secondaryMotiveIds }))
        : await api.confirmSimulation(activeSession.session_id, personality, primaryMotiveId, secondaryMotiveIds)
          .then(() => api.completeSetup(activeSession.session_id));

      setSession(completed);
      syncSimulationSelection(completed);
      if (personalityChanged || motiveChanged) clearDownstreamState();
      showToast('人格与诉求已确认');
    });
  }, [beginFreshSessionFromSnapshot, buildSetupSnapshot, clearDownstreamState, ensureSession, runTask, selectedPersonality, selectedPrimaryMotiveId, selectedSecondaryMotiveIds, showToast, syncSimulationSelection]);

  const ensureGuidance = useCallback(async () => {
    if (guidanceStatus === 'ready' || guidanceStatus === 'streaming' || guidanceInFlight.current) return;
    const activeSession = await ensureSession();
    if (!activeSession.setup_ready) {
      showToast('请先完成员工信息、意图、人格与诉求设置。', 'error');
      return;
    }
    guidanceInFlight.current = true;
    setGuidanceReport(null);
    setGuidanceSections(createGuidanceSections('generating'));
    setGuidanceStatus('streaming');
    const textByKey = Object.fromEntries(guidanceSectionSeeds.map((section) => [section.key, ''])) as Record<GuidanceSectionKey, string>;
    const patchSection = (key: GuidanceSectionKey, patch: Partial<GuidanceSectionDraft>) => {
      setGuidanceSections((current) => current.map((section) => section.key === key ? { ...section, ...patch } : section));
    };

    try {
      let completed = false;
      try {
        await api.streamGuidance(activeSession.session_id, (event, data) => {
          const key = asGuidanceSectionKey(data.key);
          if (event === 'section_start' && key) {
            patchSection(key, { title: String(data.title || key), status: 'generating', error: null });
          }
          if (event === 'delta' && key) {
            textByKey[key] += String(data.text || '');
            patchSection(key, { text: textByKey[key], status: 'generating', error: null });
          }
          if (event === 'section_done' && key) {
            patchSection(key, { status: 'done', error: null });
          }
          if (event === 'section_error' && key) {
            patchSection(key, { status: 'error', error: String(data.message || '该部分生成失败') });
          }
          if (event === 'done') {
            completed = true;
            if (data.complete === false) {
              setGuidanceStatus('partial_error');
              showToast('谈前指导部分生成失败，请重新生成。', 'error');
              return;
            }
            setSession((data.state as SessionState) || activeSession);
            setGuidanceReport((data.report as GuidanceReport) || null);
            setGuidanceStatus('ready');
          }
        });
      } catch {
        const report = await api.generateGuidance(activeSession.session_id);
        setGuidanceReport(report);
        const refreshed = await api.getSession(activeSession.session_id);
        setSession(refreshed);
        setGuidanceStatus('ready');
        showToast('流式生成中断，已使用普通模式完成谈前指导。');
        return;
      }
      if (!completed) throw new Error('谈前指导生成中断，请重新生成。');
    } catch (error) {
      setGuidanceStatus('partial_error');
      showToast(friendlyErrorMessage(error), 'error');
    } finally {
      guidanceInFlight.current = false;
    }
  }, [ensureSession, guidanceStatus, showToast]);

  const updateRehearsalContext = useCallback(async (payload: RehearsalContextUpdatePayload): Promise<SessionState | null> => {
    if (rehearsalStreaming) {
      showToast('员工正在回复中，请等本轮回复结束后再调整模拟设定。', 'error');
      return null;
    }
    return await runTask('更新模拟设定', async () => {
      const activeSession = await ensureSession();
      const updated = await api.updateRehearsalContext(activeSession.session_id, payload);
      setSession(updated);
      setLiveConversation(null);
      if (payload.persona_id) setSelectedPersonaIdState(payload.persona_id);
      if (payload.difficulty_id) setSelectedDifficultyIdState(payload.difficulty_id);
      setCoachReport(null);
      setReportStatus('idle');
      setCoachTasks(createCoachTasks());
      setCoachSections(createCoachSections());
      showToast(payload.clear_context ? '本轮动态模拟设定已清空' : '本轮模拟设定已更新');
      return updated;
    });
  }, [ensureSession, rehearsalStreaming, runTask, showToast]);

  const sendMessage = useCallback(async (message: string, options?: RehearsalMessageOptions) => {
    const text = message.trim();
    if (!text || rehearsalStreaming) return;

    let previousConversation: ConversationTurn[] | null = null;
    let activeSession: SessionState | null = null;
    setRehearsalStreaming(true);
    try {
      activeSession = await ensureSession();
      const base = liveConversation || activeSession.conversation || [];
      previousConversation = base;
      const streamId = `${activeSession.session_id}-${Date.now()}`;
      const managerTurn: ConversationTurn = { speaker: 'manager', text, metadata: { stream_id: `${streamId}-manager` } };
      const employeeTurn: ConversationTurn = { speaker: 'employee', text: '', metadata: { stream_id: `${streamId}-employee`, streaming: true } };
      let draft: ConversationTurn[] = [...base, managerTurn, employeeTurn];
      setLiveConversation(draft);
      let accumulated = '';

      const updateEmployeeDraft = () => {
        setLiveConversation((current) => {
          const source = current && current.length >= 2 ? current : draft;
          const next = [...source.slice(0, -1), {
            ...employeeTurn,
            text: accumulated,
            metadata: { ...employeeTurn.metadata },
          }];
          draft = next;
          return next;
        });
      };

      await api.streamRehearsalMessage(activeSession.session_id, text, options, (event, data) => {
        if (event === 'emotion.updated') {
          const emotionState = data.emotion_state as EmotionState | undefined;
          if (emotionState) {
            setSession((current) => current ? { ...current, emotion_state: emotionState } : current);
          }
        }
        if (event === 'employee_start') {
          updateEmployeeDraft();
        }
        if (event === 'delta') {
          accumulated += String(data.text || '');
          updateEmployeeDraft();
        }
        if (event === 'done') {
          const updated = (data.state as SessionState) || activeSession;
          setSession(updated);
          window.requestAnimationFrame(() => setLiveConversation(null));
        }
      });
    } catch (error) {
      let finalError: unknown = error;
      try {
        if (activeSession) {
          const refreshed = await api.getSession(activeSession.session_id);
          const previousLength = previousConversation?.length || 0;
          if ((refreshed.conversation || []).length > previousLength) {
            setSession(refreshed);
            setLiveConversation(null);
            return;
          }

          const updated = await api.sendRehearsalMessage(activeSession.session_id, text, options);
          setSession(updated);
          setLiveConversation(null);
          showToast('流式预演中断，已使用普通模式完成本轮回复。');
          return;
        }
      } catch (fallbackError) {
        finalError = fallbackError;
      }
      const err = finalError as Error & { name?: string };
      setLiveConversation(previousConversation);
      showToast(friendlyErrorMessage(finalError), 'error');
    } finally {
      setRehearsalStreaming(false);
    }
  }, [ensureSession, liveConversation, rehearsalStreaming, showToast]);

  const endRehearsal = useCallback(async () => {
    await runTask('结束预演', async () => {
      const activeSession = await ensureSession();
      const updated = await api.endRehearsal(activeSession.session_id);
      setSession(updated);
      setLiveConversation(null);
    });
  }, [ensureSession, runTask, session]);

  const ensureReport = useCallback(async () => {
    if (coachReport || reportStatus === 'streaming' || reportInFlight.current) return;
    const activeSession = await ensureSession();
    const managerTurns = (activeSession.conversation || []).filter((turn) => turn.speaker === 'manager');
    if (!managerTurns.length) {
      showToast('请先完成至少一轮多轮预演，再生成复盘报告。', 'error');
      return;
    }
    reportInFlight.current = true;
    setCoachReport(null);
    setCoachTasks(createCoachTasks('running'));
    setCoachSections(createCoachSections('generating'));
    setReportStatus('streaming');
    const sectionText = Object.fromEntries(coachSectionSeeds.map((section) => [section.key, ''])) as Record<CoachReportSectionKey, string>;
    const patchTask = (taskId: string, patch: Partial<CoachTaskDraft>) => {
      setCoachTasks((current) => current.map((task) => task.task_id === taskId ? { ...task, ...patch } : task));
    };
    const patchSection = (key: CoachReportSectionKey, patch: Partial<CoachSectionDraft>) => {
      setCoachSections((current) => current.map((section) => section.key === key ? { ...section, ...patch } : section));
    };

    try {
      let completed = false;
      try {
        await api.streamCoachReport(activeSession.session_id, (event, data) => {
          const taskId = typeof data.task_id === 'string' ? data.task_id : '';
          const sectionKey = asCoachSectionKey(data.key);
          if (event === 'task_start' && taskId) {
            patchTask(taskId, { task_name: String(data.task_name || taskId), status: 'running', error: null });
          }
          if (event === 'task_done' && taskId) {
            const result = (data.result || {}) as Record<string, unknown>;
            patchTask(taskId, {
              task_name: String(data.task_name || result.task_name || taskId),
              status: 'done',
              summary: String(result.summary || ''),
              score: typeof result.score === 'number' ? result.score : null,
              error: null,
            });
          }
          if (event === 'task_error' && taskId) {
            patchTask(taskId, { task_name: String(data.task_name || taskId), status: 'error', error: String(data.message || '该评估任务失败') });
          }
          if (event === 'section_start' && sectionKey) {
            patchSection(sectionKey, { title: String(data.title || sectionKey), status: 'generating', error: null });
          }
          if (event === 'section_delta' && sectionKey) {
            sectionText[sectionKey] += String(data.text || '');
            patchSection(sectionKey, { text: sectionText[sectionKey], status: 'generating', error: null });
          }
          if (event === 'section_done' && sectionKey) {
            patchSection(sectionKey, { status: 'done', error: null });
          }
          if (event === 'section_error' && sectionKey) {
            patchSection(sectionKey, { status: 'error', error: String(data.message || '该部分生成失败') });
          }
          if (event === 'done') {
            completed = true;
            if (data.complete === false) {
              setReportStatus('partial_error');
              showToast('复盘报告部分生成失败，请重新生成。', 'error');
              return;
            }
            setSession((data.state as SessionState) || activeSession);
            setCoachReport((data.report as CoachReport) || null);
            setReportStatus('ready');
          }
        });
      } catch (error) {
        throw error;
      }
      if (!completed) throw new Error('复盘报告生成中断，请重新生成。');
    } catch (error) {
      setReportStatus('partial_error');
      showToast(friendlyErrorMessage(error), 'error');
    } finally {
      reportInFlight.current = false;
    }
  }, [coachReport, ensureSession, reportStatus, showToast]);

  const exportReport = useCallback(() => window.print(), []);

  const value = useMemo<WorkflowContextValue>(() => ({
    apiBase,
    sessionId,
    session,
    sessions,
    options,
    profileText,
    selectedFile,
    employeeResults,
    selectedEmployee,
    selectedIntentId: effectiveSelectedIntentId,
    selectedPersonaId: effectiveSelectedPersonaId,
    selectedDifficultyId: effectiveSelectedDifficultyId,
    selectedPersonality: effectiveSelectedPersonality,
    selectedPrimaryMotiveId: effectiveSelectedPrimaryMotiveId,
    selectedSecondaryMotiveIds: effectiveSelectedSecondaryMotiveIds,
    guidanceReport,
    guidanceSections,
    guidanceStatus,
    coachReport,
    reportStatus,
    coachTasks,
    coachSections,
    liveConversation,
    rehearsalStreaming,
    loading,
    toast,
    displayedProfile,
    setProfileText,
    setSelectedFile,
    setSelectedIntentId,
    setSelectedPersonaId,
    setSelectedDifficultyId,
    setSelectedPersonality,
    updatePersonalityDimension,
    setSelectedPrimaryMotiveId,
    setSelectedSecondaryMotiveIds,
    bootstrap,
    refreshSession,
    refreshSessionList,
    switchSession,
    lookupEmployee,
    selectEmployee,
    confirmProfile,
    confirmIntent,
    confirmPersona,
    confirmSimulation,
    ensureGuidance,
    startNewSession,
    deleteSession,
    updateRehearsalContext,
    sendMessage,
    endRehearsal,
    ensureReport,
    exportReport,
    showToast,
  }), [
    apiBase,
    sessionId,
    session,
    sessions,
    options,
    profileText,
    selectedFile,
    employeeResults,
    selectedEmployee,
    effectiveSelectedIntentId,
    effectiveSelectedPersonaId,
    effectiveSelectedDifficultyId,
    effectiveSelectedPersonality,
    effectiveSelectedPrimaryMotiveId,
    effectiveSelectedSecondaryMotiveIds,
    guidanceReport,
    guidanceSections,
    guidanceStatus,
    coachReport,
    reportStatus,
    coachTasks,
    coachSections,
    liveConversation,
    rehearsalStreaming,
    loading,
    toast,
    displayedProfile,
    setSelectedIntentId,
    setSelectedPersonaId,
    setSelectedDifficultyId,
    setSelectedPersonality,
    updatePersonalityDimension,
    setSelectedPrimaryMotiveId,
    setSelectedSecondaryMotiveIds,
    bootstrap,
    refreshSession,
    refreshSessionList,
    switchSession,
    lookupEmployee,
    selectEmployee,
    confirmProfile,
    confirmIntent,
    confirmPersona,
    confirmSimulation,
    ensureGuidance,
    startNewSession,
    deleteSession,
    updateRehearsalContext,
    sendMessage,
    endRehearsal,
    ensureReport,
    exportReport,
    showToast,
  ]);

  return <WorkflowContext.Provider value={value}>{children}</WorkflowContext.Provider>;
}

export function useWorkflow() {
  const context = useContext(WorkflowContext);
  if (!context) throw new Error('useWorkflow must be used inside WorkflowProvider');
  return context;
}
