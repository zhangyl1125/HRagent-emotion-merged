import { ScoreTile } from '../../components/ScoreTile';
import { useWorkflow } from '../../context/WorkflowContext';
import type { CoachSectionDraft, CoachTaskDraft, ConversationEmotionLog, EmployeeAttitude, WorkflowStreamStatus } from '../../types/domain';
import { safeList } from '../../utils/format';

interface ReportTaskResult {
  task_id?: string;
  task_name?: string;
  score?: number | null;
  dimension_scores?: Array<{ id?: string; name?: string; score?: number | null }>;
}

function reportStatusText(status: WorkflowStreamStatus) {
  if (status === 'ready') return '已生成';
  if (status === 'streaming') return '生成中';
  if (status === 'partial_error') return '部分失败';
  return '待生成';
}

function reportStatusTone(status: WorkflowStreamStatus) {
  if (status === 'ready') return 'success';
  if (status === 'streaming') return 'info';
  if (status === 'partial_error') return 'danger';
  return 'neutral';
}

function taskStatusText(task: CoachTaskDraft) {
  if (task.status === 'done') return '已完成';
  if (task.status === 'error') return '失败';
  if (task.status === 'running') return '分析中';
  return '等待中';
}

function sectionStatusText(section: CoachSectionDraft) {
  if (section.status === 'done') return '已完成';
  if (section.status === 'error') return '失败';
  if (section.status === 'generating') return '生成中';
  return '等待中';
}

const attitudeLabels: Record<EmployeeAttitude, string> = {
  calm_neutral: '平静中立',
  guarded_hesitant: '谨慎犹豫',
  defensive_resistant: '防御抵触',
  frustrated_pushback: '不满反驳',
  silent_withdrawn: '沉默退缩',
  reflective_softening: '开始反思',
  cooperative_constructive: '合作建设',
};

function attitudeText(attitude?: EmployeeAttitude | null) {
  if (!attitude) return '未记录';
  return attitudeLabels[attitude] || attitude;
}

