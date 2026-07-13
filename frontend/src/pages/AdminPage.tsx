import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { BoschSupergraphic } from '../components/BoschSupergraphic';
import { Brand } from '../components/Brand';
import { createAdminAccount, deleteAdminAccount, listAdminAccounts, resetAdminPassword, updateAdminWhitelist } from '../api/auth';
import { useAuthStore } from '../store/authStore';
import type { AdminAccount } from '../types/auth';

const validPassword = (value: string) => /^\d{8,}$/.test(value);

export default function AdminPage() {
  const { user } = useAuthStore();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetEmail, setResetEmail] = useState<string | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const result = await listAdminAccounts();
    setAccounts(result.items);
  }, []);

  useEffect(() => {
    if (user?.role === 'admin') void refresh().catch(() => setError('无法读取白名单账号。'));
  }, [refresh, user?.role]);

  if (user?.role !== 'admin') return <Navigate to="/" replace />;

  const createAccount = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setMessage('');
    if (!validPassword(password)) return setError('密码至少需要 8 位数字。');
    if (password !== confirmPassword) return setError('两次输入的密码不一致。');
    setBusy(true);
    try {
      await createAdminAccount(email, password, displayName || undefined);
      setEmail('');
      setDisplayName('');
      setPassword('');
      setConfirmPassword('');
      setMessage('账号已加入白名单并创建。');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '账号创建失败。');
    } finally {
      setBusy(false);
    }
  };

  const resetPasswordForAccount = async (event: FormEvent) => {
    event.preventDefault();
    if (!resetEmail) return;
    setError('');
    setMessage('');
    if (!validPassword(resetPassword)) return setError('密码至少需要 8 位数字。');
    setBusy(true);
    try {
      await resetAdminPassword(resetEmail, resetPassword);
      setResetEmail(null);
      setResetPassword('');
      setMessage('密码已重置。');
    } catch (err) {
      setError(err instanceof Error ? err.message : '密码重置失败。');
    } finally {
      setBusy(false);
    }
  };

  const deleteAccount = async (account: AdminAccount) => {
    if (!window.confirm(`确认删除 ${account.email} 的白名单授权？`)) return;
    setError('');
    setMessage('');
    setBusy(true);
    try {
      await deleteAdminAccount(account.email);
      setMessage('白名单授权已删除，账号已停用。');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '账号删除失败。');
    } finally {
      setBusy(false);
    }
  };

  const toggleWhitelist = async (account: AdminAccount) => {
    setError('');
    setMessage('');
    setBusy(true);
    try {
      await updateAdminWhitelist(account.email, !account.whitelist_enabled);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '白名单更新失败。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="admin-page">
      <BoschSupergraphic />
      <header className="admin-header">
        <Brand />
        <div><span>Internal HR workspace</span><h1>账号与白名单</h1></div>
        <Link className="btn btn-secondary" to="/">返回工作台</Link>
      </header>

      <section className="admin-layout">
        <form className="soft-card admin-account-form" onSubmit={createAccount}>
          <h2>创建授权账号</h2>
          <label><span>邮箱</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label><span>显示名称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
          <label><span>密码</span><div className="auth-password-control"><input type="password" inputMode="numeric" pattern="[0-9]{8,}" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />{validPassword(password) && <span className="auth-password-valid" aria-label="密码格式正确">✓</span>}</div></label>
          <label><span>确认密码</span><div className="auth-password-control"><input type="password" inputMode="numeric" pattern="[0-9]{8,}" minLength={8} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />{validPassword(password) && password === confirmPassword && <span className="auth-password-valid" aria-label="两次密码一致">✓</span>}</div></label>
          <small className="auth-field-help">密码至少 8 位数字，两次输入必须一致。</small>
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? '处理中' : '加入白名单并创建'}</button>
        </form>

        <section className="soft-card admin-account-list">
          <div className="admin-list-head"><div><h2>授权账号</h2><span>{accounts.length} 个</span></div><button className="btn btn-secondary" type="button" onClick={() => void refresh()} disabled={busy}>刷新</button></div>
          {error && <div className="auth-error" role="alert">{error}</div>}
          {message && <div className="auth-success" role="status">{message}</div>}
          <div className="admin-account-rows">
            {accounts.map((account) => (
              <article className="admin-account-row" key={account.email}>
                <div><strong>{account.display_name || account.email}</strong><span>{account.email}</span></div>
                <span className={`admin-account-status ${account.whitelist_enabled ? 'enabled' : ''}`}>{account.whitelist_enabled ? '已授权' : '已停用'}</span>
                <span>{account.registered ? (account.role === 'admin' ? '管理员' : '已注册') : '待注册'}</span>
                <div className="admin-row-actions">
                  {account.registered && <button type="button" onClick={() => { setResetEmail(account.email); setResetPassword(''); }}>重置密码</button>}
                  <button type="button" disabled={account.role === 'admin' || busy} onClick={() => void toggleWhitelist(account)}>{account.whitelist_enabled ? '停用' : '启用'}</button>
                  <button className="admin-delete-account" type="button" disabled={account.role === 'admin' || busy} onClick={() => void deleteAccount(account)}>删除</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      </section>

      {resetEmail && (
        <div className="admin-reset-backdrop" role="presentation">
          <form className="soft-card admin-reset-dialog" onSubmit={resetPasswordForAccount}>
            <h2>重置密码</h2><p>{resetEmail}</p>
            <label><span>新密码</span><div className="auth-password-control"><input autoFocus type="password" inputMode="numeric" pattern="[0-9]{8,}" minLength={8} value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required />{validPassword(resetPassword) && <span className="auth-password-valid">✓</span>}</div></label>
            <div><button className="btn btn-secondary" type="button" onClick={() => setResetEmail(null)}>取消</button><button className="btn btn-primary" type="submit" disabled={busy}>确认重置</button></div>
          </form>
        </div>
      )}
    </main>
  );
}
