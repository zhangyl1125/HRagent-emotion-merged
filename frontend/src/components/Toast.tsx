import { useWorkflow } from '../context/WorkflowContext';

export function Toast() {
  const { toast } = useWorkflow();
  return <div className={`toast ${toast ? `show ${toast.type}` : ''}`} role="status">{toast?.message}</div>;
}
