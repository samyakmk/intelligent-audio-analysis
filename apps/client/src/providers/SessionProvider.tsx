import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { ApiError, api, setSessionCsrf, setUnauthorizedHandler } from '@/lib/api';
import { RequestGeneration } from '@/lib/requestGeneration';
import type { Session } from '@/types/api';

interface SessionContextValue {
  session?: Session;
  loading: boolean;
  error?: Error;
  login(principalId: string): Promise<void>;
  logout(): Promise<void>;
  switchWorkspace(workspaceId: string): Promise<void>;
  refresh(): Promise<void>;
  sync(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const sessionGeneration = useRef(new RequestGeneration());
  const [session, setSession] = useState<Session>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error>();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      sessionGeneration.current.invalidate();
      setSession(undefined);
      setSessionCsrf(undefined);
      setLoading(false);
    });
    return () => setUnauthorizedHandler(undefined);
  }, []);

  const refresh = useCallback(async () => {
    const generation = sessionGeneration.current.begin();
    setLoading(true);
    setError(undefined);
    try {
      const value = await api.session();
      if (sessionGeneration.current.isCurrent(generation)) {
        setSession(value);
        setSessionCsrf(value.csrf_token);
      }
    } catch (caught) {
      if (!sessionGeneration.current.isCurrent(generation)) return;
      if (!(caught instanceof ApiError && caught.status === 401)) {
        setError(caught instanceof Error ? caught : new Error('Could not load the demo session'));
      }
      setSession(undefined);
      setSessionCsrf(undefined);
    } finally {
      if (sessionGeneration.current.isCurrent(generation)) setLoading(false);
    }
  }, []);

  const sync = useCallback(async () => {
    const generation = sessionGeneration.current.begin();
    try {
      const value = await api.session();
      if (sessionGeneration.current.isCurrent(generation)) {
        setSession(value);
        setSessionCsrf(value.csrf_token);
      }
    } catch (caught) {
      if (!sessionGeneration.current.isCurrent(generation)) return;
      if (caught instanceof ApiError && caught.status === 401) {
        setSession(undefined);
        setSessionCsrf(undefined);
        return;
      }
      setError(caught instanceof Error ? caught : new Error('Could not refresh workspace usage'));
    } finally {
      if (sessionGeneration.current.isCurrent(generation)) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const gate = sessionGeneration.current;
    const generation = gate.begin();
    let active = true;
    api.session()
      .then((value) => {
        if (!active || !gate.isCurrent(generation)) return;
        setSession(value);
        setSessionCsrf(value.csrf_token);
      })
      .catch((caught: unknown) => {
        if (!active || !gate.isCurrent(generation)) return;
        if (!(caught instanceof ApiError && caught.status === 401)) {
          setError(caught instanceof Error ? caught : new Error('Could not load the demo session'));
        }
        setSession(undefined);
        setSessionCsrf(undefined);
      })
      .finally(() => {
        if (active && gate.isCurrent(generation)) setLoading(false);
      });
    return () => {
      active = false;
      gate.invalidate();
    };
  }, []);

  const login = useCallback(async (principalId: string) => {
    const generation = sessionGeneration.current.begin();
    setLoading(true);
    setError(undefined);
    try {
      const value = await api.demoLogin(principalId);
      if (sessionGeneration.current.isCurrent(generation)) {
        setSession(value);
        setSessionCsrf(value.csrf_token);
      }
    } catch (caught) {
      if (sessionGeneration.current.isCurrent(generation)) {
        setError(caught instanceof Error ? caught : new Error('Could not open the demo'));
      }
      throw caught;
    } finally {
      if (sessionGeneration.current.isCurrent(generation)) setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    const generation = sessionGeneration.current.begin();
    // Build the authenticated request before clearing the in-memory CSRF token,
    // but hide all scoped data immediately and remain logged out locally even
    // if the response is lost.
    const request = api.logout();
    setSession(undefined);
    setSessionCsrf(undefined);
    setLoading(false);
    try {
      await request;
    } catch (caught) {
      if (sessionGeneration.current.isCurrent(generation)) {
        setError(caught instanceof Error ? caught : new Error('Server logout could not be confirmed'));
      }
    }
  }, []);

  const switchWorkspace = useCallback(async (workspaceId: string) => {
    const generation = sessionGeneration.current.begin();
    setLoading(true);
    setError(undefined);
    try {
      const value = await api.switchWorkspace(workspaceId);
      if (sessionGeneration.current.isCurrent(generation)) {
        setSession(value);
        setSessionCsrf(value.csrf_token);
      }
    } catch (caught) {
      // The mutation may have committed before its response was lost. Re-read
      // the server-owned session so the UI never guesses which workspace won.
      try {
        const reconciled = await api.session();
        if (sessionGeneration.current.isCurrent(generation)) {
          setSession(reconciled);
          setSessionCsrf(reconciled.csrf_token);
        }
      } catch (reconcileError) {
        if (sessionGeneration.current.isCurrent(generation)) {
          setSession(undefined);
          setSessionCsrf(undefined);
          setError(
            reconcileError instanceof Error
              ? reconcileError
              : new Error('Workspace switch could not be reconciled'),
          );
        }
      }
      if (sessionGeneration.current.isCurrent(generation)) {
        setError(caught instanceof Error ? caught : new Error('Workspace switch failed'));
      }
      throw caught;
    } finally {
      if (sessionGeneration.current.isCurrent(generation)) setLoading(false);
    }
  }, []);

  const value = useMemo(
    () => ({ session, loading, error, login, logout, switchWorkspace, refresh, sync }),
    [session, loading, error, login, logout, switchWorkspace, refresh, sync],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside SessionProvider');
  return value;
}
