import type { EmotionState, EmployeeAttitude } from '../../types/domain';

const attitudeLabels: Record<EmployeeAttitude, string> = {
  calm_neutral: '平静中立',
  guarded_hesitant: '谨慎犹豫',
  defensive_resistant: '防御抵触',
  frustrated_pushback: '不满反驳',
  silent_withdrawn: '沉默退缩',
  reflective_softening: '开始反思',
  cooperative_constructive: '合作建设',
};

const reasonLabels: Record<string, string> = {
  initial_state: '初始状态',
  no_significant_change: '本轮话术影响较小，员工态度保持稳定。',
  risk_flags_detected: '话术中出现低尊重或高风险表达，员工防御增强。',
  high_pressure_low_empathy: '压力较高且共情不足，员工更容易抵触。',
  low_respectfulness: '表达尊重感不足，员工态度转为防御。',
  employee_likely_to_withdraw: '对话压力让员工倾向收缩回应。',
  concrete_support_plan: '给出具体支持方案，员工开始软化。',
  empathy_with_specific_evidence: '兼顾理解和事实，员工更愿意继续讨论。',
  softening_signal: '话术释放合作信号，员工态度有所缓和。',
  satisfaction_rising: '主辅诉求满足度上升，员工更愿意进入讨论。',
  satisfaction_dropping: '主辅诉求满足度下降，员工防御增强。',
};

const motivationLabels: Record<string, string> = {
  commerce: '收益回报',
  power: '权限发展',
  recognition: '认可价值',
  affiliation: '团队归属',
  security: '安全稳定',
  hedonism: '工作舒适度',
};

const purposeLabels: Record<string, string> = {
  motivation: '激励型',
  improvement: '改进型',
  exit: '退出型',
  motivation_improvement: '激励+改进',
  improvement_exit: '改进+退出',
};

function displayLabel(attitude?: EmployeeAttitude | null): string {
  if (!attitude) return '未开始';
  return attitudeLabels[attitude] || attitude;
}

function displayMotivation(value?: string | null): string {
  if (!value) return '未设置';
  return motivationLabels[value] || value;
}

function signed(value?: number | null): string {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric === 0) return '0';
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(1)}`;
}

export function EmotionBadge({ emotionState }: { emotionState?: EmotionState | null }) {
  const attitude = emotionState?.current_attitude;
  const intensity = Math.max(0, Math.min(100, Number(emotionState?.intensity ?? 0)));
  const total = Math.max(0, Math.min(100, Number(emotionState?.total_satisfaction ?? 0)));
  const primary = Math.max(0, Math.min(100, Number(emotionState?.primary_satisfaction ?? 0)));
  const secondary = Math.max(0, Math.min(100, Number(emotionState?.secondary_satisfaction ?? 0)));
  const reason = reasonLabels[emotionState?.transition_reason || ''] || emotionState?.transition_reason || '等待第一轮对话后更新。';
  const purpose = emotionState?.interview_purpose ? (purposeLabels[emotionState.interview_purpose] || emotionState.interview_purpose) : '未设置';

  return (
    <section className={`emotion-badge attitude-${attitude || 'empty'}`} aria-label="员工态度状态">
      <div className="emotion-badge-head">
        <span>员工态度</span>
        <strong>{displayLabel(attitude)}</strong>
      </div>
      <div className="emotion-meter" aria-label={`态度强度 ${intensity}`}>
        <span style={{ width: `${intensity}%` }} />
      </div>
      <div className="emotion-badge-meta">
        <span>强度 {intensity}/100</span>
        {emotionState?.previous_attitude && <span>上一轮 {displayLabel(emotionState.previous_attitude)}</span>}
      </div>
      <p>{reason}</p>
      {emotionState?.emotion_description && <p>{emotionState.emotion_description}</p>}
      <div className="motivation-score-card" aria-label="员工诉求满足度">
        <div><span>面谈目的</span><strong>{purpose}</strong></div>
        <div><span>总满足度</span><strong>{total.toFixed(1)}/100</strong></div>
        <div className="emotion-meter compact"><span style={{ width: `${total}%` }} /></div>
        <div><span>主诉求 · {displayMotivation(emotionState?.primary_motivation)}</span><strong>{primary.toFixed(1)} <em>{signed(emotionState?.last_primary_delta)}</em></strong></div>
        <div><span>辅诉求 · {displayMotivation(emotionState?.secondary_motivation)}</span><strong>{secondary.toFixed(1)} <em>{signed(emotionState?.last_secondary_delta)}</em></strong></div>
      </div>
    </section>
  );
}
