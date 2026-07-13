import { useNavigate } from 'react-router-dom';
import { Brand } from './Brand';
import type { SessionState, StepKey } from '../types/domain';
import { inferStepFromState, STEP_KEYS, STEP_LABELS } from '../utils/format';
import { useAuthStore } from '../store/authStore';

function isStepUnlocked(step: StepKey, session: SessionState | null): boolean {
  const stage = session?.stage || 'created';
  if (step === 'profile') return true;
  if (step === 'intent') return Boolean(session?.employee_profile) || ['profile_ready', 'setup_ready', 'guidance_ready', 'rehearsal', 'report_ready'].includes(stage);
  if (step === 'simulation') return Boolean(session?.intent) || ['setup_ready', 'guidance_ready', 'rehearsal', 'report_ready'].includes(stage);
  if (step === 'guidance') return Boolean(session?.setup_ready) || ['setup_ready', 'guidance_ready', 'rehearsal', 'report_ready'].includes(stage);
  if (step === 'rehearsal') return ['guidance_ready', 'rehearsal', 'report_ready'].includes(stage);
  if (step === 'report') return Boolean(session?.conversation?.some((turn) => turn.speaker === 'manager')) || stage === 'report_ready';
  return false;
}

function stepStatus(index: number, currentIndex: number, canVisit: boolean) {
  if (index < currentIndex) return '已完成';
  if (index === currentIndex) return '当前步骤';
  return canVisit ? '可进入' : '';
}

export function StepNav({ current, session, sessions, onSwitchSession, onCreateSession, onDeleteSession, collapsed, onToggle }: { current: StepKey; session: SessionState | null; sessions: SessionState[]; onSwitchSession: (sessionId: string) => Promise<SessionState | null>; onCreateSession: () => Promise<SessionState>; onDeleteSession: (sessionId: string) => Promise<SessionState | null>; collapsed: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const currentIndex = STEP_KEYS.indexOf(current);
  const { user, logout } = useAuthStore();
  const sessionLabel = (item: SessionState) => item.employee_profile?.name || item.employee_profile?.employee_alias || `会话 ${item.session_id.slice(0, 8)}`;

  return (
    <aside className={"app-sidebar" + (collapsed ? " is-collapsed" : "")} aria-label="工作台导航">
      <div className="workspace-toolbar">
        <button
          className="sidebar-logo-button"
          type="button"
          onClick={() => navigate('/')}
          aria-label="返回主页"
          title="返回主页"
        >
          <Brand small showText={false} />
        </button>
        <button
          className={"sidebar-toggle" + (collapsed ? " is-open-control" : "")}
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
        >
          <span className="sidebar-toggle-icon" aria-hidden="true"><span /><span /></span>
        </button>
      </div>
      <nav className="stepper" aria-label="流程步骤">
        {STEP_KEYS.map((step, index) => {
          const canVisit = index <= currentIndex || isStepUnlocked(step, session);
          const status = stepStatus(index, currentIndex, canVisit);
          return (
            <button
              key={step}
              type="button"
              className={`step-item ${step === current ? 'is-current' : ''} ${index < currentIndex ? 'is-complete' : ''}`}
              aria-current={step === current ? 'step' : undefined}
              data-label={STEP_LABELS[step]}
              data-status={status}
              disabled={!canVisit}
              onClick={() => canVisit && navigate(`/app/${step}`)}
            >
              <span className="step-index">{index < currentIndex ? '✓' : String(index + 1).padStart(2, '0')}</span>
              <span className="step-copy"><strong>{STEP_LABELS[step]}</strong>{canVisit && <small>{status}</small>}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="session-switcher">
          <label htmlFor="session-switcher-select">会话</label>
          <select
            id="session-switcher-select"
            value={session?.session_id || ''}
            onChange={(event) => {
              void onSwitchSession(event.target.value).then((next) => {
                if (next) navigate(`/app/${inferStepFromState(next.stage)}`);
              });
            }}
            disabled={!sessions.length}
          >
            {sessions.length ? sessions.map((item) => (
              <option key={item.session_id} value={item.session_id}>{sessionLabel(item)}</option>
            )) : <option value="">当前会话</option>}
          </select>
          <button type="button" onClick={() => void onCreateSession().then(() => navigate('/app/profile'))}>新建会话</button>
          <button
            className="session-delete-button"
            type="button"
            disabled={!session}
            onClick={() => {
              if (!session || !window.confirm('确认删除当前会话？')) return;
              void onDeleteSession(session.session_id).then((next) => {
                if (next) navigate(`/app/${inferStepFromState(next.stage)}`);
              });
            }}
          >
            删除当前会话
          </button>
        </div>
        <div className="sidebar-user">
          <span>{user?.display_name || user?.email}</span>
          {user?.role === 'admin' && <button type="button" onClick={() => navigate('/admin')}>账号管理</button>}
          <button type="button" onClick={() => void logout()}>退出</button>
        </div>
        <button
          className="home-return-button"
          type="button"
          onClick={() => navigate('/')}
          aria-label="返回主页"
          title="返回主页"
        >
          <span className="home-return-icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 11.5 12 4l9 7.5" />
              <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
            </svg>
          </span>
          <span className="home-return-text">返回主页</span>
        </button>
      </div>
    </aside>
  );
}
