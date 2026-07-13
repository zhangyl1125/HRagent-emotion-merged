import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import type { BigFivePersonality, IntentOption, MotiveOption } from '../../types/domain';
import { firstText, safeList, valueToText } from '../../utils/format';

type PersonalityDimension = keyof BigFivePersonality;

const dimensions: Array<{ key: PersonalityDimension; label: string; low: string; mid: string; high: string }> = [
  { key: 'openness', label: '接受新事物程度', low: '更习惯现有方式', mid: '接受适度变化', high: '更愿意尝试新方案' },
  { key: 'conscientiousness', label: '做事靠谱程度', low: '更灵活随性', mid: '基本按计划推进', high: '很重视计划和兑现' },
  { key: 'extraversion', label: '表达主动程度', low: '更少主动表达', mid: '需要时会表达', high: '更主动表达想法' },
  { key: 'agreeableness', label: '好沟通程度', low: '更坚持自己看法', mid: '能协商但有保留', high: '更愿意配合沟通' },
  { key: 'neuroticism', label: '情绪敏感程度', low: '不太容易被影响', mid: '压力反应中等', high: '更容易感到压力' },
];

function intentCopy(intent?: IntentOption | null) {
  return {
    goal: valueToText(intent?.business_goal),
    outcome: valueToText(intent?.expected_outcome),
    coachFocus: safeList<string>(intent?.coach_focus),
  };
}

function motiveText(motive?: MotiveOption | null) {
  if (!motive) return '';
  const examples = safeList<string>(motive.examples).slice(0, 2).join(' / ');
  return [motive.description, examples].filter(Boolean).join('；');
}

function personalityText(value: number, dimension: { low: string; mid: string; high: string }) {
  if (value < 35) return dimension.low;
  if (value > 65) return dimension.high;
  return dimension.mid;
}

