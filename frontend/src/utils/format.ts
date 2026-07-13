import type { EmployeeProfile, EmployeeRecord, StepKey } from '../types/domain';

export const STEP_KEYS: StepKey[] = ['profile', 'intent', 'simulation', 'guidance', 'rehearsal', 'report'];

export const STEP_LABELS: Record<StepKey, string> = {
  profile: 'Profile',
  intent: 'Intent',
  simulation: '人格与诉求',
  guidance: 'Guidance',
  rehearsal: 'Rehearsal',
  report: 'Report',
};

export const DEFAULT_PROFILE_TEXT = '';

export function safeList<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value.filter(Boolean) as T[]) : [];
}

export function valueToText(value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const obj = item as Record<string, unknown>;
          return String(obj.description ?? obj.name ?? obj.text ?? '').trim();
        }
        return String(item).trim();
      })
      .filter(Boolean)
      .join(' / ');
  }
  if (typeof value === 'object') return '';
  return String(value).trim();
}

export function firstText(values: unknown[], fallback = '—'): string {
  for (const value of values) {
    const text = valueToText(value);
    if (text) return text;
  }
  return fallback;
}

export function profileFromEmployeeRecord(record: EmployeeRecord | null): EmployeeProfile | null {
  if (!record) return null;
  const p = record.profile || {};
  return {
    employee_id: record.employee_id ?? p.employee_id,
    name: record.name ?? p.name,
    employee_alias: p.employee_alias ?? record.employee_alias ?? record.name,
    role: p.role ?? record.role,
    department: p.department ?? record.department,
    level: p.level,
    reporting_line: p.reporting_line ?? (record.manager ? `汇报给 ${record.manager}` : null),
    performance_rating: p.performance_rating,
    review_cycle: p.review_cycle,
    conversation_topic: p.conversation_topic,
    key_goals: p.key_goals ?? [],
    facts: p.facts ?? [],
    past_ratings: p.past_ratings ?? [],
    historical_feedback: p.historical_feedback ?? [],
    management_actions: p.management_actions ?? [],
    employee_status_summary: p.employee_status_summary,
    sensitive_constraints: p.sensitive_constraints ?? {},
    source_profile_text: p.source_profile_text ?? record.profile_text ?? null,
  };
}

export function employeeRecordText(record: EmployeeRecord | null): string {
  if (!record) return '';
  if (record.profile_text && String(record.profile_text).trim()) return String(record.profile_text).trim();
  const p = profileFromEmployeeRecord(record) || {};
  const rows: Array<[string, unknown]> = [
    ['工号', record.employee_id],
    ['姓名', record.name],
    ['员工代称', p.employee_alias],
    ['岗位', p.role],
    ['部门', p.department],
    ['职级', p.level],
    ['汇报关系', p.reporting_line],
    ['当前绩效评级', p.performance_rating],
    ['考核周期', p.review_cycle],
    ['本次谈话主题', p.conversation_topic],
    ['关键目标', p.key_goals],
    ['事实', p.facts],
    ['历史反馈', p.historical_feedback],
    ['管理动作', p.management_actions],
    ['员工状态', p.employee_status_summary],
  ];
  return rows
    .map(([label, value]) => [label, valueToText(value)] as const)
    .filter(([, value]) => value)
    .map(([label, value]) => `${label}：${value}`)
    .join('\n');
}

export function composeProfileText(_selectedEmployee: EmployeeRecord | null, manualText: string): string {
  return manualText.trim();
}

export function profileRows(profile: EmployeeProfile | null): Array<[string, string, string]> {
  if (!profile) return [];
  const p = profile;
  const sensitive = Object.values(p.sensitive_constraints || {})
    .map((x) => (x && typeof x === 'object' ? (x as { status?: string }).status : x))
    .filter(Boolean);
  const rows: Array<[string, string, unknown]> = [
    ['#', '工号', p.employee_id],
    ['NM', '姓名', p.name],
    ['AL', '员工代称', p.employee_alias],
    ['RL', '岗位', p.role],
    ['▦', '部门', p.department],
    ['LV', '职级', p.level],
    ['↗', '汇报关系', p.reporting_line],
    ['◎', '当前绩效评级', p.performance_rating],
    ['□', '考核周期', p.review_cycle],
    ['◇', '本次谈话主题', p.conversation_topic],
    ['GO', '关键目标', p.key_goals],
    ['✓', '完成情况', p.facts],
    ['↺', '历史反馈', p.historical_feedback],
    ['MA', '管理动作', p.management_actions],
    ['ST', '员工状态', p.employee_status_summary],
    ['SC', '敏感约束', sensitive],
  ];
  return rows
    .map(([icon, label, value]) => [icon, label, valueToText(value)] as [string, string, string])
    .filter(([, , value]) => Boolean(value));
}

export function inferStepFromState(stage?: string): StepKey {
  if (stage === 'report_ready') return 'report';
  if (stage === 'rehearsal') return 'rehearsal';
  if (stage === 'guidance_ready') return 'rehearsal';
  if (stage === 'setup_ready') return 'guidance';
  if (stage === 'profile_ready') return 'intent';
  return 'profile';
}

export function getApiBase(): string {
  const injected = window.__HR_AGENT_API_BASE;
  const env = import.meta.env.VITE_API_BASE as string | undefined;
  const fallback = '/api/v1';
  return (injected || env || fallback).replace(/\/$/, '');
}
