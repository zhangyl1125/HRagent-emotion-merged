import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import type { IntentOption } from '../../types/domain';
import { firstText, safeList, valueToText } from '../../utils/format';

function intentCopy(intent?: IntentOption | null) {
  return {
    goal: valueToText(intent?.business_goal),
    redLines: safeList<string>(intent?.red_lines),
    outcome: valueToText(intent?.expected_outcome),
    coachFocus: safeList<string>(intent?.coach_focus),
  };
}

function IntentDetailBlocks({ intent }: { intent?: IntentOption | null }) {
  const copy = intentCopy(intent);
  return (
    <>
      {copy.goal && <div className="summary-block intent-focus"><h3>业务目标</h3><p>{copy.goal}</p></div>}
      {copy.redLines.length > 0 && <div className="summary-block danger-note"><h3>对话红线</h3><p>{copy.redLines.join('；')}</p></div>}
      {copy.outcome && <div className="summary-block"><h3>期望结局</h3><p>{copy.outcome}</p></div>}
      {copy.coachFocus.length > 0 && <div className="summary-block"><h3>指导关注点</h3><p>{copy.coachFocus.join(' / ')}</p></div>}
    </>
  );
}

export default function IntentStep() {
  const navigate = useNavigate();
  const {
    options,
    selectedIntentId,
    setSelectedIntentId,
    displayedProfile,
    confirmIntent,
  } = useWorkflow();
  const intent = options.intents.find((item) => item.id === selectedIntentId) || null;

  const submit = async () => {
    await confirmIntent();
    navigate('/app/simulation');
  };

  const alias = firstText([displayedProfile?.employee_alias, displayedProfile?.name], '未选择员工');
  const department = firstText([displayedProfile?.department], '');
  const performanceRating = firstText([displayedProfile?.performance_rating], '');
  const performanceSummary = performanceRating ? `绩效：${performanceRating}` : '';
  const employeeSummary = [department, performanceSummary].filter(Boolean).join(' · ') || '暂无员工信息';

  return (
    <section id="screen-intent" className="screen active">
      <div className="page-intro">
        <h1>沟通意图</h1>
        <p>选择本次绩效反馈的主要目标</p>
      </div>
      <div className="split-layout narrow-right intent-layout-five">
        <section className="soft-card intent-card intent-card-five">
          <div className="intent-options intent-options-five">
            {options.intents.map((item, index) => {
              const selected = item.id === selectedIntentId;
              const copy = intentCopy(item);
              return (
                <button key={item.id} className={`intent-option intent-option-compact ${selected ? 'selected' : ''}`} type="button" onClick={() => setSelectedIntentId(item.id)}>
                  <span className="option-icon">{selected ? '✓' : String(index + 1).padStart(2, '0')}</span>
                  <span className="option-content">
                    <h3>{item.name || item.id}</h3>
                    {copy.goal && <p className="intent-brief">{copy.goal}</p>}
                    {copy.outcome && <small>期望结果：{copy.outcome}</small>}
                  </span>
                  <span className="option-radio" />
                </button>
              );
            })}
          </div>
          <div className="intent-card-action"><button className="btn btn-primary btn-wide" onClick={submit} disabled={!selectedIntentId}>确认沟通意图</button></div>
        </section>
        <section className="soft-card selected-card setup-summary-card intent-detail-card summary-panel">
          <div className="summary-person">
            <div className="avatar">{alias.slice(0, 1).toUpperCase()}</div>
            <div className="summary-person-main">
              <strong>{alias}</strong>
              <span>{employeeSummary}</span>
            </div>
          </div>
          <div className="summary-progress">
            <div className="summary-row"><span>意图</span><strong>{intent?.name || '待选择'}</strong></div>
          </div>
          <IntentDetailBlocks intent={intent} />
        </section>
      </div>
    </section>
  );
}
