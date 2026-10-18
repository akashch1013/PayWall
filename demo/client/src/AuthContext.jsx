import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from './api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    api('/api/auth/me')
      .then((data) => active && setUser(data.user))
      .catch(() => active && setUser(null))
      .finally(() => active && setReady(true));
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await api('/api/auth/login', { method: 'POST', body: { email, password } });
    setUser(data.user);
    return data.user;
  }, []);

  const register = useCallback(async (name, email, password) => {
    const data = await api('/api/auth/register', { method: 'POST', body: { name, email, password } });
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' });
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, ready, login, register, logout }), [user, ready, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
