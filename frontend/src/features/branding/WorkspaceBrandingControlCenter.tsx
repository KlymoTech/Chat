import { useMemo, useState } from 'react';
import { Badge, Button, Card, Field } from '@/components/ui';
import { useToast } from '@/components/providers';
import {
  workspaceSettingsApi,
  type ExtendedBranding,
  type WorkspaceSettingsBundle,
} from '@/features/workspace/settings/workspaceSettings.api';
import { BrandAuthenticationSettings } from './BrandAuthenticationSettings';
import { BrandDashboardSettings } from './BrandDashboardSettings';
import { BrandDomainsSettings } from './BrandDomainsSettings';
import { BrandEmailSettings } from './BrandEmailSettings';
import { BrandIdentitySettings } from './BrandIdentitySettings';
import { BrandThemeSettings } from './BrandThemeSettings';
import { BrandVersionsSettings } from './BrandVersionsSettings';
import { BrandWidgetSettings } from './BrandWidgetSettings';

type Surface = 'identity' | 'theme' | 'dashboard' | 'authentication' | 'email' | 'widget' | 'domains' | 'versions';
const surfaces: Surface[] = ['identity', 'theme', 'dashboard', 'authentication', 'email', 'widget', 'domains', 'versions'];

export function WorkspaceBrandingControlCenter({ bundle, onChange }: { bundle: WorkspaceSettingsBundle; onChange: (bundle: WorkspaceSettingsBundle) => void }) {
  const { pushToast } = useToast();
  const [surface, setSurface] = useState<Surface>('identity');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const draft = bundle.brandingDraft;
  const published = bundle.brandingPublished;
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(published), [draft, published]);

  function updateDraft(value: ExtendedBranding) {
    onChange({ ...bundle, brandingDraft: value, dashboard: value.dashboard });
  }
  async function saveDraft() {
    setBusy(true);
    try {
      const saved = await workspaceSettingsApi.saveBrandDraft(draft);
      onChange({ ...bundle, brandingDraft: saved, dashboard: saved.dashboard });
      pushToast('Brand draft saved');
    } catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Brand draft could not be saved', 'error'); }
    finally { setBusy(false); }
  }
  async function publish() {
    setBusy(true);
    try {
      await workspaceSettingsApi.saveBrandDraft(draft);
      const version = await workspaceSettingsApi.publishBrand(note);
      onChange({ ...bundle, brandingDraft: version.branding, brandingPublished: version.branding, dashboard: version.branding.dashboard, brandingVersions: [...bundle.brandingVersions, version].slice(-50) });
      setNote('');
      pushToast(`Brand version ${version.version} published`);
    } catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Brand could not be published', 'error'); }
    finally { setBusy(false); }
  }
  async function rollback(version: number) {
    setBusy(true);
    try {
      const created = await workspaceSettingsApi.rollbackBrand(version, `Rollback to version ${version}`);
      onChange({ ...bundle, brandingDraft: created.branding, brandingPublished: created.branding, dashboard: created.branding.dashboard, brandingVersions: [...bundle.brandingVersions, created].slice(-50) });
      pushToast(`Rollback published as version ${created.version}`);
    } catch (reason) { pushToast(reason instanceof Error ? reason.message : 'Rollback failed', 'error'); }
    finally { setBusy(false); }
  }

  return <div className="workspace-branding-settings">
    <Card className="workspace-panel"><div className="workspace-panel__body">
      <div className="page-heading page-heading--split"><div><h3>White-label control center</h3><p>Edit a private draft, preview it, validate it server-side, and publish an immutable version only when ready.</p></div><Badge tone={dirty ? 'warning' : 'success'}>{dirty ? 'Draft differs from published' : 'Published state'}</Badge></div>
      <div className="workspace-branding-tabs">{surfaces.map((item) => <Button key={item} type="button" variant={surface === item ? 'primary' : 'secondary'} onClick={() => setSurface(item)}>{item}</Button>)}</div>
      <div className="workspace-panel__actions"><Button type="button" variant="secondary" onClick={() => setPreview((value) => !value)}>{preview ? 'Hide preview' : 'Preview draft'}</Button></div>
    </div></Card>

    {preview ? <BrandPreview value={draft} /> : null}
    {surface === 'identity' ? <BrandIdentitySettings value={draft} onChange={updateDraft} /> : null}
    {surface === 'theme' ? <BrandThemeSettings value={draft} onChange={updateDraft} /> : null}
    {surface === 'dashboard' ? <BrandDashboardSettings value={draft.dashboard} onChange={(dashboard) => updateDraft({ ...draft, dashboard })} /> : null}
    {surface === 'authentication' ? <BrandAuthenticationSettings value={draft} onChange={updateDraft} /> : null}
    {surface === 'email' ? <BrandEmailSettings value={draft} onChange={updateDraft} /> : null}
    {surface === 'widget' ? <BrandWidgetSettings value={draft} onChange={updateDraft} /> : null}
    {surface === 'domains' ? <BrandDomainsSettings bundle={bundle} onChange={onChange} /> : null}
    {surface === 'versions' ? <BrandVersionsSettings versions={bundle.brandingVersions} busy={busy} onRollback={(version) => void rollback(version)} /> : null}

    {!['domains', 'versions'].includes(surface) ? <Card className="workspace-panel"><div className="workspace-panel__body">
      <Field label="Publication note"><input value={note} maxLength={500} placeholder="Describe this production brand change" onChange={(event) => setNote(event.target.value)} /></Field>
      <div className="workspace-panel__actions"><Button type="button" variant="secondary" disabled={busy} onClick={() => void saveDraft()}>Save draft</Button><Button type="button" disabled={busy || !dirty} onClick={() => { if (window.confirm('Publish this branding draft to production?')) void publish(); }}>Publish brand</Button></div>
    </div></Card> : null}
  </div>;
}

function BrandPreview({ value }: { value: ExtendedBranding }) {
  return <Card className="workspace-panel"><div className="workspace-panel__body" style={{ background: value.colors.background, color: value.colors.textPrimary, borderRadius: value.appearance.borderRadius, fontFamily: value.typography.bodyFont }}>
    <div className="page-heading page-heading--split"><div>{value.identity.logoDataUrl ? <img src={value.identity.logoDataUrl} alt="Draft logo" style={{ maxHeight: 42, maxWidth: 180 }} /> : null}<h3 style={{ fontFamily: value.typography.headingFont }}>{value.identity.companyName || 'Company name'}</h3><p style={{ color: value.colors.textSecondary }}>{value.authentication.loginDescription || 'Published surfaces will use these design tokens.'}</p></div><span style={{ background: value.identity.primaryColor, color: value.colors.sidebarText, padding: '8px 12px', borderRadius: value.appearance.borderRadius }}>Primary action</span></div>
    <div style={{ padding: 16, background: value.colors.surface, border: `1px solid ${value.colors.border}`, borderRadius: value.appearance.borderRadius }}><strong>Dashboard card</strong><p>Widgets configured: {value.dashboard.widgets.filter((widget) => widget.visible).length}</p></div>
  </div></Card>;
}
