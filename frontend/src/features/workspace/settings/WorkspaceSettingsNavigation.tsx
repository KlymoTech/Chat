import { Bell, Blocks, Braces, Building2, CreditCard, KeyRound, Palette, Radio, ScrollText, ShieldCheck, UsersRound, UserRoundCog } from 'lucide-react';
import type { SettingsSection } from './workspaceSettings.api';

const groups: { label: string; items: { id: SettingsSection; label: string; icon: typeof Building2 }[] }[] = [
  { label: 'Workspace', items: [
    { id: 'general', label: 'General', icon: Building2 },
    { id: 'members', label: 'Members', icon: UsersRound },
    { id: 'roles', label: 'Roles & permissions', icon: UserRoundCog },
    { id: 'teams', label: 'Teams', icon: UsersRound },
  ] },
  { label: 'Communication', items: [
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'channels', label: 'Channels', icon: Radio },
    { id: 'integrations', label: 'Integrations', icon: Blocks },
  ] },
  { label: 'Security', items: [
    { id: 'security', label: 'Authentication & security', icon: ShieldCheck },
    { id: 'audit', label: 'Audit', icon: ScrollText },
  ] },
  { label: 'Developer', items: [{ id: 'developer', label: 'Developer', icon: Braces }] },
  { label: 'Account', items: [{ id: 'billing', label: 'Billing / usage', icon: CreditCard }] },
  { label: 'Customization', items: [{ id: 'branding', label: 'White label', icon: Palette }] },
];

export function WorkspaceSettingsNavigation({ active, onSelect }: { active: SettingsSection; onSelect: (section: SettingsSection) => void }) {
  return <nav className="workspace-console-nav" aria-label="Workspace settings">
    {groups.map((group) => <div key={group.label}><p>{group.label}</p>{group.items.map(({ id, label, icon: Icon }) =>
      <button type="button" key={id} className={active === id ? 'is-active' : ''} onClick={() => onSelect(id)}><Icon /><span>{label}</span></button>)}</div>)}
    <p>Legacy</p><a href="/workspace"><KeyRound /><span>Original workspace console</span></a>
  </nav>;
}