function signedScore(value?: number | null) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric) || numeric === 0) return '0';
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(1)}`;
}

function emotionReason(item: ConversationEmotionLog) {
  return item.signal?.analysis_reason || item.transition_reason || '本轮未记录明确变化原因。';
}

function vadText(vad?: ConversationEmotionLog['vad_before']) {
  if (!vad) return '未记录';
  const value = (number: number) => Number.isFinite(Number(number)) ? Number(number).toFixed(2) : '0.00';
  return `V ${value(vad.valence)} / A ${value(vad.arousal)} / D ${value(vad.dominance)}`;
}

function satisfactionText(motivation?: ConversationEmotionLog['motivation_before']) {
  return typeof motivation?.total_satisfaction === 'number'
    ? `${Math.round(motivation.total_satisfaction)} 分`
    : '未记录';
}

export default function ReportStep() {
  const { session, coachReport, reportStatus, coachTasks, coachSections, exportReport } = useWorkflow();
  const hasManagerTurn = Boolean(session?.conversation?.some((turn) => turn.speaker === 'manager'));
  const hasScore = typeof coachReport?.overall_score === 'number';
  const score = hasScore ? coachReport.overall_score : '暂无';
  const strengths = safeList<string>(coachReport?.key_strengths).slice(0, 3);
  const improvements = safeList<string>(coachReport?.key_improvements).slice(0, 3);
  const risks = safeList<{ explanation?: string; category?: string } | string>(coachReport?.top_risks)
    .slice(0, 3)
    .map((item) => typeof item === 'string' ? item : item.explanation || item.category || '风险项');
  const phrases = safeList<{ suggestion?: string } | string>(coachReport?.better_phrases)
    .slice(0, 3)
    .map((item) => typeof item === 'string' ? item : item.suggestion || '建议话术');
  const emotionTimeline = safeList<ConversationEmotionLog>(session?.emotion_log);
  const rubricItems = safeList<ReportTaskResult>(coachReport?.task_results)
    .flatMap((task) => {
      const dimensions = safeList<{ id?: string; name?: string; score?: number | null }>(task.dimension_scores)
        .filter((dimension) => typeof dimension.score === 'number')
        .map((dimension) => ({ name: dimension.name || dimension.id || task.task_name || task.task_id || '分项评估', score: dimension.score as number }));
      if (dimensions.length) return dimensions;
      return typeof task.score === 'number'
        ? [{ name: task.task_name || task.task_id || '分项评估', score: task.score }]
        : [];
    })
    .slice(0, 8);

  return (
    <section id="screen-report" className="screen active">
      <div className="page-intro compact-intro">
        <h1>复盘报告</h1>
        <p>面向管理者阅读的对话质量、风险话术和改进建议总结。</p>
      </div>
      <section className="report-view">
        {!coachReport && !hasManagerTurn && (
          <section className="soft-card empty-report"><h2>请先完成至少一轮多轮预演</h2><p className="muted">复盘报告需要 manager 原话和员工回复作为评估依据。</p></section>
        )}
        {!coachReport && hasManagerTurn && (
          <section className="soft-card report-loading">
            <div className="report-stream-header">
              <div><h2>{reportStatus === 'partial_error' ? '复盘报告部分生成失败' : '正在生成复盘报告'}</h2><p>系统正在分析对话结构、反馈质量与风险话术。</p></div>
              <span className={`status-badge ${reportStatusTone(reportStatus)}`}>{reportStatusText(reportStatus)}</span>
            </div>
            {reportStatus === 'streaming' && <div className="progress-line"><span /></div>}
            <div className="report-stream-block">
              <h3>评估任务</h3>
              <ul className="stream-task-list">
                {coachTasks.map((task) => (
                  <li key={task.task_id}>
                    <span className={`status-badge ${task.status === 'error' ? 'danger' : task.status === 'done' ? 'success' : task.status === 'running' ? 'info' : 'neutral'}`}>{taskStatusText(task)}</span>
                    <div><strong>{task.task_name}</strong>{task.summary && <p>{task.summary}</p>}{task.error && <p className="muted">{task.error}</p>}</div>
                  </li>
                ))}
              </ul>
            </div>
            <div className="guidance-list report-stream-sections">
              {coachSections.map((section, index) => {
                const active = reportStatus === 'streaming' && section.status === 'generating';
                const text = (section.error || section.text || '').trim();
                return (
                  <section className={`guidance-section ${section.key === 'risks' ? 'risk-section' : ''}`} key={section.key}>
                    <span className="guidance-icon">{String(index + 1).padStart(2, '0')}</span>
                    <div>
                      <div className="stream-section-title"><h3>{section.title}</h3><span className={`status-badge ${section.status === 'error' ? 'danger' : section.status === 'done' ? 'success' : section.status === 'generating' ? 'info' : 'neutral'}`}>{sectionStatusText(section)}</span></div>
                      <p>{text || (section.status === 'error' ? '该部分生成失败' : '正在整理结构化内容')}{active && <span className="cursor" />}</p>
                      {section.status === 'generating' && !section.text && <div className="skeleton-line" />}
                    </div>
                  </section>
                );
              })}
            </div>
          </section>
        )}
        {coachReport && (
          <>
            <section className="soft-card report-summary">
              <div className="score-circle"><strong>{score}</strong>{hasScore && <span>/100</span>}</div>
              <div className="report-summary-copy"><span>Overall assessment</span><h2>综合结论</h2><p>{coachReport.summary || '暂无综合结论。'}</p></div>
              <button className="btn btn-primary" onClick={exportReport}>导出报告</button>
            </section>
            <section className="rubric-grid">
              {rubricItems.length
                ? rubricItems.map((item) => <ScoreTile key={`${item.name}-${item.score}`} label={item.name} score={item.score} />)
                : <ScoreTile label="分项评分" score="暂无" />}
            </section>
            <section className="report-columns">
              <article className="soft-card report-card"><h3>优势</h3><ul>{(strengths.length ? strengths : ['暂无可展示优势']).map((item) => <li key={item}>{item}</li>)}</ul></article>
              <article className="soft-card report-card"><h3>待改进</h3><ul>{(improvements.length ? improvements : ['暂无可展示改进项']).map((item) => <li key={item}>{item}</li>)}</ul></article>
              <article className="soft-card report-card risk-card"><h3>风险提示</h3><ul>{(risks.length ? risks : ['暂无可展示风险']).map((item) => <li key={item}>{item}</li>)}</ul></article>
            </section>
            <section className="soft-card report-card emotion-timeline-card">
              <div className="report-section-head"><h3>员工情绪与诉求动态轨迹</h3><span>{emotionTimeline.length ? `${emotionTimeline.length} 轮` : '暂无记录'}</span></div>
              {emotionTimeline.length ? (
                <ol className="emotion-timeline">
                  {emotionTimeline.map((item) => (
                    <li key={`${item.turn_index}-${item.employee_attitude_after}`}>
                      <span className="timeline-index">{String(item.turn_index).padStart(2, '0')}</span>
                      <div>
                        <div className="timeline-title"><strong>{attitudeText(item.employee_attitude_before)} → {attitudeText(item.employee_attitude_after)}</strong><span>强度 {item.intensity}/100</span></div>
                        <p>{emotionReason(item)}</p>
                        <div className="timeline-delta">
                          <span>情绪锚点 {item.emotion_anchor_before || '未记录'} → {item.emotion_anchor_after || '未记录'}</span>
                          <span>VAD {vadText(item.vad_before)} → {vadText(item.vad_after)}</span>
                          <span>诉求满足度 {satisfactionText(item.motivation_before)} → {satisfactionText(item.motivation_after)}</span>
                          <span>主诉求 {signedScore(item.signal?.primary_delta)}</span>
                          <span>辅诉求 {signedScore(item.signal?.secondary_delta)}</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : <p className="muted">完成预演并生成报告后，这里会展示每轮员工态度、VAD 与诉求满足度变化。</p>}
            </section>
            <section className="soft-card report-card phrase-card"><h3>建议话术</h3>{(phrases.length ? phrases : ['暂无建议话术']).map((item) => <div className="quote-box" key={item}>{item}</div>)}</section>
          </>
        )}
      </section>
      {coachReport && <div className="bottom-action mobile-export"><button className="btn btn-primary btn-wide" onClick={exportReport}>导出报告</button></div>}
    </section>
  );
}
