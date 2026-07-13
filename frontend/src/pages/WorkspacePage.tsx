import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { StepNav } from '../components/StepNav';
import { useWorkflow } from '../context/WorkflowContext';
import type { StepKey } from '../types/domain';
import { inferStepFromState, STEP_KEYS } from '../utils/format';
import GuidanceStep from './steps/GuidanceStep';
import IntentStep from './steps/IntentStep';
import SimulationStep from './steps/SimulationStep';
import ProfileStep from './steps/ProfileStep';
import RehearsalStep from './steps/RehearsalStep';
import ReportStep from './steps/ReportStep';

function isStep(value: string | undefined): value is StepKey {
  return Boolean(value && STEP_KEYS.includes(value as StepKey));
}

export default function WorkspacePage() {
  const { step: stepParam } = useParams();
  const navigate = useNavigate();
  const { bootstrap, session, sessions, switchSession, startNewSession, deleteSession, ensureGuidance, ensureReport } = useWorkflow();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('hr-sidebar-collapsed') === 'true');
  const inferred = inferStepFromState(session?.stage);
  const step: StepKey = isStep(stepParam) ? stepParam : inferred;

  useEffect(() => { void bootstrap(); }, [bootstrap]);

  useEffect(() => {
    localStorage.setItem('hr-sidebar-collapsed', String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (!stepParam && session) navigate(`/app/${inferred}`, { replace: true });
  }, [inferred, navigate, session, stepParam]);

  useEffect(() => {
    if (step === 'guidance' && session?.setup_ready) void ensureGuidance().catch(() => undefined);
    if (step === 'report') void ensureReport().catch(() => undefined);
  }, [ensureGuidance, ensureReport, session?.setup_ready, step]);

  if (stepParam && !isStep(stepParam)) return <Navigate to={`/app/${inferred}`} replace />;

  return (
    <div className={"app-shell" + (sidebarCollapsed ? " is-sidebar-collapsed" : "")} aria-live="polite">
      <StepNav current={step} session={session} sessions={sessions} onSwitchSession={switchSession} onCreateSession={startNewSession} onDeleteSession={deleteSession} collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((value) => !value)} />
      <main className="app-main">
        {step === 'profile' && <ProfileStep />}
        {step === 'intent' && <IntentStep />}
        {step === 'simulation' && <SimulationStep />}
        {step === 'guidance' && <GuidanceStep />}
        {step === 'rehearsal' && <RehearsalStep />}
        {step === 'report' && <ReportStep />}
      </main>
    </div>
  );
}
