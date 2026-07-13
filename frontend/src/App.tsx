import { Navigate, Route, Routes } from 'react-router-dom';
import { LoadingOverlay } from './components/LoadingOverlay';
import { Toast } from './components/Toast';
import AdminPage from './pages/AdminPage';
import HomePage from './pages/HomePage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import { ProtectedRoute } from './routes/ProtectedRoute';
import WorkspacePage from './pages/WorkspacePage';

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/app" element={<WorkspacePage />} />
          <Route path="/app/persona" element={<Navigate to="/app/simulation" replace />} />
          <Route path="/app/:step" element={<WorkspacePage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <LoadingOverlay />
      <Toast />
    </>
  );
}
