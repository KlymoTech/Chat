import { Bell, Blocks, Braces, Building2, CreditCard, KeyRound, Palette, Radio, ScrollText, ShieldCheck, UsersRound, UserRoundCog } from 'lucide-react';
import type { SettingsSection } from './workspaceSettings.api';

type Item = { id: SettingsSection; label: string; icon: typeof Building2; permission?: string };
const groups: { label: string; items: Item[] }[] = [
  { label: 'Workspace', items: [
    { id: 'general', label: 'General', icon: Building2, permission: 'settings.view' },
    { id: 'members', label: 'Members', icon: UsersRound, permission: 'members.view' },
    { id: 'roles', label: 'Roles & permissions', icon: UserRoundCog, permission: 'roles.manage' },
    { id: 'teams', label: 'Teams', icon: UsersRound, permission: 'teams.manage' },
  ] },
  { label: 'Communication', items: [
    { id: 'notifications', label: 'Notifications', icon: Bell, permission: 'settings.view' },
    { id: 'channels', label: 'Channels', icon: Radio, permission: 'channels.view' },
    { id: 'integrations', label: 'Integrations', icon: Blocks, permission: 'integrations.view' },
  ] },
  { label: 'Security', items: [
    { id: 'security', label: 'Authentication & security', icon: ShieldCheck, permission: 'settings.view' },
    { id: 'audit', label: 'Audit', icon: ScrollText, permission: 'audit.view' },
  ] },
  { label: 'Developer', items: [{ id: 'developer', label: 'Developer', icon: Braces, permission: 'settings.view' }] },
  { label: 'Account', items: [{ id: 'billing', label: 'Billing / usage', icon: CreditCard, permission: 'billing.view' }] },
  { label: 'Customization', items: [{ id: 'branding', label: 'White label', icon: Palette, permission: 'branding.view' }] },
];

export function WorkspaceSettingsNavigation({ active, onSelect, permissions }: { active: SettingsSection; onSelect: (section: SettingsSection) => void; permissions: string[] }) {
  const allowed = new Set(permissions);
  return <nav className="workspace-console-nav" aria-label="Workspace settings">
    {groups.map((group) => {
      const items = group.items.filter((item) => !item.permission || allowed.has(item.permission));
      if (!items.length) return null;
      return <div key={group.label}><p>{group.label}</p>{items.map(({ id, label, icon: Icon }) =>
        <button type="button" key={id} className={active === id ? 'is-active' : ''} onClick={() => onSelect(id)}><Icon /><span>{label}</span></button>)}</div>;
    })}
    <p>Legacy</p><a href="/workspace"><KeyRound /><span>Original workspace console</span></a>
  </nav>;
}
