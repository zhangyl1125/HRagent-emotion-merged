import type { ReactNode } from 'react';

interface StatusBadgeProps {
  children: ReactNode;
  tone?: 'info' | 'success' | 'warning' | 'danger' | 'neutral';
}

export function StatusBadge({ children, tone = 'info' }: StatusBadgeProps) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
