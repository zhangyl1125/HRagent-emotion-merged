import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BoschSupergraphic } from '../components/BoschSupergraphic';
import { Brand } from '../components/Brand';
import { useWorkflow } from '../context/WorkflowContext';
import { useAuthStore } from '../store/authStore';

const flowSteps = ['员工信息', '沟通意图', '人格与诉求', '谈前指导', '预演', '复盘'];
const valuePoints = [
  {
    code: '01',
    title: '员工背景整理',
    text: '集中员工库信息、补充事实和参考资料，减少会前反复确认。',
  },
  {
    code: '02',
    title: '谈前材料准备',
    text: '把业务目标、沟通红线和建议话术整理成可执行 briefing。',
  },
  {
    code: '03',
    title: '预演与复盘',
    text: '在正式沟通前完成一轮演练，并沉淀风险提示和改进建议。',
  },
];
const standards = ['事实先行', '合规边界', '可执行行动', '经理自检'];

export default function HomePage() {
  const navigate = useNavigate();
  const { startNewSession } = useWorkflow();
  const { user, logout } = useAuthStore();
  const [starting, setStarting] = useState(false);

  const start = async () => {
    if (starting) return;
    setStarting(true);
    try {
      await startNewSession();
      navigate('/app/profile');
    } finally {
      setStarting(false);
    }
  };

  return (
    <main className="launch-page">
      <BoschSupergraphic />
      <div className="launch-shell">
        <header className="launch-header">
          <Brand />
          <div className="launch-status">
            <span>Internal HR workspace</span>
            <strong>绩效沟通准备流程</strong>
            <button className="auth-inline-button" type="button" onClick={() => void logout()}>{user?.display_name || user?.email || '退出登录'}</button>
          </div>
        </header>

        <section className="launch-hero" aria-labelledby="launch-title">
          <div className="launch-copy">
            <p className="eyebrow">Bosch internal preparation</p>
            <h1 id="launch-title">绩效反馈准备工作台</h1>
            <p className="launch-subtitle">
              面向经理和 HRBP 的会前准备流程：先梳理事实，再明确沟通目标、边界和后续行动。
            </p>
            <div className="launch-actions">
              <button className="btn btn-primary btn-large" type="button" onClick={start} disabled={starting}>
                {starting ? '正在创建会话' : '开始准备'}
              </button>
              <span className="launch-action-note">数据仅用于内部演练与会前准备</span>
            </div>
          </div>

          <aside className="launch-panel" aria-label="流程概览">
            <div className="launch-panel-head">
              <span>Workflow</span>
              <strong>6 step preparation</strong>
            </div>
            <ol className="flow-list">
              {flowSteps.map((item, index) => <li key={item}><span>{String(index + 1).padStart(2, '0')}</span>{item}</li>)}
            </ol>
          </aside>
        </section>

        <section className="launch-standard-band" aria-label="准备标准">
          <div>
            <span>Preparation standard</span>
            <strong>沟通前先完成四项检查</strong>
          </div>
          <ul>
            {standards.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>

        <section className="value-grid" aria-label="核心价值">
          {valuePoints.map((item) => (
            <article key={item.title}>
              <span>{item.code}</span>
              <h2>{item.title}</h2>
              <p>{item.text}</p>
            </article>
          ))}
        </section>

        <section className="launch-operations" aria-label="使用范围">
          <div>
            <span className="eyebrow">Scope</span>
            <h2>用于会前准备，不替代正式判断</h2>
          </div>
          <p>
            正式沟通仍需结合真实业务背景、公司政策和 HR/Legal 要求。系统只帮助整理事实、练习表达和识别话术风险。
          </p>
        </section>

        <footer className="launch-footer">Bosch internal use only · HR Conversation Coach</footer>
      </div>
    </main>
  );
}
