import { useWorkflow } from '../context/WorkflowContext';

export function LoadingOverlay() {
  const { loading } = useWorkflow();
  return (
    <div className={`overlay ${loading.active ? '' : 'hidden'}`}>
      <div className="loading-card">
        <span className="spinner" />
        <p>{loading.text}</p>
      </div>
    </div>
  );
}
