import { useNavigate } from 'react-router-dom';
import { useWorkflow } from '../../context/WorkflowContext';
import type { GuidanceSectionDraft, WorkflowStreamStatus } from '../../types/domain';
import { safeList } from '../../utils/format';

function draftStatusText(section: GuidanceSectionDraft) {
  if (section.status === 'done') return '已完成';
  if (section.status === 'error') return '失败';
  if (section.status === 'generating') return '生成中';
  return '等待中';
}

function renderDraftBody(section: GuidanceSectionDraft, guidanceStatus: WorkflowStreamStatus) {
  const text = (section.error || section.text || '').trim();
  const active = guidanceStatus === 'streaming' && section.status === 'generating';
  return (
    <p>
      {text || (section.status === 'error' ? '该部分生成失败' : '正在整理结构化内容')}
      {active && <span className="cursor" />}
    </p>
  );
}

export default function GuidanceStep() {
  const navigate = useNavigate();
  const { guidanceReport, guidanceSections, guidanceStatus } = useWorkflow();
  const finalSections = guidanceReport ? [
    { title: '沟通目标', list: safeList<string>([guidanceReport.purpose]).filter(Boolean) },
    { title: '开场建议', list: safeList<string>([guidanceReport.opening_suggestion]).filter(Boolean) },
    { title: '风险提醒', list: safeList<string>(guidanceReport.risk_preview) },
    { title: '应对策略', list: safeList<string>(guidanceReport.response_strategies) },
    { title: '推荐话术', list: safeList<string>(guidanceReport.safer_phrases) },
    { title: '说明', list: safeList<string>([guidanceReport.disclaimer]).filter(Boolean) },
  ] : null;

  return (
    <section id="screen-guidance" className="screen active">
      <div className="briefing-layout">
        <section className="soft-card guidance-card briefing-card">
          <div className="briefing-header">
            <div>
              <h1>谈前指导</h1>
            </div>
            <button className="btn btn-primary guidance-start-button" onClick={() => navigate('/app/rehearsal')} disabled={guidanceStatus !== 'ready'}>开始预演</button>
          </div>
          {guidanceStatus === 'streaming' && <div className="progress-line"><span /></div>}
          <div className="guidance-list">
            {finalSections ? finalSections.map((section) => (
              <section className={`guidance-section ${section.title.includes('风险') ? 'risk-section' : ''}`} key={section.title}>
                <div><h3>{section.title}</h3><ul>{section.list.length ? section.list.map((item) => <li key={item}>{item}</li>) : <li>—</li>}</ul></div>
              </section>
            )) : guidanceSections.map((section) => (
              <section className={`guidance-section ${section.key === 'risk_preview' ? 'risk-section' : ''}`} key={section.key}>
                <div>
                  <div className="stream-section-title"><h3>{section.title}</h3><span className={`status-badge ${section.status === 'error' ? 'danger' : section.status === 'done' ? 'success' : section.status === 'generating' ? 'info' : 'neutral'}`}>{draftStatusText(section)}</span></div>
                  {renderDraftBody(section, guidanceStatus)}
                  {section.status === 'generating' && !section.text && <div className="skeleton-line" />}
                </div>
              </section>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
