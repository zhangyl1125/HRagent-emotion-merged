import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getMe, login as loginRequest, logout as logoutRequest, register as registerRequest } from '../api/auth';
import type { AuthUser } from '../types/auth';

type AuthContextValue = {
  initialized: boolean;
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [initialized, setInitialized] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);

  const refresh = useCallback(async () => {
    try {
      const result = await getMe();
      setUser(result.authenticated ? result.user || null : null);
    } catch {
      setUser(null);
    } finally {
      setInitialized(true);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginRequest(email, password);
    if (!result.success || !result.user) throw new Error('邮箱或密码错误，或账号暂不可用。');
    setUser(result.user);
  }, []);

  const register = useCallback(async (email: string, password: string, displayName?: string) => {
    const result = await registerRequest(email, password, displayName);
    return Boolean(result.success);
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(() => ({ initialized, user, login, register, logout, refresh }), [initialized, user, login, register, logout, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthStore() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuthStore must be used within AuthProvider');
  return context;
}
