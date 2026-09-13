import { ChevronDown, CircleHelp, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Search, Settings2, ShieldCheck, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '@/components/brand';
import { CommandPalette } from '@/components/CommandPalette';
import { NotificationBell } from '@/components/NotificationBell';
import { useAuth, useToast, useWorkspace } from '@/components/providers';
import { platformAdminApi } from '@/lib/platform-admin-api';
import { commandNavigation, materialmPageTitle, primaryNavigation, visibleNavigation } from '@/lib/materialm-navigation';
import { MaterialmSidebarLinks } from './MaterialmSidebar';
import { MaterialmWorkspaceSwitcher } from './WorkspaceSwitcher';
import '@/theme/materialm.tokens.css';
import '@/theme/materialm.css';

const COLLAPSED_KEY = 'northstar.materialm.sidebar-collapsed';
function savedCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSED_KEY) === 'true'; } catch { return false; }
}

/** MaterialM layout adaptation. Existing business pages, providers and APIs are reused. */
export function MaterialmAppShell() {
  const { session, logout } = useAuth();
  const { activeWorkspace, workspaces, selectWorkspace } = useWorkspace();
  const { pushToast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(savedCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [platformAdmin, setPlatformAdmin] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  const account = useRef<HTMLDivElement>(null);
  const accountTrigger = useRef<HTMLButtonElement>(null);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const scope = { role: session?.user.role, permissions: activeWorkspace?.permissions };
  const items = visibleNavigation(primaryNavigation, scope);
  const commands = commandNavigation(scope);
  const initials = useMemo(() => (session?.user.name || 'NS').split(' ').map((part) => part[0]).join('').slice(0, 2).toUpperCase(), [session?.user.name]);
  const branding = activeWorkspace?.whiteLabel;
  const primary = branding?.brandedDashboard && /^#[0-9a-f]{6}$/i.test(branding.primaryColor) ? branding.primaryColor : undefined;
  const theme = primary ? { '--mm-accent': primary, '--blue': primary, '--blue-hover': primary } as CSSProperties : undefined;

  useEffect(() => {
    let active = true;
    setPlatformAdmin(false);
    if (session?.accessToken) {
      void platformAdminApi.canAccess().then((allowed) => { if (active) setPlatformAdmin(allowed); })
        .catch(() => { if (active) setPlatformAdmin(false); });
    }
    return () => { active = false; };
  }, [session?.accessToken, session?.user.email]);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSED_KEY, String(collapsed)); } catch { /* Storage may be disabled. */ }
  }, [collapsed]);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setMobileOpen(false); setCommandOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  useEffect(() => {
    setMobileOpen(false); setAccountOpen(false);
  }, [location.key, activeWorkspace?.id]);

  useEffect(() => {
    const element = drawer.current;
    if (!element) return;
    if (mobileOpen && !element.open) element.showModal();
    if (!mobileOpen && element.open) element.close();
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const resize = () => { if (window.innerWidth >= 1100) setMobileOpen(false); };
    window.addEventListener('resize', resize);
    return () => { document.body.style.overflow = previous; window.removeEventListener('resize', resize); };
  }, [mobileOpen]);

  useEffect(() => {
    if (!accountOpen) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !account.current?.contains(event.target)) setAccountOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setAccountOpen(false); accountTrigger.current?.focus(); }
    };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [accountOpen]);

  async function signOut() {
    try { await logout(); navigate('/login'); }
    catch (error) { pushToast(error instanceof Error ? error.message : 'Sign out failed', 'error'); }
  }

  return <div className={`mm-shell${collapsed ? ' mm-shell--compact' : ''}`} style={theme}>
    <a className="mm-skip" href="#mm-main-content">Skip to content</a>
    <aside className="mm-sidebar" aria-label="Primary navigation">
      <Link to="/" className="mm-sidebar__brand" aria-label="Northstar AI home"><Brand compact={collapsed} /></Link>
      <MaterialmSidebarLinks items={items} />
      <button type="button" className="mm-collapse" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
        {collapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}<span>{collapsed ? 'Expand' : 'Collapse sidebar'}</span>
      </button>
    </aside>
    <div className="mm-main">
      <header className="mm-topbar">
        <div className="mm-topbar__left">
          <button ref={menuTrigger} type="button" className="mm-menu-button" aria-label="Open navigation" aria-haspopup="dialog" aria-controls="mm-mobile-navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen(true)}><Menu aria-hidden="true" /></button>
          <MaterialmWorkspaceSwitcher key={activeWorkspace?.id ?? 'workspace-loading'} />
          <div className="mm-page-title"><small>{location.pathname.startsWith('/education') ? 'Learning' : 'Workspace'}</small><h1>{materialmPageTitle(location.pathname)}</h1></div>
        </div>
        <div className="mm-topbar__actions">
          <button className="mm-search" type="button" aria-label="Search pages and workspaces" aria-haspopup="dialog" onClick={() => setCommandOpen(true)}><Search aria-hidden="true" /><span>Search</span><kbd>Ctrl / ⌘ K</kbd></button>
          <NotificationBell />
          <div className="account-menu" ref={account}>
            <button ref={accountTrigger} type="button" className="account-button" aria-label="Account menu" aria-expanded={accountOpen} onClick={() => setAccountOpen(!accountOpen)}><span className="avatar">{initials}</span><span className="account-copy"><strong>{session?.user.name}</strong><small>{session?.user.role}</small></span><ChevronDown aria-hidden="true" /></button>
            {accountOpen ? <div className="account-popover"><div><strong>{session?.user.name}</strong><small>{session?.user.email}</small></div>
              {platformAdmin ? <Link to="/platform-admin" onClick={() => setAccountOpen(false)}><ShieldCheck />Platform control plane</Link> : null}
              <Link to="/workspace" onClick={() => setAccountOpen(false)}><Settings2 />Workspace settings</Link>
              <Link to="/help" onClick={() => setAccountOpen(false)}><CircleHelp />Help Center</Link>
              <button type="button" onClick={() => void signOut()}><LogOut />Sign out</button>
            </div> : null}
          </div>
        </div>
      </header>
      <main id="mm-main-content" className="mm-content" tabIndex={-1}><Outlet key={activeWorkspace?.id ?? 'workspace-loading'} /></main>
    </div>
    <dialog ref={drawer} id="mm-mobile-navigation" className="mm-drawer" aria-label="Main navigation" onCancel={() => setMobileOpen(false)} onClose={() => { setMobileOpen(false); menuTrigger.current?.focus(); }} onClick={(event) => { if (event.target === event.currentTarget) setMobileOpen(false); }}>
      <div className="mm-drawer__inner">
        <div className="mm-drawer__header"><Brand /><button type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X aria-hidden="true" /></button></div>
        <MaterialmSidebarLinks items={items} onNavigate={() => setMobileOpen(false)} />
      </div>
    </dialog>
    <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} navigation={commands} workspaces={workspaces} activeWorkspaceId={activeWorkspace?.id} onSelectWorkspace={selectWorkspace} canViewPlatformAdmin={platformAdmin} />
  </div>;
}
