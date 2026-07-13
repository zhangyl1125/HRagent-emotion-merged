import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export function ProtectedRoute() {
  const { initialized, user } = useAuthStore();
  const location = useLocation();

  if (!initialized) {
    return <div className="auth-loading">正在确认登录状态...</div>;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}
