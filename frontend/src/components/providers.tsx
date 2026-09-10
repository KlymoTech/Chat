import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react';
import { api, AUTH_SESSION_EVENT } from '@/lib/api';
import { isMFAChallenge, mfaApi, type LoginResult, type MFAFactor } from '@/lib/mfa-api';
import { signupApi, type SignupInput } from '@/lib/signup-api';
import {
  activeWorkspaceId,
  persistActiveWorkspace,
  workspaceApi,
  type WorkspaceCreate,
  type WorkspaceSettings,
} from '@/lib/workspace-api';
import type { Session } from '@/types';

interface AuthContextValue {
  session: Session | null;
  login: (email: string, password: string) => Promise<LoginResult>;
  completeMFA: (challengeToken: string, factor: MFAFactor) => Promise<Session>;
  signup: (input: SignupInput) => Promise<Session>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => api.auth.session());
  useEffect(() => {
    const syncSession = () => setSession(api.auth.session());
    window.addEventListener(AUTH_SESSION_EVENT, syncSession);
    window.addEventListener('storage', syncSession);
    return () => {
      window.removeEventListener(AUTH_SESSION_EVENT, syncSession);
      window.removeEventListener('storage', syncSession);
    };
  }, []);
  const login = useCallback(async (email: string, password: string) => {
    const next = await mfaApi.login(email, password);
    if (!isMFAChallenge(next)) setSession(next);
    return next;
  }, []);
  const completeMFA = useCallback(async (challengeToken: string, factor: MFAFactor) => {
    const next = await mfaApi.verifyChallenge(challengeToken, factor);
    setSession(next);
    return next;
  }, []);
  const signup = useCallback(async (input: SignupInput) => {
    const next = await signupApi.signup(input);
    setSession(next);
    return next;
  }, []);
  const logout = useCallback(async () => { await api.auth.logout(); setSession(null); }, []);
  const value = useMemo(
    () => ({ session, login, completeMFA, signup, logout }),
    [session, login, completeMFA, signup, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}

interface WorkspaceContextValue {
  workspaces: WorkspaceSettings[];
  activeWorkspace: WorkspaceSettings | null;
  loading: boolean;
  selectWorkspace: (workspaceId: string) => void;
  refreshWorkspaces: () => Promise<void>;
  createWorkspace: (input: WorkspaceCreate) => Promise<WorkspaceSettings>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [workspaces, setWorkspaces] = useState<WorkspaceSettings[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceSettings | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!session || session.user.emailVerified === false) {
      setWorkspaces([]);
      setActiveWorkspace(null);
      return;
    }
    setLoading(true);
    try {
      const values = await workspaceApi.list();
      const savedId = activeWorkspaceId();
      const selected = values.find((item) => item.id === savedId) ?? values[0] ?? null;
      setWorkspaces(values);
      setActiveWorkspace(selected);
      if (selected) persistActiveWorkspace(selected.id);
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => { void load(); }, [load]);

  const selectWorkspace = useCallback((workspaceId: string) => {
    const selected = workspaces.find((item) => item.id === workspaceId);
    if (!selected || selected.id === activeWorkspace?.id) return;
    persistActiveWorkspace(selected.id);
    setActiveWorkspace(selected);
  }, [activeWorkspace?.id, workspaces]);

  const createWorkspace = useCallback(async (input: WorkspaceCreate) => {
    const created = await workspaceApi.create(input);
    setWorkspaces((current) => [...current.filter((item) => item.id !== created.id), created]);
    setActiveWorkspace(created);
    return created;
  }, []);

  const value = useMemo(() => ({
    workspaces,
    activeWorkspace,
    loading,
    selectWorkspace,
    refreshWorkspaces: load,
    createWorkspace,
  }), [workspaces, activeWorkspace, loading, selectWorkspace, load, createWorkspace]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('useWorkspace must be used inside WorkspaceProvider');
  return value;
}

type ToastTone = 'success' | 'error' | 'info';
interface ToastItem { id: number; message: string; tone: ToastTone }
interface ToastContextValue { pushToast: (message: string, tone?: ToastTone) => void }
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const pushToast = useCallback((message: string, tone: ToastTone = 'success') => {
    const next = { id: Date.now() + Math.random(), message, tone }; setItems((current) => [...current, next]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== next.id)), 3600);
  }, []);
  return <ToastContext.Provider value={{ pushToast }}>
    {children}
    <div className="toast-stack" aria-live="polite">
      {items.map((item) => <div key={item.id} className={`toast toast--${item.tone}`}>
        {item.tone === 'success' ? <CheckCircle2 /> : item.tone === 'error' ? <CircleAlert /> : <Info />}
        <span>{item.message}</span><button onClick={() => setItems((current) => current.filter((toast) => toast.id !== item.id))} aria-label="Dismiss"><X /></button>
      </div>)}
    </div>
  </ToastContext.Provider>;
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error('useToast must be used inside ToastProvider');
  return value;
}