import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { Button, Modal } from '@/components/ui';
import { WorkspaceBrandEffects } from '@/components/WorkspaceBrandEffects';
import { OrganizationProfileWizard } from '@/components/OrganizationProfileWizard';
import { setupApi, type BrandingChoice, type OnboardingState, type SetupBootstrap } from '@/lib/setup-api';
import './workspace-setup.css';

interface SetupContextValue { data: SetupBootstrap; refresh: () => void; updateOnboarding: (state: OnboardingState) => void }
const SetupContext = createContext<SetupContextValue | null>(null);
export function useWorkspaceSetup(): SetupContextValue {
  const value = useContext(SetupContext);
  if (!value) throw new Error('Workspace setup context is unavailable');
  return value;
}

/** Blocks only new accounts with incomplete profiles; migrated organizations keep their access. */
export function WorkspaceSetupGate({ children }: { children: ReactNode }) {
  const { session, logout } = useAuth();
  const { activeWorkspace, loading, error: workspaceError, refreshWorkspaces } = useWorkspace();
  const [snapshot, setSnapshot] = useState<{ key: string; data: SetupBootstrap } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const demo = import.meta.env.VITE_DEMO_MODE === 'true' && !!session?.accessToken.startsWith('demo');
  const key = `${session?.accessToken ?? ''}:${activeWorkspace?.id ?? ''}:${attempt}`;
  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    if (!session || loading || demo) return;
    const controller = new AbortController();
    void setupApi.bootstrap(controller.signal).then((data) => {
      if (!controller.signal.aborted) { setSnapshot({ key, data }); setFailure(null); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setFailure({ key, message: reason instanceof Error ? reason.message : 'Workspace setup could not be loaded' });
    });
    return () => controller.abort();
  }, [session, loading, key, demo]);
  const data = snapshot?.key === key ? snapshot.data : null;
  const updateOnboarding = (state: OnboardingState) => {
    setSnapshot((old) => old?.key === key ? { key, data: { ...old.data, onboarding: state } } : old);
    if (state.profileComplete && data?.onboarding.profileComplete === false) {
      void refreshWorkspaces().then(refresh).catch(refresh);
    }
  };
  if (demo) return <>{children}</>;
  if (workspaceError) return <section className="setup-page" role="alert"><h1>Workspaces could not be loaded</h1><p>{workspaceError}</p><Button onClick={() => void refreshWorkspaces().then(refresh).catch(() => undefined)}>Retry</Button><Button variant="secondary" onClick={() => void logout().catch(() => undefined)}>Sign out</Button></section>;
  if (failure?.key === key) return <section className="setup-page" role="alert"><h1>Workspace setup needs attention</h1><p>{failure.message}</p>
    <div className="setup-actions"><Button onClick={refresh}>Retry</Button><Button variant="secondary" onClick={() => void logout().catch(() => undefined)}>Sign out</Button></div></section>;
  if (!data || loading) return <section className="setup-page" role="status">Loading your authorized workspace…</section>;
  const editable = data.capabilities.organization.includes('organization.profile.update');
  if (data.onboarding.profileRequired && !data.onboarding.profileComplete) {
    return editable ? <OrganizationProfileWizard key={data.organization.id} initial={data.onboarding} onSaved={updateOnboarding} /> :
      <section className="setup-page"><h1>Organization setup is in progress</h1><p>An organization administrator must complete the profile before workspace resources become available.</p><Button onClick={refresh}>Check again</Button></section>;
  }
  return <SetupContext.Provider value={{ data, refresh, updateOnboarding }}><WorkspaceBrandEffects />{children}<WhiteLabelChoiceDialog /></SetupContext.Provider>;
}

function WhiteLabelChoiceDialog() {
  const { data, updateOnboarding } = useWorkspaceSetup();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const show = data.organization.role === 'owner' && data.onboarding.profileComplete
    && data.onboarding.brandingChoice === 'unseen' && data.plan.dashboardCustomize
    && data.capabilities.workspace.includes('branding.edit');
  async function choose(choice: Exclude<BrandingChoice, 'unseen'>) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const result = await setupApi.chooseBranding(choice, data.onboarding.revision);
      updateOnboarding(result);
      if (choice === 'customize') navigate('/workspace/white-label');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Your choice could not be saved'); }
    finally { setBusy(false); }
  }
  return <Modal open={show} title="Make this workspace your own" description="Customize your dashboard’s identity and appearance for your institution or business. You can keep our default appearance and change this later." closeDisabled={busy} onClose={() => void choose('deferred')} footer={<div className="setup-actions">
    <Button disabled={busy} onClick={() => void choose('customize')}>Customize now</Button>
    <Button variant="secondary" disabled={busy} onClick={() => void choose('keep_default')}>Keep the default appearance</Button>
    <Button variant="secondary" disabled={busy} onClick={() => void choose('deferred')}>Later</Button>
  </div>}>{error ? <p role="alert" className="setup-error">{error}</p> : <p>Your decision is saved for this organization. You can open Appearance later.</p>}</Modal>;
}

export function WorkspaceStarterPanel() {
  const context = useContext(SetupContext);
  if (!context) return null;
  const { data } = context;
  const canCustomize = data.capabilities.workspace.includes('branding.edit') && data.plan.dashboardCustomize;
  const limit = (value: number | null) => value === null ? 'Contract allowance' : value.toLocaleString();
  return <section className="setup-starter" aria-labelledby="starter-content-heading">
    <header><h2 id="starter-content-heading">Start with your workspace</h2><p>Plan: <strong>{data.plan.name}</strong> · {data.plan.status}. Starter material is separate from your private knowledge and student enrollments.</p></header>
    {data.usage ? <div className="setup-usage"><span>Workspaces: {data.usage.workspaces} / {limit(data.plan.workspaceLimit)}</span>
      <span>Staff: {data.usage.members} / {limit(data.plan.memberLimit)}</span><span>Monthly tokens: {data.usage.tokensMonthly.toLocaleString()} / {limit(data.plan.monthlyTokenLimit)}</span></div> : null}
    <div className="setup-grid">{data.starterContent.map((item) => <article className="setup-resource" key={`${item.id}:${item.version}`}>
      <small>Free starter {item.kind} · version {item.version}</small><h3>{item.title}</h3><p>{item.content}</p></article>)}</div>
    <div className="setup-actions"><Link to="/help">Open Help Center</Link>{canCustomize ? <Link to="/workspace/white-label">Customize appearance</Link> : null}</div>
    {!data.onboarding.profileComplete && data.capabilities.organization.includes('organization.profile.update') ? <p>Your existing organization can continue working. Complete your <Link to="/organization/profile">organization profile</Link> when ready.</p> : null}
  </section>;
}

export function OrganizationProfilePage() {
  const { data, updateOnboarding } = useWorkspaceSetup();
  const navigate = useNavigate();
  if (!data.capabilities.organization.includes('organization.profile.update')) return <section className="setup-page"><h1>Organization profile</h1><p>An organization administrator manages this profile.</p></section>;
  return <OrganizationProfileWizard key={data.organization.id} initial={data.onboarding} onSaved={(state, completed) => { updateOnboarding(state); if (completed) navigate('/'); }} />;
}
