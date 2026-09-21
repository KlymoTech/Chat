import { Bell, Blocks, Braces, Building2, CreditCard, KeyRound, Palette, Radio, ScrollText, ShieldCheck, UsersRound, UserRoundCog } from 'lucide-react';
import type { SettingsSection } from './workspaceSettings.api';

type Item = { id: SettingsSection; label: string; icon: typeof Building2; permissions?: string[] };
const groups: { label: string; items: Item[] }[] = [
  { label: 'Workspace', items: [
    { id: 'general', label: 'General', icon: Building2, permissions: ['settings.view'] },
    { id: 'members', label: 'Members', icon: UsersRound, permissions: ['members.view'] },
    { id: 'roles', label: 'Roles & permissions', icon: UserRoundCog, permissions: ['roles.manage'] },
    { id: 'teams', label: 'Teams', icon: UsersRound, permissions: ['teams.manage'] },
  ] },
  { label: 'Communication', items: [
    { id: 'notifications', label: 'Notifications', icon: Bell, permissions: ['settings.view'] },
    { id: 'channels', label: 'Channels', icon: Radio, permissions: ['channels.view'] },
    { id: 'integrations', label: 'Integrations', icon: Blocks, permissions: ['integrations.view'] },
  ] },
  { label: 'Security', items: [
    { id: 'security', label: 'Authentication & security', icon: ShieldCheck, permissions: ['settings.view'] },
    { id: 'audit', label: 'Audit', icon: ScrollText, permissions: ['audit.view'] },
  ] },
  { label: 'Developer', items: [{ id: 'developer', label: 'Developer', icon: Braces, permissions: ['settings.view'] }] },
  { label: 'Account', items: [{ id: 'billing', label: 'Billing / usage', icon: CreditCard, permissions: ['billing.view'] }] },
  { label: 'Customization', items: [{ id: 'branding', label: 'White label', icon: Palette, permissions: ['branding.view', 'branding.edit', 'branding.publish', 'branding.domain.manage'] }] },
];

export function WorkspaceSettingsNavigation({ active, onSelect, permissions }: { active: SettingsSection; onSelect: (section: SettingsSection) => void; permissions: string[] }) {
  const allowed = new Set(permissions);
  return <nav className="workspace-console-nav" aria-label="Workspace settings">
    {groups.map((group) => {
      const items = group.items.filter((item) => !item.permissions?.length || item.permissions.some((permission) => allowed.has(permission)));
      if (!items.length) return null;
      return <div key={group.label}><p>{group.label}</p>{items.map(({ id, label, icon: Icon }) =>
        <button type="button" key={id} className={active === id ? 'is-active' : ''} onClick={() => onSelect(id)}><Icon /><span>{label}</span></button>)}</div>;
    })}
    <p>Legacy</p><a href="/workspace"><KeyRound /><span>Original workspace console</span></a>
  </nav>;
}
