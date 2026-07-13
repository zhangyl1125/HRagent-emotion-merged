import { FormEvent, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BoschSupergraphic } from '../components/BoschSupergraphic';
import { Brand } from '../components/Brand';
import { useAuthStore } from '../store/authStore';

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuthStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const from = (location.state as { from?: string } | null)?.from || '/';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch {
      setError('邮箱或密码错误，或账号暂不可用。');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <BoschSupergraphic />
      <section className="auth-card" aria-labelledby="login-title">
        <Brand />
        <div className="auth-heading">
          <span>Internal HR workspace</span>
          <h1 id="login-title">登录</h1>
          <p>使用白名单内 Bosch 邮箱访问绩效沟通预演工作台。</p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>邮箱</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required />
          </label>
          <label>
            <span>密码</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <button className="btn btn-primary btn-large" type="submit" disabled={submitting}>{submitting ? '正在登录' : '登录'}</button>
        </form>
        <footer className="auth-switch">还没有账号？<Link to="/register">注册白名单账号</Link></footer>
      </section>
    </main>
  );
}
