import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BoschSupergraphic } from '../components/BoschSupergraphic';
import { Brand } from '../components/Brand';
import { useAuthStore } from '../store/authStore';

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuthStore();
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const passwordValid = /^\d{8,}$/.test(password);
  const passwordsMatch = passwordValid && confirmPassword.length > 0 && password === confirmPassword;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setMessage('');
    if (!passwordValid) {
      setError('密码至少需要 8 位数字。');
      return;
    }
    if (!passwordsMatch) {
      setError('两次输入的密码不一致。');
      return;
    }
    setSubmitting(true);
    try {
      const ok = await register(email, password, displayName || undefined);
      if (!ok) {
        setError('注册失败，请检查信息或联系管理员。');
        return;
      }
      setMessage('注册成功，请登录。');
      window.setTimeout(() => navigate('/login', { replace: true }), 700);
    } catch {
      setError('注册失败，请检查信息或联系管理员。');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <BoschSupergraphic />
      <section className="auth-card" aria-labelledby="register-title">
        <Brand />
        <div className="auth-heading">
          <span>Internal HR workspace</span>
          <h1 id="register-title">注册</h1>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>邮箱</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required />
          </label>
          <label>
            <span>显示名称</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" />
          </label>
          <label>
            <span>密码</span>
            <div className="auth-password-control">
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                inputMode="numeric"
                pattern="[0-9]{8,}"
                minLength={8}
                aria-describedby="password-requirement"
                required
              />
              {passwordValid && <span className="auth-password-valid" role="img" aria-label="密码格式正确">✓</span>}
            </div>
            <small id="password-requirement" className="auth-field-help">至少 8 位数字</small>
          </label>
          <label>
            <span>确认密码</span>
            <div className="auth-password-control">
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                inputMode="numeric"
                pattern="[0-9]{8,}"
                minLength={8}
                aria-invalid={confirmPassword.length > 0 && !passwordsMatch}
                required
              />
              {passwordsMatch && <span className="auth-password-valid" role="img" aria-label="两次密码一致">✓</span>}
            </div>
          </label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          {message && <div className="auth-success" role="status">{message}</div>}
          <button className="btn btn-primary btn-large" type="submit" disabled={submitting}>{submitting ? '正在注册' : '创建账号'}</button>
        </form>
        <footer className="auth-switch">已有账号？<Link to="/login">返回登录</Link></footer>
      </section>
    </main>
  );
}