export default function SimulationStep() {
  const navigate = useNavigate();
  const [secondaryOpen, setSecondaryOpen] = useState(false);
  const secondaryDropdownRef = useRef<HTMLDivElement>(null);
  const {
    options,
    selectedIntentId,
    selectedPersonality,
    selectedPrimaryMotiveId,
    selectedSecondaryMotiveIds,
    displayedProfile,
    updatePersonalityDimension,
    setSelectedPrimaryMotiveId,
    setSelectedSecondaryMotiveIds,
    confirmSimulation,
  } = useWorkflow();

  const intent = options.intents.find((item) => item.id === selectedIntentId);
  const primaryMotive = options.motives.find((item) => item.id === selectedPrimaryMotiveId);
  const secondaryMotives = selectedSecondaryMotiveIds
    .map((id) => options.motives.find((item) => item.id === id))
    .filter(Boolean) as MotiveOption[];
  const selectedIntentCopy = intentCopy(intent);
  const alias = firstText([displayedProfile?.employee_alias, displayedProfile?.name], '未选择员工');
  const role = firstText([displayedProfile?.role], '');
  const department = firstText([displayedProfile?.department], '');
  const reviewCycle = firstText([displayedProfile?.review_cycle], '');
  const performanceRating = firstText([displayedProfile?.performance_rating], '');
  const performanceSummary = performanceRating ? `绩效：${performanceRating}` : '';
  const employeeSummary = [role, department, performanceSummary, reviewCycle].filter(Boolean).join(' · ') || '暂无员工信息';
  const canSubmit = Boolean(selectedPrimaryMotiveId && selectedSecondaryMotiveIds.length === 2);
  const secondarySelectionText = secondaryMotives.length
    ? secondaryMotives.map((item) => item.name || item.id).join(' / ')
    : '请选择辅诉求';

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!secondaryDropdownRef.current?.contains(event.target as Node)) {
        setSecondaryOpen(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);

  const submit = async () => {
    await confirmSimulation();
    navigate('/app/guidance');
  };

  const toggleSecondaryMotive = (id: string) => {
    if (!id || id === selectedPrimaryMotiveId) return;
    if (selectedSecondaryMotiveIds.includes(id)) {
      setSelectedSecondaryMotiveIds(selectedSecondaryMotiveIds.filter((item) => item !== id));
      return;
    }
    if (selectedSecondaryMotiveIds.length >= 2) return;
    setSelectedSecondaryMotiveIds([...selectedSecondaryMotiveIds, id]);
  };

  return (
    <section id="screen-simulation" className="screen active">
      <div className="page-intro">
        <h1>人格与诉求</h1>
      </div>
      <div className="split-layout narrow-right simulation-layout">
        <section className="soft-card simulation-card">
          <div className="big-five-panel" aria-label="人格倾向滑动条">
            {dimensions.map((dimension) => {
              const value = selectedPersonality[dimension.key];
              return (
                <label key={dimension.key} className="personality-slider">
                  <span className="slider-head">
                    <strong>{dimension.label}</strong>
                    <span className="slider-state">{personalityText(value, dimension)}</span>
                  </span>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={value}
                    onChange={(event) => updatePersonalityDimension(dimension.key, Number(event.target.value))}
                    aria-label={dimension.label}
                    aria-valuetext={personalityText(value, dimension)}
                  />
                  <span className="slider-scale"><small>{dimension.low}</small><small>{dimension.high}</small></span>
                </label>
              );
            })}
          </div>

          <div className="motive-select-panel">
            <label className="motive-select-field">
              <span>主诉求</span>
              <select value={selectedPrimaryMotiveId || ''} onChange={(event) => setSelectedPrimaryMotiveId(event.target.value)}>
                <option value="">请选择主诉求</option>
                {options.motives.map((item) => (
                  <option key={item.id} value={item.id}>{item.name || item.id}</option>
                ))}
              </select>
              {primaryMotive && <small>{motiveText(primaryMotive)}</small>}
            </label>

            <div className="motive-select-field motive-multiselect" ref={secondaryDropdownRef}>
              <span>辅诉求 <em>{selectedSecondaryMotiveIds.length}/2</em></span>
              <button
                type="button"
                className="motive-multiselect-trigger"
                aria-haspopup="listbox"
                aria-expanded={secondaryOpen}
                onClick={() => setSecondaryOpen((open) => !open)}
              >
                <strong>{secondarySelectionText}</strong>
                <i aria-hidden="true" />
              </button>
              {secondaryOpen && (
                <div className="motive-multiselect-menu" role="listbox" aria-label="辅诉求，最多选择两个">
                  {options.motives.map((item) => {
                    const checked = selectedSecondaryMotiveIds.includes(item.id);
                    const disabled = item.id === selectedPrimaryMotiveId || (!checked && selectedSecondaryMotiveIds.length >= 2);
                    return (
                      <button
                        key={item.id}
                        type="button"
                        className={'motive-multiselect-option' + (checked ? ' selected' : '')}
                        aria-selected={checked}
                        disabled={disabled}
                        onClick={() => toggleSecondaryMotive(item.id)}
                      >
                        <span className="checkbox-mark" aria-hidden="true">{checked ? '✓' : ''}</span>
                        <span>
                          <strong>{item.name || item.id}</strong>
                          <small>{motiveText(item)}</small>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              <small>{secondaryMotives.length ? secondaryMotives.map((item) => motiveText(item)).filter(Boolean).join('；') : '选择两个次要诉求，用于叠加员工情绪反应。'}</small>
            </div>
          </div>
          <div className="simulation-card-action"><button className="btn btn-primary btn-wide" onClick={submit} disabled={!canSubmit}>确认人格与诉求</button></div>
        </section>

        <section className="soft-card selected-card setup-summary-card summary-panel">
          <div className="summary-person">
            <div className="avatar">{alias.slice(0, 1).toUpperCase()}</div>
            <div className="summary-person-main">
              <strong>{alias}</strong>
              <span>{employeeSummary}</span>
            </div>
          </div>
          <div className="summary-progress">
            <div className="summary-row"><span>意图</span><strong>{intent?.name || '已确认'}</strong></div>
            <div className="summary-row"><span>主诉求</span><strong>{primaryMotive?.name || '待选择'}</strong></div>
            <div className="summary-row"><span>辅诉求</span><strong>{secondaryMotives.map((item) => item.name || item.id).join(' / ') || '待选择'}</strong></div>
          </div>
          {selectedIntentCopy.goal && <div className="summary-block intent-focus"><h3>业务目标</h3><p>{selectedIntentCopy.goal}</p></div>}
          {selectedIntentCopy.outcome && <div className="summary-block"><h3>期望结局</h3><p>{selectedIntentCopy.outcome}</p></div>}
          <div className="summary-block">
            <h3>人格倾向</h3>
            <p>{dimensions.map((item) => `${item.label}：${personalityText(selectedPersonality[item.key], item)}`).join(' / ')}</p>
          </div>
        </section>
      </div>
    </section>
  );
}
